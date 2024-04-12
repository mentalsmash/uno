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


from ..core.exec import shell_which

from .systemd_service import SystemdService


if TYPE_CHECKING:
  from .agent import Agent


class AgentStaticService(SystemdService):
  # PROPERTIES = [
  #   "uno_bin",
  #   "service_file_name",
  #   "root",
  # ]
  STR_PROPERTIES = [
    "name",
  ]

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.previous_service: AgentStaticService | None = None


  @cached_property
  def uno_bin(self) -> Path:
    uno_bin = shell_which("uno")
    assert(uno_bin is not None)
    return uno_bin


  @property
  def agent(self) -> "Agent":
    from .agent_service import AgentService
    if isinstance(self.parent, AgentService):
      return self.parent.agent
    return self.parent


  @cached_property
  def service_file_name(self) -> str:
    return f"uno-{self.name}.service"


  @cached_property
  def root(self) -> Path:
    return self.agent.root / "static" / self.name


  @property
  def template_context(self) -> dict:
    return {
      "uno_bin": self.uno_bin,
      "pid_file": self.agent.PID_FILE,
      "root": self.agent.root,
      "previous_service": self.previous_service,
      "name": self.name,
    }


  @property
  def template_id(self) -> str:
    return "service/agent-static-service.service"


  @property
  def config_id(self) -> str:
    return self.agent.registry_id


  def up(self) -> None:
    if self.active:
      self.log.warning("already active")
      return
    self.parent.start_static()
    # from .agent_service import AgentService
    # if isinstance(self.parent, AgentService):
    # else:
    #   self.agent.service_up(self.name)


  def down(self) -> None:
    self.parent.stop_static()
    # from .agent_service import AgentService
    # if isinstance(self.parent, AgentService):
    #   self.parent.stop_static()
    # else:
    #   self.agent.service_down(self.name)

