###############################################################################
# (C) Copyright 2020 Andrea Sorbini
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

from libuno.yml import YamlSerializer

class DeploymentStrategy:

    name = "null"

    def __init__(self, **kwargs):
        pass

    def deploy_cells(self, cells):
        return ([], None, None)
    
    def __str__(self):
        return DeploymentStrategy.name
    
    @staticmethod
    def strategies():
        return [
            DefaultDeploymentStrategy,
            CircularDeploymentStrategy
        ]
    
    @staticmethod
    def strategy_names():
        return (s.name for s in DeploymentStrategy.strategies())

    @staticmethod
    def by_name(strategy_name):
        for s in DeploymentStrategy.strategies():
            if (s.name == strategy_name):
                return s
        
        raise err.UnexpectedError(
                "Unknown deployment strategy: {}".format(strategy_name))

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return str(py_repr)
    
        def repr_py(self, yml_repr, **kwargs):
            strategy = DeploymentStrategy.by_name(yml_repr)
            return strategy(**kwargs)

class DefaultDeploymentStrategy(DeploymentStrategy):

    name = "default"

    def __str__(self):
        return DefaultDeploymentStrategy.name

    def deploy_cells(self, cells):

        cells = list(cells)
        cells_len = len(cells)
    
        if (cells_len == 0):
            return ([], 0, None, [])
        
        random.shuffle(cells)

        def peer_1(cell_i):
            # 1st peer is always the next cell (modulo cells_len)
            return (cell_i + 1) % cells_len
        
        def peer_2(cell_i):
            # 2nd peer is always set to the previous cell (modulo cells_len)
            if (cell_i == 0):
                return cells_len - 1
            else:
                return cell_i - 1
        
        def peer_3(cell_i):
            # 3rd peer is set to the cell "opposite" to this
            # one, i.e. with index: current.n + floor(len(cells)/2)
            offset = (cells_len // 2)
            if (cell_i <= (offset - 1)):
                return (cell_i + offset) % cells_len
            else:
                return cell_i - offset
        
        peer_generators = [
            peer_1,
            peer_2,
            peer_3
        ]

        def cell_peers_count(n, cells_len):
            if (cells_len <= 2):
                return 1
            elif (cells_len <= 3):
                return 2
            elif (not cells_len % 2 > 0 or not n == cells_len - 1):
                return 3
            else:
                return 2

        return (cells, cells_len, cell_peers_count, peer_generators)

class CircularDeploymentStrategy(DefaultDeploymentStrategy):

    name = "circular"

    def __str__(self):
        return CircularDeploymentStrategy.name

    def deploy_cells(self, cells):
        (cells,
         cells_len,
         _,
         peer_generators) = super().deploy_cells(cells)
        
        def cell_peers_count(n, cells_len):
            if (cells_len <= 2):
                return 1
            else:
                return 2

        return (cells, cells_len, cell_peers_count, peer_generators)
