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
from typing import  Optional, Callable

from .wg import WireGuardInterface
from .ip import LanDescriptor
from .dds import DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer
from .render import Templates
from .dds_data import uvn_info, cell_agent_config
from .agent_svc import AgentServices

from .log import Logger as log


class RegistryAgent:
  DDS_CONFIG_TEMPLATE = "uno.xml"

  def __init__(self, registry: Registry) -> None:
    if not registry.deployed:
      raise ValueError("uvn not deployed", registry)

    self.registry = registry
    self.root_vpn_config = self.registry.root_vpn_config.root_config
    self.root_vpn = WireGuardInterface(self.root_vpn_config)

    self.peers = UvnPeersList(
      uvn_id=self.registry.uvn_id,
      local_peer_id=0)

    self._services = AgentServices(peers=self.peers)


  @property
  def uvn_consistent_config(self) -> bool:
    return len(self.consistent_config_peers) == len(self.registry.uvn_id.cells)


  @property
  def consistent_config_peers(self) -> set[UvnPeer]:
    return set(
      p for p in self.peers
        # Mark peers as consistent if they are at the expected configuration IDs
        if p.cell
          and p.deployment_id == self.registry.backbone_vpn_config.deployment.generation_ts
          and p.root_vpn_id == self.registry.root_vpn_config.peer_configs[p.id].generation_ts
          and p.particles_vpn_id == self.registry.particles_vpn_configs[p.id].root_config.generation_ts
          and next((cfg_id for i, cfg_id in enumerate(p.backbone_vpn_ids)
              if cfg_id != self.registry.backbone_vpn_config.peer_configs[p.id][i].generation_ts), None) is None
    )


  @property
  def inconsistent_config_peers(self) -> set[UvnPeer]:
    return set(self.peers) - self.consistent_config_peers


  @property
  def uvn_routed_sites(self) -> set[LanDescriptor]:
    return {
      s
      for peer in self.peers if peer.cell
        for s in peer.routed_sites
    }


  @property
  def connected_peers(self) -> set[UvnPeer]:
    routed_sites = self.uvn_routed_sites
    if len(routed_sites) == 0:
      return set()
    return {
      p for p in self.peers if p.reachable_sites == routed_sites
    }


  @property
  def disconnected_peers(self) -> set[UvnPeer]:
    return set(self.peers) - self.connected_peers


  @property
  def uvn_consistent(self) -> bool:
    if not self.uvn_consistent_config:
      return False
    return len(self.connected_peers) != len(self.registry.uvn_id.cells)


  def _write_uvn_info(self) -> None:
    sample = uvn_info(
      participant=self._services.dds,
      uvn_id=self.registry.uvn_id,
      deployment=self.registry.backbone_vpn_config.deployment)
    self._services.dds.writers[UvnTopic.UVN_ID].write(sample)
    log.activity(f"[AGENT] published uvn info: {self}")


  def _write_backbone(self):
    cells_dir = self.registry.root / "cells"
    for cell_id in self.registry.backbone_vpn_config.deployment.peers:
      cell = self.registry.uvn_id.cells[cell_id]
      config_file = cells_dir / f"{cell.name}.yaml"
      config_str = config_file.read_text()
      sample = cell_agent_config(
        participant=self._services.dds,
        uvn_id=self.registry.uvn_id,
        cell_id=cell.id,
        deployment=self.registry.backbone_vpn_config.deployment,
        config_string=config_str)
      self._services.dds.writers[UvnTopic.BACKBONE].write(sample)


  def spin_until_consistent(self,
      max_spin_time: Optional[int]=None,
      config_only: bool=False) -> None:
    spin_state = {
      "consistent_config": False
    }
    deployment = self.registry.backbone_vpn_config.deployment
    def _until_consistent() -> bool:
      if not spin_state["consistent_config"] and self.uvn_consistent_config:
        spin_state["consistent_config"] = True
        log.warning(f"[AGENT] all {len(self.consistent_config_peers)} UVN agents have consistent configuration:")
        for peer_a_id, peer_a in sorted(deployment.peers.items(), key=lambda t: t[1]["n"]):
          peer_a_cell = self.registry.uvn_id.cells[peer_a_id]
          for peer_b_id, (peer_b_port_i, peer_a_addr, peer_b_addr, link_network) in sorted(peer_a["peers"].items(), key=lambda t: t[1][0]):
            peer_b_cell = self.registry.uvn_id.cells[peer_b_id]
            log.warning(f"[AGENT] backbone[{peer_a['n']}][{peer_b_port_i}]: {peer_a_cell} ({peer_a_addr}) => {peer_b_cell} ({peer_b_addr})")
        if config_only:
          return True
      if self.uvn_consistent:
        routed_sites = self.uvn_routed_sites
        peers = self.consistent_config_peers
        log.warning(f"[AGENT] UVN is consistent with {len(routed_sites)} LANs routed by {len(peers)} agents:")
        for s in routed_sites:
          log.warning(f"[AGENT] - {s}")
        return True
      if not spin_state["consistent_config"]:
        log.debug(f"[AGENT] still waiting for all UVN agents to reach expected configuration")
      else:
        log.debug(f"[AGENT] still waiting for UVN to become consistent")
    
    timedout = self.spin(until=_until_consistent, max_spin_time=max_spin_time)
    if timedout:
      raise RuntimeError("UVN failed to reach expected state before timeout")



  def spin(self,
      until: Optional[Callable[[], bool]]=None,
      max_spin_time: Optional[int]=None) -> None:
    xml_config_tmplt = Templates.compile(
      DdsParticipantConfig.load_config_template(self.DDS_CONFIG_TEMPLATE))
    
    xml_config = Templates.render(xml_config_tmplt, {
      "deployment_id": self.registry.backbone_vpn_config.deployment.generation_ts,
      "uvn": self.registry.uvn_id,
      "cell": None,
      "initial_peers": [p.address for p in self.root_vpn_config.peers],
      "timing": self.registry.uvn_id.settings.timing_profile,
    })

    writers = [
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
      UvnTopic.DNS,
    ]

    readers = {
      UvnTopic.CELL_ID: {
        "query": "id.uvn.name MATCH %0",
        "params": [
          f"'{self.registry.uvn_id.name}'"
        ],
      },
      UvnTopic.DNS: {
        "query": "cell.uvn.name MATCH %0",
        "params": [
          f"'{self.registry.uvn_id.name}'"
        ]
      },
    }

    dds_config = DdsParticipantConfig(
      participant_xml_config=xml_config,
      participant_profile=DdsParticipantConfig.PARTICIPANT_PROFILE_ROOT,
      writers=writers,
      readers=readers)


    try:
      self._services.start(
        dds_config=dds_config,
        lans=[],
        vpn_interfaces=[self.root_vpn])
      self.peers.update_peer(self.peers.local_peer,
        status=UvnPeerStatus.ONLINE)
      self._write_uvn_info()
      self._write_backbone()
      self._services.spin(
        until=until,
        max_spin_time=max_spin_time)
    finally:
      self.peers.update_peer(self.peers.local_peer,
        status=UvnPeerStatus.OFFLINE)
      self._services.stop()
