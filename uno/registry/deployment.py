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
from typing import Tuple, Callable, Sequence, Optional, Iterable
from enum import Enum

import ipaddress

from ..core.paired_map import PairedValuesMap
from ..core.time import Timestamp
from ..core.log import Logger as log
from ..registry.versioned import Versioned

class P2PLinkAllocationMap(PairedValuesMap):
  def __init__(self,subnet: ipaddress.IPv4Network) -> None:
    self.subnet = subnet
    self._next_ip = self.subnet.network_address + 2

  def _allocate_ip(self) -> ipaddress.IPv4Address:
    result = self._next_ip
    if result not in self.subnet:
      raise RuntimeError("exceeded allocated backbone subnet", self.subnet)
    self._next_ip += 1
    return result

  def generate_val(self, peer_a: int, peer_b: int) -> Tuple[Tuple[ipaddress.IPv4Address, ipaddress.IPv4Address], ipaddress.IPv4Network]:
    peer_a_ip = self._allocate_ip()
    peer_b_ip = self._allocate_ip()
    peer_a_net = ipaddress.ip_network(f"{peer_a_ip}/31")
    peer_b_net = ipaddress.ip_network(f"{peer_b_ip}/31", strict=False)
    if peer_a_net != peer_b_net:
      raise RuntimeError("peer addresses not in the same network",
        (peer_a_ip, peer_a_net), (peer_b_ip, peer_b_net))
    return ((peer_a_ip, peer_b_ip), peer_a_net)


class P2PLinksMap(Versioned):
  PROPERTIES = [
    "peers",
  ]
  REQ_PROPERTIES = [
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
            ipaddress.ip_network(link_network))
            for peer_b_id, (i, peer_a_addr, peer_b_addr, link_network) in peer_a["peers"].items()
        }
      } for peer_a_id, peer_a in (val or {}).items()
    }


  def serialize_peers(self, val: dict) -> dict:
    return {
      peer_a_id: {
        "n": peer_a["n"],
        "peers": {  
          peer_b_id: [i, str(peer_a_addr), str(peer_b_addr), str(link_network)]  
            for peer_b_id, (i, peer_a_addr, peer_b_addr, link_network) in peer_a["peers"].items()
        }
      } for peer_a_id, peer_a in self.peers.items()
    }


  def get_peers(self, peer_id: int) -> list[int]:
    peer = self.peers.get(peer_id)
    if not peer:
      return []
    return [
      peer_b
      for peer_b, _ in
        sorted(((peer_b, i) for peer_b, (i, _, _, _) in peer["peers"].items()), key=lambda t: t[1])
    ]



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
  EMPTY_DEPLOYMENT = ([], None, [])
  ALLOW_PRIVATE_PEERS = True
  KIND = None

  PROPERTIES = [
    "peers",
    "args",
    "private_peers",
    "public_peers",

  ]
  REQ_PROPERTIES = [
    "peers",
  ]
  INITIAL_ARGS = lambda self: {}
  INITIAL_PRIVATE_PEERS = lambda self: set()
  INITIAL_PUBLIC_PEERS = lambda self: self.peers - self.private_peers

  def prepare_peers(self, val: list[str]) -> set[int]:
    return set(val)


  def prepare_private_peers(self, val: list[int]) -> set[int]:
    return set(val)


  def validate_new(self) -> None:
    if not self.ALLOW_PRIVATE_PEERS and self.private_peers:
      raise RuntimeError("strategy requires all peers to be public",
        self.KIND.name, {"private": self.private_peers, "public": self.public_peers})


  def __str__(self) -> str:
    return self.KIND.name


  def _generate_deployment(self)  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    raise NotImplementedError()


  def deploy(self, network_map: P2PLinkAllocationMap) -> P2PLinksMap:
    deployed_peers, deployed_peers_count, deployed_peers_connections = (
      self._generate_deployment() if len(self.public_peers) > 0 else
      self.EMPTY_DEPLOYMENT
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
              for peer_b_n in [deployed_peers_connections[i](n)] if peer_b_n is not None
                for peer_b in [deployed_peers[peer_b_n]]
                  for (link_addresses, link_network), _ in [network_map.assert_pair(peer_a, peer_b)]
        },
      } for n, peer_a in enumerate(deployed_peers)
    }
    return self.new_child(P2PLinksMap, peers=peers_map)


