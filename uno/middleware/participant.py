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
import ipaddress

from ..registry.topic import UvnTopic
from ..core.time import Timestamp
from ..core.wg import WireGuardConfig
from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.lan_descriptor import LanDescriptor
from ..registry.keys_backend_dds import DdsKeysBackend

if TYPE_CHECKING:
  from ..registry.registry import Registry
  from ..agent.agent import Agent


class Participant:
  def __init__(
    self,
    agent: "Agent|None" = None,
    registry: "Registry|None" = None,
    owner: "Uvn|Cell|None" = None,
  ) -> None:
    assert (agent is not None and registry is None) or (
      agent is None and registry is not None and owner is not None
    )
    self.__agent = agent
    self.__registry = registry
    self.__owner = owner

  @property
  def agent(self) -> "Agent":
    return self.__agent

  @property
  def registry(self) -> "Registry":
    if self.agent is not None:
      return self.agent.registry
    return self.__registry

  @property
  def owner(self) -> Uvn | Cell:
    if self.agent is not None:
      return self.agent.owner
    return self.__owner

  @property
  def root(self) -> Path:
    if self.agent is not None:
      return self.agent.root
    else:
      return self.registry.root

  @property
  def backbone_vpn_configs(self) -> list[WireGuardConfig]:
    if self.agent is not None:
      return [vpn.config for vpn in self.agent.backbone_vpns]
    return self.registry.vpn_config.backbone_vpn.peer_config(self.owner.id)

  @property
  def root_vpn_config(self) -> WireGuardConfig | None:
    if self.agent:
      return self.agent.root_vpn.config if self.agent.root_vpn else None
    return self.registry.root_vpn_config(self.owner)

  @property
  def initial_peers(self) -> list[ipaddress.IPv4Address]:
    if isinstance(self.owner, Cell):
      # Pick the address of the first backbone port for every peer
      # and all addresses for peers connected directly to this one
      backbone_peers = {
        peer_b[1]
        for peer_a in self.registry.deployment.peers.values()
        for peer_b_id, peer_b in peer_a["peers"].items()
        if peer_b[0] == 0 or peer_b_id == self.owner.id
      } - {config.intf.address for config in self.backbone_vpn_configs}
      return [
        *backbone_peers,
        *([self.root_vpn_config.peers[0].address] if self.root_vpn_config else []),
      ]
    elif isinstance(self.owner, Uvn):
      return [p.address for p in self.root_vpn_config.peers] if self.root_vpn_config else []

  @property
  def topics(self) -> dict[str, list[UvnTopic]]:
    if isinstance(self.owner, Cell):
      return {
        "writers": DdsKeysBackend.CELL_TOPICS["published"],
        "readers": DdsKeysBackend.CELL_TOPICS["subscribed"],
      }
    elif isinstance(self.owner, Uvn):
      return {
        "writers": DdsKeysBackend.REGISTRY_TOPICS["published"],
        "readers": DdsKeysBackend.REGISTRY_TOPICS["subscribed"],
      }
    else:
      raise NotImplementedError()

  def uvn_info(self, uvn: Uvn, registry_id: str) -> None:
    raise NotImplementedError()

  def cell_agent_config(self, uvn: Uvn, cell_id: int, registry_id: str, package: Path) -> None:
    raise NotImplementedError()

  def cell_agent_status(
    self,
    uvn: Uvn,
    cell_id: int,
    registry_id: str,
    ts_start: Timestamp | None = None,
    lans: list[LanDescriptor] | None = None,
    known_networks: dict[LanDescriptor, bool] | None = None,
  ) -> None:
    raise NotImplementedError()

  def start(self) -> None:
    raise NotImplementedError()

  def stop(self) -> None:
    raise NotImplementedError()

  def spin(self) -> bool:
    raise NotImplementedError()

  def install(self) -> None:
    pass

  @property
  def cell_agent_package_files(self) -> Generator[Path, None, None]:
    for f in []:
      yield f
