################################################################################
# siglent_sdl1000.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains all code related to the Siglent SDL1000 series:
#   - SDL1020X
#   - SDL1020X-E
#   - SDL1030X
#   - SDL1030X-E
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

# The behavior of :FUNCTION and :FUNCTION:MODE is confusing. Here are the details.
#
# :FUNCTION:MODE? is an undocumented SCPI command that is ONLY useful for queries. You
#   cannot use it to set the mode!
#       It returns one of: BASIC, TRAN, BATTERY, OCP, OPP, LIST, PROGRAM
#   Note that LED is considered a BASIC mode.
#
# :FUNCTION <mode> is used to set the "constant" mode while in the BASIC mode. If the
#   instrument is not currently in the BASIC mode, this places it in the BASIC mode.
#   There is no way to go into the BASIC mode without also specifying the "constant"
#   mode. LED mode is considered a BASIC mode, so to put the instrument in LED mode,
#   execute
#       :FUNCTION LED
#
# :FUNCTION:TRANSIENT <mode> does the same thing as :FUNCTION but for the TRANSIENT
#   (Dynamic) mode. It can both query the current "constant" mode and put the instrument
#   into the Dynamic mode.
#
# To place the instrument in other modes, you use specific commands:
#   :BATTERY:FUNC
#   :OCP:FUNC
#   :OPP:FUNC
#   :LIST:STATE:ON
#   :PROGRAM:STATE:ON


import json
import pprint
import time
import re

from PyQt6.QtWidgets import (QWidget,
                             QAbstractSpinBox,
                             QButtonGroup,
                             QCheckBox,
                             QDialog,
                             QDoubleSpinBox,
                             QFileDialog,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QLabel,
                             QLayout,
                             QLineEdit,
                             QMessageBox,
                             QPushButton,
                             QRadioButton,
                             QSpinBox,
                             QVBoxLayout)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt

from .device import Device4882, ContactLostError
from .config_widget_base import ConfigureWidgetBase


_SDL_OVERALL_MODES = {
    'Basic':   ('!Dynamic_Mode_.*', 'Const_.*',),
    'Dynamic': ('Dynamic_Mode_.*',  'Const_.*',),
    'LED':     ('!Dynamic_Mode_.*', '!Const_.*',),
    'Battery': ('!Dynamic_Mode_.*', 'Const_.*', '!Const_Voltage'),
    'List':    ('!Dynamic_Mode_.*', 'Const_.*',),
    'Program': ('!Dynamic_Mode_.*', '!Const_.*',),
    'OCPT':    ('!Dynamic_Mode_.*', '!Const_.*',),
    'OPPT':    ('!Dynamic_Mode_.*', '!Const_.*',),
}

