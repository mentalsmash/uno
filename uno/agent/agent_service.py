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
from typing import TYPE_CHECKING, Generator
from pathlib import Path
from functools import cached_property
import contextlib
import os
from enum import Enum
import rti.connextdds as dds

from ..core.exec import exec_command
from ..registry.versioned import disabled_if

from .runnable import Runnable

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
    "svc_class"
  ]

  def __init__(self, **properties) -> None:
    def _gchandler(cond: dds.GuardCondition) -> None:
      self.log.warning("condition triggered")
      self.agent.updated_services.put(self)
    self.updated_condition_triggered = False
    self.updated_condition = dds.GuardCondition()
    self.updated_condition.set_handler(_gchandler)
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

