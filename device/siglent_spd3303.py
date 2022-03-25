################################################################################
# siglent_spd3303.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains all code related to the Siglent SPD3303X series of programmable
# DC electronic loads:
#   - SPD3303X
#   - SPD3303X-E
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

import json
import re
import time

from PyQt6.QtWidgets import (QWidget,
                             QAbstractSpinBox,
                             QButtonGroup,
                             QCheckBox,
                             QDial,
                             QDoubleSpinBox,
                             QFileDialog,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QLabel,
                             QLayout,
                             QMessageBox,
                             QPushButton,
                             QRadioButton,
                             QStyledItemDelegate,
                             QTableView,
                             QVBoxLayout)
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtCore import Qt, QAbstractTableModel, QTimer

import pyqtgraph as pg

from .device import Device4882
from .config_widget_base import ConfigureWidgetBase


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


# This class encapsulates the main SDL configuration widget.

class InstrumentSiglentSPD3303ConfigureWidget(ConfigureWidgetBase):
    def __init__(self, *args, **kwargs):
        # The current state of all SCPI parameters. String values are always stored
        # in upper case!
        self._param_state = {}

        self._widgets_minmax_limits = []
        self._widgets_adjustment_knobs = []
        self._widgets_preset_buttons = []
        self._widgets_measurements = []

        # List mode parameters
        self._list_mode_levels = None
        self._list_mode_widths = None
        self._list_mode_slews = None

        # We have to fake the progress of the steps in List mode because there is no
        # SCPI command to find out what step we are currently on, so we do it by
        # looking at the elapsed time and hope the instrument and the computer stay
        # roughly synchronized. But if they fall out of sync there's no way to get
        # them back in sync except starting the List sequence over.

        # The time the most recent List step was started
        self._list_mode_running = False
        self._list_mode_cur_step_start_time = None
        self._list_mode_cur_step_num = None
        self._list_mode_stopping = False

        # Used to enable or disable measurement of parameters to speed up
        # data acquisition.
        self._enable_measurement_v = True
        self._enable_measurement_c = True
        self._enable_measurement_p = True

        # Needed to prevent recursive calls when setting a widget's value invokes
        # the callback handler for it.
        self._disable_callbacks = False

        # We need to call this later because some things called by __init__ rely
        # on the above variables being initialized.
        super().__init__(*args, **kwargs)

        # Timer used to follow along with List mode
        self._list_mode_timer = QTimer(self._main_window.app)
        self._list_mode_timer.timeout.connect(self._update_list_table_heartbeat)
        self._list_mode_timer.setInterval(250)

    ######################
    ### Public methods ###
    ######################

    # This reads instrument -> _param_state
    def refresh(self):
        """Read all parameters from the instrument and set our internal state to match."""
        return # XXX
        self._param_state = {} # Start with a blank slate
        for mode, info in _SDL_MODE_PARAMS.items():
            for param_spec in info['params']:
                param0, param1 = self._scpi_cmds_from_param_info(info, param_spec)
                if param0 in self._param_state:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    # And we will have already taken care of param1 the previous time
                    # as well
                    continue
                val = self._inst.query(f'{param0}?')
                param_type = param_spec[1][-1]
                match param_type:
                    case 'f': # Float
                        val = float(val)
                    case 'b' | 'd': # Boolean or Decimal
                        val = int(float(val))
                    case 's' | 'r': # String or radio button
                        val = val.upper()
                    case _:
                        assert False, f'Unknown param_type {param_type}'
                self._param_state[param0] = val
                if param1 is not None:
                    # A Boolean flag associated with param0
                    # We let the flag override the previous value
                    val1 = int(float(self._inst.query(f'{param1}?')))
                    self._param_state[param1] = val1
                    if not val1 and self._param_state[param0] != 0:
                        if param_type == 'f':
                            self._param_state[param0] = 0.
                        else:
                            self._param_state[param0] = 0
                        self._inst.write(f'{param0} 0')

        # Special read of the List Mode parameters
        self._update_list_mode_from_instrument()

        if self._param_state[':TRIGGER:SOURCE'] == 'MANUAL':
            # No point in using the SDL's panel when the button isn't available
            new_param_state = {':TRIGGER:SOURCE': 'BUS'}
            self._update_param_state_and_inst(new_param_state)

        # Set things like _cur_overall_mode and _cur_const_mode and update widgets
        self._update_state_from_param_state()

    # This writes _param_state -> instrument (opposite of refresh)
    def update_instrument(self):
        """Update the instrument with the current _param_state.

        This is tricker than it should be, because if you send a configuration
        command to the SDL for a mode it's not currently in, it crashes!"""
        return # XXX
        set_params = set()
        first_list_mode_write = True
        for mode, info in _SDL_MODE_PARAMS.items():
            first_write = True
            for param_spec in info['params']:
                if param_spec[2] is False:
                    continue # The General False flag, all others are written
                param0, param1 = self._scpi_cmds_from_param_info(info, param_spec)
                if param0 in set_params:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    continue
                set_params.add(param0)
                if first_write and info['mode_name']:
                    first_write = False
                    # We have to put the instrument in the correct mode before setting
                    # the parameters. Not necessary for "General" (mode_name None).
                    self._put_inst_in_mode(mode[0], mode[1])
                self._update_one_param_on_inst(param0, self._param_state[param0])
                if param1 is not None:
                    self._update_one_param_on_inst(param1, self._param_state[param1])
            if info['mode_name'] == 'LIST' and first_list_mode_write:
                first_list_mode_write = False
                # Special write of the List Mode parameters
                steps = self._param_state[':LIST:STEP']
                for i in range(1, steps+1):
                    self._inst.write(f':LIST:LEVEL {i},{self._list_mode_levels[i-1]:.3f}')
                    self._inst.write(f':LIST:WIDTH {i},{self._list_mode_widths[i-1]:.3f}')
                    self._inst.write(f':LIST:SLEW {i},{self._list_mode_slews[i-1]:.3f}')

        self._update_state_from_param_state()
        self._put_inst_in_mode(self._cur_overall_mode, self._cur_const_mode)

    def update_measurements(self, read_inst=True):
        """Read current values, update control panel display, return the values."""
        # if read_inst:
        #     input_state = int(self._inst.query(':INPUT:STATE?'))
        #     if self._param_state[':INPUT:STATE'] != input_state:
        #         # No need to update the instrument, since it changed the state for us
        #         self._update_load_state(input_state, update_inst=False)

        measurements = {}

        for ch in (1,2):
            voltage = None
            if read_inst:
                w = self._widget_registry[f'MeasureV{ch}']
                if self._enable_measurement_v:
                    voltage = self._inst.measure_voltage(ch)
                    w.setText(f'{voltage:6.3f} V')
                else:
                    w.setText('---   V')
            measurements[f'CH{ch} Voltage'] = {'name':  'Voltage',
                                               'unit':  'V',
                                               'val':   voltage}

            current = None
            if read_inst:
                w = self._widget_registry[f'MeasureC{ch}']
                if self._enable_measurement_c:
                    current = self._inst.measure_current(ch)
                    w.setText(f'{current:5.3f} A')
                else:
                    w.setText('---   A')
            measurements[f'CH{ch} Current'] = {'name':  'Current',
                                               'unit':  'A',
                                               'val':   current}

            power = None
            if read_inst:
                w = self._widget_registry[f'MeasureP{ch}']
                if self._enable_measurement_p:
                    power = self._inst.measure_power(ch)
                    w.setText(f'{power:6.3f} W')
                else:
                    w.setText('---   W')
            measurements[f'CH{ch} Power'] = {'name':  'Power',
                                             'unit':  'W',
                                             'val':   power}

        return measurements

    ############################################################################
    ### Setup Window Layout
    ############################################################################

    def _init_widgets(self):
        """Set up all the toplevel widgets."""
        toplevel_widget = self._toplevel_widget()

        ### Add to Device menu

        ### Add to View menu

        action = QAction('&Min/Max Limits', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_minmax_limits)
        self._menubar_view.addAction(action)
        action = QAction('&Adjustment Knobs', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_adjustment_knobs)
        self._menubar_view.addAction(action)
        action = QAction('&Presets', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_presets)
        self._menubar_view.addAction(action)
        action = QAction('&Measurements', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_measurements)
        self._menubar_view.addAction(action)

        ### Set up configuration window widgets

        main_vert_layout = QVBoxLayout(toplevel_widget)
        main_vert_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        main_horiz_layout = QHBoxLayout()
        main_vert_layout.addLayout(main_horiz_layout)
        frame = self._init_widgets_add_channel(1)
        main_horiz_layout.addWidget(frame)
        frame = self._init_widgets_add_channel(2)
        main_horiz_layout.addWidget(frame)

        self.show()


    def _init_widgets_add_channel(self, ch):
        frame = QGroupBox(f'Channel {ch}')

        vert_layout = QVBoxLayout(frame)
        vert_layout.setContentsMargins(0, 0, 0, 0)

        layoutg = QGridLayout()
        layoutg.setSpacing(0)
        vert_layout.addLayout(layoutg)

        for cv_num, (cv, cvu) in enumerate((('V', 'V'), ('I', 'A'))):
            # Min/max limits
            w = QWidget()
            layouth = QHBoxLayout(w)
            layouth.addStretch()
            layoutg.addWidget(w, 0, cv_num)
            layoutg2 = QGridLayout()
            layouth.addLayout(layoutg2)
            self._widgets_minmax_limits.append(w)
            for mm_num, mm in enumerate(('Min', 'Max')):
                layoutg2.addWidget(QLabel(f'{cv} {mm}:'), mm_num, 0,
                                          Qt.AlignmentFlag.AlignLeft)
                spinner = QDoubleSpinBox()
                spinner.setAlignment(Qt.AlignmentFlag.AlignRight)
                spinner.setSuffix(f' {cvu}')
                spinner.setDecimals(3)
                if cv == 'V':
                    spinner.setRange(0, 32)
                else:
                    spinner.setRange(0, 3.2)
                layoutg2.addWidget(spinner, mm_num, 1, Qt.AlignmentFlag.AlignLeft)
            layouth.addStretch()

            # Main V/C inputs
            ss = """font-size: 30px;"""
            spinner = QDoubleSpinBox()
            spinner.setStyleSheet(ss)
            spinner.setAlignment(Qt.AlignmentFlag.AlignRight)
            spinner.setSuffix(f' {cvu}')
            spinner.setDecimals(3)
            if cv == 'V':
                spinner.setRange(0, 32)
            else:
                spinner.setRange(0, 3.2)
            layouth = QHBoxLayout()
            layoutg.addLayout(layouth, 2, cv_num)
            layouth.addStretch()
            layouth.addWidget(spinner)
            layouth.addStretch()

            # Adjustment knobs
            w = QWidget()
            self._widgets_adjustment_knobs.append(w)
            layoutg2 = QGridLayout(w)
            layoutg2.setSpacing(0)
            layoutg2.setContentsMargins(0,0,0,0)
            layoutg.addWidget(w, 3, cv_num)
            ss = """max-width: 5.5em; max-height: 5.5em; background-color:yellow; border: 1px;"""
            ss2 = """max-width: 4.5em; max-height: 4.5em;"""
            for cf_num, cf in enumerate(('Coarse', 'Fine')):
                dial = QDial()
                if cf == 'Coarse':
                    dial.setStyleSheet(ss)
                else:
                    dial.setStyleSheet(ss2)
                dial.setWrapping(True)
                layoutg2.addWidget(dial, 0, cf_num, Qt.AlignmentFlag.AlignCenter)
                layoutg2.addWidget(QLabel(f'{cf} {cv}'), 1, cf_num,
                                   Qt.AlignmentFlag.AlignCenter)

        # Preset buttons
        w = QWidget()
        vert_layout.addWidget(w)
        self._widgets_preset_buttons.append(w)
        layoutg = QGridLayout(w)
        for preset_num in range(6):
            row, column = divmod(preset_num, 2)
            # button = QPushButton(f'Preset {preset_num+1}')
            button = QPushButton(f'32.000V / 3.200A')
            layoutg.addWidget(button, row, column)


        ###### ROW X - MEASUREMENTS ######

        w = QWidget()
        w.setStyleSheet('background: black;')
        layoutv = QVBoxLayout(w)
        vert_layout.addWidget(w)
        self._widgets_measurements.append(w)

        ss = """font-size: 30px; font-weight: bold; font-family: "Courier New";
                min-width: 4.5em; color: yellow;
             """
        ss2 = """font-size: 15px; font-weight: bold; font-family: "Courier New";
                 min-width: 2.5em; color: yellow;
             """
        layouth = QHBoxLayout()
        layoutv.addLayout(layouth)
        layouth.addStretch()
        w = QLabel(' ---  V')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layouth.addWidget(w)
        self._widget_registry[f'MeasureV{ch}'] = w
        w = QLabel(' ---  A')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layouth.addWidget(w)
        self._widget_registry[f'MeasureC{ch}'] = w
        layouth.addStretch()
        layouth = QHBoxLayout()
        layoutv.addLayout(layouth)
        layouth.addStretch()
        w = QLabel(' ---  W')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss2)
        layouth.addWidget(w)
        self._widget_registry[f'MeasureP{ch}'] = w
        layouth.addStretch()

        return frame

    # Our general philosophy is to create all of the possible input widgets for all
    # parameters and all units, and then hide the ones we don't need.
    # The details structure contains a list of:
    #   - The string to display as the input label
    #   - The name of the parameter as used in the _SDL_MODE_PARAMS dictionary
    #   - The unit to display in the input edit field
    #   - The SCPI parameter name, which gets added as an attribute on the widget
    #     - If the SCPI parameter is a tuple (SCPI1, SCPI2), then the first is the
    #       main parameter, and the second is the associated "STATE" parameter that
    #       is set to 0 or 1 depending on whether the main parameter is zero or
    #       non-zero.
    #     - If the SCPI parameter starts with ":" then the current mode is not
    #       prepended during widget update.
    def _init_widgets_value_box(self, title, details, layout=None):
        # Value for most modes
        widget_prefix = title.replace(' ', '')
        if layout is None:
            frame = QGroupBox(title)
            layoutv = QVBoxLayout(frame)
        else:
            frame = None
            layoutv = layout
        for (display, param_name, unit, scpi) in details:
            special_text = None
            if display[0] == '*':
                # Special indicator that "0" means "Disabled"
                special_text = 'Disabled'
                display = display[1:]
            if display[0] == '@':
                # Special indicator that "0" means "Infinite"
                special_text = 'Infinite'
                display = display[1:]
            layouth = QHBoxLayout()
            label = QLabel(display+':')
            layouth.addWidget(label)
            input = QDoubleSpinBox()
            input.wid = (param_name, scpi)
            if special_text:
                input.setSpecialValueText(special_text)
            input.setAlignment(Qt.AlignmentFlag.AlignRight)
            input.setDecimals(3)
            input.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
            input.setAccelerated(True)
            if unit is not None:
                input.setSuffix(' '+unit)
            input.editingFinished.connect(self._on_value_change)
            layouth.addWidget(input)
            label.sizePolicy().setRetainSizeWhenHidden(True)
            input.sizePolicy().setRetainSizeWhenHidden(True)
            layoutv.addLayout(layouth)
            input.registry_name = f'{widget_prefix}_{param_name}'
            self._widget_registry[input.registry_name] = input
            self._widget_registry[f'{widget_prefix}Label_{param_name}'] = label
        if frame is not None:
            layoutv.addStretch()
            self._widget_registry[f'Frame{widget_prefix}'] = frame
        return frame

    ############################################################################
    ### Action and Callback Handlers
    ############################################################################

    def _menu_do_about(self):
        """Show the About box."""
        msg = """Siglent SDL1000-series instrument interface.

Supported instruments: SDL1020X, SDL1020X-E, SDL1030X, SDL1030X-E.

Copyright 2022, Robert S. French"""
        QMessageBox.about(self, 'About', msg)

    def _menu_do_save_configuration(self):
        """Save the current configuration to a file."""
        fn = QFileDialog.getSaveFileName(self, caption='Save Configuration',
                                         filter='All (*.*);;Configuration (*.scfg)',
                                         initialFilter='Configuration (*.scfg)')
        fn = fn[0]
        if not fn:
            return
        ps = self._param_state.copy()
        # Add the List mode parameters as fake SCPI commands
        step = ps[':LIST:STEP']
        for i in range(step):
            ps[f':LIST:LEVEL {i+1}'] = self._list_mode_levels[i]
            ps[f':LIST:WIDTH {i+1}'] = self._list_mode_widths[i]
            ps[f':LIST:SLEW {i+1}'] = self._list_mode_slews[i]
        with open(fn, 'w') as fp:
            json.dump(ps, fp, sort_keys=True, indent=4)

    def _menu_do_load_configuration(self):
        """Load the current configuration from a file."""
        fn = QFileDialog.getOpenFileName(self, caption='Load Configuration',
                                         filter='All (*.*);;Configuration (*.scfg)',
                                         initialFilter='Configuration (*.scfg)')
        fn = fn[0]
        if not fn:
            return
        with open(fn, 'r') as fp:
            ps = json.load(fp)
        # Retrieve the List mode parameters
        step = ps[':LIST:STEP']
        self._list_mode_levels = []
        self._list_mode_widths = []
        self._list_mode_slews = []
        for i in range(step):
            cmd = f':LIST:LEVEL {i+1}'
            self._list_mode_levels.append(ps[cmd])
            del ps[cmd]
            cmd = f':LIST:WIDTH {i+1}'
            self._list_mode_widths.append(ps[cmd])
            del ps[cmd]
            cmd = f':LIST:SLEW {i+1}'
            self._list_mode_slews.append(ps[cmd])
            del ps[cmd]
        self._param_state = ps
        # Clean up the param state. We don't want to start with the load or short on.
        self._param_state['SYST:REMOTE:STATE'] = 1
        self._update_load_state(0)
        self._param_state['INPUT:STATE'] = 0
        self._update_short_state(0)
        self._param_state['SHORT:STATE'] = 0
        if self._param_state[':TRIGGER:SOURCE'] == 'Manual':
            # No point in using the SDL's panel when the button isn't available
            self._param_state[':TRIGGER:SOURCE'] = 'Bus'
        self.update_instrument()

    def _menu_do_reset_device(self):
        """Reset the instrument and then reload the state."""
        # A reset takes around 6.75 seconds, so we wait up to 10s to be safe.
        self.setEnabled(False)
        self.repaint()
        self._inst.write('*RST', timeout=10000)
        self.refresh()
        self.setEnabled(True)

    def _menu_do_view_minmax_limits(self, state):
        """Toggle visibility of the min/max limit spinboxes."""
        for w in self._widgets_minmax_limits:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_adjustment_knobs(self, state):
        """Toggle visibility of the adjustment knobs."""
        for w in self._widgets_adjustment_knobs:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_presets(self, state):
        """Toggle visibility of the preset buttons."""
        for w in self._widgets_preset_buttons:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_measurements(self, state):
        """Toggle visibility of the measurements row."""
        for w in self._widgets_measurements:
            if state:
                w.show()
            else:
                w.hide()

    def _on_value_change(self):
        """Handle clicking on any input value edit box."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        input = self.sender()
        param_name, scpi = input.wid
        scpi_cmd_state = None
        scpi_state = None
        if isinstance(scpi, tuple):
            scpi, scpi_state = scpi
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        if scpi[0] == ':':
            mode_name = ''  # Global setting
            scpi_cmd = scpi
            if scpi_state is not None:
                scpi_cmd_state = scpi_state
        else:
            mode_name = f':{mode_name}'
            scpi_cmd = f'{mode_name}:{scpi}'
            if scpi_state is not None:
                scpi_cmd_state = f'{mode_name}:{scpi_state}'
        val = input.value()
        if input.decimals() > 0:
            val = float(input.value())
        else:
            val = int(val)
        new_param_state = {scpi_cmd: val}
        # Check for special case of associated boolean flag. In these cases if the
        # value is zero, we set the boolean to False. If the value is non-zero, we
        # set the boolean to True. This makes zero be the "deactivated" sentinal.
        if scpi_cmd_state in self._param_state:
            new_param_state[scpi_cmd_state] = int(val != 0)
        # Check for the special case of a slew parameter. The rise and fall slew
        # values are tied together. In 5A mode, both must be in the range
        # 0.001-0.009 or 0.010-0.500. In 30A mode, both must be in the range
        # 0.001-0.099 or 0.100-2.500. If one of the inputs goes outside of its
        # current range, the other field needs to be changed.
        if 'SLEW' in scpi_cmd:
            if mode_name == '':
                trans = ''
            else:
                trans = self._transient_string()
            irange = self._param_state[f'{mode_name}{trans}:IRANGE']
            if input.registry_name.endswith('SlewPos'):
                other_name = input.registry_name.replace('SlewPos', 'SlewNeg')
                other_scpi = scpi.replace('POSITIVE', 'NEGATIVE')
            else:
                other_name = input.registry_name.replace('SlewNeg', 'SlewPos')
                other_scpi = scpi.replace('NEGATIVE', 'POSITIVE')
            other_widget = self._widget_registry[other_name]
            orig_other_val = other_val = other_widget.value()
            if irange == '5':
                if 0.001 <= val <= 0.009:
                    if not (0.001 <= other_val <= 0.009):
                        other_val = 0.009
                elif not (0.010 <= other_val <= 0.500):
                    other_val = 0.010
            else:
                if 0.001 <= val <= 0.099:
                    if not (0.001 <= other_val <= 0.099):
                        other_val = 0.099
                elif not (0.100 <= other_val <= 2.500):
                    other_val = 0.100
            if orig_other_val != other_val:
                scpi_cmd = f'{mode_name}:{other_scpi}'
                new_param_state[scpi_cmd] = other_val
        self._update_param_state_and_inst(new_param_state)
        if scpi_cmd == ':LIST:STEP':
            # When we change the number of steps, we might need to read in more
            # rows from the instrument
            self._update_list_mode_from_instrument(new_rows_only=True)
        self._update_widgets()

    def _on_list_table_change(self, row, column, val):
        """Handle change to any List Mode table value."""
        match column:
            case 0:
                self._list_mode_levels[row] = val
                self._inst.write(f':LIST:LEVEL {row+1},{val:.3f}')
            case 1:
                self._list_mode_widths[row] = val
                self._inst.write(f':LIST:WIDTH {row+1},{val:.3f}')
            case 2:
                self._list_mode_slews[row] = val
                self._inst.write(f':LIST:SLEW {row+1},{val:.3f}')
        self._update_list_table_graph(update_table=False)

    def _on_click_load_on_off(self):
        """Handle clicking on the LOAD button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        state = 1-self._param_state[':INPUT:STATE']
        self._update_load_state(state) # Also updates the button

    def _update_load_onoff_button(self, state=None):
        """Update the style of the SHORT button based on current or given state."""
        if state is None:
            state = self._param_state[':INPUT:STATE']
        bt = self._widget_registry['LoadONOFF']
        if state:
            if self._cur_overall_mode in ('Battery', 'OCPT', 'OPPT'):
                bt.setText('STOP TEST')
            else:
                bt.setText('LOAD IS ON')
            bg_color = '#ffc0c0'
        else:
            if self._cur_overall_mode in ('Battery', 'OCPT', 'OPPT'):
                bt.setText('START TEST')
            else:
                bt.setText('LOAD IS OFF')
            bg_color = '#c0ffb0'
        ss = f"""QPushButton {{
                    background-color: {bg_color};
                    min-width: 7em; max-width: 7em;
                    min-height: 1em; max-height: 1em;
                    border-radius: 0.4em; border: 5px solid black;
                    font-weight: bold; font-size: 22px; }}
                 QPushButton:pressed {{ border: 7px solid black; }}
              """
        bt.setStyleSheet(ss)

    def _on_click_enable_measurements(self):
        """Handle clicking on an enable measurements checkbox."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        cb = self.sender()
        match cb.mode:
            case 'V':
                self._enable_measurement_v = cb.isChecked()
            case 'C':
                self._enable_measurement_c = cb.isChecked()
            case 'P':
                self._enable_measurement_p = cb.isChecked()
        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    ################################
    ### Internal helper routines ###
    ################################

    def _scpi_cmds_from_param_info(self, param_info, param_spec):
        """Create a SCPI command from a param_info structure."""
        mode_name = param_info['mode_name']
        if mode_name is None: # General parameters
            mode_name = ''
        else:
            mode_name = f':{mode_name}:'
        if isinstance(param_spec[0], (tuple, list)):
            ps1, ps2 = param_spec[0]
            if ps1[0] == ':':
                mode_name = ''
            return f'{mode_name}{ps1}', f'{mode_name}{ps2}'
        ps1 = param_spec[0]
        if ps1[0] == ':':
            mode_name = ''
        return f'{mode_name}{ps1}', None

    def _put_inst_in_mode(self, overall_mode, const_mode):
        """Place the SDL in the given overall mode (and const mode)."""
        overall_mode = overall_mode.upper()
        if const_mode is not None:
            const_mode = const_mode.upper()
        match overall_mode:
            case 'DYNAMIC':
                self._inst.write(f':FUNCTION:TRANSIENT {const_mode}')
            case 'BASIC':
                self._inst.write(f':FUNCTION {const_mode}')
            case 'LED':
                self._inst.write(':FUNCTION LED')
            case 'BATTERY':
                self._inst.write(':FUNCTION BATTERY')
                self._inst.write(f':BATTERY:MODE {const_mode}')
            case 'OCPT':
                self._inst.write(':OCP:FUNC')
            case 'OPPT':
                self._inst.write(':OPP:FUNC')
            case 'EXT \u26A0':
                if const_mode == 'VOLTAGE':
                    self._inst.write(':EXT:MODE EXTV')
                else:
                    assert const_mode == 'CURRENT'
                    self._inst.write(':EXT:MODE EXTI')
            case 'LIST':
                self._inst.write(':LIST:STATE:ON')
            case 'PROGRAM':
                self._inst.write(':PROGRAM:STATE:ON')
            case _:
                assert False, overall_mode

    def _update_state_from_param_state(self):
        """Update all internal state and widgets based on the current _param_state."""
        if self._param_state[':EXT:MODE'] != 'INT':
            mode = 'Ext \u26A0'
        else:
            mode = self._param_state[':FUNCTION:MODE']
            # Convert the title-case SDL-specific name to the name we use in the GUI
            match mode:
                case 'BASIC':
                    if self._param_state[':FUNCTION'] == 'LED':
                        mode = 'LED'
                case 'TRAN':
                    mode = 'Dynamic'
                case 'OCP':
                    mode = 'OCPT'
                case 'OPP':
                    mode = 'OPPT'
                # Other cases are already correct
            if mode not in ('LED', 'OCPT', 'OPPT'):
                mode = mode.title()
        assert mode in ('Basic', 'LED', 'Battery', 'OCPT', 'OPPT', 'Ext \u26A0',
                        'Dynamic', 'Program', 'List')
        self._cur_overall_mode = mode

        # Initialize the dynamic and const mode as appropriate
        self._cur_dynamic_mode = None
        self._cur_const_mode = None
        match mode:
            case 'Basic':
                self._cur_const_mode = self._param_state[':FUNCTION'].title()
                assert self._cur_const_mode in (
                    'Voltage', 'Current', 'Power', 'Resistance'), self._cur_const_mode
            case 'Dynamic':
                self._cur_const_mode = self._param_state[':FUNCTION:TRANSIENT'].title()
                assert self._cur_const_mode in (
                    'Voltage', 'Current', 'Power', 'Resistance'), self._cur_const_mode
                param_info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
                mode_name = param_info['mode_name']
                self._cur_dynamic_mode = (
                    self._param_state[f':{mode_name}:TRANSIENT:MODE'].title())
                assert self._cur_dynamic_mode in (
                    'Continuous', 'Pulse', 'Toggle'), self._cur_dynamic_mode
            case 'Battery':
                self._cur_const_mode = self._param_state[':BATTERY:MODE'].title()
                assert self._cur_const_mode in (
                    'Current', 'Power', 'Resistance'), self._cur_const_mode
            case 'Ext \u26A0':
                if self._param_state[':EXT:MODE'] == 'EXTV':
                    self._cur_const_mode = 'Voltage'
                else:
                    assert self._param_state[':EXT:MODE'] == 'EXTI'
                    self._cur_const_mode = 'Current'
            case 'List':
                self._cur_const_mode = self._param_state[':LIST:MODE'].title()
                assert self._cur_const_mode in (
                    'Voltage', 'Current', 'Power', 'Resistance'), self._cur_const_mode

        # If the Time test is turned on, then we enable both the TRise and TFall
        # measurements, but if it's off, we disable them both.
        if self._param_state[':TIME:TEST:STATE']:
            self._enable_measurement_trise = True
            self._enable_measurement_tfall = True
        else:
            self._enable_measurement_trise = False
            self._enable_measurement_tfall = False

        # Now update all the widgets and their values with the new info
        # This is a bit of a hack - first do all the widgets ignoring the min/max
        # value limits, which allows us to actually initialize all the values. Then
        # go back and do the same thing again, this time setting the min/max values.
        # It's not very efficient, but it doesn't matter.
        self._update_widgets(minmax_ok=False)
        self._update_widgets(minmax_ok=True)

    def _update_list_mode_from_instrument(self, new_rows_only=False):
        """Update the internal state for List mode from the instruments.

        If new_rows_only is True, then we just read the data for any rows that
        we haven't read already, assuming the rest to already be correct. If the
        number of rows has decreased, we leave the entries in the internal state so
        if the rows are increased again we don't have to bother fetching the data."""
        if not new_rows_only:
            self._list_mode_levels = []
            self._list_mode_widths = []
            self._list_mode_slews = []
        steps = self._param_state[':LIST:STEP']
        for i in range(len(self._list_mode_levels)+1, steps+1):
            self._list_mode_levels.append(float(self._inst.query(f':LIST:LEVEL? {i}')))
            self._list_mode_widths.append(float(self._inst.query(f':LIST:WIDTH? {i}')))
            self._list_mode_slews.append(float(self._inst.query(f':LIST:SLEW? {i}')))

    def _update_load_state(self, state, update_inst=True, update_widgets=True):
        """Update the load on/off internal state, possibly updating the instrument."""
        old_state = self._param_state[':INPUT:STATE']
        if state == old_state:
            return

        # When turning on/off the load, record the details for the battery log
        # or other purposes that may be written in the future
        if state:
            self._load_on_time = time.time()
            self._batt_log_initial_voltage = None
            # And if we're in List mode, reset to step None (it will go to 0 when
            # triggered)
            if self._cur_overall_mode == 'List':
                self._list_mode_cur_step_num = None
        else:
            self._load_off_time = time.time()
            # Any change from one overall mode to another (e.g. leaving List mode
            # for any reason) will pass through here, so this takes care of stopping
            # the timer in all those cases
            self._list_mode_timer.stop()
            self._list_mode_cur_step_num = None
            self._list_mode_stopping = False
            self._list_mode_running = False
            self._update_list_table_graph(list_step_only=True)

        if not state and self._cur_overall_mode == 'Battery':
            # For some reason when using Battery mode remotely, when the test is
            # complete (or aborted), the ADDCAP field is not automatically updated
            # like it is when you run a test from the front panel. So we do the
            # computation and update it here.
            disch_cap = self._inst.measure_battery_capacity()
            add_cap = self._inst.measure_battery_add_capacity()
            new_add_cap = (disch_cap + add_cap) * 1000  # ADDCAP takes mAh
            self._inst.write(f':BATTERY:ADDCAP {new_add_cap}')
            # Update the battery log entries
            if self._load_on_time is not None and self._load_off_time is not None:
                level = self._param_state[':BATTERY:LEVEL']
                match self._cur_const_mode:
                    case 'Current':
                        batt_mode = f'CC {level:.3f}A'
                    case 'Power':
                        batt_mode = f'CP {level:.3f}W'
                    case 'Resistance':
                        batt_mode = f'CR {level:.3f}\u2126'
                self._batt_log_modes.append(batt_mode)
                stop_cond = ''
                if self._param_state[':BATTERY:VOLTAGE:STATE']:
                    v = self._param_state[':BATTERY:VOLTAGE']
                    stop_cond += f'Vmin {v:.3f}V'
                if self._param_state[':BATTERY:CAP:STATE']:
                    if stop_cond != '':
                        stop_cond += ' or '
                        cap = self._param_state[':BATTERY:CAP']/1000
                    stop_cond += f'Cap {cap:3f}Ah'
                if self._param_state[':BATTERY:TIMER:STATE']:
                    if stop_cond != '':
                        stop_cond += ' or '
                    stop_cond += 'Time '+self._time_to_hms(
                        int(self._param_state[':BATTERY:TIMER']))
                if stop_cond == '':
                    self._batt_log_stop_cond.append('None')
                else:
                    self._batt_log_stop_cond.append(stop_cond)
                self._batt_log_initial_voltages.append(self._batt_log_initial_voltage)
                self._batt_log_start_times.append(self._load_on_time)
                self._batt_log_end_times.append(self._load_off_time)
                self._batt_log_run_times.append(self._load_off_time -
                                                self._load_on_time)
                self._batt_log_caps.append(disch_cap)

        if update_inst:
            new_param_state = {':INPUT:STATE': state}
            self._update_param_state_and_inst(new_param_state)
        else:
            self._param_state[':INPUT:STATE'] = state

        if update_widgets:
            self._update_widgets()

    def _update_short_state(self, state):
        new_param_state = {':SHORT:STATE': state}
        self._update_param_state_and_inst(new_param_state)
        self._update_short_onoff_button(state)

    def _show_or_disable_widgets(self, widget_list):
        for widget_re in widget_list:
            if widget_re[0] == '~':
                # Hide unused widgets
                widget_re = widget_re[1:]
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_re, trial_widget):
                        self._widget_registry[trial_widget].hide()
            elif widget_re[0] == '!':
                # Disable (and grey out) unused widgets
                widget_re = widget_re[1:]
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_re, trial_widget):
                        widget = self._widget_registry[trial_widget]
                        widget.setEnabled(False)
                        if isinstance(widget, QRadioButton):
                            # For disabled radio buttons we remove ALL selections so it
                            # doesn't look confusing
                            widget.button_group.setExclusive(False)
                            widget.setChecked(False)
                            widget.button_group.setExclusive(True)
            else:
                # Enable/show everything else
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_re, trial_widget):
                        self._widget_registry[trial_widget].setEnabled(True)
                        self._widget_registry[trial_widget].show()

    def _update_widgets(self, minmax_ok=True):
        """Update all parameter widgets with the current _param_state values."""
        if self._cur_overall_mode is None:
            return

        # We need to do this because various set* calls below trigger the callbacks,
        # which then call this routine again in the middle of it already doing its
        # work.
        self._disable_callbacks = True

        param_info = self._cur_mode_param_info()
        mode_name = param_info['mode_name']

        # We start by setting the proper radio button selections for the "Overall Mode"
        # and the "Constant Mode" groups
        for widget_name, widget in self._widget_registry.items():
            if widget_name.startswith('Overall_'):
                widget.setChecked(widget_name.endswith(self._cur_overall_mode))
            if self._cur_const_mode is not None and widget_name.startswith('Const_'):
                widget.setChecked(widget_name.endswith(self._cur_const_mode))

        # First we go through the widgets for the Dynamic sub-modes and the Constant
        # Modes and enable or disable them as appropriate based on the Overall Mode.
        self._show_or_disable_widgets(_SDL_OVERALL_MODES[self._cur_overall_mode])

        # Now we enable or disable widgets by first scanning through the "General"
        # widget list and then the widget list specific to this overall mode (if any).
        self._show_or_disable_widgets(_SDL_MODE_PARAMS['General']['widgets'])
        if param_info['widgets'] is not None:
            self._show_or_disable_widgets(param_info['widgets'])

        # Now we go through the details for each parameter and fill in the widget
        # value and set the widget parameters, as appropriate. We do the General
        # parameters first and then the parameters for the current mode.
        new_param_state = {}
        for phase in range(2):
            if phase == 0:
                params = _SDL_MODE_PARAMS['General']['params']
                mode_name = None
            else:
                params = param_info['params']
                mode_name = param_info['mode_name']
            for scpi_cmd, param_full_type, *rest in params:
                if isinstance(scpi_cmd, (tuple, list)):
                    # Ignore the boolean flag
                    scpi_cmd = scpi_cmd[0]
                param_type = param_full_type[-1]

                # Parse out the label and main widget REs and the min/max values
                match len(rest):
                    case 1:
                        # For General, these parameters don't have associated widgets
                        assert rest[0] in (False, True)
                        widget_label = None
                        widget_main = None
                    case 2:
                        # Just a label and main widget, no value range
                        widget_label, widget_main = rest
                    case 4:
                        # A label and main widget with min/max value
                        widget_label, widget_main, min_val, max_val = rest
                        trans = self._transient_string()
                        if min_val in ('C', 'V', 'P'):
                            min_val = 0
                        elif min_val == 'S':
                            min_val = 0.001
                        elif isinstance(min_val, str) and min_val.startswith('W:'):
                            if minmax_ok:
                                # This is needed because when we're first loading up the
                                # widgets from a cold start, the paired widget may not
                                # have a good min value yet
                                min_val = self._widget_registry[min_val[2:]].value()
                            else:
                                min_val = 0
                        if isinstance(max_val, str):
                            match max_val[0]:
                                case 'C': # Based on current range selection (5A, 30A)
                                    # Don't need to check for mode_name being None
                                    # because that will never happen for C/V/P/S
                                    max_val = self._param_state[
                                        f':{mode_name}{trans}:IRANGE']
                                    max_val = float(max_val)
                                case 'V': # Based on voltage range selection (36V, 150V)
                                    max_val = self._param_state[
                                        f':{mode_name}{trans}:VRANGE']
                                    max_val = float(max_val)
                                case 'P': # SDL1020 is 200W, SDL1030 is 300W
                                    max_val = self._inst._max_power
                                case 'S': # Slew range depends on IRANGE
                                    if self._param_state[
                                            f':{mode_name}{trans}:IRANGE'] == '5':
                                        max_val = 0.5
                                    else:
                                        max_val = 2.5
                                case 'W':
                                    if minmax_ok:
                                        # This is needed because when we're first loading
                                        # up the widgets from a cold start, the paired
                                        # widget may not have a good max value yet
                                        max_val = (self._widget_registry[max_val[2:]]
                                                   .value())
                                    else:
                                        max_val = 1000000000
                    case _:
                        assert False, f'Unknown widget parameters {rest}'

                if widget_label is not None:
                    self._widget_registry[widget_label].show()
                    self._widget_registry[widget_label].setEnabled(True)

                if widget_main is not None:
                    full_scpi_cmd = scpi_cmd
                    if mode_name is not None and scpi_cmd[0] != ':':
                        full_scpi_cmd = f':{mode_name}:{scpi_cmd}'
                    val = self._param_state[full_scpi_cmd]

                    if param_type in ('d', 'f', 'b'):
                        widget = self._widget_registry[widget_main]
                        widget.setEnabled(True)
                        widget.show()
                    if param_type in ('d', 'f'):
                        widget.setMaximum(max_val)
                        widget.setMinimum(min_val)

                    match param_type:
                        case 'b': # Boolean - used for checkboxes
                            widget.setChecked(val)
                        case 'd': # Decimal
                            widget.setDecimals(0)
                            widget.setValue(val)
                            # It's possible that setting the minimum or maximum caused
                            # the value to change, which means we need to update our
                            # state.
                            if val != int(float(widget.value())):
                                widget_val = float(widget.value())
                                new_param_state[full_scpi_cmd] = widget_val
                        case 'f': # Floating point
                            assert param_full_type[0] == '.'
                            dec = int(param_full_type[1:-1])
                            dec10 = 10 ** dec
                            widget.setDecimals(dec)
                            widget.setValue(val)
                            # It's possible that setting the minimum or maximum caused
                            # the value to change, which means we need to update our
                            # state. Note floating point comparison isn't precise so we
                            # only look to the precision of the number of decimals.
                            if int(val*dec10+.5) != int(widget.value()*dec10+.5):
                                widget_val = float(widget.value())
                                new_param_state[full_scpi_cmd] = widget_val
                        case 'r': # Radio button
                            # In this case only the widget_main is an RE
                            for trial_widget in self._widget_registry:
                                if re.fullmatch(widget_main, trial_widget):
                                    widget = self._widget_registry[trial_widget]
                                    widget.setEnabled(True)
                                    checked = (trial_widget.upper()
                                               .endswith('_'+str(val).upper()))
                                    widget.setChecked(checked)
                        case _:
                            assert False, f'Unknown param type {param_type}'

        self._update_param_state_and_inst(new_param_state)

        # Update the buttons
        self._update_load_onoff_button()
        self._update_short_onoff_button()
        self._update_trigger_buttons()

        # Maybe update the List table
        if self._cur_overall_mode == 'List':
            self._update_list_table_graph()

        # Update the Enable Measurements checkboxes
        self._widget_registry['EnableV'].setChecked(self._enable_measurement_v)
        self._widget_registry['EnableC'].setChecked(self._enable_measurement_c)
        self._widget_registry['EnableP'].setChecked(self._enable_measurement_p)
        self._widget_registry['EnableR'].setChecked(self._enable_measurement_r)
        self._widget_registry['EnableTRise'].setChecked(self._enable_measurement_trise)
        self._widget_registry['EnableTFall'].setChecked(self._enable_measurement_tfall)

        # If TRise and TFall are turned off, then also disable their measurement
        # display just to save space, since these are rare functions to actually
        # user. Note they will have been turned on in the code above as part of the
        # normal widget actions for Basic mode, so we only have to worry about hiding
        # them here, not showing them.
        if not self._enable_measurement_trise and not self._enable_measurement_tfall:
            self._widget_registry['MeasureTRise'].hide()
            self._widget_registry['MeasureTFall'].hide()

        # Finally, we don't allow parameters to be modified during certain modes
        if (self._cur_overall_mode in ('Battery', 'List') and
            self._param_state[':INPUT:STATE']):
            # Battery or List mode is running
            self._widget_registry['FrameMode'].setEnabled(False)
            self._widget_registry['FrameConstant'].setEnabled(False)
            self._widget_registry['FrameRange'].setEnabled(False)
            self._widget_registry['FrameMainParameters'].setEnabled(False)
            self._widget_registry['FrameAuxParameters'].setEnabled(False)
            self._widget_registry['GlobalParametersRow'].setEnabled(False)
        elif self._cur_overall_mode == 'Ext \u26A0' and self._param_state[':INPUT:STATE']:
            # External control mode - can't change range
            self._widget_registry['FrameRange'].setEnabled(False)
        else:
            self._widget_registry['FrameMode'].setEnabled(True)
            self._widget_registry['FrameConstant'].setEnabled(True)
            self._widget_registry['FrameRange'].setEnabled(True)
            self._widget_registry['FrameMainParameters'].setEnabled(True)
            self._widget_registry['FrameAuxParameters'].setEnabled(True)
            self._widget_registry['GlobalParametersRow'].setEnabled(True)
            self._widget_registry['MainParametersLabel_BattC'].setEnabled(True)
            self._widget_registry['MainParameters_BattC'].setEnabled(True)

        status_msg = None
        if self._cur_overall_mode == 'List':
            status_msg = """Turn on load. Use TRIG to start/pause list progression.
List status tracking is an approximation."""
        if status_msg is None:
            self._statusbar.clearMessage()
        else:
            self._statusbar.showMessage(status_msg)

        self._disable_callbacks = False

    def _update_list_table_graph(self, update_table=True, list_step_only=False):
        """Update the list table and associated plot if data has changed."""
        if self._cur_overall_mode != 'List':
            return
        vrange = float(self._param_state[':LIST:VRANGE'])
        irange = float(self._param_state[':LIST:IRANGE'])
        # If the ranges changed, we may have to clip the values in the table
        match self._cur_const_mode:
            case 'Voltage':
                self._list_mode_levels = [min(x, vrange)
                                          for x in self._list_mode_levels]
            case 'Current':
                self._list_mode_levels = [min(x, irange)
                                          for x in self._list_mode_levels]
            case 'Power':
                self._list_mode_levels = [min(x, self._inst._max_power)
                                          for x in self._list_mode_levels]
            # Nothing to do for Resistance since its max is largest
        table = self._widget_registry['ListTable']
        step = self._param_state[':LIST:STEP']
        widths = (90, 70, 80)
        match self._cur_const_mode:
            case 'Voltage':
                hdr = ('Voltage (V)', 'Time (s)')
                fmts = ('.3f', '.3f')
                ranges = ((0, vrange), (0.001, 999))
            case 'Current':
                hdr = ['Current (A)', 'Time (s)', 'Slew (A/\u00B5s)']
                fmts = ['.3f', '.3f', '.3f']
                if irange == 5:
                    ranges = ((0, irange), (0.001, 999), (0.001, 0.5))
                else:
                    ranges = ((0, irange), (0.001, 999), (0.001, 2.5))
            case 'Power':
                hdr = ['Power (W)', 'Time (s)']
                fmts = ['.2f', '.3f']
                ranges = ((0, self._inst._max_power), (0.001, 999))
            case 'Resistance':
                hdr = ['Resistance (\u2126)', 'Time (s)']
                fmts = ['.3f', '.3f']
                ranges = ((0.03, 10000), (0.001, 999))
        self._list_mode_levels = [min(max(x, ranges[0][0]), ranges[0][1])
                                  for x in self._list_mode_levels]
        self._list_mode_widths = [min(max(x, ranges[1][0]), ranges[1][1])
                                  for x in self._list_mode_widths]
        if len(ranges) == 3:
            self._list_mode_slews = [min(max(x, ranges[2][0]), ranges[2][1])
                                     for x in self._list_mode_slews]
        if update_table:
            # We don't always want to update the table, because in edit mode when the
            # user changes a value, the table will have already been updated internally,
            # and if we mess with it here it screws up the focus for the edit box and
            # the edit box never closes.
            data = []
            for i in range(step):
                if self._cur_const_mode == 'Current':
                    data.append([self._list_mode_levels[i],
                                 self._list_mode_widths[i],
                                 self._list_mode_slews[i]])
                else:
                    data.append([self._list_mode_levels[i],
                                 self._list_mode_widths[i]])
            table.model().set_params(data, fmts, hdr)
            for i, fmt in enumerate(fmts):
                table.setItemDelegateForColumn(
                    i, DoubleSpinBoxDelegate(self, fmt, ranges[i]))
                table.setColumnWidth(i, widths[i])

        # Update the List plot
        min_plot_y = 0
        max_plot_y = max(self._list_mode_levels[:step])
        if not list_step_only:
            plot_x = [0]
            plot_y = [self._list_mode_levels[0]]
            for i in range(step-1):
                x_val = plot_x[-1] + self._list_mode_widths[i]
                plot_x.append(x_val)
                plot_x.append(x_val)
                plot_y.append(self._list_mode_levels[i])
                plot_y.append(self._list_mode_levels[i+1])
            plot_x.append(plot_x[-1]+self._list_mode_widths[step-1])
            plot_y.append(self._list_mode_levels[step-1])
            plot_widget = self._widget_registry['ListPlot']
            self._list_mode_level_plot.setData(plot_x, plot_y)
            plot_widget.setLabel(axis='left', text=hdr[0])
            plot_widget.setLabel(axis='bottom', text='Cumulative Time (s)')
            plot_widget.setYRange(min_plot_y, max_plot_y)

        # Update the running plot and highlight the appropriate table row
        if self._list_mode_cur_step_num is not None:
            delta = 0
            step_num = self._list_mode_cur_step_num
            if self._list_mode_running:
                delta = time.time() - self._list_mode_cur_step_start_time
            else:
                # When we pause List mode, we end at the end of the previous step,
                # not the start of the next step
                step_num = (step_num-1) % self._param_state[':LIST:STEP']
                delta = self._list_mode_widths[step_num]
            cur_step_x = 0
            if step_num > 0:
                cur_step_x = sum(self._list_mode_widths[:step_num])
            cur_step_x += delta
            self._list_mode_step_plot.setData([cur_step_x, cur_step_x],
                                              [min_plot_y, max_plot_y])
            table.model().set_highlighted_row(step_num)
        else:
            table.model().set_highlighted_row(None)
            self._list_mode_step_plot.setData([], [])

    def _update_list_table_heartbeat(self):
        """Handle the rapid heartbeat when in List mode to update the highlighting."""
        if self._list_mode_running:
            cur_time = time.time()
            delta = cur_time - self._list_mode_cur_step_start_time
            if delta >= self._list_mode_widths[self._list_mode_cur_step_num]:
                # We've moved on to the next step (or more than one step)
                if self._list_mode_stopping:
                    self._list_mode_stopping = False
                    self._list_mode_running = False
                    self._list_mode_timer.stop()
                while delta >= self._list_mode_widths[self._list_mode_cur_step_num]:
                    delta -= self._list_mode_widths[self._list_mode_cur_step_num]
                    self._list_mode_cur_step_num = (
                        self._list_mode_cur_step_num+1) % self._param_state[':LIST:STEP']
                self._list_mode_cur_step_start_time = cur_time - delta
            self._update_list_table_graph(list_step_only=True)

    def _cur_mode_param_info(self, null_dynamic_mode_ok=False):
        if self._cur_overall_mode == 'Dynamic':
            if null_dynamic_mode_ok and self._cur_dynamic_mode is None:
                # We fake this here for refresh(), where we don't know the dynamic
                # mode until we know we're in the dynamic mode itself...catch 22
                key = (self._cur_overall_mode, self._cur_const_mode, 'Continuous')
            else:
                key = (self._cur_overall_mode, self._cur_const_mode,
                       self._cur_dynamic_mode)
        else:
            key = (self._cur_overall_mode, self._cur_const_mode)
        return _SDL_MODE_PARAMS[key]

    def _update_param_state_and_inst(self, new_param_state):
        for key, data in new_param_state.items():
            if data != self._param_state[key]:
                self._update_one_param_on_inst(key, data)
                self._param_state[key] = data

    def _update_one_param_on_inst(self, key, data):
        fmt_data = data
        if isinstance(data, bool):
            fmt_data = '1' if True else '0'
        elif isinstance(data, float):
            fmt_data = '%.6f' % data
        elif isinstance(data, int):
            fmt_data = int(data)
        elif isinstance(data, str):
            # This is needed because there are a few places when the instrument
            # is case-sensitive to the SCPI argument! For example,
            # "TRIGGER:SOURCE Bus" must be "BUS"
            fmt_data = data.upper()
        else:
            assert False
        self._inst.write(f'{key} {fmt_data}')

    def _reset_batt_log(self):
        self._batt_log_modes = []
        self._batt_log_stop_cond = []
        self._batt_log_start_times = []
        self._batt_log_end_times = []
        self._batt_log_run_times = []
        self._batt_log_initial_voltage = None
        self._batt_log_initial_voltages = []
        self._batt_log_caps = []

    @staticmethod
    def _time_to_str(t):
        return time.strftime('%Y %b %d %H:%M:%S', time.localtime(t))

    @staticmethod
    def _time_to_hms(t):
        m, s = divmod(t, 60)
        h, m = divmod(m, 60)
        return '%02d:%02d:%02d' % (h, m, s)

    def _batt_log_report(self):
        n_entries = len(self._batt_log_start_times)
        if n_entries == 0:
            return None
        single = (n_entries == 1)
        ret = f'Test device: {self._inst.manufacturer} {self._inst.model}\n'
        ret += f'S/N: {self._inst.serial_number}\n'
        ret += f'Firmware: {self._inst.firmware_version}\n'
        if not single:
            ret += '** Overall test **\n'
        ret += 'Start time: '+self._time_to_str(self._batt_log_start_times[0])+'\n'
        ret += 'End time: '+self._time_to_str(self._batt_log_end_times[-1])+'\n'
        t = self._batt_log_end_times[-1]-self._batt_log_start_times[0]
        ret += 'Elapsed time: '+self._time_to_hms(t)+'\n'
        if not single:
            t = sum(self._batt_log_run_times)
            ret += 'Test time: '+self._time_to_hms(t)+'\n'
        if single:
            ret += 'Test mode: '+self._batt_log_modes[0]+'\n'
            ret += 'Stop condition: '+self._batt_log_stop_cond[0]+'\n'
            if self._batt_log_initial_voltages[0] is None:
                ret += 'Initial voltage: Not measured\n'
            else:
                init_v = self._batt_log_initial_voltages[0]
                ret += f'Initial voltage: {init_v:.3f}V\n'
        cap = sum(self._batt_log_caps)
        ret += f'Capacity: {cap:.3f}Ah\n'
        if not single:
            for i in range(n_entries):
                ret += f'** Test segment #{i+1}  **\n'
                ret += 'Start time: '+self._time_to_str(self._batt_log_start_times[i])
                ret += '\n'
                ret += 'End time: '+self._time_to_str(self._batt_log_end_times[i])+'\n'
                ret += 'Test time: '+self._time_to_hms(self._batt_log_run_times[i])+'\n'
                ret += 'Test mode: '+self._batt_log_modes[i]+'\n'
                ret += 'Stop condition: '+self._batt_log_stop_cond[i]+'\n'
                if self._batt_log_initial_voltages[i] is None:
                    ret += 'Initial voltage: Not measured\n'
                else:
                    init_v = self._batt_log_initial_voltages[i]
                    ret += f'Initial voltage: {init_v:.3f}V\n'
                cap = self._batt_log_caps[i]
                ret += f'Capacity: {cap:.3f}Ah\n'
        return ret


