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
from typing import Callable, Sequence

from .deployment_strategy import DeploymentStrategy, DeploymentStrategyKind


class StaticDeploymentStrategy(DeploymentStrategy):
  KIND = DeploymentStrategyKind.STATIC

  PROPERTIES = ["static_deployment"]
  # RO_PROPERTIES = ["static_deployment"]

  def INITIAL_STATIC_DEPLOYMENT(self) -> tuple:
    return tuple((p, tuple(peers)) for p, peers in self.args.get("peers_map", []))

  def _generate_deployment(
    self,
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
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
      def _peer_generator(peer_a_i: int) -> int | None:
        try:
          res = self.static_deployment[peer_a_i]
        except IndexError:
          self.log.warning(
            "unknown peer ({}) detected for link: {} → {}", peer_a_i, peer_a_i, peer_b_i
          )
          return None
        peer_id, static_peers = res
        res = static_peers[peer_b_i]
        try:
          return peer_ids.index(res)
        except ValueError:
          self.log.warning("unknown peer ({})", peer_b_i)

      return _peer_generator

    peer_generators = [_mk_peer_generator(i) for i in range(max_peers_count)]
    return (peer_ids, cell_peers_count, peer_generators)
