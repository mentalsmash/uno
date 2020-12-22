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
from collections import namedtuple

import libuno.log
from libuno.exec import exec_command
from libuno.helpers import ListenerDescriptor, AbstractContainer, StatefulObservable, ObservableStatus, ObservableDelegate, Observable, StatefulObjectStatusDescriptor
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from .router import LocalRoute

logger = libuno.log.logger("uvn.peers")

PeerStatus = ObservableStatus

RemoteSiteRoute = namedtuple("RemoteSiteRoute", ["nic", "gw", "peer"])

RemoteSite = namedtuple("RemoteSite",
    ["nic", "subnet", "mask", "endpoint", "gw", "route"])

RemoteWriter = namedtuple("RemoteWriter", ["handle", "reader", "alive"])

RemoteAgent = namedtuple("RemoteAgent", ["pid", "locators", "handle"])

class PeerWriters(AbstractContainer, ObservableDelegate):
    def __init__(self, peer):
        ObservableDelegate.__init__(self, peer)
        AbstractContainer.__init__(self)
    
    ############################################################################
    # AbstractContainer methods
    ############################################################################
    def _container_default_item(self, handle, *args, **kwargs):
        return RemoteWriter(handle=None, reader=None, alive=False)

    def _container_create_item(self, handle, *args, **kwargs):
        return RemoteWriter(
                reader=kwargs["local_reader"],
                handle=kwargs["writer_handle"],
                alive=kwargs["alive"])
    
    def _container_snapshot_item(self, handle, item, *args, **kwargs):
        return RemoteWriter(*item)

    def _container_removed_item(self, handle, item, *args, **kwargs):
        # nothing to do
        pass
    
    def _container_update_item(self, handle, remote_writer, *args, **kwargs):
        updated = False

        update_args = [*remote_writer]

        if (("writer_handle" in kwargs and remote_writer.handle != kwargs["writer_handle"])
            or kwargs.get("reset_writer")):
            val = kwargs["writer_handle"] if not kwargs.get("reset_writer") else None
            update_args[0] = handle
            updated = True
        if "alive" in kwargs and remote_writer.alive != kwargs["alive"]:
            update_args[2] = kwargs["alive"]
            updated = True
        if updated:
            remote_writer = RemoteWriter(*update_args)

        return remote_writer, updated
    
    def _container_asserted_item(self,
            reader_handle,
            remote_writer, remote_writer_prev, new_item, updated,
            *args, **kwargs):
        events = []
        if remote_writer.handle != remote_writer_prev.handle:
            events.append("writer_changed")
        if not remote_writer_prev.alive and remote_writer.alive:
            events.append("writer_alive")
        elif remote_writer_prev.alive and not remote_writer.alive:
            events.append("writer_not_alive")
        
        # sanity check
        if remote_writer.alive and remote_writer.handle is None:
            raise ValueError("alive writer with no handle")
        
        self._event_dispatch_all(events,
                remote_writer=remote_writer,
                remote_writer_prev=remote_writer_prev)

