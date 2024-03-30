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
from typing import Generator, TYPE_CHECKING

from ..core.wg import WireGuardInterface
from ..registry.lan_descriptor import LanDescriptor
import ipaddress

if TYPE_CHECKING:
  from .uvn_peers_list import UvnPeersList
  from .uvn_peer import UvnPeer
  from .uvn_peers_tester import UvnPeersTester


def _filter_find_lan_status_by_peer(peer_id: int, peers_tester: "UvnPeersTester") -> list[tuple[LanDescriptor, bool]]:
  return peers_tester.find_status_by_peer(peer_id)


def _filter_find_backbone_peer_by_address(addr: str, peers: "UvnPeersList", backbone_vpns: list[WireGuardInterface]) -> "UvnPeer | None":
  if not addr:
    return None
  addr = ipaddress.ip_address(addr)
  for bbone in backbone_vpns:
    if bbone.config.peers[0].address == addr:
      return peers[bbone.config.peers[0].id]
    elif bbone.config.intf.address == addr:
      return peers.local
  return None


def _filter_sort_peers(val: "UvnPeersList", enable_particles: bool=True) -> "Generator[UvnPeer, None, None]":
  enable_particles = bool(enable_particles)
  def peer_type_id(v: "UvnPeer"):
    return (
      0 if v.registry else
      1 if v.cell else
      2
    )
  for p in sorted(val, key=lambda v: (peer_type_id(v), v.id)):
    if not enable_particles and p.particle:
      continue
    yield p

from ..core.render import Templates
Templates.registry_filters(
  find_lan_status_by_peer=_filter_find_lan_status_by_peer,
  find_backbone_peer_by_address=_filter_find_backbone_peer_by_address,
  sort_peers=_filter_sort_peers)

