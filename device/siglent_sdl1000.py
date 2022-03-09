################################################################################
# siglent_sdl1000.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains all code related to the Siglent SDL1000 series of programmable
# DC electronic loads:
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

################################################################################
# This module contains two basic sections. The GUI for the control widget is
# specified by the InstrumentSiglentSDL1000ConfigureWidget class. The internal
# instrument driver is specified by the InstrumentSiglentSDL1000 class.
#
# Some general notes:
#
# ** SIGLENT SCPI DOCUMENTATION
#
# There are errors and omissions in the "Siglent Programming Guide: SDL1000X
# Programmable DC Electronic Load" document (PG0801X-C01A dated 2019). In particular
# there are two SCPI commands that we need that are undocumented:
#
# - SYST:REMOTE:STATE locks the instrument keyboard and shows the remote control
#   icon.
# - :FUNCTION:MODE[?] which is described below
#
# Figuring out what mode the instrument is in and setting it to a new mode is
# a confusing mismash of operations. Here are the details.
#
# :FUNCTION:MODE? is an undocumented SCPI command that is ONLY useful for queries. You
#   cannot use it to set the mode! It returns one of:
#       BASIC, TRAN, BATTERY, OCP, OPP, LIST, PROGRAM
#   Note that LED is considered a BASIC mode.
#
# :FUNCTION <X> is used to set the "constant X" mode while in the BASIC mode. If the
#   instrument is not currently in the BASIC mode, this places it in the BASIC mode.
#   There is no way to go into the BASIC mode without also specifying the "constant"
#   mode. Examples:
#       :FUNCTION VOLTAGE
#       :FUNCTION CURRENT
#       :FUNCTION POWER
#       :FUNCTION RESISTANCE
#   LED mode is considered a BASIC mode, so to put the instrument in LED mode,
#   execute:
#       :FUNCTION LED
#   It can also be used to query the current "constant X" mode:
#       :FUNCTION?
#
# :FUNCTION:TRANSIENT <X> does the same thing as :FUNCTION but for the TRANSIENT
#   (Dynamic) mode. It can both query the current "constant X" mode and put the
#   instrument into the Dynamic mode.
#
# To place the instrument in other modes, you use specific commands:
#   :BATTERY:FUNC
#   :OCP:FUNC
#   :OPP:FUNC
#   :LIST:STATE:ON
#   :PROGRAM:STATE:ON
################################################################################


import json
import pprint
import re
import time

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

from .device import Device4882
from .config_widget_base import ConfigureWidgetBase


# Widget names referenced below are stored in the self._widget_registry dictionary.
# Widget descriptors can generally be anything permitted by a standard Python
# regular expression.

# This dictionary maps from the "overall" mode (shown in the left radio button group)
# to the set of widgets that should be shown or hidden.
#   !   means hide
#   ~   means set as not enabled (greyed out)
#       No prefix means show and enable
# Basically, the Dynamic modes (continuous, pulse, trigger) are only available in
# Dynamic mode, and the Constant X modes are only available in Basic, Dynamic,
# Battery (except CV), and List modes.
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

