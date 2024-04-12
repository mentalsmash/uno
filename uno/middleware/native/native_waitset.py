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
import threading

from .native_condition import NativeCondition


class NativeWaitset:
  def __init__(self) -> None:
    self._semaphore = threading.Semaphore()
    self._lock = threading.RLock()
    self._condvar = threading.Condition(self._lock)
    self._conditions = []
    super().__init__()

  def attach(self, condition: NativeCondition):
    with self._lock:
      condition._waitset = self
      if condition not in self._conditions:
        self._conditions.append(condition)

  def detach(self, condition: NativeCondition):
    with self._lock:
      condition._waitset = None

  def wait(self) -> list[NativeCondition]:
    with self._lock:
      self._condvar.acquire()
      active = []
      for cond in self._conditions:
        if cond._changed():
          active.append(cond)
    return active
