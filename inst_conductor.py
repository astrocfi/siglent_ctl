################################################################################
# inst_conductor.py
#
# This file is part of the inst_conductor software suite.
#
# Is contains the top-level entry point for the suite.
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

from PyQt6.QtWidgets import QApplication

from main_window import MainWindow

app = QApplication(sys.argv)  # sys.argv is modified to remove Qt options
main_window = MainWindow(app, sys.argv)
main_window.show()

app.exec()