class PeerRemoteSites(AbstractContainer, ObservableDelegate):

    def __init__(self, peer):
        ObservableDelegate.__init__(self, peer)
        AbstractContainer.__init__(self)
    
    ############################################################################
    # AbstractContainer methods
    ############################################################################
    def _container_default_item(self, handle, *args, **kwargs):
        return RemoteSite(
                    nic=None,
                    subnet=ipaddress.ip_address("0.0.0.0"),
                    mask=0,
                    endpoint=ipaddress.ip_address("0.0.0.0"),
                    gw=ipaddress.ip_address("0.0.0.0"),
                    route=None)

    def _container_create_item(self, handle, *args, **kwargs):
        route = kwargs.get("route")
        return RemoteSite(
                    nic=handle,
                    subnet=ipaddress.ip_network(kwargs["subnet"]),
                    mask=int(kwargs["mask"]),
                    endpoint=ipaddress.ip_address(kwargs["endpoint"]),
                    gw=ipaddress.ip_address(kwargs["gw"]),
                    route=RemoteSiteRoute(*route) if route else None)

    def _container_snapshot_item(self, handle, item, *args, **kwargs):
        return RemoteSite(*item)

    def _container_removed_item(self, handle, item, *args, **kwargs):
        # nothing to do
        pass

    def _container_update_item(self, handle, remote_site, *args, **kwargs):
        updated = False

        update_args = [*remote_site]

        if "subnet" in kwargs:
            subnet = ipaddress.ip_network(kwargs["subnet"])
            if remote_site.subnet != subnet:
                udpate_args[1] = subnet
                updated = True
        if "mask" in kwargs:
            mask = int(kwargs["mask"])
            if remote_site.mask != mask:
                udpate_args[2] = mask
                updated = True
        if "endpoint" in kwargs:
            endpoint = ipaddress.ip_address(kwargs["endpoint"])
            if remote_site.endpoint != endpoint:
                udpate_args[3] = endpoint
                updated = True
        if "gw" in kwargs:
            endpoint = ipaddress.ip_address(kwargs["gw"])
            if remote_site.gw != endpoint:
                udpate_args[4] = endpoint
                updated = True
        if ("route" in kwargs and remote_site.route != kwargs["route"]
            or kwargs.get("reset_route")):
            udpate_args[5] = kwargs["route"] if not kwargs.get("reset_route") else None
            updated = True
        
        if updated:
            remote_site = RemoteSite(*update_args)

        return remote_site, updated
    
    def _container_asserted_item(self,
            nic, remote_site, remote_site_prev, new_item, updated,
            *args, **kwargs):
        events = []
        if remote_site.route != remote_site_prev.route:
            if remote_site.route:
                events.append("remote_site_route_enabled")
            else:
                events.append("remote_site_route_disabled")
        if (remote_site.subnet != remote_site_prev.subnet
            or remote_site.mask != remote_site_prev.mask
            or remote_site.endpoint != remote_site_prev.endpoint
            or remote_site.gw != remote_site_prev.gw):
            events.append("remote_site_changed")
        
        self._event_dispatch_all(events,
                remote_site=remote_site,
                remote_site_prev=remote_site_prev)

class UvnPeerListener:
    def on_uvn_peer_started(self, peer, **kwargs):
        pass

    def on_uvn_peer_stopped(self, peer, **kwargs):
        pass
    
    def on_uvn_peer_reset(self, peer, **kwargs):
        pass
    
    def on_uvn_peer_error(self, peer, **kwargs):
        pass
    
    def on_uvn_peer_writer_changed(self, peer, local_reader, writer, writer_prev, **kwargs):
        pass

    def on_uvn_peer_writer_alive(self, peer, local_reader, writer_handle, **kwargs):
        pass
    
    def on_uvn_peer_writer_not_alive(self, peer, local_reader, writer_handle, **kwargs):
        pass
    
    def on_uvn_peer_remote_site_changed(self, peer, net, net_prev, **kwargs):
        pass
    
    def on_uvn_peer_remote_site_route_enabled(self, peer, net, **kwargs):
        pass
    
    def on_uvn_peer_remote_site_route_disabled(self, peer, net, **kwargs):
        pass
    
    def on_uvn_peer_private_ports_changed(self, peer, ports, ports_prev, **kwargs):
        pass

