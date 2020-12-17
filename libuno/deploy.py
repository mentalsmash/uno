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
import itertools
import ipaddress

from libuno.tmplt import TemplateRepresentation
from libuno.yml import YamlSerializer, repr_yml, repr_py
from libuno.helpers import Timestamp
from libuno.identity import UvnIdentityDatabase
from libuno.cfg import UvnDefaults
from libuno.psk import PresharedKeys
from libuno.cell_cfg import CellDeployment
from libuno.strategy import DeploymentStrategy
from libuno import ip

import libuno.log
logger = libuno.log.logger("uvn.deploy")

class UvnDeployment:

    def __init__(self,
                 deploy_time,
                 strategy,
                 cells,
                 deployed_cells,
                 address_range,
                 psks,
                 registry,
                 id=None,
                 loaded=False):
        self.registry = registry
        self.strategy = strategy
        self.deploy_time = deploy_time
        if (id is None):
            self.id = self.deploy_time.format()
        else:
            self.id = id
        self.cells = cells;
        self.deployed_cells = deployed_cells
        self.address_range = address_range
        self.psks = psks
        self.loaded = loaded
        self.dirty = False

    def to_graph(self,
                 save=False,
                 filename=UvnDefaults["registry"]["deployment_graph"],
                 label_name=True):
        import networkx
        graph = networkx.Graph()

        for c in self.deployed_cells:
            # for p in c.peers:
            #     if (label_name):
            #         graph.add_edge(c.cell.id.name, p.cell.id.name)
            #     else:
            #         graph.add_edge(c.deploy_id, p.deploy_id)
            for b in c.backbone:
                for p in b.peers:
                    graph.add_edge(c.cell.id.name, p.name)
                    
        
        if (save):
            import matplotlib.pyplot
            matplotlib.pyplot.clf()
            networkx.draw_circular(graph, with_labels = True)
            matplotlib.pyplot.savefig(filename)
            matplotlib.pyplot.clf()
        
        return graph
    
    def is_stale(self):
        # Check that the deployment still applies or if it has become stale
        # (i.e. the cells it deploys are all still part of the uvn, and all
        # current cells in the uvn are included in the deployment), 
        return len(set(self.cells) ^ set(self.registry.cells.values())) > 0
    
    def backbone_subnet(self):
        return ip.ipv4_range_subnet(*self.address_range)
    
    def cell_config(self, name):
        return next(filter(lambda c: c.cell.id.name == name,
                    self.deployed_cells), None)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            tgt_cell_cfg = kwargs.get("tgt_cell_cfg")
            if (tgt_cell_cfg is not None):
                tgt_cells = list(itertools.chain(
                    (c.deploy_id for c in tgt_cell_cfg.peers),
                    [tgt_cell_cfg.deploy_id]))
            else:
                tgt_cells = [c.deploy_id for c in py_repr.deployed_cells]
            
            deployment_id = kwargs.get("deployment_id")
            if (deployment_id is None):
                deployment_id = py_repr.id
    
            yml_repr = dict()
            yml_repr["id"] = deployment_id
            yml_repr["strategy"] = repr_yml(py_repr.strategy, **kwargs)
            yml_repr["deploy_time"] = repr_yml(py_repr.deploy_time, **kwargs)
            yml_repr["cells"] = [c.id.name for c in py_repr.cells]
            yml_repr["psks"] = repr_yml(py_repr.psks, psk_cells=tgt_cells, **kwargs)
            yml_repr["deployed_cells"] = [repr_yml(c, deployment=py_repr, **kwargs)
                                            for c in py_repr.deployed_cells
                                                if c.deploy_id in tgt_cells]
            yml_repr["address_range"] = tuple(map(str, py_repr.address_range))
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            registry = kwargs["registry"]

            strategy = repr_py(DeploymentStrategy, yml_repr["strategy"], **kwargs)
            deploy_time = repr_py(Timestamp, yml_repr["deploy_time"], **kwargs)
            cells = [registry.cell(c) for c in yml_repr["cells"]]
            psks = repr_py(PresharedKeys, yml_repr["psks"], **kwargs)
            address_range = tuple(ipaddress.ip_address(a)
                                for a in yml_repr["address_range"])
            
            py_repr = UvnDeployment(
                        id=yml_repr["id"],
                        strategy=strategy,
                        deploy_time=deploy_time,
                        address_range=address_range,
                        cells=cells,
                        deployed_cells=[],
                        psks=psks,
                        registry=registry,
                        loaded=bool(kwargs.get("from_file")))
            
            py_repr.deployed_cells = [
                repr_py(CellDeployment, c, deployment=py_repr, **kwargs)
                    for c in yml_repr.get("deployed_cells",[])
            ]
                
            return py_repr
        
        def _file_format_out(self, yml_str, **kwargs):
            return UvnIdentityDatabase.sign_data(
                    "deployment manifest", yml_str, **kwargs)

        def _file_format_in(self, yml_str, **kwargs):
            return UvnIdentityDatabase.verify_data(
                    "deployment manifest", yml_str, **kwargs)


@TemplateRepresentation("human", "md/deployment_report.md")
class UvnDeploymentSummary:
    def __init__(self, registry, deployment):
        self.registry = registry
        self.deployment = deployment
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = {}
            yml_repr["registry"] = repr_yml(py_repr.registry, **kwargs)
            yml_repr["identity_db"] = repr_yml(py_repr.registry.identity_db, **kwargs)
            yml_repr["deployment"] = repr_yml(py_repr.deployment, **kwargs)
            def get_cell_by_name(registry, name):
                return next(iter([c for c in registry["cells"] if c["id"]["name"] == name]))
            def get_cell_public_key_by_name(name):
                return py_repr.registry.identity_db.get_cell_record(name).key.fingerprint
            # def get_cell_port(cell_cfg, peer_id):
            #     return int(cell_cfg["peers"][peer_id].split(":")[0])
            def get_peer_port(cell_cfg, peer_id):
                return int(cell_cfg["peers"][peer_id].split(":")[2])
            def _extract_deployed_cell_name(cell):
                return cell["name"]
            def _extract_deployed_cell_registration_id(cell):
                return get_cell_by_name(yml_repr["registry"], cell["cell"])["id"]["n"]
            def sort_deployed_cells(deployed_cells):
                return sorted(deployed_cells, key=_extract_deployed_cell_registration_id)
            # def enumerate_peers(cell_cfg, peers):
            #     def _extract_local_port(peerentry):
            #         return get_cell_port(cell_cfg, peerentry[0])
            #     return sorted(enumerate(peers), key=_extract_local_port)
            yml_repr["get_cell_public_key_by_name"] = get_cell_public_key_by_name
            yml_repr["get_cell_by_name"] = get_cell_by_name
            # yml_repr["get_cell_port"] = get_cell_port
            yml_repr["get_peer_port"] = get_peer_port
            yml_repr["sort_deployed_cells"] = sort_deployed_cells
            # yml_repr["enumerate_peers"] = enumerate_peers
            yml_repr["enumerate"] = enumerate
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()
