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
