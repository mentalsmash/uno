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
from .deployment_strategy import DeploymentStrategy, DeploymentStrategyKind
from .static_deployment_strategy import StaticDeploymentStrategy
from .crossed_deployment_strategy import CrossedDeploymentStrategy
from .circular_deployment_strategy import CircularDeploymentStrategy
from .random_deployment_strategy import RandomDeploymentStrategy
from .fullmesh_deployment_strategy import FullMeshDeploymentStrategy
