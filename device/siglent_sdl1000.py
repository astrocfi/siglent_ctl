import pprint
import re

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
from PyQt6.QtCore import *

from .device import Device4882
from .config_widget_base import ConfigureWidgetBase


# XXX There's a complicated thing with slew rise/fall where they have to both be in
# the same range 0.001-0.01 or 0.01-0.5

_SDL_OVERALL_MODES = {
    'Basic':   ('!Dynamic_Mode_.*', 'Const_.*',),
    'Dynamic': ('Dynamic_Mode_.*', 'Const_.*',),
    'LED':     ('!Dynamic_Mode_.*', '!Const_.*',),
    'Battery': ('!Dynamic_Mode_.*', 'Const_.*', '!Const_Voltage'),
    'List':    ('!Dynamic_Mode_.*', 'Const_.*',),
    'Program': ('!Dynamic_Mode_.*', '!Const_.*',),
    'OCPT':    ('!Dynamic_Mode_.*', '!Const_.*',),
    'OPPT':    ('!Dynamic_Mode_.*', '!Const_.*',),
}

_SDL_MODE_PARAMS = {
    ('General'):
        {'widgets': None,
         'mode_name': None,
         'params': (
            # SYST:REMOTE:STATE is undocumented! It locks the keyboard and
            # sets the remote access icon
            ('SYST:REMOTE:STATE',  'b', None),
            ('INPUT:STATE',        'b', None),
            ('SHORT:STATE',        'b', None),
            ('FUNCTION',           'r', None),
            ('FUNCTION:TRANSIENT', 'r', None),
            # FUNCtion:MODE is undocumented! Possible return values are:
            #   BASIC, TRAN, BATTERY, OCP, OPP, LIST, PROGRAM
            ('FUNCTION:MODE',      's', None),
            ('TRIGGER:SOURCE',     's', None),
         )
        },
    ('Basic', 'Voltage'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_T.*', '~Slew_T.*',
                     'SlewLabel_B.*', 'Slew_B.*',
                     '!SlewLabel_B.*', '!Slew_B.*',
                     ('ValueLabel_Voltage', 'Value_Voltage', 'V')),
         'mode_name': 'VOLTAGE',
         'params': (
            ('IRANGE',          'r', 'Range_Current_.*'),
            ('VRANGE',          'r', 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', 'f', 'Value_Voltage'),
          )
        },
    ('Basic', 'Current'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_T.*', '~Slew_T.*',
                     ('ValueLabel_Current', 'Value_Current', 'C'),
                     ('SlewLabel_BSlewPos', 'Slew_BSlewPos', 0.001, 0.5),
                     ('SlewLabel_BSlewNeg', 'Slew_BSlewNeg', 0.001, 0.5)),
         'mode_name': 'CURRENT',
         'params': (
            ('IRANGE',          'r', 'Range_Current_.*'),
            ('VRANGE',          'r', 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', 'f', 'Value_Current'),
            ('SLEW:POSITIVE',   'f', 'Slew_SlewPos'),
            ('SLEW:NEGATIVE',   'f', 'Slew_SlewNeg'),
          )
        },
    ('Basic', 'Power'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_T.*', '~Slew_T.*',
                     'SlewLabel_B.*', 'Slew_B.*',
                     '!SlewLabel_B.*', '!Slew_B.*',
                     ('ValueLabel_Power', 'Value_Power', 'P')),
         'mode_name': 'POWER',
         'params': (
            ('IRANGE',          'r', 'Range_Current_.*'),
            ('VRANGE',          'r', 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', 'f', 'Value_Power'),
          )
        },
    ('Basic', 'Resistance'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_T.*', '~Slew_T.*',
                     'SlewLabel_B.*', 'Slew_B.*',
                     '!SlewLabel_B.*', '!Slew_B.*',
                     ('ValueLabel_Resistance', 'Value_Resistance', 0, 10000)),
         'mode_name': 'RESISTANCE',
         'params': (
            ('IRANGE',          'r', 'Range_Current_.*'),
            ('VRANGE',          'r', 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', 'f', 'Value_Resistance'),
          )
        },
    ('LED', None): # This behaves like a Basic mode
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_T.*', '~Slew_T.*',
                     'SlewLabel_B.*', 'Slew_B.*',
                     '!SlewLabel_B.*', '!Slew_B.*',
                     ('ValueLabel_LEDV', 'Value_LEDV', 'V'),
                     ('ValueLabel_LEDC', 'Value_LEDC', 'C'),
                     ('ValueLabel_LEDR', 'Value_LEDR', 0.01, 1.0)),
         'mode_name': 'LED',
         'params': (
            ('IRANGE',  'r', 'Range_Current_.*'),
            ('VRANGE',  'r', 'Range_Voltage_.*'),
            ('VOLTAGE', 'f', 'Value_LEDV'),
            ('CURRENT', 'f', 'Value_LEDC'),
            ('RCONF',   'f', 'Value_LEDR'),
          )
        },
    ('Dynamic', 'Voltage'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_B.*', '~Slew_B.*',
                     'SlewLabel_T.*', 'Slew_T.*',
                     '!SlewLabel_T.*', '!Slew_T.*',
                     ('ValueLabel_ALevelV', 'Value_ALevelV', 'V'),
                     ('ValueLabel_BLevelV', 'Value_BLevelV', 'V'),
                     ('ValueLabel_AWidth', 'Value_AWidth', 1, 999),
                     ('ValueLabel_BWidth', 'Value_BWidth', 1, 999)),
         'mode_name': 'VOLTAGE',
         'params': (
            ('TRANSIENT:IRANGE', 'r', 'Range_Current_.*'),
            ('TRANSIENT:VRANGE', 'r', 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',   'r', 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', 'f', 'Value_ALevelV'),
            ('TRANSIENT:BLEVEL', 'f', 'Value_BLevelV'),
            ('TRANSIENT:AWIDTH', 'f', 'Value_AWidth'),
            ('TRANSIENT:BWIDTH', 'f', 'Value_BWidth'),
          )
        },
    ('Dynamic', 'Current'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_B.*', '~Slew_B.*',
                     ('ValueLabel_ALevelC', 'Value_ALevelC', 'C'),
                     ('ValueLabel_BLevelC', 'Value_BLevelC', 'C'),
                     ('ValueLabel_AWidth', 'Value_AWidth', 1, 999),
                     ('ValueLabel_BWidth', 'Value_BWidth', 1, 999),
                     ('SlewLabel_TSlewPos', 'Slew_TSlewPos', 0.001, 0.5),
                     ('SlewLabel_TSlewNeg', 'Slew_TSlewNeg', 0.001, 0.5)),
         'mode_name': 'CURRENT',
         'params': (
            ('TRANSIENT:IRANGE',         'r', 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',        'r', 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',           'r', 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL',         'f', 'Value_ALevelC'),
            ('TRANSIENT:BLEVEL',        'f', 'Value_BLevelC'),
            ('TRANSIENT:AWIDTH',        'f', 'Value_AWidth'),
            ('TRANSIENT:BWIDTH',        'f', 'Value_BWidth'),
            ('TRANSIENT:SLEW:POSITIVE', 'f', 'Slew_TSlewPos'),
            ('TRANSIENT:SLEW:NEGATIVE', 'f', 'Slew_TSlewNeg'),
          )
        },
    ('Dynamic', 'Power'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_B.*', '~Slew_B.*',
                     'SlewLabel_T.*', 'Slew_T.*',
                     '!SlewLabel_T.*', '!Slew_T.*',
                     ('ValueLabel_ALevelP', 'Value_ALevelP', 'P'),
                     ('ValueLabel_BLevelP', 'Value_BLevelP', 'P'),
                     ('ValueLabel_AWidth', 'Value_AWidth', 1, 999),
                     ('ValueLabel_BWidth', 'Value_BWidth', 1, 999)),
         'mode_name': 'POWER',
         'params': (
            ('TRANSIENT:IRANGE', 'r', 'Range_Current_.*'),
            ('TRANSIENT:VRANGE', 'r', 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',   'r', 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', 'f', 'Value_ALevelP'),
            ('TRANSIENT:BLEVEL', 'f', 'Value_BLevelP'),
            ('TRANSIENT:AWIDTH', 'f', 'Value_AWidth'),
            ('TRANSIENT:BWIDTH', 'f', 'Value_BWidth'),
          )
        },
    ('Dynamic', 'Resistance'):
        {'widgets': ('~ValueLabel_.*', '~Value_.*',
                     '~SlewLabel_B.*', '~Slew_B.*',
                     'SlewLabel_T.*', 'Slew_T.*',
                     '!SlewLabel_T.*', '!Slew_T.*',
                     ('ValueLabel_ALevelR', 'Value_ALevelR', 0.03, 10000), # XXX
                     ('ValueLabel_BLevelR', 'Value_BLevelR', 0.03, 10000),
                     ('ValueLabel_AWidth', 'Value_AWidth', 1, 999),
                     ('ValueLabel_BWidth', 'Value_BWidth', 1, 999)),
         'mode_name': 'RESISTANCE',
         'params': (
            ('TRANSIENT:IRANGE', 'r', 'Range_Current_.*'),
            ('TRANSIENT:VRANGE', 'r', 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',   'r', 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', 'f', 'Value_ALevelR'),
            ('TRANSIENT:BLEVEL', 'f', 'Value_BLevelR'),
            ('TRANSIENT:AWIDTH', 'f', 'Value_AWidth'),
            ('TRANSIENT:BWIDTH', 'f', 'Value_BWidth'),
          )
        },

}

