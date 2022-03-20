################################################################################
# device/config_widget_base.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains the parent class for all instrument configuration widgets to
# provide utility functions and a consistent look and feel.
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

from PyQt6.QtWidgets import (QDialog,
                             QLayout,
                             QMenuBar,
                             QPlainTextEdit,
                             QStatusBar,
                             QVBoxLayout,
                             QWidget)
from PyQt6.QtGui import QAction


class ConfigureWidgetBase(QWidget):
    def __init__(self, main_window, instrument):
        super().__init__()
        self._main_window = main_window
        self._inst = instrument
        self._param_state = {}
        self._widget_registry = {}
        self._statusbar = None
        self._init_widgets()
        self.show() # Do this here so all the widgets get their sizes before being hidden
        self.refresh()

    def refresh(self):
        raise NotImplementedError

    def update_measurements(self):
        raise NotImplementedError

    def _toplevel_widget(self):
        QWidget.__init__(self)
        self.setWindowTitle(f'{self._inst._long_name} ({self._inst._name})')

        layoutv = QVBoxLayout(self)
        layoutv.setContentsMargins(0, 0, 0, 0)
        layoutv.setSpacing(0)
        layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_configure = self._menubar.addMenu('&Configuration')
        action = QAction('&Load...', self)
        action.triggered.connect(self._menu_do_load_configuration)
        self._menubar_configure.addAction(action)
        action = QAction('&Save As...', self)
        action.triggered.connect(self._menu_do_save_configuration)
        self._menubar_configure.addAction(action)
        action = QAction('Reset device to &default', self)
        action.triggered.connect(self._menu_do_reset_device)
        self._menubar_configure.addAction(action)
        action = QAction('&Refresh', self)
        action.triggered.connect(self._menu_do_refresh_configuration)
        self._menubar_configure.addAction(action)

        self._menubar_device = self._menubar.addMenu('&Device')

        self._menubar_view = self._menubar.addMenu('&View')

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About', self)
        action.triggered.connect(self._menu_do_about)
        self._menubar_help.addAction(action)

        layoutv.addWidget(self._menubar)
        central_widget = QWidget()
        layoutv.addWidget(central_widget)
        self._statusbar = QStatusBar()
        self._statusbar.setSizeGripEnabled(False)
        ss = """color: black; background-color: #c0c0c0; font-weight: bold;"""
        self._statusbar.setStyleSheet(ss)
        layoutv.addWidget(self._statusbar)

        return central_widget

    def _menu_do_refresh_configuration(self):
        self.refresh()

    def _menu_do_load_configuration(self):
        raise NotImplementedError

    def _menu_do_save_configuration(self):
        raise NotImplementedError

    def _menu_do_reset_device(self):
        raise NotImplementedError

    def _menu_do_about(self):
        raise NotImplementedError

    def _printable_text_dialog(self, title, contents):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layoutv = QVBoxLayout()
        dialog.setLayout(layoutv)
        text = QPlainTextEdit()
        layoutv.addWidget(text)
        text.setPlainText(contents)
        dialog.exec()

    def closeEvent(self, event):
        self._inst.disconnect()
        self._main_window._device_window_closed(self._inst)
