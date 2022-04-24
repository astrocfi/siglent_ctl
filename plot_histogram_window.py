################################################################################
# plot_histogram_window.py
#
# This file is part of the inst_conductor software suite.
#
# It contains the plot window that displays a histogram.
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

from PyQt6.QtWidgets import (QCheckBox,
                             QColorDialog,
                             QComboBox,
                             QGridLayout,
                             QGroupBox,
                             QHBoxLayout,
                             QLabel,
                             QMenuBar,
                             QPushButton,
                             QSpinBox,
                             QVBoxLayout,
                             QWidget)
from PyQt6.QtGui import QAction, QColor, QKeySequence
from PyQt6.QtCore import Qt

import numpy as np
import pyqtgraph as pg


_TIME_DURATIONS = (('All data', 0),
                   ('15 seconds', 15),
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


class PlotHistogramWindow(QWidget):
    """Class to plot measurements as a histogram."""
    _PLOT_NUM = 0

    def __init__(self, main_window):
        super().__init__()
        self._main_window = main_window
        PlotHistogramWindow._PLOT_NUM += 1
        self.setWindowTitle(f'Histogram Plot #{PlotHistogramWindow._PLOT_NUM}')

        self._plot_background_color = '#000000'
        if len(main_window._measurement_names) > 0:
            self._plot_data_source = list(main_window._measurement_names.keys())[0]
        else:
            self._plot_data_source = None
        self._plot_x_axis_color = '#FFFFFF'
        self._plot_fill_color = '#0000A0'
        self._plot_edge_color = '#FFFFFF'
        self._plot_duration = 60 # Default to "1 min"
        self._plot_num_bins = 30
        self._plot_show_percentage = False

        ### Layout the widgets

        layoutv = QVBoxLayout()
        layoutv.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layoutv)
        layoutv.setSpacing(0)

        ### Create the menu bar

        self._menubar = QMenuBar()
        self._menubar.setStyleSheet('margin: 0px; padding: 0px;')

        self._menubar_view = self._menubar.addMenu('&View')
        action = QAction('Show &config row', self, checkable=True)
        action.setShortcut(QKeySequence('Ctrl+1'))
        action.setChecked(True)
        # action.triggered.connect(self._menu_do_show_config_row)

        layoutv.addWidget(self._menubar)

        ### The plot

        # https://stackoverflow.com/questions/44402399/how-to-disable-the-default-context-menu-of-pyqtgraph
        pw = pg.plot()
        self._plot_widget = pw
        # Disable zoom and pan
        self._plot_item = pw.plot([], stepMode='center', fillLevel=0, fillOutline=True,
                                  pen=QColor(self._plot_edge_color),
                                  brush=QColor(self._plot_fill_color))
        pw.setMouseEnabled(x=True, y=False)
        for action in pw.plotItem.vb.menu.actions():
            print(action.text())
            if action.text() in ('View All', 'Y axis', 'Mouse Mode'):
                action.setVisible(False)
        pw.plotItem.ctrlMenu.menuAction().setVisible(False)
        layoutv.addWidget(pw)

        ### Row 1

        layouth = QHBoxLayout()
        layouth.setContentsMargins(10, 10, 10, 10)
        w = QWidget()
        w.setLayout(layouth)
        # self._row_x_widgets.append(w)
        layoutv.addWidget(w)

        # Data source selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('Data Source:')
        layouth2.addWidget(label)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.activated.connect(self._on_data_source_selection)
        self._widget_data_source_combo = combo
        layouth2.addWidget(self._widget_data_source_combo)
        layouth2.addSpacing(5)

        # Time duration selector
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('View Last:')
        layouth2.addWidget(label)
        combo = QComboBox()
        combo.activated.connect(self._on_duration_selection)
        self._widget_duration = combo
        layouth2.addWidget(combo)
        for duration, secs in _TIME_DURATIONS:
            combo.addItem(duration, userData=secs)
        layouth2.addSpacing(5)

        # Num bins
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('# Bins:')
        layouth2.addWidget(label)
        input = QSpinBox()
        layouth2.addWidget(input)
        input.setRange(1, 999)
        input.setValue(self._plot_num_bins)
        input.valueChanged.connect(self._on_update_num_bins)
        layouth.addStretch()

        ### Row 2

        layouth = QHBoxLayout()
        layouth.setContentsMargins(10, 0, 10, 10)
        w = QWidget()
        w.setLayout(layouth)
        # self._row_x_widgets.append(w)
        layoutv.addWidget(w)

        # Show percentage
        cb = QCheckBox('Percentage')
        layouth.addWidget(cb)
        cb.clicked.connect(self._on_percentage)
        layouth.addWidget(cb)
        layouth2.addSpacing(5)

        # Fill color
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('Fill Color:')
        layouth2.addWidget(label)
        button = QPushButton('')
        layouth2.addWidget(button)
        button.setStyleSheet(
            f'background-color: {self._plot_fill_color}; max-width: 1.5em;')
        button.source_num = 'X'
        button.clicked.connect(self._on_click_fill_color_selector)
        layouth2.addSpacing(5)

        # Edge color
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('Edge Color:')
        layouth2.addWidget(label)
        button = QPushButton('')
        layouth2.addWidget(button)
        button.setStyleSheet(
            f'background-color: {self._plot_edge_color}; max-width: 1.5em;')
        button.source_num = 'X'
        button.clicked.connect(self._on_click_edge_color_selector)
        layouth2.addSpacing(5)

        # Background color
        layouth2 = QHBoxLayout()
        layouth.addLayout(layouth2)
        label = QLabel('Background Color:')
        layouth2.addWidget(label)
        button = QPushButton('')
        layouth2.addWidget(button)
        button.setStyleSheet(
            f'background-color: {self._plot_background_color}; max-width: 1.5em;')
        button.source_num = 'B'
        button.clicked.connect(self._on_click_background_color_selector)

        layouth.addStretch()

        self._update_axes()
        self._update_widgets()

    def _menu_do_show_row_x(self, state):
        """Handle Show X Row menu item."""
        self._x_row_action.setChecked(state)
        for w in self._row_x_widgets:
            if state:
                w.show()
            else:
                w.hide()

    def _on_data_source_selection(self, sel):
        """Handle selection of a data source."""
        combo = self.sender()
        self._plot_data_source = combo.itemData(sel)
        self._update_axes()

    def _on_click_edge_color_selector(self):
        """Handle color selector of the plot edge."""
        button = self.sender()
        color = QColorDialog.getColor(QColor(self._plot_edge_color))
        if not color.isValid():
            return
        rgb = color.name()
        self._plot_edge_color = rgb
        button.setStyleSheet(f'background-color: {rgb}; max-width: 1.5em;')
        self._update_axes()

    def _on_click_fill_color_selector(self):
        """Handle color selector of the plot fill."""
        button = self.sender()
        color = QColorDialog.getColor(QColor(self._plot_fill_color))
        if not color.isValid():
            return
        rgb = color.name()
        self._plot_fill_color = rgb
        button.setStyleSheet(f'background-color: {rgb}; max-width: 1.5em;')
        self._update_axes()

    def _on_click_background_color_selector(self):
        """Handle color selector of the plot background."""
        button = self.sender()
        color = QColorDialog.getColor(QColor(self._plot_background_color))
        if not color.isValid():
            return
        rgb = color.name()
        self._plot_background_color = rgb
        button.setStyleSheet(f'background-color: {rgb}; max-width: 1.5em;')
        self._update_axes()

    def _on_duration_selection(self, sel):
        """Handle selection of a duration."""
        combo = self.sender()
        self._plot_duration = combo.itemData(sel)
        self._update_axes()

    def _on_update_num_bins(self):
        """Handle change of value in number of bins."""
        input = self.sender()
        self._plot_num_bins = input.value()
        self.update()

    def _on_percentage(self):
        """Handle click on Percentage checkbox."""
        cb = self.sender()
        self._plot_show_percentage = cb.isChecked()
        self._update_axes()
        self.update()

    def _update_widgets(self):
        """Update the control widgets based on currently available measurements."""
        # Duration selection
        for index in range(self._widget_duration.count()):
            if self._widget_duration.itemData(index) == self._plot_duration:
                self._widget_duration.setCurrentIndex(index)
                break

        # Data source selections
        self._widget_data_source_combo.clear()
        for index, (key, name) in enumerate(self._main_window._measurement_names.items()):
            self._widget_data_source_combo.addItem(name, userData=key)

    def update(self):
        """Update the plot using the current measurements."""
        if (len(self._main_window._measurement_times) == 0 or
            self._plot_data_source is None):
            self._plot_item.setData([], [])
            return

        start_time = self._main_window._measurement_times[0]
        stop_time = self._main_window._measurement_times[-1]

        # Update X axis range
        x_min = start_time
        x_max = stop_time
        times = np.array(self._main_window._measurement_times)

        mask = None
        if self._plot_duration > 0:
            if x_max - x_min < self._plot_duration:
                # We have less data than the requested duration - no mask
                x_max = x_min + self._plot_duration
            else:
                x_min = x_max - self._plot_duration
                mask = times >= x_min

        if mask is None:
            times_mask = times
        else:
            times_mask = times[mask]
        vals = np.array(self._main_window._measurements[self._plot_data_source])
        if mask is not None:
            vals = vals[mask]
        finite_vals = vals[~np.isnan(vals)]
        if len(finite_vals) == 0:
            x_min = 0
            x_max = 1
        else:
            x_min = np.min(finite_vals)
            x_max = np.max(finite_vals)
            padding = (x_max-x_min)*0.02
            x_min -= padding
            x_max += padding
        if x_min == x_max:
            x_min -= 1
            x_max += 1
        # self._plot_.setRange(xRange=(x_min, x_max), padding=0)

        y, x = np.histogram(vals, range=(x_min, x_max), bins=self._plot_num_bins)
        if self._plot_show_percentage:
            y = y / len(vals) * 100

        self._plot_item.setData(x, y,
                                pen=pg.mkPen(QColor(self._plot_edge_color)),
                                brush=self._plot_fill_color)

    def measurements_changed(self):
        """Called when the set of instruments/measurements changes."""
        if self._plot_data_source not in self._main_window._measurements:
            # The data source disappeared
            self._plot_data_source = 'X'
        self._update_widgets()
        self._update_axes()

    def _update_axes(self):
        """Update the plot axes and background color."""
        self._plot_widget.setBackground(self._plot_background_color)
        # self._plot_x_axis_item.setPen(self._plot_x_axis_color)
        # self._plot_x_axis_item.setTextPen(self._plot_x_axis_color)
        if self._plot_data_source is None:
            label = '(No source selected)'
        else:
            m_name = self._main_window._measurement_names[self._plot_data_source]
            m_unit = self._main_window._measurement_units[self._plot_data_source]
            label = f'{m_name} ({m_unit})'
        self._plot_widget.setLabel(axis='bottom', text=label)
        if self._plot_show_percentage:
            self._plot_widget.setLabel(axis='left', text='Percentage')
        else:
            self._plot_widget.setLabel(axis='left', text='Count')

        self.update()
