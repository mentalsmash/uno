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

from libuno.wg import WireGuardInterface
from libuno.tmplt import render
from libuno.cfg import UvnDefaults
from libuno.router_port import CellRouterPortWireguardConfig

from .vpn import UvnVpn, logger

class CellVpn(UvnVpn):
    def __init__(self,
            registry,
            cell,
            cell_record,
            cell_cfg,
            keep=False,
            interfaces=[]):
        self.cell = cell
        self.cell_record = cell_record
        self.cell_cfg = cell_cfg
        UvnVpn.__init__(self, registry, keep=keep, interfaces=interfaces)
        self.wg_particles = self._create_particles_connection()
        logger.debug("loaded cell vpn: {}/{}",
            self.cell.id.name, self.registry.deployment_id)

    def _get_interfaces(self):
        interfaces = UvnVpn._get_interfaces(self)
        interfaces.append(self.wg_particles)
        return interfaces

    def _create_backbone(self):
        wg_backbone = []
        if self.cell_cfg is not None:
            for b in self.cell_cfg.backbone:
                wg_config = render(b, "wireguard-cfg")
                wgi = WireGuardInterface(
                    b.interface,
                    b.addr_local,
                    UvnDefaults["registry"]["vpn"]["backbone2"]["netmask"],
                    wg_config,
                    keep=self.keep,
                    allowed_ips={ipaddress.ip_network(a)
                        for a in UvnDefaults["registry"]["vpn"]["router"]["allowed_ips"]})
                wg_backbone.append(wgi)
        return wg_backbone

    def _create_root_connection(self):
        wg_config = render(self.cell.registry_vpn, "wireguard-cfg")
        wgi = WireGuardInterface(
            self.cell.registry_vpn.interface,
            self.cell.registry_vpn.cell_ip,
            UvnDefaults["registry"]["vpn"]["registry"]["netmask"],
            wg_config,
            keep=self.keep,
            allowed_ips={ipaddress.ip_network("{}/{}".format(
                UvnDefaults["registry"]["vpn"]["registry"]["base_ip"],
                UvnDefaults["registry"]["vpn"]["registry"]["netmask"]))})
        return wgi

    def _create_router_connections(self):
        port_config = CellRouterPortWireguardConfig(self.registry, self.cell)
        wg_config = render(port_config, "wireguard-cfg")
        wgi = WireGuardInterface(
            self.cell.router_port.interface,
            self.cell.router_port.addr_local,
            UvnDefaults["registry"]["vpn"]["router"]["netmask"],
            wg_config,
            keep=self.keep,
            allowed_ips={ipaddress.ip_network(a)
                for a in UvnDefaults["registry"]["vpn"]["router"]["allowed_ips"]})
        return [wgi]

    def _create_particles_connection(self):
        wg_config = render(self.cell.particles_vpn, "wireguard-cfg")
        wgi = WireGuardInterface(
            self.cell.particles_vpn.interface,
            self.cell.particles_vpn.addr_local,
            self.cell.particles_vpn.network.prefixlen,
            wg_config,
            keep=self.keep)
        return wgi
