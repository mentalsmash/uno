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
import rti.connextdds as dds
from ..core.time import Timestamp

from ..registry.versioned import Versioned


class Triggerrable:
  max_trigger_delay: int = 60

  def __init__(self) -> None:
    self._trigger_sem = threading.BoundedSemaphore(1)
    self._trigger_sem.acquire()
    self._state_lock = threading.Lock()
    self._service_thread = None
    self._service_active = False
    self._triggered = False
    self._last_trigger_ts = None
    self.result_available_condition = dds.GuardCondition()
    super().__init__()


  @property
  def trigger_delay(self) -> int:
    if self._last_trigger_ts is None:
      return self.max_trigger_delay + 1
    return int(Timestamp.now().subtract(self._last_trigger_ts).total_seconds())


  def trigger_service(self) -> None:
    self.log.debug("triggering")
    with self._state_lock:
      if self._triggered:
        self.log.debug("already queued.")
        return
      self._triggered = True
    self.log.debug("trigger queued.")
    self._trigger_sem.release()


  def run(self) -> None:
    try:
      self.log.debug("service started")
      while self._service_active:
        self._trigger_sem.acquire(timeout=self.max_trigger_delay)
        with self._state_lock:
          triggered = self._triggered
          self._triggered = False
        triggered = triggered or self.trigger_delay >= self.max_trigger_delay
        if not self._service_active or not triggered:
          continue

        self._last_trigger_ts = Timestamp.now()

        self._handle_trigger()
        if not self._service_active:
          continue

        test_end = Timestamp.now()
        test_length = int(test_end.subtract(self._last_trigger_ts).total_seconds())
        self.log.debug("trigger handled in {} seconds", test_length)
        self.result_available_condition.trigger_value = True
        if test_length > self.max_trigger_delay:
          self.log.warning("handler took longer than max delay: {} > {}", test_length, self.max_trigger_delay)
    except Exception as e:
      self._service_active = False
      self.log.error("exception in service thread")
      self.log.exception(e)
      raise e
    self.log.debug("service stopped")


  def start_service(self) -> None:
    if self._service_thread is not None:
      return
    self._service_active = True
    self._service_thread = threading.Thread(target=self.run)
    self._service_thread.start()


  def stop_service(self) -> None:
    if self._service_thread is None:
      return
    try:
      self._service_active = False
      self.trigger_service()
      self._service_thread.join()
    finally:
      self._service_thread = None


  def _handle_trigger(self) -> None:
    raise NotImplementedError()




