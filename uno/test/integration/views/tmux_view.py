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
import shlex
import subprocess
from math import ceil
from enum import Enum
from typing import Generator, NamedTuple
from uno.test.integration import ExperimentView, Host, HostRole
from uno.core.log import Logger
from uno.test.integration.experiment import Experiment

log = Logger.sublogger("tmux")


class PaneType(Enum):
  TMUX_MAIN = "main"
  CONTAINER_LOGS = "logs"
  CONTAINER_SHELL = "shell"


class WindowActions:
  @classmethod
  def pane_command(cls, pane_type: PaneType, host: Host) -> list[str]:
    return {
      PaneType.CONTAINER_LOGS: ["docker", "logs", "-f", host.container_name],
      PaneType.CONTAINER_SHELL: ["docker", "exec", "-ti", host.container_name, "bash"],
    }[pane_type]


class Window(NamedTuple):
  session: str
  id: int
  title: str
  hosts: list[Host]
  pane_type: PaneType

  Actions = WindowActions

  def __str__(self) -> str:
    return self.title

  @property
  def win_id(self) -> str:
    return f"{self.session}:{self.id}"

  def create(self) -> None:
    cmd = ["tmux", "new-window", "-t", self.win_id, *(["-n", self.title] if self.title else [])]
    log.cmdexec(cmd)
    subprocess.run(cmd, check=True)

    if len(self.hosts) > 2:
      # 4x layout
      self._split(0, vertical=True)
      self._split(0)
      self._split(2)
    else:
      # 2x layout
      self._split(0)

    for pane_id, host in enumerate(self.hosts):
      cmd = self.Actions.pane_command(self.pane_type, host)
      self._exec(pane_id, cmd)

  def _split(self, pane_id: int, vertical: bool = False) -> None:
    cmd = [
      "tmux",
      "split-window",
      "-t",
      f"{self.win_id}.{pane_id}",
      "-p",
      "50",
      ("-v" if vertical else "-h"),
    ]
    log.cmdexec(cmd)
    subprocess.run(cmd, check=True)

  def _exec(self, pane_id: int, cmd: list[str]) -> None:
    pane_cmd = " ".join(map(shlex.quote, cmd))
    cmd = ["tmux", "send-keys", "-t", f"{self.win_id}.{pane_id}", pane_cmd, "C-m"]
    log.cmdexec(cmd)
    subprocess.run(cmd, check=True)

  def kill(self) -> None:
    cmd = ["tmux", "kill-window", "-t", self.win_id]
    log.cmdexec(cmd)
    subprocess.run(cmd, check=True)
    log.activity("window killed: {}", self)

  def select(self, pane_id: int) -> None:
    cmd = ["tmux", "select-window", "-t", f"{self.win_id}.{pane_id}"]
    log.cmdexec(cmd)
    subprocess.run(cmd, check=True)


class TmuxExperimentView(ExperimentView):
  Id = "tmux"
  Live = True
  WindowPanes = 4

  def __init__(self, experiment: Experiment) -> None:
    self.windows: list[Window] = []
    super().__init__(experiment)

  @property
  def tmux_session(self) -> str:
    return self.experiment.name

  def _create_session(self) -> None:
    cmd = ["tmux", "kill-session", "-t", self.tmux_session]
    self.log.cmdexec(cmd)
    subprocess.run(cmd)
    # Create detached so that we can setup different windows
    cmd = ["tmux", "new-session", "-s", self.tmux_session, "-d"]
    self.log.cmdexec(cmd)
    subprocess.run(cmd)
    self.log.info("created tmux session: {}", self.tmux_session)

  def display(self) -> None:
    assert len(self.windows) == 0, "view already initialized"

    def _host_key(host: Host) -> tuple[int, str]:
      if host.role == HostRole.REGISTRY:
        return (0, host.container_name)
      elif host.role == HostRole.CELL:
        return (1, host.container_name)
      elif host.role == HostRole.HOST:
        return (2, host.container_name)
      elif host.role == HostRole.PARTICLE:
        return (3, host.container_name)
      else:
        return (4, host.container_name)

    def _windows(hosts: list[Host]) -> Generator[tuple[str], None, None]:
      for i in range(0, len(hosts), self.WindowPanes):
        yield hosts[i : i + self.WindowPanes]

    def _window_title(w_i: int, pane_type: PaneType, hosts: list[Host]) -> str:
      hosts_str = "/".join(sorted({host.role.name.lower() for host in hosts}))
      return f"{w_i}. {pane_type.value} [{hosts_str}]"

    hosts = sorted(self.experiment.hosts, key=_host_key)
    windows_count = ceil(len(hosts) / self.WindowPanes)
    main_window = Window(self.tmux_session, 0, "main", [], PaneType.TMUX_MAIN)
    self.windows.append(main_window)

    self._create_session()

    for t_i, pane_type in enumerate([PaneType.CONTAINER_LOGS, PaneType.CONTAINER_SHELL]):
      for j, w_hosts in enumerate(_windows(hosts)):
        w_i = 1 + (t_i * windows_count) + j
        w_title = _window_title(w_i, pane_type, w_hosts)
        window = Window(self.tmux_session, w_i, w_title, w_hosts, pane_type)
        self.log.activity("creating window: {}", window.title)
        window.create()
        self.windows.append(window)
        self.log.info("window created: {}", window.title)
        for host in window.hosts:
          self.log.info("- {}", host)

    # Remove main window
    main_window.kill()

    # Select first pane in first window
    self.windows[1].select(0)

    tmux_cmd = ["tmux", "attach", "-t", self.tmux_session]
    subprocess.run(tmux_cmd)
