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
import os
from pathlib import Path
import importlib

from .condition import Condition
from .participant import Participant

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..core.log import Logger
  
log = Logger.sublogger("middleware")

if TYPE_CHECKING:
  from ..registry.registry import Registry
  from ..agent.agent import Agent

class Middleware:
  EnvVar = "UNO_MIDDLEWARE"
  Default = ["uno_middleware_connext", "uno.middleware.native"]

  CONDITION: type[Condition] = None
  PARTICIPANT: type[Participant] = None

  @classmethod
  def load(cls) -> "Middleware":
    def _load_cls(plugin: str) -> Middleware|None:
      try:
        log.activity("loading middleware: {}", plugin)
        plugin_mod = importlib.import_module(plugin)
        ImplCls = getattr(plugin_mod, "Middleware")
        assert(issubclass(ImplCls, cls))
        log.info("loaded middleware: {}", plugin)
        return ImplCls
      except Exception as e:
        log.error("failed to load middleware {}: {}", plugin, e)
        log.exception(e)
        return None

    plugin = os.environ.get(cls.EnvVar)
    if plugin:
      ImplCls = _load_cls(plugin)
      if ImplCls is None:
        raise RuntimeError(f"invalid middleware selected via {cls.EnvVar}", plugin)
      return ImplCls()
    else:
      for plugin in cls.Default:
        ImplCls = _load_cls(plugin)
        if ImplCls is not None:
          return ImplCls()
      raise RuntimeError("no middleware available")


  def supports_agent(self) -> bool:
    return True


  def condition(self) -> Condition:
    return self.CONDITION()


  def participant(self,
      agent: "Agent|None"=None,
      registry: "Registry|None"=None,
      owner: "Uvn|Cell|None"=None) -> Participant:
    return self.PARTICIPANT(agent=agent, registry=registry, owner=owner)
