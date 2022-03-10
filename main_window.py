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
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle('Connect to IP address')
        layoutv = QVBoxLayout()
        self.setLayout(layoutv)
        self.ip_address = QLineEdit()
        self.ip_address.setInputMask('000.000.000.000;_')
        layoutv.addWidget(self.ip_address)

        buttons = (QDialogButtonBox.StandardButton.Open |
                   QDialogButtonBox.StandardButton.Cancel)
        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layoutv.addWidget(button_box)

    def get_ip_address(self):
        return self.ip_address.text()

class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()

        self.app = app

        self.resource_manager = pyvisa.ResourceManager()

        self.resource_list = []
        self.device_list = []
        self.config_widget_list = []

        self.setWindowTitle(f'Siglent Instrument Controller')

        layoutv = QVBoxLayout()
        self.setLayout(layoutv)
        layoutv.setSpacing(0)
        layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_configure = self._menubar.addMenu('&Device')
        action = QAction('&Open IP address...', self)
        action.triggered.connect(self._menu_do_open_ip)
        self._menubar_configure.addAction(action)
        action = QAction('E&xit', self)
        action.triggered.connect(self._menu_do_exit)
        self._menubar_configure.addAction(action)

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About', self)
        action.triggered.connect(self._menu_do_about)
        self._menubar_help.addAction(action)

        layoutv.addWidget(self._menubar)
        central_widget = QWidget()
        layoutv.addWidget(central_widget)
        # self._statusbar = QStatusBar()
        # self._statusbar.setSizeGripEnabled(False)
        # layoutv.addWidget(self._statusbar)

        self.set_heartbeat_timer(1000)

    def set_heartbeat_timer(self, timeout):
        timer = QTimer(self.app)
        timer.timeout.connect(self.update)
        timer.start(timeout)

    def update(self):
        for config_widget in self.config_widget_list:
            config_widget.update_measurements()

    def _menu_do_about(self):
        """Show the About box."""
        msg = """Siglent Instrument Controller.

Copyright 2022, Robert S. French"""
        QMessageBox.about(self, 'About', msg)

    def _menu_do_open_ip(self):
        dialog = IPAddressDialog(self)
        if not dialog.exec():
            return
        ip_address = dialog.get_ip_address()
        # Reformat into a standard form
        ip_address = '.'.join([('%d' % int(x)) for x in ip_address.split('.')])
        resource_name = f'TCPIP::{ip_address}'

        if resource_name in self.resource_list:
            QMessageBox.warning(self, 'Error',
                                      f'Resource "{resource_name}" is already open!')
            return

        inst = device.create_device(self.resource_manager, resource_name)
        inst.set_debug(True)
        inst.connect()
        config_widget = inst.configure_widget()
        config_widget.show()
        self.resource_list.append(resource_name)
        self.device_list.append(inst)
        self.config_widget_list.append(config_widget)

    def _menu_do_exit(self):
        sys.exit(0)
