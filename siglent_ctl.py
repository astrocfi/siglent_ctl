import sys
import time

import matplotlib.pyplot as plt
import pandas as pd
import pyqtgraph as pg
import pyvisa

from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QGridLayout
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import pyqtSlot, QTimer

from data_stream import DataStream
# from device.siglent_sdl import InstrumentSiglentSDL
import device

def update():
    config_widget.refresh()
    # stream_v.record_value(inst.measure_voltage())
    # stream_i.record_value(inst.measure_current())
    # # stream_p.record_value(inst.measure_power())
    # # stream_r.record_value(inst.measure_resistance())
    # pdi_v.setData(stream_v.values)
    # pdi_i.setData(stream_i.values)
    # pw.setXRange(0, max(100, len(stream_v.values)))
    # # pdi_p.setData(stream_p.values)
    # # pdi_r.setData(stream_r.values)

app = QApplication(sys.argv)

rm = pyvisa.ResourceManager()
# inst = InstrumentSiglentSDL(rm, 'TCPIP::192.168.0.63')
inst = device.create_device(rm, 'TCPIP::192.168.0.63')
inst.set_debug(True)

inst.connect()

config_widget = inst.configure_widget()


# stream_v = DataStream('V')
# stream_i = DataStream('I')
# stream_p = DataStream('P')
# stream_r = DataStream('R')

config_widget.show()

# widget = QWidget()
# layout = QGridLayout()
# widget.setLayout(layout)
#
# pw = pg.plot(title='SDL Measurement')
# layout.addWidget(pw, 0, 0)
#
# pdi_v = pw.plot([], pen=0)
# pdi_i = pw.plot([], pen=1)
# pdi_p = pw.plot([], pen=2)
# pdi_r = pw.plot([], pen=3)

# widget.setWindowTitle('Measurement Example')
# widget.show()
#
timer = QTimer(app)
# timer.timeout.connect(update)
timer.start(2000)

app.exec()


df_v = stream_v.to_df()
df_i = stream_i.to_df()
df_p = stream_p.to_df()
df_r = stream_r.to_df()

df = df_v.join((df_i, df_p, df_r))

print(df)

val_v = stream_v.values
val_i = stream_i.values
val_p = stream_p.values
val_r = stream_r.values

# textLabel = QLabel(widget)
# textLabel.setText("Hello World!")
# textLabel.move(110,85)

# widget.setGeometry(50,50,320,200)

inst.disconnect()
