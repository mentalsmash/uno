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
from libuno.router_port import RegistryRouterPortWireguardConfig

from .vpn import UvnVpn, logger

class RootVpn(UvnVpn):
    def __init__(self, registry, keep=False, interfaces=[]):
        UvnVpn.__init__(self, registry, keep=keep, interfaces=interfaces)
        logger.activity("loaded root vpn: {}", self.registry.address)

    def _create_root_connection(self):
        wg_config = render(self.registry.vpn_config, "wireguard-cfg")
        wg_root = WireGuardInterface(
                        self.registry.vpn_config.interface,
                        self.registry.vpn_config.registry_address,
                        UvnDefaults["registry"]["vpn"]["registry"]["netmask"],
                        wg_config,
                        keep=self.keep)
        return wg_root

    def _create_router_connections(self):
        result = []
        for cell in self.registry.cells.values():
            port_config = RegistryRouterPortWireguardConfig(self.registry, cell)
            wg_config = render(port_config, "wireguard-cfg")
            wgi = WireGuardInterface(
                cell.router_port.interface_registry,
                cell.router_port.addr_remote,
                UvnDefaults["registry"]["vpn"]["router"]["netmask"],
                wg_config,
                keep=self.keep,
                allowed_ips={ipaddress.ip_network(a)
                    for a in UvnDefaults["registry"]["vpn"]["router"]["allowed_ips"]})
            result.append(wgi)
        return result
