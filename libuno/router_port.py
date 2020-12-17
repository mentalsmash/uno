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
import ipaddress

from libuno.tmplt import TemplateRepresentation, render
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.wg import WireGuardInterface, WireGuardKeyPair
from libuno.psk import PresharedKeys
from libuno.cfg import UvnDefaults
from libuno.exception import UvnException

import libuno.log
logger = libuno.log.logger("uvn.router.port")

class PortsExhaustedException(UvnException):
    pass

class RegistryRouterPorts:
    
    def __init__(self,
            min=UvnDefaults["registry"]["vpn"]["router"]["ports"]["range"][0],
            max=UvnDefaults["registry"]["vpn"]["router"]["ports"]["range"][1],
            reserved=UvnDefaults["registry"]["vpn"]["router"]["ports"]["reserved"],
            allocated={},
            psks=None,
            keymat=None):
        self.min = min
        self.max = max
        self.reserved = list(reserved)
        
        # Validate port range
        if self.max <= self.min or self.min <= 0:
            raise ValueError(self.min, self.max)
        self._range_len = self.max - self.min
        self._range_reserved = list(filter(
            lambda p: (p >= self.min and p <= self.max), self.reserved))
        self._range_len -= len(self._range_reserved)
        if self._range_len <= 0:
            # no available port in selected range
            raise ValueError(self.min, self.max, self.reserved)

        self.allocated = dict(allocated)
        self._sorted = sorted(self.allocated.values(),
                            key=lambda p: p.addr_remote)
        self.in_use = [p.n for p in self.allocated.values()]

        if psks is not None:
            self.psks = psks
        else:
            self.psks = PresharedKeys()
        
        if keymat is not None:
            self.keymat = keymat
        else:
            self.keymat = WireGuardKeyPair.generate()

    def __iter__(self):
        return iter(self.allocated.values())

    def __getitem__(self, index):
        return self._sorted[index]

    def _random_port_number(self):
        max_tries = 1e12
        i = 0
        n = None
        while n is None and i < max_tries:
            n = random.randint(self.min, self.max)
            if n in self.in_use or n in self.reserved:
                n = 0
            i += 1
        if not n:
            raise UvnException(f"failed to pick a port after {i} tries")
        return n

    def assert_cell(self, cell):
        port = self.allocated.get(cell.id.name)
        if port:
            logger.debug("router port already allocated for {}", cell.id.name)
            return port

        if len(self.in_use) >= self._range_len:
            raise PortsExhaustedException()

        psk = self.psks.assert_psk(0, cell.id.n)
        n = self._random_port_number()
        keymat = WireGuardKeyPair.generate()
        
        base_ip = ipaddress.ip_address(
            UvnDefaults["registry"]["vpn"]["router"]["base_ip"])
        # Assume that base IP doesn't have host bits set (so set one)
        base_ip += 2
        addr_local = base_ip + ((cell.id.n * 2) - 2)
        addr_remote = base_ip + ((cell.id.n * 2) - 1)

        interface = UvnDefaults["registry"]["vpn"]["router"]["interface"].format(0)

        area = str(addr_remote)

        port = CellRouterPort(cell.id.n, n, psk, keymat, self.keymat.pubkey,
                addr_local, addr_remote, interface, area)

        self.allocated[cell.id.name] = port
        self._sorted = sorted(self.allocated.values(),
                            key=lambda p: p.addr_remote)
        self.in_use.append(port.n)

        return port
    
    def find_port_by_interface(self, interface, root=False):
        return next(filter(lambda p:
                ((not root and p.interface == interface)
                  or (root and p.interface_registry == interface)),
                  self.allocated.values()))
    
    def find_port_by_cell(self, cell_n):
        return next(filter(lambda p: p.cell_n == cell_n,
                  self.allocated.values()))

    def interface_area(self, interface, root=False):
        port = self.find_port_by_interface(interface, root=root)
        return port.area

    def cell_area(self, cell_n):
        port = self.find_port_by_cell(cell_n)
        return port.area

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            target_cell = kwargs.get("tgt_cell")
            public_only = target_cell is not None or kwargs.get("public_only")
            if target_cell:
                tgt_cells = [py_repr.allocated[target_cell].cell_n]
            else:
                tgt_cells = [p.cell_n for p in py_repr.allocated.values()]

            kwargs = dict(kwargs)
            kwargs["public_only"] = public_only

            yml_repr = {
                "min": py_repr.min,
                "max": py_repr.max,
                "reserved": py_repr.reserved,
                "allocated": {
                    k: repr_yml(p, tgt_cells=tgt_cells, **kwargs)
                            for k, p in py_repr.allocated.items()
                },
                "psks": repr_yml(py_repr.psks, psk_cells=tgt_cells, **kwargs),
                "keymat": repr_yml(py_repr.keymat, **kwargs)
            }
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):

            return RegistryRouterPorts(
                    min=yml_repr["min"],
                    max=yml_repr["max"],
                    reserved=yml_repr["reserved"],
                    allocated={k: repr_py(CellRouterPort, p, **kwargs)
                                for k, p in yml_repr["allocated"].items()},
                    psks=repr_py(PresharedKeys, yml_repr["psks"], **kwargs),
                    keymat=repr_py(WireGuardKeyPair, yml_repr["keymat"], **kwargs))