##########################################################################################
##########################################################################################
##########################################################################################


class InstrumentSiglentSPD3303(Device4882):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._long_name = f'SPD3303 @ {self._resource_name}'
        if self._resource_name.startswith('TCPIP'):
            ips = self._resource_name.split('.') # This only works with TCP!
            self._name = f'SPD{ips[-1]}'
        else:
            self._name = 'SPD'

    def connect(self, *args, **kwargs):
        super().connect(*args, **kwargs)
        idn = self.idn().split(',')
        if len(idn) != 4:
            assert ValueError
        (self._manufacturer,
         self._model,
         self._serial_number,
         self._firmware_version,
         self._hardware_version) = idn
        if self._manufacturer != 'Siglent Technologies':
            assert ValueError
        if not self._model.startswith('SPD'):
            assert ValueError
        self._long_name = f'{self._model} @ {self._resource_name}'
        self.write(':SYST:REMOTE:STATE 1') # Lock the keyboard

    def disconnect(self, *args, **kwargs):
        self.write(':SYST:REMOTE:STATE 0')
        super().disconnect(*args, **kwargs)

    def configure_widget(self, main_window):
        return InstrumentSiglentSPD3303ConfigureWidget(main_window, self)

    def set_input_state(self, val):
        self._validator_1(val)
        self.write(f':INPUT:STATE {val}')

    def measure_voltage(self, ch):
        return float(self.query(f'MEAS:VOLT? CH{ch}'))

    def measure_current(self, ch):
        return float(self.query(f'MEAS:CURR? CH{ch}'))

    def measure_power(self, ch):
        return float(self.query(f'MEAS:POWER? CH{ch}'))

    def measure_vcp(self, ch):
        return (self.measure_voltage(ch),
                self.measure_current(ch),
                self.measure_power(ch))
