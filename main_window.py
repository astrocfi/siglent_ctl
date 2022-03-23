################################################################################
# main_window.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains the main window displayed when the program is first run.
#
# Copyright 2022 Robert S. French (rfrench@rfrench.org)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
################################################################################

import math
import sys
import time

from PyQt6.QtWidgets import (QDialog,
                             QDialogButtonBox,
                             QDoubleSpinBox,
                             QGroupBox,
                             QHBoxLayout,
                             QLabel,
                             QLayout,
                             QLineEdit,
                             QMenuBar,
                             QMessageBox,
                             QPushButton,
                             QVBoxLayout,
                             QWidget,
                            )
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QTimer

import numpy as np
import pyvisa

import device
from plot_xy_window import PlotXYWindow


class IPAddressDialog(QDialog):
    """Custom dialog that accepts and validates an IP address."""
    def __init__(self, parent=None):
        super().__init__(parent)

        layoutv = QVBoxLayout()
        self.setLayout(layoutv)
        self._ip_address = QLineEdit()
        self._ip_address.setInputMask('000.000.000.000;_')
        self._ip_address.textChanged.connect(self._validator)
        layoutv.addWidget(self._ip_address)

        buttons = (QDialogButtonBox.StandardButton.Open |
                   QDialogButtonBox.StandardButton.Cancel)
        self._button_box = QDialogButtonBox(buttons)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        self._button_box.button(
            QDialogButtonBox.StandardButton.Open).setEnabled(False)
        layoutv.addWidget(self._button_box)

    def _validator(self):
        val = self._ip_address.text()
        octets = val.split('.')
        if len(octets) == 4:
            for octet in octets:
                try:
                    octet_int = int(octet)
                except ValueError:
                    break
                if not (0 <= octet_int <= 255):
                    break
            else: # Good address
                self._button_box.button(
                    QDialogButtonBox.StandardButton.Open).setEnabled(True)
                return
        self._button_box.button(
            QDialogButtonBox.StandardButton.Open).setEnabled(False)

    def get_ip_address(self):
        """Return the entered IP address."""
        return self._ip_address.text()


