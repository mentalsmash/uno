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

from .uvn_id import UvnId
from .wg import WireGuardInterface
from .dds import DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList
from .render import Templates
from .dds_data import uvn_info, cell_agent_config
from .agent_net import AgentNetworking
from .agent import Agent
from .vpn_config import P2PLinksMap
from .log import Logger as log


class RegistryAgent(Agent):
  DDS_CONFIG_TEMPLATE = "uno.xml"

  def __init__(self, registry: Registry) -> None:
    if not registry.deployed:
      raise ValueError("uvn not deployed", registry)

    self.registry = registry
    self.root_vpn_config = self.registry.root_vpn_config.root_config
    self.root_vpn = WireGuardInterface(self.root_vpn_config)

    self._peers = UvnPeersList(
      uvn_id=self.registry.uvn_id,
      local_peer_id=0)

    self._net = AgentNetworking(
      root=True,
      config_dir=self.config_dir,
      vpn_interfaces=self.vpn_interfaces)
  
    super().__init__()


  @property
  def registry_id(self) -> str:
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
  def dds_config(self) -> DdsParticipantConfig:
    if not self.registry.rti_license.is_file():
      log.error(f"RTI license file not found: {self.registry.rti_license}")
      raise RuntimeError("RTI license file not found")

    xml_config_tmplt = Templates.compile(
      DdsParticipantConfig.load_config_template(self.DDS_CONFIG_TEMPLATE))

    xml_config = Templates.render(xml_config_tmplt, {
      "deployment_id": self.registry.backbone_vpn_config.deployment.generation_ts,
      "uvn": self.registry.uvn_id,
      "cell": None,
      "initial_peers": [p.address for p in self.root_vpn_config.peers],
      "timing": self.registry.uvn_id.settings.timing_profile,
      "license_file": self.registry.rti_license.read_text(),
      "ca_cert": self.registry.dds_keymat.ca.cert,
      "perm_ca_cert": self.registry.dds_keymat.perm_ca.cert,
      "cert": self.registry.dds_keymat.cert("root"),
      "key": self.registry.dds_keymat.cert("key"),
      "governance": self.registry.dds_keymat.governance,
      "permissions": self.registry.dds_keymat.permissions("root"),
      "enable_dds_security": False,
    })

    return DdsParticipantConfig(
      participant_xml_config=xml_config,
      participant_profile=DdsParticipantConfig.PARTICIPANT_PROFILE_ROOT,
      user_conditions=[
        self.peers.updated_condition,
      ],
      **Registry.AGENT_REGISTRY_TOPICS)


  def _start_services(self, boot: bool=False) -> None:
    self._write_uvn_info()
    self._write_backbone()


  def _write_uvn_info(self) -> None:
    sample = uvn_info(
      participant=self.dp,
      uvn_id=self.registry.uvn_id,
      deployment=self.registry.backbone_vpn_config.deployment,
      registry_id=self.registry_id)
    self.dp.writers[UvnTopic.UVN_ID].write(sample)
    log.activity(f"[AGENT] published uvn info: {self}")


  def _write_backbone(self):
    cells_dir = self.registry.root / "cells"
    for cell_id in self.registry.backbone_vpn_config.deployment.peers:
      cell = self.registry.uvn_id.cells[cell_id]
      config_file = cells_dir / f"{cell.name}.yaml"
      config_str = config_file.read_text()
      sample = cell_agent_config(
        participant=self.dp,
        uvn_id=self.registry.uvn_id,
        cell_id=cell.id,
        deployment=self.registry.backbone_vpn_config.deployment,
        config_string=config_str)
      self.dp.writers[UvnTopic.BACKBONE].write(sample)
      log.activity(f"[AGENT] published agent configuration: {cell}")

