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
import subprocess
import threading
import os
from pathlib import Path
from enum import Enum
import signal

from ..registry.cell import Cell
from ..core.ip import ipv4_list_routes
from .agent_service import AgentService, AgentServiceListener


class RoutesMonitorEvent(Enum):
  LOCAL_ROUTES = 1


class RoutesMonitorListener(AgentServiceListener):
  EVENT = RoutesMonitorEvent

  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    pass


class RoutesMonitor(AgentService):
  LISTENER = RoutesMonitorListener

  def __init__(self, **properties) -> None:
    self._monitor = None
    self._monitor_thread = None
    self._monitor_thread_active = False
    self._monitor_thread_started = threading.Semaphore(0)
    super().__init__(**properties)

  def check_runnable(self) -> bool:
    return isinstance(self.agent.owner, Cell)

  @property
  def routes_file(self) -> Path:
    return self.log_dir / "routes.local"

  def _process_updates(self) -> None:
    new_routes, gone_routes = self.poll_routes()
    if new_routes or gone_routes:
      self.notify_listeners("local-routes", new_routes, gone_routes)

  def _read_routes(self) -> set[str]:
    if not self.routes_file.exists():
      return set()
    return set(lan for lan in self.routes_file.read_text().splitlines() if lan)

  def _write_routes(self, routes: set[str]) -> None:
    with self.routes_file.open("wt") as output:
      for r in routes:
        output.write(r)
        output.write("\n")

  def poll_routes(self) -> tuple[set[str], set[str]]:
    current_routes = ipv4_list_routes()
    prev_routes = self._read_routes()
    new_routes = current_routes - prev_routes
    gone_routes = prev_routes - current_routes
    if not (new_routes or gone_routes):
      return (set(), set())
    self._write_routes(current_routes)
    return (new_routes, gone_routes)

  def _start(self) -> None:
    self.poll_routes()
    self._monitor = subprocess.Popen(
      ["ip", "monitor", "route"],
      stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE,
      stderr=subprocess.DEVNULL,
      preexec_fn=os.setpgrp,
      text=True,
    )
    self._monitor_thread = threading.Thread(target=self._monitor_thread_run)
    self._monitor_thread_active = True
    self._monitor_thread.start()
    self._monitor_thread_started.acquire()

  def _stop(self, assert_stopped: bool) -> None:
    if self._monitor is not None:
      self._monitor_thread_active = False
      self._monitor.send_signal(signal.SIGINT)
      if self._monitor_thread is not None:
        self._monitor_thread.join()
        self._monitor_thread = None
      self._monitor = None

  def _monitor_thread_run(self):
    self.log.activity("starting to monitor kernel routes")
    self._monitor_thread_started.release()
    while self._monitor_thread_active:
      try:
        self.log.debug("reading next...")
        route_change = self._monitor.stdout.readline()
        self.log.debug("detected: '{}'", route_change.strip())
        self.updated_condition.trigger_value = True
      except Exception as e:
        self.log.error("error in monitor thread")
        self.log.exception(e)
    self.log.activity("stopped")
