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
import pathlib

import libuno.log
logger = libuno.log.logger("uvn.particle")

from libuno.wg import WireGuardKeyPair
from libuno.psk import PresharedKeys
from libuno.tmplt import TemplateRepresentation, render
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.identity import UvnIdentityDatabase
from libuno.cfg import UvnDefaults
from libuno import qr

@TemplateRepresentation("wireguard-cfg", "wg/particle_to_cell.conf")
class ParticleToCellConfig:
    def __init__(self,
            registry_address,
            privkey,
            address,
            address_mask,
            cell_name,
            cell_address,
            cell_pubkey,
            cell_endpoint,
            cell_psk):
        self.registry_address = registry_address
        self.privkey = privkey
        self.address = address
        self.address_mask = address_mask
        self.cell_name = cell_name
        self.cell_address = cell_address
        self.cell_pubkey = cell_pubkey
        self.cell_endpoint = cell_endpoint
        self.cell_psk = cell_psk

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return {
                "registry_address": py_repr.registry_address,
                "privkey": py_repr.privkey,
                "address": str(py_repr.address),
                "address_mask": py_repr.address_mask,
                "cell_name": py_repr.cell_name,
                "cell_address": py_repr.cell_address,
                "cell_endpoint": py_repr.cell_endpoint,
                "cell_psk": py_repr.cell_psk,
            }
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()

class Particle:
    def __init__(self,
            name,
            n,
            contact,
            psks=None,
            keymat=None):
        self.name = name
        self.n = n
        self.contact = contact
        if keymat is None:
            self.keymat = WireGuardKeyPair.generate()
        else:
            self.keymat = keymat
        if psks is None:
            self.psks = PresharedKeys()
        else:
            self.psks = psks
        
        self.configs = {}
    
    def clear(self):
        self.configs.clear()

    def generate_config(self, registry, cell):
        psk = self.psks.assert_psk(self.name, cell.id.name)

        cfg = ParticleToCellConfig(
            registry_address=registry.address,
            privkey=self.keymat.privkey,
            address=cell.particles_vpn.addr_local + self.n,
            address_mask=cell.particles_vpn.network.prefixlen,
            cell_name=cell.id.name,
            cell_address=cell.particles_vpn.addr_local,
            cell_endpoint=cell.particles_vpn.endpoint,
            cell_pubkey=cell.id.keymat.particles.pubkey,
            cell_psk=psk
        )

        self.configs[cell.id.name] = cfg

        return cfg
    
    def cell_config(self, cell_name):
        return self.configs.get(cell_name)
    
    def render(self, base_dir):
        base_dir = pathlib.Path(base_dir)
        for cell_name, cfg in self.configs.items():
            cfg_file = base_dir / UvnDefaults["registry"]["vpn"]["particles"]["particle_cfg_fmt"].format(
                cfg.registry_address,
                cfg.cell_name,
                self.name)
            qr_file = base_dir / UvnDefaults["registry"]["vpn"]["particles"]["particle_qr_fmt"].format(
                cfg.registry_address,
                cfg.cell_name,
                self.name)
            
            render(cfg, "wireguard-cfg", to_file=cfg_file)
            qr.encode_file(cfg_file, qr_file, format="png")
            logger.debug("generated particle: {} -> {}",
                self.name, cfg.cell_name)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            tgt_particle = kwargs.get("tgt_particle")
            pkg_cell = kwargs.get("pkg_cell")
            if pkg_cell:
                kwargs["psk_cells"] = [py_repr.name, pkg_cell]
            public_only = (kwargs.get("public_only")
                or (tgt_particle is not None and
                        tgt_particle != py_repr.name)
                or pkg_cell is not None)

            kwargs["public_only"] = public_only

            return {
                "name": py_repr.name,
                "n": py_repr.n,
                "contact": py_repr.contact,
                "psks": repr_yml(py_repr.psks, **kwargs),
                "keymat": repr_yml(py_repr.keymat, **kwargs)
            }
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = Particle(
                        name=yml_repr["name"],
                        n=yml_repr["n"],
                        contact=yml_repr["contact"],
                        psks=repr_py(PresharedKeys, yml_repr["psks"], **kwargs),
                        keymat=repr_py(WireGuardKeyPair, yml_repr["keymat"], **kwargs))
            return py_repr