class MainWindow(QWidget):
    """The main window of the entire application."""
    def __init__(self, app):
        super().__init__()
        self.setWindowTitle('Siglent Instrument Controller')

        self.app = app
        self.resource_manager = pyvisa.ResourceManager('@py')

        # Tuple of (resource_name,
        #           instrument class instance,
        #           config widget class instance)
        self._open_resources = []

        self._measurement_times = []
        self._measurements = {}
        self._measurement_units = {}
        self._measurement_names = {}

        self._max_recent_resources = 4
        self._recent_resources = [] # List of resource names
        self._recent_resources.append('TCPIP::192.168.0.63')

        self._plot_window_widgets = []

        self._paused = True

        ### Layout the widgets

        layouttopv = QVBoxLayout()
        layouttopv.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layouttopv)
        layouttopv.setSpacing(0)
        layouttopv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ### Create the menu bar

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_device = self._menubar.addMenu('&Device')
        action = QAction('&Open IP address...', self)
        action.triggered.connect(self._menu_do_open_ip)
        self._menubar_device.addAction(action)
        action = QAction('E&xit', self)
        action.triggered.connect(self._menu_do_exit)
        self._menubar_device.addAction(action)
        self._menubar_device.addSeparator()
        # Create empty actions for the recent resource list, to be filled in
        # later
        self._menubar_device_recent_actions = []
        for num in range(self._max_recent_resources):
            action = QAction(str(num), self)
            action.resource_number = num
            action.triggered.connect(self._menu_do_open_recent)
            action.setVisible(False)
            self._menubar_device.addAction(action)
            self._menubar_device_recent_actions.append(action)
        self._refresh_menubar_device_recent_resources()

        self._menubar_device = self._menubar.addMenu('&Plot')
        action = QAction('New &X/Y Plot', self)
        action.triggered.connect(self._menu_do_new_xy_plot)
        self._menubar_device.addAction(action)

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About', self)
        action.triggered.connect(self._menu_do_about)
        self._menubar_help.addAction(action)

        layouttopv.addWidget(self._menubar)

        layoutv = QVBoxLayout()
        layoutv.setContentsMargins(11, 11, 11, 11)
        layouttopv.addLayout(layoutv)
        layouth = QHBoxLayout()
        layoutv.addLayout(layouth)

        frame = QGroupBox('Measurement')
        frame.setStyleSheet("""QGroupBox { min-width: 11em; max-width: 11em; }""")
        layoutv2 = QVBoxLayout(frame)
        layouth.addWidget(frame)

        layouth2 = QHBoxLayout()
        layoutv2.addLayout(layouth2)
        layouth2.addWidget(QLabel('Interval:'))
        input = QDoubleSpinBox()
        layouth2.addWidget(input)
        input.setAlignment(Qt.AlignmentFlag.AlignRight)
        input.setDecimals(1)
        input.setRange(0.5, 60)
        input.setSuffix(' s')
        input.setValue(1)
        input.setSingleStep(0.5)
        input.editingFinished.connect(self._on_interval_changed)
        layouth2.addWidget(input)
        layouth2.addStretch()

        layouth2 = QHBoxLayout()
        layoutv2.addLayout(layouth2)
        button = QPushButton('Erase All')
        layouth2.addWidget(button)
        button.clicked.connect(self._on_erase_all)
        button = QPushButton()
        self._widget_pause_go = button
        layouth2.addWidget(button)
        button.clicked.connect(self._on_pause_go)
        layouth2.addStretch()

        self._widget_measurement_started = QLabel('Started: N/A')
        layoutv2.addWidget(self._widget_measurement_started)
        self._widget_measurement_elapsed = QLabel('Elapsed: N/A')
        layoutv2.addWidget(self._widget_measurement_elapsed)
        self._widget_measurement_points = QLabel('# Data Points: 0')
        layoutv2.addWidget(self._widget_measurement_points)

        self._update_pause_go_button()

        self._heartbeat_timer = QTimer(self.app)
        self._heartbeat_timer.timeout.connect(self._heartbeat_update)
        self._heartbeat_timer.setInterval(1000)
        self._heartbeat_timer.start()

        self._measurement_timer = QTimer(self.app)
        self._measurement_timer.timeout.connect(self._update)
        self._measurement_timer.setInterval(1000)
        self._measurement_timer.start()

    def _on_interval_changed(self):
        """Handle a new value in the Measurement Interval input."""
        input = self.sender()
        self._measurement_timer.setInterval(int(input.value() * 1000))

    def _on_erase_all(self):
        """Handle Erase All button."""
        self._measurement_times = []
        self._measurements = {}
        self._measurement_units = {}
        self._measurement_names = {}
        self._update()

    def _on_pause_go(self):
        """Handle Pause/Go button."""
        self._paused = not self._paused
        self._update_pause_go_button()

    def _update_pause_go_button(self):
        if self._paused:
            self._widget_pause_go.setText('\u23F5 Record')
            self._widget_pause_go.setStyleSheet('background-color: #80ff40;')
        else:
            self._widget_pause_go.setText('\u23F8 Pause')
            self._widget_pause_go.setStyleSheet('background-color: #ff8080;')

    def closeEvent(self, event):
        # Close all the sub-windows, allowing them to shut down peacefully
        for resource_name, inst, config_widget in self._open_resources:
            config_widget.close()
        for widget in self._plot_window_widgets:
            widget.close()

    def _refresh_menubar_device_recent_resources(self):
        """Update the text in the Recent Resources actions."""
        for num in range(self._max_recent_resources):
            action = self._menubar_device_recent_actions[num]
            if num < len(self._recent_resources):
                resource_name = self._recent_resources[num]
                action.setText(f'&{num+1} {resource_name}')
                action.setVisible(True)
                if resource_name in [x[0] for x in self._open_resources]:
                    action.setEnabled(False)
                else:
                    action.setEnabled(True)
            else:
                action.setVisible(False)

    @staticmethod
    def _time_to_hms(t):
        m, s = divmod(t, 60)
        h, m = divmod(m, 60)
        return '%02d:%02d:%02d' % (h, m, s)

    def _heartbeat_update(self):
        """Regular updates like the elapsed time."""
        if len(self._measurement_times) == 0:
            msg1 = 'Started: N/A'
            msg2 = 'Elapsed: N/A'
        else:
            msg1 = ('Started: ' +
                    time.strftime('%Y %b %d %H:%M:%S',
                                  time.localtime(self._measurement_times[0])))
            msg2 = 'Elapsed: ' + self._time_to_hms(self._measurement_times[-1] -
                                                   self._measurement_times[0])
        self._widget_measurement_started.setText(msg1)
        self._widget_measurement_elapsed.setText(msg2)
        npts = len(self._measurement_times)
        self._widget_measurement_points.setText(f'# Data Points: {npts}')

    def _update(self):
        """Query all instruments and update all measurements and display widgets."""
        # Although technically each measurement takes place at a different time,
        # it's important that we treat each measurement group as being at a single
        # time so we can match up measurements in X/Y plots and file saving.
        if len(self._open_resources) == 0:
            return
        for resource_name, inst, config_widget in self._open_resources:
            if config_widget is not None:
                measurements = config_widget.update_measurements()
                if not self._paused:
                    for meas_key, meas in measurements.items():
                        name = meas['name']
                        key = (inst.name, name)
                        if key not in self._measurements:
                            self._measurements[key] = ([np.nan] *
                                                       len(self._measurement_times))
                            self._measurement_units[key] = meas['unit']
                            self._measurement_names[key] = f'{inst.name}: {name}'
                        val = meas['val']
                        if val is None:
                            val = math.nan
                        self._measurements[key].append(val)
        if not self._paused:
            cur_time = time.time()
            self._measurement_times.append(cur_time)
        for plot_widget in self._plot_window_widgets:
            plot_widget.update()

    def _menu_do_about(self):
        """Show the About box."""
        msg = """Siglent Instrument Controller.

Supported instruments:
SDL1020X, SDL1020X-E, SDL1030X, SDL1030X-E

Copyright 2022, Robert S. French"""
        QMessageBox.about(self, 'About', msg)

    def _menu_do_open_ip(self):
        """Open a device based on an entered IP address."""
        dialog = IPAddressDialog(self)
        dialog.setWindowTitle('Connect to Instrument Using IP Address')
        if not dialog.exec():
            return
        ip_address = dialog.get_ip_address()
        # Reformat into a standard form, removing any zeroes
        ip_address = '.'.join([('%d' % int(x)) for x in ip_address.split('.')])
        self._open_resource(f'TCPIP::{ip_address}')

    def _menu_do_open_recent(self, idx):
        """Open a resource from the Recent Resource list."""
        action = self.sender()
        self._open_resource(self._recent_resources[action.resource_number])

    def _open_resource(self, resource_name):
        """Open a resource by name."""
        if resource_name in [x[0] for x in self._open_resources]:
            QMessageBox.critical(self, 'Error',
                                 f'Resource "{resource_name}" is already open!')
            return

        # Update the recent resource list and put this resource on top
        try:
            idx = self._recent_resources.index(resource_name)
        except ValueError:
            pass
        else:
            del self._recent_resources[idx]
        self._recent_resources.insert(0, resource_name)
        self._recent_resources = self._recent_resources[:self._max_recent_resources]

        # Create the device
        try:
            inst = device.create_device(self.resource_manager, resource_name)
        except pyvisa.errors.VisaIOError as ex:
            QMessageBox.critical(self, 'Error',
                                 f'Failed to open "{resource_name}":\n{ex.description}')
            return
        except device.UnknownInstrumentType as ex:
            QMessageBox.critical(self, 'Error',
                                 f'Unknown instrument type "{ex.args[0]}"')
            # inst = None
            return

        config_widget = None
        if inst is not None:
            # inst.set_debug(True)
            inst.connect()
            config_widget = inst.configure_widget(self)
            config_widget.show()
        self._open_resources.append((resource_name, inst, config_widget))
        self._refresh_menubar_device_recent_resources()

        num_existing = len(self._measurement_times)
        measurements = config_widget.update_measurements(read_inst=False)
        for meas_key, meas in measurements.items():
            name = meas['name']
            key = (inst.name, name)
            self._measurements[key] = [None] * num_existing
            self._measurement_units[key] = meas['unit']
            self._measurement_names[key] = f'{inst.name}: {name}'
        for plot_widget in self._plot_window_widgets:
            plot_widget.measurements_changed()

    def _menu_do_exit(self):
        """Perform the menu exit command."""
        sys.exit(0)

    def _menu_do_new_xy_plot(self):
        """Perform the menu New XY Plot command."""
        w = PlotXYWindow(self)
        w.show()
        self._plot_window_widgets.append(w)

    def _device_window_closed(self, inst):
        """Update internal state when one of the configuration widgets is closed."""
        idx = [x[0] for x in self._open_resources].index(inst.resource_name)
        del self._open_resources[idx]
        self._refresh_menubar_device_recent_resources()
        for key in list(self._measurements): # Need list because we're modifying keys
            if key[0] == inst.name:
                del self._measurements[key]
                del self._measurement_names[key]
                del self._measurement_units[key]

        for plot_widget in self._plot_window_widgets:
            plot_widget.measurements_changed()

# NEED A WAY TO QUERY MEASUREMENTS WITHOUT TRIGGERING AN INST READ
