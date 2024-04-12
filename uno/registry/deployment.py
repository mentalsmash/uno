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
import ipaddress

from ..core.paired_map import PairedValuesMap
from ..registry.versioned import Versioned


class P2pLinkAllocationMap(PairedValuesMap):
  def __init__(self, subnet: ipaddress.IPv4Network) -> None:
    self.subnet = subnet
    self._next_ip = self.subnet.network_address + 2

  def _allocate_ip(self) -> ipaddress.IPv4Address:
    result = self._next_ip
    if result not in self.subnet:
      raise RuntimeError("exceeded allocated backbone subnet", self.subnet)
    self._next_ip += 1
    return result

  def generate_val(
    self, peer_a: int, peer_b: int
  ) -> tuple[tuple[ipaddress.IPv4Address, ipaddress.IPv4Address], ipaddress.IPv4Network]:
    peer_a_ip = self._allocate_ip()
    peer_b_ip = self._allocate_ip()
    peer_a_net = ipaddress.ip_network(f"{peer_a_ip}/31")
    peer_b_net = ipaddress.ip_network(f"{peer_b_ip}/31", strict=False)
    if peer_a_net != peer_b_net:
      raise RuntimeError(
        "peer addresses not in the same network", (peer_a_ip, peer_a_net), (peer_b_ip, peer_b_net)
      )
    return ((peer_a_ip, peer_b_ip), peer_a_net)


class P2pLinksMap(Versioned):
  PROPERTIES = [
    "peers",
  ]
  REQ_PROPERTIES = [
    "peers",
  ]
  EQ_PROPERTIES = [
    "generation_ts",
  ]
  RO_PROPERTIES = [
    "peers",
  ]

  def prepare_peers(self, val: dict) -> dict:
    return {
      peer_a_id: {
        "n": peer_a["n"],
        "peers": {
          peer_b_id: (
            i,
            ipaddress.ip_address(peer_a_addr),
            ipaddress.ip_address(peer_b_addr),
            ipaddress.ip_network(link_network),
          )
          for peer_b_id, (i, peer_a_addr, peer_b_addr, link_network) in peer_a["peers"].items()
        },
      }
      for peer_a_id, peer_a in (val or {}).items()
    }

  def serialize_peers(self, val: dict, public: bool = False) -> dict:
    return {
      peer_a_id: {
        "n": peer_a["n"],
        "peers": {
          peer_b_id: [i, str(peer_a_addr), str(peer_b_addr), str(link_network)]
          for peer_b_id, (i, peer_a_addr, peer_b_addr, link_network) in peer_a["peers"].items()
        },
      }
      for peer_a_id, peer_a in self.peers.items()
    }

  def get_peers(self, peer_id: int) -> list[int]:
    peer = self.peers.get(peer_id)
    if not peer:
      return []
    return [
      peer_b
      for peer_b, _ in sorted(
        ((peer_b, i) for peer_b, (i, _, _, _) in peer["peers"].items()), key=lambda t: t[1]
      )
    ]

  def get_interfaces(self, peer_id: int) -> list[ipaddress.IPv4Address]:
    peer = self.peers.get(peer_id)
    if not peer:
      return []
    return [addr for _, addr, _, _ in peer["peers"].values()]