class UvnPeer(StatefulObservable):
    listener = ListenerDescriptor(UvnPeerListener)
    status = StatefulObjectStatusDescriptor()

    def __init__(self, cell,
            listener=None,
            status="created",
            detected=False,
            private_ports=[],
            pid=None):
        self.listener = listener
        self.cell = cell
        self.detected = detected
        self.pid = pid
        self.private_ports = set(private_ports)
        self.peers = []
        self.agent = RemoteAgent(pid=None, locators={}, handle=None)
        self._remote_writers = PeerWriters(self)
        self._remote_sites = PeerRemoteSites(self)
        StatefulObservable.__init__(self, initial_status=status,
            callbacks=Observable.listener_event_map(self, {
                "writer_changed": "on_uvn_peer_writer_changed",
                "writer_alive": "on_uvn_peer_writer_alive",
                "writer_not_alive": "on_uvn_peer_writer_not_alive",
                "remote_site_route_enabled": "on_uvn_peer_remote_site_route_enabled",
                "remote_site_route_disabled": "on_uvn_peer_remote_site_route_disabled",
                "remote_site_changed": "on_uvn_peer_remote_site_changed",
                "private_ports_changed": "on_uvn_peer_private_ports_changed",
                "state_started": "on_uvn_peer_started",
                "state_stopped": "on_uvn_peer_stopped",
                "state_reset": "on_uvn_peer_reset",
                "state_error": "on_uvn_peer_error",
                "state_unknown": "on_uvn_peer_error"
            }))
        
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return {
                # "cell": py_repr.cell.id.name,
                "detected": py_repr.detected,
                "pid": py_repr.pid if py_repr.pid else "<unknown>",
                "private_ports": [str(p) for p in py_repr.private_ports],
                "peers": [str(p) for p in py_repr.peers],
                "sites": [str(s.nic) for s in py_repr._remote_sites],
                # "writers": [str(h.handle) for h in py_repr._remote_writers]
            }
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()
    
    ############################################################################
    # Observable methods
    ############################################################################
    def _dispatch_event_writer_alive(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_writer"].reader, kwargs["remote_writer"].handle, **kwargs)
    
    def _dispatch_event_writer_not_alive(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_writer"].reader, kwargs["remote_writer"].handle, **kwargs)
    
    def _dispatch_event_writer_changed(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_writer"].reader, kwargs["remote_writer"], kwargs["remote_writer_prev"], **kwargs)
    
    def _dispatch_event_remote_site_route_enabled(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_site"], **kwargs)
    
    def _dispatch_event_remote_site_route_disabled(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_site"], **kwargs)
    
    def _dispatch_event_remote_site_changed(self, cb, *args, **kwargs):
        cb(self, kwargs["remote_site"], kwargs["remote_site_prev"], **kwargs)
    
    ############################################################################
    # "Public" methods
    ############################################################################
    def assert_remote_writer(self, local_reader, **kwargs):
        return self._remote_writers._container_assert_item(
            # TODO update once connextdds-py implement's __eq__
            str(local_reader.instance_handle),
            local_reader=local_reader,
            **kwargs)
    
    def assert_remote_site(self, nic, **kwargs):
        return self._remote_sites._container_assert_item(nic, **kwargs)
    
    def update_remote_site_routes(self, routes):
        peers = []
        peers_updated = []
        for site in self._remote_sites:
            route = next(filter(lambda r: r.subnet == site.subnet, routes), None)
            (peer,
             peer_prev,
             new_item,
             updated) = self._remote_sites._container_assert_item(site.nic, route=route)
            peers.append(peer)
            if updated:
                peers_updated.append(peer)
        return peers, peers_updated
    
    def find_writer(self, writer_handle):
        for wr in self._remote_writers:
            if wr.handle == writer_handle:
                return wr
        return None
    
    def assert_private_ports(self, ports):
        ports = set(ports)
        current = set(self.private_ports)
        diff_ports = ports ^ current
        if not diff_ports:
            return
        self.private_ports = list(ports)
        self._event_dispatch("private_ports_changed", ports, current)
    
    def add_private_ports(self, ports):
        eports = set(self.private_ports)
        eports.update(ports)
        return self.assert_private_ports(eports)

    def agent_detected(self, pid, locators, handle):
        ports = set(self.private_ports)
        locators = set(locators)
        ports = ports & locators
        self.assert_private_ports(ports)
        
        if self.agent.pid and self.agent.pid != pid:
            raise RuntimeError("agent changed without disposing")

        self.agent = RemoteAgent(pid, locators, handle)

    def agent_gone(self):
        self.assert_private_ports([])
        self.agent = RemoteAgent(None, set(), None)
