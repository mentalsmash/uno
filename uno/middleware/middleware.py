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
from types import ModuleType
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


  def __init__(self, plugin: str, module: ModuleType):
    self.plugin = plugin
    self.module = module


  @classmethod
  def load_module(cls) -> tuple[str, ModuleType]:
    def _load_module(plugin: str) -> ModuleType|None:
      try:
        log.debug("loading middleware: {}", plugin)
        plugin_mod = importlib.import_module(plugin)
        ImplCls = getattr(plugin_mod, "Middleware")
        assert(issubclass(ImplCls, cls))
        log.activity("loaded middleware: {} ({})", plugin, Path(plugin_mod.__file__))
        return plugin_mod
      except Exception as e:
        log.error("failed to load middleware {}: {}", plugin, e)
        log.exception(e)
        return None

    plugin = os.environ.get(cls.EnvVar)
    if plugin:
      plugin_mod = _load_module(plugin)
      if plugin_mod is None:
        raise RuntimeError(f"invalid middleware selected via {cls.EnvVar}", plugin)
      return (plugin, plugin_mod)
    else:
      for plugin in cls.Default:
        plugin_mod = _load_module(plugin)
        if plugin_mod is not None:
          return (plugin, plugin_mod)
      raise RuntimeError("no middleware available")
  

  @classmethod
  def load(cls) -> "Middleware":
    plugin, plugin_mod = cls.load_module()
    ImplCls = getattr(plugin_mod, "Middleware")
    return ImplCls(plugin=plugin, module=plugin_mod)


  @classmethod
  def plugin_base_directory(cls, uno_dir: Path, plugin: str, plugin_module: ModuleType) -> Path | None:
    plugin_base_dir = Path(plugin_module.__file__).parent
    try:
      # If the plugin directory is in the base uno repository, we don't need to mount it
      plugin_base_dir.relative_to(uno_dir)
      plugin_base_dir = None
    except ValueError:
      # Determine the base directory to add to PYTHONPATH
      plugin_parent_depth = len(plugin.split("."))
      for i in range(plugin_parent_depth):
        plugin_base_dir = plugin_base_dir.parent
    return plugin_base_dir


  @property
  def install_instructions(self) -> str | None:
    return None


  @classmethod
  def supports_agent(cls) -> bool:
    return True


  def condition(self) -> Condition:
    return self.CONDITION()


  def participant(self,
      agent: "Agent|None"=None,
      registry: "Registry|None"=None,
      owner: "Uvn|Cell|None"=None) -> Participant:
    return self.PARTICIPANT(agent=agent, registry=registry, owner=owner)
