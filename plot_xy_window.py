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
                             QColorDialog,
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
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtCore import *

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyvisa

import device


_TIME_DURATIONS = (('15 seconds', 15),
                   ('1 min', 60),
                   ('5 min', 60*5),
                   ('15 min', 60*15),
                   ('30 min', 60*30),
                   ('1 hour', 60*60),
                   ('3 hours', 60*60*3),
                   ('6 hours', 60*60*6),
                   ('12 hours', 60*60*12),
                   ('1 day', 60*60*24),
                   ('1 week', 60*60*24*7),
                   ('4 weeks', 60*60*24*7*4))

_LINE_STYLES = (('Solid', Qt.PenStyle.SolidLine),
                ('Dash', Qt.PenStyle.DashLine),
                ('Dot', Qt.PenStyle.DotLine),
                ('Dash-Dot', Qt.PenStyle.DashDotLine),
                ('Dash-Dot-Dot', Qt.PenStyle.DashDotDotLine))

_MARKER_SYMBOLS = (('Circle', 'o'),
                   ('Tri-down', 't'),
                   ('Tri-up', 't1'),
                   ('Tri-right', 't2'),
                   ('Tri-left', 't3'),
                   ('Square', 's'),
                   ('Pentagon', 'p'),
                   ('Hexagon', 'h'),
                   ('Star', 'star'),
                   ('Plus', '+'),
                   ('Diamond', 'd'),
                   ('Cross', 'x'))

