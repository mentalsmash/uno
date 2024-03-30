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
from typing import TYPE_CHECKING, Generator, Iterable
from pathlib import Path
from functools import cached_property
import contextlib
import os
from enum import Enum
import rti.connextdds as dds

from ..core.exec import exec_command, shell_which
from ..registry.versioned import disabled_if, error_if

from .render import Templates
from .runnable import Runnable
from .agent_static_service import AgentStaticService

if TYPE_CHECKING:
  from .agent import Agent


class StopAgentServiceError(Exception):
  pass


class AgentServiceListener:
  EVENT: type[Enum] = None

  def __init_subclass__(cls, *a, **kw) -> None:
    if cls.EVENT is not None:
      assert(issubclass(cls.EVENT, Enum))
    super().__init_subclass__(*a, **kw)


class AgentService(Runnable):
  USER: tuple[str] | None = None
  LISTENER: type[AgentServiceListener] = None

  EQ_PROPERTIES = [
    "svc_class",
    "parent",
  ]

  STATIC_SERVICE = None

  def __init__(self, **properties) -> None:
    self.updated_condition_triggered = False
    self.updated_condition = dds.GuardCondition()
    self.listeners: list[AgentServiceListener] = list()
    super().__init__(**properties)


  @property
  def agent(self) -> "Agent":
    return self.parent


  @cached_property
  def service_user(self) -> tuple[str, str] | tuple[None, None]:
    return tuple(self.USER or (None, None))


  @cached_property
  def svc_class(self) -> str:
    cls_name = self.__class__.__name__
    cls_name = cls_name[0].lower() + cls_name[1:]
    return self.log.camelcase_to_kebabcase(cls_name)


  @cached_property
  def root(self) -> Path:
    root = self.agent.root / self.svc_class
    self.mkdir(root)
    return root


  @cached_property
  def log_dir(self) -> Path:
    log_dir = self.agent.log_dir / self.svc_class
    self.mkdir(log_dir)
    return log_dir


  @disabled_if("runnable", neg=True)
  def mkdir(self, output: Path) -> None:
    if not output.is_dir():
      output.mkdir(parents=True)
      user, group = self.service_user
      if user and group:
        exec_command(["chown", f"{user}:{group}", output])


  @disabled_if("runnable", neg=True)
  def notify_listeners(self, event: Enum | str, *args):
    if isinstance(event, str):
      assert(issubclass(self.LISTENER, AgentServiceListener))
      event = self.LISTENER.EVENT[event.upper().replace("-", "_")]
    for l in self.listeners:
      getattr(l, f"on_event_{event.name.lower()}")(*args)


  @disabled_if("runnable", neg=True)
  def process_updates(self) -> None:
    self._process_updates()


  def _process_updates(self) -> None:
    raise NotImplementedError()


  @cached_property
  def static(self) -> AgentStaticService | None:
    if self.STATIC_SERVICE is None:
      return None
    return self.new_child(AgentStaticService, {
      "name": self.STATIC_SERVICE,
    })


  @disabled_if("runnable", neg=True)
  def start(self) -> None:
    if self.static is not None and self.static.current_marker is not None:
      self.static.check_marker_compatible()
      self.log.warning("taking over systemd unit")
      return
    super().start()
    if self.static:
      self.static.write_marker()


  def stop(self, assert_stopped: bool=False) -> None:
    try:
      super().stop(assert_stopped=assert_stopped)
    finally:
      if self.static:
        self.static.delete_marker()


  @error_if("static", neg=True)
  @disabled_if("runnable", neg=True)
  def start_static(self) -> None:
    self._start_static()
    self.static.write_marker()
    self.log.info("systemd unit started")


  @error_if("static", neg=True)
  def stop_static(self) -> None:
    self.stop(assert_stopped=True)
    self.log.info("systemd unit stopped")


  def _start_static(self) -> None:
    raise NotImplementedError()



