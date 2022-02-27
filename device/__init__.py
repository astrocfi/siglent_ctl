from .device import Device4882
from .siglent_sdl1000 import InstrumentSiglentSDL1000

_DEVICE_MAPPING = {
    ('Siglent Technologies', 'SDL1020X'): InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1020X-E'): InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1030X'): InstrumentSiglentSDL1000,
    ('Siglent Technologies', 'SDL1030X-E'): InstrumentSiglentSDL1000,
}

def create_device(rm, resource_name):
    dev = Device4882(rm, resource_name)
    dev.connect()
    idn = dev.idn().split(',')
    manufacturer = idn[0]
    model = idn[1]
    cls = _DEVICE_MAPPING.get((manufacturer, model), None)
    if cls is None:
        print(f'Unknown device {manufacturer} {model}')
        return None
    new_dev = cls(rm, resource_name)
    new_dev.connect(resource=dev._resource)
    print(f'Found a {manufacturer} {model}')
    return new_dev