class InstrumentSiglentSDL1000ConfigureWidget(ConfigureWidgetBase):
    def __init__(self, *args, **kwargs):
        self._cur_overall_mode = None
        self._cur_dynamic_mode = None
        self._cur_const_mode = None
        self._cur_dynamic_mode = None
        self._enable_measurement_v = True
        self._enable_measurement_c = True
        self._enable_measurement_p = True
        self._enable_measurement_r = True
        super().__init__(*args, **kwargs)

    ### Public methods

    def refresh(self):
        """Read all parameters from the instrument and set our internal state to match."""
        for mode, info in _SDL_MODE_PARAMS.items():
            mode_name = info['mode_name']
            if mode_name is None: # General parameters
                mode_name = ''
            else:
                mode_name = ':'+mode_name
            for param_spec in info['params']:
                param = f'{mode_name}:{param_spec[0]}'
                val = self._inst.query(param+'?')
                param_type = param_spec[1]
                if param_type == 'f': # Float
                    val = float(val)
                elif param_type == 'b' or param_type == 'd': # Boolean or Decimal
                    val = int(val)
                elif param_type == 's' or param_type == 'r': # Strings
                    val = val.title()
                else:
                    assert False, 'Unknown param_type '+str(param_type)
                self._param_state[param] = val

        mode = self._param_state[':FUNCTION:MODE']
        if mode == 'Ocp':
            mode = 'OCPT'
        elif mode == 'Opp':
            mode = 'OPPT'
        elif mode == 'Basic' and self._param_state[':FUNCTION'] == 'Led':
            mode = 'LED'
        elif mode == 'Tran':
            mode = 'Dynamic'
        else:
            mode = mode.title()
        self._cur_overall_mode = mode
        self._cur_dynamic_mode = None
        if mode == 'Basic':
            self._cur_const_mode = self._param_state[':FUNCTION']
        elif mode == 'Dynamic':
            self._cur_const_mode = self._param_state[':FUNCTION:TRANSIENT']
            param_info = self._cur_mode_param_info()
            mode_name = param_info['mode_name']
            val = self._param_state[f':{mode_name}:TRANSIENT:MODE']
            self._cur_dynamic_mode = val
        else:
            self._cur_const_mode = None

        self._update_widgets()

    def update_measurements(self):
        # Update the load on/off state in case we hit a protection limit
        input_state = int(self._inst.query(':INPUT:STATE?'))
        if self._param_state[':INPUT:STATE'] != input_state:
            self._param_state[':INPUT:STATE'] = input_state
            self._update_load_state(input_state)

        w = self._widget_registry['MeasureV']
        if self._enable_measurement_v:
            voltage = self._inst.measure_voltage()
            w.setText('%10.6f V' % voltage)
        else:
            w.setText('---   V')

        w = self._widget_registry['MeasureC']
        if self._enable_measurement_c:
            if not input_state:
                w.setText('N/A   A')
            else:
                current = self._inst.measure_current()
                w.setText('%10.6f A' % current)
        else:
            w.setText('---   A')

        w = self._widget_registry['MeasureP']
        if self._enable_measurement_p:
            if not input_state:
                w.setText('N/A   W')
            else:
                power = self._inst.measure_power()
                w.setText('%10.6f W' % power)
        else:
            w.setText('---   W')

        w = self._widget_registry['MeasureR']
        if self._enable_measurement_r:
            if not input_state:
                w.setText('N/A   \u2126')
            else:
                resistance = self._inst.measure_resistance()
                if resistance < 10:
                    fmt = '%8.6f'
                elif resistance < 100:
                    fmt = '%8.5f'
                elif resistance < 1000:
                    fmt = '%8.4f'
                elif resistance < 10000:
                    fmt = '%8.3f'
                elif resistance < 100000:
                    fmt = '%8.2f'
                else:
                    fmt = '%8.1f'
                w.setText(f'{fmt} \u2126' % resistance)
        else:
            w.setText('---   \u2126')

    ### Override from ConfigureWidgetBase

    def _menu_do_about(self):
        msg = 'Siglent SDL1000-series\n\nBy Robert S. French'
        QMessageBox.about(self, 'About', msg)


    ### Internal routines

    def _transient_string(self):
        if self._cur_overall_mode == 'Dynamic':
            return ':TRANSIENT'
        return ''

    def _update_load_state(self, state):
        new_params = {':INPUT:STATE': state}
        self._update_params(new_params)
        self._update_load_onoff_button(state)
        self._update_trigger_buttons()

    def _update_short_state(self, state):
        new_params = {':SHORT:STATE': state}
        self._update_params(new_params)
        self._update_short_onoff_button(state)

    def _update_widgets(self):
        if self._cur_overall_mode is None:
            return

        param_info = self._cur_mode_param_info()
        mode_name = param_info['mode_name']

        for widget_name, widget in self._widget_registry.items():
            # Set the main mode radio buttons
            if widget_name.startswith('Overall_'):
                widget.setChecked(widget_name.endswith(self._cur_overall_mode))
            # Set the const mode radio buttons
            if widget_name.startswith('Const_') and self._cur_const_mode is not None:
                widget.setChecked(widget_name.endswith(self._cur_const_mode))

        # Enable or disable widgets based on the current overall mode
        for widget_name in _SDL_OVERALL_MODES[self._cur_overall_mode]:
            if widget_name[0] == '~':
                # Hide unused widgets
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name[1:], trial_widget):
                        self._widget_registry[trial_widget].hide()
            elif widget_name[0] == '!':
                # Disable (and grey out) unused widgets
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name[1:], trial_widget):
                        widget = self._widget_registry[trial_widget]
                        widget.setEnabled(False)
                        if isinstance(widget, QRadioButton):
                            # For disabled radio buttons we remove ALL selections so it
                            # doesn't look confusing
                            widget.button_group.setExclusive(False)
                            widget.setChecked(False)
                            widget.button_group.setExclusive(True)
            else:
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name, trial_widget):
                        self._widget_registry[trial_widget].setEnabled(True)
                        self._widget_registry[trial_widget].show()

        # Now do the same thing for the constant mode
        for widget_name in param_info['widgets']:
            min_val = max_val = None
            widget_name2 = None
            if isinstance(widget_name, (tuple, list)):
                if len(widget_name) == 4:
                    widget_name, widget_name2, min_val, max_val = widget_name
                elif len(widget_name) == 3:
                    widget_name, widget_name2, range_type = widget_name
                    trans = self._transient_string()
                    if range_type == 'C':
                        min_val = 0
                        max_val = float(self._param_state[f':{mode_name}{trans}:IRANGE'])
                        print(max_val)
                    elif range_type == 'V':
                        min_val = 0
                        max_val = float(self._param_state[f':{mode_name}{trans}:VRANGE'])
                    elif range_type == 'P':
                        min_val = 0
                        if self._inst._high_power:
                            max_val = 300
                        else:
                            max_val = 200
                    else:
                        assert False
                else:
                    assert False
            if widget_name[0] == '~':
                # Hide unused widgets
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name[1:], trial_widget):
                        self._widget_registry[trial_widget].hide()
            elif widget_name[0] == '!':
                # Disable (and grey out) unused widgets
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name[1:], trial_widget):
                        self._widget_registry[trial_widget].setEnabled(False)
            else:
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_name, trial_widget):
                        self._widget_registry[trial_widget].setEnabled(True)
                        self._widget_registry[trial_widget].show()
                    if widget_name2 is not None:
                        if re.fullmatch(widget_name2, trial_widget):
                            widget = self._widget_registry[trial_widget]
                            widget.setEnabled(True)
                            widget.show()
                            widget.setMinimum(min_val)
                            widget.setMaximum(max_val)

        # Fill in widget values
        params = param_info['params']
        mode_name = param_info['mode_name']
        for scpi_cmd, param_type, widget_re in params:
            val = self._param_state[f':{mode_name}:{scpi_cmd}']
            if param_type == 'f' or param_type == 'd':
                self._widget_registry[widget_re].setValue(val)
            elif param_type == 'r': # Radio button
                for trial_widget in self._widget_registry:
                    if re.fullmatch(widget_re, trial_widget):
                        checked = trial_widget.upper().endswith('_'+str(val).upper())
                        self._widget_registry[trial_widget].setChecked(checked)

        # Update the buttons
        self._update_load_onoff_button()
        self._update_short_onoff_button()
        self._update_trigger_buttons()

    def _cur_mode_param_info(self):
        key = (self._cur_overall_mode, self._cur_const_mode)
        return _SDL_MODE_PARAMS[key]

    def _update_params(self, new_params):
        # print('Old')
        # print(pprint.pformat(self._param_state))
        # print()
        # print('New')
        # print(pprint.pformat(new_params))
        # print()
        for key, data in new_params.items():
            if data != self._param_state[key]:
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
                self._inst.write(f'{key} {fmt_data}')
                self._param_state[key] = data


    ############################################################################
    ### SETUP WINDOW LAYOUT
    ############################################################################

    def _init_widgets(self):
        toplevel_widget = self._toplevel_widget()
        main_vert_layout = QVBoxLayout(toplevel_widget)
        main_vert_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        row_layout = QHBoxLayout()
        main_vert_layout.addLayout(row_layout)

        ###### ROW 1 ######

        ### COLUMN 1 ###

        # Overall mode: Basic, Dynamic, LED, Battery, List, Program, OCPT, OPPT
        layouts = QVBoxLayout()
        row_layout.addLayout(layouts)
        frame = QGroupBox('Mode')
        frame.setStyleSheet('QGroupBox { min-height: 10em; max-height: 10em; }')
        layouts.addWidget(frame)
        layouth = QHBoxLayout(frame)
        layoutv = QVBoxLayout()
        layoutv.setSpacing(4)
        layouth.addLayout(layoutv)
        bg = QButtonGroup(layouts)
        # Left column
        for mode in ('Basic', 'LED', 'Battery', 'OCPT', 'OPPT'):
            rb = QRadioButton(mode)
            layoutv.addWidget(rb)
            bg.addButton(rb)
            rb.button_group = bg
            rb.wid = mode
            rb.toggled.connect(self._on_click_overall_mode)
            self._widget_registry['Overall_'+mode] = rb
        layoutv.addStretch()
        # Right column
        layoutv = QVBoxLayout()
        layoutv.setSpacing(2)
        layouth.addLayout(layoutv)
        for mode in ('Dynamic', 'List', 'Program'):
            rb = QRadioButton(mode)
            layoutv.addWidget(rb)
            bg.addButton(rb)
            rb.button_group = bg
            rb.wid = mode
            rb.toggled.connect(self._on_click_overall_mode)
            self._widget_registry['Overall_'+mode] = rb
            if mode == 'Dynamic':
                bg2 = QButtonGroup(layouts)
                for mode in ('Continuous', 'Pulse', 'Toggle'):
                    rb = QRadioButton(mode)
                    rb.setStyleSheet('padding-left: 1.4em;') # Indent
                    layoutv.addWidget(rb)
                    bg2.addButton(rb)
                    rb.button_group = bg
                    rb.wid = mode
                    rb.toggled.connect(self._on_click_dynamic_mode)
                    self._widget_registry['Dynamic_Mode_'+mode] = rb
        layoutv.addStretch()
        # layouts.addStretch()

        ### COLUMN 2 ###

        # Mode radio buttons: CV, CC, CP, CR
        frame = QGroupBox('Constant')
        frame.setStyleSheet('QGroupBox { min-height: 10em; max-height: 10em; }')
        row_layout.addWidget(frame)
        layoutv = QVBoxLayout(frame)
        bg = QButtonGroup(layouts)
        for mode in ('Voltage', 'Current', 'Power', 'Resistance'):
            rb = QRadioButton(mode)
            bg.addButton(rb)
            rb.button_group = bg
            rb.wid = mode
            rb.sizePolicy().setRetainSizeWhenHidden(True)
            rb.toggled.connect(self._on_click_const_mode)
            self._widget_registry['Const_'+mode] = rb
            layoutv.addWidget(rb)

        ### COLUMN 3 ###

        layouts = QVBoxLayout()
        layouts.setSpacing(0)
        row_layout.addLayout(layouts)

        # V/I/R Range selections
        frame = QGroupBox('Range')
        # frame.setStyleSheet('QGroupBox { min-height: 8.1em; max-height: 8.1em; }')
        layouts.addWidget(frame)
        layout = QGridLayout(frame)
        layout.setSpacing(0)
        for row_num, (mode, ranges) in enumerate((('Voltage', ('36V', '150V')),
                                                  ('Current', ('5A', '30A')))):
            layout.addWidget(QLabel(mode+':'), row_num, 0)
            bg = QButtonGroup(layout)
            for col_num, range_name in enumerate(ranges):
                rb = QRadioButton(range_name)
                bg.addButton(rb)
                rb.button_group = bg
                rb.wid = range_name
                rb.toggled.connect(self._on_click_range)
                if len(ranges) == 1:
                    layout.addWidget(rb, row_num, col_num+1, 1, 2)
                else:
                    layout.addWidget(rb, row_num, col_num+1)
                self._widget_registry['Range_'+mode+'_'+range_name.strip('VA')] = rb

        frame = self._init_widgets_value_box('Slew', (
                    ('Slew (rise)', 'BSlewPos', 'A/\u00B5', 'SLEW:POSITIVE'),
                    ('Slew (fall)', 'BSlewNeg', 'A/\u00B5', 'SLEW:NEGATIVE'),
                    ('Slew (rise)', 'TSlewPos', 'A/\u00B5', 'TRANSIENT:SLEW:POSITIVE'),
                    ('Slew (fall)', 'TSlewNeg', 'A/\u00B5', 'TRANSIENT:SLEW:NEGATIVE')))
        ss = """QGroupBox { min-width: 11em; max-width: 11em;
                            min-height: 5em; max-height: 5em; }
                QDoubleSpinBox { min-width: 5.5em; max-width: 5.5em; }
             """
        frame.setStyleSheet(ss)
        layouts.addWidget(frame)

        ### COLUMN 4 ###

        frame = self._init_widgets_value_box('Value', (
                    ('Voltage', 'Voltage', 'V', 'LEVEL:IMMEDIATE'),
                    ('Current', 'Current', 'A', 'LEVEL:IMMEDIATE'),
                    ('Power', 'Power', 'W', 'LEVEL:IMMEDIATE'),
                    ('Resistance', 'Resistance', '\u2126', 'LEVEL:IMMEDIATE'),
                    ('A Level', 'ALevelV', 'V', 'TRANSIENT:ALEVEL'),
                    ('B Level', 'BLevelV', 'V', 'TRANSIENT:BLEVEL'),
                    ('A Level', 'ALevelC', 'A', 'TRANSIENT:ALEVEL'),
                    ('B Level', 'BLevelC', 'A', 'TRANSIENT:BLEVEL'),
                    ('A Level', 'ALevelP', 'W', 'TRANSIENT:ALEVEL'),
                    ('B Level', 'BLevelP', 'W', 'TRANSIENT:BLEVEL'),
                    ('A Level', 'ALevelR', '\u2126', 'TRANSIENT:ALEVEL'),
                    ('B Level', 'BLevelR', '\u2126', 'TRANSIENT:BLEVEL'),
                    ('A Width', 'AWidth', 's', 'TRANSIENT:AWIDTH'),
                    ('B Width', 'BWidth', 's', 'TRANSIENT:BWIDTH'),
                    ('Vo', 'LEDV', 'V', 'VOLTAGE'),
                    ('Io', 'LEDC', 'A', 'CURRENT'),
                    ('Rco', 'LEDR', '\u2126', 'RCONF')))
        ss = """QGroupBox { min-width: 11em; max-width: 11em;
                            min-height: 10em; max-height: 10em; }
                QDoubleSpinBox { min-width: 5.5em; max-width: 5.5em; }
             """
        frame.setStyleSheet(ss)
        row_layout.addWidget(frame)

        ###################

        ###### ROW 2 ######

        row_layout = QHBoxLayout()
        main_vert_layout.addLayout(row_layout)

        layoutv = QVBoxLayout()
        layoutv.setSpacing(0)
        row_layout.addLayout(layoutv)

        w = QPushButton('') # SHORT ON/OFF
        w.setEnabled(False) # Default to disabled since checkbox is unchecked
        w.clicked.connect(self._on_click_short_on_off)
        layoutv.addWidget(w)
        self._widget_registry['ShortONOFF'] = w
        layouth = QHBoxLayout()
        layoutv.addLayout(layouth)
        layouth.addStretch()
        w = QCheckBox('Enable short operation') # Enable short
        w.setChecked(False)
        w.clicked.connect(self._on_click_short_enable)
        layouth.addWidget(w)
        self._update_short_onoff_button(False) # Sets the style sheet
        layouth.addStretch()

        row_layout.addStretch()

        w = QPushButton('') # LOAD ON/OFF
        w.clicked.connect(self._on_click_load_on_off)
        row_layout.addWidget(w)
        self._widget_registry['LoadONOFF'] = w
        self._update_load_onoff_button(False) # Sets the style sheet

        row_layout.addStretch()

        layoutv = QVBoxLayout()
        layoutv.setSpacing(0)
        row_layout.addLayout(layoutv)
        bg = QButtonGroup(layoutv)
        rb = QRadioButton('Bus')
        rb.setChecked(True)
        rb.mode = 'Bus'
        bg.addButton(rb)
        rb.button_group = bg
        rb.clicked.connect(self._on_click_trigger_source)
        layoutv.addWidget(rb)
        self._widget_registry['Trigger_Bus'] = rb
        rb = QRadioButton('Man')
        rb.mode = 'Manual'
        bg.addButton(rb)
        rb.button_group = bg
        rb.clicked.connect(self._on_click_trigger_source)
        layoutv.addWidget(rb)
        self._widget_registry['Trigger_Man'] = rb
        rb = QRadioButton('Ext')
        rb.mode = 'External'
        bg.addButton(rb)
        rb.button_group = bg
        rb.clicked.connect(self._on_click_trigger_source)
        layoutv.addWidget(rb)
        self._widget_registry['Trigger_Ext'] = rb

        w = QPushButton('TRIG\u25CE')
        w.clicked.connect(self._on_click_trigger)
        ss = """QPushButton {
                    min-width: 2.9em; max-width: 2.9em;
                    min-height: 1.5em; max-height: 1.5em;
                    border-radius: 0.75em; border: 4px solid black;
                    font-weight: bold; font-size: 18px;
                    background: #ffff80; }
                QPushButton:pressed { border: 6px solid black; }"""
        w.setStyleSheet(ss)
        row_layout.addWidget(w)
        self._widget_registry['Trigger'] = w

        ###################

        ###### ROW 3 ######

        row_layout = QHBoxLayout()
        main_vert_layout.addLayout(row_layout)

        layoutv = QVBoxLayout()
        layoutv.setSpacing(0)
        row_layout.addLayout(layoutv)
        layoutv.addWidget(QLabel('Enable measurements:'))
        cb = QCheckBox('Voltage')
        cb.setStyleSheet('padding-left: 0.5em;') # Indent
        cb.setChecked(True)
        cb.mode = 'V'
        cb.clicked.connect(self._on_click_enable_measurements)
        layoutv.addWidget(cb)
        self._widget_registry['Enable_V'] = cb
        cb = QCheckBox('Current')
        cb.setStyleSheet('padding-left: 0.5em;') # Indent
        cb.setChecked(True)
        cb.mode = 'C'
        cb.clicked.connect(self._on_click_enable_measurements)
        layoutv.addWidget(cb)
        self._widget_registry['Enable_C'] = cb
        cb = QCheckBox('Power')
        cb.setStyleSheet('padding-left: 0.5em;') # Indent
        cb.setChecked(True)
        cb.mode = 'P'
        cb.clicked.connect(self._on_click_enable_measurements)
        layoutv.addWidget(cb)
        self._widget_registry['Enable_P'] = cb
        cb = QCheckBox('Resistance')
        cb.setStyleSheet('padding-left: 0.5em;') # Indent
        cb.setChecked(True)
        cb.mode = 'R'
        cb.clicked.connect(self._on_click_enable_measurements)
        layoutv.addWidget(cb)
        self._widget_registry['Enable_R'] = cb
        layoutv.addStretch()

        row_layout.addStretch()

        container = QWidget()
        container.setStyleSheet('background: black; color: yellow;')
        row_layout.addStretch()
        row_layout.addWidget(container)

        ss = """font-size: 30px; font-weight: bold;
                min-width: 6.5em; text-align: right;
                font-family: "Courier New";
             """
        layout = QGridLayout(container)
        w = QLabel('---   V')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layout.addWidget(w, 0, 0)
        self._widget_registry['MeasureV'] = w
        w = QLabel('---   A')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layout.addWidget(w, 0, 1)
        self._widget_registry['MeasureC'] = w
        w = QLabel('---   W')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layout.addWidget(w, 1, 0)
        self._widget_registry['MeasureP'] = w
        w = QLabel('---   \u2126')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss)
        layout.addWidget(w, 1, 1)
        self._widget_registry['MeasureR'] = w

        row_layout.addStretch()

    def _init_widgets_value_box(self, title, details):
        # Value for most modes
        frame = QGroupBox(title)
        layoutv = QVBoxLayout(frame)
        for (display, mode, unit, scpi) in details:
            layouth = QHBoxLayout()
            label = QLabel(display+':')
            layouth.addWidget(label)
            input = QDoubleSpinBox()
            input.wid = (mode, scpi)
            input.setAlignment(Qt.AlignmentFlag.AlignRight)
            input.setDecimals(3)
            input.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
            input.setAccelerated(True)
            input.setSuffix(' '+unit)
            input.editingFinished.connect(self._on_value_change)
            layouth.addWidget(input)
            label.sizePolicy().setRetainSizeWhenHidden(True)
            input.sizePolicy().setRetainSizeWhenHidden(True)
            layoutv.addLayout(layouth)
            self._widget_registry[f'{title}_{mode}'] = input
            self._widget_registry[f'{title}Label_{mode}'] = label
        layoutv.addStretch()
        return frame


    ############################################################################
    ### ACTION HANDLERS
    ############################################################################

    def _on_click_overall_mode(self):
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_overall_mode = rb.wid
        self._cur_dynamic_mode = None
        new_params = {}
        if self._cur_overall_mode == 'Basic':
            if self._cur_const_mode is None:
                self._cur_const_mode = self._param_state[':FUNCTION']
                if self._cur_const_mode == 'LED':
                    # LED is weird in that the instrument treats it as a BASIC mode
                    # but there's no CV/CC/CP/CR choice
                    self._cur_const_mode = 'Voltage' # For lack of anything else to do
            # Force update since this does more than set a parameter - it switches modes
            self._param_state[':FUNCTION'] = None
            new_params[':FUNCTION'] = self._cur_const_mode
        elif self._cur_overall_mode == 'Dynamic':
            if self._cur_const_mode is None:
                self._cur_const_mode = self._param_state[':FUNCTION:TRANSIENT']
            param_info = self._cur_mode_param_info()
            mode_name = param_info['mode_name']
            val = self._param_state[f':{mode_name}:TRANSIENT:MODE']
            self._cur_dynamic_mode = val
            # Force update since this does more than set a parameter - it switches modes
            self._param_state[':FUNCTION:TRANSIENT'] = None
            new_params[':FUNCTION:TRANSIENT'] = self._cur_const_mode
        elif self._cur_overall_mode == 'LED':
            # Force update since this does more than set a parameter - it switches modes
            self._param_state[':FUNCTION'] = None
            new_params[':FUNCTION'] = 'LED'
            self._cur_const_mode = None

        # Changing the mode turns off the load and short
        # We have to do this manually in order for the later mode change to take effect
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_params(new_params)
        self._update_widgets()

    def _on_click_dynamic_mode(self):
        rb = self.sender()
        if not rb.isChecked():
            return

        self._cur_dynamic_mode = rb.wid

        # Changing the mode turns off the load and short
        # We have to do this manually in order for the later mode change to take effect
        self._update_load_state(0)
        self._update_short_state(0)

        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        new_params = {':FUNCTION:TRANSIENT': self._cur_const_mode,
                      f':{mode_name}:TRANSIENT:MODE': rb.wid}

        self._update_params(new_params)
        self._update_widgets()

    def _on_click_const_mode(self):
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_const_mode = rb.wid
        if self._cur_overall_mode == 'Basic':
            new_params = {':FUNCTION': self._cur_const_mode}
        elif self._cur_overall_mode == 'Dynamic':
            new_params = {':FUNCTION:TRANSIENT': self._cur_const_mode}

        # Changing the mode turns off the load and short
        # We have to do this manually in order for the later mode change to take effect
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_params(new_params)
        self._update_widgets()

    def _on_click_range(self):
        rb = self.sender()
        if not rb.isChecked():
            return
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        val = rb.wid
        trans = self._transient_string()
        if val.endswith('V'):
            new_params = {f':{mode_name}{trans}:VRANGE': val.strip('V')}
        else:
            new_params = {f':{mode_name}{trans}:IRANGE': val.strip('A')}
        self._update_params(new_params)
        self._update_widgets()

    def _on_value_change(self):
        input = self.sender()
        mode, scpi = input.wid
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        val = float(input.value())
        new_params = {f':{mode_name}:{scpi}': val}
        self._update_params(new_params)
        self._update_widgets()

    def _on_click_short_enable(self):
        cb = self.sender()
        if cb.isChecked():
            self._widget_registry['ShortONOFF'].setEnabled(True)
        else:
            self._update_short_state(0)
            self._widget_registry['ShortONOFF'].setEnabled(False)

    def _on_click_short_on_off(self):
        bt = self.sender()
        state = 1-self._param_state[':SHORT:STATE']
        self._update_short_state(state)

    def _on_click_load_on_off(self):
        bt = self.sender()
        state = 1-self._param_state[':INPUT:STATE']
        self._update_load_state(state)

    def _on_click_trigger_source(self):
        rb = self.sender()
        if not rb.isChecked():
            return
        new_params = {':TRIGGER:SOURCE': rb.mode.upper()}
        self._update_params(new_params)
        self._update_trigger_buttons()

    def _on_click_trigger(self):
        self._inst.trg()

    def _on_click_enable_measurements(self):
        cb = self.sender()
        match cb.mode:
            case 'V':
                self._enable_measurement_v = cb.isChecked()
            case 'C':
                self._enable_measurement_c = cb.isChecked()
            case 'P':
                self._enable_measurement_p = cb.isChecked()
            case 'R':
                self._enable_measurement_r = cb.isChecked()

    def _update_load_onoff_button(self, state=None):
        if state is None:
            state = self._param_state[':INPUT:STATE']
        bt = self._widget_registry['LoadONOFF']
        if state:
            bt.setText('LOAD IS ON')
            bg_color = '#ffc0c0'
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

    def _update_short_onoff_button(self, state=None):
        if state is None:
            state = self._param_state[':SHORT:STATE']
        bt = self._widget_registry['ShortONOFF']
        if state:
            bt.setText('\u26A0 SHORT IS ON \u26A0')
            bg_color = '#ff0000'
        else:
            bt.setText('SHORT IS OFF')
            bg_color = '#00ff00'
        ss = f"""QPushButton {{
                    background-color: {bg_color};
                    min-width: 7.5em; max-width: 7.5em; min-height: 1.1em; max-height: 1.1em;
                    border-radius: 0.3em; border: 3px solid black;
                    font-weight: bold; font-size: 14px; }}
                 QPushButton::pressed {{ border: 4px solid black; }}
              """
        bt.setStyleSheet(ss)

    def _update_trigger_buttons(self):
        src = self._param_state[':TRIGGER:SOURCE']
        self._widget_registry['Trigger_Bus'].setChecked(src == 'Bus')
        self._widget_registry['Trigger_Man'].setChecked(src == 'Manual')
        self._widget_registry['Trigger_Ext'].setChecked(src == 'External')

        enabled = False
        print(self._cur_overall_mode, self._cur_dynamic_mode)
        if (self._cur_overall_mode == 'Dynamic' and
            self._cur_dynamic_mode != 'Continuous' and
            src == 'Bus' and
            self._param_state[':INPUT:STATE']):
            enabled = True
        self._widget_registry['Trigger'].setEnabled(enabled)


