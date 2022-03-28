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

import platform

from PyQt6.QtWidgets import (QApplication,
                             QDialog,
                             QDoubleSpinBox,
                             QLayout,
                             QMenuBar,
                             QPlainTextEdit,
                             QPushButton,
                             QStatusBar,
                             QStyledItemDelegate,
                             QVBoxLayout,
                             QWidget)
from PyQt6.QtCore import Qt, QAbstractTableModel, QTimer
from PyQt6.QtGui import QAction

class ConfigureWidgetBase(QWidget):
    def __init__(self, main_window, instrument):
        super().__init__()
        self._style_env = main_window._style_env
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

    def _toplevel_widget(self, has_reset=True):
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
        if has_reset:
            action = QAction('Reset device to &default', self)
            action.triggered.connect(self._menu_do_reset_device)
            self._menubar_configure.addAction(action)
        action = QAction('&Refresh', self)
        action.triggered.connect(self._menu_do_refresh_configuration)
        self._menubar_configure.addAction(action)

        self._menubar_device = self._menubar.addMenu('&Device')

        self._menubar_view = self._menubar.addMenu('&View')

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About...', self)
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
        """Handle window close event by disconnecting from the instrument."""
        self._inst.disconnect()
        self._main_window._device_window_closed(self._inst)


class DoubleSpinBoxDelegate(QStyledItemDelegate):
    """Numerical input field to use in a QTableView."""
    def __init__(self, parent, fmt, minmax):
        super().__init__(parent)
        self._fmt = fmt
        self._min_val, self._max_val = minmax

    def createEditor(self, parent, option, index):
        input = QDoubleSpinBox(parent)
        input.setAlignment(Qt.AlignmentFlag.AlignLeft)
        if self._fmt[-1] == 'd':
            input.setDecimals(0)
        else:
            input.setDecimals(int(self._fmt[1:-1]))
        input.setMinimum(self._min_val)
        input.setMaximum(self._max_val)
        input.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        input.setAccelerated(True)
        return input

    def setEditorData(self, editor, index):
        val = index.model().data(index, Qt.ItemDataRole.EditRole)
        editor.setValue(val)


class ListTableModel(QAbstractTableModel):
    """Table model for the List table."""
    def __init__(self, data_changed_callback):
        super().__init__()
        self._data = [[]]
        self._fmts = []
        self._header = []
        self._highlighted_row = None
        self._data_changed_calledback = data_changed_callback

    def set_params(self, data, fmts, header):
        self._data = data
        self._fmts = fmts
        self._header = header
        self.layoutChanged.emit()
        index_1 = self.index(0, 0)
        index_2 = self.index(len(self._data)-1, len(self._fmts)-1)
        self.dataChanged.emit(index_1, index_2, [Qt.ItemDataRole.DisplayRole])

    def set_highlighted_row(self, row):
        if self._highlighted_row is not None:
            index_1 = self.index(self._highlighted_row, 0)
            index_2 = self.index(self._highlighted_row, len(self._fmts)-1)
            # Remove old highlight
            self._highlighted_row = None
            self.dataChanged.emit(index_1, index_2, [Qt.ItemDataRole.BackgroundRole])
        self._highlighted_row = row
        if row is not None:
            index_1 = self.index(row, 0)
            index_2 = self.index(row, len(self._fmts)-1)
            # Set new highlight
            self.dataChanged.emit(index_1, index_2, [Qt.ItemDataRole.BackgroundRole])

    def cur_data(self):
        return self._data

    def data(self, index, role):
        row = index.row()
        column = index.column()
        match role:
            case Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            case Qt.ItemDataRole.DisplayRole:
                val = self._data[row][column]
                return (('%'+self._fmts[column]) % val)
            case Qt.ItemDataRole.EditRole:
                return self._data[row][column]
            case Qt.ItemDataRole.BackgroundRole:
                if row == self._highlighted_row:
                    return QColor('yellow')
                return None
        return None

    def setData(self, index, val, role):
        if role == Qt.ItemDataRole.EditRole:
            row = index.row()
            column = index.column()
            val = float(val)
            self._data[row][column] = val
            self._data_changed_calledback(row, column, val)
            return True
        return False

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self._data[0])

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal:
            match role:
                case Qt.ItemDataRole.TextAlignmentRole:
                    return Qt.AlignmentFlag.AlignCenter
                case Qt.ItemDataRole.DisplayRole:
                    if 0 <= section < len(self._header):
                        return self._header[section]
                    return ''
        else:
            match role:
                case Qt.ItemDataRole.TextAlignmentRole:
                    return Qt.AlignmentFlag.AlignRight
                case Qt.ItemDataRole.DisplayRole:
                    return '%d' % (section+1)

    def flags(self, index):
        return (Qt.ItemFlag.ItemIsEnabled |
                Qt.ItemFlag.ItemIsEditable)


class LongClickButton(QPushButton):
    """Button that implements both normal click and long-hold click."""
    def __init__(self, text, click_handler, long_click_handler,
                 delay=2000):
        super().__init__(text)
        self._click_handler = click_handler
        self._long_click_handler = long_click_handler
        self._delay = delay
        self._timer = QTimer()
        # Execute longClick() after timer expires
        self._timer.timeout.connect(self.long_click)

    # Rewrite the mousePressEvent method and turn on the timer
    def mousePressEvent(self, e):
        self._timer.start(self._delay)
        super().mousePressEvent(e)

    # Override the mouseReleaseEvent method and close the timer
    def mouseReleaseEvent(self, e):
        active = self._timer.isActive()
        self._timer.stop()
        if active:
            self._click_handler(self)
        super().mouseReleaseEvent(e)

    # What to do after long press
    def long_click(self):
        # Here, stop must also be called once, because mouseReleaseEvent will not be
        # executed in some scenarios, for example when QMessageBox is called.
        self._timer.stop()
        self._long_click_handler(self)

class DoubleSpeedSpinBox(QDoubleSpinBox):
    """DoubleSpinBox that supports click, Ctrl+click, and Shift+click steps.

    Click means normal step. Then moving counterclockwise around the keyboard,
    Shift means 0.1, ctrl means 0.01, and alt means 0.001."""
    def __init__(self, default_step, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_step = default_step

    def setSingleStep(self, val):
        self._default_step = val
        super().setSingleStep(val)

    def stepBy(self, steps):
        new_step = self._default_step
        mods = QApplication.queryKeyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            new_step *= 0.1
        elif mods & Qt.KeyboardModifier.ControlModifier:
            new_step *= 0.01
            steps = steps // 10  # Qt will already have bumped this up because of Ctrl
        elif mods & Qt.KeyboardModifier.AltModifier:
            # Note for some reason Alt+mouse wheel doesn't work. This is a Qt or
            # Windows problem.
            new_step *= 0.001
        super().setSingleStep(new_step)
        super().stepBy(steps)
