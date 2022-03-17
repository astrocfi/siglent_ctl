################################################################################
# plot_window.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains the plot window that displays a graph of X vs Y values.
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

import sys

from PyQt6.QtWidgets import (QWidget,
                             QApplication,
                             QComboBox,
                             QMenuBar, QMenu, QStatusBar,
                             QDialog,
                             QDialogButtonBox,
                             QLabel,
                             QLineEdit,
                             QMessageBox,
                             QPushButton,
                             QRadioButton,
                             QAbstractSpinBox,
                             QDoubleSpinBox,
                             QSpinBox,
                             QButtonGroup,
                             QLayout,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QVBoxLayout,
                             QPlainTextEdit)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import *

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyvisa

import device


_TIME_DURATIONS = (('1 min', 60),
                   ('5 min', 60*5),
                   ('15 min', 60*15),
                   ('30 min', 60*30),
                   ('1 hour', 60*60),
                   ('6 hours', 60*60*6),
                   ('12 hours', 60*60*12),
                   ('1 day', 60*60*24))

class PlotXYWindow(QWidget):
    """The main window of the entire application."""
    def __init__(self, main_window):
        super().__init__()
        self._main_window = main_window
        self.setWindowTitle(f'XY Plot')

        self._max_plot_items = 4
        self._plot_items = []
        self._plot_y_axis_items = []
        self._plot_x_axis_item = None
        self._plot_viewboxes = []
        self._plot_colors = ['FF0000', 'FFFF00', '00FF00', '00FFFF', '3030FF',
                             'FF00FF', 'FF8000', '80FF00']
        self._plot_sources = ['Voltage', 'Current', 'Power', 'Resistance']
        self._plot_x_source_prev = None
        self._plot_x_source = 'Elapsed Time'
        self._plot_duration = 60 # Default to "1 min"

        ### Layout the widgets

        layoutv = QVBoxLayout()
        layoutv.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layoutv)
        layoutv.setSpacing(0)
        # layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ### Create the menu bar

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_help = self._menubar.addMenu('&Help')
        action = QAction('&About', self)
        # action.triggered.connect(self._menu_do_about)
        self._menubar_help.addAction(action)

        layoutv.addWidget(self._menubar)

        ### The plot

        # This complicated way to get a multi-axis plot is taken from here:
        # https://stackoverflow.com/questions/29473757/
        #   pyqtgraph-multiple-y-axis-on-left-side
        # At some point this pull request will be approved, and all this won't be
        # necessary:
        #   https://github.com/pyqtgraph/pyqtgraph/pull/1359
        pw = pg.GraphicsView()
        # pw.setStyleSheet('padding: 10px;')
        gl = pg.GraphicsLayout()
        pw.setCentralWidget(gl)
        layoutv.addWidget(pw)

        pi = pg.PlotItem()
        self._master_plot_item = pi
        v1 = pi.vb
        v1.sigResized.connect(self._on_update_views)
        gl.addItem(pi, row=2, col=self._max_plot_items, rowspan=1, colspan=1)

        self._plot_viewboxes.append(v1)
        self._plot_y_axis_items.append(pi.getAxis('left'))
        for i in range(1, self._max_plot_items):
            axis_item = pg.AxisItem('left')
            # axis_item.hide()
            self._plot_y_axis_items.append(axis_item)
            gl.addItem(axis_item, row=2, col=self._max_plot_items-i,
                       rowspan=1, colspan=1)
            viewbox = pg.ViewBox()
            viewbox.setXLink(self._plot_viewboxes[-1])
            self._plot_viewboxes.append(viewbox)
            gl.scene().addItem(viewbox)
            axis_item.linkToView(viewbox)
            viewbox.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)

        for i in range(self._max_plot_items):
            pdi = pg.PlotDataItem([], [], pen=self._plot_colors[i])
            self._plot_viewboxes[i].addItem(pdi)
            self._plot_items.append(pdi)
            self._plot_sources.append(None)

        self._on_update_views()
        self._update_axes()

        ### The X axis and time duration controls

        layouth = QHBoxLayout()
        layouth.setContentsMargins(10, 10, 10, 10)
        layoutv.addLayout(layouth)
        layouth.addStretch()

        # X axis selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('X Axis:')
        label.setStyleSheet('margin-right: 5px;')
        layouth2.addWidget(label)
        combo = QComboBox()
        combo.activated.connect(self._on_x_axis_source)
        self._widget_x_axis_combo = combo
        layouth2.addWidget(self._widget_x_axis_combo)

        layouth.addStretch()

        # Time duration selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('View Last:')
        label.setStyleSheet('margin-right: 5px;')
        layouth2.addWidget(label)
        combo = QComboBox()
        combo.activated.connect(self._on_x_axis_duration)
        layouth2.addWidget(combo)
        for duration, secs in _TIME_DURATIONS:
            combo.addItem(duration, userData=secs)

        layouth.addStretch()

        self._update_widgets()

    def _on_x_axis_source(self, sel):
        """Handle selection of a new X axis source."""
        combo = self.sender()
        self._plot_x_source_prev = self._plot_x_source
        self._plot_x_source = combo.itemData(sel)
        self._update_axes()
        self.update()

    def _on_x_axis_duration(self, sel):
        """Handle selection of a new X axis duration."""
        combo = self.sender()
        self._plot_duration = combo.itemData(sel)
        self._update_axes()
        self.update()

    def _update_widgets(self):
        """Update the control widgets based on currently available measurements."""
        # X axis selections
        self._widget_x_axis_combo.clear()
        self._widget_x_axis_combo.addItem('Elapsed Time', userData='Elapsed Time')
        self._widget_x_axis_combo.addItem('Absolute Time', userData='Absolute Time')
        for key, name in self._main_window._measurement_names.items():
            self._widget_x_axis_combo.addItem(name, userData=key)

    def _on_update_views(self):
        """Resize the plot."""
        for viewbox in self._plot_viewboxes[1:]:
            viewbox.setGeometry(self._plot_viewboxes[0].sceneBoundingRect())

    def update(self):
        """Update the plot using the current measurements."""
        start_time = self._main_window._measurement_start_time
        stop_time = max(self._main_window._measurement_times[x][-1]
                        for x in self._main_window._measurement_times.keys())

        # Update X axis range
        x_min = start_time
        x_max = stop_time
        x_scale = 1
        x_unit = 'sec'
        if x_max - x_min < self._plot_duration:
            x_max = x_min + self._plot_duration
        else:
            x_min = x_max - self._plot_duration
        match self._plot_x_source:
            case 'Elapsed Time':
                x_min -= start_time
                x_max -= start_time
                if 60 < self._plot_duration <= 60*60:
                    x_unit = 'min'
                    x_scale = 60
                elif 60*60 < self._plot_duration:
                    x_unit = 'hour'
                    x_scale = 60*60
                self._plot_x_axis_item.setLabel(f'Elapsed Time ({x_unit})')
                x_min /= x_scale
                x_max /= x_scale
            case 'Absolute Time':
                # This will autoscale nicely
                pass
            case _:
                x_scale = None
        if x_scale is not None:
            self._plot_viewboxes[0].setRange(xRange=(x_min, x_max))

        for plot_num in range(self._max_plot_items):
            source = self._plot_sources[plot_num]
            if source is None:
                continue
            plot_key = ('SDL63', source)
            plot_item = self._plot_items[plot_num]
            scatter = False
            mask = None
            match self._plot_x_source:
                case 'Elapsed Time':
                    x_vals = (np.array(self._main_window._measurement_times[plot_key])-
                              start_time) / x_scale
                case 'Absolute Time':
                    x_vals = np.array(self._main_window._measurement_times[plot_key])
                case _:
                    times = np.array(self._main_window._measurement_times[plot_key])
                    mask = (x_min <= times) & (times <= x_max)
                    x_vals = np.array(
                        self._main_window._measurements[self._plot_x_source])
                    x_vals = x_vals[mask]
                    scatter = True
            y_vals = np.array(self._main_window._measurements[plot_key])
            if mask is not None:
                y_vals = y_vals[mask]
            if scatter:
                pen_color = None
                symbol_color = self._plot_colors[plot_num]
                symbol = 'o'
            else:
                pen_color = self._plot_colors[plot_num]
                symbol_color = None
                symbol = None
            if not np.all(np.isnan(x_vals)) and not np.all(np.isnan(y_vals)):
                plot_item.setData(x_vals, y_vals, connect='finite',
                                  pen=pen_color, symbol=symbol,
                                  symbolPen=None, symbolBrush=symbol_color)
            else:
                plot_item.setData([], [])

    def _update_axes(self):
        """Update the plot axes."""
        if (self._plot_x_source == 'Absolute Time' and
            self._plot_x_source != self._plot_x_source_prev):
            # Not Absolute -> Absolute
            self._plot_x_axis_item = pg.DateAxisItem(orientation='bottom')
            self._master_plot_item.setAxisItems({'bottom': self._plot_x_axis_item})
        elif ((self._plot_x_source != 'Absolute Time' and
              self._plot_x_source_prev == 'Absolute Time') or
              self._plot_x_axis_item is None):
            # Absolute -> Not Absolute
            self._plot_x_axis_item = pg.AxisItem(orientation='bottom')
            self._plot_viewboxes[0].enableAutoRange()
            self._master_plot_item.setAxisItems({'bottom': self._plot_x_axis_item})
        self._plot_viewboxes[0].enableAutoRange()
        if self._plot_x_source in ('Elapsed Time', 'Absolute Time'):
            self._master_plot_item.setLabel(axis='bottom', text=self._plot_x_source)
        else:
            m_name = self._main_window._measurement_names[self._plot_x_source]
            m_unit = self._main_window._measurement_units[self._plot_x_source]
            label = f'{m_name} ({m_unit})'
            self._master_plot_item.setLabel(axis='bottom', text=label)
        for plot_num in range(self._max_plot_items):
            source = self._plot_sources[plot_num]
            axis_item = self._plot_y_axis_items[plot_num]
            if source is None:
                axis_item.hide()
                continue
            axis_item.show()
            plot_key = ('SDL63', source)
            plot_item = self._plot_items[plot_num]
            color = self._plot_colors[plot_num]
            m_name = self._main_window._measurement_names[plot_key]
            m_unit = self._main_window._measurement_units[plot_key]
            label = f'{m_name} ({m_unit})'
            axis_item.setLabel(label)
            axis_item.setPen(self._plot_colors[plot_num])
