###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from typing import TYPE_CHECKING
from pathlib import Path
import matplotlib.pyplot as plt
import networkx

from ..registry.uvn import Uvn
from ..registry.deployment import P2pLinksMap
from .uvn_peer import UvnPeerStatus, UvnPeer

if TYPE_CHECKING:
  from .agent import Agent


COLOR_ON_NODE = "#89f881"
COLOR_OFF_NODE = "#ef454a"
COLOR_WARN_NODE = "#f5b047"
COLOR_LOCAL_NODE = "#5260ec"

COLOR_ON_EDGE = "#108708"
COLOR_OFF_EDGE = "#d91319"
COLOR_WARN_EDGE = "#e96607"


def backbone_deployment_graph(
  uvn: Uvn,
  deployment: P2pLinksMap,
  output_file: Path,
  peers: UvnPeerStatus | None = None,
  local_peer: UvnPeer | None = None,
) -> Path | None:
  if len(uvn.cells) < 2:
    # We can only generate a graph if there are two or more cells
    return None

  # graph = networkx.Graph()
  graph = networkx.DiGraph()

  # graph_labels = {}
  local_nodes = []
  on_nodes = []
  off_nodes = []
  warn_nodes = []

  public_edges = []
  public_off_edges = []
  public_warn_edges = []

  private_edges = []
  private_off_edges = []
  private_warn_edges = []

  def _store_node_by_status(node, node_status):
    if local_peer.cell and local_peer.cell.name == node:
      local_nodes.append(node)
    elif node_status == UvnPeerStatus.ONLINE:
      on_nodes.append(node)
    elif node_status == UvnPeerStatus.OFFLINE:
      off_nodes.append(node)
    else:
      warn_nodes.append(node)

  def _store_edge_by_status(cell_1_status, cell_2_status, edge, public):
    if public:
      if (
        cell_1_status.status == UvnPeerStatus.ONLINE
        and cell_2_status.status == UvnPeerStatus.ONLINE
      ):
        public_edges.append(edge)
      elif (
        cell_1_status.status == UvnPeerStatus.OFFLINE
        or cell_2_status.status == UvnPeerStatus.OFFLINE
      ):
        public_off_edges.append(edge)
      else:
        public_warn_edges.append(edge)
    else:
      if (
        cell_1_status.status == UvnPeerStatus.ONLINE
        and cell_2_status.status == UvnPeerStatus.ONLINE
      ):
        private_edges.append(edge)
      elif (
        cell_1_status.status == UvnPeerStatus.OFFLINE
        or cell_2_status.status == UvnPeerStatus.OFFLINE
      ):
        private_off_edges.append(edge)
      else:
        private_warn_edges.append(edge)

  for peer_a_id, peer_a in sorted(deployment.peers.items(), key=lambda t: t[1]["n"]):
    peer_a_cell = uvn.cells[peer_a_id]
    if peers:
      _store_node_by_status(peer_a_cell.name, peers[peer_a_id].status)
    else:
      on_nodes.append(peer_a_cell.name)

    for peer_b_id, (peer_a_port_id, _, _, _) in sorted(
      peer_a["peers"].items(), key=lambda t: t[1][0]
    ):
      peer_b_cell = uvn.cells[peer_b_id]

      if peers:
        _store_node_by_status(peer_b_cell.name, peers[peer_b_id].status)
      else:
        on_nodes.append(peer_b_cell.name)

      for edge in [
        *([(peer_a_cell, peer_b_cell)] if peer_b_cell.address else []),
        *([(peer_b_cell, peer_a_cell)] if peer_a_cell.address else []),
      ]:
        cell_1, cell_2 = edge
        edge = (cell_1.name, cell_2.name)
        graph.add_edge(*edge)
        public = cell_1.address and cell_2.address
        if peers:
          _store_edge_by_status(peers[cell_1.id], peers[cell_2.id], edge, public)
        else:
          if public:
            public_edges.append(edge)
          else:
            private_edges.append(edge)

  plt.clf()

  _ = plt.figure(1, figsize=(100, 100), dpi=200)
  plt.margins(x=0.1, y=0.1)
  plt.axis("off")
  pos = networkx.circular_layout(graph)

  for nodes, color in [
    (local_nodes, COLOR_LOCAL_NODE),
    (on_nodes, COLOR_ON_NODE),
    (off_nodes, COLOR_OFF_NODE),
    (warn_nodes, COLOR_WARN_NODE),
  ]:
    if not nodes:
      continue
    networkx.draw_networkx_nodes(graph, pos, nodelist=nodes, node_color=color, node_size=60)

  for edges, color, style in [
    (public_edges, COLOR_ON_EDGE, "solid"),
    (public_off_edges, COLOR_OFF_EDGE, "solid"),
    (public_warn_edges, COLOR_WARN_EDGE, "solid"),
    (private_edges, COLOR_ON_EDGE, "dotted"),
    (private_off_edges, COLOR_OFF_EDGE, "dotted"),
    (private_warn_edges, COLOR_WARN_EDGE, "dotted"),
  ]:
    if not edges:
      continue
    networkx.draw_networkx_edges(graph, pos, edgelist=edges, edge_color=color, style=style)

  networkx.draw_networkx_labels(graph, pos, font_size=9)

  output_file.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(str(output_file), dpi=200)
  plt.clf()

  return output_file


