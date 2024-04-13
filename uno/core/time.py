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
from typing import Callable
import time

from .log import UvnLogger


class Timestamp:
  # EPOCH = datetime.utcfromtimestamp(0)
  DEFAULT_FORMAT = "%Y%m%d-%H%M%S-%f"

  def __init__(self, ts: datetime):
    self._ts = ts

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Timestamp):
      return False
    return self._ts.timetz() == other._ts.timetz()

  def __hash__(self) -> int:
    return hash(self._ts)

  def subtract(self, ts: "Timestamp | int") -> timedelta:
    return self._ts - ts._ts

  def format(self, fmt: str | None = None) -> str:
    if fmt is None:
      fmt = self.DEFAULT_FORMAT
    return self._ts.strftime(fmt)

  def from_epoch(self) -> int:
    return int(self._ts.timestamp())

  def __str__(self):
    return self.format()

  @staticmethod
  def parse(val: str | int, fmt: str | None = None):
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
  def unix(ts: str | int):
    ts = datetime.fromtimestamp(float(ts), timezone.utc)
    return Timestamp(ts)


_epoch = datetime.fromtimestamp(0)
_epoch = _epoch.replace(tzinfo=timezone.utc)
Timestamp.EPOCH = Timestamp(_epoch)


class Timer:
  class TimeoutError(Exception):
    def __init__(self, *args: object) -> None:
      super().__init__(*args)

  def __init__(
    self,
    period: int = -1,
    check_delay: float = 0,
    check_condition: Callable[[], bool] | None = None,
    logger: UvnLogger | None = None,
    start_message: str | None = None,
    not_ready_message: str | None = None,
    ready_message: str | None = None,
    timeout_message: str | None = None,
  ) -> None:
    self._period = period
    self._ts_start = None
    self._check_delay = check_delay
    self._check_condition = check_condition
    self._start_message = start_message
    self._not_ready_message = not_ready_message
    self._ready_message = ready_message
    self._timeout_message = timeout_message
    self._logger = logger

  def _log(self, *args, level="activity") -> None:
    if self._logger is None:
      return
    getattr(self._logger, level)(*args)

  @property
  def expired(self) -> bool:
    assert self._ts_start is not None
    if self._period < 0:
      return False
    elif self._period == 0:
      return True
    else:
      return Timestamp.now().subtract(self._ts_start).total_seconds() >= self._period

  def start(self) -> None:
    assert self._ts_start is None
    self._ts_start = Timestamp.now()
    if self._start_message:
      self._log(self._start_message)

  def check(self) -> None:
    if self.expired:
      raise Timer.TimeoutError(f"timeout expired: {self._timeout_message}", self._period)
    if self._not_ready_message:
      self._log(self._not_ready_message, level="debug")
    if self._check_delay > 0:
      time.sleep(self._check_delay)

  def stop(self) -> timedelta:
    assert self._ts_start is not None
    now = Timestamp.now()
    start_ts = self._ts_start
    self._ts_start = None
    result = now.subtract(start_ts)
    if self._ready_message:
      self._log("{} [{} seconds]", self._ready_message, result.total_seconds())
    return result

  def wait(self) -> timedelta:
    assert self._check_condition is not None
    self.start()
    while not self._check_condition():
      self.check()
    return self.stop()
