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
from typing import Iterable, Optional
from pathlib import Path

import rti.connextdds as dds

from .dds import DdsParticipant
from ..core.ip import ipv4_to_bytes, ipv4_netmask_to_cidr
from ..core.time import Timestamp
from ..registry.dds import UvnTopic
from ..registry.uvn import Uvn
from ..registry.lan_descriptor import LanDescriptor


def uvn_info(
    participant: DdsParticipant,
    uvn: Uvn,
    registry_id: str) -> dds.DynamicData:
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.UVN_ID]])
  sample["name"] = uvn.name
  sample["registry_id"] = registry_id
  return sample


def cell_agent_config(
    participant: DdsParticipant,
    uvn: Uvn,
    cell_id: int,
    registry_id: str,
    config_string: str|None=None,
    package: Path|None=None) -> dds.DynamicData:
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.BACKBONE]])
  sample["cell.n"] = cell_id
  sample["cell.uvn"] = uvn.name
  sample["registry_id"] = registry_id
  if config_string is not None:
    sample["config"] = config_string
  elif package:
    with package.open("rb") as input:
      sample["package"] = input.read()
  return sample


def lan_descriptor(
    participant: DdsParticipant,
    net: LanDescriptor) -> dds.DynamicData:
  sample = dds.DynamicData(participant.types["uno::NetworkInfo"])
  sample["nic"] = net.nic.name
  sample["subnet.address.value"] = ipv4_to_bytes(net.nic.subnet.network_address)
  sample["subnet.mask"] = ipv4_netmask_to_cidr(net.nic.subnet.netmask)
  sample["endpoint.value"] = ipv4_to_bytes(net.nic.address)
  sample["gw.value"] = ipv4_to_bytes(net.gw)
  return sample


def cell_agent_status(
    participant: DdsParticipant,
    uvn: Uvn,
    cell_id: int,
    registry_id: str,
    ts_start: Timestamp|None=None,
    lans: Optional[Iterable[LanDescriptor]]=None,
    reachable_networks: Optional[Iterable[LanDescriptor]]=None,
    unreachable_networks: Optional[Iterable[LanDescriptor]]=None) -> None:
  import os

  cell = uvn.cells[cell_id]
  sample = dds.DynamicData(participant.types[participant.TOPIC_TYPES[UvnTopic.CELL_ID]])
  
  sample["id.n"] = cell.id
  sample["id.uvn"] = uvn.name

  sample["registry_id"] = registry_id

  sample["routed_networks"] = [
    lan_descriptor(participant, lan)
      for lan in lans or []
  ]

  sample["reachable_networks"] = [
    lan_descriptor(participant, lan)
      for lan in reachable_networks
  ]

  sample["unreachable_networks"] = [
    lan_descriptor(participant, lan)
      for lan in unreachable_networks
  ]

  if ts_start is not None:
    sample["ts_start"] = ts_start.from_epoch()

  return sample

