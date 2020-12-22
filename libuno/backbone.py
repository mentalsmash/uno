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

from libuno.psk import PresharedKeys
from libuno.cell_cfg import CellDeployment
from libuno.cfg import UvnDefaults

import libuno.log
logger = libuno.log.logger("uvn.backbone")

def deploy(registry, strategy):

    for c in registry.cells.values():
        c.id.keymat.rekey()

    (cells,
     cells_len,
     cell_peers_count,
     peer_generators) = strategy.deploy_cells(registry.cells.values())

    psks = PresharedKeys()

    def generate_peer(n, i):
        peer_i = peer_generators[i](n)
        peer_cell = cells[peer_i]
        psks.assert_psk(n, peer_i)
        return CellDeployment.Peer(deploy_id=peer_i, cell=peer_cell)

    # Iterate over cells, asserting peers.Given N cells, we should end up
    # with floor(N * 3/2) pairs.
    deployed_cells = [
        CellDeployment(
            cell=cells[n],
            deploy_id=n,
            psks=psks,
            peers=[generate_peer(n, i)
                        for i in range(cell_peers_count(n, cells_len))])
        for n in range(cells_len)]

    # Make sure that all cell configurations have the correct remote peer
    # configuration, which reflects the correct remote port number, and
    # actually matches the entry in the remote cell's configuration.
    # This step acually sets cell_cfg.peers[n].port_i to a valid value
    for cell_cfg in deployed_cells:
        cell_cfg.validate_peers(deployed_cells)

    # Now iterate over each deployed cell start assigning ip addresses to 
    # each pair (local backbone port, peer backbone port)
    next_ip = ipaddress.ip_address(
                UvnDefaults["registry"]["vpn"]["backbone2"]["base_ip"])
    base_ip = next_ip
    next_ip += 2
    ip_start = next_ip

    for cell_cfg in deployed_cells:
        for i, p in enumerate(cell_cfg.peers):
            consumed_ips, backbone_connection = generate_cell_to_cell_config(
                registry, deployed_cells, cell_cfg, i, p, next_ip)
            next_ip += consumed_ips
            cell_cfg.backbone.append(backbone_connection)

    return (cells, psks, deployed_cells, (base_ip, next_ip))

def generate_cell_to_cell_config(
        registry, deployed_cells, cell_cfg, port_i, peer, next_ip):
    logger.debug("[generate] backbone: {}[{}] <-> {}[{}]",
            cell_cfg.cell.id.name, port_i,
            peer.cell.id.name, peer.port_id)
    consumed_ips = 0
    backbone_connection = cell_cfg.backbone[port_i] if len(cell_cfg.backbone) > port_i else None
    if backbone_connection:
        assert(len(backbone_connection.peers) == 1)
        assert(backbone_connection.peers[0] != None)
        assert(backbone_connection.peers[0].name == peer.cell.id.name)
        assert(backbone_connection.peers[0].peer_i == peer.port_id)
        logger.warning("[already configured] backbone: {}[{}][{}] <-> {}[{}][{}]",
            cell_cfg.cell.id.name, port_i, backbone_connection.addr_local,
            peer.cell.id.name, peer.port_id, peer.addr_remote)
        return consumed_ips, backbone_connection

    peer_cfg = next(iter([c for c in deployed_cells if c.cell == peer.cell]))

    # Check if peer already has a configuration for this port
    other_backbone_connection = peer_cfg.backbone[peer.port_id] if len(peer_cfg.backbone) else None
    if other_backbone_connection:
        assert(len(other_backbone_connection.peers) == 1)
        assert(other_backbone_connection.peers[0] != None)
        assert(other_backbone_connection.peers[0].name == cell_cfg.cell.id.name)
        assert(other_backbone_connection.peers[0].peer_i == port_i)
        cell_ip = other_backbone_connection.peers[0].addr_remote
        peer_ip = other_backbone_connection.addr_local
        port_net = other_backbone_connection.network_local
        port_net_mask_size = other_backbone_connection.network_mask
        logger.debug("[reuse] backbone: {}[{}][{}] <-> {}[{}][{}]",
            cell_cfg.cell.id.name, port_i, cell_ip,
            peer.cell.id.name, peer.port_id, peer_ip)
    else:
        cell_ip = next_ip
        peer_ip = next_ip + 1
        consumed_ips += 2
        port_net_mask_size = UvnDefaults["registry"]["vpn"]["backbone2"]["netmask"]
        port_net = ipaddress.ip_network(f"{cell_ip}/{port_net_mask_size}")

    port_keymat = cell_cfg.cell.id.keymat[port_i]
    peer_keymat = peer.cell.id.keymat[peer.port_id]
    psk = cell_cfg.psks.get_psk(cell_cfg.deploy_id, peer.deploy_id)

    backbone_connection = CellDeployment.BackboneConnection(
        cell_name=cell_cfg.cell.id.name,
        interface=UvnDefaults["registry"]["vpn"]["backbone2"]["interface"].format(port_i),
        cell_pubkey=port_keymat.pubkey,
        cell_privkey=port_keymat.privkey,
        net_cell_n=0, # not meaningful anymore
        port_i=port_i,
        port_local=cell_cfg.cell.peer_ports[port_i],
        addr_local=cell_ip,
        network_local=port_net,
        network=port_net.network_address,
        network_mask=port_net_mask_size)
    
    bpeer = backbone_connection.add_peer(
        psk=psk,
        name=peer.cell.id.name,
        pubkey=peer_keymat.pubkey,
        addr_remote=str(peer_ip),
        endpoint=":".join(map(str,peer.endpoint())),
        peer_i=peer.port_id)

    logger.activity("[connection] {}[{}][{}] <-> {}[{}][{}]",
        backbone_connection.cell_name,
        backbone_connection.port_i,
        backbone_connection.addr_local,
        bpeer.name, bpeer.peer_i, bpeer.addr_remote)
    
    return consumed_ips, backbone_connection
