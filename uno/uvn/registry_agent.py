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
from pathlib import Path
from typing import Tuple

from .uvn_id import UvnId, CellId
from .wg import WireGuardInterface
from .dds import DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList
from .render import Templates
from .dds_data import uvn_info, cell_agent_config
from .agent_net import AgentNetworking
from .agent import Agent
from .vpn_config import P2PLinksMap
from .keys import KeyId
from .id_db import IdentityDatabase
from .peer import UvnPeerStatus
from .time import Timestamp
from .log import Logger as log


class RegistryAgent(Agent):
  TOPICS = {
    "writers": [
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
    ],

    "readers": {
      UvnTopic.CELL_ID: {},
    },
  }

  def __init__(self, registry: Registry) -> None:
    if not registry.deployed:
      raise ValueError("uvn not deployed", registry)
    if not registry.uvn_id.settings.enable_root_vpn:
      raise ValueError("root vpn disabled by uvn", registry)

    self.registry = registry
    self._rekeyed_registry = self.registry.rekeyed_registry

    self.root_vpn = WireGuardInterface(self.registry.root_vpn_config.root_config)

    self._peers = UvnPeersList(
      uvn_id=self.uvn_id,
      registry_id=self.registry_id,
      local_peer_id=0)
    self._peers.listeners.append(self)

    self._net = AgentNetworking(
      root=True,
      config_dir=self.config_dir,
      vpn_interfaces=self.vpn_interfaces)
  
    super().__init__()


  @property
  def needs_rekeying(self) -> bool:
    return self._rekeyed_registry is not None


  @property
  def id_db(self) -> IdentityDatabase:
    return self.registry.id_db


  @property
  def registry_id(self) -> str:
    if self._rekeyed_registry:
      return self._rekeyed_registry.id
    return self.registry.id


  @property
  def deployment(self) -> P2PLinksMap:

    return self.registry.backbone_vpn_config.deployment


  @property
  def uvn_id(self) -> UvnId:
    return self.registry.uvn_id


  @property
  def root(self) -> Path:
    return self.registry.root


  @property
  def peers(self) -> UvnPeersList:
    return self._peers


  @property
  def vpn_interfaces(self) -> set[WireGuardInterface]:
    return {self.root_vpn}


  @property
  def net(self) -> AgentNetworking:
    return self._net


  @property
  def dds_xml_config(self) -> Tuple[str, str, dict]:
    if not self.registry.rti_license.is_file():
      log.error(f"RTI license file not found: {self.registry.rti_license}")
      raise RuntimeError("RTI license file not found")

    initial_peers = [p.address for p in self.root_vpn.config.peers]
    initial_peers = [f"[0]@{p}" for p in initial_peers]

    key_id = KeyId.from_uvn_id(self.registry.uvn_id)
    Templates.generate(self.participant_xml_config, "dds/uno.xml", {
      "uvn": self.registry.uvn_id,
      "cell": None,
      "initial_peers": initial_peers,
      "timing": self.registry.uvn_id.settings.timing_profile,
      "license_file": self.registry.rti_license.read_text(),
      "ca_cert": self.id_db.backend.ca.cert,
      "perm_ca_cert": self.id_db.backend.perm_ca.cert,
      "cert": self.id_db.backend.cert(key_id),
      "key": self.id_db.backend.key(key_id),
      "governance": self.id_db.backend.governance,
      "permissions": self.id_db.backend.permissions(key_id),
      "enable_dds_security": self.uvn_id.settings.enable_dds_security,
      "domain": self.uvn_id.settings.dds_domain,
      "domain_tag": self.uvn_id.name,
    })

    return (self.participant_xml_config, RegistryAgent.TOPICS)


  def _on_started(self, boot: bool=False) -> None:
    self._write_uvn_info()
    # self._write_agent_configs()


  def on_event_all_cells_connected(self) -> None:
    super().on_event_all_cells_connected()
    self._write_agent_configs()


  def _write_uvn_info(self) -> None:
    sample = uvn_info(
      participant=self.dp,
      uvn_id=self.uvn_id,
      registry_id=self.registry_id)
    self.dp.writers[UvnTopic.UVN_ID].write(sample)
    log.activity(f"[AGENT] published uvn info: {self.uvn_id.name}")


  def _write_agent_configs(self, target_cells: list[CellId]|None=None):
    cells_dir = self.registry.root / "cells"
    for cell in self.uvn_id.cells.values():
      if target_cells is not None and cell not in target_cells:
        continue
      cell_package = cells_dir / f"{cell.name}.uvn-agent"
      import tempfile
      tmp_dir_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_dir_h.name)
      from .exec import exec_command
      exec_command(["tar", "xJf", cell_package, Registry.AGENT_CONFIG_FILENAME], cwd=tmp_dir)
      config = tmp_dir / Registry.AGENT_CONFIG_FILENAME
      enc_config = Path(f"{config}.enc")

      key = self.id_db.backend[cell]
      self.id_db.backend.encrypt_file(key, config, enc_config)
      
      sample = cell_agent_config(
        participant=self.dp,
        uvn_id=self.uvn_id,
        cell_id=cell.id,
        registry_id=self.registry_id,
        config_string=enc_config.read_text(),
        package=cell_package)
      self.dp.writers[UvnTopic.BACKBONE].write(sample)
      log.activity(f"[AGENT] published agent configuration: {cell}")


  def spin_until_rekeyed(self,
      max_spin_time: int|None=None,
      config_only: bool=False) -> None:
    if not self._rekeyed_registry:
      raise RuntimeError("no rekeyed registry available")

    all_cells = set(c.name for c in self.uvn_id.cells.values())
    
    log.warning(f"[AGENT] pushing rekeyed configuration to {len(all_cells)} cells: {self.registry.id} → {self._rekeyed_registry.id}")

    state = {
      "offline": set(),
      "stage": 0,
    }
    def _on_condition_check() -> bool:
      if state["stage"] == 0:
        log.debug(f"[AGENT] waiting to detect all cells ONLINE")
        if self.peers.status_all_cell_connected:
          state["stage"] = 1
      elif state["stage"] == 1:
        log.debug(f"[AGENT] waiting to detect all cells OFFLINE {len(state['offline'])}/{len(all_cells)} {state['offline']}")
        for p in (p for p in self.peers.cells if p.status == UvnPeerStatus.OFFLINE):
          state["offline"].add(p.name)
        if state["offline"] == all_cells:
          return True
      return False
    spin_start = Timestamp.now()
    self.spin(until=_on_condition_check, max_spin_time=max_spin_time)

    self._stop()

    log.warning(f"[AGENT] applying rekeyed configuration: {self._rekeyed_registry.id}")
    self.registry.save_rekeyed()
    self.registry = self._rekeyed_registry
    self._rekeyed_registry = None
    self.root_vpn = WireGuardInterface(self.registry.root_vpn_config.root_config)

    self._start()

    spin_len = Timestamp.now().subtract(spin_start).total_seconds()
    max_spin_time -= spin_len
    max_spin_time = max(0, max_spin_time)
    self.spin_until_consistent(
      max_spin_time=max_spin_time,
      config_only=config_only)