# This dictionary maps from the current overall mode (see above) and the current
# "Constant X" mode (if any, None otherwise) to a description of what to do
# in this combination.
#   'widgets'       The list of widgets to show/hide/grey out/enable.
#                   See above for the syntax.
#   'mode_name'     The string to place at the beginning of a SCPI command.
#   'params'        A list of parameters active in this mode. Each entry is
#                   constructed as follows:
#       0) The SCPI base command. The 'mode_name', if any, will be prepended to give,
#          e.g. ":VOLTAGE:IRANGE"
#       1) The type of the parameter. Options are '.Xf' for a float with a given
#          number of decimal places, 'd' for an integer, 'b' for a Boolean
#          (treated the same as 'd' for now), 's' for an arbitrary string,
#          and 'r' for a radio button.
#       2) A widget name telling which container widgets to enable (e.g.
#          the "*Label" boxes around the entry spinners).
#       3) A widget name telling which widget contains the actual value to read
#          or set. It is automatically enabled. For a 'r' radio button, this is
#          a regular expression describing a radio button group. All are set to
#          unchecked except for the appropriate selected one which is set to
#          checked.
#       4) For numerical widgets ('d' and 'f'), the minimum allowed value.
#       5) For numerical widgets ('d' and 'f'), the maximum allowed value.
#           For 4 and 5, the min/max can be a constant number or a special
#           character. 'C' means the limits of the CURRENT RANGE. 'V' means the
#           limits of the VOLTAGE RANGE. 'P' means the limits of power based
#           on the SDL model number (200W or 300W). It can also be 'W:<widget_name>'
#           which means to retrieve the value of that widget; this is useful for
#           min/max pairs.
# The "General" entry is a little special, since it doesn't pertain to a particular
# mode combination. It is used as an addon to all other modes.
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
            ('START',      '.3f', 'MainParametersLabel_OCPSTART', 'MainParameters_OCPSTART', 0, 'W:MainParameters_OCPEND'),
            ('END',        '.3f', 'MainParametersLabel_OCPEND', 'MainParameters_OCPEND', 'W:MainParameters_OCPSTART', 'C'),
            ('STEP',       '.3f', 'MainParametersLabel_OCPSTEP', 'MainParameters_OCPSTEP', 0, 'C'),
            ('STEP:DELAY', '.3f', 'MainParametersLabel_OCPDELAY', 'MainParameters_OCPDELAY', 0.001, 999),
            ('MIN',        '.3f', 'AuxParametersLabel_OCPMIN', 'AuxParameters_OCPMIN', 0, 'W:AuxParameters_OCPMAX'),
            ('MAX',        '.3f', 'AuxParametersLabel_OCPMAX', 'AuxParameters_OCPMAX', 'W:AuxParameters_OCPMIN', 'C'),
          )
        },
    ('OPPT', None):
        {'widgets': None,
         'mode_name': 'OPP',
         'params': (
            ('IRANGE',       'r', None, 'Range_Current_.*'),
            ('VRANGE',       'r', None, 'Range_Voltage_.*'),
            ('VOLTAGE',    '.3f', 'MainParametersLabel_OPPV', 'MainParameters_OPPV', 0, 'V'),
            ('START',      '.2f', 'MainParametersLabel_OPPSTART', 'MainParameters_OPPSTART', 0, 'W:MainParameters_OPPEND'),
            ('END',        '.2f', 'MainParametersLabel_OPPEND', 'MainParameters_OPPEND', 'W:MainParameters_OPPSTART', 'P'),
            ('STEP',       '.2f', 'MainParametersLabel_OPPSTEP', 'MainParameters_OPPSTEP', 0, 'P'),
            ('STEP:DELAY', '.3f', 'MainParametersLabel_OPPDELAY', 'MainParameters_OPPDELAY', 0.001, 999),
            ('MIN',        '.3f', 'AuxParametersLabel_OPPMIN', 'AuxParameters_OPPMIN', 0, 'W:AuxParameters_OPPMAX'),
            ('MAX',        '.3f', 'AuxParametersLabel_OPPMAX', 'AuxParameters_OPPMAX', 'W:AuxParameters_OPPMIN', 'P'),
          )
        },
}


# This class encapsulates the main SDL configuration widget.

