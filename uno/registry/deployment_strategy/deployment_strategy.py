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
from typing import Callable, Sequence
from enum import Enum

from uno.core.paired_map import PairedValuesMap
from uno.registry.versioned import Versioned
from uno.registry.deployment import P2pLinksMap, P2pLinkAllocationMap


class DeploymentStrategyKind(Enum):
  CROSSED = 1
  CIRCULAR = 2
  STATIC = 3
  RANDOM = 4
  FULL_MESH = 5
  # ASYMMETRIC = 3

  @staticmethod
  def parse(val: str) -> "DeploymentStrategyKind":
    return DeploymentStrategyKind[val.upper().replace("-", "_")]


class DeploymentStrategy(Versioned):
  KnownStrategies = {}
  EMPTY_DEPLOYMENT = ([], None, [])
  ALLOW_PRIVATE_PEERS = True
  KIND = None

  PROPERTIES = [
    "uvn",
    "peers",
    "args",
    "private_peers",
    # "public_peers",
  ]
  EQ_PROPERTIES = [
    "KIND",
  ]

  def INITIAL_ARGS(self) -> dict:
    return {}

  def INITIAL_PEERS(self) -> set:
    return set()

  def INITIAL_PRIVATE_PEERS(self) -> set:
    return set()

  def __init_subclass__(cls, *args, **kwargs) -> None:
    if cls.KIND is not None:
      assert DeploymentStrategy.KnownStrategies.get(cls.KIND) is None
      DeploymentStrategy.KnownStrategies[cls.KIND] = cls
    return super().__init_subclass__(*args, **kwargs)

  def prepare_peers(self, val: list[str]) -> set[int]:
    return set(val)

  def prepare_private_peers(self, val: list[int]) -> set[int]:
    return set(val)

  def _validate(self) -> None:
    if not self.ALLOW_PRIVATE_PEERS and self.private_peers:
      raise RuntimeError(
        "strategy requires all peers to be public",
        self.KIND.name,
        {"private": self.private_peers, "public": self.public_peers},
      )

  def __str__(self) -> str:
    return self.KIND.name

  @property
  def public_peers(self) -> set[int]:
    return self.peers - self.private_peers

  def _generate_deployment(
    self,
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    raise NotImplementedError()

  def deploy(
    self, peers: set[int], private_peers: set[int], args: dict, network_map: P2pLinkAllocationMap
  ) -> P2pLinksMap:
    self.peers = peers
    self.private_peers = private_peers
    self.args = args or {}

    self.log.activity("deployment strategy arguments:")
    self.log.activity("- strategy: {}", self)
    self.log.activity("- public peers [{}]: [{}]", len(self.public_peers), self.public_peers)
    self.log.activity("- private peers [{}]: [{}]", len(self.private_peers), self.private_peers)
    self.log.activity("- extra args: {}", self.args)

    deployed_peers, deployed_peers_count, deployed_peers_connections = (
      self._generate_deployment() if len(self.public_peers) > 0 else self.EMPTY_DEPLOYMENT
    )
    peers_map = {
      peer_a: {
        "n": n,
        "peers": {
          peer_b: (
            i,
            PairedValuesMap.pick(peer_a, peer_b, peer_a, link_addresses),
            PairedValuesMap.pick(peer_a, peer_b, peer_b, link_addresses),
            link_network,
          )
          for i in range(deployed_peers_count(n))
          for peer_b_n in [deployed_peers_connections[i](n)]
          if peer_b_n is not None
          for peer_b in [deployed_peers[peer_b_n]]
          for (link_addresses, link_network), _ in [network_map.assert_pair(peer_a, peer_b)]
        },
      }
      for n, peer_a in enumerate(deployed_peers)
    }
    res = self.new_child(P2pLinksMap, {"peers": peers_map})
    return res
