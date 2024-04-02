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
from .crossed_deployment_strategy import CrossedDeploymentStrategy

class CircularDeploymentStrategy(CrossedDeploymentStrategy):
  KIND = DeploymentStrategyKind.CIRCULAR
  ALLOW_PRIVATE_PEERS = True

  def _generate_deployment_all_public(self, public_peers: Iterable[int])  -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
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

