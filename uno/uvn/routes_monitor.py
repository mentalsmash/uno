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
from typing import Tuple
import subprocess
import threading
import os
from pathlib import Path
from enum import Enum

import rti.connextdds as dds

from .ip import ipv4_list_routes

from .log import Logger as log

class RoutesMonitorListener:
  class Event(Enum):
    LOCAL_ROUTES = 0

  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    pass


class RoutesMonitor:
  def __init__(self, log_dir: Path) -> None:
    self._log_dir = log_dir
    self.updated_condition = dds.GuardCondition()
    self._monitor = None
    self._monitor_thread = None
    self._active = False
    self.listeners: list[RoutesMonitorListener] = list()


  @property
  def routes_file(self) -> Path:
    return self._log_dir / "routes.local"


  def notify(self, event: RoutesMonitorListener.Event, *args):
    for l in self.listeners:
      getattr(l, f"on_event_{event.name.lower()}")(*args)


  def process_updates(self) -> None:
    new_routes, gone_routes = self.poll_routes()
    if new_routes or gone_routes:
      self.notify(RoutesMonitorListener.Event.LOCAL_ROUTES, new_routes, gone_routes)



  def _read_routes(self) -> set[str]:
    if not self.routes_file.exists():
      return set()
    return set(l for l in self.routes_file.read_text().splitlines() if l)


  def _write_routes(self, routes: set[str]) -> None:
    with self.routes_file.open("wt") as output:
      for r in routes:
        output.write(r)
        output.write("\n")


  def poll_routes(self) -> Tuple[set[str], set[str]]:
    current_routes = ipv4_list_routes()
    prev_routes = self._read_routes()
    new_routes = current_routes - prev_routes
    gone_routes = prev_routes - current_routes
    if not (new_routes or gone_routes):
      return (set(), set())
    self._write_routes(current_routes)
    return (new_routes, gone_routes)


  def start(self) -> None:
    self.poll_routes()
    self._monitor = subprocess.Popen(["ip", "monitor", "route"],
      stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE,
      stderr=subprocess.DEVNULL,
      preexec_fn=os.setpgrp,
      text=True)
    self._monitor_thread = threading.Thread(target=self._run)
    self._active = True
    self._monitor_thread.start()


  def stop(self) -> None:
    self._active = False
    if self._monitor is not None:
      import signal
      self._monitor.send_signal(signal.SIGINT)
      if self._monitor_thread is not None:
        self._monitor_thread.join()
        self._monitor_thread = None
      self._monitor = None


  def _run(self):
    log.activity(f"[ROUTE-MONITOR] starting to monitor kernel routes")
    while self._active:
      try:
        route_change = self._monitor.stdout.readline()
        log.activity(f"[ROUTE-MONITOR] detected: '{route_change}'")
        self.updated_condition.trigger_value = True
      except Exception as e:
        log.error(f"[ROUTE-MONITOR] error in monitor thread")
        log.exception(e)
    log.activity(f"[ROUTE-MONITOR] stopped")
