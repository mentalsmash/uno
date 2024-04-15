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
