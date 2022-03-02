################################################################################
# data_stream.py
#
# This file is part of the siglent_ctl software suite.
#
# It contains definitions related to storing data streams, which include a
# series of measurements along with the name of the stream, units, etc.

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

import time

import pandas as pd

class DataStream(object):
    def __init__(self, name, unit):
        self._name = name
        self._unit = unit
        self._times = []
        self._time_steps = []
        self._values = []
        self._current_time_step = 0

    @property
    def name(self):
        return self._name

    def record_value(self, v):
        self._values.append(v)
        self._times.append(time.time())
        self._time_steps.append(self._current_time_step)
        self._current_time_step += 1

    @property
    def times(self):
        return self._times

    @property
    def time_steps(self):
        return self._time_steps

    @property
    def values(self):
        return self._values

    def to_ds(self):
        return pd.Series(data=(self._times, self._values),
                        index=self._time_steps)

    def to_df(self):
        return pd.DataFrame(data={self._name: self._values},
                            index=self._time_steps)

    def to_df_with_time(self):
        return pd.DataFrame(data={self._name+' Time': pd.to_datetime(self._times,
                                                                     unit='s'),
                                  self._name:         self._values},
                            index=self._time_steps)
