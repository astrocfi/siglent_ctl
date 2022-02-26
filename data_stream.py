import time

import pandas as pd

class DataStream(object):
    def __init__(self, name='Value'):
        self._name = name
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
