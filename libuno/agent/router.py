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
import threading
import types
from collections import namedtuple
import ipaddress
import pathlib

import libuno.log
from libuno import ip
from libuno.exception import UvnException
from libuno.helpers import ListenerDescriptor
from libuno.cfg import UvnDefaults
from libuno.exec import exec_command
from libuno.psk import PresharedKeys
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml

logger = libuno.log.logger("uvn.agent.router")

LocalRoute = namedtuple("LocalRoute", ["subnet", "nic", "peer", "gw"])

class RemoteSiteClashException(UvnException):

    def __init__(self, net, clash):
        self.net = net
        self.clash = clash
        UvnException.__init__(self,
            f"remote site clash detected: {self.net.handle} x-x {self.clash.handle}")

class RemoteNetwork:
    def __init__(self,
            handle,
            adjacent,
            cell,
            nic,
            subnet,
            mask,
            gw,
            route_nic=None,
            route_peer=None,
            route_gw=None,
            remote_cell=None,
            enabled=False):
        self.handle = handle
        self.adjacent = adjacent
        self.cell = cell
        self.nic = nic
        self.subnet = subnet
        self.mask = mask
        self.gw = gw
        self.route_nic = route_nic
        self.route_peer = route_peer
        self.route_gw = route_gw
        self.remote_cell = remote_cell
        self.enabled = enabled
    
    def has_route(self):
        return self.route_nic is not None and self.route_gw is not None
    
    def route_changed(self, route_nic, route_gw, route_peer):
        return ((route_nic is not None and self.route_nic != route_nic)
            or (route_gw is not None and self.route_gw != route_gw)
            or (route_peer is not None and self.route_peer != route_peer))
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = {
                # "cell": py_repr.cell.id.name,
                # "handle": py_repr.handle,
                "adjacent": py_repr.adjacent,
                "enabled": py_repr.enabled,
                "subnet": str(py_repr.subnet),
                "gw": str(py_repr.gw)
                        if py_repr.gw else "<unknown>",
                "nic": py_repr.nic
            }
            if py_repr.route_nic:
                yml_repr["route"] = {
                    "nic": py_repr.route_nic,
                    "gw": str(py_repr.route_gw),
                    "peer": py_repr.route_peer,
                }
            return yml_repr

        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()

class UvnRouterListener:
    def __init__(self):
        pass

    def on_route_enabled(self, router, net):
        pass
    
    def on_route_disabled(self, router, net):
        pass
    
    def on_route_monitor_result(self, router, backbone_routes):
        logger.trace("tester results: {}", backbone_routes)

