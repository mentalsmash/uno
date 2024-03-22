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
from typing import TYPE_CHECKING
from pathlib import Path
from functools import cached_property
import os
from enum import Enum
import rti.connextdds as dds

from ..core.exec import exec_command
from ..registry.versioned import Versioned

if TYPE_CHECKING:
  from .agent import Agent



class AgentServiceListener:
  EVENTS: type[Enum] = None

  def __init_subclass__(cls, *a, **kw) -> None:
    if cls.EVENTS is not None:
      assert(issubclass(cls.EVENTS, Enum))
    super().__init_subclass__(*a, **kw)


class AgentService(Versioned):
  CLASS: str = None
  USER: tuple[str] | None = None
  LISTENERS: type[AgentServiceListener] | None = None

  def __init__(self, *a, **kw) -> None:
    self.updated_condition = dds.GuardCondition()
    self.listeners: list[AgentServiceListener] = list()
    super().__init__(*a, **kw)


  @classmethod
  def check_enabled(cls, agent: "Agent") -> bool:
    return True


  @property
  def agent(self) -> "Agent":
    return self.parent


  @property
  def service_user(self) -> tuple[str|None, str|None]:
    return self.SvcUser or (None, None)


  @cached_property
  def svc_class(self) -> str:
    if self.CLASS:
      return self.CLASS
    else:
      return self.__class__.__name__.lower()


  @cached_property
  def root(self) -> Path:
    root = self.agent.root / self.svc_class
    self._mkdir(root)
    return root


  @cached_property
  def log_dir(self) -> Path:
    log_dir = self.agent.log_dir / self.svc_class
    self._mkdir(log_dir)
    return log_dir


  def mkdir(self, output: Path) -> None:
    if not output.is_dir():
      output.mkdir(parents=True)
      user, group = self.service_user
      if user and group:
        exec_command(["chown", f"{user}:{group}", output])


  def start(self) -> None:
    raise NotImplementedError()


  def stop(self) -> None:
    raise NotImplementedError()


  def notify_listeners(self, event: Enum, *args):
    for l in self.listeners:
      getattr(l, f"on_event_{event.name.lower()}")(*args)

