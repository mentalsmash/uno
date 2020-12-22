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
import types

from libuno.wg import WireGuardKeyPair
from libuno.tmplt import TemplateRepresentation
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.identity import UvnIdentityDatabase
from libuno.router_port import CellRouterPort
from libuno.particle import Particle
from libuno.cfg import UvnDefaults

import libuno.log
logger = libuno.log.logger("uvn.cell")

class CellKeyMaterial(list):
    
    def __init__(self,
            peers=None,
            registry=None,
            particles=None):
        if peers is None:
            self.rekey()
        else:
            self.extend(peers)
        
        if registry is None:
            self.registry = WireGuardKeyPair.generate()
        else:
            self.registry = registry
        
        if particles is None:
            self.particles = WireGuardKeyPair.generate()
        else:
            self.particles = particles
    
    def rekey(self):
        self.clear()
        self.append(WireGuardKeyPair.generate())
        self.append(WireGuardKeyPair.generate())
        self.append(WireGuardKeyPair.generate())

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["peers"] = [repr_yml(k, **kwargs) for k in py_repr]
            yml_repr["registry"] = repr_yml(py_repr.registry, **kwargs)
            yml_repr["particles"] = repr_yml(py_repr.particles, **kwargs)
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            def keymat_deserialize(k):
                return repr_py(WireGuardKeyPair, k, **kwargs)
            registry = keymat_deserialize(yml_repr["registry"])
            particles = keymat_deserialize(yml_repr["particles"])
            peers = list(map(keymat_deserialize, yml_repr["peers"]))
            py_repr = CellKeyMaterial(
                        registry=registry,
                        particles=particles,
                        peers=peers)
            return py_repr

class CellIdentity:
    
    def __init__(self, name, n, address, keymat, location, admin, admin_name):
        self.name = name
        self.n = n
        self.address = address
        self.keymat = keymat
        self.location = location
        self.admin = admin
        self.admin_name = admin_name
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["name"] = py_repr.name
            yml_repr["n"] = py_repr.n
            yml_repr["address"] = py_repr.address
            yml_repr["location"] = py_repr.location
            yml_repr["admin"] = py_repr.admin
            yml_repr["admin_name"] = py_repr.admin_name
            yml_repr["keymat"] = repr_yml(py_repr.keymat, **kwargs)
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            keymat = repr_py(CellKeyMaterial, yml_repr["keymat"], **kwargs)
            py_repr = CellIdentity(
                        name=yml_repr["name"],
                        n=yml_repr["n"],
                        address=yml_repr["address"],
                        keymat=keymat,
                        location=yml_repr["location"],
                        admin=yml_repr["admin"],
                        admin_name=yml_repr["admin_name"])
            return py_repr

