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
import ipaddress

import libuno.ip as ip
from libuno.tmplt import TemplateRepresentation
from libuno.yml import YamlSerializer, repr_yml, repr_py
from libuno.psk import PresharedKeys
from libuno.exception import UvnException
from libuno.cfg import UvnDefaults

class CellDeployment:
    def __init__(self,
                 cell,
                 deploy_id,
                 psks,
                 peers,
                 backbone=[]):
        self.cell = cell
        self.deploy_id = deploy_id
        self.peers = peers
        self.psks = psks
        self.backbone = list(backbone)
        self.allocated_ports = {}
    
    def __str__(self):
        return "{}:{}".format(self.deploy_id, self.cell.id.name)
    
    def validate_peers(self, deployed_cells):
        for peer_i, peer_local in enumerate(self.peers):
            if (peer_local is None):
                raise err.UnexpectedError(
                        "Unexpected empty peer entry: {}[{}]".format(
                            self, peer_i))
            
            peer_cfg = deployed_cells[peer_local.deploy_id]
            self._assert_peer_remote(
                peer_i, peer_local, peer_cfg, assert_valid=True)

    def _assert_peer_remote(self, peer_i, peer_local, peer_cfg, assert_valid=False):
        remote_port = peer_cfg._find_peer_port_id(self.cell.id.name)
        
        if (remote_port >= 0):
            remote_peer_entry = peer_cfg.peers[remote_port]

        if (peer_local.port_id >= 0):
            # The peer entry has a valid remote port id, make sure that
            # this value matches the peer's deployment configuration
            if (peer_local.port_id != remote_port):
                raise err.UnexpectedError(
                    "Invalid peer configuration detected: {}[{}] -> {}[{}], but remote port is {}".format(
                    self, peer_i,
                    peer_local.cell.id.name, peer_local.port_id,
                    remote_port))
        elif remote_port >= 0:
            peer_local.port_id = remote_port
            # Check if the peer's entry for this cell has a valid remote port,
            # and update it with our local port if it isn't    
            if (remote_peer_entry.port_id < 0):
                remote_peer_entry.port_id = peer_i
        
        if (assert_valid):
            if (peer_local.port_id < 0 or remote_port < 0 or
                remote_peer_entry.port_id < 0):

                if (remote_peer_entry is not None):
                    remote_peer_name = remote_peer_entry.cell.id.name
                    remote_peer_port = remote_peer_entry.port_id
                else:
                    remote_peer_name = "unknown"
                    remote_peer_port = -1

                raise err.UnexpectedError(
                    "Invalid peer configuration detected: {}[{}] -> {}[{}], {}[{}] -> {}[{}]",
                    self, peer_i,
                    peer_local.cell.id.name, peer_local.port_id,
                    peer_cfg.cell.id.name, remote_port,
                    remote_peer_name, remote_peer_port)
    
    def _find_peer_port_id(self, peer_name, required=False):
        try:
            return next(map(lambda p: p[0],filter(
                    lambda p: p[1] is not None and 
                            p[1].cell.id.name == peer_name,
                    enumerate(self.peers))))
        except StopIteration as e:
            if required:
                raise e
            else:
                return -1
    
    def _find_backbone_connection(self, net_n):
        for c in self.backbone:
            if c.net_cell_n == net_n:
                return c
        return None
    
    def _find_peer_connection(self, peer_name, noexcept=False):
        for bbone_connection in self.backbone:
            for pc in bbone_connection.peers:
                if pc.name == peer_name:
                    return bbone_connection.interface, pc
        if not noexcept:
            raise UvnException("failed to find peer connection for {}".format(peer_name))
        return None, None

    def _find_cell_peer(self, cell_name, noexcept=False):
        for p in self.peers:
            if p.cell.id.name == cell_name:
                return self._find_peer_connection(cell_name, noexcept=noexcept)
        if not noexcept:
            raise UvnException("failed to find peer for {}".format(cell_name))
        return None, None

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            tgt_cell_cfg = kwargs.get("tgt_cell_cfg")
            public_only = (tgt_cell_cfg is not None and
                            tgt_cell_cfg.cell.id.name != py_repr.cell.id.name)

            yml_repr = dict()
            yml_repr["cell"] = py_repr.cell.id.name
            yml_repr["deploy_id"] = py_repr.deploy_id
            yml_repr["peers"] = [repr_yml(p, **kwargs) for p in py_repr.peers]
            yml_repr["backbone"] = [repr_yml(p, **kwargs) for p in py_repr.backbone]
            
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            deployment = kwargs.get("deployment")
            cell = kwargs["registry"].cells[yml_repr["cell"]]

            peers = [repr_py(CellDeployment.Peer, p, **kwargs)
                        for p in yml_repr["peers"]]

            backbone = [repr_py(CellDeployment.BackboneConnection, c, **kwargs)
                            for c in yml_repr["backbone"]]
            
            if (deployment is not None):
                psks = deployment.psks
            elif ("psks" in yml_repr):
                psks = PresharedKeys()
                
            py_repr = CellDeployment(
                            cell=cell,
                            peers=peers,
                            backbone=backbone,
                            psks=psks,
                            deploy_id=yml_repr["deploy_id"])
            
            return py_repr

    class Peer:

        def __init__(self, deploy_id, cell, port_id=-1, cell_name=None):
            self.deploy_id = deploy_id
            self.cell = cell
            self.port_id = port_id
            if (self.cell is not None):
                self.cell_name = self.cell.id.name
            else:
                self.cell_name = cell_name
        
        def __str__(self):
            return "{}:{}:{}".format(self.deploy_id, self.cell_name, self.port_id)
        
        def endpoint(self):
            if (self.port_id >= 0):
                cell_port = self.cell.peer_ports[self.port_id]
            else:
                cell_port = 0
            
            return (self.cell.id.address, cell_port)
        
        def _update_port(self, port_id):
            self.port_id = port_id
        
        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                yml_repr = str(py_repr)
                return yml_repr
        
            def repr_py(self, yml_repr, **kwargs):
                deploy_id, cell_name, port_id = yml_repr.split(":")
                cell = kwargs["registry"].cells[cell_name]
                py_repr = CellDeployment.Peer(
                            cell = cell,
                            port_id = port_id,
                            deploy_id = deploy_id)
                return py_repr
    
    @TemplateRepresentation("wireguard-cfg", "wg/cell_to_cell.conf")
    class BackboneConnection:

        def __init__(self,
                    cell_name,
                    cell_pubkey,
                    cell_privkey,
                    interface,
                    net_cell_n,
                    port_i,
                    port_local,
                    addr_local,
                    network_local,
                    network,
                    network_mask,
                    peers=None):
            
            self.cell_name = cell_name
            self.cell_pubkey = cell_pubkey
            self.cell_privkey = cell_privkey
            self.interface = interface
            self.net_cell_n = net_cell_n
            self.port_i = port_i
            self.port_local = port_local
            self.addr_local = addr_local
            self.network_local = network_local
            self.network = network
            self.network_mask = network_mask
            if peers:
                self.peers = peers
            else:
                self.peers = []

        
        def add_peer(self, **kwargs):
            peer = CellDeployment.BackboneConnection.Peer(**kwargs)
            self.peers.append(peer)
            return peer
        
        def has_peer(self, peer_name):
            for p in self.peers:
                if p.name == peer_name:
                    return True
            return False
        
        def get_peer(self, peer_name):
            for p in self.peers:
                if p.name == peer_name:
                    return p
            raise StopIteration()
        
        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                if (kwargs.get("public_only")):
                    cell_privkey = ""
                    interface = ""
                else:
                    cell_privkey = py_repr.cell_privkey
                    interface = py_repr.interface

                yml_repr = dict()
                yml_repr["cell_name"] = py_repr.cell_name
                yml_repr["cell_pubkey"] = py_repr.cell_pubkey
                yml_repr["cell_privkey"] = cell_privkey
                yml_repr["interface"] = interface
                yml_repr["net_cell_n"] = py_repr.net_cell_n
                yml_repr["port_i"] = py_repr.port_i
                yml_repr["port_local"] = py_repr.port_local
                yml_repr["addr_local"] = str(py_repr.addr_local)
                yml_repr["network_local"] = str(py_repr.network_local)
                yml_repr["network"] = str(py_repr.network)
                yml_repr["network_mask"] = str(py_repr.network_mask)
                yml_repr["peers"] = [repr_yml(p, **kwargs) for p in py_repr.peers]
                return yml_repr
        
            def repr_py(self, yml_repr, **kwargs):
                py_repr = CellDeployment.BackboneConnection(
                            cell_name=yml_repr["cell_name"],
                            cell_pubkey=yml_repr["cell_pubkey"],
                            cell_privkey=yml_repr["cell_privkey"],
                            interface=yml_repr["interface"],
                            net_cell_n=yml_repr["net_cell_n"],
                            port_i=yml_repr["port_i"],
                            port_local=yml_repr["port_local"],
                            addr_local=ipaddress.ip_address(yml_repr["addr_local"]),
                            network_local=yml_repr["network_local"],
                            network=ipaddress.ip_network(yml_repr["network"]),
                            network_mask=int(yml_repr["network_mask"]),
                            peers=[repr_py(CellDeployment.BackboneConnection.Peer, p, **kwargs)
                                    for p in yml_repr["peers"]])
                return py_repr
        
        class Peer:
            def __init__(self,
                    name,
                    pubkey,
                    addr_remote,
                    psk,
                    endpoint,
                    peer_i):
                self.name = name
                self.pubkey = pubkey
                self.addr_remote = addr_remote
                self.psk = psk
                self.endpoint = endpoint
                self.peer_i = peer_i
            
            class _YamlSerializer(YamlSerializer):
                def repr_yml(self, py_repr, **kwargs):
                    if (kwargs.get("public_only")):
                        psk = ""
                    else:
                        psk = py_repr.psk
                    
                    yml_repr = dict()
                    yml_repr["name"] = py_repr.name
                    yml_repr["pubkey"] = py_repr.pubkey
                    yml_repr["addr_remote"] = py_repr.addr_remote
                    yml_repr["psk"] = psk
                    yml_repr["endpoint"] = py_repr.endpoint
                    yml_repr["peer_i"] = py_repr.peer_i

                    return yml_repr
            
                def repr_py(self, yml_repr, **kwargs):
                    py_repr = CellDeployment.BackboneConnection.Peer(
                                name=yml_repr["name"],
                                pubkey=yml_repr["pubkey"],
                                psk=yml_repr["psk"],
                                addr_remote=yml_repr["addr_remote"],
                                endpoint=yml_repr["endpoint"],
                                peer_i=yml_repr["peer_i"])
                    return py_repr
