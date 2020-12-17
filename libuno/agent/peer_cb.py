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

from libuno import ip

from .peer_manager import UvnPeerManagerListener

import libuno.log
logger = libuno.log.logger("uvn.agent.peers")

class AgentPeerCallbacks(UvnPeerManagerListener):
    ############################################################################
    # Peer events
    ############################################################################
    def on_uvn_peer_created(self, manager, peer, **kwargs):
        logger.activity("[cell][{}] record created", peer.cell.id.name)
    
    def on_uvn_peer_removed(self, manager, peer, **kwargs):
        logger.activity("[cell][{}] record removed", peer.cell.id.name)

    def on_uvn_peer_started(self, peer, **kwargs):
        logger.activity("[cell][{}] started", peer.cell.id.name)

    def on_uvn_peer_stopped(self, peer, **kwargs):
        logger.activity("[cell][{}] stopped", peer.cell.id.name)
    
    def on_uvn_peer_reset(self, peer, **kwargs):
        logger.warning("[cell][{}] reset", peer.cell.id.name)
    
    def on_uvn_peer_error(self, peer, **kwargs):
        logger.error("[cell][{}] ERROR", peer.cell.id.name)

    def on_uvn_peer_writer_changed(self, peer, local_reader, writer, writer_prev, **kwargs):
        logger.debug("[cell][{}][{}] writer changed: {} -> {}",
            peer.cell.id.name, local_reader.topic_description.name, writer_prev.handle, writer.handle)

    def on_uvn_peer_writer_alive(self, peer, local_reader, writer_handle, **kwargs):
        logger.debug("[cell][{}][{}] writer alive: {}",
            peer.cell.id.name, local_reader.topic_description.name, writer_handle)
    
    def on_uvn_peer_writer_not_alive(self, peer, local_reader, writer_handle, **kwargs):
        logger.warning("[cell][{}][{}] writer NOT ALIVE: {}",
            peer.cell.id.name, local_reader.topic_description.name, writer_handle)

    def on_uvn_peer_remote_site_changed(self, peer, net, net_prev, **kwargs):
        logger.debug("[site][{}/{}] state changed: {}",
            peer.cell.id.name, net.nic, kwargs["dispatched_events"])
        # Assert network in agent's router database
        self._route_assert_peer_network(peer, net)

    def on_uvn_peer_remote_site_route_enabled(self, peer, net, **kwargs):
        logger.info("[site][{}/{}] route enabled: {} via {} dev {}",
            peer.cell.id.name, net.nic,
            net.subnet, net.route_gw, net.route_nic)
    
    def on_uvn_peer_remote_site_route_disabled(self, peer, net, **kwargs):
        logger.warning("[site][{}/{}] route disabled: {} via {} dev {}",
            peer.cell.id.name, net.nic,
            net.subnet, net.route_gw, net.route_nic)

    def on_uvn_peer_private_ports_changed(self, peer, ports, ports_prev, **kwargs):
        if not ports_prev:
            logger.info("detected private ports: {}@{}",
                peer.cell.id.name, list(map(str, ports)))
        else:
            gone = ports_prev - ports
            new = ports - ports_prev
            logger.info("[agent][{}] private ports changed: gone=[{}], new=[{}]",
                peer.cell.id.name,
                ", ".join(map(str, gone)),
                ", ".join(map(str, new)))
        self.participant.assert_private_port(peer.cell.id.name, ports)
        self._on_status_assert()


