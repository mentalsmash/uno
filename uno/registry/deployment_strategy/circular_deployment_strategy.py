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
from functools import partial
import random
from typing import Callable, Sequence, Iterable

from .deployment_strategy import DeploymentStrategyKind
from .crossed_deployment_strategy import CrossedDeploymentStrategy


class CircularDeploymentStrategy(CrossedDeploymentStrategy):
  KIND = DeploymentStrategyKind.CIRCULAR
  ALLOW_PRIVATE_PEERS = True

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
      ],
    )
