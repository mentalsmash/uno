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
from typing import Iterable

from .uvn_peer import UvnPeer
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
  SERIALIZED_PROPERTIES = ["max_trigger_delay"]
  INITIAL_PING_LEN = 3
  INITIAL_PING_COUNT = 3

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self._peers_status = {}
    self._last_result = None

  def check_runnable(self) -> bool:
    return isinstance(self.agent.owner, Cell)

  @property
  def max_trigger_delay(self) -> int:
    return self.agent.uvn.settings.timing_profile.tester_max_delay

  @property
  def tested_peers(self) -> Iterable[UvnPeer]:
    return self.agent.peers.cells

  def find_status_by_lan(self, lan: LanDescriptor) -> bool:
    reachable_subnets = [
      status.lan.nic.subnet for status in self.agent.peers.local.reachable_networks
    ]
    return lan.nic.subnet in reachable_subnets

  def find_status_by_peer(self, peer_id: int) -> Iterable[tuple[LanDescriptor, bool]]:
    reachable_subnets = [
      status.lan.nic.subnet for status in self.agent.peers.local.reachable_networks
    ]
    return [
      (lan, reachable)
      for lan in self.agent.peers[peer_id].routed_networks
      for reachable in [True if lan.nic.subnet in reachable_subnets else False]
    ]

  def _start(self) -> None:
    self.start_trigger_thread()

  def _stop(self, assert_stopped: bool = False) -> None:
    self.stop_trigger_thread()

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

    self._last_result = dict(
      (*((lan, True) for p, lan in reachable), *((lan, False) for p, lan in unreachable))
    )

    self.updated_condition.trigger_value = True

  def _process_updates(self) -> None:
    self.agent.peers.update_peer(self.agent.peers.local, known_networks=self._last_result)

  def _ping_test(self, peer: UvnPeer, lan: LanDescriptor) -> bool:
    log.activity(f"[LAN] PING start: {peer}/{lan}")
    result = exec_command(
      ["ping", "-w", str(self.ping_len), "-c", str(self.ping_count), str(lan.gw)], noexcept=True
    )
    result = result.returncode == 0
    log.activity(f"[LAN] PING {'OK' if result else 'FAILED'}: {peer}/{lan}")
    return result
