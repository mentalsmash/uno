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
import threading
from typing import Optional, Tuple, Iterable, TYPE_CHECKING

import rti.connextdds as dds

from .peer import UvnPeer
from .time import Timestamp
from .exec import exec_command
from .ip import LanDescriptor, ipv4_get_route

from .log import Logger as log

if TYPE_CHECKING:
  from .agent import Agent


class UvnPeersTester:
  DEFAULT_PING_LEN = 3
  DEFAULT_PING_COUNT = 3
  DEFAULT_MAX_TEST_DELAY = 60

  def __init__(self,
      agent: "Agent",
      max_test_delay: Optional[int]=None) -> None:
    self.agent = agent
    self._peers_status = {}
    self._trigger_sem = threading.BoundedSemaphore(1)
    self._trigger_sem.acquire()
    self._state_lock = threading.Lock()
    self._test_thread = None
    self._triggered = False
    self._active = False
    self._max_test_delay = max_test_delay
    self._last_trigger_ts = None
    self.result_available_condition = dds.GuardCondition()


  @property
  def tested_peers(self) -> Iterable[UvnPeer]:
    return self.agent.peers.cells


  @property
  def max_test_delay(self) -> int:
    if self._max_test_delay is None:
      return self.DEFAULT_MAX_TEST_DELAY
    return self._max_test_delay


  @property
  def test_delay(self) -> int:
    if self._last_trigger_ts is None:
      return self.max_test_delay + 1
    return int(Timestamp.now().subtract(self._last_trigger_ts).total_seconds())


  def find_status_by_lan(self, lan: LanDescriptor) -> bool:
    reachable_subnets = [l.nic.subnet for l in self.agent.peers.local.reachable_networks]
    return lan.nic.subnet in reachable_subnets


  def find_status_by_peer(self, peer_id: int) -> Iterable[Tuple[LanDescriptor, bool]]:
    reachable_subnets = [l.nic.subnet for l in self.agent.peers.local.reachable_networks]
    return [
      (l, reachable)
        for l in self.agent.peers[peer_id].routed_networks
          for reachable in [True if l.nic.subnet in reachable_subnets else False]
    ]


  def trigger(self) -> None:
    log.activity("[LAN] triggering tester...")
    with self._state_lock:
      if self._triggered:
        log.debug("[LAN] test already queued.")
        return
      self._triggered = True
    log.debug("[LAN] queued new test.")
    self._trigger_sem.release()


  def run(self) -> None:
    try:
      log.debug("[LAN] tester started")
      while self._active:
        self._trigger_sem.acquire(timeout=self.max_test_delay)
        with self._state_lock:
          triggered = self._triggered
          self._triggered = False
        triggered = triggered or self.test_delay >= self.max_test_delay
        if not self._active or not triggered:
          continue

        self._last_trigger_ts = Timestamp.now()

        tested_peers = list(self.tested_peers)
        if len(tested_peers) == 0:
          continue

        log.activity(f"[LAN] testing {len(tested_peers)} peers")
        reachable = []
        unreachable = []
        for peer in tested_peers:
          if not self._active:
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

        if not self._active:
          continue

        test_end = Timestamp.now()
        test_length = int(test_end.subtract(self._last_trigger_ts).total_seconds())
        
        log.activity(f"[LAN] test completed in {test_length} seconds")

        self.agent.peers.update_peer(self.agent.peers.local,
          reachable_networks=(l for p, l in reachable),
          unreachable_networks=(l for p, l in unreachable))

        self.result_available_condition.trigger_value = True

        if test_length > self.max_test_delay:
          log.warning(f"[LAN] test took longer than configured max delay: {test_length} > {self.max_test_delay}")
    except Exception as e:
      self._active = False
      log.error(f"[LAN] exception in tester thread:")
      log.exception(e)
      raise e
    log.debug("[LAN] tester stopped")


  def _ping_test(self, peer: UvnPeer, lan: LanDescriptor) -> bool:
    log.activity(f"[LAN] PING start: {peer}/{lan}")
    result = exec_command(
        ["ping", "-w", str(self.DEFAULT_PING_LEN),"-c", str(self.DEFAULT_PING_COUNT), str(lan.gw)],
        noexcept=True)
    result = result.returncode == 0
    log.activity(f"[LAN] PING {'OK' if result else 'FAILED'}: {peer}/{lan}")
    return result
  

  def start(self) -> None:
    if self._test_thread is not None:
      return
    self._active = True
    self._test_thread = threading.Thread(target=self.run, daemon=True)
    self._test_thread.start()


  def stop(self) -> None:
    if self._test_thread is None:
      return
    self._active = False
    self.trigger()
    self._test_thread.join()
    self._test_thread = None
