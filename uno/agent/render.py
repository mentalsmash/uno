###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from typing import Generator, TYPE_CHECKING
import ipaddress

from ..core.wg import WireGuardInterface
from ..registry.lan_descriptor import LanDescriptor
from ..core.render import Templates

if TYPE_CHECKING:
  from .uvn_peers_list import UvnPeersList
  from .uvn_peer import UvnPeer
  from .uvn_peers_tester import UvnPeersTester


def _filter_find_lan_status_by_peer(
  peer_id: int, peers_tester: "UvnPeersTester"
) -> list[tuple[LanDescriptor, bool]]:
  return peers_tester.find_status_by_peer(peer_id)


def _filter_find_backbone_peer_by_address(
  addr: str, peers: "UvnPeersList", backbone_vpns: list[WireGuardInterface]
) -> "UvnPeer | None":
  if not addr:
    return None
  addr = ipaddress.ip_address(addr)
  for bbone in backbone_vpns:
    if bbone.config.peers[0].address == addr:
      return peers[bbone.config.peers[0].id]
    elif bbone.config.intf.address == addr:
      return peers.local
  return None


def _filter_sort_peers(
  val: "UvnPeersList", enable_particles: bool = True
) -> "Generator[UvnPeer, None, None]":
  enable_particles = bool(enable_particles)

  def peer_type_id(v: "UvnPeer"):
    return 0 if v.registry else 1 if v.cell else 2

  for p in sorted(val, key=lambda v: (peer_type_id(v), v.id)):
    if not enable_particles and p.particle:
      continue
    yield p


Templates.registry_filters(
  find_lan_status_by_peer=_filter_find_lan_status_by_peer,
  find_backbone_peer_by_address=_filter_find_backbone_peer_by_address,
  sort_peers=_filter_sort_peers,
)
