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
import shutil
import pathlib
import tempfile
import os
import types
from itertools import chain
import ipaddress
import rti.connextdds as dds

import libuno.log

from libuno import ip
from libuno.exception import UvnException
from libuno.cfg import UvnDefaults

from .peer import PeerStatus
from .agent import UvnAgent, logger
from .vpn_cell import CellVpn
from .dds_cell import CellParticipant
from .router_cell import CellRouter
from .router import RemoteSiteClashException

class CellAgent(UvnAgent):
    def __init__(self, registry_dir, keep=False, roaming=False, daemon=False,
            interfaces=[],
            assert_period=UvnDefaults["registry"]["agent"]["assert"]["registry"]):
        self.roaming = roaming
        self._uvn_status = self._mkuvnstatus()
        UvnAgent.__init__(self, registry_dir,
            keep=keep, assert_period=assert_period, daemon=daemon, interfaces=interfaces)

    ################################################################################
    # UvnAgent implementation
    ################################################################################
    def _get_participant_class(self):
        return CellParticipant, {
            "cell": self.registry.deployed_cell,
            "cell_cfg": self.registry.deployed_cell_config,
            "cell_record": self.registry.deployed_cell_record
        }
    
    def _get_vpn_class(self):
        return CellVpn, {
            "cell": self.registry.deployed_cell,
            "cell_record": self.registry.deployed_cell_record,
            "cell_cfg": self.registry.deployed_cell_config
        }

    def _get_router_class(self):
        return CellRouter, {
            "cell": self.registry.deployed_cell,
            "cell_cfg": self.registry.deployed_cell_config,
            "roaming": self.roaming
        }

    def _get_connection_test_peers(self):
        cell = self.registry.deployed_cell
        cell_cfg = self.registry.deployed_cell_config
        peers = [{
            "name": "uvn-registry",
            "address": cell.registry_vpn.registry_address,
            "tags": ["registry", "vpn"],
            "cell": cell.id.name
        }]
        peers.extend(super(CellAgent, self)._get_connection_test_peers())
        logger.info("initial test peers: {}", len(peers))
        return peers

    def _get_nameserver_entries(self):
        cell = self.registry.deployed_cell

        entries = [
            # record for registry vpn address
            {
                "hostname": UvnDefaults["nameserver"]["vpn"]["cell_host_fmt"].format(cell.id.name, self.registry.address),
                "address": cell.registry_vpn.cell_ip,
                "server": cell.id.name,
                "tags": ["cell", "uvn", "vpn"]
            },
            # record for vpn address
            {
                "hostname": UvnDefaults["nameserver"]["vpn"]["registry_host_fmt"].format(self.registry.address),
                "address": cell.registry_vpn.registry_address,
                "server": self.registry.address,
                "tags": ["registry", "vpn", "uvn"]
            }
        ]

        entries.extend(self._get_nameserver_entries_router_cell(cell))

        # Assert records for backbone addresses
        cell_cfg = self.registry.deployed_cell_config
        if cell_cfg is not None:
            entries.extend(self._get_nameserver_entries_backbone(cell, cell_cfg))

        return entries
    
    def _get_nameserver_entries_backbone(self, cell, cell_cfg):
        entries = [
            {
                "hostname": UvnDefaults["nameserver"]["backbone"]["cell_host_fmt"].format(
                    bbone.peers[0].name, cell.id.name, self.registry.address),
                "address": bbone.addr_local,
                "server": cell.id.name,
                "tags": ["cell", "uvn", "backbone", f"b{i}", self.registry.deployment_id]
            } for i, bbone in enumerate(filter(lambda b: len(b.peers) == 1, cell_cfg.backbone))
        ]
        return entries
    
    def _get_nameserver_entries_router_cell(self, cell):
        return [
            {
                "hostname": UvnDefaults["nameserver"]["router"]["cell_host_fmt"].format(
                    cell.id.name, self.registry.address),
                "address": cell.router_port.addr_local,
                "server": cell.id.name,
                "tags": ["cell", "uvn", "router"]
            },
            {
                "hostname": UvnDefaults["nameserver"]["router"]["registry_host_fmt"].format(
                    cell.id.name, self.registry.address),
                "address": cell.router_port.addr_remote,
                "server": cell.id.name,
                "tags": ["cell", "uvn", "router"]
            }
        ]
    
    def _get_published_nameserver_entries(self):
        dns_recs = list(self.registry.nameserver.db.values())
        cell_name = self.registry.deployed_cell.id.name
        return [{
            "server": cell_name,
            "record": r
        } for r in filter(lambda r: r.server == cell_name, dns_recs)]

    def _list_local_sites(self):
        if self.roaming:
            return []
        return list(self.vpn.list_local_networks())
    
    ############################################################################
    # Agent status events
    ############################################################################
    def _on_status_assert(self, **kwargs):
        do_assert = super(CellAgent, self)._on_status_assert(**kwargs)
        if not do_assert:
            return
        self.publish.cell_info(
            self.registry.deployed_cell,
            self.registry.deployed_cell_config)
        if kwargs.get("init"):
            self.publish.dns_entries()

    def _on_status_start(self):
        super(CellAgent, self)._on_status_start()
        # Allow all local sites on backbone and router interfaes:
        for s in self._local_sites:
            logger.info("[enable] local network: {}/{}", s["nic"], s["subnet"])
            self._route_enable_on_backbone(s["subnet"])
            self._route_enable_on_registry(s["subnet"])
    
    def _on_status_reset(self):
        super(CellAgent, self)._on_status_reset()
        self._uvn_status = self._mkuvnstatus()
    
    def _mkuvnstatus(self):
        return types.SimpleNamespace(
            detected=False,
            active_cells=set())

    ############################################################################
    # Agent routing events
    ############################################################################
    def _backbone_peer(self, cell_name):
        backbone = []
        if self.registry.deployed_cell_config:
            backbone = self.registry.deployed_cell_config.backbone
        return next(filter(lambda r: r[1].name == cell_name,
                [(bbone, p) for bbone in backbone for p in bbone.peers]),
                (None, None))

    def on_route_enabled(self, router, net):
        # Assert network on backbone interface to enable routing via peers
        self._route_enable_on_backbone(net.subnet)
        # Assert network on router interface to enable routing via registry
        self._route_enable_on_registry(net.subnet)
        # Perform a connection test
        self.connection_test.perform_test()
        # Publish updated state
        self._on_status_assert()

    def _route_assert_peer_network(self, peer, net):
        # Find peer and backbone connection for remote network
        bbone, p = self._backbone_peer(peer.cell.id.name)
        self.router.assert_remote_network(
            f"{peer.cell.id.name}/{net.nic}",
            adjacent=p is not None,
            cell_name=peer.cell.id.name,
            nic=net.nic,
            subnet=net.subnet,
            mask=net.mask,
            gw=net.gw,
            route_nic=bbone.interface if bbone else None,
            route_peer=p.pubkey if p else None,
            route_gw=p.addr_remote if p else None)
    
    def _route_enable_on_registry(self, subnet):
        logger.activity("[enable] network on router port: {}", subnet)
        self.vpn.assert_remote_network(
            self.registry.router_ports.keymat.pubkey,
            self.registry.deployed_cell.router_port.interface,
            subnet)
    
    def _route_enable_on_backbone(self, subnet):
        if not self.registry.deployed_cell_config:
            return
        logger.activity("[enable] network on backbone ports: {}", subnet)
        for bbone in self.registry.deployed_cell_config.backbone:
            for p in bbone.peers:
                self.vpn.assert_remote_network(
                    p.pubkey, bbone.interface, subnet)

    ############################################################################
    # "uvn_info" DataReader handlers
    ############################################################################
    def _on_reader_matched_uvn_info(self, participant, reader, status):
        if status.current_count_change < 0:
            count = status.current_count_change * -1
            logger.warning("{} uvn registry {} unmatched",
                count, "writers" if count > 1 else "writer")
            self.connection_test.perform_test()

    def _on_reader_data_uvn_info(self, participant, reader, reader_condition):
        return self._read_data_and_process(
            participant, reader, reader_condition,
            on_data=self._on_reader_uvn_info_received)

    def _on_reader_uvn_info_received(self, participant, reader, data, info):
        address = data["id.address"]
        deployment_id = data["deployment_id"]
        if not self._accept_deployment_id(deployment_id):
            logger.warning("ignored uvn update: {}@{}", address, deployment_id)
            return

        cells = {c["name"] for c in data["cells"]}
        logger.debug("[rcvd] uvn info:\n{}", data)

        already_detected = self._uvn_status.detected
        already_active = set(self._uvn_status.active_cells)
        new_active = cells - already_active
        not_active = already_active - cells
        self._uvn_status.detected = True
        self._uvn_status.active_cells = cells

        if not already_detected:
            logger.info("[uvn][{}] detected registry [{}]", address, ", ".join(cells))

            subnet_addr = ip.ipv4_from_bytes(data["router_subnet.address.value"])
            subnet_mask = data["router_subnet.mask"]
            if int(subnet_addr) > 0:
                subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
                logger.info("[enable] router network: {}", subnet)
                self._route_enable_on_registry(subnet)
                self._route_enable_on_backbone(subnet)

            subnet_addr = ip.ipv4_from_bytes(data["backbone_subnet.address.value"])
            subnet_mask = data["backbone_subnet.mask"]
            if int(subnet_addr) > 0:
                subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
                logger.info("[enable] backbone network: {}", subnet)
                self._route_enable_on_registry(subnet)
                self._route_enable_on_backbone(subnet)
        
        if new_active:
            logger.info("[uvn][{}] active cells [{}]", address, ", ".join(new_active))
        if not_active:
            logger.warning("[uvn][{}] inactive cells [{}]", address, ", ".join(not_active))

        for s in data["cell_sites"]:
            self._on_cell_site_received(s)

        for p in data["cells"]:
            self._on_cell_peer_received(p)

    ############################################################################
    # "deployment" DataReader handlers
    ############################################################################
    def _on_reader_data_deployment(self, participant, reader, reader_condition):
        return self._read_data_and_process(
            participant, reader, reader_condition,
            on_data=self._on_reader_deployment_received)

    def _on_reader_deployment_received(self, participant, reader, data, info):
        with self._lock:
            if not len(data["id"]):
                logger.warning("[registry] invalid deployment id received")
                return
            if (self.registry.deployment_id == data["id"]):
                logger.info("[registry] cell at current deployment: {}",
                    data["id"])
                return
            elif (self.registry.bootstrapped
                and self.registry.deployment_id > data["id"]):
                logger.warning("[registry] stale deployment received: {}",
                    data["id"])
                return
            logger.info("[registry] new deployment received: {}", data["id"])
            tmp_file_fd, tmp_file_path = tempfile.mkstemp(
                prefix="uvn-deployment-{}-{}-".format(self.registry.address,
                    data["id"]))
            tmp_file_path = pathlib.Path(tmp_file_path)
            extracted = False
            queued = False
            ok = False
            try:
                with tmp_file_path.open("wb") as output:
                    output.write(data["package"])
                extracted = True
                logger.debug("extracted installer: {}", tmp_file_path)
                queued = self._request_reload(
                    deployment_id=data["id"], installer=tmp_file_path)
            except Exception as e:
                logger.exception(e)
            finally:
                os.close(tmp_file_fd)
                if not extracted:
                    logger.error("failed to extract: {}", tmp_file_path)
                elif not queued:
                    logger.warning("not queued: {}", tmp_file_path)
                if not queued:
                    if not self._keep:
                        tmp_file_path.unlink()
                    else:
                        logger.warning("[tmp] not deleted: {}", tmp_file_path)

    def _get_peer_backbone_ports(self, cell_name):
        ports = []
        if self.registry.deployed_cell_config:
            for bbone in self.registry.deployed_cell_config.backbone:
                for p in bbone.peers:
                    if p.name != cell_name:
                        continue
                    ipaddr = dds.DynamicData(self.participant.types["ip_address"])
                    ipaddr["value"] = ip.ipv4_to_bytes(p.addr_remote)
                    ports.append(ipaddr)
        return ports