class InstrumentSiglentSDL1000ConfigureWidget(ConfigureWidgetBase):
    def __init__(self, *args, **kwargs):
        # The current state of all SCPI parameters. String values are always stored
        # in upper case!
        self._param_state = {}

        self._cur_overall_mode = None # e.g. Basic, Dynamic, LED
        self._cur_const_mode = None   # e.g. Voltage, Current, Power, Resistance
        self._cur_dynamic_mode = None # e.g. Continuous, Pulse, Toggle

        # Used to enable or disable measurement of parameters to speed up
        # data acquisition.
        self._enable_measurement_v = True
        self._enable_measurement_c = True
        self._enable_measurement_p = True
        self._enable_measurement_r = True

        # Needed to prevent recursive calls when setting a widget's value invokes
        # the callback handler for it.
        self._disable_callbacks = False

        # The time the LOAD was turned on and off. Used for battery discharge logging.
        self._load_on_time = None
        self._load_off_time = None
        self._reset_batt_log()

        # We need to call this last because some things called by __init__ rely
        # on the above variables being initialized.
        super().__init__(*args, **kwargs)


    ######################
    ### Public methods ###
    ######################

    # This reads instrument -> _param_state
    def refresh(self):
        """Read all parameters from the instrument and set our internal state to match."""
        self._param_state = {} # Start with a blank slate
        for mode, info in _SDL_MODE_PARAMS.items():
            for param_spec in info['params']:
                param = self._scpi_cmd_from_param_info(info, param_spec)
                if param in self._param_state:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    continue
                val = self._inst.query(f'{param}?')
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
                self._param_state[param] = val
        # Set things like _cur_overall_mode and _cur_const_mode and update widgets
        self._update_state_from_param_state()

    # This writes _param_state -> instrument (opposite of refresh)
    def update_instrument(self):
        """Update the instrument with the current _param_state.

        This is tricker than it should be, because if you send a configuration
        command to the SDL for a mode it's not currently in, it crashes!"""
        set_params = set()
        for mode, info in _SDL_MODE_PARAMS.items():
            first_write = True
            for param_spec in info['params']:
                if not param_spec[2]:
                    continue # This captures the General True/False flag
                param = self._scpi_cmd_from_param_info(info, param_spec)
                if param in set_params:
                    # Sub-modes often ask for the same data, no need to retrieve it twice
                    continue
                set_params.add(param)
                if first_write and info['mode_name']:
                    first_write = False
                    # We have to put the instrument in the correct mode before setting
                    # the parameters. Not necessary for "General" (mode_name None).
                    self._put_inst_in_mode(mode[0], mode[1])
                val = self._param_state[param]
                self._update_one_param_on_inst(param, val)
        self._update_state_from_param_state()
        self._put_inst_in_mode(self._cur_overall_mode, self._cur_const_mode)

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
            # No need to update the instrument, since it changed the state for us
            self._update_load_state(input_state, update_inst=False)

        measurements = {}

        w = self._widget_registry['MeasureV']
        if self._enable_measurement_v:
            # Voltage is available regardless of the input state
            voltage = self._inst.measure_voltage()
            measurements['Voltage'] = voltage
            w.setText('%10.6f V' % voltage)
        else:
            w.setText('---   V')

        w = self._widget_registry['MeasureC']
        if self._enable_measurement_c:
            # Current is only available when the load is on
            if not input_state:
                w.setText('N/A   A')
            else:
                current = self._inst.measure_current()
                measurements['Current'] = current
                w.setText('%10.6f A' % current)
        else:
            w.setText('---   A')

        w = self._widget_registry['MeasureP']
        if self._enable_measurement_p:
            # Power is only available when the load is on
            if not input_state:
                w.setText('N/A   W')
            else:
                power = self._inst.measure_power()
                measurements['Power'] = power
                w.setText('%10.6f W' % power)
        else:
            w.setText('---   W')

        w = self._widget_registry['MeasureR']
        if self._enable_measurement_r:
            # Resistance is only available when the load is on
            if not input_state:
                w.setText('N/A   \u2126')
            else:
                resistance = self._inst.measure_resistance()
                measurements['Resistance'] = resistance
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
            # Battery measurements are available regardless of load state
            if self._batt_log_initial_voltage is None:
                self._batt_log_initial_voltage = voltage
            disch_time = self._inst.measure_battery_time()
            measurements['Discharge Time'] = disch_time
            m, s = divmod(disch_time, 60)
            h, m = divmod(m, 60)
            w = self._widget_registry['MeasureBattTime']
            w.setText('%02d:%02d:%02d' % (h, m, s))

            w = self._widget_registry['MeasureBattCap']
            disch_cap = self._inst.measure_battery_capacity()
            measurements['Capacity'] = disch_cap
            w.setText('%d mAh' % disch_cap)

            w = self._widget_registry['MeasureBattAddCap']
            add_cap = self._inst.measure_battery_add_capacity()
            measurements['Addl Capacity'] = add_cap
            w.setText('Addl Cap: %6d mAh' % add_cap)

            # When the LOAD is OFF, we have already updated the ADDCAP to include the
            # current test results, so we don't want to add it in a second time
            if input_state:
                val = disch_cap+add_cap
            else:
                val = add_cap
            measurements['Total Capacity'] = val
            w = self._widget_registry['MeasureBattTotalCap']
            w.setText('Total Cap: %6d mAh' % val)

        return measurements


    ############################################################################
    ### Setup Window Layout
    ############################################################################

    def _init_widgets(self):
        toplevel_widget = self._toplevel_widget()

        ### Add to Device menu

        action = QAction('Show &battery report...', self)
        action.triggered.connect(self._menu_do_device_batt_report)
        self._menubar_device.addAction(action)

        ### Add to View menu

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

        ### Set up configuration window widgets

        main_vert_layout = QVBoxLayout(toplevel_widget)
        main_vert_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ###### ROW 1 - Modes and Paramter Values ######

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_parameters = w;

        ### ROW 1, COLUMN 1 ###

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

        ### ROW 1, COLUMN 2 ###

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

        ### ROW 1, COLUMN 3 ###

        # V/I/R Range selections and Aux Parameters
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

        # Aux Parameters
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

        ### ROW 1, COLUMN 4 ###

        # Main Parameters
        frame = self._init_widgets_value_box('Main Parameters', (
                    ('Voltage',     'Voltage',     'V',      'LEVEL:IMMEDIATE'),
                    ('Current',     'Current',     'A',      'LEVEL:IMMEDIATE'),
                    ('Power',       'Power',       'W',      'LEVEL:IMMEDIATE'),
                    ('Resistance',  'Resistance',  '\u2126', 'LEVEL:IMMEDIATE'),
                    ('A Level',     'ALevelV',     'V',      'TRANSIENT:ALEVEL'),
                    ('B Level',     'BLevelV',     'V',      'TRANSIENT:BLEVEL'),
                    ('A Level',     'ALevelC',     'A',      'TRANSIENT:ALEVEL'),
                    ('B Level',     'BLevelC',     'A',      'TRANSIENT:BLEVEL'),
                    ('A Level',     'ALevelP',     'W',      'TRANSIENT:ALEVEL'),
                    ('B Level',     'BLevelP',     'W',      'TRANSIENT:BLEVEL'),
                    ('A Level',     'ALevelR',     '\u2126', 'TRANSIENT:ALEVEL'),
                    ('B Level',     'BLevelR',     '\u2126', 'TRANSIENT:BLEVEL'),
                    ('A Width',     'AWidth',      's',      'TRANSIENT:AWIDTH'),
                    ('B Width',     'BWidth',      's',      'TRANSIENT:BWIDTH'),
                    ('Width',       'Width',       's',      'TRANSIENT:BWIDTH'),
                    ('Vo',          'LEDV',        'V',      'VOLTAGE'),
                    ('Io',          'LEDC',        'A',      'CURRENT'),
                    ('Rco',         'LEDR',        None,     'RCONF'),
                    ('Current',     'BATTC',       'A',      'LEVEL'),
                    ('Power',       'BATTP',       'W',      'LEVEL'),
                    ('Resistance',  'BATTR',       '\u2126', 'LEVEL'),
                    ('*V Stop',      'BATTVSTOP',   'V',      'VOLTAGE'),
                    ('*Cap Stop',    'BATTCAPSTOP', 'mAh',    'CAP'),
                    ('*Time Stop',   'BATTTSTOP',   's',      'TIMER'),
                    ('Von',         'OCPV',        'V',      'VOLTAGE'),
                    ('I Start',     'OCPSTART',    'A',      'START'),
                    ('I End',       'OCPEND',      'A',      'END'),
                    ('I Step',      'OCPSTEP',     'A',      'STEP'),
                    ('Step Delay',  'OCPDELAY',    's',      'STEP:DELAY'),
                    ('Prot V',      'OPPV',        'V',      'VOLTAGE'),
                    ('P Start',     'OPPSTART',    'W',      'START'),
                    ('P End',       'OPPEND',      'W',      'END'),
                    ('P Step',      'OPPSTEP',     'W',      'STEP'),
                    ('Step Delay',  'OPPDELAY',    's',      'STEP:DELAY')))
        ss = """QGroupBox { min-width: 11em; max-width: 11em;
                            min-height: 10em; max-height: 10em; }
                QDoubleSpinBox { min-width: 5.5em; max-width: 5.5em; }
             """
        frame.setStyleSheet(ss)
        row_layout.addWidget(frame)

        ###################

        ###### ROW 2 - PROGRAM MODE ######

        ###### ROW 3 - LIST MODE ######

        ###### ROW 4 - SHORT/LOAD/TRIGGER ######

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_trigger = w;

        ###### ROW 4, COLUMN 1 - SHORT ######

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

        ###### ROW 4, COLUMN 2 - LOAD ######

        w = QPushButton('') # LOAD ON/OFF
        w.clicked.connect(self._on_click_load_on_off)
        row_layout.addWidget(w)
        self._widget_registry['LoadONOFF'] = w
        self._update_load_onoff_button(False) # Sets the style sheet

        row_layout.addStretch()

        ###### ROW 4, COLUMN 3 - TRIGGER ######

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

        ###### ROW 5 - MEASUREMENTS ######

        w = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(row_layout)
        main_vert_layout.addWidget(w)
        self._widget_row_measurements = w;

        # Enable measurements, reset battery log button
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

        # Main measurements widget
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

    # Our general philosophy is to create all of the possible input widgets for all
    # parameters and all units, and then hide the ones we don't need.
    # The details structure contains a list of:
    #   - The string to display as the input label
    #   - The name of the parameter as used in the _SDL_MODE_PARAMS dictionary
    #   - The unit to display in the input edit field
    #   - The SCPI parameter name, which gets added as an attribute on the widget
    def _init_widgets_value_box(self, title, details):
        # Value for most modes
        frame = QGroupBox(title)
        widget_prefix = title.replace(' ', '')
        layoutv = QVBoxLayout(frame)
        for (display, param_name, unit, scpi) in details:
            disabled_ok = False
            if display[0] == '*':
                # Special indicator that "0" means "Disabled"
                disabled_ok = True
                display = display[1:]
            layouth = QHBoxLayout()
            label = QLabel(display+':')
            layouth.addWidget(label)
            input = QDoubleSpinBox()
            input.wid = (param_name, scpi)
            if disabled_ok:
                input.setSpecialValueText('Disabled')
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
            self._widget_registry[f'{widget_prefix}_{param_name}'] = input
            self._widget_registry[f'{widget_prefix}Label_{param_name}'] = label
        layoutv.addStretch()
        return frame


    ############################################################################
    ### Action and Callback Handlers
    ############################################################################

    def _menu_do_about(self):
        """Show the About box."""
        msg = """Siglent SDL1000-series configuration widget.

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
        with open(fn, 'w') as fp:
            json.dump(self._param_state, fp, sort_keys=True, indent=4)

    def _menu_do_load_configuration(self):
        """Load the current configuration from a file."""
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
        self.update_instrument()

    def _menu_do_reset_device(self):
        """Reset the instrument and then reload the state."""
        # A reset takes around 6.75 seconds, so we wait up to 10s to be safe.
        self.setEnabled(False)
        self.repaint()
        self._inst.write('*RST', timeout=10000)
        self.refresh()
        self.setEnabled(True)

    def _menu_do_device_batt_report(self):
        """Produce the battery discharge report, if any, and display it in a dialog."""
        report = self._batt_log_report()
        if report is None:
            report = 'No current battery log.'
        print(report)
        self._printable_text_dialog('Battery Discharge Report', report)

    def _menu_do_view_parameters(self, state):
        """Toggle visibility of the parameters row."""
        if state:
            self._widget_row_parameters.show()
        else:
            self._widget_row_parameters.hide()

    def _menu_do_view_load_trigger(self, state):
        """Toggle visibility of the short/load/trigger row."""
        if state:
            self._widget_row_trigger.show()
        else:
            self._widget_row_trigger.hide()

    def _menu_do_view_measurements(self, state):
        """Toggle visibility of the measurements row."""
        if state:
            self._widget_row_measurements.show()
        else:
            self._widget_row_measurements.hide()

    def _on_click_overall_mode(self):
        """Handle clicking on an Overall Mode button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_overall_mode = rb.wid
        self._cur_dynamic_mode = None
        new_param_state = {}
        # Special handling for each button
        match self._cur_overall_mode:
            case 'Basic':
                self._cur_const_mode = self._param_state[':FUNCTION'].title()
                if self._cur_const_mode in ('Led', 'OCP', 'OPP'):
                    # LED is weird in that the instrument treats it as a BASIC mode
                    # but there's no CV/CC/CP/CR choice.
                    # We lose information going from OCP/OPP back to Basic because
                    # we don't know which basic mode we were in before!
                    self._cur_const_mode = 'Voltage' # For lack of anything else to do
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION'] = None
                new_param_state[':FUNCTION'] = self._cur_const_mode.upper()
                self._param_state[':FUNCTION:MODE'] = 'BASIC'
            case 'Dynamic':
                self._cur_const_mode = (
                        self._param_state[':FUNCTION:TRANSIENT'].title())
                # Dynamic also has sub-modes - Continuous, Pulse, Toggle
                param_info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
                mode_name = param_info['mode_name']
                self._cur_dynamic_mode = (
                            self._param_state[f':{mode_name}:TRANSIENT:MODE'].title())
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION:TRANSIENT'] = None
                new_param_state[':FUNCTION:TRANSIENT'] = self._cur_const_mode.upper()
                self._param_state[':FUNCTION:MODE'] = 'TRAN'
            case 'LED':
                # Force update since this does more than set a parameter - it switches
                # modes
                self._param_state[':FUNCTION'] = None
                new_param_state[':FUNCTION'] = 'LED' # LED is consider a BASIC mode
                self._param_state[':FUNCTION:MODE'] = 'BASIC'
                self._cur_const_mode = None
            case 'Battery':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in the Battery mode, but it
                # doesn't allow us to SWITCH TO the Battery mode!
                self._inst.write(':BATTERY:FUNC')
                self._param_state[':FUNCTION:MODE'] = 'BATTERY'
                self._cur_const_mode = self._param_state[':BATTERY:MODE'].title()
            case 'OCPT':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in OCP mode, but it
                # doesn't allow us to SWITCH TO the OCP mode!
                self._inst.write(':OCP:FUNC')
                self._param_state[':FUNCTION:MODE'] = 'OCP'
                self._cur_const_mode = None
            case 'OPPT':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in OPP mode, but it
                # doesn't allow us to SWITCH TO the OPP mode!
                self._inst.write(':OPP:FUNC')
                self._param_state[':FUNCTION:MODE'] = 'OPP'
                self._cur_const_mode = None
            case 'List':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in List mode, but it
                # doesn't allow us to SWITCH TO the List mode!
                self._inst.write(':LIST:STATE:ON')
                self._param_state[':FUNCTION:MODE'] = 'LIST'
                self._cur_const_mode = self._param_state[':LIST:MODE'].title()
            case 'Program':
                # This is not a parameter with a state - it's just a command to switch
                # modes. The normal :FUNCTION tells us we're in List mode, but it
                # doesn't allow us to SWITCH TO the List mode!
                self._inst.write(':PROGRAM:STATE:ON')
                self._param_state[':FUNCTION:MODE'] = 'PROGRAM'
                self._cur_const_mode = None

        # Changing the mode turns off the load and short.
        # We have to do this manually in order for the later mode change to take effect.
        # If you try to change mode while the load is on, the SDL turns off the load,
        # but then ignores the mode change.
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    def _on_click_dynamic_mode(self):
        """Handle clicking on a Dynamic Mode button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        rb = self.sender()
        if not rb.isChecked():
            return

        self._cur_dynamic_mode = rb.wid

        # Changing the mode turns off the load and short.
        # We have to do this manually in order for the later mode change to take effect.
        # If you try to change mode while the load is on, the SDL turns off the load,
        # but then ignores the mode change.
        self._update_load_state(0)
        self._update_short_state(0)

        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        new_param_state = {':FUNCTION:TRANSIENT': self._cur_const_mode.upper(),
                           f':{mode_name}:TRANSIENT:MODE': rb.wid.upper()}

        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    def _on_click_const_mode(self):
        """Handle clicking on a Constant Mode button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        self._cur_const_mode = rb.wid
        match self._cur_overall_mode:
            case 'Basic':
                new_param_state = {':FUNCTION': self._cur_const_mode.upper()}
            case 'Dynamic':
                new_param_state = {':FUNCTION:TRANSIENT': self._cur_const_mode.upper()}
                info = self._cur_mode_param_info(null_dynamic_mode_ok=True)
                mode_name = info['mode_name']
                self._cur_dynamic_mode = (
                            self._param_state[f':{mode_name}:TRANSIENT:MODE'].title())
            case 'Battery':
                new_param_state = {':BATTERY:MODE': self._cur_const_mode}
            case 'List':
                new_param_state = {':LIST:MODE': self._cur_const_mode}
            # None of the other modes have a "constant mode"

        # Changing the mode turns off the load and short.
        # We have to do this manually in order for the later mode change to take effect.
        # If you try to change mode while the load is on, the SDL turns off the load,
        # but then ignores the mode change.
        self._update_load_state(0)
        self._update_short_state(0)

        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    def _on_click_range(self):
        """Handle clicking on a V or I range button."""
        if self._disable_callbacks: # Prevent recursive calls
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
        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    def _on_value_change(self):
        """Handle clicking on any input value edit box."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        input = self.sender()
        mode, scpi = input.wid
        info = self._cur_mode_param_info()
        mode_name = info['mode_name']
        val = input.value()
        if input.decimals() > 0:
            val = float(input.value())
        else:
            val = int(val)
        new_param_state = {f':{mode_name}:{scpi}': val}
        self._update_param_state_and_inst(new_param_state)
        self._update_widgets()

    def _on_click_short_enable(self):
        """Handle clicking on the short enable checkbox."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        cb = self.sender()
        if not cb.isChecked():
            self._update_short_onoff_button(None)
        else:
            self._update_short_state(0) # Also updates the button

    def _on_click_short_on_off(self):
        """Handle clicking on the SHORT button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        bt = self.sender()
        state = 1-self._param_state[':SHORT:STATE']
        self._update_short_state(state) # Also updates the button

    def _update_short_onoff_button(self, state=None):
        """Update the style of the SHORT button based on current or given state."""
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
            # There is no SHORT capability in these modes
            self._widget_registry['ShortONOFFEnable'].setEnabled(False)
            self._widget_registry['ShortONOFF'].setEnabled(False)
        elif self._widget_registry['ShortONOFFEnable'].isChecked():
            self._widget_registry['ShortONOFFEnable'].setEnabled(True)
            self._widget_registry['ShortONOFF'].setEnabled(True)
        else:
            self._widget_registry['ShortONOFFEnable'].setEnabled(True)
            self._widget_registry['ShortONOFF'].setEnabled(False)

    def _on_click_load_on_off(self):
        """Handle clicking on the LOAD button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        bt = self.sender()
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

    def _on_click_trigger_source(self):
        """Handle clicking on a trigger source button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        rb = self.sender()
        if not rb.isChecked():
            return
        new_param_state = {':TRIGGER:SOURCE': rb.mode.upper()}
        self._update_param_state_and_inst(new_param_state)
        self._update_trigger_buttons()

    def _update_trigger_buttons(self):
        """Update the trigger button based on the current state."""
        src = self._param_state[':TRIGGER:SOURCE']
        self._widget_registry['Trigger_Bus'].setChecked(src == 'BUS')
        self._widget_registry['Trigger_Man'].setChecked(src == 'MANUAL')
        self._widget_registry['Trigger_Ext'].setChecked(src == 'EXTERNAL')

        enabled = False
        if (src == 'Bus' and
            self._param_state[':INPUT:STATE'] and
            (self._cur_overall_mode == 'Dynamic' and
             self._cur_dynamic_mode != 'Continuous') or
            self._cur_overall_mode in ('List', 'Program')):
            enabled = True
        self._widget_registry['Trigger'].setEnabled(enabled)

    def _on_click_trigger(self):
        """Handle clicking on the main trigger button."""
        if self._disable_callbacks: # Prevent recursive calls
            return
        self._inst.trg()

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
            case 'R':
                self._enable_measurement_r = cb.isChecked()

    def _on_click_reset_batt_test(self):
        """Handle clicking on the reset battery log button."""
        self._inst.write(':BATT:ADDCAP 0')
        self._reset_batt_log()


    ################################
    ### Internal helper routines ###
    ################################

    def _transient_string(self):
        """Return the SCPI substring corresponding to the Dynamic mode, if applicable."""
        if self._cur_overall_mode == 'Dynamic':
            return ':TRANSIENT'
        return ''

    def _scpi_cmd_from_param_info(self, param_info, param_spec):
        """Create a SCPI command from a param_info structure."""
        mode_name = param_info['mode_name']
        if mode_name is None: # General parameters
            mode_name = ''
        else:
            mode_name = f':{mode_name}'
        return f'{mode_name}:{param_spec[0]}'

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
            case 'BATTERY':
                self._inst.write(':FUNCTION BATTERY')
                self._inst.write(f':BATTERY:MODE {const_mode}')
            case _:
                self._inst.write(f':FUNCTION {overall_mode}')

    def _update_state_from_param_state(self):
        """Update all internal state and widgets based on the current _param_state."""
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
        assert mode in ('Basic', 'LED', 'Battery', 'OCPT', 'OPPT', 'Dynamic',
                        'Program', 'List')
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

        # Now update all the widgets and their values with the new info
        # This is a bit of a hack - first do all the widgets ignoring the min/max
        # value limits, which allows us to actually initialize all the values. Then
        # go back and do the same thing again, this time setting the min/max values.
        # It's not very efficient, but it doesn't matter.
        self._update_widgets(minmax_ok=False)
        self._update_widgets(minmax_ok=True)

    def _update_load_state(self, state, update_inst=True):
        """Update the load on/off internal state, possibly updating the instrument."""
        old_state = self._param_state[':INPUT:STATE']
        new_param_state = {':INPUT:STATE': state}

        if state != old_state:
            # When turning on/off the load, record the details for the battery log
            if state:
                self._load_on_time = time.time()
                self._batt_log_initial_voltage = None
            else:
                self._load_off_time = time.time()

            if not state and self._cur_overall_mode == 'Battery':
                # For some reason when using Battery mode remotely, when the test is
                # complete (or aborted), the ADDCAP field is not automatically updated
                # like it is when you run a test from the front panel. So we do the
                # computation and update it here.
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

        if update_inst:
            self._update_param_state_and_inst(new_param_state)
        self._update_load_onoff_button(state)
        self._update_trigger_buttons()

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
                                max_val = self._param_state[f':{mode_name}{trans}:IRANGE']
                                max_val = float(max_val)
                            case 'V': # Based on voltage range selection (36V, 150V)
                                max_val = self._param_state[f':{mode_name}{trans}:VRANGE']
                                max_val = float(max_val)
                            case 'P': # SDL1020 is 200W, SDL1030 is 300W
                                if self._inst._high_power:
                                    max_val = 300
                                else:
                                    max_val = 200
                            case 'W':
                                if minmax_ok:
                                    # This is needed because when we're first loading up
                                    # the widgets from a cold start, the paired widget
                                    # may not have a good max value yet
                                    max_val = self._widget_registry[max_val[2:]].value()
                                else:
                                    max_val = 1000000000
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
                    dec = int(param_full_type[1:-1])
                    dec10 = 10 ** dec
                    widget.setDecimals(dec)
                    widget.setValue(val)
                    # It's possible that setting the minimum or maximum caused the value
                    # to change, which means we need to update our state.
                    # Note floating point comparison isn't precise so we only look to
                    # the precision of the number of decimals.
                    if int(val*dec10+.5) != int(widget.value()*dec10+.5):
                        new_param_state[f':{mode_name}:{scpi_cmd}'] = float(widget.value())
                case 'r': # Radio button
                    # In this case only the widget_main is an RE
                    for trial_widget in self._widget_registry:
                        if re.fullmatch(widget_main, trial_widget):
                            checked = trial_widget.upper().endswith('_'+str(val).upper())
                            self._widget_registry[trial_widget].setChecked(checked)
                case _:
                    assert False, f'Unknown param type {param_type}'

        self._update_param_state_and_inst(new_param_state)

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

    def _update_param_state_and_inst(self, new_param_state):
        # print('Old')
        # print(pprint.pformat(self._param_state))
        # print()
        # print('New')
        # print(pprint.pformat(new_param_state))
        # print()
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
            if self._batt_log_initial_voltages[0] is None:
                ret += 'Initial voltage: Not measured\n'
            else:
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
                if self._batt_log_initial_voltages[i] is None:
                    ret += 'Initial voltage: Not measured\n'
                else:
                    ret += 'Initial voltage: %.3f\n'%self._batt_log_initial_voltages[i]
                ret += 'Capacity: %.3fAh\n' % (self._batt_log_caps[i]/1000)
        return ret


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