class PlotXYWindow(QWidget):
    """The main window of the entire application."""
    def __init__(self, main_window):
        super().__init__()
        self._main_window = main_window
        self.setWindowTitle(f'XY Plot')

        self._max_plot_items = 8
        self._plot_background_color = '#000000'
        self._plot_items = []
        self._plot_y_axis_items = []
        self._plot_x_axis_item = None
        self._plot_x_axis_color = '#FFFFFF'
        self._plot_viewboxes = []
        self._plot_colors = ['#FF0000', '#FFFF00', '#00FF00', '#00FFFF', '#3030FF',
                             '#FF00FF', '#FF8000', '#C0C0C0']
        self._plot_widths = [1] * self._max_plot_items
        self._plot_line_styles = [Qt.PenStyle.SolidLine] * self._max_plot_items
        self._plot_marker_sizes = [3] * self._max_plot_items
        self._plot_marker_styles = ['o'] * self._max_plot_items
        self._plot_x_source_prev = None
        self._plot_x_source = 'Elapsed Time'
        self._plot_y_sources = [None] * self._max_plot_items
        self._plot_y_source_combos = []
        self._plot_duration = 60 # Default to "1 min"

        ### Layout the widgets

        layoutv = QVBoxLayout()
        layoutv.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layoutv)
        layoutv.setSpacing(0)
        # layoutv.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        ### Create the menu bar

        # self._menubar = QMenuBar()
        # self._menubar.setStyleSheet('margin: 0px; padding: 0px;')
        #
        # self._menubar_help = self._menubar.addMenu('&Help')
        # action = QAction('&About', self)
        # # action.triggered.connect(self._menu_do_about)
        # self._menubar_help.addAction(action)
        #
        # layoutv.addWidget(self._menubar)

        ### The plot

        # This complicated way to get a multi-axis plot is taken from here:
        # https://stackoverflow.com/questions/29473757/
        # At some point this pull request will be approved, and all this won't be
        # necessary:
        #   https://github.com/pyqtgraph/pyqtgraph/pull/1359
        pw = pg.GraphicsView()
        self._plot_graphics_view_widget = pw
        gl = pg.GraphicsLayout()
        pw.setCentralWidget(gl)
        layoutv.addWidget(pw)

        pi = pg.PlotItem()
        self._master_plot_item = pi
        v1 = pi.vb
        v1.setDefaultPadding(0)
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
            viewbox = pg.ViewBox(defaultPadding=0)
            viewbox.setXLink(self._plot_viewboxes[-1])
            self._plot_viewboxes.append(viewbox)
            gl.scene().addItem(viewbox)
            axis_item.linkToView(viewbox)
            viewbox.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)

        for i in range(self._max_plot_items):
            pdi = pg.PlotDataItem([], [])
            self._plot_viewboxes[i].addItem(pdi)
            self._plot_items.append(pdi)
            self._plot_y_sources.append(None)

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
        layouth2.addWidget(label)
        layouth2.addSpacing(5)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.activated.connect(self._on_x_axis_source)
        self._widget_x_axis_combo = combo
        layouth2.addWidget(self._widget_x_axis_combo)
        layouth2.addSpacing(5)
        button = QPushButton('')
        layouth2.addWidget(button)
        button.setStyleSheet(
            f'background-color: {self._plot_x_axis_color}; max-width: 1.5em;')
        button.source_num = 'X'
        button.clicked.connect(self._on_click_color_selector)

        layouth.addStretch()

        # Time duration selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('View Last:')
        layouth2.addWidget(label)
        layouth2.addSpacing(5)
        combo = QComboBox()
        combo.activated.connect(self._on_x_axis_duration)
        self._widget_duration = combo
        layouth2.addWidget(combo)
        for duration, secs in _TIME_DURATIONS:
            combo.addItem(duration, userData=secs)

        layouth.addStretch()

        # Background color selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('Background Color:')
        layouth2.addWidget(label)
        layouth2.addSpacing(5)
        button = QPushButton('')
        layouth2.addWidget(button)
        button.setStyleSheet(
            f'background-color: {self._plot_background_color}; max-width: 1.5em;')
        button.source_num = 'B'
        button.clicked.connect(self._on_click_color_selector)

        layouth.addStretch()

        button = QPushButton('Show All')
        layouth.addWidget(button)
        button.clicked.connect(self._on_click_all_measurements)
        button = QPushButton('Show None')
        layouth.addWidget(button)
        button.clicked.connect(self._on_click_no_measurements)

        layouth.addStretch()

        # Plot all params button

        ### The data selectors

        layoutg = QGridLayout()
        layoutg.setContentsMargins(11, 11, 11, 11)
        layoutg.setHorizontalSpacing(7)
        layoutg.setVerticalSpacing(0)
        layoutv.addLayout(layoutg)
        for source_num in range(self._max_plot_items):
            frame = QGroupBox(f'Plot #{source_num+1}')
            layoutf = QVBoxLayout(frame)
            row = source_num // 4
            column = source_num % 4
            layoutg.addWidget(frame, row, column)

            layouth = QHBoxLayout()
            layoutf.addLayout(layouth)
            button = QPushButton('')
            bgcolor = self._plot_colors[source_num]
            button.setStyleSheet(f'background-color: {bgcolor}; max-width: 1.5em;')
            button.source_num = source_num
            button.clicked.connect(self._on_click_color_selector)
            layouth.addWidget(button)
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.source_num = source_num
            self._plot_y_source_combos.append(combo)
            combo.activated.connect(self._on_y_source_selection)
            layouth.addWidget(combo)
            layouth.addStretch()

            layoutg2 = QGridLayout()
            layoutf.addLayout(layoutg2)
            layoutg2.addWidget(QLabel('Line:'), 0, 0)
            combo = QComboBox()
            combo.source_num = source_num
            layoutg2.addWidget(combo, 0, 1)
            for pix in range(1,9):
                combo.addItem(str(pix), userData=pix)
            combo.activated.connect(self._on_y_line_width_selection)
            combo = QComboBox()
            combo.source_num = source_num
            layoutg2.addWidget(combo, 0, 2)
            for num, (name, style) in enumerate(_LINE_STYLES):
                combo.addItem(name, userData=num)
            combo.activated.connect(self._on_y_line_style_selection)

            layoutg2.addWidget(QLabel('Scatter:'), 1, 0)
            combo = QComboBox()
            combo.source_num = source_num
            layoutg2.addWidget(combo, 1, 1)
            for pix in range(1,9):
                combo.addItem(str(pix), userData=pix)
            combo.activated.connect(self._on_y_marker_size_selection)
            combo = QComboBox()
            combo.source_num = source_num
            layoutg2.addWidget(combo, 1, 2)
            for num, (name, style) in enumerate(_MARKER_SYMBOLS):
                combo.addItem(name, userData=num)
            combo.activated.connect(self._on_y_marker_style_selection)

        self._update_widgets()

    def _on_x_axis_source(self, sel):
        """Handle selection of a new X axis source."""
        combo = self.sender()
        self._plot_x_source_prev = self._plot_x_source
        self._plot_x_source = combo.itemData(sel)
        self._update_axes()

    def _on_x_axis_duration(self, sel):
        """Handle selection of a new X axis duration."""
        combo = self.sender()
        self._plot_duration = combo.itemData(sel)
        self._update_axes()

    def _on_y_source_selection(self, sel):
        """Handle selection of a Y source."""
        combo = self.sender()
        source_num = combo.source_num
        self._plot_y_sources[source_num] = combo.itemData(sel)
        self._update_axes()

    def _on_click_all_measurements(self):
        """Handle Show All button."""
        m_keys = list(self._main_window._measurements.keys())
        print(m_keys)
        num_items = min(self._max_plot_items, len(m_keys))
        for source_num in range(num_items):
            self._plot_y_sources[source_num] = m_keys[source_num]
        for source_num in range(num_items, self._max_plot_items):
            self._plot_y_sources[source_num] = None
        self._update_widgets()
        self._update_axes()

    def _on_click_no_measurements(self):
        """Handle Show None button."""
        for source_num in range(self._max_plot_items):
            self._plot_y_sources[source_num] = None
        self._update_widgets()
        self._update_axes()

    def _on_click_color_selector(self):
        """Handle color selector of a Y source."""
        button = self.sender()
        source_num = button.source_num
        match source_num:
            case 'X':
                prev_color = self._plot_x_axis_color
            case 'B':
                prev_color = self._plot_background_color
            case _:
                prev_color = self._plot_colors[source_num]
        color = QColorDialog.getColor(QColor(prev_color))
        if not color.isValid():
            return
        rgb = color.name()
        match source_num:
            case 'X':
                self._plot_x_axis_color = rgb
            case 'B':
                self._plot_background_color = rgb
            case _:
                self._plot_colors[source_num] = rgb
        button.setStyleSheet(f'background-color: {rgb}; max-width: 1.5em;')
        self._update_axes()

    def _on_y_line_width_selection(self, sel):
        """Handle line width selector of a Y source."""
        combo = self.sender()
        source_num = combo.source_num
        width = combo.itemData(sel)
        self._plot_widths[source_num] = width
        self.update()

    def _on_y_line_style_selection(self, sel):
        """Handle line style selector of a Y source."""
        combo = self.sender()
        source_num = combo.source_num
        style = combo.itemData(sel)
        self._plot_line_styles[source_num] = _LINE_STYLES[style][1]
        self.update()

    def _on_y_marker_size_selection(self, sel):
        """Handle marker size selector of a Y source."""
        combo = self.sender()
        source_num = combo.source_num
        size = combo.itemData(sel)
        self._plot_marker_sizes[source_num] = size
        self.update()

    def _on_y_marker_style_selection(self, sel):
        """Handle marker style selector of a Y source."""
        combo = self.sender()
        source_num = combo.source_num
        style = combo.itemData(sel)
        self._plot_marker_styles[source_num] = _MARKER_SYMBOLS[style][1]
        self.update()

    def _update_widgets(self):
        """Update the control widgets based on currently available measurements."""
        # Duration selection
        for index in range(self._widget_duration.count()):
            if self._widget_duration.itemData(index) == self._plot_duration:
                self._widget_duration.setCurrentIndex(index)
                break

        # X axis selections
        self._widget_x_axis_combo.clear()
        self._widget_x_axis_combo.addItem('Elapsed Time', userData='Elapsed Time')
        self._widget_x_axis_combo.addItem('Absolute Time', userData='Absolute Time')
        for index, (key, name) in enumerate(self._main_window._measurement_names.items()):
            self._widget_x_axis_combo.addItem(name, userData=key)
            if key == self._plot_x_source:
                combo.setCurrentIndex(index)

        # Y axis selections
        for source_num, combo in enumerate(self._plot_y_source_combos):
            combo.clear()
            combo.addItem('Not used', userData=None)
            for index, (key, name) in enumerate(
                                self._main_window._measurement_names.items()):
                combo.addItem(name, userData=key)
                if key == self._plot_y_sources[source_num]:
                    combo.setCurrentIndex(index+1) # Account for "Not used"

    def _on_update_views(self):
        """Resize the plot."""
        for viewbox in self._plot_viewboxes[1:]:
            viewbox.setGeometry(self._plot_viewboxes[0].sceneBoundingRect())

    def update(self):
        """Update the plot using the current measurements."""
        if len(self._main_window._measurement_times) == 0:
            for plot_item in self._plot_items:
                plot_item.setData([], [])
            return

        start_time = self._main_window._measurement_times[0]
        stop_time = self._main_window._measurement_times[-1]

        # Update X axis range
        x_min = start_time
        x_max = stop_time
        x_scale = 1
        x_unit = 'sec'
        times = np.array(self._main_window._measurement_times)

        mask = None
        if x_max - x_min < self._plot_duration:
            # We have less data than the requested duration - no mask
            x_max = x_min + self._plot_duration
        else:
            x_min = x_max - self._plot_duration
            mask = times >= x_min
            # Make sure that x_min corresponds to an actual data point
            if np.any(mask):
                x_min = times[mask][0]
                x_max = x_min + self._plot_duration

        scatter = False
        if mask is None:
            times_mask = times
        else:
            times_mask = times[mask]
        match self._plot_x_source:
            case 'Elapsed Time':
                if 60 < self._plot_duration <= 60*60*3:
                    x_unit = 'min'
                    x_scale = 60
                elif 60*60*3 < self._plot_duration < 60*60*24*3:
                    x_unit = 'hour'
                    x_scale = 60*60
                elif 60*60*24*3 < self._plot_duration:
                    x_unit = 'day'
                    x_scale = 60*60*24
                self._plot_x_axis_item.setLabel(f'Elapsed Time ({x_unit})')
                x_min -= start_time
                x_max -= start_time
                x_min /= x_scale
                x_max /= x_scale
                x_vals = (times_mask - start_time) / x_scale
            case 'Absolute Time':
                # This will autoscale nicely
                x_vals = times_mask
            case _:
                x_scale = None
                scatter = True
                x_vals = np.array(self._main_window._measurements[self._plot_x_source])
                if mask is not None:
                    x_vals = x_vals[mask]
        if x_scale is not None:
            self._plot_viewboxes[0].setRange(xRange=(x_min, x_max), padding=0)

        for plot_num in range(self._max_plot_items):
            plot_key = self._plot_y_sources[plot_num]
            plot_item = self._plot_items[plot_num]
            if plot_key is None:
                plot_item.setData([], [])
                continue
            y_vals = np.array(self._main_window._measurements[plot_key])
            if mask is not None:
                y_vals = y_vals[mask]
            if scatter:
                pen = None
                symbol_color = self._plot_colors[plot_num]
                symbol = self._plot_marker_styles[plot_num]
                symbol_size = self._plot_marker_sizes[plot_num]*3
            else:
                pen = pg.mkPen(QColor(self._plot_colors[plot_num]),
                               width=self._plot_widths[plot_num],
                               style=self._plot_line_styles[plot_num])
                symbol_color = None
                symbol = None
                symbol_size = None
            if not np.all(np.isnan(x_vals)) and not np.all(np.isnan(y_vals)):
                plot_item.setData(x_vals, y_vals, connect='finite',
                                  pen=pen, symbol=symbol, symbolSize=symbol_size,
                                  symbolPen=None, symbolBrush=symbol_color)
            else:
                plot_item.setData([], [])

    def measurements_changed(self):
        """Called when the set of instruments/measurements changes."""
        if (self._plot_x_source not in ('Elapsed Time', 'Absolute Time') and
            self._plot_x_source not in self._main_window._measurements):
            # The X source disappeared
            self._plot_x_source = 'Elapsed Time'
        for source_num in range(self._max_plot_items):
            if self._plot_y_sources[source_num] not in self._main_window._measurements:
                # The Y source disappeared
                self._plot_y_sources[source_num] = None
        self._update_widgets()
        self._update_axes()

    def _update_axes(self):
        """Update the plot axes and background color."""
        self._plot_graphics_view_widget.setBackground(self._plot_background_color)
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
        self._plot_x_axis_item.setPen(self._plot_x_axis_color)
        self._plot_x_axis_item.setTextPen(self._plot_x_axis_color)
        if self._plot_x_source in ('Elapsed Time', 'Absolute Time'):
            self._master_plot_item.setLabel(axis='bottom', text=self._plot_x_source)
        else:
            m_name = self._main_window._measurement_names[self._plot_x_source]
            m_unit = self._main_window._measurement_units[self._plot_x_source]
            label = f'{m_name} ({m_unit})'
            self._master_plot_item.setLabel(axis='bottom', text=label)
        for plot_num in range(self._max_plot_items):
            plot_key = self._plot_y_sources[plot_num]
            axis_item = self._plot_y_axis_items[plot_num]
            if plot_key is None:
                axis_item.hide()
                continue
            axis_item.show()
            plot_item = self._plot_items[plot_num]
            color = self._plot_colors[plot_num]
            m_name = self._main_window._measurement_names[plot_key]
            m_unit = self._main_window._measurement_units[plot_key]
            label = f'{m_name} ({m_unit})'
            axis_item.setLabel(label)
            axis_item.setPen(self._plot_colors[plot_num])
            axis_item.setTextPen(self._plot_colors[plot_num])
        self.update()