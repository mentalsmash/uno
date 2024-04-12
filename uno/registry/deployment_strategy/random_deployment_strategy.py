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
import random
from typing import Callable, Sequence, Iterable

from .deployment_strategy import DeploymentStrategyKind
from .static_deployment_strategy import StaticDeploymentStrategy


class IncompleteSpanTree(Exception):
  def __init__(self, span_tree, *args: object) -> None:
    self.span_tree = span_tree
    super().__init__(*args)


class RandomDeploymentGraph:
  def __init__(
    self,
    peers: Iterable[int],
    min_peer_edges: int,
    ok_peer_edges: int,
    max_peer_edges: int,
    private_peers: Iterable[int] | None = None,
  ) -> None:
    self.min_peer_edges = min_peer_edges
    self.ok_peer_edges = ok_peer_edges
    self.max_peer_edges = max_peer_edges
    self.peers = set(peers)
    self.private_peers = set(private_peers or [])
    self.public_peers = self.peers - self.private_peers
    self.peer_edges = {p: set() for p in self.peers}
    self.full_peers = set()
    self.ok_peers = set()
    self.min_peers = set()

  def _store_edge(self, a: int, b: int) -> None:
    def _update_peer_status(p: int, p_edges: list[int]) -> None:
      if len(p_edges) >= self.max_peer_edges:
        if p in self.ok_peers:
          self.ok_peers.remove(p)
        if p in self.min_peers:
          self.min_peers.remove(p)
        self.full_peers.add(p)
      elif len(p_edges) >= self.ok_peer_edges:
        self.ok_peers.add(p)
        if p in self.min_peers:
          self.min_peers.remove(p)
      elif len(p_edges) >= self.min_peer_edges:
        self.min_peers.add(p)

    a_edges = self.peer_edges[a] = self.peer_edges.get(a, set())
    b_edges = self.peer_edges[b] = self.peer_edges.get(b, set())
    if len(a_edges) < self.max_peer_edges and len(b_edges) < self.max_peer_edges:
      a_edges.add(b)
      _update_peer_status(a, a_edges)
      b_edges.add(a)
      _update_peer_status(b, b_edges)

  def _generate_new_spanning_tree(self, private_first: bool = False, public_first: bool = False):
    visited = set()
    edges = list()

    def _pick_random(peers: Iterable[int] | None) -> tuple[int, bool]:
      peer = random.sample(list(peers), 1).pop()
      peer_public = peer in self.public_peers
      return peer, peer_public

    def _pick_random_neighbor(current_public: bool = False) -> tuple[int, bool]:
      # if not current_public:
      #   neighbors = self.public_peers - visited
      # else:
      #   if public_first:
      #     neighbors = self.public_peers - visited
      #   elif private_first:
      #     neighbors = self.private_peers - visited
      #     if not neighbors:
      #       neighbors = self.peers - visited
      #   else:
      #     neighbors = self.peers - visited
      if not current_public:
        neighbors = self.public_peers - visited
      else:
        neighbors = self.peers - visited
      if not neighbors:
        raise IncompleteSpanTree(edges)
      return _pick_random(neighbors)

    current, current_public = _pick_random(self.peers)
    visited.add(current)
    while len(visited) < len(self.peers):
      other, other_public = _pick_random_neighbor(current_public)
      assert current_public or other_public
      visited.add(other)
      edges.append((current, other))
      current = other
      current_public = other_public

    return edges

  def generate_edges(self, max_tries: int = 100000) -> None:
    validate = False
    for i in range(max_tries):
      try:
        span_tree = self._generate_new_spanning_tree()
        for edge in span_tree:
          self._store_edge(*edge)
        # Stop early if all peers have at least "min" edges
        if len(self.ok_peers) + len(self.full_peers) >= len(self.peers):
          validate = True
          return
      except IncompleteSpanTree as e:

        def test_partial() -> bool:
          return len(self.ok_peers) + len(self.full_peers) + len(self.min_peers) >= len(self.peers)

        if len(self.private_peers) >= len(self.public_peers):
          # With more private peers then public peers, there is not span tree,
          # so cache intermediate results and continue
          for edge in e.span_tree:
            self._store_edge(*edge)
          if test_partial():
            return

        if i < max_tries - 1:
          continue

        if test_partial():
          return
        self.log.error("Failed to generate a backbone deployment with the 'random' strategy.")
        self.log.error(
          "You can try to run this command again, and it is possible that the generation will succeeed."
        )
        self.log.error("If it continues to fail, adjust the min/ok/max parameters.")
        self.log.error(
          "In the worst case, you might have to define the deployment manually using the 'static' strategy."
        )
        import pprint

        self.log.warning("Allocated peer links: {}", pprint.pformat(self.peer_edges))
        self.log.warning("{}", pprint.pformat(self.peer_edges))
        self.log.warning(
          "- min: {}, ok: {}, max: {}", self.min_peer_edges, self.ok_peer_edges, self.max_peer_edges
        )
        self.log.warning("- public peers [{}] = {}", len(self.public_peers), self.public_peers)
        self.log.warning("- private peers [{}] = {}", len(self.private_peers), self.private_peers)
        self.log.warning("- min peers [{}] = {}", len(self.min_peers), self.min_peers)
        self.log.warning("- ok peers [{}] = {}", len(self.ok_peers), self.ok_peers)
        self.log.warning("- max peers [{}] = {}", len(self.full_peers), self.full_peers)
        raise RuntimeError("failed to generate requested edges")
      finally:
        if validate:
          assert len(self.ok_peers & self.full_peers) == 0
          assert len(self.ok_peers & self.min_peers) == 0
          assert len(self.full_peers & self.min_peers) == 0


class RandomDeploymentStrategy(StaticDeploymentStrategy):
  KIND = DeploymentStrategyKind.RANDOM

  def _generate_deployment(
    self,
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    peers_count = len(self.peers)
    if peers_count <= 1:
      min_peers = 0
      ok_peers = 0
      max_peers = 0
    elif peers_count <= 3:
      min_peers = 1
      ok_peers = peers_count - 1
      max_peers = peers_count
    else:
      min_peers = 1
      ok_peers = 2
      public_count = len(self.public_peers)
      private_count = len(self.private_peers)
      max_peers = 3
      if public_count < private_count:
        max_peers = 3 + private_count - public_count

    if max(max_peers, min_peers, ok_peers) != max_peers:
      raise RuntimeError("invalid max_peers setting", max_peers, min_peers, ok_peers)
    if min(max_peers, min_peers, ok_peers) != min_peers:
      raise RuntimeError("invalid min_peers setting")
    if ok_peers > max_peers or ok_peers < min_peers:
      raise RuntimeError("invalid ok_peers setting")

    self.min_peer_edges = min_peers
    self.ok_peer_edges = ok_peers
    self.max_peer_edges = max_peers

    graph = RandomDeploymentGraph(
      peers=self.peers,
      min_peer_edges=self.min_peer_edges,
      ok_peer_edges=self.ok_peer_edges,
      max_peer_edges=self.max_peer_edges,
      private_peers=self.private_peers,
    )
    graph.generate_edges()

    self.static_deployment = tuple((p, tuple(peers)) for p, peers in graph.peer_edges.items())
    return super()._generate_deployment()
