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
import pathlib
import threading
import time
import shutil
import itertools
import tempfile
import ipaddress
import types
import os
import lockfile
from functools import partial
import rti.connextdds as dds

from libuno import data as StaticData
from libuno import ip
from libuno.reg import UvnRegistry
from libuno.identity import UvnIdentityDatabase, CryptoError
from libuno.helpers import wait_for_signals, Timestamp, process_queue, PeriodicFunctionThread, ExtraClassMethods
from libuno.ping import PeerConnectionsTester, PeerConnectionsListener
from libuno.exception import UvnException
from libuno.cfg import UvnDefaults
from libuno.install import UvnCellInstaller
from libuno.ns import UvnNameserverListener
from libuno.tmplt import render

from .publisher import methods as publish_fns
from .dds import UvnParticipantListener, UvnParticipantListener
from .router import UvnRouterListener
from .peer import PeerStatus
from .peer_manager import UvnPeerManager, UvnPeerManagerListener
from .peer_cb import AgentPeerCallbacks
from .proc import AgentProc

import libuno.log
logger = libuno.log.logger("uvn.agent")

class UvnAgent(UvnParticipantListener,
               AgentPeerCallbacks,
               PeerConnectionsListener,
               UvnRouterListener,
               UvnNameserverListener,
               UvnPeerManagerListener):

    publish = ExtraClassMethods(publish_fns)

    @staticmethod
    def load(registry_dir, keep=False, roaming=False, daemon=False, interfaces=[]):
        from .agent_cell import CellAgent
        from .agent_root import RootAgent
        
        registry_dir = pathlib.Path(registry_dir)
        identity_db = UvnIdentityDatabase.load(basedir=registry_dir)
        registry = UvnRegistry.load(identity_db)
        
        if registry.packaged:
            return CellAgent(registry, keep=keep, roaming=roaming, daemon=daemon, interfaces=interfaces)
        else:
            if roaming:
                raise UvnException("roaming mode not supported for root agent")
            return RootAgent(registry, keep=keep, daemon=daemon, interfaces=interfaces)
    
    def __init__(self, registry, assert_period, keep=False, daemon=False,
            interfaces=[],
            basedir=UvnDefaults["registry"]["agent"]["basedir"],
            logfile=UvnDefaults["registry"]["agent"]["log_file"]):
        # Try to create and lock a pid file to guarantee that only one
        # uvn agent is running on the system
        self.registry = registry
        self._basedir = pathlib.Path(basedir)
        self._logfile = self._basedir / logfile
        self._daemon = daemon
        if not daemon:
            libuno.log.output_file(self._logfile)
        self._interfaces = list(interfaces)
        self._keep = keep
        self._loaded = False
        self._started = False
        self._sem_wait = threading.Semaphore()
        self._sem_wait.acquire()
        self._sem_reload = threading.Semaphore()
        self._sem_reload.acquire()
        self._sem_deploy = threading.Semaphore()
        self._sem_deploy.acquire()
        self._sem_exit = threading.Semaphore()
        self._sem_exit.acquire()
        self._lock = threading.RLock()
        self._ts_created = Timestamp.now()
        self._ts_loaded = None
        self._ts_started = None
        self.vpn = None
        self.connection_test = None
        self.router = None
        self.participant = None
        self._rs = None
        self._peers = UvnPeerManager(listener=self)
        self._reload_queue = []
        self._deploy_queue = []
        self._status = PeerStatus.CREATED
        self._local_sites = []
        self._private_ports = set()
        self._proc = None
        self._assert_period = assert_period
        self._default_gw = None
        logger.debug("loading uvn agent")
        self._load()

    ############################################################################
    # General helpers
    ############################################################################
    def agent_id(self, brief=False):
        if self.registry.packaged:
            if brief:
                fmt = UvnDefaults["registry"]["agent"]["id"]["cell_brief"]
                fmt_args = [self.registry.deployed_cell.id.name,
                            self.registry.deployment_id]
            else:
                fmt = UvnDefaults["registry"]["agent"]["id"]["cell"]
                fmt_args = [self.registry.deployed_cell.id.name,
                            self.registry.address,
                            self.registry.deployment_id]
        else:
            deployment_id = UvnDefaults["registry"]["deployment_bootstrap"]
            if self.registry.latest_deployment:
                deployment_id = self.registry.latest_deployment.id
            if brief:
                fmt = UvnDefaults["registry"]["agent"]["id"]["registry_brief"]
                fmt_args = [deployment_id]
            else:
                fmt = UvnDefaults["registry"]["agent"]["id"]["registry"]
                fmt_args = [self.registry.address, deployment_id]

        return fmt.format(*fmt_args)

    ############################################################################
    # Abstract methods
    ############################################################################
    def _get_vpn_class(self):
        raise NotImplementedError()

    def _get_participant_class(self):
        raise NotImplementedError()

    def _get_router_class(self):
        raise NotImplementedError()

    def _get_nameserver_entries(self):
        raise NotImplementedError()
    
    def _get_published_nameserver_entries(self):
        raise NotImplementedError()
    
    def _list_local_sites(self):
        return list(self.vpn.list_local_networks())

    def _get_connection_test_peers(self):
        peers = []
        for ns_rec in self.registry.nameserver.db.values():
            peers.append({
                "name": f"{ns_rec.hostname}",
                "address": ns_rec.address,
                "tags": ns_rec.tags,
                "cell": ns_rec.server
            })
        return peers

    ############################################################################
    # Helper objects
    ############################################################################
    def _create_connection_test(self, peers):
        logger.debug("ping peers: {}", peers)
        return PeerConnectionsTester(peers, listener=self)
    
    def _create_vpn(self, cls, extra):
        logger.debug("agent vpn: {}", cls)
        return cls(registry=self.registry, keep=self._keep, interfaces=self._interfaces, **extra)
    
    def _create_router(self, cls, extra):
        logger.debug("agent router: {}", cls)
        basedir = self._basedir / UvnDefaults["router"]["run_dir"]
        return cls(basedir=basedir, registry=self.registry, vpn=self.vpn, listener=self, **extra)
    
    def _create_participant(self, cls, extra):
        logger.debug("agent participant: {}", cls)
        cfg_dir = self._basedir / UvnDefaults["dds"]["dir"]
        profile_file = cfg_dir / UvnDefaults["dds"]["profile_file"]
        with StaticData.dds_profile_file().open() as profile_file_tmplt:
            render({
                "registry_address": self.registry.address,
                "cell_name": self.registry.deployed_cell.id.name
                                if self.registry.packaged
                                else self.agent_id(),
                "deployment_id": self.registry.latest_deployment.id
                    if self.registry.latest_deployment else
                    UvnDefaults["registry"]["deployment_bootstrap"]
            }, profile_file_tmplt.read(),
            to_file=profile_file,
            inline=True)
        return cls(self._basedir, self.registry,
            listener=self, profile_file=str(profile_file), **extra)
    
    ############################################################################
    # Agent status events
    ############################################################################
    def on_participant_started(self, participant):
        logger.activity("[{}][started] dds participant", self.agent_id())
        self._on_status_start()

    def on_participant_stopped(self, participant):
        logger.activity("[{}][stopped] dds participant", self.agent_id())

    
    def _on_status_assert(self, **kwargs):
        logger.activity("[{}][{}] assert status{}",
            self.agent_id(),
            self._status,
            " [initial]" if kwargs.get("init") else
            " [stopped]" if kwargs.get("stopped") else
            "")
        return (self.participant is not None)
    
    def _on_status_reset(self):
        self._peers.clear()
        self.registry.nameserver.clear()
        self.router.clear()
        self._status = PeerStatus.CREATED
        logger.activity("[reset] agent: {}", self.agent_id())
    
    def _on_status_start(self):
        # Assert peers for every known cell in the registry
        # Skip the registry's own "deployed cell" if packaged
        for c in self.registry.cells.values():
            if self.registry.packaged and c == self.registry.deployed_cell:
                continue
            self._peers.create_peer(c)

        self._status = PeerStatus.STARTED
        logger.activity("[started] agent: {}", self.agent_id())
        # Start agent's status assertion thread
        self._on_status_assert(init=True)
        # self._assert_thread = PeriodicFunctionThread(
        #     self._on_status_assert, period=self._assert_period)
        # self._assert_thread.start()
        # Start and trigger connection tester
        self.connection_test.start()
        self.connection_test.perform_test()
    
    def _on_status_stop(self):
        self._status = PeerStatus.STOPPED
        # Publish updated agent's status
        self._on_status_assert(stopped=True)
        logger.activity("[stopped] agent: {}", self.agent_id())

    ############################################################################
    # Agent routing events
    ############################################################################
    def _route_assert_peer_network(self, peer, net):
        raise NotImplementedError()
    
    ############################################################################
    # Agent runtime ctrl
    ############################################################################
    def _load(self):
        (self._vpn_cls,
         self._vpn_extra) = self._get_vpn_class()
        (self._router_cls,
         self._router_extra) = self._get_router_class()
        (self._participant_cls,
         self._participant_extra,) = self._get_participant_class()
        self._connection_test_peers = self._get_connection_test_peers()

        self.vpn = self._create_vpn(self._vpn_cls, self._vpn_extra)
        self.router = self._create_router(self._router_cls, self._router_extra)
        self.participant = self._create_participant(
             self._participant_cls, self._participant_extra)
        self.connection_test = self._create_connection_test(
            self._connection_test_peers)
        # register agent as the nameserver's listener
        self.registry.nameserver.listener = self
        # Determine default gateway
        self._default_gw = ip.ipv4_default_gateway()
        # Read network interfaces to determine the list of networks to which
        # the agent is attached
        self._local_sites = self._list_local_sites()
        # Determine list of private addresses on which to listen
        self._private_ports = {n["address"] for n in self._local_sites}
        self._loaded = True
        self._ts_loaded = Timestamp.now()
        logger.info("[loaded] UVN agent: {}", self.agent_id())

        if self.registry.packaged:
            if not self.registry.bootstrapped:
                logger.warning("no deployment loaded")
            elif not self.registry.deployed_cell_config:
                raise UvnException(f"configuration not found: {self.registry.deployed_cell.id.name}@{self.registry.deployment_id}")

    def start(self, nameserver=False, localhost_only=False):
        if self._started:
            raise RuntimeError("already started")
        try:
            ip.ipv4_enable_forwarding()
            self.vpn.start()
            self.router.start()
            if nameserver:
                for e in self._get_nameserver_entries():
                    self.registry.nameserver.assert_record(**e)
                basedir = self._basedir / UvnDefaults["nameserver"]["run_dir"]
                self.registry.nameserver.start(basedir, localhost_only=localhost_only)
            self.participant.start()
            self._started = True
            self._ts_started = Timestamp.now()
            self._proc = AgentProc(self)
            self._proc.start()
            logger.info("[started] UVN agent: {}", self.agent_id())
            libuno.log.global_prefix(self.agent_id(brief=True))
        except Exception as e:
            logger.exception(e)
            logger.error("failed to start agent")
            # Try to reset state
            self.stop()
            raise e

    def stop(self):
        if not self._started:
            logger.debug("agent already stopped")
            return
        if not self.participant:
            logger.debug("agent not started (no participant)")
            return
        try:
            if self._proc:
                self._proc.stop()
                self._proc = None
            self._on_status_stop()
            self.connection_test.stop()
            self.participant.stop()
            self.registry.nameserver.stop()
            self.router.stop()
            self.vpn.stop()
            logger.info("[stopped] UVN agent: {}", self.agent_id())
            libuno.log.global_prefix(None)
        except Exception as e:
            logger.exception(e)
            logger.error("failed to stop agent")
            raise e
        finally:
            try:
                del self.connection_test
            except Exception as e:
                logger.exception(e)
                logger.error("failed to delete connection test")
            try:
                del self.participant
            except Exception as e:
                logger.exception(e)
                logger.error("failed to delete participant")
            self.connection_test = None
            self.participant = None
            self._started = False

    ############################################################################
    # Agent main()
    ############################################################################
    def main(self, daemon=False):
        try:
            while True:
                if daemon:
                    logger.debug("uvnd waiting...")
                    self._sem_wait.acquire()
                else:
                    logger.debug("uvn agent waiting...")
                    wait_for_signals(self._sem_wait, signals={
                        "SIGINT": self._request_exit,
                        "SIGUSR1": self._request_reload,
                        "SIGUSR2": self._request_deploy
                    }, logger=logger)
                logger.trace("main thread awaken")
                if self._sem_exit.acquire(blocking=False):
                    return
                while self._sem_deploy.acquire(blocking=False):
                    self._process_deploy_requests()
                while self._sem_reload.acquire(blocking=False):
                    self._process_reload_requests()
        finally:
            self.stop()
            logger.info("[main] agent done")

    def _process_reload_requests(self):
        return process_queue(
            self._lock, self._reload_queue, self._on_reload_requested)
    

    def _process_deploy_requests(self):
        return process_queue(
            self._lock, self._deploy_queue, self._on_deploy_requested)

    ############################################################################
    # Agent control interface
    ############################################################################
    def _request_exit(self):
        logger.info("agent exiting...")
        self._sem_exit.release()
        self._sem_wait.release()

    def _request_reload(self, deployment_id=None, installer=None):
        with self._lock:
            if deployment_id is not None:
                if (self.registry.bootstrapped
                    and (
                        self.registry.deployment_id >= deployment_id
                        or next(filter(
                            lambda d: d["id"] >= deployment_id,
                            self._reload_queue), None)
                    )):
                    logger.warning("already queued or stale: {}", deployment_id)
                    return False
            self._reload_queue.append({
                "deployment_id": deployment_id,
                "installer": installer
            })
            logger.warning("agent reloading...")
            self._sem_reload.release()
            self._sem_wait.release()
            return True
    
    def _request_deploy(self, strategy=None):
        with self._lock:
            self._deploy_queue.append({
                "strategy": strategy
            })
            logger.info("deploying uvn...")
            self._sem_deploy.release()
            self._sem_wait.release()
            return True
    
    ############################################################################
    # Agent reload events
    ############################################################################
    def _on_reload_requested(self, deployment_id=None, installer=None):
        if deployment_id is not None:
            self._do_reload_deployment(deployment_id, installer)
        else:
            self._do_reload_service()

    def _do_reload_service(self):
        # Cache whether the nameserver is running
        with_ns = self.registry.nameserver.started()
        with_ns_local = self.registry.nameserver.localhost_only
        self.stop()
        self.registry = self.registry.reload()
        self._on_status_reset()
        self._load()
        self.start(nameserver=with_ns, localhost_only=with_ns_local)
    
    def _do_reload_deployment(self, deployment_id, installer):
        valid = True
        installed = False
        reloaded = False
        ok = False
        try:
            bootstrapped = self.registry.bootstrapped
            old_deployment_id = self.registry.deployment_id
            if bootstrapped and old_deployment_id >= deployment_id:
                logger.warning("stale reload request: {}", deployment_id)
                return False
            
            logger.debug("installing deployment: {} [{}]", deployment_id, installer)
            UvnCellInstaller.bootstrap(
                package=installer,
                install_prefix=self.registry.basedir,
                keep=self._keep)
            logger.activity("[installed] deployment: {}", deployment_id)
            installed = True

            self._do_reload_service()
            logger.info("[loaded] new deployment: {}", deployment_id)
            reloaded = True

            if (not self._keep and bootstrapped):
                logger.debug("deleting old deployment: {}", old_deployment_id)
                deployment_dir = self.registry.paths.dir_deployment(old_deployment_id)
                if not deployment_dir.exists():
                    logger.warning("not found: {}", deployment_dir)
                else:
                    shutil.rmtree(str(deployment_dir))
            ok = True
            return ok
        except CryptoError as crypto_e:
            logger.exception(e)
            valid = False
        except Exception as e:
            logger.exception(e)
        finally:
            if not valid:
                logger.error("invalid installer: {}", installer)
            elif not installed:
                logger.error("failed to install: {}", installer)
            elif not reloaded:
                logger.error("failed to reload agent")
            elif not ok:
                logger.error("failed to cleanup old deployment")
            
            if not self._keep:
                installer.unlink()
            else:
                logger.warning("[tmp] not deleted: {}", installer)
    
    ############################################################################
    # Deployment requests
    ############################################################################
    def _on_deploy_requested(self, strategy):
        logger.info("generating deployment: {}", strategy if strategy else "default")
        self.registry.deploy(strategy=strategy)
        self.registry.export(keep=self._keep)
        self.registry.identity_db.export()
        deployment = self.registry.deployments[-1]
        deployment.to_graph(
            save=True,
            filename="{}/{}".format(
                self.registry.paths.dir_deployment(deployment.id),
                UvnDefaults["registry"]["deployment_graph"]))
        # self.publish.deployments()
        # Reload routing service
        # self.participant.restart_rs()
        # Reload agent and publish new deployment packages
        self._do_reload_service()


    ############################################################################
    # Common DataReader handlers
    ############################################################################
    def _read_data_and_process(self, participant, reader, reader_condition,
            on_data=None,
            on_not_alive=None,
            on_disposed=None,
            on_results=None,
            take=False):
        results = types.SimpleNamespace(
                    on_data=[], on_not_alive=[], on_disposed=[])
        def read_data(condition):
            if take:
                return condition.take()
            else:
                return condition.read()
        with read_data(reader.select().condition(reader_condition)) as samples:
            for s in samples:
                if s.info.valid:
                    if on_data:
                        res = on_data(participant, reader, s.data, s.info)
                        if res is not None:
                            results.on_data.append(res)
                elif (s.info.state.instance_state
                        & dds.InstanceState.not_alive_disposed()):
                    if on_disposed:
                        res = on_disposed(participant, reader, s.data, s.info)
                        if res is not None:
                            results.on_disposed.append(res)
                elif (s.info.state.instance_state
                        & dds.InstanceState.not_alive_no_writers()):
                    if on_not_alive:
                        res = on_not_alive(participant, reader, s.data, s.info)
                        if res is not None:
                            results.on_not_alive.append(res)
        if on_results:
            return on_results(participant, reader, results)
        
        return results

    ############################################################################
    # "dns" DataReader handlers
    ############################################################################
    def _on_reader_data_dns(self, participant, reader, reader_condition):
        return self._read_data_and_process(
            participant, reader, reader_condition,
            on_data=self._on_reader_dns_received,
            on_results=self._on_reader_dns_processed)

    def _on_reader_dns_entry_received(self, server, data):
        address = ip.ipv4_from_bytes(data["address.value"])
        tags = set(data["tags"])
        hostname = data["hostname"]
        
        logger.debug("[rcvd] dns entry [{}]: {} {} {}",
            server, address, hostname, tags)
        
        if "backbone" in tags:
            if not self.registry.latest_deployment:
                logger.warning("unexpected backbone record without deployment: {}", record)
                return
            if not self.registry.latest_deployment.id in tags:
                logger.warning("stale entry ignored [{}]: {} {} {}",
                    server, address, hostname, tags)
                return
        
        record, updated = self.registry.nameserver.assert_record(
            hostname=hostname,
            server=server,
            address=address,
            tags=tags)
        
        return (record, updated)
    
    def _on_reader_dns_received(self, participant, reader, data, info):
        cell_name = data["cell.name"]
        if cell_name != self.registry.address:
            cell = self.registry.cells.get(cell_name)
            if not cell:
                logger.debug("[ignored] dns entry from unknown cell: {}", cell_name)
                return

        process = partial(self._on_reader_dns_entry_received, cell_name)
        return list(filter(bool,map(process, data["entries"])))
    
    def _on_reader_dns_processed(self, participant, reader, results):
        added = []
        for db_results in results.on_data:
            for record, updated in db_results:
                self.connection_test.add_peer(
                    name=record.hostname,
                    address=record.address,
                    tags=record.tags,
                    cell=record.server)
                added.append(record)
        return added
    
    ############################################################################
    # "cell_status" and "cell_info" DataReader handlers
    ############################################################################
    def _on_reader_matched_cell_info(self, participant, reader, status):
        if status.current_count_change < 0:
            count = status.current_count_change * -1
            logger.warning("{} cell {} unmatched",
                count, "writers" if count > 1 else "writer")
            self.connection_test.perform_test()

    def _accept_deployment_id(self, deployment_id):
        return ((self.registry.latest_deployment
                 and deployment_id == self.registry.latest_deployment.id)
             or (not self.registry.latest_deployment and
                 deployment_id == UvnDefaults["registry"]["deployment_bootstrap"]))

    def _on_cell_site_received(self, site):
        # Check if we know about the cell, otherwise ignore the entry
        subnet_addr = ip.ipv4_from_bytes(site["subnet.address.value"])
        subnet_mask = site["subnet.mask"]
        subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
        endpoint = ip.ipv4_from_bytes(site["endpoint.value"])
        gw = ip.ipv4_from_bytes(site["gw.value"])
        nic = site["nic"]

        cell = self.registry.cell_by_n(site["cell"], noexcept=True)
        if not cell:
            return
        if self.registry.deployed_cell and cell == self.registry.deployed_cell:
            return

        # Lookup or assert peer for cell
        (peer,
         peer_prev,
         new_item,
         updated) = self._peers.assert_peer(cell, detected=True)
        peer.add_private_ports({endpoint})
        peer.assert_remote_site(
            nic=nic,
            subnet=subnet,
            mask=subnet_mask,
            endpoint=endpoint,
            gw=gw)

    def _on_cell_peer_received(self, cpeer):
        cell = self.registry.cell(cpeer["name"], noexcept=True)
        if not cell:
            return
        if self.registry.deployed_cell and cell == self.registry.deployed_cell:
            return

        peer = self._peers.lookup_peer(cell.id.name)
        if not peer:
            raise RuntimeError(f"peer not found for cell: {cell.id.name}")
        
        ports = set()
        for p in cpeer["backbone_ports"]:
            address = ip.ipv4_from_bytes(p["value"])
            ports.add(address)

        peer.add_private_ports(ports)

    def _on_reader_data_cell_info(self, participant, reader, reader_condition):
        return self._read_data_and_process(
            participant, reader, reader_condition,
            on_data=self._on_reader_cell_info_received,
            on_results=self._on_reader_cell_info_processed)
    
    def _on_reader_cell_info_received(self, participant, reader, data, info):
        logger.debug("[rcvd] cell info:\n{}", data)
        cell = self.registry.cells.get(data["id.name"])
        if not cell:
            logger.debug("info from unknown cell: {}", data["id.name"])
            return

        deployment_id = data["deployment_id"]
        if not self._accept_deployment_id(deployment_id):
            logger.warning("ignored cell update: {}@{}", cell.id.name, deployment_id)
            return

        (peer,
         peer_prev,
         new_item,
         updated) = self._peers.assert_peer(cell,
            detected=True,
            status=int(data["status"]),
            peers=[p["name"] for p in data["peers"]],
            pid=int(data["pid"]))
        # peer.assert_private_ports({p for p in data["private_ports"]})
        peer.assert_remote_writer(reader,
            writer_handle=str(info.publication_handle),
            alive=True)
        for s in data["routed_sites"]:
            self._on_cell_site_received(s)
        for p in data["peers"]:
            self._on_cell_peer_received(p)
        return (peer, peer_prev, new_item, updated)

    def _log_peer_updated(self, peer, peer_prev, new_item, updated):
        current_detected = list(self._peers.detected_peers())
        current_detected_len = len(current_detected)
        if self.registry.packaged:
            current_detected_len += 1

        # if not peer_prev or not peer_prev.detected:
        #     logger.info("[cells] detected {}/{}: {} [prev: {}, was_detected:{}]",
        #         current_detected_len,
        #         len(self.registry.cells),
        #         peer.cell.id.name,
        #         peer_prev,
        #         peer_prev.detected if peer_prev else "no")
        if updated:
            logger.info("[cell][{}] status={}, ports={}, peers={}",
                peer.cell.id.name,
                peer.status,
                list(map(str, peer.private_ports)),
                peer.peers)
    
    def _on_reader_cell_info_processed(self, participant, reader, results):
        for res in results.on_data:
            self._log_peer_updated(*res)


    ############################################################################
    # Nameserver events
    ############################################################################
    def on_nameserver_record_updated(self, server, record, created=False):
        self.connection_test.add_peer(
            record.hostname, record.address,
            tags=record.tags, cell=record.server)

    ############################################################################
    # Router ports helpers
    ############################################################################
    def summarize_peer_sites(self):
        sites = []
        for p in self._peers:
            for s in p._remote_sites:
                cell_site = dds.DynamicData(self.participant.types["cell_site"])
                cell_site["cell"] = p.cell.id.n
                cell_site["nic"] = s.nic
                cell_site["subnet.address.value"] = ip.ipv4_to_bytes(s.subnet.network_address)
                cell_site["subnet.mask"] = ip.ipv4_netmask_to_cidr(s.subnet.netmask)
                cell_site["endpoint.value"] = ip.ipv4_to_bytes(s.endpoint)
                cell_site["gw.value"] = ip.ipv4_to_bytes(s.gw)
                sites.append(cell_site)
        return sites
    
    def summarize_cell_sites(self):
        sites = []
        if self.registry.deployed_cell:
            for s in self._local_sites:
                cell_site = dds.DynamicData(self.participant.types["cell_site"])
                cell_site["cell"] = self.registry.deployed_cell.id.n
                cell_site["nic"] = s["nic"]
                cell_site["subnet.address.value"] = ip.ipv4_to_bytes(s["subnet"].network_address)
                cell_site["subnet.mask"] = ip.ipv4_netmask_to_cidr(s["subnet"].netmask)
                cell_site["endpoint.value"] = ip.ipv4_to_bytes(s["address"])
                cell_site["gw.value"] = ip.ipv4_to_bytes(self._default_gw)
                sites.append(cell_site)
        return sites

    def summarize_peers(self):
        peers = []
        for p in self._peers:
            ports = self._get_peer_backbone_ports(p.cell.id.name)
            if not ports:
                continue
            if len(ports) > 3:
                raise ValueError(f"too many ports: {ports}")
            peer = dds.DynamicData(self.participant.types["cell_peer"])
            peer["name"] = p.cell.id.name
            peer["n"] = p.cell.id.n
            peer["backbone_ports"] = ports
            peers.append(peer)
        return peers
    
    def summarize_nameserver_entries(self):
        entries = []
        for e in self._get_published_nameserver_entries():
            dns_rec = e["record"]
            dns_host = dds.DynamicData(self.participant.types["dns_rec"])
            dns_host["hostname"] = dns_rec.hostname
            dns_host["address.value"] = ip.ipv4_to_bytes(dns_rec.address)
            dns_host["tags"] = list(dns_rec.tags)
            entries.append(dns_host)
            logger.activity("publishing dns entry: {}/{} {}",
                dns_host["hostname"],
                ".".join(map(str, dns_host["address.value"])),
                list(dns_host["tags"]))
        return entries


