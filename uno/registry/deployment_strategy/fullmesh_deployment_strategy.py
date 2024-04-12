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

from .deployment_strategy import DeploymentStrategyKind
from .static_deployment_strategy import StaticDeploymentStrategy


class FullMeshDeploymentStrategy(StaticDeploymentStrategy):
  KIND = DeploymentStrategyKind.FULL_MESH

  def _generate_deployment(
    self,
  ) -> tuple[Sequence[int], Callable[[int], int], Sequence[Callable[[int], int]]]:
    graph = {
      a: [
        b
        for b in self.peers
        for b_priv in [b in self.private_peers]
        if b != a and (not a_priv or not b_priv)
      ]
      for a in self.peers
      for a_priv in [a in self.private_peers]
    }

    self.static_deployment = tuple((p, tuple(peers)) for p, peers in graph.items())

    return super()._generate_deployment()
