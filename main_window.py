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
import platform
import sys
import time

from PyQt6.QtWidgets import (QButtonGroup,
                             QComboBox,
                             QDialog,
                             QDialogButtonBox,
                             QDoubleSpinBox,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QLabel,
                             QLayout,
                             QLineEdit,
                             QMenuBar,
                             QMessageBox,
                             QPushButton,
                             QRadioButton,
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
        layouth = QHBoxLayout()
        layoutv.addSpacing(50)
        layoutv.addLayout(layouth)
        layoutv.addSpacing(50)
        layouth.addSpacing(50)
        layouth.addWidget(QLabel('IP Address:'))
        self._ip_address = QLineEdit()
        self._ip_address.setStyleSheet('max-width: 7.6em; font-family: "Courier New";')
        self._ip_address.setInputMask('000.000.000.000;_')
        self._ip_address.textChanged.connect(self._validator)
        layouth.addWidget(self._ip_address)
        layouth.addSpacing(50)

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
    def __init__(self, app, argv):
        super().__init__()
        self.setWindowTitle('Siglent Instrument Controller')

        match platform.system():
            case 'Linux':
                self._style_env = 'linux'
            case 'Windows':
                self._style_env = 'windows'
            case 'Darwin':
                self._style_env = 'windows'

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

        self._plot_window_widgets = []

        self._acquisition_mode = 'Manual'
        self._acquisition_ready = True
        self._user_paused = False
        self._measurement_state_source = None
        self._measurement_value_source = None
        self._measurement_value_op = '>'
        self._measurement_value_comp = 0

        self._widget_registry = {}

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

        frame = QGroupBox('Measurement and Acquisition')
        frame.setStyleSheet("""QGroupBox { min-width: 20em; max-width: 20em; }""")
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
        button = QPushButton('\u23F5 Record')
        ss = """min-width: 4.5em; max-width: 4.5em; min-height: 1.5em; max-height: 1.5em;
                border-radius: 0.5em; border: 2px solid black; font-weight: bold;
                background-color: #80ff40;"""
        button.setStyleSheet(ss)
        self._widget_registry['GoButton'] = button
        button.clicked.connect(self._on_click_go)
        layouth2.addWidget(button)
        button = QPushButton('\u23F8 Pause')
        ss = """min-width: 4.5em; max-width: 4.5em; min-height: 1.5em; max-height: 1.5em;
                border-radius: 0.5em; border: 2px solid black; font-weight: bold;
                background-color: #ff8080;"""
        button.setStyleSheet(ss)
        self._widget_registry['PauseButton'] = button
        button.clicked.connect(self._on_click_pause)
        layouth2.addWidget(button)
        button = QPushButton('\u26A0 Erase All Data \u26A0')
        ss = """background: black; color: red;"""
        button.setStyleSheet(ss)
        layouth2.addStretch()
        layouth2.addWidget(button)
        button.clicked.connect(self._on_erase_all)

        layoutg = QGridLayout()
        layoutv2.addLayout(layoutg)
        bg = QButtonGroup(layoutg)

        rb = QRadioButton('Manual')
        layoutg.addWidget(rb, 0, 0)
        bg.addButton(rb)
        rb.setChecked(True)
        rb.wid = 'Manual'
        rb.toggled.connect(self._on_click_acquisition_mode)

        rb = QRadioButton('Instrument State:')
        layoutg.addWidget(rb, 1, 0)
        bg.addButton(rb)
        rb.setChecked(False)
        rb.wid = 'State'
        rb.toggled.connect(self._on_click_acquisition_mode)
        layouth = QHBoxLayout()
        layoutg.addLayout(layouth, 1, 1)
        combo = QComboBox()
        layouth.addWidget(combo)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.activated.connect(self._on_select_meas_state_source)
        self._widget_registry['InstrumentStateCombo'] = combo
        layouth.addStretch()

        rb = QRadioButton('Measurement Value:')
        layoutg.addWidget(rb, 2, 0)
        bg.addButton(rb)
        rb.setChecked(False)
        rb.wid = 'Value'
        rb.toggled.connect(self._on_click_acquisition_mode)
        layouth = QHBoxLayout()
        layoutg.addLayout(layouth, 2, 1)
        combo = QComboBox()
        layouth.addWidget(combo)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.activated.connect(self._on_select_meas_value_source)
        self._widget_registry['MeasurementValueSourceCombo'] = combo
        layouth.addStretch()

        layouth = QHBoxLayout()
        layoutg.addLayout(layouth, 3, 1)
        combo = QComboBox()
        combo.addItem('Less than', userData='<')
        combo.addItem('Less than or equal', userData='<=')
        combo.addItem('Greater than', userData='>')
        combo.addItem('Greater than or equal', userData='<')
        layouth.addWidget(combo)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.activated.connect(self._on_select_meas_value_op)
        self._widget_registry['MeasurementValueOperatorCombo'] = combo
        layouth.addStretch()

        layouth = QHBoxLayout()
        layoutg.addLayout(layouth, 4, 1)
        input = QDoubleSpinBox()
        input.setAlignment(Qt.AlignmentFlag.AlignRight)
        layouth.addWidget(input)
        input.setRange(-1000000, 1000000)
        input.setSingleStep(1)
        input.editingFinished.connect(self._on_value_changed_meas_comp)
        self._widget_registry['MeasurementValueComp'] = input
        layouth.addStretch()

        layouth = QHBoxLayout()
        layoutv2.addLayout(layouth)
        layoutv3 = QVBoxLayout()
        layouth.addLayout(layoutv3)
        self._widget_measurement_started = QLabel('Started: N/A')
        layoutv3.addWidget(self._widget_measurement_started)
        self._widget_measurement_elapsed = QLabel('Elapsed: N/A')
        layoutv3.addWidget(self._widget_measurement_elapsed)
        self._widget_measurement_points = QLabel('# Data Points: 0')
        layoutv3.addWidget(self._widget_measurement_points)
        layouth.addStretch()
        layoutv3 = QVBoxLayout()
        layouth.addLayout(layoutv3)
        layoutv3.addStretch()
        label = QLabel('')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layoutv3.addWidget(label)
        self._widget_registry['AcquisitionIndicator'] = label

        self._update_pause_go_buttons()
        self._update_acquisition_indicator()

        self._heartbeat_timer = QTimer(self.app)
        self._heartbeat_timer.timeout.connect(self._heartbeat_update)
        self._heartbeat_timer.setInterval(1000)
        self._heartbeat_timer.start()

        self._measurement_timer = QTimer(self.app)
        self._measurement_timer.timeout.connect(self._update)
        self._measurement_timer.setInterval(1000)
        self._measurement_timer.start()

        self.show()

        if len(argv) == 1:
            self._menu_do_open_ip()
        else:
            for ip_address in argv[1:]:
                self._open_ip(ip_address)

    def _on_interval_changed(self):
        """Handle a new value in the Measurement Interval input."""
        input = self.sender()
        self._measurement_timer.setInterval(int(input.value() * 1000))

    def _on_erase_all(self):
        """Handle Erase All button."""
        self._measurement_times = []
        for key in self._measurements:
            self._measurements[key] = []
        self._update()

    def _on_click_acquisition_mode(self):
        """Handle Measurement Mode radio buttons."""
        rb = self.sender()
        if not rb.isChecked():
            return
        self._acquisition_mode = rb.wid
        self._check_acquisition_ready()
        self._update_widgets()

    def _on_select_meas_state_source(self, sel):
        """Handle Instrument State source selection."""
        combo = self.sender()
        self._measurement_state_source = combo.itemData(sel)
        self._check_acquisition_ready()
        self._update_widgets()
        print('S', self._measurement_state_source, self._measurement_value_source,
              self._measurement_value_op, self._measurement_value_comp)

    def _on_select_meas_value_source(self, sel):
        """Handle Measurement Value source selection."""
        combo = self.sender()
        self._measurement_value_source = combo.itemData(sel)
        self._check_acquisition_ready()
        self._update_widgets()
        print('S', self._measurement_state_source, self._measurement_value_source,
              self._measurement_value_op, self._measurement_value_comp)

    def _on_select_meas_value_op(self, sel):
        """Handle Measurement Value operator selection."""
        combo = self.sender()
        self._measurement_value_op = combo.itemData(sel)
        self._check_acquisition_ready()
        self._update_widgets()
        print('S', self._measurement_state_source, self._measurement_value_source,
              self._measurement_value_op, self._measurement_value_comp)

    def _on_value_changed_meas_comp(self):
        """Handle Measurement Value comparison value changed."""
        input = self.sender()
        self._measurement_value_comp = input.value()
        self._check_acquisition_ready()
        self._update_widgets()
        print('S', self._measurement_state_source, self._measurement_value_source,
              self._measurement_value_op, self._measurement_value_comp)

    def _on_click_go(self):
        """Handle Go button."""
        self._user_paused = False
        self._update_widgets()

    def _on_click_pause(self):
        """Handle Go button."""
        self._user_paused = True
        self._update_widgets()

    def closeEvent(self, event):
        # Close all the sub-windows, allowing them to shut down peacefully
        # Closing a config window also removes it from the open resources list,
        # so we have to make a copy of the list before iterating.
        for resource_name, inst, config_widget in self._open_resources[:]:
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

    def _check_acquisition_ready(self):
        """Check to see if the current acquisition trigger is met."""
        match self._acquisition_mode:
            case 'Manual':
                self._acquisition_ready = True
                return
            case 'State':
                for resource_name, inst, config_widget in self._open_resources:
                    if config_widget is not None:
                        for index, trigger in enumerate(
                                config_widget.get_triggers().values()):
                            key = (inst.name, trigger['name'])
                            print(key, self._measurement_state_source)
                            if key == self._measurement_state_source:
                                self._acquisition_ready = trigger['val']
                                return
                assert False, 'State source no longer in open resources'

    def _update(self):
        """Query all instruments and update all measurements and display widgets."""
        # Although technically each measurement takes place at a different time,
        # it's important that we treat each measurement group as being at a single
        # time so we can match up measurements in X/Y plots and file saving.
        if len(self._open_resources) == 0:
            return
        # First update all the cached measurements and config widget displays
        for resource_name, inst, config_widget in self._open_resources:
            if config_widget is not None:
                config_widget.update_measurements_and_triggers()
        # Check for the current trigger condition
        self._check_acquisition_ready()
        self._update_acquisition_indicator()
        if not self._acquisition_ready:
            return
        # Now go through and read all the cached measurements
        if self._user_paused:
            return
        cur_time = time.time()
        self._measurement_times.append(cur_time)
        for resource_name, inst, config_widget in self._open_resources:
            if config_widget is not None:
                measurements = config_widget.get_measurements()
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
        self._open_ip(ip_address)

    def _menu_do_open_recent(self, idx):
        """Open a resource from the Recent Resource list."""
        action = self.sender()
        self._open_resource(self._recent_resources[action.resource_number])

    def _open_ip(self, ip_address):
        """Open a device based on the given IP address."""
        # Reformat into a standard form, removing any zeroes
        ip_address = '.'.join([('%d' % int(x)) for x in ip_address.split('.')])
        self._open_resource(f'TCPIP::{ip_address}')

    def _open_resource(self, resource_name):
        """Open a resource by name."""
        if resource_name in [x[0] for x in self._open_resources]:
            QMessageBox.critical(self, 'Error',
                                 f'Resource "{resource_name}" is already open!')
            return

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
            return

        config_widget = None
        inst.set_debug(True)
        inst.connect()
        config_widget = inst.configure_widget(self)
        config_widget.show()
        self._open_resources.append((resource_name, inst, config_widget))

        # Update the recent resource list and put this resource on top
        try:
            idx = self._recent_resources.index(resource_name)
        except ValueError:
            pass
        else:
            del self._recent_resources[idx]
        self._recent_resources.insert(0, resource_name)
        self._recent_resources = self._recent_resources[:self._max_recent_resources]
        self._refresh_menubar_device_recent_resources()

        # Update the measurement list with newly available measurements
        num_existing = len(self._measurement_times)
        measurements, _ = config_widget.update_measurements_and_triggers(read_inst=False)
        for meas_key, meas in measurements.items():
            name = meas['name']
            key = (inst.name, name)
            self._measurements[key] = [None] * num_existing
            self._measurement_units[key] = meas['unit']
            self._measurement_names[key] = f'{inst.name}: {name}'
        for plot_widget in self._plot_window_widgets:
            plot_widget.measurements_changed()

        self._update_widgets()

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

        self._update_widgets()

    def _update_widgets(self):
        """Update our widgets with current information."""
        state_combo = self._widget_registry['InstrumentStateCombo']
        state_combo.clear()
        val_src_combo = self._widget_registry['MeasurementValueSourceCombo']
        val_src_combo.clear()
        val_op_combo = self._widget_registry['MeasurementValueOperatorCombo']
        val_comp = self._widget_registry['MeasurementValueComp']
        trigger_found = 0
        val_src_found = 0
        if len(self._open_resources) == 0:
            state_combo.setEnabled(False)
            val_src_combo.setEnabled(False)
            val_op_combo.setEnabled(False)
            val_comp.setEnabled(False)
            self._measurement_state_source = None
            self._measurement_value_source = None
            return
        trigger_index = 0
        measurement_index = 0
        for resource_name, inst, config_widget in self._open_resources:
            if config_widget is not None:
                for trigger in config_widget.get_triggers().values():
                    trig_name = trigger['name']
                    name = f'{inst.name}: {trig_name}'
                    key = (inst.name, trig_name)
                    state_combo.addItem(name, userData=key)
                    if self._measurement_state_source is None:
                        self._measurement_state_source = key
                    if key == self._measurement_state_source:
                        trigger_found = trigger_index
                    trigger_index += 1
                for measurement in config_widget.get_measurements().values():
                    meas_name = measurement['name']
                    name = f'{inst.name}: {meas_name}'
                    key = (inst.name, meas_name)
                    val_src_combo.addItem(name, userData=key)
                    if self._measurement_value_source is None:
                        self._measurement_value_source = key
                    if key == self._measurement_value_source:
                        val_src_found = measurement_index
                    measurement_index += 1
        print('Trigger', trigger_found)
        state_combo.setCurrentIndex(trigger_found)
        print('Val src', val_src_found)
        val_src_combo.setCurrentIndex(val_src_found)

        val_op_combo.setCurrentIndex(val_op_combo.findData(self._measurement_value_op))
        val_comp.setValue(self._measurement_value_comp)

        state_combo.setEnabled(True)
        val_src_combo.setEnabled(True)
        val_op_combo.setEnabled(True)
        val_comp.setEnabled(True)

        print('U', self._measurement_state_source, self._measurement_value_source,
              self._measurement_value_op, self._measurement_value_comp)

        self._update_pause_go_buttons()
        self._update_acquisition_indicator()

    def _update_pause_go_buttons(self):
        go_button = self._widget_registry['GoButton']
        pause_button = self._widget_registry['PauseButton']
        if self._user_paused:
            go_button.setEnabled(True)
            pause_button.setEnabled(False)
        else:
            go_button.setEnabled(False)
            pause_button.setEnabled(True)

    def _update_acquisition_indicator(self):
        label = self._widget_registry['AcquisitionIndicator']
        if self._acquisition_mode == 'Manual':
            label.setText('Manual')
            color = '#000000'
        else:
            if self._acquisition_ready:
                color = '#b00000'
                label.setText('Acquiring')
            else:
                color = '#00b000'
                label.setText('Waiting')
        ss = f"""min-width: 4em; max-width: 4em; min-height: 1.5em; max-height: 1.5em;
                 border: 2px solid black;
                 text-align: center;
                 font-weight: bold; font-size: 18px;
                 background-color: #c0c0c0; color: {color};"""
        label.setStyleSheet(ss)
