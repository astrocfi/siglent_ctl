################################################################################
# acquire.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains code to define the AcquireWidget, which is the top-level widget
# used to manage measurement acquisition.
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

from PyQt6.QtWidgets import (QWidget,
                             QDialog,
                             QMessageBox,
                             QLabel,
                             QLineEdit,
                             QPushButton,
                             QCheckBox,
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
from PyQt6.QtCore import Qt


class AcquireWidget(QWidget):
    def __init__(self, instrument):
        super().__init__()
        self._init_widgets()

    def _init_widgets():
