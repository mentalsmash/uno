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
from itertools import chain

from libuno.cfg import UvnDefaults
import rti.connextdds as dds

from .dds import UvnParticipant, logger
from .dds_rs import RootRoutingServiceConfig, TopicQueries


def _router_cell_peers(registry, cell):
    if not registry.latest_deployment:
        return []
    return map(lambda p: p.name,
        chain.from_iterable(
            map(lambda bbone: bbone.peers,
            chain.from_iterable(
                map(lambda cell_cfg: cell_cfg.backbone,
                    filter(lambda cell_cfg: cell_cfg.cell == cell,
                        registry.latest_deployment.deployed_cells))))))

def _router_repeat_targets(registry, cell):
    peers = set(_router_cell_peers(registry, cell))
    # peers_of_p = set()
    # for p in peers:
    #     peers_of_p.update(_router_cell_peers(registry, registry.cell(p)))
    # peers.update(peers_of_p)
    cells = set(registry.cells)
    repeat_tgts = (cells - peers) - set([cell.id.name])
    # repeat_tgts = cells - set([cell.id.name])
    return repeat_tgts

class RootParticipant(UvnParticipant):
    def __init__(self, basedir, registry, listener, profile_file):
        dds_peers = [str(c.registry_vpn.cell_ip) for c in registry.cells.values()]
        # dds_peers = ["shmem://"]
        UvnParticipant.__init__(self, basedir, registry, listener, profile_file,
            participant_config=UvnDefaults["dds"]["participant"]["root_agent"],
            dds_peers=dds_peers,
            writers={
                "uvn_info":    UvnDefaults["dds"]["writer"]["uvn_info"],
                "deployment":  UvnDefaults["dds"]["writer"]["deployment"],
                "dns":         UvnDefaults["dds"]["writer"]["dns"]
            },
            queries={
                "cell_info": {
                    "params": [
                        "'{}'".format(registry.address)
                    ],
                    "str": TopicQueries["match_uvn"]["cell_info"].format("%0")
                },
                "dns": {
                    "params": [
                        "'{}'".format(registry.address)
                    ],
                    "str": TopicQueries["match_uvn"]["dns"].format("%0")
                }
            },
            router_cfg=(UvnDefaults["dds"]["rs"]["config"]["root"],
                RootRoutingServiceConfig(
                    registry=registry,
                    peers=[{
                        "name": cell.id.name,
                        "address": cell.registry_vpn.cell_ip,
                        "peers": _router_cell_peers(registry, cell),
                        "repeat_tgt": _router_repeat_targets(registry, cell),
                    } for cell in registry.cells.values()])
            )
        )