class CellRouterPort:
    def __init__(self,
            cell_n,
            n,
            psk,
            keymat,
            registry_pubkey,
            addr_local,
            addr_remote,
            interface,
            area):
        self.cell_n = cell_n
        self.n = n
        self.psk = psk
        self.keymat = keymat
        self.registry_pubkey = registry_pubkey
        self.addr_local = addr_local
        self.addr_remote = addr_remote
        self.interface = interface
        self.interface_registry = UvnDefaults["registry"]["vpn"]["router"]["interface"].format(cell_n)
        self.area = area
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            tgt_cells = kwargs.get("tgt_cells", None)
            public_only = tgt_cells is not None and py_repr.cell_n not in tgt_cells
            kwargs = dict(kwargs)
            kwargs["public_only"] = public_only
            return {
                "cell_n": py_repr.cell_n,
                "n": py_repr.n,
                "psk": py_repr.psk if not public_only else "",
                "keymat": repr_yml(py_repr.keymat, **kwargs),
                "registry_pubkey": py_repr.registry_pubkey,
                "addr_local": str(py_repr.addr_local),
                "addr_remote": str(py_repr.addr_remote),
                "interface": py_repr.interface,
                "area": py_repr.area
            }
    
        def repr_py(self, yml_repr, **kwargs):
            return CellRouterPort(
                    cell_n=yml_repr["cell_n"],
                    n=yml_repr["n"],
                    psk=yml_repr["psk"],
                    keymat=repr_py(WireGuardKeyPair, yml_repr["keymat"]),
                    registry_pubkey=yml_repr["registry_pubkey"],
                    addr_local=ipaddress.ip_address(yml_repr["addr_local"]),
                    addr_remote=ipaddress.ip_address(yml_repr["addr_remote"]),
                    interface=yml_repr["interface"],
                    area=yml_repr["area"])


@TemplateRepresentation("wireguard-cfg","wg/router_root.conf")
class RegistryRouterPortWireguardConfig:
    def __init__(self, registry, cell):
        self.registry = registry
        self.cell = cell
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            # These values are currently ignored by the generated configuration
            allowed_ips = ["{}/{}".format(
                    py_repr.cell.router_port.addr_local,
                    UvnDefaults["registry"]["vpn"]["router"]["netmask"])]
            allowed_ips.extend(UvnDefaults["registry"]["vpn"]["router"]["allowed_ips"])
            return {
                "registry": repr_yml(py_repr.registry, **kwargs),
                "cell": repr_yml(py_repr.cell, **kwargs),
                "allowed_ips": allowed_ips
            }
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()

@TemplateRepresentation("wireguard-cfg","wg/router_cell.conf")
class CellRouterPortWireguardConfig:
    def __init__(self, registry, cell):
        self.registry = registry
        self.cell = cell
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            # These values are currently ignored by the generated configuration
            allowed_ips = ["{}/{}".format(
                    py_repr.cell.router_port.addr_remote,
                    UvnDefaults["registry"]["vpn"]["router"]["netmask"])]
            allowed_ips.extend(UvnDefaults["registry"]["vpn"]["router"]["allowed_ips"])
            return {
                "registry": repr_yml(py_repr.registry,
                                target_cell=py_repr.cell, deployment_id=None, **kwargs),
                "identity_db": repr_yml(py_repr.registry.identity_db,
                                target_cell=py_repr.cell, deployment_id=None, **kwargs),
                "cell": repr_yml(py_repr.cell, **kwargs),
                "allowed_ips": allowed_ips
            }
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()