class Cell:

    def __init__(self,
                 cell_id,
                 peer_ports,
                 psk,
                 registry_vpn=None,
                 router_port=None,
                 loaded=False):
        self.id = cell_id
        self.registry_psk = psk
        self.peer_ports = peer_ports
        self.registry_vpn = registry_vpn
        self.router_port = router_port
        self.loaded = loaded
        self.dirty = False
        self.particles_vpn = Cell.ParticlesConnection(self)
    
    def __str__(self):
        return self.id.name
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            tgt_cell = kwargs.get("tgt_cell")
            public_only = (kwargs.get("public_only") or
                            (tgt_cell is not None and
                            tgt_cell != py_repr.id.name))

            kwargs["public_only"] = public_only

            yml_repr = dict()
            yml_repr["id"] = repr_yml(py_repr.id, **kwargs)
            yml_repr["peer_ports"] = py_repr.peer_ports

            if (public_only):
                registry_psk = ''
                registry_vpn = ''
                router_port = ''
            else:
                registry_psk = py_repr.registry_psk
                registry_vpn = repr_yml(py_repr.registry_vpn, **kwargs)
                router_port = repr_yml(py_repr.router_port, **kwargs)
            
            yml_repr["registry_psk"] = registry_psk
            yml_repr["registry_vpn"] = registry_vpn
            yml_repr["router_port"] = router_port
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            cell_id = repr_py(CellIdentity, yml_repr["id"], **kwargs)
            if isinstance(yml_repr["registry_vpn"], dict):
                registry_vpn = repr_py(Cell.RegistryConnection,
                                yml_repr["registry_vpn"], **kwargs)
            else:
                registry_vpn = None
            
            if isinstance(yml_repr["router_port"], dict):
                router_port = repr_py(CellRouterPort,
                                yml_repr["router_port"], **kwargs)
            else:
                router_port = None
            
            py_repr = Cell(
                        cell_id=cell_id,
                        peer_ports=yml_repr["peer_ports"],
                        psk=yml_repr["registry_psk"],
                        registry_vpn=registry_vpn,
                        router_port=router_port,
                        loaded=True)

            return py_repr
        
        def _file_format_out(self, yml_str, **kwargs):
            return UvnIdentityDatabase.sign_data(
                    "cell manifest", yml_str, **kwargs)

        def _file_format_in(self, yml_str, **kwargs):
            return UvnIdentityDatabase.verify_data(
                    "cell manifest", yml_str, **kwargs)

    @TemplateRepresentation("wireguard-cfg", "wg/cell_to_registry.conf")
    class RegistryConnection:
        
        def __init__(self,
                    interface,
                    allowed_ips,
                    cell_ip,
                    registry_pubkey,
                    psk,
                    cell_privkey,
                    registry_endpoint,
                    registry_address,
                    registry_port):

            self.interface = interface
            self.allowed_ips = allowed_ips
            self.cell_ip = cell_ip
            self.registry_pubkey = registry_pubkey
            self.psk = psk
            self.cell_privkey = cell_privkey
            self.registry_port = registry_port
            self.registry_address = registry_address
            self.registry_endpoint = registry_endpoint
        
        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                yml_repr = dict()
                yml_repr["interface"] = py_repr.interface
                yml_repr["registry_port"] = py_repr.registry_port
                yml_repr["registry_endpoint"] = py_repr.registry_endpoint
                yml_repr["registry_address"] = str(py_repr.registry_address)
                yml_repr["registry_pubkey"] = py_repr.registry_pubkey
                yml_repr["psk"] = py_repr.psk
                yml_repr["allowed_ips"] = str(py_repr.allowed_ips)
                yml_repr["cell_ip"] = str(py_repr.cell_ip)
                yml_repr["cell_privkey"] = py_repr.cell_privkey
                return yml_repr
        
            def repr_py(self, yml_repr, **kwargs):
                py_repr = Cell.RegistryConnection(
                            interface=yml_repr["interface"],
                            allowed_ips=ipaddress.ip_network(
                                            yml_repr["allowed_ips"]),
                            cell_ip=ipaddress.ip_address(
                                                yml_repr["cell_ip"]),
                            registry_endpoint=yml_repr["registry_endpoint"],
                            registry_address=ipaddress.ip_address(
                                                yml_repr["registry_address"]),
                            registry_port=yml_repr["registry_port"],
                            registry_pubkey=yml_repr["registry_pubkey"],
                            psk=yml_repr["psk"],
                            cell_privkey=yml_repr["cell_privkey"])
                return py_repr

    @TemplateRepresentation("wireguard-cfg", "wg/cell_to_particles.conf")
    class ParticlesConnection:
        
        def __init__(self, cell):
            self.cell_n = cell.id.n
            self.cell_name = cell.id.name
            self.endpoint = "{}:{}".format(
                cell.id.address,
                UvnDefaults["registry"]["vpn"]["particles"]["port"])
            self.interface = UvnDefaults["registry"]["vpn"]["particles"]["interface"].format(0)
            self.port = UvnDefaults["registry"]["vpn"]["particles"]["port"]
            self.network = ipaddress.ip_network(
                "{}/{}".format(
                    UvnDefaults["registry"]["vpn"]["particles"]["base_ip"],
                    UvnDefaults["registry"]["vpn"]["particles"]["netmask"]))
            self.addr_local = self.network.network_address + 1
            self.keymat = cell.id.keymat.particles
            self.particles = {}

        def add_particle(self, name, address, pubkey, psk):
            particle_cfg = self.particles.get(name)
            if particle_cfg:
                # already registered
                return particle_cfg

            particle_cfg = types.SimpleNamespace(
                name=name,
                allowed=address,
                pubkey=pubkey,
                psk=psk)

            self.particles[name] = particle_cfg

            logger.debug("registered particle: {}/{}", self.cell_name, name)

            return particle_cfg

        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                yml_repr = dict()
                yml_repr["interface"] = py_repr.interface
                yml_repr["endpoint"] = py_repr.endpoint
                yml_repr["port"] = py_repr.port
                yml_repr["network"] = str(py_repr.network)
                yml_repr["addr_local"] = str(py_repr.addr_local)
                yml_repr["keymat"] = repr_yml(py_repr.keymat, **kwargs)
                yml_repr["peers"] = [repr_yml(p, **kwargs)
                    for p in py_repr.particles.values()]
                return yml_repr
        
            def repr_py(self, yml_repr, **kwargs):
                raise NotImplementedError()
