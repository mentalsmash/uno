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

from libuno.exception import UvnException

import libuno.log
from libuno import ip

logger = libuno.log.logger("uvn.vpn")

class UvnVpn:
    def __init__(self, registry, keep=False):
        self.registry = registry
        self.keep = keep
        self.wg_root = self._create_root_connection()
        self.wg_backbone = self._create_backbone()
        self.wg_router = self._create_router_connections()
        self._nat_nets = []
        self._nat_wgs = []
    
    def __iter__(self):
        return iter(chain([self.wg_root], self.wg_backbone, self.wg_router))

    def _create_root_connection(self):
        return None
    
    def _create_router_connections(self):
        return []
    
    def _create_backbone(self):
        return []
    
    def start(self):
        logger.debug("starting UVN vpn: {}", self.registry.address)
        self.wg_root.create()
        self.wg_root.bring_up()
        for wg in self.wg_router:
            wg.create()
            wg.bring_up()
        for wg in self.wg_backbone:
            wg.create()
            wg.bring_up()
        self._enable_nat()
        logger.activity("started registry vpn: {}", self.registry.address)
    
    def stop(self):
        logger.debug("stopping UVN vpn: {}", self.registry.address)
        for wg in self.wg_backbone:
            wg.tear_down()
            wg.delete()
        for wg in self.wg_router:
            wg.tear_down()
            wg.delete()
        self.wg_root.tear_down()
        self.wg_root.delete()
        self._disable_nat()
        logger.activity("stopped UVN vpn: {}", self.registry.address)

    def list_local_networks(self):
        return ip.list_local_networks(skip=list(self.list_wg_interfaces()))
    
    def list_wg_networks(self):
        return ip.list_local_networks(interfaces=list(self.list_wg_interfaces()))

    def list_local_interfaces(self):
        return map(lambda nic_r: nic_r[0],
                    ip.list_local_nics(skip=list(self.list_wg_interfaces())))

    def list_backbone_interfaces(self):
        return map(lambda wg: wg.interface, self.wg_backbone)
    
    def list_vpn_interfaces(self):
        return [self.wg_root.interface]
    
    def list_router_interfaces(self):
        return map(lambda wg: wg.interface, self.wg_router)
    
    def list_wg_interfaces(self):
        return chain(self.list_vpn_interfaces(),
                     self.list_backbone_interfaces(),
                     self.list_router_interfaces())
    
    def find_wg_interface(self, name):
        if self.wg_root.interface == name:
            return self.wg_root
        intf = next(filter(lambda wg: wg.interface == name, self.wg_backbone), None)
        if intf:
            # logger.warning("DEBUG found backbone {}: {}", name, intf)
            return intf
        intf = next(filter(lambda wg: wg.interface == name, self.wg_router))
        # logger.warning("DEBUG found router {}: {}", name, intf)
        return intf


    def _enable_nat(self):
        if self._nat_wgs:
            raise UvnException("[NAT] already enabled")

        try:
            self._nat_nets = []
            self._nat_wgs = []
            wg_nics = list(self.list_wg_interfaces())
            local_nets = list(ip.list_local_networks(skip=wg_nics))
            logger.activity("[NAT][enable] wireguard interfaces: {}", wg_nics)
            for nic in wg_nics:
                ip.ipv4_enable_forward(nic)
                ip.ipv4_enable_output_nat(nic)
                self._nat_wgs.append(nic)
            logger.activity("[NAT][enable] local LANs: {}",
                list(map(lambda n: n["nic"],local_nets)))
            for net in local_nets:
                ip.ipv4_enable_output_nat(net["nic"])
                self._nat_nets.append(net)
        except Exception as e:
            logger.exception(e)
            logger.error("failed to enable NAT for local networks")
            # Try to disable NAT on already enabled nics
            self._disable_nat()
            raise e
    
    def _disable_nat(self, ignore_errors=False):
        if not self._nat_wgs:
            # Clear self._nat_net anyway, since we might have beeen called
            # by _enable_nat() to cleanup on error
            self._nat_nets = []
            logger.debug("[NAT] already disabled")
            return

        try:
            logger.activity("[NAT][disable] wireguard interfaces: {}", self._nat_wgs)
            for nic in self._nat_wgs:
                ip.ipv4_disable_forward(nic,
                    ignore_errors=ignore_errors)
                ip.ipv4_disable_output_nat(nic,
                    ignore_errors=ignore_errors)
            logger.activity("[NAT][disable] local LANs: {}",
                list(map(lambda n: n["nic"], self._nat_nets)))
            for net in self._nat_nets:
                ip.ipv4_disable_output_nat(net["nic"],
                    ignore_errors=ignore_errors)
        except Exception as e:
            if not ignore_errors:
                logger.exception(e)
                logger.error("failed to disable NAT for local networks")
                raise e
        finally:
            self._nat_wgs = []
            self._nat_nets = []
    
    def assert_remote_network(self, peer, nic, subnet):
        wg_i = self.find_wg_interface(nic)
        wg_i.allow_ips(peer, f"{subnet}")
    
    def remove_remote_network(self, peer, nic, subnet):
        wg_i = self.find_wg_interface(nic)
        wg_i.disallow_ips(peer, f"{subnet}")
