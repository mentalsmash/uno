###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
import threading
from ..core.time import Timestamp


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
    super().__init__()

  @property
  def trigger_delay(self) -> int:
    if self._last_trigger_ts is None:
      return self.max_trigger_delay + 1
    return int(Timestamp.now().subtract(self._last_trigger_ts).total_seconds())

  def trigger(self) -> None:
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
        if test_length > self.max_trigger_delay:
          self.log.warning(
            "handler took longer than max delay: {} > {}", test_length, self.max_trigger_delay
          )
    except Exception as e:
      self._service_active = False
      self.log.error("exception in service thread")
      self.log.exception(e)
      raise e
    self.log.debug("service stopped")

  def start_trigger_thread(self) -> None:
    if self._service_thread is not None:
      return
    self._service_active = True
    self._service_thread = threading.Thread(target=self.run)
    self._service_thread.start()

  def stop_trigger_thread(self) -> None:
    if self._service_thread is None:
      return
    try:
      self._service_active = False
      self.trigger()
      self._service_thread.join()
    finally:
      self._service_thread = None

  def _handle_trigger(self) -> None:
    raise NotImplementedError()
