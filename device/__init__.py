from .device import Device4882
from .siglent_sdl import InstrumentSiglentSDL

_DEVICE_MAPPING = {
    ('Siglent Technologies', 'SDL1020X'): InstrumentSiglentSDL,
    ('Siglent Technologies', 'SDL1020X-E'): InstrumentSiglentSDL,
    ('Siglent Technologies', 'SDL1030X'): InstrumentSiglentSDL,
    ('Siglent Technologies', 'SDL1030X-E'): InstrumentSiglentSDL,
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