_SDL_MODE_PARAMS = {
    ('General'):
        {'widgets': ('~MainParametersLabel_.*', '~MainParameters_.*',
                     '~AuxParametersLabel_.*', '~AuxParameters_.*',
                     '~MeasureBatt.*', '~ClearAddCap'),
         'mode_name': None,
         'params': (
            # For General only! The third param is True meaning to write it while
            # copying _param_state to the instrument.
            # SYST:REMOTE:STATE is undocumented! It locks the keyboard and
            # sets the remote access icon
            ('SYST:REMOTE:STATE',  'b', False),
            ('INPUT:STATE',        'b', False),
            ('SHORT:STATE',        'b', False),
            ('FUNCTION',           'r', False),
            ('FUNCTION:TRANSIENT', 'r', False),
            # FUNCtion:MODE is undocumented! Possible return values are:
            #   BASIC, TRAN, BATTERY, OCP, OPP, LIST, PROGRAM
            ('FUNCTION:MODE',      's', False),
            ('BATTERY:MODE',       's', True),
            ('TRIGGER:SOURCE',     's', True),
         )
        },
    ('Basic', 'Voltage'):
        {'widgets': None,
         'mode_name': 'VOLTAGE',
         'params': (
            ('IRANGE',            'r', None, 'Range_Current_.*'),
            ('VRANGE',            'r', None, 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', '.3f', 'MainParametersLabel_Voltage', 'MainParameters_Voltage', 0, 'V'),
          )
        },
    ('Basic', 'Current'):
        {'widgets': None,
         'mode_name': 'CURRENT',
         'params': (
            ('IRANGE',            'r', None, 'Range_Current_.*'),
            ('VRANGE',            'r', None, 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', '.3f', 'MainParametersLabel_Current', 'MainParameters_Current', 0, 'C'),
            ('SLEW:POSITIVE',   '.3f', 'AuxParametersLabel_BSlewPos', 'AuxParameters_BSlewPos', 0.001, 2.5),
            ('SLEW:NEGATIVE',   '.3f', 'AuxParametersLabel_BSlewNeg', 'AuxParameters_BSlewNeg', 0.001, 2.5),
          )
        },
    ('Basic', 'Power'):
        {'widgets': None,
         'mode_name': 'POWER',
         'params': (
            ('IRANGE',            'r', None, 'Range_Current_.*'),
            ('VRANGE',            'r', None, 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', '.3f', 'MainParametersLabel_Power', 'MainParameters_Power', 0, 'P'),
          )
        },
    ('Basic', 'Resistance'):
        {'widgets': None,
         'mode_name': 'RESISTANCE',
         'params': (
            ('IRANGE',            'r', None, 'Range_Current_.*'),
            ('VRANGE',            'r', None, 'Range_Voltage_.*'),
            ('LEVEL:IMMEDIATE', '.3f', 'MainParametersLabel_Resistance', 'MainParameters_Resistance', 0.030, 10000),
          )
        },
    ('LED', None): # This behaves like a Basic mode
        {'widgets': None,
         'mode_name': 'LED',
         'params': (
            ('IRANGE',    'r', None, 'Range_Current_.*'),
            ('VRANGE',    'r', None, 'Range_Voltage_.*'),
            ('VOLTAGE', '.3f', 'MainParametersLabel_LEDV', 'MainParameters_LEDV', 0.010, 'V'),
            ('CURRENT', '.3f', 'MainParametersLabel_LEDC', 'MainParameters_LEDC', 0, 'C'),
            ('RCONF',   '.2f', 'MainParametersLabel_LEDR', 'MainParameters_LEDR', 0.01, 1),
          )
        },
    ('Battery', 'Current'):
        {'widgets': ('MeasureBatt.*', 'ClearAddCap'),
         'mode_name': 'BATTERY',
         'params': (
            ('IRANGE',    'r', None, 'Range_Current_.*'),
            ('VRANGE',    'r', None, 'Range_Voltage_.*'),
            ('LEVEL',   '.3f', 'MainParametersLabel_BATTC', 'MainParameters_BATTC', 0, 'C'),
            ('VOLTAGE', '.3f', 'MainParametersLabel_BATTVSTOP', 'MainParameters_BATTVSTOP', 0, 'V'),
            ('CAP',       'd', 'MainParametersLabel_BATTCAPSTOP', 'MainParameters_BATTCAPSTOP', 0, 999999),
            ('TIMER',     'd', 'MainParametersLabel_BATTTSTOP', 'MainParameters_BATTTSTOP', 0, 86400),
          )
        },
    ('Battery', 'Power'):
        {'widgets': ('MeasureBatt.*', 'ClearAddCap'),
         'mode_name': 'BATTERY',
         'params': (
            ('IRANGE',    'r', None, 'Range_Current_.*'),
            ('VRANGE',    'r', None, 'Range_Voltage_.*'),
            ('LEVEL',   '.3f', 'MainParametersLabel_BATTP', 'MainParameters_BATTP', 0, 'P'),
            ('VOLTAGE', '.3f', 'MainParametersLabel_BATTVSTOP', 'MainParameters_BATTVSTOP', 0, 'V'),
            ('CAP',       'd', 'MainParametersLabel_BATTCAPSTOP', 'MainParameters_BATTCAPSTOP', 0, 999999),
            ('TIMER',     'd', 'MainParametersLabel_BATTTSTOP', 'MainParameters_BATTTSTOP', 0, 86400),
          )
        },
    ('Battery', 'Resistance'):
        {'widgets': ('MeasureBatt.*', 'ClearAddCap'),
         'mode_name': 'BATTERY',
         'params': (
            ('IRANGE',    'r', None, 'Range_Current_.*'),
            ('VRANGE',    'r', None, 'Range_Voltage_.*'),
            ('LEVEL',   '.3f', 'MainParametersLabel_BATTR', 'MainParameters_BATTR', 0.030, 10000),
            ('VOLTAGE', '.3f', 'MainParametersLabel_BATTVSTOP', 'MainParameters_BATTVSTOP', 0, 'V'),
            ('CAP',       'd', 'MainParametersLabel_BATTCAPSTOP', 'MainParameters_BATTCAPSTOP', 0, 999999),
            ('TIMER',     'd', 'MainParametersLabel_BATTTSTOP', 'MainParameters_BATTTSTOP', 0, 86400),
          )
        },
    ('Dynamic', 'Voltage', 'Continuous'):
        {'widgets': None,
         'mode_name': 'VOLTAGE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelV', 'MainParameters_ALevelV', 0, 'V'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelV', 'MainParameters_BLevelV', 0, 'V'),
            ('TRANSIENT:AWIDTH', '.3f', 'MainParametersLabel_AWidth',  'MainParameters_AWidth', 1, 999),
            ('TRANSIENT:BWIDTH', '.3f', 'MainParametersLabel_BWidth',  'MainParameters_BWidth', 1, 999),
          )
        },
    ('Dynamic', 'Voltage', 'Pulse'):
        {'widgets': None,
         'mode_name': 'VOLTAGE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelV', 'MainParameters_ALevelV', 0, 'V'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelV', 'MainParameters_BLevelV', 0, 'V'),
            ('TRANSIENT:BWIDTH', '.3f', 'MainParametersLabel_Width',   'MainParameters_Width', 1, 999),
          )
        },
    ('Dynamic', 'Voltage', 'Toggle'):
        {'widgets': None,
         'mode_name': 'VOLTAGE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelV', 'MainParameters_ALevelV', 0, 'V'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelV', 'MainParameters_BLevelV', 0, 'V'),
          )
        },
    ('Dynamic', 'Current', 'Continuous'):
        {'widgets': None,
         'mode_name': 'CURRENT',
         'params': (
            ('TRANSIENT:IRANGE',          'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',          'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',            'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL',        '.3f', 'MainParametersLabel_ALevelC', 'MainParameters_ALevelC', 0, 'C'),
            ('TRANSIENT:BLEVEL',        '.3f', 'MainParametersLabel_BLevelC', 'MainParameters_BLevelC', 0, 'C'),
            ('TRANSIENT:AWIDTH',        '.6f', 'MainParametersLabel_AWidth',  'MainParameters_AWidth', 0.000020, 999),
            ('TRANSIENT:BWIDTH',        '.6f', 'MainParametersLabel_BWidth',  'MainParameters_BWidth', 0.000020, 999),
            ('TRANSIENT:SLEW:POSITIVE', '.3f', 'AuxParametersLabel_TSlewPos', 'AuxParameters_TSlewPos', 0.001, 0.5),
            ('TRANSIENT:SLEW:NEGATIVE', '.3f', 'AuxParametersLabel_TSlewNeg', 'AuxParameters_TSlewNeg', 0.001, 0.05),
          )
        },
    ('Dynamic', 'Current', 'Pulse'):
        {'widgets': None,
         'mode_name': 'CURRENT',
         'params': (
            ('TRANSIENT:IRANGE',          'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',          'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',            'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL',        '.3f', 'MainParametersLabel_ALevelC', 'MainParameters_ALevelC', 0, 'C'),
            ('TRANSIENT:BLEVEL',        '.3f', 'MainParametersLabel_BLevelC', 'MainParameters_BLevelC', 0, 'C'),
            ('TRANSIENT:BWIDTH',        '.6f', 'MainParametersLabel_Width',   'MainParameters_Width', 0.000020, 999),
            ('TRANSIENT:SLEW:POSITIVE', '.3f', 'AuxParametersLabel_TSlewPos', 'AuxParameters_TSlewPos', 0.001, 0.5),
            ('TRANSIENT:SLEW:NEGATIVE', '.3f', 'AuxParametersLabel_TSlewNeg', 'AuxParameters_TSlewNeg', 0.001, 0.05),
          )
        },
    ('Dynamic', 'Current', 'Toggle'):
        {'widgets': None,
         'mode_name': 'CURRENT',
         'params': (
            ('TRANSIENT:IRANGE',          'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',          'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',            'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL',        '.3f', 'MainParametersLabel_ALevelC', 'MainParameters_ALevelC', 0, 'C'),
            ('TRANSIENT:BLEVEL',        '.3f', 'MainParametersLabel_BLevelC', 'MainParameters_BLevelC', 0, 'C'),
            ('TRANSIENT:SLEW:POSITIVE', '.3f', 'AuxParametersLabel_TSlewPos', 'AuxParameters_TSlewPos', 0.001, 0.5),
            ('TRANSIENT:SLEW:NEGATIVE', '.3f', 'AuxParametersLabel_TSlewNeg', 'AuxParameters_TSlewNeg', 0.001, 0.05),
          )
        },
    ('Dynamic', 'Power', 'Continuous'):
        {'widgets': None,
         'mode_name': 'POWER',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelP', 'MainParameters_ALevelP', 0, 'P'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelP', 'MainParameters_BLevelP', 0, 'P'),
            ('TRANSIENT:AWIDTH', '.6f', 'MainParametersLabel_AWidth',  'MainParameters_AWidth', 0.000040, 999),
            ('TRANSIENT:BWIDTH', '.6f', 'MainParametersLabel_BWidth',  'MainParameters_BWidth', 0.000040, 999),
          )
        },
    ('Dynamic', 'Power', 'Pulse'):
        {'widgets': None,
         'mode_name': 'POWER',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelP', 'MainParameters_ALevelP', 0, 'P'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelP', 'MainParameters_BLevelP', 0, 'P'),
            ('TRANSIENT:BWIDTH', '.6f', 'MainParametersLabel_Width',   'MainParameters_Width', 0.000040, 999),
          )
        },
    ('Dynamic', 'Power', 'Toggle'):
        {'widgets': None,
         'mode_name': 'POWER',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelP', 'MainParameters_ALevelP', 0, 'P'),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelP', 'MainParameters_BLevelP', 0, 'P'),
          )
        },

    ('Dynamic', 'Resistance', 'Continuous'):
        {'widgets': None,
         'mode_name': 'RESISTANCE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelR', 'MainParameters_ALevelR', 0.030, 10000),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelR', 'MainParameters_BLevelR', 0.030, 10000),
            ('TRANSIENT:AWIDTH', '.3f', 'MainParametersLabel_AWidth',  'MainParameters_AWidth', 0.001, 999),
            ('TRANSIENT:BWIDTH', '.3f', 'MainParametersLabel_BWidth',  'MainParameters_BWidth', 0.001, 999),
          )
        },
    ('Dynamic', 'Resistance', 'Pulse'):
        {'widgets': None,
         'mode_name': 'RESISTANCE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelR', 'MainParameters_ALevelR', 0.030, 10000),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelR', 'MainParameters_BLevelR', 0.030, 10000),
            ('TRANSIENT:BWIDTH', '.3f', 'MainParametersLabel_Width',   'MainParameters_Width', 0.001, 999),
          )
        },
    ('Dynamic', 'Resistance', 'Toggle'):
        {'widgets': None,
         'mode_name': 'RESISTANCE',
         'params': (
            ('TRANSIENT:IRANGE',   'r', None, 'Range_Current_.*'),
            ('TRANSIENT:VRANGE',   'r', None, 'Range_Voltage_.*'),
            ('TRANSIENT:MODE',     'r', None, 'Dynamic_Mode_.*'),
            ('TRANSIENT:ALEVEL', '.3f', 'MainParametersLabel_ALevelR', 'MainParameters_ALevelR', 0.030, 10000),
            ('TRANSIENT:BLEVEL', '.3f', 'MainParametersLabel_BLevelR', 'MainParameters_BLevelR', 0.030, 10000),
          )
        },
    ('OCPT', None):
        {'widgets': None,
         'mode_name': 'OCP',
         'params': (
            ('IRANGE',       'r', None, 'Range_Current_.*'),
            ('VRANGE',       'r', None, 'Range_Voltage_.*'),
            ('VOLTAGE',    '.3f', 'MainParametersLabel_OCPV', 'MainParameters_OCPV', 0, 'V'),
            ('START',      '.3f', 'MainParametersLabel_OCPSTART', 'MainParameters_OCPSTART', 0, 'C'), # END XXX
            ('END',        '.3f', 'MainParametersLabel_OCPEND', 'MainParameters_OCPEND', 0, 'C'), # START XXX
            ('STEP',       '.3f', 'MainParametersLabel_OCPSTEP', 'MainParameters_OCPSTEP', 0, 'C'),
            ('STEP:DELAY', '.3f', 'MainParametersLabel_OCPDELAY', 'MainParameters_OCPDELAY', 0.001, 999),
            ('MIN',        '.3f', 'AuxParametersLabel_OCPMIN', 'AuxParameters_OCPMIN', 0, 'C'), # MAX XXX
            ('MAX',        '.3f', 'AuxParametersLabel_OCPMAX', 'AuxParameters_OCPMAX', 0, 'C'), # MIN XXX
          )
        },
    ('OPPT', None):
        {'widgets': None,
         'mode_name': 'OPP',
         'params': (
            ('IRANGE',       'r', None, 'Range_Current_.*'),
            ('VRANGE',       'r', None, 'Range_Voltage_.*'),
            ('VOLTAGE',    '.3f', 'MainParametersLabel_OPPV', 'MainParameters_OPPV', 0, 'V'),
            ('START',      '.2f', 'MainParametersLabel_OPPSTART', 'MainParameters_OPPSTART', 0, 'P'), # END XXX
            ('END',        '.2f', 'MainParametersLabel_OPPEND', 'MainParameters_OPPEND', 0, 'P'), # START XXX
            ('STEP',       '.2f', 'MainParametersLabel_OPPSTEP', 'MainParameters_OPPSTEP', 0, 'P'),
            ('STEP:DELAY', '.3f', 'MainParametersLabel_OPPDELAY', 'MainParameters_OPPDELAY', 0.001, 999),
            ('MIN',        '.3f', 'AuxParametersLabel_OPPMIN', 'AuxParameters_OPPMIN', 0, 'P'), # MAX XXX
            ('MAX',        '.3f', 'AuxParametersLabel_OPPMAX', 'AuxParameters_OPPMAX', 0, 'P'), # MIN XXX
          )
        },
}

