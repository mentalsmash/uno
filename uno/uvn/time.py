###############################################################################
# (C) Copyright 2020-2024 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of the 
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################
import datetime
import time

from typing import Union, Optional

class Timestamp:
  EPOCH = datetime.datetime.utcfromtimestamp(0)
  DEFAULT_FORMAT = "%Y%m%d-%H%M%S"


  def __init__(self, ts: int):
    self._ts = ts


  def subtract(self, ts: Union["Timestamp", int]) -> float:
    self_ts = time.mktime(self._ts)
    if isinstance(ts, Timestamp):
      other_ts = time.mktime(ts._ts)
    else:
      other_ts = time.mktime(ts)
    return self_ts - other_ts


  def format(self, fmt: Optional[str]=None) -> str:
    if fmt is None:
      fmt = self.DEFAULT_FORMAT
    return time.strftime(fmt, self._ts)


  def millis(self) -> int:
    ts = datetime.datetime.fromtimestamp(time.mktime(self._ts))
    return (ts - self.EPOCH).total_seconds() * 1000.0
  

  def from_epoch(self) -> int:
    return int(time.mktime(self._ts))


  def __str__(self):
    return self.format()


  @staticmethod
  def parse(val, fmt: Optional[str] = None):
    if fmt is None:
      fmt = Timestamp.DEFAULT_FORMAT
    ts = time.strptime(val, fmt)
    return Timestamp(ts)


  @staticmethod
  def now():
    return Timestamp(time.gmtime())


  @staticmethod
  def unix(ts: Union[str, int]):
    return Timestamp(time.gmtime(int(ts)))