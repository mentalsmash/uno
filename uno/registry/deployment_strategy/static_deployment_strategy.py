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

from .deployment_strategy import DeploymentStrategy, DeploymentStrategyKind


class StaticDeploymentStrategy(DeploymentStrategy):
  KIND = DeploymentStrategyKind.STATIC

  PROPERTIES = ["static_deployment"]
  # RO_PROPERTIES = ["static_deployment"]

  INITIAL_STATIC_DEPLOYMENT = lambda self: tuple(
    (p, tuple(peers))
      for p, peers in self.args.get("peers_map", []))


  def _generate_deployment(self)  -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    if not self.static_deployment:
      self.log.warning("no configuration specified, the deployment will be empty.")
      return self.EMPTY_DEPLOYMENT

    peer_ids = [id for id, _ in self.static_deployment]

    def cell_peers_count(n: int) -> int:
      _, cell_peers = self.static_deployment[n]
      return len(cell_peers)
    
    peers_counts = list(map(cell_peers_count, range(len(peer_ids))))
    max_peers_count = max(peers_counts or [0])

    def _mk_peer_generator(peer_b_i: int):
      def _peer_generator(peer_a_i: int) -> int|None:
        try:
          res = self.static_deployment[peer_a_i]
        except IndexError:
          self.log.warning("unknown peer ({}) detected for link: {} → {}",
            peer_a_i,
            peer_a_i,
            peer_b_i)
          return None
        peer_id, static_peers = res
        res = static_peers[peer_b_i]
        try:
          return peer_ids.index(res)
        except ValueError:
          self.log.warning("unknown peer ({})", peer_b_i)
      return _peer_generator

    peer_generators = [
      _mk_peer_generator(i) for i in range(max_peers_count)
    ]
    return (peer_ids, cell_peers_count, peer_generators)