##########################################################################################

class InstrumentSiglentSDL1000(Device4882):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._long_name = f'SDL1000 @ {self._resource_name}'
        if self._resource_name.startswith('TCPIP'):
            ips = self._resource_name.split('.') # This only works with TCP!
            self._name = f'SDL{ips[-1]}'
        else:
            self._name = f'SDL'

    def connect(self, *args, **kwargs):
        super().connect(*args, **kwargs)
        idn = self.idn().split(',')
        if len(idn) != 4:
            assert ValueError
        (self._manufacturer,
         self._model,
         self._serial_number,
         self._firmware_version) = idn
        if self._manufacturer != 'Siglent Technologies':
            assert ValueError
        if not self._model.startswith('SDL'):
            assert ValueError
        self._long_name = f'{self._model} @ {self._resource_name}'
        self._high_power = self._model in ('SDL1030X-E', 'SDL1030X')
        self.write(':SYST:REMOTE:STATE 1') # Lock the keyboard

    def configure_widget(self):
        return InstrumentSiglentSDL1000ConfigureWidget(self)

    def set_input_state(self, val):
        self._validator_1(val)
        self.write(f':INPUT:STATE {val}')

    def measure_voltage(self):
        return float(self.query('MEAS:VOLT?'))

    def measure_current(self):
        return float(self.query('MEAS:CURR?'))

    def measure_power(self):
        return float(self.query('MEAS:POW?'))

    def measure_resistance(self):
        return float(self.query('MEAS:RES?'))

    def measure_vcpr(self):
        return (self.measure_voltage(),
                self.measure_current(),
                self.measure_power(),
                self.measure_resistance())

    ###





