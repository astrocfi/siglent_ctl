import re

from PyQt6.QtWidgets import (QWidget,
                             QMenuBar, QMenu, QStatusBar,
                             QDialog,
                             QLabel,
                             QLineEdit,
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
                             QVBoxLayout)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import *

class ConfigureWidgetBase(QWidget):
    def __init__(self, instrument):
        self._inst = instrument
        self._param_state = {}
        self._widget_registry = {}
        self._menubar = None
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
        self.setWindowTitle(f'Configure {self._inst._long_name} ({self._inst._name})')

        layoutv = QVBoxLayout(self)
        layoutv.setSpacing(0)
        layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_configure = self._menubar.addMenu('&Configure')
        action = QAction('&Refresh', self)
        action.triggered.connect(self._menu_do_refresh_configuration)
        self._menubar_configure.addAction(action)
        action = QAction('&Load...', self)
        action.triggered.connect(self._menu_do_load_configuration)
        self._menubar_configure.addAction(action)
        action = QAction('&Save...', self)
        action.triggered.connect(self._menu_do_save_configuration)
        self._menubar_configure.addAction(action)
        action = QAction('Reset device to &default', self)
        action.triggered.connect(self._menu_do_reset_device)
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
