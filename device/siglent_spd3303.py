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

from PyQt6.QtWidgets import (QAbstractSpinBox,
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
                             QVBoxLayout,
                             QWidget)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor

import pyqtgraph as pg

from .device import Device4882
from .config_widget_base import (ConfigureWidgetBase,
                                 DoubleSpeedSpinBox,
                                 DoubleSpinBoxDelegate,
                                 ListTableModel,
                                 LongClickButton)


# Style sheets for different operating systems
_STYLE_SHEET = {
    'TimerTable': {
        'windows': """QTableView { min-width: 17em; max-width: 17em;
                                   min-height: 11em; max-height: 11em; }""",
        'linux': """QTableView { min-width: 18em; max-width: 18em;
                                 min-height: 10em; max-height: 10em; }""",
    },
    'TimerPlot': {
        'windows': (300, 178),
        'linux': (485, 172),
    },
}

_PRESETS = [
    [ 2.5, 3.2],
    [ 3.3, 3.2],
    [ 5.0, 3.2],
    [12.0, 3.2],
    [13.8, 3.2],
    [24.0, 3.2]
]

# This class encapsulates the main SDL configuration widget.

class InstrumentSiglentSPD3303ConfigureWidget(ConfigureWidgetBase):
    def __init__(self, *args, **kwargs):
        # Widgets that can be hidden
        # These could be put in the widget registry but this makes them easier to
        # find
        self._widgets_minmax_limits = []
        self._widgets_setpoints = []
        # self._widgets_adjustment_knobs = []
        self._widgets_preset_buttons = []
        self._widgets_timer = []
        self._widgets_on_off_buttons = []
        self._widgets_measurements = []

        # Widget registry for various widgets we want to read or write
        self._widget_registry = {}

        # Power supply parameters
        self._psu_voltage = [0., 0.]
        self._psu_current = [0., 0.]
        self._psu_timer_params = [[[0., 0., 0.]]*5, [[0., 0., 0.]]*5]
        self._psu_on_off = [False, False, False]
        self._psu_cc = [False, False]
        self._psu_mode = 'I'

        # Presets
        self._presets = [_PRESETS[:], _PRESETS[:]]

        # We have to fake the progress of the steps in Timer mode because there is no
        # SCPI command to find out what step we are currently on, so we do it by
        # looking at the elapsed time and hope the instrument and the computer stay
        # roughly synchronized. But if they fall out of sync there's no way to get
        # them back in sync except starting the Time sequence over.

        # The time the most recent Timer step was started
        self._timer_mode_running = [False, False]
        self._timer_mode_cur_step_start_time = [None, None]
        self._timer_mode_cur_step_num = [None, None]

        # Stored measurements and triggers
        self._cached_measurements = None
        self._cached_triggers = None

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
        self._timer_mode_timer = QTimer(self._main_window.app)
        self._timer_mode_timer.timeout.connect(self._update_timer_table_heartbeat)
        self._timer_mode_timer.setInterval(250)

    ######################
    ### Public methods ###
    ######################

    # This reads instrument -> internal parameter state
    def refresh(self):
        """Read all parameters from the instrument and set our internal state to match."""
        status = int(self._inst.query('SYST:STATUS?').replace('0x', ''), base=16)
        for ch in range(2):
            self._psu_voltage[ch] = float(self._inst.query(f'CH{ch+1}:VOLT?'))
            self._psu_current[ch] = float(self._inst.query(f'CH{ch+1}:CURRENT?'))
            self._psu_on_off[ch] = bool(status & (1 << (ch+4)))
            for entry in range(5):
                # TIMER:SET? returns an extra comma at the end for some reason
                res = self._inst.query(f'TIMER:SET? CH{ch+1},{entry+1}').split(',')
                volt = float(res[0])
                curr = float(res[1])
                timer = float(res[2])
                self._psu_timer_params[ch][entry] = [volt, curr, timer]
        # There's no way to know if CH3 is on or off
        self._psu_on_off[2] = False
        match status & 0x0C:
            case 0x04:
                self._psu_mode = 'I'
            case 0x08:
                self._psu_mode = 'P'
            case 0x0C:
                self._psu_mode = 'S'

        self._update_widgets()

    # This writes internal parameter state -> instrument (opposite of refresh)
    def update_instrument(self):
        """Update the instrument with the current parameter state."""
        status = 0
        for ch in range(2):
            volt = self._psu_voltage[ch]
            curr = self._psu_current[ch]
            self._inst.write(f'CH{ch+1}:VOLT {volt:.3f}')
            self._inst.write(f'CH{ch+1}:CURR {volt:.3f}')
            status |= (1 << (ch+4)) and self._psu_on_off[ch]
            for entry in range(5):
                volt, curr, timer = self._psu_timer_params[ch][entry]
                res = self._inst.write(
                    f'TIMER:SET CH{ch+1},{entry+1},{volt:.3f},{curr:.3f},{timer:.3f}')
        for ch in range(3):
            on_off = 'ON' if self._psu_on_off[ch] else 'OFF'
            self._inst.write(f'OUTPUT CH{ch+1},{on_off}')
        match self._psu_mode:
            case 'I':
                status |= 0x04
            case 'P':
                status |= 0x08
            case 'S':
                status |= 0x0C

