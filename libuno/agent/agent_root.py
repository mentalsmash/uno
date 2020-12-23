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
import types
import pathlib
import itertools
import ipaddress
import rti.connextdds as dds

import libuno.ip as ip
from libuno.cfg import UvnDefaults
from .agent import UvnAgent, logger
from .vpn_root import RootVpn
from .dds_root import RootParticipant
from .router_root import RootRouter
from .router import RemoteSiteClashException

class RootAgent(UvnAgent):
    
    def __init__(self, registry_dir, keep=False, daemon=False,
            interfaces=[],
            assert_period=UvnDefaults["registry"]["agent"]["assert"]["cell"]):
        self._cells = {}
        UvnAgent.__init__(self, registry_dir,
            keep=keep, assert_period=assert_period, daemon=daemon, interfaces=interfaces)
    
    ################################################################################
    # UvnAgent implementation
    ################################################################################
    def _get_participant_class(self):
        return RootParticipant, {}
    
    def _get_vpn_class(self):
        return RootVpn, {}

    def _get_router_class(self):
        # Don't create a router for root agent
        return RootRouter, {}

    def _get_connection_test_peers(self):
        peers = [{
            "name": p.cell_name,
            "address": p.cell_ip,
            "tags": ["cell", "vpn", "peer"],
            "cell": p.cell_name
        } for p in self.registry.vpn_config.peers]
        peers.extend(super(RootAgent, self)._get_connection_test_peers())
        logger.info("initial test peers: {}", len(peers))
        return peers

    def _get_nameserver_entries(self):
        peers = [
            # record for vpn address
            {
                "hostname": UvnDefaults["nameserver"]["vpn"]["registry_host_fmt"].format(self.registry.address),
                "address": self.registry.vpn_config.registry_address,
                "server": self.registry.address,
                "tags": ["registry", "vpn", "uvn"]
            }
        ]
        # peers.extend([
        #     {
        #         "hostname": UvnDefaults["nameserver"]["vpn"]["cell_host_fmt"].format(cell.id.name, self.registry.address),
        #         "address": cell.registry_vpn.cell_ip,
        #         "server": cell.id.name,
        #         "tags": ["cell", "vpn", "uvn"]
        #     } for cell in self.registry.cells.values()
        # ])

        return peers
    
    def _get_published_nameserver_entries(self):
        return [{
            "server": e.server,
            "record": e
        } for e in self.registry.nameserver.db.values()
            if e.server == self.registry.address]
    
    ############################################################################
    # Agent status events
    ############################################################################
    def _on_status_assert(self, **kwargs):
        do_assert = super(RootAgent, self)._on_status_assert(**kwargs)
        if not do_assert:
            return
        self.publish.uvn_info()
        if kwargs.get("init"):
            self.publish.deployments()
            self.publish.dns_entries()

    def _on_status_start(self):
        super(RootAgent, self)._on_status_start()
        # Assert each router port on every other router port
        if self.registry.router_subnet:
            self._route_enable_on_registry(self.registry.router_subnet)

        # Assert backbone ports to allow routing via registry if needed
        if self.registry.backbone_subnet:
            self._route_enable_on_registry(self.registry.backbone_subnet)

    ############################################################################
    # Agent routing events
    ############################################################################
    def on_route_enabled(self, router, net):
        # Assert network on all router interfaces
        self._route_enable_on_registry(net.subnet)
        # Perform a connection test
        self.connection_test.perform_test()
        # Publish updated state
        self._on_status_assert()

    def _route_assert_peer_network(self, peer, net):
        port = self.registry.router_ports.find_port_by_cell(peer.cell.id.n)
        self.router.assert_remote_network(
            f"{peer.cell.id.name}/{net.nic}",
            adjacent=True,
            cell_name=peer.cell.id.name,
            nic=net.nic,
            subnet=net.subnet,
            mask=net.mask,
            gw=net.gw,
            route_nic=port.interface_registry,
            route_peer=port.keymat.pubkey,
            route_gw=port.addr_local)
    
    def _route_enable_on_registry(self, subnet, skip=[]):
        logger.activity("[enable] network on router ports: {}", subnet)
        for p in self.registry.router_ports:
            if skip and p in skip:
                continue
            self.vpn.assert_remote_network(
                p.keymat.pubkey, p.interface_registry, subnet)

    def _get_peer_backbone_ports(self, cell_name):
        ports = []
        if self.registry.latest_deployment:
            cell_cfg = self.registry.latest_deployment.cell_config(cell_name)
            for bbone in cell_cfg.backbone:
                ipaddr = dds.DynamicData(self.participant.types["ip_address"])
                ipaddr["value"] = ip.ipv4_to_bytes(bbone.addr_local)
                ports.append(ipaddr)
        return ports