"""
# [:SOURce]:CURRent[:LEVel][:IMMediate] {<value> | MINimum| MAXimum | DEFault}
# [:SOURce]:CURRent[:LEVel][:IMMediate]?
# [:SOURce]:CURRent:IRANGe <value>
# [:SOURce]:CURRent:IRANGe?
# [:SOURce]:CURRent:VRANGe <value>
# [:SOURce]:CURRent:VRANGe?
# [:SOURce]:CURRent:SLEW[:BOTH] {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:SLEW:POSitive {<value> | MINimum |MAXimum | DEFault}
# [:SOURce]:CURRent:SLEW:POSitive?
# [:SOURce]:CURRent:SLEW:NEGative {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:SLEW:NEGative?
# [:SOURce]:CURRent:TRANsient:MODE {CONTinuous | PULSe |TOGGle}
# [:SOURce]:CURRent:TRANsient:MODE?
# [:SOURce]:CURRent:TRANsient:IRANGe
# [:SOURce]:CURRent:TRANsient:IRANGe?
# [:SOURce]:CURRent:TRANsient:VRANGe
# [:SOURce]:CURRent:TRANsient:VRANGe?
# [:SOURce]:CURRent:TRANsient:ALEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:ALEVel?
# [:SOURce]:CURRent:TRANsient:BLEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:BLEVel?
# [:SOURce]:CURRent:TRANsient:AWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:AWIDth?
# [:SOURce]:CURRent:TRANsient:BWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:BWIDth?
# [:SOURce]:CURRent:TRANsient:SLEW:POSitive {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:SLEW:POSitive?
# [:SOURce]:CURRent:TRANsient:SLEW:NEGative {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:CURRent:TRANsient:SLEW:NEGative?

# [:SOURce]:VOLTage[:LEVel][:IMMediate] {<value> | MINimum| MAXimum | DEFault}
# [:SOURce]:VOLTage[:LEVel][:IMMediate]?
# [:SOURce]:VOLTage:IRANGe <value>
# [:SOURce]:VOLTage:IRANGe?
# [:SOURce]:VOLTage:VRANGe <value>
# [:SOURce]:VOLTage:VRANGe?
# [:SOURce]:VOLTage:TRANsient:MODE {CONTinuous | PULSe |TOGGle}
# [:SOURce]:VOLTage:TRANsient:MODE?
# [:SOURce]:VOLTage:TRANsient:IRANGe
# [:SOURce]:VOLTage:TRANsient:IRANGe?
# [:SOURce]:VOLTage:TRANsient:VRANGe
# [:SOURce]:VOLTage:TRANsient:VRANGe?
# [:SOURce]:VOLTage:TRANsient:ALEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:VOLTage:TRANsient:ALEVel?
# [:SOURce]:VOLTage:TRANsient:BLEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:VOLTage:TRANsient:BLEVel?
# [:SOURce]:VOLTage:TRANsient:AWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:VOLTage:TRANsient:AWIDth?
# [:SOURce]:VOLTage:TRANsient:BWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:VOLTage:TRANsient:BWIDth?

# [:SOURce]:POWer[:LEVel][:IMMediate] {<value> | MINimum| MAXimum | DEFault}
# [:SOURce]:POWer[:LEVel][:IMMediate]?
# [:SOURce]:POWer:IRANGe <value>
# [:SOURce]:POWer:IRANGe?
# [:SOURce]:POWer:VRANGe <value>
# [:SOURce]:POWer:VRANGe?
# [:SOURce]:POWer:TRANsient:MODE {CONTinuous | PULSe |TOGGle}
# [:SOURce]:POWer:TRANsient:MODE?
# [:SOURce]:POWer:TRANsient:IRANGe
# [:SOURce]:POWer:TRANsient:IRANGe?
# [:SOURce]:POWer:TRANsient:VRANGe
# [:SOURce]:POWer:TRANsient:VRANGe?
# [:SOURce]:POWer:TRANsient:ALEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:POWer:TRANsient:ALEVel?
# [:SOURce]:POWer:TRANsient:BLEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:POWer:TRANsient:BLEVel?
# [:SOURce]:POWer:TRANsient:AWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:POWer:TRANsient:AWIDth?
# [:SOURce]:POWer:TRANsient:BWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:POWer:TRANsient:BWIDth?

# [:SOURce]:RESistance[:LEVel][:IMMediate] {<value> | MINimum| MAXimum | DEFault}
# [:SOURce]:RESistance[:LEVel][:IMMediate]?
# [:SOURce]:RESistance:IRANGe <value>
# [:SOURce]:RESistance:IRANGe?
# [:SOURce]:RESistance:VRANGe <value>
# [:SOURce]:RESistance:VRANGe?
# [:SOURce]:RESistance:RRANGe {LOW | MIDDLE | HIGH | UPPER}
# [:SOURce]:RESistance:RRANGe?
# [:SOURce]:RESistance:TRANsient:MODE {CONTinuous | PULSe |TOGGle}
# [:SOURce]:RESistance:TRANsient:MODE?
# [:SOURce]:RESistance:TRANsient:IRANGe
# [:SOURce]:RESistance:TRANsient:IRANGe?
# [:SOURce]:RESistance:TRANsient:VRANGe
# [:SOURce]:RESistance:TRANsient:VRANGe?
# [:SOURce]:RESistance:TRANsient:RRANGe {LOW | MIDDLE | HIGH | UPPER}
# [:SOURce]:RESistance:TRANsient:RRANGe?
# [:SOURce]:RESistance:TRANsient:ALEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:RESistance:TRANsient:ALEVel?
# [:SOURce]:RESistance:TRANsient:BLEVel {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:RESistance:TRANsient:BLEVel?
# [:SOURce]:RESistance:TRANsient:AWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:RESistance:TRANsient:AWIDth?
# [:SOURce]:RESistance:TRANsient:BWIDth {<value> | MINimum | MAXimum | DEFault}
# [:SOURce]:RESistance:TRANsient:BWIDth?

# [:SOURce]:LED:IRANGe
# [:SOURce]:LED:IRANGe?
# [:SOURce]:LED:VRANGe
# [:SOURce]:LED:VRANGe?
# [:SOURce]:LED:VOLTage {< value > | MINimum | MAXimum | DEFault}
# [:SOURce]:LED:VOLTage?
# [:SOURce]:LED:CURRent {< value > | MINimum | MAXimum | DEFault}
# [:SOURce]:LED:CURRent?
# [:SOURce]:LED: RCOnf {< value > | MINimum | MAXimum | DEFault}
# [:SOURce]:LED: RCOnf?

[:SOURce]:BATTery:FUNC
[:SOURce]:BATTery:FUNC?
[:SOURce]:BATTery:MODE {CURRent | POWer | RESistance}
[:SOURce]:BATTery:MODE?
[:SOURce]:BATTery:IRANGe <value>
[:SOURce]:BATTery:IRANGe?
[:SOURce]:BATTery:VRANGe <value>
[:SOURce]:BATTery:VRANGe?
[:SOURce]:BATTery:RRANGe {LOW | MIDDLE | HIGH | UPPER}
[:SOURce]:BATTery:RRANGe?
[:SOURce]:BATTery:LEVel <value>
[:SOURce]:BATTery:LEVel?
[:SOURce]:BATTery:VOLTage <value > | MINimum | MAXimum | DEFault}
[:SOURce]:BATTery:VOLTage?
[:SOURce]:BATTery:CAPability <value>
[:SOURce]:BATTery:CAPability?
[:SOURce]:BATTery:TIMer?
[:SOURce]:BATTery:VOLTage:STATe {ON | OFF | 0 | 1}
[:SOURce]:BATTery:VOLTage:STATe?
[:SOURce]:BATTery:CAPability:STATe {ON | OFF | 0 | 1}
[:SOURce]:BATTery:CAPability:STATe?
[:SOURce]:BATTery:TIMer:STATe
[:SOURce]:BATTery:TIMer:STATe {ON | OFF | 0 | 1}
[:SOURce]:BATTery:TIMer:STATe?
[:SOURce]:BATTery:DISCHArg:CAPability?
[:SOURce]:BATTery:DISCHArg:TIMer?


[:SOURce]:LIST:MODE {CURRent | VOLTage | POWer | RESistance}
[:SOURce]:LIST:MODE?
[:SOURce]:LIST:IRANGe <value>
[:SOURce]:LIST:IRANGe?
[:SOURce]:LIST:VRANGe <value>
[:SOURce]:LIST:VRANGe?
[:SOURce]:LIST:RRANGe {LOW | MIDDLE | HIGH | UPPER}
[:SOURce]:LIST:RRANGe?
[:SOURce]:LIST:COUNt {< number: int > | MINimum | MAXimum | DEFault}
[:SOURce]:LIST:COUNt?
[:SOURce]:LIST:STEP {< number: int > | MINimum | MAXimum | DEFault}
[:SOURce]:LIST:STEP?
[:SOURce]:LIST:LEVel <step: int, value: float>
[:SOURce]:LIST:LEVel?
[:SOURce]:LIST:SLEW[:BOTH] <step: int, value: float>
[:SOURce]:LIST:SLEW[:BOTH]?
[:SOURce]:LIST:WIDth <step: int, value: float>
[:SOURce]:LIST:WIDth?
[:SOURce]:LIST:STATe:ON
[:SOURce]:LIST:STATe?

[:SOURce]:OCP:FUNC
[:SOURce]:OCP:FUNC?
[:SOURce]:OCP:IRANGe?
[:SOURce]:OCP:VRANGe <value>
[:SOURce]:OCP:VRANGe?
[:SOURce]:OCP:STARt {< value: float,int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:STARt?
[:SOURce]:OCP:STEP {< value: float?, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:STEP?
[:SOURce]:OCP:STEP:DELay {< value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:STEP:DELay?
[:SOURce]:OCP:END {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:END?
[:SOURce]:OCP:MIN {< value: float,int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:MIN?
[:SOURce]:OCP:MAX {< value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:MAX?
[:SOURce]:OCP:VOLTage <value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OCP:VOLTage?

[:SOURce]:OPP:FUNC
[:SOURce]:OPP:FUNC?
[:SOURce]:OPP:IRANGe?
[:SOURce]:OPP:VRANGe <value>
[:SOURce]:OPP:VRANGe?
[:SOURce]:OPP:STARt {< value: float,int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:STARt?
[:SOURce]:OPP:STEP {< value: float?, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:STEP?
[:SOURce]:OPP:STEP:DELay {< value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:STEP:DELay?
[:SOURce]:OPP:END {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:END?
[:SOURce]:OPP:MIN {< value: float,int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:MIN?
[:SOURce]:OPP:MAX {< value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:MAX?
[:SOURce]:OPP:VOLTage <value: float, int > | MINimum | MAXimum | DEFault}
[:SOURce]:OPP:VOLTage?


[:SOURce]:PROGram:STEP {< number > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:STEP?
[:SOURce]:PROGram:MODE <step>, {CURRent | VOLTage | POWer | RESistance | LED}
[:SOURce]:PROGram:MODE? <step>
[:SOURce]:PROGram:IRANGe <step,value>
[:SOURce]:PROGram: VRANGe <step, value>,
[:SOURce]:PROGram: V RANGe? <step>
[:SOURce]:PROGram:RRANGe <step>, {LOW | MIDDLE | HIGH}
[:SOURce]:PROGram:RRANGe? <step>
[:SOURce]:PROGram:SHORt <step>, {ON | OFF | 0 | 1}
[:SOURce]:PROGram:SHORt? <step>
[:SOURce]:PROGram:PAUSE <step>, {ON | OFF | 0 | 1 }
[:SOURce]:PROGram:PAUSE? <step>,
[:SOURce]:PROGram:TIME:ON <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:TIME:ON? <step>
[:SOURce]:PROGram:TIME:OFF <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:TIME:OFF? <step>
[:SOURce]:PROGram:TIME:DELay <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:TIME:DELay? <step>
[:SOURce]:PROGram:MIN <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:MIN? <step>
[:SOURce]:PROGram:MAX <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:MAX? <step>
[:SOURce]:PROGram:LEVel <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:LEVel? <step>
[:SOURce]:PROGram:LED:CURRent <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:LED:CURRent? <step>
[:SOURce]:PROGram:LED:RCOnf <step>, {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:PROGram:LED:RCOnf? <step>
[:SOURce]:PROGram:STATe:ON
[:SOURce]:PROGram:STATe?
[:SOURce]:PROGram:TEST? <step>

[:SOURce]:VOLTage [:LEVel]:ON <step>
[:SOURce]:VOLTage [:LEVel]:ON?
[:SOURce]:VOLTage :LATCh[:STATe] {ON | OFF | 0 | 1}
[:SOURce]:VOLTage :LATCh[:STATe]?
[:SOURce]:EXT:INPUT[:StATe] {ON | OFF | 0 | 1}
[:SOURce]:EXT:INPUT[:StATe]?
[:SOURce]:CURRent:PROTection:STATe {ON | OFF | 0 | 1}
[:SOURce]:EXT:INPUT[:StATe]?
[:SOURce]:CURRent:PROTection:LEVel {< value | MINimum | MAXimum | DEFault}
[:SOURce]:CURRent:PROTection:LEVel?
[:SOURce]:CURRent:PROTection:DELay {< value | MINimum | MAXimum | DEFault}
[:SOURce]:CURRent:PROTection:DELay?
[:SOURce]:POWer:PROTection:STATe {ON | OFF | 0 | 1}
[:SOURce]:POWer:PROTection:STATe?
[:SOURce]:POWer:PROTection:LEVel {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:POWer:PROTection:LEVel?
[:SOURce]:POWer:PROTection:DELay {< value > | MINimum | MAXimum | DEFault}
[:SOURce]:POWer:PROTection:DELay?

SYSTem:SENSe[:STATe] {ON | OFF | 0 | 1}
SYSTem:SENSe[:STATe]?
SYSTem:IMONItor[:STATe] {ON | OFF | 0 | 1}
SYSTem:IMONItor[:STATe]?
SYSTem:VMONItor [: {ON | OFF | 0 | 1}
SYSTem:VMONItor[:STATe]?
STOP:ON:FAIL[:STATe] {ON | OFF | 0 | 1}
STOP:ON:FAIL[:STATe]?

TRIGger:SOURce {MANUal | EXTernal | BUS}
TRIGger:SOURce?
SENSe:AVERage:COUNt {6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14}
SENSe:AVERage:COUNt?
EXT:MODE {INT | EXTI | EXTV}
EXT:MODE?
EXT:IRANGe <value>
EXT:IRANGe?
EXT:VRANGe <value>
EXT:VRANGe?
TIME:TEST[:STATe] {ON | OFF | 0 | 1}
TIME:TEST[:STATe]?
TIME:TEST:VOLTage:LOW {< value > | MINimum | MAXimum | DEFault}
TIME:TEST:VOLTage:LOW?
TIME:TEST:VOLTage:HIGH {< value | MINimum | MAXimum | DEFault}
TIME:TEST:VOLTage:HIGH?
TIME:TEST:RISE?
TIME:TEST:FALL?
"""
