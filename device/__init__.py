################################################################################
# device/__init__.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains the top-level interface to the instrument device driver module.
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

from .device import Device4882
from .siglent_sdl1000 import InstrumentSiglentSDL1000

_DEVICE_MAPPING = {
    ('Siglent Technologies', 'SDL1020X'):   InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1020X-E'): InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1030X'):   InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1030X-E'): InstrumentSiglentSDL1000,
}

def create_device(rm, resource_name):
    dev = Device4882(rm, resource_name)
    dev.connect()
    idn = dev.idn()
    manufacturer, model, *_ = idn.split(',')
    cls = _DEVICE_MAPPING.get((manufacturer, model), None)
    if cls is None:
        print(f'Unknown device {idn}')
        return None
    new_dev = cls(rm, resource_name)
    new_dev.connect(resource=dev._resource)
    print(f'Found a {manufacturer} {model}')
    return new_dev