class UvnRouter:
    
    listener = ListenerDescriptor(UvnRouterListener)

    def __init__(self, basedir, registry, vpn, listener):
        self._basedir = pathlib.Path(basedir)
        self.registry = registry
        self._vpn = vpn
        self.listener = listener
        self.networks = {}
        (self._quagga_cls,
         self._quagga_extra) = self._get_quagga_cls()
        self._quagga = self._create_quagga()
        self._monitor = None

    def __iter__(self):
        return iter(self.networks.values())

    def _create_quagga(self):
        return self._quagga_cls(self._basedir, self.registry, vpn=self._vpn, **self._quagga_extra)
    
    def _get_quagga_cls(self):
        return None, {}
    
    def find_remote_network_by_subnet(self, subnet, mask):
        return filter(
                lambda n: (n[1].subnet == subnet and n[1].mask == mask),
                self.networks.items())

    def find_remote_networks_by_cell(self, cell_name):
        return filter(lambda n: n[1].cell.id.name == cell_name, self.networks.items())
    
    def enabled_networks(self):
        return filter(lambda n: n.enabled, self.networks.values())
    
    def adjacent_networks(self):
        return filter(lambda n: n.adjacent, self.networks.values())

    def monitor(self, interfaces=None):
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        if interfaces is None:
            interfaces = list(self.vpn.list_wg_interfaces())
        if not interfaces:
            logger.warning("no interfaces to monitor")
            return
        self._monitor = RouteMonitor(self, interfaces)
        self._monitor.start()
    
    def clear(self):
        self.networks = {}

    def start(self):
        self._quagga.start()

    def stop(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._quagga.stop()

    def _route_log_action(self, net, action, log_fn=logger.info):
        if net.has_route():
            route_args = [net.route_gw, net.route_nic]
            route_fmt = " via {} dev {}"
        else:
            route_args = []
            route_fmt = ""

        cell_args = [net.cell.id.name, net.nic]
        cell_fmt = "{}.{}"

        cell_fmt = cell_fmt.format(*cell_args)
        route_fmt = route_fmt.format(*route_args)

        log_fn("{} <{}> {}{} [{}]",
            action, cell_fmt, net.subnet, route_fmt,
            "adjacent" if net.adjacent else "routed")

    def _update_remote_network(self, net, enabled, new=False):
        if enabled and net.enabled and not new:
            self._route_log_action(net, "already enabled", log_fn=logger.warning)
            return False
        elif not enabled and not net.enabled and not new:
            self._route_log_action(net, "already disabled", log_fn=logger.warning)
            return False
        
        if not enabled:
            log_action = "del"
            # route_action = ip.ipv4_del_route_to_network
            listener = self.listener.on_route_disabled
        else:
            log_action = "add"
            # route_action = ip.ipv4_add_route_to_network
            listener = self.listener.on_route_enabled
        
        self._route_log_action(net, log_action)
        net.enabled = enabled
        listener(self, net)
        return True


    def assert_remote_network(self, net_handle, adjacent,
            cell_name=None, nic=None, subnet=None, mask=None, gw=None,
            route_nic=None, route_peer=None, route_gw=None,
            enabled=True):
        net = self.networks.get(net_handle)
        new = net is None
        if new:
            # Check if another route to the network exists.
            # If it exist, we cache this route for later use,
            # unless this is a forced addition
            others = list(self.find_remote_network_by_subnet(subnet, mask))
            cell = self.registry.cell(cell_name)
            net = RemoteNetwork(net_handle,
                    adjacent,
                    cell, nic, subnet, mask, gw,
                    route_nic, route_peer, route_gw,
                    enabled=enabled)
            if len(others):
                logger.error("site clash detected: {}", net)
                logger.error("clashes: {}", others)
                raise RemoteSiteClashException(net, others[0])
            self.networks[net_handle] = net
        updated = self._update_remote_network(net, enabled, new)
        return net

    def remove_remote_network(self, net_handle):
        net = self.networks.get(net_handle)
        if net is None:
            return None, False
        was_enabled = net.enabled
        self._update_remote_network(net, enabled=False)
        del self.networks[net_handle]
        return net, was_enabled


class RouteMonitor(threading.Thread):
    
    def __init__(self, router, interfaces,
            poll_period=UvnDefaults["router"]["monitor"]["poll_period"]):
        threading.Thread.__init__(self, name="route-monitor")
        self.interfaces = interfaces
        self.router = router
        self._poll_period = poll_period
        self._lock = threading.RLock()
        self._sem_exit = threading.BoundedSemaphore()
        self._sem_exit.acquire()
        self._sem_test = threading.Semaphore()
        self._sem_test.acquire()
        self._queued = False
        self.schedule()
    
    def schedule(self):
        with self._lock:
            if self._queued:
                # already queued
                return
            self._queued = True
        self._sem_test.release()
    
    def _run_test(self):
        result = exec_command(["ip", "-o", "route"])
        def check_route(r):
            for n in self.interfaces:
                if f"dev {n}" in r:
                    return True
            return False
        def mkroute(r):
            subnet = ipaddress.ip_network(r.split(" ")[0])
            nic = r.split(" ")[2]
            gw = ipaddress.ip_address("0.0.0.0")
            peer = ""
            return LocalRoute(
                subnet=subnet,
                nic=nic,
                gw=gw,
                peer=peer)
        results = frozenset(result.stdout.decode("utf-8").split("\n")[:-1])
        results = filter(check_route,results)
        # Filter by finding peer in cell_cfg.backbone and checking
        # that route isn't for a backbone network
        routes = [mkroute(r) for r in results]
        if routes:
            logger.trace("found routes for {}: {}", self.interfaces, routes)
            self.router.listener.on_route_monitor_result(self.router, routes)
        else:
            logger.warning(
                "no backbone routes detected for {}", self.interfaces)

    def run(self):
        try:
            complete = False
            while not (complete or self._exit):
                logger.debug("waiting for next test request...")
                signalled = self._sem_test.acquire(timeout=self._poll_period)

                if not signalled:
                    logger.trace("running periodic check route check")
                else:
                    logger.debug("running manually triggered route check")

                do_test = False
                with self._lock:
                    do_test = self._queued or not signalled
                    self._queued = False
                    
                if do_test:
                    self._run_test()

                complete = self._sem_exit.acquire(blocking=False)
        except Exception as e:
            logger.exception(e)
            logger.error("unexpected error in route monitor")
    

    def start(self):
        self._exit = False
        threading.Thread.start(self)

    def stop(self):
        if not self.is_alive():
            return
        self._exit = True
        self._sem_exit.release()
        self._sem_test.release()
        self.join()