###############################################################################
# (C) Copyright 2020-2024 Andrea Sorbini
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
from typing import Iterable

from .uvn_peer import UvnPeer, LanStatus
from ..core.exec import exec_command
from ..core.ip import ipv4_get_route
from ..core.log import Logger as log
from ..registry.cell import Cell
from ..registry.lan_descriptor import LanDescriptor

from .agent_service import AgentService
from .triggerable import Triggerrable


class UvnPeersTester(AgentService, Triggerrable):
  PROPERTIES = [
    "ping_len",
    "ping_count",
  ]
  SERIALIZED_PROPERTIES = [
    "max_trigger_delay"
  ]
  INITIAL_PING_LEN = 3
  INITIAL_PING_COUNT = 3

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self._peers_status = {}


  def check_runnable(self) -> bool:
    return isinstance(self.agent.owner, Cell)


  @property
  def max_trigger_delay(self) -> int:
    return self.agent.uvn.settings.timing_profile.tester_max_delay


  @property
  def tested_peers(self) -> Iterable[UvnPeer]:
    return self.agent.peers.cells


  def find_status_by_lan(self, lan: LanDescriptor) -> bool:
    reachable_subnets = [status.lan.nic.subnet for status in self.agent.peers.local.reachable_networks]
    return lan.nic.subnet in reachable_subnets


  def find_status_by_peer(self, peer_id: int) -> Iterable[tuple[LanDescriptor, bool]]:
    reachable_subnets = [status.lan.nic.subnet for status in self.agent.peers.local.reachable_networks]
    return [
      (l, reachable)
        for l in self.agent.peers[peer_id].routed_networks
          for reachable in [True if l.nic.subnet in reachable_subnets else False]
    ]


  def _start(self) -> None:
    self.start_service()


  def _stop(self, assert_stopped: bool=False) -> None:
    self.stop_service()


  def _handle_trigger(self) -> None:
    tested_peers = list(self.tested_peers)
    if len(tested_peers) == 0:
      return

    log.activity(f"[LAN] testing {len(tested_peers)} peers")
    reachable = []
    unreachable = []
    for peer in tested_peers:
      if not self._service_active:
        break
      log.debug(f"[LAN] testing {len(peer.routed_networks)} LANs for peer {peer}")
      for lan in peer.routed_networks:
        # status = self[(peer, lan)]
        pinged = self._ping_test(peer, lan)
        # Cache current route to the lan's gateway
        lan.next_hop = ipv4_get_route(lan.gw)
        if pinged:
          reachable.append((peer, lan))
        else:
          unreachable.append((peer, lan))

    known_networks = [
      *({
        "lan": l,
        "reachable": True,
      } for p, l in reachable),
      *({
        "lan": l,
        "reachable": False,
      } for p, l in unreachable),
    ]
    self.agent.peers.update_peer(self.agent.peers.local,
      known_networks=known_networks)


  def _ping_test(self, peer: UvnPeer, lan: LanDescriptor) -> bool:
    log.activity(f"[LAN] PING start: {peer}/{lan}")
    result = exec_command(
        ["ping",
            "-w", str(self.ping_len),
            "-c", str(self.ping_count),
            str(lan.gw)],
        noexcept=True)
    result = result.returncode == 0
    log.activity(f"[LAN] PING {'OK' if result else 'FAILED'}: {peer}/{lan}")
    return result
  
