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
from collections import namedtuple

import libuno.log
from libuno.exec import exec_command
from libuno.helpers import ContainerListenerDescriptor, AbstractContainer, Observable
from .peer import UvnPeer, UvnPeerListener, PeerStatus

logger = libuno.log.logger("uvn.peers")

class UvnPeerManagerListener(UvnPeerListener):
    def on_uvn_peer_created(self, manager, peer):
        logger.activity("[cell][{}] record created", peer.cell.id.name)
    
    def on_uvn_peer_removed(self, manager, peer):
        logger.activity("[cell][{}] record removed", peer.cell.id.name)

class UvnPeerManager(AbstractContainer, Observable):
    listener = ContainerListenerDescriptor(UvnPeerManagerListener)

    def __init__(self, listener=None):
        AbstractContainer.__init__(self)
        Observable.__init__(self,
            callbacks=Observable.listener_event_map(self,
                {
                    "peer_created": "on_uvn_peer_created",
                    "peer_removed": "on_uvn_peer_removed"
                }))
        self.listener = listener
    
    ############################################################################
    # "Public" methods
    ############################################################################
    def create_peer(self, cell):
        return self._container_assert_item(cell.id.name,
                    cell=cell, status=PeerStatus.CREATED)

    def assert_peer(self, cell, **kwargs):
        return self._container_assert_item(cell.id.name, cell=cell, **kwargs)

    def lookup_peer(self, cell_name):
        return next(filter(lambda p: p.cell.id.name == cell_name, self), None)
    
    def find_peer_by_writer(self, handle):
        for p in self:
            if p.find_writer(handle):
                return p
        return None
    
    def detected_peers(self):
        return filter(lambda p: p.detected, self)

    ############################################################################
    # AbstractContainer methods
    ############################################################################
    def _container_create_item(self, handle, **kwargs):
        return UvnPeer(cell=kwargs["cell"], listener=self.listener)

    def _container_update_item(self, handle, peer, *args, **kwargs):
        updated = False
        if "status" in kwargs and kwargs["status"] != peer.status:
            status = kwargs["status"]
            peer.status = status
            updated = True
        if "detected" in kwargs and kwargs["detected"] != peer.detected:
            peer.detected = kwargs["detected"]
            updated = True
        # TODO re-enable after refactoring AbstracContainer to retrieve also
        # a list of additional events to trigger
        # if "private_ports" in kwargs and kwargs["private_ports"] != peer.private_ports:
        #     peer.private_ports = kwargs["private_ports"]
        #     updated = True
        if "peers" in kwargs and kwargs["peers"] != peer.peers:
            peer.peers = kwargs["peers"]
            updated = True
        if "pid" in kwargs and kwargs["pid"] != peer.pid:
            peer.pid = kwargs["pid"]
            updated = True
        return peer, updated

    def _container_removed_item(self, handle, item, *args, **kwargs):
        self._event_dispatch("peer_removed", item)
    
    def _container_asserted_item(self,
            reader_handle,
            peer,
            peer_prev, # always None
            new_item, updated,
            *args, **kwargs):
        if new_item:
            self._event_dispatch("peer_created", peer)