# SYST:STATUS? (returns hex)
#   0 - CH1 CV/CC
#   1 - CH2 CV/CC
#   2,3 - 01: Ind, 10: Parallel, 11: Serial
#   6 - TIMER1 off/on
#   7 - TIMER2 off/on
#   8 - CH1 analog, waveform
#   9 - CH2 analog, waveform


    def update_measurements_and_triggers(self, read_inst=True):
        """Read current values, update control panel display, return the values."""
        if read_inst:
            status = int(self._inst.query('SYST:STATUS?').replace('0x', ''), base=16)
            self._psu_cc[0] = bool(status & 0x01)
            self._psu_cc[1] = bool(status & 0x02)
            self._psu_on_off[0] = bool(status & 0x10)
            self._psu_on_off[1] = bool(status & 0x20)
            self._update_output_on_off_buttons()

        measurements = {}
        triggers = {}

        triggers['CH1On'] = {'name': 'CH1 On',
                             'val':  self._psu_on_off[0]}
        triggers['CH2On'] = {'name': 'CH2 On',
                             'val':  self._psu_on_off[1]}
        triggers['CH1CV'] = {'name': 'CH1 CV Mode',
                             'val':  not self._psu_cc[0]}
        triggers['CH2CV'] = {'name': 'CH2 CV Mode',
                             'val':  not self._psu_cc[1]}
        triggers['CH1CC'] = {'name': 'CH1 CC Mode',
                             'val':  self._psu_cc[0]}
        triggers['CH2CC'] = {'name': 'CH2 CC Mode',
                             'val':  self._psu_cc[1]}
        triggers['CH1TimerRunning'] = {'name': 'CH1 Timer Running',
                                       'val':  self._timer_mode_running[0]}
        triggers['CH2TimerRunning'] = {'name': 'CH2 Timer Running',
                                       'val':  self._timer_mode_running[1]}

        for ch in range(2):
            voltage = None
            if read_inst:
                w = self._widget_registry[f'MeasureV{ch}']
                if not self._enable_measurement_v or not self._psu_on_off[ch]:
                    w.setText('---  V')
                else:
                    voltage = self._inst.measure_voltage(ch+1)
                    w.setText(f'{voltage:6.3f} V')
            measurements[f'Voltage{ch+1}'] = {'name':  f'CH{ch+1} Voltage',
                                              'unit':  'V',
                                              'val':   voltage}

            current = None
            if read_inst:
                w = self._widget_registry[f'MeasureC{ch}']
                if not self._enable_measurement_c or not self._psu_on_off[ch]:
                    w.setText('---  A')
                else:
                    current = self._inst.measure_current(ch+1)
                    w.setText(f'{current:5.3f} A')
            measurements[f'Current{ch+1}'] = {'name':  f'CH{ch+1} Current',
                                              'unit':  'A',
                                              'val':   current}

            power = None
            if read_inst:
                w = self._widget_registry[f'MeasureP{ch}']
                if not self._enable_measurement_p or not self._psu_on_off[ch]:
                    w.setText('---  W')
                else:
                    power = self._inst.measure_power(ch+1)
                    w.setText(f'{power:6.3f} W')
            measurements[f'Power{ch+1}'] = {'name':  f'CH{ch+1} Power',
                                            'unit':  'W',
                                            'val':   power}

        self._cached_measurements = measurements
        self._cached_triggers = triggers
        return measurements, triggers

    def get_measurements(self):
        """Return most recently cached measurements."""
        if self._cached_measurements is None:
            self.update_measurements_and_triggers()
        return self._cached_measurements

    def get_triggers(self):
        """Return most recently cached triggers."""
        if self._cached_triggers is None:
            self.update_measurements_and_triggers()
        return self._cached_triggers

    ############################################################################
    ### Setup Window Layout
    ############################################################################

    def _init_widgets(self):
        """Set up all the toplevel widgets."""
        toplevel_widget = self._toplevel_widget(has_reset=False)

        ### Add to Device menu

        action = QAction('&Independent', self, checkable=True)
        self._widget_registry['IndependentAction'] = action
        action.triggered.connect(self._menu_do_device_independent)
        self._menubar_device.addAction(action)
        action = QAction('&Series', self, checkable=True)
        self._widget_registry['SeriesAction'] = action
        action.triggered.connect(self._menu_do_device_series)
        self._menubar_device.addAction(action)
        action = QAction('&Parallel', self, checkable=True)
        self._widget_registry['ParallelAction'] = action
        action.triggered.connect(self._menu_do_device_parallel)
        self._menubar_device.addAction(action)

        ### Add to View menu

        action = QAction('&Min/Max Limits', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_minmax_limits)
        self._menubar_view.addAction(action)
        # action = QAction('&Adjustment Knobs', self, checkable=True)
        # action.setChecked(True)
        # action.triggered.connect(self._menu_do_view_adjustment_knobs)
        # self._menubar_view.addAction(action)
        action = QAction('&Set Points', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_setpoints)
        self._menubar_view.addAction(action)
        action = QAction('&Presets', self, checkable=True)
        self._widget_registry['PresetsAction'] = action
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_presets)
        self._menubar_view.addAction(action)
        action = QAction('&Timer', self, checkable=True)
        self._widget_registry['TimerAction'] = action
        action.setChecked(False)
        action.triggered.connect(self._menu_do_view_timer)
        self._menubar_view.addAction(action)
        action = QAction('&Output On/Off', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_output_on_off)
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
        frame = self._init_widgets_add_channel(0)
        self._widget_registry['FrameCH1'] = frame
        main_horiz_layout.addWidget(frame)
        frame = self._init_widgets_add_channel(1)
        self._widget_registry['FrameCH2'] = frame
        main_horiz_layout.addWidget(frame)

        self.show()

        self._update_widgets()

    def _init_widgets_add_channel(self, ch):
        """Set up the widgets for one channel."""
        frame = QGroupBox(f'Channel {ch+1}')
        if ch == 0:
            bgcolor = '#a0ff80'
        else:
            bgcolor = '#ffff20'
        ss = f"""\QGroupBox::title {{ subcontrol-position: top center;
                                      background-color: {bgcolor}; color: black; }}"""
        frame.setStyleSheet(ss)

        vert_layout = QVBoxLayout(frame)
        vert_layout.setContentsMargins(0, 0, 0, 0)

        layoutg = QGridLayout()
        layoutg.setSpacing(0)
        vert_layout.addLayout(layoutg)

        ###### ROW 1 - MIN/MAX LIMITS ######

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
                input = DoubleSpeedSpinBox(1.)
                input.wid = (mm, cv, ch)
                input.setAlignment(Qt.AlignmentFlag.AlignRight)
                input.setSuffix(f' {cvu}')
                input.setDecimals(3)
                if cv == 'V':
                    input.setRange(0, 32)
                    if mm == 'Min':
                        input.setValue(0)
                    else:
                        input.setValue(32)
                else:
                    input.setRange(0, 3.2)
                    if mm == 'Min':
                        input.setValue(0)
                    else:
                        input.setValue(3.2)
                input.editingFinished.connect(self._on_value_change)
                layoutg2.addWidget(input, mm_num, 1, Qt.AlignmentFlag.AlignLeft)
                self._widget_registry[f'{mm}{ch}{cv}'] = input
            layouth.addStretch()

            ###### ROW 2 - MAIN V/C INPUTS ######

            # Main V/C inputs
            ss = """font-size: 30px; min-width: 4em; max-width: 4em;"""
            input = DoubleSpeedSpinBox(1.)
            input.wid = ('SetPoint', cv, ch)
            self._widgets_setpoints.append(input)
            input.setStyleSheet(ss)
            input.setAlignment(Qt.AlignmentFlag.AlignRight)
            input.setSuffix(f' {cvu}')
            input.setDecimals(3)
            if cv == 'V':
                input.setRange(0, 32)
            else:
                input.setRange(0, 3.2)
            input.editingFinished.connect(self._on_value_change)
            layouth = QHBoxLayout()
            layoutg.addLayout(layouth, 2, cv_num)
            layouth.addStretch()
            layouth.addWidget(input)
            layouth.addStretch()
            self._widget_registry[f'SetPoint{ch}{cv}'] = input

            # Adjustment knobs
            # w = QWidget()
            # self._widgets_adjustment_knobs.append(w)
            # layoutg2 = QGridLayout(w)
            # layoutg2.setSpacing(0)
            # layoutg2.setContentsMargins(0,0,0,0)
            # layoutg.addWidget(w, 3, cv_num)
            # ss = """max-width: 5.5em; max-height: 5.5em;
            #         background-color:yellow; border: 1px;"""
            # ss2 = """max-width: 4.5em; max-height: 4.5em;"""
            # for cf_num, cf in enumerate(('Coarse', 'Fine')):
            #     dial = QDial()
            #     if cf == 'Coarse':
            #         dial.setStyleSheet(ss)
            #     else:
            #         dial.setStyleSheet(ss2)
            #     dial.setWrapping(True)
            #     layoutg2.addWidget(dial, 0, cf_num, Qt.AlignmentFlag.AlignCenter)
            #     layoutg2.addWidget(QLabel(f'{cf} {cv}'), 1, cf_num,
            #                        Qt.AlignmentFlag.AlignCenter)

        ###### ROW 3 - PRESET BUTTONS ######

        # Preset buttons
        w = QWidget()
        vert_layout.addWidget(w)
        self._widgets_preset_buttons.append(w)
        layoutg = QGridLayout(w)
        ss = """QPushButton { min-width: 7em; max-width: 7em;
                              min-height: 1em; max-height: 1em;
                              font-weight: bold;
                              border-radius: 0.5em; border: 2px solid black; }
                QPushButton::pressed { border: 3px solid black; }"""
        for preset_num in range(6):
            row, column = divmod(preset_num, 2)
            button = LongClickButton(f'32.000V / 3.200A',
                                     self._on_preset_clicked,
                                     self._on_preset_long_click)
            button.wid = (ch, preset_num)
            button.setStyleSheet(ss)
            layoutg.addWidget(button, row, column)
            self._widget_registry[f'Preset{ch}_{preset_num}'] = button

        ###### ROW 4 - TIMER MODE ######

        w = QWidget()
        w.hide()
        vert_layout.addWidget(w)
        layoutv = QVBoxLayout()
        layoutv.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layoutv)
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        layoutv.addLayout(row_layout)
        self._widgets_timer.append(w)

        row_layout.addStretch()
        table = QTableView(alternatingRowColors=True)
        f = lambda *args, **kwargs: self._on_timer_table_change(ch, *args, **kwargs)
        table.setModel(ListTableModel(f))
        row_layout.addWidget(table)
        table.setStyleSheet(_STYLE_SHEET['TimerTable'][self._style_env])
        table.verticalHeader().setMinimumWidth(30)
        self._widget_registry[f'TimerTable{ch}'] = table
        row_layout.addStretch()

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        layoutv.addLayout(row_layout)
        pw = pg.plot()
        pw.showAxis('right')
        # Disable zoom and pan
        pw.plotItem.setMouseEnabled(x=False, y=False)
        pw.plotItem.setMenuEnabled(False)

        pw.setLabel('left', 'Voltage', units='V', color='#ff4040')
        pw.getAxis('left').setPen(pg.mkPen(color='#ff4040', width=1))
        pdi = pw.plot([], [], pen=pg.mkPen(color='#ff4040', width=2))
        self._widget_registry[f'TimerVPlotItem{ch}'] = pdi

        pw.setLabel('right', 'Current', units='A', color='#40ff40')
        pw.getAxis('right').setPen(pg.mkPen(color='#40ff40', width=1))
        pdi = pg.PlotDataItem(pen=pg.mkPen(color='#40ff40', width=3))
        self._widget_registry[f'TimerIPlotItem{ch}'] = pdi

        pw2 = pg.ViewBox()
        pw2.setMouseEnabled(x=False, y=False)
        pw2.setMenuEnabled(False)
        pw.scene().addItem(pw2)
        pw.getAxis('right').linkToView(pw2)
        pw2.setXLink(pw)
        pw2.addItem(pdi)

        self._widget_registry[f'TimerStepPlot{ch}'] = pw.plot([], pen=1)
        size = _STYLE_SHEET['TimerPlot'][self._style_env]
        pw.setMaximumSize(size[0], size[1]) # XXX Warning magic constants!
        row_layout.addWidget(pw)
        pw.setLabel(axis='bottom', text='Cumulative Time (s)')
        self._widget_registry[f'TimerPlotV{ch}'] = pw
        self._widget_registry[f'TimerPlotI{ch}'] = pw2
        pw.getViewBox().sigResized.connect(self._on_timer_plot_resize)

        row_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ###### ROW 5 - ON/OFF BUTTON ######

        # On/Off button
        w = QWidget()
        vert_layout.addWidget(w)
        self._widgets_on_off_buttons.append(w)
        layouth = QHBoxLayout(w)
        layouth.addStretch()
        button = QPushButton('OUTPUT ON (CV)')
        button.wid = ch
        button.clicked.connect(self._on_click_output_on_off)
        layouth.addWidget(button)
        self._widget_registry[f'OutputOnOff{ch}'] = button
        layouth.addStretch()

        ###### ROW 6 - MEASUREMENTS ######

        # Measurements
        w = QWidget()
        vert_layout.addWidget(w)
        w.setStyleSheet('background: black;')
        layoutv = QVBoxLayout(w)
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

    ############################################################################
    ### Action and Callback Handlers
    ############################################################################

    def _menu_do_about(self):
        """Show the About box."""
        msg = f"""Siglent SPD3303X-series instrument interface.

Copyright 2022, Robert S. French.

Supported instruments: SPD3303X, SPD3303X-E.

Connected to {self._inst._resource_name}
    {self._inst._model}
    S/N {self._inst._serial_number}
    HW {self._inst._hardware_version}
    FW {self._inst._firmware_version}"""

        QMessageBox.about(self, 'About', msg)

    def _menu_do_save_configuration(self):
        """Save the current configuration to a file."""
        fn = QFileDialog.getSaveFileName(self, caption='Save Configuration',
                                         filter='All (*.*);;SPD Configuration (*.spdcfg)',
                                         initialFilter='SPD Configuration (*.spdcfg)')
        fn = fn[0]
        if not fn:
            return
        cfg = {}
        for ch in range(2):
            volt = self._psu_voltage[ch]
            cfg[f'CH{ch+1}:VOLT'] = f'{volt:.3f}'
            curr = self._psu_current[ch]
            cfg[f'CH{ch+1}:CURR'] = f'{curr:.3f}'
            for num in range(5):
                v, c, t = self._psu_timer_params[ch][num]
                cfg[f'TIMER:SET CH{ch+1},{num+1}'] = f'{v:.3f},{c:.3f},{t:.3f}'
            for num in range(len(self._presets[ch])):
                v, c = self._presets[ch][num]
                cfg[f'CH{ch+1}:PRESET {num+1}'] = f'{v:.3f},{c:.3f}'
            for mm in ('Min', 'Max'):
                for cv in ('V', 'I'):
                    key1 = f'{mm}{ch}{cv}'
                    key2 = f'{mm}{ch+1}{cv}'
                    v = self._widget_registry[key1].value()
                    cfg[key2] = f'{v:.3f}'

        match self._psu_mode:
            case 'I':
                cfg['OUTPUT:TRACK'] = 0
            case 'S':
                cfg['OUTPUT:TRACK'] = 1
            case 'P':
                cfg['OUTPUT:TRACK'] = 2
            case _:
                assert False, self._psu_mode

        with open(fn, 'w') as fp:
            json.dump(cfg, fp, sort_keys=True, indent=4)

    def _menu_do_load_configuration(self):
        """Load the current configuration from a file."""
        fn = QFileDialog.getOpenFileName(self, caption='Load Configuration',
                                         filter='All (*.*);;SPD Configuration (*.spdcfg)',
                                         initialFilter='SPD Configuration (*.spdcfg)')
        fn = fn[0]
        if not fn:
            return
        with open(fn, 'r') as fp:
            cfg = json.load(fp)
        # Be safe by turning off the outputs before changing values
        match cfg['OUTPUT:TRACK']:
            case 0:
                self._psu_mode = 'I'
                self._inst.write('OUTPUT:TRACK 0')
            case 1:
                self._psu_mode = 'S'
                self._inst.write('OUTPUT:TRACK 1')
            case 2:
                self._psu_mode = 'P'
                self._inst.write('OUTPUT:TRACK 2')
            case _:
                assert False, cfg['OUTPUT:TRACK']
        self._update_output_state(0, False)
        max_ch = 2
        if self._psu_mode == 'I':
            max_ch = 2
            self._update_output_state(1, False)
        else:
            max_ch = 1
        for ch in range(max_ch):
            key = f'CH{ch+1}:VOLT'
            volt = cfg[key]
            self._psu_voltage[ch] = float(volt)
            self._inst.write(f'{key} {volt}')
            key = f'CH{ch+1}:CURR'
            curr = cfg[key]
            self._psu_current[ch] = float(curr)
            self._inst.write(f'{key} {curr}')
            for num in range(5):
                key = f'TIMER:SET CH{ch+1},{num+1}'
                val = cfg[key]
                self._inst.write(f'{key},{val}')
                v, c, t = [float(x) for x in val.split(',')]
                self._psu_timer_params[ch][num] = [v, c, t]
            for num in range(len(self._presets[ch])):
                key = f'CH{ch+1}:PRESET {num+1}'
                val = cfg[key]
                v, c = [float(x) for x in val.split(',')]
                self._presets[ch][num] = [v, c]
            for mm in ('Min', 'Max'):
                for cv in ('V', 'I'):
                    key1 = f'{mm}{ch}{cv}'
                    key2 = f'{mm}{ch+1}{cv}'
                    self._widget_registry[key1].setValue(float(cfg[key2]))
        self._update_widgets()

    def _menu_do_device_independent(self, state):
        """Handle Device Independent menu."""
        self._widget_registry['IndependentAction'].setChecked(True)
        self._widget_registry['SeriesAction'].setChecked(False)
        self._widget_registry['ParallelAction'].setChecked(False)
        self._psu_mode = 'I'
        self._psu_on_off[0] = False
        self._psu_on_off[1] = False
        self._inst.write('OUTPUT:TRACK 0') # Turns off the outputs
        self._update_widgets()

    def _menu_do_device_series(self, state):
        """Handle Device Series menu."""
        self._widget_registry['IndependentAction'].setChecked(False)
        self._widget_registry['SeriesAction'].setChecked(True)
        self._widget_registry['ParallelAction'].setChecked(False)
        self._psu_mode = 'S'
        self._psu_on_off[0] = False
        self._psu_on_off[1] = False
        self._inst.write('OUTPUT:TRACK 1') # Turns off the outputs
        self._update_widgets()

    def _menu_do_device_parallel(self, state):
        """Handle Device Parallel menu."""
        self._widget_registry['IndependentAction'].setChecked(False)
        self._widget_registry['SeriesAction'].setChecked(False)
        self._widget_registry['ParallelAction'].setChecked(True)
        self._psu_mode = 'P'
        self._psu_on_off[0] = False
        self._psu_on_off[1] = False
        self._inst.write('OUTPUT:TRACK 2') # Turns off the outputs
        self._update_widgets()

    def _menu_do_view_minmax_limits(self, state):
        """Toggle visibility of the min/max limit spinboxes."""
        for w in self._widgets_minmax_limits:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_setpoints(self, state):
        """Toggle visibility of the setpoint spinboxes."""
        for w in self._widgets_setpoints:
            if state:
                w.show()
            else:
                w.hide()

    # def _menu_do_view_adjustment_knobs(self, state):
    #     """Toggle visibility of the adjustment knobs."""
    #     for w in self._widgets_adjustment_knobs:
    #         if state:
    #             w.show()
    #         else:
    #             w.hide()

    def _menu_do_view_presets(self, state):
        """Toggle visibility of the preset buttons."""
        if state:
            # When presets are shown, we turn off timer
            self._menu_do_view_timer(False)
            self._widget_registry['TimerAction'].setChecked(False)
        for w in self._widgets_preset_buttons:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_timer(self, state):
        """Toggle visibility of the timer settings."""
        if state:
            # When timer is shown, we turn off presets
            self._menu_do_view_presets(False)
            self._widget_registry['PresetsAction'].setChecked(False)
        for w in self._widgets_timer:
            if state:
                w.show()
            else:
                w.hide()

    def _menu_do_view_output_on_off(self, state):
        """Toggle visibility of the output buttons row."""
        for w in self._widgets_on_off_buttons:
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
        wid = input.wid
        wid_type = wid[0]
        ch = wid[-1]
        val = input.value()
        match wid_type:
            case 'Min':
                vi = wid[1]
                sp = self._widget_registry[f'SetPoint{ch}{vi}']
                sp.setMinimum(val)
                self._widget_registry[f'Max{ch}{vi}'].setMinimum(val)
                # Fall through into SetPoint to catch this change affecting the
                # SetPoint spinner's value
                wid_type = 'SetPoint'
                val = sp.value()
            case 'Max':
                vi = wid[1]
                sp = self._widget_registry[f'SetPoint{ch}{vi}']
                sp.setMaximum(val)
                self._widget_registry[f'Min{ch}{vi}'].setMaximum(val)
                # Fall through into SetPoint to catch this change affecting the
                # SetPoint spinner's value
                wid_type = 'SetPoint'
                val = sp.value()
            case 'SetPoint':
                pass  # Fall through
            case _:
                assert wid_type in ('Min', 'Max')
        if wid_type == 'SetPoint':
            match wid[1]:
                case 'V':
                    if self._psu_voltage[ch] != val:
                        self._inst.write(f'CH{ch+1}:VOLT {val:.3f}')
                        self._psu_voltage[ch] = val
                        if self._psu_mode != 'I':
                            assert ch == 0
                            self._psu_voltage[1] = val
                case 'I':
                    if self._psu_current[ch] != val:
                        self._inst.write(f'CH{ch+1}:CURR {val:.3f}')
                        self._psu_current[ch] = val
                        if self._psu_mode != 'I':
                            assert ch == 0
                            self._psu_current[1] = val
                case _:
                    assert False

        self._update_widgets()

    def _on_preset_clicked(self, button):
        ch, preset_num = button.wid
        volt, curr = self._presets[ch][preset_num]
        self._psu_voltage[ch] = volt
        self._psu_current[ch] = curr
        # This will take care of min/max, which might change the values
        self._update_widgets()
        volt = self._widget_registry[f'SetPoint{ch}V'].value()
        curr = self._widget_registry[f'SetPoint{ch}I'].value()
        self._inst.write(f'CH{ch+1}:VOLT {volt:.3f}')
        self._inst.write(f'CH{ch+1}:CURR {curr:.3f}')

    def _on_preset_long_click(self, button):
        ch, preset_num = button.wid
        self._presets[ch][preset_num] = [self._psu_voltage[ch], self._psu_current[ch]]
        self._update_widgets()

    def _on_timer_table_change(self, ch, row, column, val):
        """Handle change to any Timer Mode table value."""
        match column:
            case 0:
                self._psu_timer_params[ch][row][0] = val
            case 1:
                self._psu_timer_params[ch][row][1] = val
            case 2:
                self._psu_timer_params[ch][row][2] = val
        volt, curr, time = self._psu_timer_params[ch][row]
        self._inst.write(f'TIMER:SET CH{ch+1},{row+1},{volt:.3f},{curr:.3f},{time:.3f}')
        self._update_timer_table_graphs(update_table=False)

    def _on_timer_plot_resize(self):
        for ch in range(2):
            p = self._widget_registry[f'TimerPlotV{ch}']
            p2 = self._widget_registry[f'TimerPlotI{ch}']
            p2.setGeometry(p.getViewBox().sceneBoundingRect())
            p2.linkedViewChanged(p.getViewBox(), p2.XAxis)

    def _on_click_output_on_off(self):
        """Handle clicking on one of the OUTPUT buttons."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        sender = self.sender()
        ch = sender.wid
        state = not self._psu_on_off[ch]
        if self._psu_mode != 'I':
            # The other channel will slave on the instrument, but we need to update
            # our internal state - before _update_output_state updates the widgets.
            assert ch == 0
            self._psu_on_off[1] = state
        self._update_output_state(ch, state)

    def _update_output_on_off_buttons(self):
        """Update the style of the OUTPUT buttons based on current state."""
        for ch in range(2):
            bt = self._widget_registry[f'OutputOnOff{ch}']
            if self._psu_on_off[ch]:
                if self._psu_cc[ch]:
                    bt.setText(f'OUTPUT ON (CC)')
                    bg_color = '#ffc0c0'
                else:
                    bt.setText(f'OUTPUT ON (CV)')
                    bg_color = '#c0ffb0'
            else:
                bt.setText('OUTPUT OFF')
                bg_color = '#c0c0c0'
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

    def _update_output_state(self, ch, state):
        self._psu_on_off[ch] = state
        val = 'ON' if state else 'OFF'
        self._inst.write(f'OUTPUT CH{ch+1},{val}')
        self._update_output_on_off_buttons()

    def _update_widgets(self, minmax_ok=True):
        """Update all widgets with the current internal state."""
        # We need to do this because various set* calls below trigger the callbacks,
        # which then call this routine again in the middle of it already doing its
        # work.
        self._disable_callbacks = True

        if self._psu_mode != 'I':
            # Slave CH2 to CH1 when in series or parallel
            for mm in ('Min', 'Max'):
                for cv in ('V', 'I'):
                    self._widget_registry[f'{mm}1{cv}'].setValue(
                        self._widget_registry[f'{mm}0{cv}'].value())
            self._psu_voltage[1] = self._psu_voltage[0]
            self._psu_current[1] = self._psu_current[0]

        for ch in range(2):
            self._widget_registry[f'SetPoint{ch}V'].setValue(self._psu_voltage[ch])
            self._widget_registry[f'SetPoint{ch}I'].setValue(self._psu_current[ch])
            for preset_num in range(len(self._presets[ch])):
                button = self._widget_registry[f'Preset{ch}_{preset_num}']
                volt, curr = self._presets[ch][preset_num]
                button.setText(f'{volt:.3f}V / {curr:.3f}A')

        # Update the buttons
        self._update_output_on_off_buttons()

        # Update the mode menus
        self._widget_registry['IndependentAction'].setChecked(self._psu_mode == 'I')
        self._widget_registry['SeriesAction'].setChecked(self._psu_mode == 'S')
        self._widget_registry['ParallelAction'].setChecked(self._psu_mode == 'P')
        match self._psu_mode:
            case 'I':
                self._widget_registry['FrameCH1'].setTitle('Channel 1')
                self._widget_registry['FrameCH2'].setTitle('Channel 2')
                self._widget_registry['FrameCH2'].setEnabled(True)
            case 'S':
                self._widget_registry['FrameCH1'].setTitle('Series Mode')
                self._widget_registry['FrameCH2'].setTitle('Series Mode')
                self._widget_registry['FrameCH2'].setEnabled(False)
            case 'P':
                self._widget_registry['FrameCH1'].setTitle('Parallel Mode')
                self._widget_registry['FrameCH2'].setTitle('Parallel Mode')
                self._widget_registry['FrameCH2'].setEnabled(False)
            case _:
                assert False, self._psu_mode

        self._update_timer_table_graphs()

        # Update the Enable Measurements checkboxes
        # self._widget_registry['EnableV'].setChecked(self._enable_measurement_v)
        # self._widget_registry['EnableC'].setChecked(self._enable_measurement_c)
        # self._widget_registry['EnableP'].setChecked(self._enable_measurement_p)

        self._disable_callbacks = False

    def _update_timer_table_graphs(self, update_table=True, timer_step_only=False):
        """Update the list table and associated plot if data has changed."""
        self._on_timer_plot_resize()
        widths = (80, 80, 80)
        hdr = ('Voltage (V)', 'Current (A)', 'Time (s)')
        fmts = ('.3f', '.3f', '.3f')
        ranges = ((0, 32), (0, 3.2), (0, 10000))
        steps = 5
        for ch in range(2):
            table = self._widget_registry[f'TimerTable{ch}']
            if update_table:
                # We don't always want to update the table, because in edit mode when
                # the user changes a value, the table will have already been updated
                # internally, and if we mess with it here it screws up the focus for
                # the edit box and the edit box never closes.
                data = []
                for i in range(steps):
                    data.append(self._psu_timer_params[ch][i])
                table.model().set_params(data, fmts, hdr)
                for i, fmt in enumerate(fmts):
                    table.setItemDelegateForColumn(
                        i, DoubleSpinBoxDelegate(self, fmt, ranges[i]))
                    table.setColumnWidth(i, widths[i])

            # Update the Timer plot
            for plot_num, vi in enumerate(('V', 'I')):
                min_plot_y = 0
                levels = [x[plot_num] for x in self._psu_timer_params[ch]]
                max_plot_y = max(levels)
                if not timer_step_only:
                    plot_x = [0]
                    plot_y = [levels[0]]
                    for i in range(steps-1):
                        x_val = plot_x[-1] + self._psu_timer_params[ch][i][2]
                        plot_x.append(x_val)
                        plot_x.append(x_val)
                        plot_y.append(self._psu_timer_params[ch][i][plot_num])
                        plot_y.append(self._psu_timer_params[ch][i+1][plot_num])
                    plot_x.append(plot_x[-1]+self._psu_timer_params[ch][steps-1][2])
                    plot_y.append(levels[steps-1])
                    plot_widget = self._widget_registry[f'TimerPlot{vi}{ch}']
                    pdi = self._widget_registry[f'Timer{vi}PlotItem{ch}']
                    pdi.setData(plot_x, plot_y)
                    plot_widget.setYRange(min_plot_y, max_plot_y)

            # Update the running plot and highlight the appropriate table row
            # if self._timer_mode_cur_step_num is not None:
            #     delta = 0
            #     step_num = self._timer_mode_cur_step_num
            #     if self._timer_mode_running:
            #         delta = time.time() - self._timer_mode_cur_step_start_time
            #     else:
            #         # When we pause List mode, we end at the end of the previous step,
            #         # not the start of the next step
            #         step_num = (step_num-1) % self._param_state[':LIST:STEP']
            #         delta = self._timer_mode_widths[step_num]
            #     cur_step_x = 0
            #     if step_num > 0:
            #         cur_step_x = sum(self._timer_mode_widths[:step_num])
            #     cur_step_x += delta
            #     self._timer_mode_step_plot.setData([cur_step_x, cur_step_x],
            #                                       [min_plot_y, max_plot_y])
            #     table.model().set_highlighted_row(step_num)
            # else:
            #     table.model().set_highlighted_row(None)
            #     self._timer_mode_step_plot.setData([], [])

    def _update_timer_table_heartbeat(self):
        """Handle the rapid heartbeat when in List mode to update the highlighting."""
        if self._timer_mode_running:
            cur_time = time.time()
            delta = cur_time - self._timer_mode_cur_step_start_time
            if delta >= self._timer_mode_widths[self._timer_mode_cur_step_num]:
                # We've moved on to the next step (or more than one step)
                if self._timer_mode_stopping:
                    self._timer_mode_stopping = False
                    self._timer_mode_running = False
                    self._timer_mode_timer.stop()
                while delta >= self._timer_mode_widths[self._timer_mode_cur_step_num]:
                    delta -= self._timer_mode_widths[self._timer_mode_cur_step_num]
                    self._timer_mode_cur_step_num = (
                        self._timer_mode_cur_step_num+1) % self._param_state[':LIST:STEP']
                self._timer_mode_cur_step_start_time = cur_time - delta
            self._update_timer_table_graphs(timer_step_only=True)


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

    def disconnect(self, *args, **kwargs):
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


"""
*SAV 1-5
*RCL 1-5
INST CH1|2
INST?
CH1:CURR <>
CH1:CURR?
CH1:VOLT <x>
CH1:VOLT?
OUTPUT CH1|2|3,ON|OFF
OUTPUT:TRACK 0|1|2  (independent, series, parallel)
OUTPUT:WAVE CH1|2,ON|OFF
TIMER:SET CH1|2,1-5,V,C,Time
TIMER:SET? CH1|2,1-5
SYST:STATUS? (returns hex)
  0 - CH1 CV/CC
  1 - CH2 CV/CC
  2,3 - 01: Ind, 10: Parallel, 11: Series
  4 - CH1 Off/on
  5 - CH2 Off/on
  6 - TIMER1 off/on
  7 - TIMER2 off/on
  8 - CH1 analog, waveform
  9 - CH2 analog, waveform
"""
