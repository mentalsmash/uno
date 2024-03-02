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
from typing import Optional, Tuple, Iterable, Iterator, Sequence, TYPE_CHECKING
import ipaddress

import rti.connextdds as dds

from .peer import UvnPeer
from .time import Timestamp
from .exec import exec_command
from .ip import LanDescriptor, ipv4_get_route

from .log import Logger as log

if TYPE_CHECKING:
  from .agent import Agent

class UvnPeerLanStatus:
  def __init__(self,
      peer: UvnPeer,
      lan: LanDescriptor,
      reachable: bool=False,
      ts_last_check: Optional[Timestamp]=None) -> None:
    self.peer = peer
    self.lan = lan
    self._reachable = reachable
    self.ts_last_check = ts_last_check


  def __str__(self) -> str:
    return f"{self.peer} -> {self.lan} gw {self.lan.gw}"


  @property
  def reachable(self) -> bool:
    return self._reachable


  @reachable.setter
  def reachable(self, val: bool) -> None:
    checked_before = self.ts_last_check is not None
    prev_val = self._reachable
    self._reachable = val
    self.ts_last_check = Timestamp.now()
    if prev_val != self._reachable or not checked_before:
      if not self._reachable:
        log.error(f"[LAN] UNREACHABLE: {self}")
      else:
        log.warning(f"[LAN] REACHABLE: {self}")
    else:
      if not self._reachable:
        log.debug(f"[LAN] still UNREACHABLE: {self}")
      else:
        log.debug(f"[LAN] still REACHABLE: {self}")


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, UvnPeerLanStatus):
      return False
    return self.peer == other.peer and self.lan == other.lan


  def __hash__(self) -> int:
    return hash((self.peer, self.lan))


class UvnPeersTester:
  DEFAULT_PING_LEN = 3
  DEFAULT_PING_COUNT = 3
  DEFAULT_MAX_TEST_DELAY = 60
  # DEFAULT_MAX_TEST_DELAY = 30

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
    self._reachable = set()
    self._unreachable = set()
    for peer in self.tested_peers:
      for lan in peer.routed_sites:
        _ = self[(peer, lan)]


  @property
  def tested_peers(self) -> Iterable[UvnPeer]:
    # Don't test on root agent
    if not self.agent.cell:
      return []
    return (p for p in self.agent.peers if p.cell)


  @property
  def max_test_delay(self) -> int:
    if self._max_test_delay is None:
      return self.DEFAULT_MAX_TEST_DELAY
    return self._max_test_delay


  @property
  def test_delay(self) -> int:
    if self._last_trigger_ts is None:
      return self.max_test_delay + 1
    return Timestamp.now().subtract(self._last_trigger_ts)


  @property
  def unreachable(self) -> Iterable[UvnPeerLanStatus]:
    # return set(s for s in self if not s.reachable)
    return self._unreachable


  @property
  def reachable(self) -> Iterable[UvnPeerLanStatus]:
    # return set(s for s in self if s.reachable)
    return self._reachable


  def peek_state(self) -> Tuple[set[UvnPeerLanStatus], set[UvnPeerLanStatus], bool]:
    with self._state_lock:
      fully_routed = len(self._reachable) == len(self)
      reachable = set(self._reachable)
      unreachable = set(self._unreachable)
      return (reachable, unreachable, fully_routed)



  def __getitem__(self, k: Tuple[UvnPeer, LanDescriptor]) -> UvnPeerLanStatus:
    status = self._peers_status.get(k)
    if status is None:
      status = self._peers_status[k] = UvnPeerLanStatus(k[0], k[1])
    return status


  def __iter__(self) -> Iterator[UvnPeerLanStatus]:
    return iter(sorted(self._peers_status.values(), key=lambda v: str(v.lan.nic.address)))


  def __len__(self):
    return len(self._peers_status)


  def find_status_by_lan(self, lan: LanDescriptor, peer_id: int | None=None) -> Optional[UvnPeerLanStatus]:
    for status in self:
      if peer_id is not None and status.peer.id != peer_id:
        continue
      if status.lan == lan:
        return status
    return None


  def find_status_by_peer(self, peer_id: int) -> Iterable[UvnPeerLanStatus]:
    return [s for s in self if s.peer.id == peer_id]


  def trigger(self) -> None:
    log.activity("[LAN] triggering tester...")
    with self._state_lock:
      if self._triggered:
        log.debug("[LAN] test already queued.")
        return
      self._triggered = True
    log.debug("[LAN] queued new test.")
    self._trigger_sem.release()

  # @staticmethod
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
          log.debug(f"[LAN] testing {len(peer.routed_sites)} LANs for peer {peer}")
          for lan in peer.routed_sites:
            status = self[(peer, lan)]
            pinged = self._ping_test(status)
            # Cache current route to the lan's gateway
            next_hop = ipv4_get_route(lan.gw)
            if pinged:
              reachable.append((status, next_hop))
            else:
              unreachable.append((status, next_hop))

        if not self._active:
          continue

        test_end = Timestamp.now()
        test_length = test_end.subtract(self._last_trigger_ts)
        
        log.activity(f"[LAN] test completed in {test_length} seconds")
        
        with self._state_lock:
          for status, next_hop in reachable:
            try:
              self._unreachable.remove(status)
            except KeyError:
              pass
            status.lan.next_hop = next_hop
            status.reachable = True
            self._reachable.add(status)

          for status, next_hop in unreachable:
            try:
              self._reachable.remove(status)
            except KeyError:
              pass
            status.lan.next_hop = next_hop
            status.reachable = False
            self._unreachable.add(status)

        self.result_available_condition.trigger_value = True

        if test_length > self.max_test_delay:
          log.warning(f"[LAN] test took longer than configured max delay: {test_length} > {self.max_test_delay}")
    except Exception as e:
      self._active = False
      log.error(f"[LAN] exception in tester thread:")
      log.exception(e)
      raise e
    log.debug("[LAN] tester stopped")


  def _ping_test(self, peer_status: UvnPeerLanStatus) -> bool:
    log.debug(f"[LAN] PING start {peer_status.lan.gw}: {peer_status}")
    result = exec_command(
        ["ping", "-w", str(self.DEFAULT_PING_LEN),"-c", str(self.DEFAULT_PING_COUNT), str(peer_status.lan.gw)],
        noexcept=True)
    result = result.returncode == 0
    log.debug(f"[LAN] PING {'OK' if result else 'FAILED'}: {peer_status}")
    return result
  

  def start(self) -> None:
    if self._test_thread is not None:
      return
    self._active = True
    self._test_thread = threading.Thread(target=self.run)
    self._test_thread.start()


  def stop(self) -> None:
    if self._test_thread is None:
      return
    self._active = False
    self.trigger()
    self._test_thread.join()
    self._test_thread = None

