from typing import Sequence, Iterable, Optional
from pathlib import Path

import rti.connextdds as dds

from .uvn_id import UvnId, CellId
from .dds import DdsParticipant, UvnTopic
from .deployment import P2PLinksMap
from .ns import Nameserver
from .ip import ipv4_to_bytes, LanDescriptor, ipv4_netmask_to_cidr
from .vpn_config import P2PVpnConfig, CentralizedVpnConfig
from .wg import WireGuardConfig
from .peer_test import UvnPeerLanStatus

def uvn_info(
    participant: DdsParticipant,
    uvn_id: UvnId,
    deployment: P2PLinksMap,
    registry_id: str) -> dds.DynamicData:
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.UVN_ID]])
  sample["id.name"] = uvn_id.name
  sample["id.address"] = uvn_id.address
  sample["cells"] = [] # summarize_peers()
  sample["cell_sites"] = [] # summarize_peer_sites()
  sample["deployment_id"] = deployment.generation_ts
  sample["registry_id"] = registry_id
  return sample

def cell_agent_config(
    participant: DdsParticipant,
    uvn_id: UvnId,
    cell_id: int,
    deployment: P2PLinksMap,
    config_string: str|None=None,
    package: Path|None=None) -> dds.DynamicData:
  cell = uvn_id.cells[cell_id]
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.BACKBONE]])
  sample["cell.name"] = cell.name
  sample["cell.uvn.name"] = uvn_id.name
  sample["cell.uvn.address"] = uvn_id.address
  sample["id"] = deployment.generation_ts
  if config_string is not None:
    sample["config"] = config_string
  elif package:
    with package.open("rb") as input:
      sample["package"] = input.read()
  return sample

def dns_database(
    participant: DdsParticipant,
    uvn_id: UvnId,
    ns: Nameserver,
    server_name: str) -> None:
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.DNS]])
  sample["cell.name"] = server_name
  sample["cell.uvn.name"] = uvn_id.name
  sample["cell.uvn.address"] = uvn_id.address
  db_len = 0
  with sample.loan_value("entries") as entries:
    for i, record in enumerate(ns.db.values()):
      if record.server != server_name:
        continue
      with entries.data.loan_value(i) as entry:
        entry.data["hostname"] = record.hostname
        entry.data["address.value"] = ipv4_to_bytes(record.address)
        entry.data["tags"] = record.tags
        db_len += 1
  return sample


def backbone_peers(
    participant: DdsParticipant,
    uvn_id: UvnId,
    backbone_vpn_config: WireGuardConfig) -> dds.DynamicData:
  peer = uvn_id.cells[backbone_vpn_config.peers[0].id]
  sample = dds.DynamicData(participant.types["uno::CellPeerSummary"])
  sample["name"] = peer.name
  sample["n"] = peer.id
  return sample


def lan_descriptor(
    participant: DdsParticipant,
    net: LanDescriptor,
    cell_id: int=0) -> dds.DynamicData:
  sample = dds.DynamicData(participant.types["uno::CellSiteSummary"])
  sample["cell"] = cell_id
  sample["nic"] = net.nic.name
  sample["subnet.address.value"] = ipv4_to_bytes(net.nic.subnet.network_address)
  sample["subnet.mask"] = ipv4_netmask_to_cidr(net.nic.subnet.netmask)
  sample["endpoint.value"] = ipv4_to_bytes(net.nic.address)
  sample["gw.value"] = ipv4_to_bytes(net.gw)
  return sample


def cell_agent_status(
    participant: DdsParticipant,
    uvn_id: UvnId,
    cell_id: int,
    deployment: P2PLinksMap,
    registry_id: str,
    root_vpn_config: Optional[WireGuardConfig]=None,
    particles_vpn_config: Optional[CentralizedVpnConfig]=None,
    backbone_vpn_configs: Optional[Iterable[WireGuardConfig]]=None,
    lans: Optional[Iterable[LanDescriptor]]=None,
    reachable_sites: Optional[Iterable[UvnPeerLanStatus]]=None,
    unreachable_sites: Optional[Iterable[UvnPeerLanStatus]]=None) -> None:
  import os

  cell = uvn_id.cells[cell_id]
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.CELL_ID]])
  
  sample["id.name"] = cell.name
  sample["id.uvn.name"] = uvn_id.name
  sample["id.uvn.address"] = uvn_id.address
  sample["pid"] = os.getpid()
  sample["status"] = 2 # CELL_STATUS_STARTED
  sample["deployment_id"] = deployment.generation_ts
  sample["registry_id"] = registry_id

  sample["routed_sites"] = [
    lan_descriptor(participant, lan, cell_id)
      for lan in lans or []
  ]

  sample["reachable_sites"] = [
    lan_descriptor(participant, peer_status.lan, peer_status.peer.id)
      for peer_status in reachable_sites
  ]

  sample["unreachable_sites"] = [
    lan_descriptor(participant, peer_status.lan, peer_status.peer.id)
      for peer_status in unreachable_sites
  ]

  if root_vpn_config:
    sample["root_vpn_id"] = root_vpn_config.generation_ts

  if particles_vpn_config and particles_vpn_config.root_config:
    sample["particles_vpn_id"] = particles_vpn_config.root_config.generation_ts
  
  if backbone_vpn_configs:
    sorted_configs = sorted(
      backbone_vpn_configs, key=lambda v: v.intf.port)
    sample["peers"] = [
      backbone_peers(participant, uvn_id, backbone_cfg)
      for backbone_cfg in sorted_configs
    ]
    sample["backbone_vpn_ids"] = [
      cfg.generation_ts for cfg in sorted_configs
    ]
  
  # Fields not in use yet
  sample["ts_created"] = 0
  sample["ts_loaded"] = 0
  sample["ts_started"] = 0
  
  return sample