class StaticDeploymentStrategy(DeploymentStrategy):
  PROPERTIES = ["static_deployment"]

  INITIAL_STATIC_DEPLOYMENT = lambda self: tuple(
    (p, tuple(peers))
      for p, peers in self.args.get("peers_map", []))


  def _generate_deployment(self)  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    if not self.static_deployment:
      log.warning("[STATIC-STRATEGY] no configuration specified, the deployment will be empty.")
      return self.EMPTY_DEPLOYMENT

    peer_ids = [id for id, _ in self.static_deployment]

    def cell_peers_count(n: int) -> int:
      _, cell_peers = self.static_deployment[n]
      return len(cell_peers)
    
    peers_counts = list(map(cell_peers_count, range(len(peer_ids))))
    max_peers_count = max(peers_counts or [0])

    def _mk_peer_generator(peer_b_i: int):
      def _peer_generator(peer_a_i: int) -> Optional[int]:
        try:
          res = self.static_deployment[peer_a_i]
        except IndexError:
          log.warning(f"[STATIC-STRATEGY] unknown peer ({peer_a_i}) detected for link: {peer_a_i} → {peer_b_i}")
          return None
        peer_id, static_peers = res
        res = static_peers[peer_b_i]
        try:
          return peer_ids.index(res)
        except ValueError:
          log.warning(f"[STATIC-STRATEGY] unknown peer ({peer_b_i})")
      return _peer_generator

    peer_generators = [
      _mk_peer_generator(i) for i in range(max_peers_count)
    ]
    return (peer_ids, cell_peers_count, peer_generators)


class CrossedDeploymentStrategy(StaticDeploymentStrategy):
  KIND = DeploymentStrategyKind.CROSSED
  ALLOW_PRIVATE_PEERS = True

  def _peer_right(self, peer_i: int, peer_count: int) -> int:
    assert(peer_i >= 0)
    assert(peer_i < peer_count)
    # Return peer the right (modulo count)
    return (peer_i + 1) % peer_count

  def _peer_left(self, peer_i: int, peer_count: int) -> int:
    assert(peer_i >= 0)
    assert(peer_i < peer_count)
    # Return the peer to the left (modulo count)
    if peer_i == 0:
      return peer_count - 1
    else:
      return peer_i - 1

  def _peer_across(self, peer_i: int, peer_count: int) -> int:
    # Return peer "opposite" to this one, i.e.
    # with index: current.n + floor(len(cells)/2)
    offset = (peer_count // 2)
    if peer_i <= (offset - 1):
      return (peer_i + offset) % peer_count
    else:
      return peer_i - offset


  def _generate_deployment_all_public(self, public_peers: Iterable[int])  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    # assert(not self.private_peers)
    peer_count = len(public_peers)

    peer_ids = list(public_peers)
    random.shuffle(peer_ids)

    def peer_peers_count(cell_i: int) -> int:
      assert(peer_count >= 2)
      if peer_count == 2:
        return 1
      elif peer_count == 3:
        return 2
      elif not peer_count % 2 > 0 or not cell_i == peer_count - 1:
        return 3
      else:
        return 2
    
    return (peer_ids, peer_peers_count, [
      # 1st peer
      partial(self._peer_left, peer_count=peer_count),
      # 2nd peer
      partial(self._peer_right, peer_count=peer_count),
      # 3rd peer
      partial(self._peer_across, peer_count=peer_count),
    ])


  def _generate_deployment(self)  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    if len(self.public_peers) > 1:
      public_peers_id, pub_peers_peers_count, pub_peers_peer_generators = self._generate_deployment_all_public(self.public_peers)
      if not self.private_peers:
        return public_peers_id, pub_peers_peers_count, pub_peers_peer_generators
    else:
      public_peers_id = [next(iter(self.public_peers))]

    private_peers_id = list(self.private_peers)
    random.shuffle(private_peers_id)
    peer_ids = [*public_peers_id, *private_peers_id]

    if len(self.private_peers) >= len(self.public_peers):
      from math import floor
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
        *(0 for i in range(len(self.public_peers) - len(self.private_peers)))
      ]

    priv_i = 0
    peer_ports = {}
    for pub_i, pub_peer in enumerate(peer_ids[:len(self.public_peers)]):
      partition_size = priv_partition_sizes[pub_i]
      pub_peer_ports = peer_ports[pub_peer] = peer_ports.get(pub_peer, set())

      if len(self.public_peers) > 1:
        pub_peer_peers_count = pub_peers_peers_count(pub_i)
        assert(pub_peer_peers_count > 0)
        assert(pub_peer_peers_count <= 3)

        pub_peer_peers = [
          port_peer
            for port_i in range(pub_peer_peers_count)
              for port_peer in [pub_peers_peer_generators[port_i](pub_i)]
                if port_peer is not None
        ]
        assert(len(pub_peer_peers) > 0)
        for peer_i in pub_peer_peers:
          pub_peer_ports.add(peer_ids[peer_i])

      partition_start = len(self.public_peers) + priv_i
      priv_peers = peer_ids[partition_start:partition_start+partition_size]
      
      for priv_peer in priv_peers:
        priv_peer_ports = peer_ports[priv_peer] = peer_ports.get(priv_peer, set())
        pub_peer_ports.add(priv_peer)
        priv_peer_ports.add(pub_peer)
      
      priv_i += partition_size

    self.static_deployment = tuple((peer, tuple(peer_ports[peer])) for peer in peer_ids)
    return super()._generate_deployment()


