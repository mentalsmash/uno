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
from functools import partial
import random
from typing import Callable, Sequence, Iterable

from .deployment_strategy import DeploymentStrategyKind
from .static_deployment_strategy import StaticDeploymentStrategy


class CrossedDeploymentStrategy(StaticDeploymentStrategy):
  KIND = DeploymentStrategyKind.CROSSED
  ALLOW_PRIVATE_PEERS = True

  def _peer_right(self, peer_i: int, peer_count: int) -> int:
    assert peer_i >= 0
    assert peer_i < peer_count
    # Return peer the right (modulo count)
    return (peer_i + 1) % peer_count

  def _peer_left(self, peer_i: int, peer_count: int) -> int:
    assert peer_i >= 0
    assert peer_i < peer_count
    # Return the peer to the left (modulo count)
    if peer_i == 0:
      return peer_count - 1
    else:
      return peer_i - 1

  def _peer_across(self, peer_i: int, peer_count: int) -> int:
    # Return peer "opposite" to this one, i.e.
    # with index: current.n + floor(len(cells)/2)
    offset = peer_count // 2
    if peer_i <= (offset - 1):
      return (peer_i + offset) % peer_count
    else:
      return peer_i - offset

  def _generate_deployment_all_public(
    self, public_peers: Iterable[int]
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    # assert(not self.private_peers)
    peer_count = len(public_peers)

    peer_ids = list(public_peers)
    random.shuffle(peer_ids)

    def peer_peers_count(cell_i: int) -> int:
      assert peer_count >= 2
      if peer_count == 2:
        return 1
      elif peer_count == 3:
        return 2
      elif not peer_count % 2 > 0 or not cell_i == peer_count - 1:
        return 3
      else:
        return 2

    return (
      peer_ids,
      peer_peers_count,
      [
        # 1st peer
        partial(self._peer_left, peer_count=peer_count),
        # 2nd peer
        partial(self._peer_right, peer_count=peer_count),
        # 3rd peer
        partial(self._peer_across, peer_count=peer_count),
      ],
    )

  def _generate_deployment(
    self,
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    if len(self.public_peers) > 1:
      public_peers_id, pub_peers_peers_count, pub_peers_peer_generators = (
        self._generate_deployment_all_public(self.public_peers)
      )
      if not self.private_peers:
        return public_peers_id, pub_peers_peers_count, pub_peers_peer_generators
    else:
      public_peers_id = [next(iter(self.public_peers))]

    private_peers_id = list(self.private_peers)
    random.shuffle(private_peers_id)
    peer_ids = [*public_peers_id, *private_peers_id]

    if len(self.private_peers) >= len(self.public_peers):
      # partition_size, remaining = floor(len(self.private_peers) / len(self.public_peers))
      partition_size, remaining = divmod(len(self.private_peers), len(self.public_peers))

      priv_partition_sizes = [partition_size for i in range(len(self.public_peers))]

      # for i in range(len(self.private_peers) - (len(self.public_peers)*partition_size)):
      for i in range(remaining):
        # partition_i = i % len(self.public_peers)
        # priv_partition_sizes[partition_i] += 1
        priv_partition_sizes[i] += 1
    else:
      # More public peers than private ones
      priv_partition_sizes = [
        *(1 for i in range(len(self.private_peers))),
        *(0 for i in range(len(self.public_peers) - len(self.private_peers))),
      ]

    priv_i = 0
    peer_ports = {}
    for pub_i, pub_peer in enumerate(peer_ids[: len(self.public_peers)]):
      partition_size = priv_partition_sizes[pub_i]
      pub_peer_ports = peer_ports[pub_peer] = peer_ports.get(pub_peer, set())

      if len(self.public_peers) > 1:
        pub_peer_peers_count = pub_peers_peers_count(pub_i)
        assert pub_peer_peers_count > 0
        assert pub_peer_peers_count <= 3

        pub_peer_peers = [
          port_peer
          for port_i in range(pub_peer_peers_count)
          for port_peer in [pub_peers_peer_generators[port_i](pub_i)]
          if port_peer is not None
        ]
        assert len(pub_peer_peers) > 0
        for peer_i in pub_peer_peers:
          pub_peer_ports.add(peer_ids[peer_i])

      partition_start = len(self.public_peers) + priv_i
      priv_peers = peer_ids[partition_start : partition_start + partition_size]

      for priv_peer in priv_peers:
        priv_peer_ports = peer_ports[priv_peer] = peer_ports.get(priv_peer, set())
        pub_peer_ports.add(priv_peer)
        priv_peer_ports.add(pub_peer)

      priv_i += partition_size

    self.static_deployment = tuple((peer, tuple(peer_ports[peer])) for peer in peer_ids)
    return super()._generate_deployment()
