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
from datetime import datetime, timezone, timedelta
import time

from typing import Union, Optional

class Timestamp:
  EPOCH = datetime.utcfromtimestamp(0)
  DEFAULT_FORMAT = "%Y%m%d-%H%M%S-%f"


  def __init__(self, ts: datetime):
    self._ts = ts


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Timestamp):
      return False
    return self._ts.timetz() == other._ts.timetz()


  def subtract(self, ts: Union["Timestamp", int]) -> timedelta:
    return self._ts - ts._ts


  def format(self, fmt: Optional[str]=None) -> str:
    if fmt is None:
      fmt = self.DEFAULT_FORMAT
    return self._ts.strftime(fmt)


  def from_epoch(self) -> int:
    return int(self._ts.timestamp())


  def __str__(self):
    return self.format()


  @staticmethod
  def parse(val: str|int, fmt: Optional[str] = None):
    if fmt is None:
      fmt = Timestamp.DEFAULT_FORMAT
    if isinstance(val, str):
      ts = datetime.strptime(val, fmt)
      ts = ts.replace(tzinfo=timezone.utc)
    else:
      ts = datetime.fromtimestamp(val, tz=timezone.utc)
    return Timestamp(ts)


  @staticmethod
  def now():
    ts = datetime.now(timezone.utc)
    return Timestamp(ts)


  @staticmethod
  def unix(ts: Union[str, int]):
    ts = datetime.fromtimestamp(float(ts), timezone.utc)
    return Timestamp(ts)
