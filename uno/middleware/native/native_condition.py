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

from typing import TYPE_CHECKING
from uno.middleware import Condition

if TYPE_CHECKING:
  from .native_waitset import NativeWaitset


class NativeCondition(Condition):
  def __init__(self) -> None:
    self._lock = threading.RLock()
    self.__trigger_value = False
    self.__changed = False
    self.__waitset = None
    super().__init__()

  @property
  def _waitset(self) -> "NativeWaitset":
    with self._lock:
      return self.__waitset

  @_waitset.setter
  def _waitset(self, val: "NativeWaitset") -> None:
    with val._lock:
      with self._lock:
        self.__waitset = val

  @property
  def trigger_value(self) -> bool:
    waitset = self._waitset
    if waitset is not None:
      with waitset._lock:
        with self._lock:
          return self.__trigger_value
    else:
      with self._lock:
        return self.__trigger_value

  @trigger_value.setter
  def trigger_value(self, val: bool) -> None:
    def _update(waitset: NativeWaitset):
      self.__changed = self.__changed or self.__trigger_value != val
      self.__trigger_value = val
      if waitset is not None:
        waitset._condvar.notify_all()

    waitset = self._waitset
    if waitset is not None:
      with waitset._lock:
        with self._lock:
          return _update(waitset)
    else:
      with self._lock:
        return _update(None)

  def _changed(self) -> bool:
    waitset = self._waitset
    if waitset is not None:
      with waitset._lock:
        with self._lock:
          changed = self.__changed
          self.__changed = False
    else:
      with self._lock:
        changed = self.__changed
        self.__changed = False
    return changed