class InstrumentSiglentSDL1000ConfigureWidget(ConfigureWidgetBase):
    def __init__(self, *args, **kwargs):
        self._cur_overall_mode = None
        self._cur_const_mode = None
        self._cur_dynamic_mode = None
        self._enable_measurement_v = True
        self._enable_measurement_c = True
        self._enable_measurement_p = True
        self._enable_measurement_r = True
        self._disable_callbacks = False
        self._load_on_time = None
        self._load_off_time = None
        self._reset_batt_log()
        super().__init__(*args, **kwargs)

    ### Public methods

    def refresh(self):
        """Read all parameters from the instrument and set our internal state to match."""
        self._param_state = {}
        for mode, info in _SDL_MODE_PARAMS.items():
            mode_name = info['mode_name']
            if mode_name is None: # General parameters
                mode_name = ''
            else:
                mode_name = ':'+mode_name
            for param_spec in info['params']:
                param = f'{mode_name}:{param_spec[0]}'
                if param in self._param_state:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    continue
                val = self._inst.query(param+'?')
                param_type = param_spec[1][-1]
                if param_type == 'f': # Float
                    val = float(val)
                elif param_type == 'b' or param_type == 'd': # Boolean or Decimal
                    val = int(float(val))
                elif param_type == 's' or param_type == 'r': # String or radio button
                    val = val.title()
                else:
                    assert False, 'Unknown param_type '+str(param_type)
                self._param_state[param] = val

        self._update_state_from_param_state()

    def _update_state_from_param_state(self):
        """Update all internal state and widgets based on the current _param_state."""
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
            param_info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
            mode_name = param_info['mode_name']
            val = self._param_state[f':{mode_name}:TRANSIENT:MODE']
            self._cur_dynamic_mode = val
        elif mode == 'Battery':
            self._cur_const_mode = self._param_state[':BATTERY:MODE']
        else:
            self._cur_const_mode = None

        self._update_widgets()

    def update_instrument(self):
        """Update the instrument with the current _param_state.

        This is tricker than it should be, because if you send a configuration
        command to the SDL for a mode it's not currently in, it crashes!"""
        set_params = set()
        for mode, info in _SDL_MODE_PARAMS.items():
            mode_name = info['mode_name']
            if mode_name is None: # General parameters
                mode_name = ''
            else:
                mode_name = ':'+mode_name

            first_write = True
            for param_spec in info['params']:
                if not param_spec[2]:
                    continue # This captures the General True/False flag
                param = f'{mode_name}:{param_spec[0]}'
                if param in set_params:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    continue

                if first_write and mode_name:
                    first_write = False
                    # We have to put the instrument in the correct mode before setting the
                    # parameters
                    if mode[0] == 'Dynamic':
                        self._inst.write(f':FUNCTION:TRANSIENT {mode[1]}')
                    elif mode[0] == 'Basic':
                        self._inst.write(f':FUNCTION {mode[1]}')
                    elif mode[0] == 'Battery':
                        self._inst.write(':FUNCTION BATTERY')
                        self._inst.write(f':BATTERY:MODE {mode[1]}')
                    else:
                        self._inst.write(f':FUNCTION {mode[0]}')

                set_params.add(param)
                val = self._param_state[param]
                self._update_one_param(param, val)

        self._update_state_from_param_state()

    def measurement_details(self):
        """Return metadata about the available measurements."""
        ret = []
        if self._enable_measurement_v:
            ret.append({'name': 'Voltage',
                        'units': 'V'})
        if self._enable_measurement_c:
            ret.append({'name': 'Current',
                        'units': 'A'})
        if self._enable_measurement_p:
            ret.append({'name': 'Power',
                        'units': 'W'})
        if self._enable_measurement_r:
            ret.append({'name': 'Resistance',
                        'units': '\u2126'})
        if self._cur_overall_mode == 'Battery':
            ret.append({'name': 'Discharge Time',
                        'units': 's'})
            ret.append({'name': 'Capacity',
                        'units': 'mAh'})
            ret.append({'name': 'Addl Capacity',
                        'units': 'mAh'})
            ret.append({'name': 'Total Capacity',
                        'units': 'mAh'})
        return ret

    def update_measurements(self):
        """Read current values, update control panel display, return the values."""
        # Update the load on/off state in case we hit a protection limit
        input_state = int(self._inst.query(':INPUT:STATE?'))
        if self._param_state[':INPUT:STATE'] != input_state:
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

        if self._cur_overall_mode == 'Battery':
            if self._batt_log_initial_voltage is None:
                self._batt_log_initial_voltage = voltage
            disch_time = self._inst.measure_battery_time()
            m, s = divmod(disch_time, 60)
            h, m = divmod(m, 60)
            w = self._widget_registry['MeasureBattTime']
            w.setText('%02d:%02d:%02d' % (h, m, s))

            w = self._widget_registry['MeasureBattCap']
            disch_cap = self._inst.measure_battery_capacity()
            w.setText('%d mAh' % disch_cap)

            w = self._widget_registry['MeasureBattAddCap']
            add_cap = self._inst.measure_battery_add_capacity()
            w.setText('Addl Cap: %6d mAh' % add_cap)

            # When the LOAD is OFF, we have already updated the ADDCAP to include the
            # current test results, so we don't want to add it in a second time
            if input_state:
                val = disch_cap+add_cap
            else:
                val = add_cap
            w = self._widget_registry['MeasureBattTotalCap']
            w.setText('Total Cap: %6d mAh' % val)


    ### Override from ConfigureWidgetBase

    def _menu_do_about(self):
        msg = 'Siglent SDL1000-series\n\nBy Robert S. French'
        QMessageBox.about(self, 'About', msg)

    def _menu_do_save_configuration(self):
        fn = QFileDialog.getSaveFileName(self, caption='Save Configuration',
                                         filter='All (*.*);;Configuration (*.scfg)',
                                         initialFilter='Configuration (*.scfg)')
        fn = fn[0]
        if not fn:
            return
        with open(fn, 'w') as fp:
            json.dump(self._param_state, fp, sort_keys=True, indent=4)

    def _menu_do_load_configuration(self):
        fn = QFileDialog.getOpenFileName(self, caption='Load Configuration',
                                         filter='All (*.*);;Configuration (*.scfg)',
                                         initialFilter='Configuration (*.scfg)')
        fn = fn[0]
        if not fn:
            return
        with open(fn, 'r') as fp:
            self._param_state = json.load(fp)
        # Clean up the param state. We don't want to start with the load or short on.
        self._param_state['SYST:REMOTE:STATE'] = 1
        self._update_load_state(0)
        self._param_state['INPUT:STATE'] = 0
        self._update_short_state(0)
        self._param_state['SHORT:STATE'] = 0
        print('Incoming :FUNCTION', self._param_state[':FUNCTION'])
        print('Incoming :FUNCTION:MODE', self._param_state[':FUNCTION:MODE'])
        self.update_instrument()

    def _menu_do_reset_device(self):
        # A reset takes around 6.75 seconds, so we wait up to 10s to be safe.
        self.setEnabled(False)
        self.repaint()
        self._inst.write('*RST', timeout=10000)
        self.refresh()
        self.setEnabled(True)


    ### Internal routines

    def _transient_string(self):
        if self._cur_overall_mode == 'Dynamic':
            return ':TRANSIENT'
        return ''

    def _update_load_state(self, state):
        old_state = self._param_state[':INPUT:STATE']
        new_param_state = {':INPUT:STATE': state}

        if state != old_state:
            if state:
                self._load_on_time = time.time()
                self._batt_log_initial_voltage = None
            else:
                self._load_off_time = time.time()

            if not state and self._cur_overall_mode == 'Battery':
                # For some reason when using Battery mode remotely, when the test is
                # complete (or aborted), the ADDCAP field is not automatically updated like
                # it is when you run a test from the front panel. So we do the computation
                # and update it here.
                disch_cap = self._inst.measure_battery_capacity()
                add_cap = self._inst.measure_battery_add_capacity()
                self._inst.write(f':BATT:ADDCAP {disch_cap + add_cap}')
                # Update the battery log entries
                if self._load_on_time is not None and self._load_off_time is not None:
                    match self._cur_const_mode:
                        case 'Current':
                            batt_mode = 'CC %.3fA' % self._param_state[':BATTERY:LEVEL']
                        case 'Power':
                            batt_mode = 'CP %.3fW' % self._param_state[':BATTERY:LEVEL']
                        case 'Resistance':
                            batt_mode = 'CR %.3f\u2126' % self._param_state[
                                                                        ':BATTERY:LEVEL']
                    self._batt_log_modes.append(batt_mode)
                    stop_cond = ''
                    stop_cond += 'Vmin %.3fV' % self._param_state[':BATTERY:VOLTAGE']
                    if stop_cond != '':
                        stop_cond += ' or '
                    stop_cond += 'Cap %.3fAh' % (self._param_state[':BATTERY:CAP']/1000)
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
                    print(self._batt_log_report())

        self._update_params(new_param_state)
        self._update_load_onoff_button(state)
        self._update_trigger_buttons()

    def _update_short_state(self, state):
        new_param_state = {':SHORT:STATE': state}
        self._update_params(new_param_state)
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

    def _update_widgets(self):
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
        # value and set the widget parameters, as appropriate.
        params = param_info['params']
        mode_name = param_info['mode_name']
        new_param_state = {}
        for scpi_cmd, param_full_type, *rest in params:
            param_type = param_full_type[-1]

            # Parse out the label and main widget REs and the min/max values
            match len(rest):
                case 2:
                    # Just a label and main widget, no value range
                    widget_label, widget_main = rest
                case 4:
                    # A label and main widget with min/max value
                    widget_label, widget_main, min_val, max_val = rest
                    trans = self._transient_string()
                    if min_val in ('C', 'V', 'P'):
                        min_val = 0
                    match max_val:
                        case 'C': # Based on current range selection (5A, 30A)
                            max_val = self._param_state[f':{mode_name}{trans}:IRANGE']
                            max_val = float(max_val)
                        case 'V': # Based on voltage range selection (36V, 150V)
                            max_val = self._param_state[f':{mode_name}{trans}:VRANGE']
                            max_val = float(max_val)
                        case 'P': # Based on SDL model - SDL1020 is 200W, SDL1030 is 300W
                            if self._inst._high_power:
                                max_val = 300
                            else:
                                max_val = 200
                case _:
                    assert False, f'Unknown widget parameters {rest}'

            if widget_label is not None:
                self._widget_registry[widget_label].show()
                self._widget_registry[widget_label].setEnabled(True)

            val = self._param_state[f':{mode_name}:{scpi_cmd}']

            if param_type == 'd' or param_type == 'f':
                widget = self._widget_registry[widget_main]
                widget.setEnabled(True)
                widget.show()
                widget.setMaximum(max_val)
                widget.setMinimum(min_val)

            match param_type:
                case 'd': # Decimal
                    widget.setDecimals(0)
                    widget.setValue(val)
                    # It's possible that setting the minimum or maximum caused the value
                    # to change, which means we need to update our state.
                    if val != int(float(widget.value())):
                        new_param_state[f':{mode_name}:{scpi_cmd}'] = float(widget.value())
                case 'f': # Floating point
                    assert param_full_type[0] == '.'
                    widget.setDecimals(int(param_full_type[1:-1]))
                    widget.setValue(val)
                    # It's possible that setting the minimum or maximum caused the value
                    # to change, which means we need to update our state.
                    if val != float(widget.value()):
                        new_param_state[f':{mode_name}:{scpi_cmd}'] = float(widget.value())
                case 'r': # Radio button
                    # In this case only the widget_main is an RE
                    for trial_widget in self._widget_registry:
                        if re.fullmatch(widget_main, trial_widget):
                            checked = trial_widget.upper().endswith('_'+str(val).upper())
                            self._widget_registry[trial_widget].setChecked(checked)
                case _:
                    assert False, f'Unknown param type {param_type}'

        self._update_params(new_param_state)

        # Update the buttons
        self._update_load_onoff_button()
        self._update_short_onoff_button()
        self._update_trigger_buttons()

        self._disable_callbacks = False

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

    def _update_params(self, new_param_state):
        # print('Old')
        # print(pprint.pformat(self._param_state))
        # print()
        # print('New')
        # print(pprint.pformat(new_param_state))
        # print()
        for key, data in new_param_state.items():
            if data != self._param_state[key]:
                self._update_one_param(key, data)
                self._param_state[key] = data

    def _update_one_param(self, key, data):
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
        return '%d:%02d:%02d' % (h, m, s)

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
            ret += 'Initial voltage: %.3fV\n'%self._batt_log_initial_voltages[0]
        cap = sum(self._batt_log_caps)
        ret += 'Capacity: %.3fAh\n' % (cap/1000)
        if not single:
            for i in range(n_entries):
                ret += '** Test segment #%d **\n' % (i+1)
                ret += 'Start time: '+self._time_to_str(self._batt_log_start_times[i])+'\n'
                ret += 'End time: '+self._time_to_str(self._batt_log_end_times[i])+'\n'
                ret += 'Test time: '+self._time_to_hms(self._batt_log_run_times[i])+'\n'
                ret += 'Test mode: '+self._batt_log_modes[i]+'\n'
                ret += 'Stop condition: '+self._batt_log_stop_cond[i]+'\n'
                ret += 'Initial voltage: %.3f\n'%self._batt_log_initial_voltages[i]
                ret += 'Capacity: %.3fAh\n' % (self._batt_log_caps[i]/1000)
        return ret


    ############################################################################
    ### SETUP WINDOW LAYOUT
    ############################################################################

    def _init_widgets(self):
        toplevel_widget = self._toplevel_widget()

        ### Update menubar

        action = QAction('&Parameters', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_parameters)
        self._menubar_view.addAction(action)
        action = QAction('&Load and Trigger', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_load_trigger)
        self._menubar_view.addAction(action)
        action = QAction('&Measurements', self, checkable=True)
        action.setChecked(True)
        action.triggered.connect(self._menu_do_view_measurements)
        self._menubar_view.addAction(action)

        ### Set up window widgets

        main_vert_layout = QVBoxLayout(toplevel_widget)
        main_vert_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ###### ROW 1 ######

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_parameters = w;

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

        frame = self._init_widgets_value_box('Aux Parameters', (
                    ('Slew (rise)', 'BSlewPos', 'A/\u00B5', 'SLEW:POSITIVE'),
                    ('Slew (fall)', 'BSlewNeg', 'A/\u00B5', 'SLEW:NEGATIVE'),
                    ('Slew (rise)', 'TSlewPos', 'A/\u00B5', 'TRANSIENT:SLEW:POSITIVE'),
                    ('Slew (fall)', 'TSlewNeg', 'A/\u00B5', 'TRANSIENT:SLEW:NEGATIVE'),
                    ('I Min', 'OCPMIN', 'A', 'MIN'),
                    ('I Max', 'OCPMAX', 'A', 'MAX'),
                    ('P Min', 'OPPMIN', 'W', 'MIN'),
                    ('P Max', 'OPPMAX', 'W', 'MAX'),
                    ))
        ss = """QGroupBox { min-width: 11em; max-width: 11em;
                            min-height: 5em; max-height: 5em; }
                QDoubleSpinBox { min-width: 5.5em; max-width: 5.5em; }
             """
        frame.setStyleSheet(ss)
        layouts.addWidget(frame)

        ### COLUMN 4 ###

        frame = self._init_widgets_value_box('Main Parameters', (
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
                    ('Width', 'Width', 's', 'TRANSIENT:BWIDTH'),
                    ('Vo', 'LEDV', 'V', 'VOLTAGE'),
                    ('Io', 'LEDC', 'A', 'CURRENT'),
                    ('Rco', 'LEDR', None, 'RCONF'),
                    ('Current', 'BATTC', 'A', 'LEVEL'),
                    ('Power', 'BATTP', 'W', 'LEVEL'),
                    ('Resistance', 'BATTR', '\u2126', 'LEVEL'),
                    ('V Stop', 'BATTVSTOP', 'V', 'VOLTAGE'),
                    ('Cap Stop', 'BATTCAPSTOP', 'mAh', 'CAP'),
                    ('Time Stop', 'BATTTSTOP', 's', 'TIMER'),
                    ('Von', 'OCPV', 'V', 'VOLTAGE'),
                    ('I Start', 'OCPSTART', 'A', 'START'),
                    ('I End', 'OCPEND', 'A', 'END'),
                    ('I Step', 'OCPSTEP', 'A', 'STEP'),
                    ('Step Delay', 'OCPDELAY', 's', 'STEP:DELAY'),
                    ('Prot V', 'OPPV', 'V', 'VOLTAGE'),
                    ('P Start', 'OPPSTART', 'W', 'START'),
                    ('P End', 'OPPEND', 'W', 'END'),
                    ('P Step', 'OPPSTEP', 'W', 'STEP'),
                    ('Step Delay', 'OPPDELAY', 's', 'STEP:DELAY')))
        ss = """QGroupBox { min-width: 11em; max-width: 11em;
                            min-height: 10em; max-height: 10em; }
                QDoubleSpinBox { min-width: 5.5em; max-width: 5.5em; }
             """
        frame.setStyleSheet(ss)
        row_layout.addWidget(frame)

        ###################

        ###### ROW 2 ######

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_trigger = w;

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
        self._widget_registry['ShortONOFFEnable'] = w
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

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_measurements = w;

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
        pb = QPushButton('Reset Addl Cap && Test Log')
        pb.clicked.connect(self._on_click_reset_batt_test)
        layoutv.addWidget(pb)
        self._widget_registry['ClearAddCap'] = pb
        layoutv.addStretch()

        row_layout.addStretch()

        container = QWidget()
        container.setStyleSheet('background: black;')
        row_layout.addStretch()
        row_layout.addWidget(container)

        ss = """font-size: 30px; font-weight: bold; font-family: "Courier New";
                min-width: 6.5em; color: yellow;
             """
        ss2 = """font-size: 30px; font-weight: bold; font-family: "Courier New";
                min-width: 6.5em; color: red;
             """
        ss3 = """font-size: 15px; font-weight: bold; font-family: "Courier New";
                min-width: 6.5em; color: red;
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
        w = QLabel('00:00:00')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss2)
        layout.addWidget(w, 2, 0)
        self._widget_registry['MeasureBattTime'] = w
        w = QLabel('---  mAh')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss2)
        layout.addWidget(w, 2, 1)
        self._widget_registry['MeasureBattCap'] = w
        w = QLabel('Addl Cap:    --- mAh')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss3)
        layout.addWidget(w, 3, 0)
        self._widget_registry['MeasureBattAddCap'] = w
        w = QLabel('Total Cap:    --- mAh')
        w.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.setStyleSheet(ss3)
        layout.addWidget(w, 3, 1)
        self._widget_registry['MeasureBattTotalCap'] = w
        row_layout.addStretch()

    def _init_widgets_value_box(self, title, details):
        # Value for most modes
        frame = QGroupBox(title)
        widget_prefix = title.replace(' ', '')
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
            if unit is not None:
                input.setSuffix(' '+unit)
            input.editingFinished.connect(self._on_value_change)
            layouth.addWidget(input)
            label.sizePolicy().setRetainSizeWhenHidden(True)
            input.sizePolicy().setRetainSizeWhenHidden(True)
            layoutv.addLayout(layouth)
            self._widget_registry[f'{widget_prefix}_{mode}'] = input
            self._widget_registry[f'{widget_prefix}Label_{mode}'] = label
        layoutv.addStretch()
        return frame


    ############################################################################
    ### ACTION HANDLERS
    ############################################################################

    def _menu_do_view_parameters(self, state):
        if state:
            self._widget_row_parameters.show()
        else:
            self._widget_row_parameters.hide()

    def _menu_do_view_load_trigger(self, state):
        if state:
            self._widget_row_trigger.show()
        else:
            self._widget_row_trigger.hide()

    def _menu_do_view_measurements(self, state):
        if state:
            self._widget_row_measurements.show()
        else:
            self._widget_row_measurements.hide()

    def _on_click_overall_mode(self):
        if self._disable_callbacks:
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_overall_mode = rb.wid
        self._cur_dynamic_mode = None
        new_param_state = {}
        match self._cur_overall_mode:
            case 'Basic':
                if self._cur_const_mode is None:
                    self._cur_const_mode = self._param_state[':FUNCTION']
                    if self._cur_const_mode == 'Led':
                        # LED is weird in that the instrument treats it as a BASIC mode
                        # but there's no CV/CC/CP/CR choice
                        self._cur_const_mode = 'Voltage' # For lack of anything else to do
                    elif self._cur_const_mode in ('OCP', 'OPP'):
                        # We lose information going from OCP/OPP back to Basic because
                        # we don'tknow which basic mode we were in before!
                        self._cur_const_mode = 'Voltage'
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION'] = None
                new_param_state[':FUNCTION'] = self._cur_const_mode
            case 'Dynamic':
                if self._cur_const_mode is None:
                    self._cur_const_mode = self._param_state[':FUNCTION:TRANSIENT']
                param_info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
                mode_name = param_info['mode_name']
                val = self._param_state[f':{mode_name}:TRANSIENT:MODE']
                self._cur_dynamic_mode = val
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION:TRANSIENT'] = None
                new_param_state[':FUNCTION:TRANSIENT'] = self._cur_const_mode
            case 'LED':
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION'] = None
                new_param_state[':FUNCTION'] = 'Led'
                self._cur_const_mode = None
            case 'Battery':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in the Battery mode, but it
                # doesn't allow us to SWITCH TO the OCP mode!
                self._inst.write(':BATTERY:FUNC')
                self._param_state[':FUNCTION'] = 'Battery'
                self._cur_const_mode = self._param_state[':BATTERY:MODE']
            case 'OCPT':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in OCP mode, but it
                # doesn't allow us to SWITCH TO the OCP mode!
                self._inst.write(':OCP:FUNC')
                self._param_state[':FUNCTION'] = 'OCP'
                self._cur_const_mode = None
            case 'OPPT':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in OPP mode, but it
                # doesn't allow us to SWITCH TO the OCP mode!
                self._inst.write(':OPP:FUNC')
                self._param_state[':FUNCTION'] = 'OPP'
                self._cur_const_mode = None

        # Changing the mode turns off the load and short
        # We have to do this manually in order for the later mode change to take effect
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_params(new_param_state)
        self._update_widgets()

    def _on_click_dynamic_mode(self):
        if self._disable_callbacks:
            return
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
        new_param_state = {':FUNCTION:TRANSIENT': self._cur_const_mode,
                           f':{mode_name}:TRANSIENT:MODE': rb.wid}

        self._update_params(new_param_state)
        self._update_widgets()

    def _on_click_const_mode(self):
        if self._disable_callbacks:
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_const_mode = rb.wid
        if self._cur_overall_mode == 'Basic':
            new_param_state = {':FUNCTION': self._cur_const_mode}
        elif self._cur_overall_mode == 'Dynamic':
            new_param_state = {':FUNCTION:TRANSIENT': self._cur_const_mode}
            info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
            mode_name = info['mode_name']
            self._cur_dynamic_mode = self._param_state[f':{mode_name}:TRANSIENT:MODE']
        elif self._cur_overall_mode == 'Battery':
            new_param_state = {':BATTERY:MODE': self._cur_const_mode}

        # Changing the mode turns off the load and short
        # We have to do this manually in order for the later mode change to take effect
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_params(new_param_state)
        self._update_widgets()

    def _on_click_range(self):
        if self._disable_callbacks:
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        val = rb.wid
        trans = self._transient_string()
        if val.endswith('V'):
            new_param_state = {f':{mode_name}{trans}:VRANGE': val.strip('V')}
        else:
            new_param_state = {f':{mode_name}{trans}:IRANGE': val.strip('A')}
        self._update_params(new_param_state)
        self._update_widgets()

    def _on_value_change(self):
        if self._disable_callbacks:
            return
        input = self.sender()
        mode, scpi = input.wid
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        val = float(input.value())
        new_param_state = {f':{mode_name}:{scpi}': val}
        self._update_params(new_param_state)
        self._update_widgets()

    def _on_click_short_enable(self):
        if self._disable_callbacks:
            return
        self._update_short_onoff_button(None)
        cb = self.sender()
        if not cb.isChecked():
            self._update_short_onoff_button(None)
        else:
            self._update_short_state(0) # Also updates the button

    def _on_click_short_on_off(self):
        if self._disable_callbacks:
            return
        bt = self.sender()
        state = 1-self._param_state[':SHORT:STATE']
        self._update_short_state(state)

    def _on_click_load_on_off(self):
        if self._disable_callbacks:
            return
        bt = self.sender()
        state = 1-self._param_state[':INPUT:STATE']
        self._update_load_state(state)

    def _on_click_trigger_source(self):
        if self._disable_callbacks:
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        new_param_state = {':TRIGGER:SOURCE': rb.mode}
        self._update_params(new_param_state)
        self._update_trigger_buttons()

    def _on_click_trigger(self):
        if self._disable_callbacks:
            return
        self._inst.trg()

    def _on_click_enable_measurements(self):
        if self._disable_callbacks:
            return
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

    def _on_click_reset_batt_test(self):
        self._inst.write(':BATT:ADDCAP 0')
        self._reset_batt_log()

    def _update_load_onoff_button(self, state=None):
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
        if self._cur_overall_mode in ('Battery', 'OCPT', 'OPPT'):
            self._widget_registry['ShortONOFFEnable'].setEnabled(False)
            self._widget_registry['ShortONOFF'].setEnabled(False)
        elif self._widget_registry['ShortONOFFEnable'].isChecked():
            self._widget_registry['ShortONOFFEnable'].setEnabled(True)
            self._widget_registry['ShortONOFF'].setEnabled(True)
        else:
            self._widget_registry['ShortONOFFEnable'].setEnabled(True)
            self._widget_registry['ShortONOFF'].setEnabled(False)

    def _update_trigger_buttons(self):
        src = self._param_state[':TRIGGER:SOURCE']
        self._widget_registry['Trigger_Bus'].setChecked(src == 'Bus')
        self._widget_registry['Trigger_Man'].setChecked(src == 'Manual')
        self._widget_registry['Trigger_Ext'].setChecked(src == 'External')

        enabled = False
        if (self._cur_overall_mode == 'Dynamic' and
            self._cur_dynamic_mode != 'Continuous' and
            src == 'Bus' and
            self._param_state[':INPUT:STATE']):
            enabled = True
        self._widget_registry['Trigger'].setEnabled(enabled)


##########################################################################################
##########################################################################################
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

    def measure_battery_time(self):
        return float(self.query(':BATT:DISCHA:TIMER?'))

    def measure_battery_capacity(self):
        return float(self.query(':BATT:DISCHA:CAP?'))

    def measure_battery_add_capacity(self):
        return float(self.query(':BATT:ADDCAP?'))

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

# [:SOURce]:OCP:FUNC
# [:SOURce]:OCP:FUNC?
# [:SOURce]:OCP:IRANGe?
# [:SOURce]:OCP:VRANGe <value>
# [:SOURce]:OCP:VRANGe?
# [:SOURce]:OCP:STARt {< value: float,int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:STARt?
# [:SOURce]:OCP:STEP {< value: float?, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:STEP?
# [:SOURce]:OCP:STEP:DELay {< value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:STEP:DELay?
# [:SOURce]:OCP:END {< value > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:END?
# [:SOURce]:OCP:MIN {< value: float,int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:MIN?
# [:SOURce]:OCP:MAX {< value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:MAX?
# [:SOURce]:OCP:VOLTage <value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OCP:VOLTage?

# [:SOURce]:OPP:FUNC
# [:SOURce]:OPP:FUNC?
# [:SOURce]:OPP:IRANGe?
# [:SOURce]:OPP:VRANGe <value>
# [:SOURce]:OPP:VRANGe?
# [:SOURce]:OPP:STARt {< value: float,int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:STARt?
# [:SOURce]:OPP:STEP {< value: float?, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:STEP?
# [:SOURce]:OPP:STEP:DELay {< value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:STEP:DELay?
# [:SOURce]:OPP:END {< value > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:END?
# [:SOURce]:OPP:MIN {< value: float,int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:MIN?
# [:SOURce]:OPP:MAX {< value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:MAX?
# [:SOURce]:OPP:VOLTage <value: float, int > | MINimum | MAXimum | DEFault}
# [:SOURce]:OPP:VOLTage?


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
