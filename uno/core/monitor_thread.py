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


class MonitorThread(threading.Thread):
  def __init__(self, name, min_wait=0):
    threading.Thread.__init__(self)
    # set thread name
    self.name = name
    self._min_wait = min_wait
    self._queued = False
    self._lock = threading.RLock()
    self._sem_run = threading.Semaphore()
    self._sem_run.acquire()
    self._sem_exit = threading.BoundedSemaphore()
    self._sem_exit.acquire()

  def trigger(self):
    with self._lock:
      if self._queued:
        return
      self._queued = True
    self._sem_run.release()

  def _do_monitor(self):
    raise NotImplementedError()

  def run(self):
    complete = False
    while not complete and not self._exit:
      self._sem_run.acquire()
      if self._exit:
        continue

      run = False
      with self._lock:
        run = self._queued
        if run:
          self._queued = False
      if run:
        self._do_monitor()
      if self._min_wait:
        complete = self._sem_exit.acquire(timeout=self._min_wait)
      else:
        complete = self._sem_exit.acquire(blocking=False)

  def start(self):
    self._exit = False
    super().start()

  def stop(self):
    if not self.is_alive():
      return
    self._exit = True
    self._sem_exit.release()
    self._sem_run.release()
    self.join()
