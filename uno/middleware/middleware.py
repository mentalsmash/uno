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
import os
from typing import TYPE_CHECKING
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

_Instance = None


class Middleware:
  CONDITION: type[Condition] = None
  PARTICIPANT: type[Participant] = None

  def __init_subclass__(cls) -> None:
    assert cls.PARTICIPANT is None or issubclass(
      cls.PARTICIPANT, Participant
    ), f"invalid class definition: PARTICIPANT must be a subclass of {Participant.__qualname__}"
    assert cls.CONDITION is None or issubclass(
      cls.CONDITION, Condition
    ), f"invalid class definition: CONDITION must be a subclass of {Condition.__qualname__}"

  @classmethod
  def load_plugin(cls, plugin: str) -> type["Middleware"]:
    log.activity("loading middleware plugin: {}", plugin)
    try:
      plugin_mod = importlib.import_module(plugin)
      ImplCls = getattr(plugin_mod, "Middleware")
      if not issubclass(ImplCls, Middleware):
        raise TypeError(ImplCls, "not a middleware")
    except Exception as e:
      if log.DEBUG:
        log.error("failed to load middleware plugin: {}", plugin)
        log.exception(e)
      raise
    log.activity("loaded middleware plugin: {}", plugin.__class__)
    return ImplCls

  @classmethod
  def selected(cls) -> type["Middleware"]:
    global _Instance
    if _Instance is None:

      def load():
        plugin = os.environ.get("UNO_MIDDLEWARE")
        if plugin:
          middleware = cls.load_plugin(plugin)
          middleware.plugin = plugin
        else:
          try:
            middleware = cls.load_plugin("uno.middleware.connext")
            middleware.plugin = "uno.middleware.connext"
          except Exception:
            middleware = Middleware
            middleware.plugin = None
        return middleware

      _Instance = load()
    return _Instance

  @classmethod
  def install_instructions(cls) -> str | None:
    return None

  @classmethod
  def supports_agent(cls, root: Path) -> bool:
    return cls.CONDITION is not None and cls.PARTICIPANT is not None

  @classmethod
  def install_cell_agent_package_files(cls, registry_root: Path, package_dir: Path) -> list[Path]:
    return []

  @classmethod
  def configure_extracted_cell_agent_package(cls, extracted_package: Path) -> None:
    pass

  @classmethod
  def condition(self) -> Condition:
    return self.CONDITION()

  @classmethod
  def participant(
    cls,
    agent: "Agent|None" = None,
    registry: "Registry|None" = None,
    owner: "Uvn|Cell|None" = None,
  ) -> Participant:
    return cls.PARTICIPANT(agent=agent, registry=registry, owner=owner)
