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

import sys
import time

from PyQt6.QtWidgets import (QWidget,
                             QApplication,
                             QMenuBar, QMenu, QStatusBar,
                             QDialog,
                             QDialogButtonBox,
                             QLabel,
                             QLineEdit,
                             QMessageBox,
                             QPushButton,
                             QRadioButton,
                             QAbstractSpinBox,
                             QDoubleSpinBox,
                             QSpinBox,
                             QButtonGroup,
                             QLayout,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QVBoxLayout,
                             QPlainTextEdit)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import *

import pyvisa

import device


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

        self.app = app

        self.resource_manager = pyvisa.ResourceManager()

        # Tuple of (resource_name, inst class, inst config class)
        self._open_resources = []

        self._max_recent_resources = 4
        self._recent_resources = [] # List of resource names

        self._recent_resources.append('TCPIP::192.168.0.63')

        self.setWindowTitle(f'Siglent Instrument Controller')

        ### Layout the widgets

        layoutv = QVBoxLayout()
        self.setLayout(layoutv)
        layoutv.setSpacing(0)
        layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

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

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About', self)
        action.triggered.connect(self._menu_do_about)
        self._menubar_help.addAction(action)

        layoutv.addWidget(self._menubar)
        central_widget = QWidget()
        layoutv.addWidget(central_widget)

        self._heartbeat_timer = QTimer(self.app)
        self._heartbeat_timer.timeout.connect(self.update)
        self._heartbeat_timer.start()
        self.set_heartbeat_timer(1000)

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

    def set_heartbeat_timer(self, timeout):
        """Set the heartbeat timer to the given interval in ms."""
        self._heartbeat_timer.setInterval(timeout)

    def update(self):
        """Query all instruments and update all measurements and display widgets."""
        for _, _, config_widget in self._open_resources:
            if config_widget is not None:
                config_widget.update_measurements()

    def _menu_do_about(self):
        """Show the About box."""
        msg = """Siglent Instrument Controller.

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
            inst = None # XXX

        config_widget = None
        if inst is not None:
            inst.set_debug(True)
            inst.connect()
            config_widget = inst.configure_widget(self)
            config_widget.show()
        self._open_resources.append((resource_name, inst, config_widget))
        self._refresh_menubar_device_recent_resources()

    def _menu_do_exit(self):
        """Perform the menu exit command."""
        sys.exit(0)

    def _device_window_closed(self, resource_name):
        """Update internal state when one of the configuration widgets is closed."""
        idx = [x[0] for x in self._open_resources].index(resource_name)
        del self._open_resources[idx]
        self._refresh_menubar_device_recent_resources()