class CircularDeploymentStrategy(CrossedDeploymentStrategy):
  KIND = DeploymentStrategyKind.CIRCULAR
  ALLOW_PRIVATE_PEERS = True

  def _generate_deployment_all_public(self, public_peers: Iterable[int])  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    # assert(not self.private_peers)
    peer_count = len(public_peers)

    peer_ids = list(public_peers)
    random.shuffle(peer_ids)

    def peer_peers_count(cell_i: int) -> int:
      assert(peer_count >= 2)
      if peer_count == 2:
        return 1
      else:
        return 2
    
    return (peer_ids, peer_peers_count, [
      # 1st peer
      partial(self._peer_left, peer_count=peer_count),
      # 2nd peer
      partial(self._peer_right, peer_count=peer_count),
    ])


class IncompleteSpanTree(Exception):
  def __init__(self, span_tree, *args: object) -> None:
    self.span_tree = span_tree
    super().__init__(*args)


class RandomDeploymentGraph:
  def __init__(self,
      peers: Iterable[int],
      min_peer_edges: int,
      ok_peer_edges: int,
      max_peer_edges: int,
      private_peers: Optional[Iterable[int]]=None) -> None:
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

  def _generate_new_spanning_tree(self,
      private_first: bool=False,
      public_first: bool=False):
    visited = set()
    edges = list()

    def _pick_random(peers: Optional[Iterable[int]]) -> Tuple[int, bool]:
      peer = random.sample(list(peers), 1).pop()
      peer_public = peer in self.public_peers
      return peer, peer_public

    def _pick_random_neighbor(current_public: bool=False) -> Tuple[int, bool]:
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
      assert(current_public or other_public)
      visited.add(other)
      edges.append((current, other))
      current = other
      current_public = other_public

    return edges


  def generate_edges(self, max_tries: int=100000) -> None:
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
        log.error("[RND-STRATEGY] Failed to generate a backbone deployment with the 'random' strategy.")
        log.error("[RND-STRATEGY] You can try to run this command again, and it is possible that the generation will succeeed.")
        log.error("[RND-STRATEGY] If it continues to fail, adjust the min/ok/max parameters.")
        log.error("[RND-STRATEGY] In the worst case, you might have to define the deployment manually using the 'static' strategy.")
        import pprint
        log.warning(f"[RND-STRATEGY] Allocated peer links: {pprint.pformat(self.peer_edges)}")
        log.warning(f"[RND-STRATEGY] {pprint.pformat(self.peer_edges)}")
        log.warning(f"[RND-STRATEGY] - min: {self.min_peer_edges}, ok: {self.ok_peer_edges}, max: {self.max_peer_edges}")
        log.warning(f"[RND-STRATEGY] - public peers [{len(self.public_peers)}] = {self.public_peers}")
        log.warning(f"[RND-STRATEGY] - private peers [{len(self.private_peers)}] = {self.private_peers}")
        log.warning(f"[RND-STRATEGY] - min peers [{len(self.min_peers)}] = {self.min_peers}")
        log.warning(f"[RND-STRATEGY] - ok peers [{len(self.ok_peers)}] = {self.ok_peers}")
        log.warning(f"[RND-STRATEGY] - max peers [{len(self.full_peers)}] = {self.full_peers}")
        raise RuntimeError("failed to generate requested edges")
      finally:
        if validate:
          assert(len(self.ok_peers & self.full_peers) == 0)
          assert(len(self.ok_peers & self.min_peers) == 0)
          assert(len(self.full_peers & self.min_peers) == 0)


class RandomDeploymentStrategy(StaticDeploymentStrategy):
  KIND = DeploymentStrategyKind.RANDOM

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
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


  def _generate_deployment(self)  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    graph = RandomDeploymentGraph(
      peers=self.peers,
      min_peer_edges=self.min_peer_edges,
      ok_peer_edges=self.ok_peer_edges,
      max_peer_edges=self.max_peer_edges,
      private_peers=self.private_peers)
    graph.generate_edges()

    self.static_deployment = tuple(
      (p, tuple(peers))
        for p, peers in graph.peer_edges.items()
    )
    return super()._generate_deployment()


class FullMeshDeploymentStrategy(StaticDeploymentStrategy):
  KIND  = DeploymentStrategyKind.FULL_MESH


  def _generate_deployment(self)  -> Tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    graph = {
      a: [
        b
        for b in self.peers
          for b_priv in [b in self.private_peers]
            if b != a and (not a_priv or not b_priv)
      ] for a in self.peers
          for a_priv in [a in self.private_peers]
    }

    self.static_deployment = tuple(
      (p, tuple(peers))
        for p, peers in graph.items()
    )

    return super()._generate_deployment()