def cell_agent_status_plot(agent: "Agent", output_file: Path, seed: int | None = None) -> None:
  graph = networkx.Graph()

  local_nodes = []
  online_nodes = []
  offline_nodes = []
  warning_nodes = []

  online_edges = []
  offline_edges = []
  warning_edges = []

  # TODO(asorbini) replace this with the agent's global status
  if agent.peers.local.status == UvnPeerStatus.ONLINE:
    online_nodes.append(agent.uvn.name)
  else:
    warning_nodes.append(agent.uvn.name)

  for peer in (p for p in agent.peers.cells):
    edge = (peer.cell.name, agent.uvn.name)
    graph.add_edge(*edge)
    if peer.local:
      local_nodes.append(peer.cell.name)
    if peer.status == UvnPeerStatus.OFFLINE:
      if not peer.local:
        offline_nodes.append(peer.cell.name)
      offline_edges.append(edge)
    elif peer.status == UvnPeerStatus.ONLINE:
      if not peer.local:
        online_nodes.append(peer.cell.name)
      online_edges.append(edge)
    else:
      if not peer.local:
        warning_nodes.append(peer.cell.name)
      warning_edges.append(edge)

    for routed_lan in peer.routed_networks:
      edge_nic = (peer.cell.name, str(routed_lan.nic.subnet))
      graph.add_edge(*edge_nic)

      lan_status = agent.peers_tester.find_status_by_lan(routed_lan)

      # peer_status = agent.peers_tester[(peer, routed_lan)]
      if lan_status:
        online_edges.append(edge_nic)
        online_nodes.append(edge_nic[1])
      else:
        # offline_edges.append(edge_lan)
        # offline_nodes.extend(edge_lan)
        offline_edges.append(edge_nic)
        offline_nodes.append(edge_nic[1])

  plt.clf()

  _ = plt.figure(1, figsize=(100, 100), dpi=200)
  plt.margins(x=0.1, y=0.1, tight=True)
  plt.axis("off")

  pos = networkx.spring_layout(graph, k=0.3, iterations=100, seed=seed)

  for nodes, color in [
    (local_nodes, COLOR_LOCAL_NODE),
    (online_nodes, COLOR_ON_NODE),
    (offline_nodes, COLOR_OFF_NODE),
    (warning_nodes, COLOR_WARN_NODE),
  ]:
    if not nodes:
      continue
    networkx.draw_networkx_nodes(graph, pos, nodelist=nodes, node_color=color, node_size=60)

  for edges, color in [
    (online_edges, COLOR_ON_EDGE),
    (offline_edges, COLOR_OFF_EDGE),
    (warning_edges, COLOR_WARN_EDGE),
  ]:
    if not edges:
      continue
    networkx.draw_networkx_edges(graph, pos, edgelist=edges, edge_color=color)

  networkx.draw_networkx_labels(graph, pos, font_size=8)

  output_file.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(str(output_file), dpi=200)
  plt.clf()
