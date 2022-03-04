################################################################################
# device/device.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains the parent class for all devices (the Device class) and the all
# devices that support IEEE-488.2 (the Device4882 class).
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

import pyvisa

class NotConnectedError(Exception): pass
class ContactLostError(Exception): pass

class Device(object):
    """Class representing any generic device accessible through VISA."""
    def __init__(self, resource_manager, resource_name):
        self._resource_manager = resource_manager
        self._resource_name = resource_name
        self._long_name = resource_name
        self._name = resource_name
        self._resource = None
        self._connected = False
        self._manufacturer = None
        self._model = None
        self._serial_number = None
        self._firmware_version = None
        self._debug = False

    @property
    def manufacturer(self):
        return self._manufacturer

    @property
    def model(self):
        return self._model

    @property
    def serial_number(self):
        return self._serial_number

    @property
    def firmware_version(self):
        return self._firmware_version
        
    def set_debug(self, val):
        self._debug = val

    def connect(self, resource=None):
        """Open the connection to the device."""
        if self._connected:
            return
        if resource is not None:
            self._resource = resource
        else:
            self._resource = self._resource_manager.open_resource(self._resource_name)
            self._resource.read_termination = '\n'
            self._resource.write_termination = '\n'
        self._connected = True
        if self._debug:
            print(f'Connected to {self._resource_name}')

    ### Direct access to pyvisa functions

    def disconnect(self):
        """Close the connection to the device."""
        if not self._connected:
            raise NotConnectedError
        try:
            self._resource.close()
        except pyvisa.errors.VisaIOError:
            pass
        self._connected = False
        if self._debug:
            print(f'Disconnected from {self._resource_name}')

    def query(self, s):
        """VISA query, write then read."""
        if not self._connected:
            raise NotConnectedError
        try:
            ret = self._resource.query(s).strip(' \t\r\n')
        except pyvisa.errors.VisaIOError:
            self.disconnect()
            raise ContactLostError
        if self._debug:
            print(f'query "{s}" returned "{ret}"')
        return ret

    def read(self):
        """VISA read, strips termination characters."""
        if not self._connected:
            raise NotConnectedError
        try:
            ret = self._resource.read().strip(' \t\r\n')
        except pyvisa.errors.VisaIOError:
            self.disconnect()
            raise ContactLostError
        if self._debug:
            print(f'read "{s}" returned "{ret}"')
        return ret

    def read_raw(self):
        """VISA read_raw."""
        if not self._connected:
            raise NotConnectedError
        try:
            ret = self._resource.read_raw()
        except pyvisa.errors.VisaIOError:
            self.disconnect()
            raise ContactLostError
        if self._debug:
            print(f'read_raw "{s}" returned "{ret}"')
        return ret

    def write(self, s):
        """VISA write, appending termination characters."""
        if not self._connected:
            raise NotConnectedError
        if self._debug:
            print(f'write "{s}"')
        try:
            self._resource.write(s)
        except pyvisa.errors.VisaIOError:
            self.disconnect()
            raise ContactLostError

    def write_raw(self, s):
        """VISA write, no termination characters."""
        if not self._connected:
            raise NotConnectedError
        if self._debug:
            print(f'write_raw "{s}"')
        try:
            self._resource.write(s)
        except pyvisa.errors.VisaIOError:
            self.disconnect()
            raise ContactLostError

    ### Internal support routines

    def _read_write(self, query, write, validator=None, value=None):
        if value is None:
            return self._resource.query(query)
        if validator is not None:
            validator(value)
        self._resource.write(f'{write} {value}')
        return None

    def _validator_1(self, value):
        if value < 0 or value > 1:
            raise ValueError

    def _validator_8(self, value):
        if not (0 <= value <= 255): # Should this be 128? Or -128?
            raise ValueError

    def _validator_16(self, value):
        if not (0 <= value <= 65535):
            raise ValueError


class Device4882(Device):
    """Class representing any device that supports IEEE 488.2 commands."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def idn(self):
        """Read instrument identification."""
        return self.query('*IDN?')

    def rst(self):
        """Return to the instrument's default state."""
        self.write('*RST')
        self.cls()

    def cls(self):
        """Clear all event registers and the error list."""
        self.write('*CLS')

    def ese(self, reg_value=None):
        """Read or write the standard event status enable register."""
        return self._read_write('*ESE?', '*ESE', self._validator_8, reg_value)

    def esr(self):
        """Read and clear the standard event status enable register."""
        return self.query('*ESR?')

    def send_opc(self):
        """"Set bit 0 in ESR when all ops have finished."""
        self.write('*OPC')

    def get_opc(self):
        """"Query if current operation finished."""
        return self.query('*OPC?')

    def sre(self, reg_value=None):
        """Read or write the status byte enable register."""
        return self._read_write('*SRE?', '*SRE', self._validator_8, reg_value)

    def stb(self):
        """Reads the status byte event register."""
        return self.query('*STB?')

    def tst(self):
        """Perform self-tests."""
        return self.query('*TST')

    def wait(self):
        """Wait until all previous commands are executed."""
        self.write('*WAI')

    def trg(self):
        """Send a trigger command."""
        self.write('*TRG')

    # def rcl(self, preset_value=None):
    #     query = '*RCL?'
    #     write = '*RCL'
    #     return self.read_write(
    #         query, write, self._validate.preset,
    #         preset_value)
    #
    # # Saves the present setup (1..9)
    # def sav(self, preset_value=None):
    #     query = '*SAV?'
    #     write = '*SAV'
    #     return self.read_write(
    #         query, write, self._validate.preset,
    #         preset_value)
