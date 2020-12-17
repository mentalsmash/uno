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
from .dds_rs import CellRoutingServiceConfig, TopicQueries

class CellParticipant(UvnParticipant):
    def __init__(self, basedir, registry, listener, profile_file,
            cell, cell_cfg, cell_record):
        dds_peers = ["shmem://", str(cell.registry_vpn.registry_address)]
        # dds_peers = ["shmem://"]
        UvnParticipant.__init__(self, basedir, registry, listener, profile_file,
            participant_config=UvnDefaults["dds"]["participant"]["cell_agent"],
            dds_peers=dds_peers,
            writers={
                "cell_info":    UvnDefaults["dds"]["writer"]["cell_info"],
                "dns":          UvnDefaults["dds"]["writer"]["dns"]
            },
            readers={
                "uvn_info":     UvnDefaults["dds"]["reader"]["uvn_info"],
                "deployment":   UvnDefaults["dds"]["reader"]["deployment"]
            },
            queries={
                "uvn_info": {
                    "params": [
                        "'{}'".format(registry.address)
                    ],
                    "str": TopicQueries["match_uvn"]["uvn_info"].format("%0")
                },
                "cell_info": {
                    "params": [
                        "'{}'".format(registry.address),
                        "'{}'".format(cell.id.name)
                    ],
                    "str": TopicQueries["match_others"]["cell_info"].format("%0", "%1")
                },
                "dns": {
                    "params": [
                        "'{}'".format(registry.address),
                        "'{}'".format(cell.id.name)
                    ],
                    "str": TopicQueries["match_others"]["dns"].format("%0", "%1")
                },
                "deployment": {
                    "params": [
                        "'{}'".format(registry.address),
                        "'{}'".format(cell.id.name)
                    ],
                    "str": TopicQueries["match_cell"]["deployment"].format("%0", "%1")
                }
            },
            router_cfg=(UvnDefaults["dds"]["rs"]["config"]["peer"],
                CellRoutingServiceConfig(
                    peers=list(chain(
                        [{
                            "name": "registry",
                            "address": cell.registry_vpn.registry_address
                        }],
                        [{
                            "name": p.name,
                            "address": p.addr_remote
                        } for bbone in cell_cfg.backbone for p in bbone.peers]
                            if cell_cfg else [])),
                    registry=registry,
                    cell=cell,
                    cell_cfg=cell_cfg))
        )

    def start(self):
        if self.registry.deployed_cell_config:
            for bbone in self.registry.deployed_cell_config.backbone:
                for p in bbone.peers:
                    self._dds_peers.add(str(p.addr_remote))
        UvnParticipant.start(self)
