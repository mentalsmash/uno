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

from .peer import UvnPeer, LanStatus
from ..core.time import Timestamp
from ..core.exec import exec_command
from ..core.ip import ipv4_get_route

from ..registry.lan_descriptor import LanDescriptor

from .agent_service import AgentService

if TYPE_CHECKING:
  from .agent import Agent


class TrigerrableAgentService(AgentService):
  PROPERTIES = [
    "max_trigger_delay"
  ]
  INITIAL_MAX_TRIGGER_DELAY = lambda self: self.uvn.settings.timing_profile.max_service_trigger_delay

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self._trigger_sem = threading.BoundedSemaphore(1)
    self._trigger_sem.acquire()
    self._state_lock = threading.Lock()
    self._service_thread = None
    self._triggered = False
    self._active = False
    self._last_trigger_ts = None


  @property
  def trigger_delay(self) -> int:
    if self._last_trigger_ts is None:
      return self.max_trigger_delay + 1
    return int(Timestamp.now().subtract(self._last_trigger_ts).total_seconds())



  def trigger(self) -> None:
    self.log.activity("triggering tester...")
    with self._state_lock:
      if self._triggered:
        self.log.debug("test already queued.")
        return
      self._triggered = True
    self.log.debug("queued new test.")
    self._trigger_sem.release()


  def run(self) -> None:
    try:
      self.log.debug("tester started")
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

        self.log.activity(f"testing {len(tested_peers)} peers")
        reachable = []
        unreachable = []
        for peer in tested_peers:
          if not self._active:
            break
          self.log.debug(f"testing {len(peer.routed_networks)} LANs for peer {peer}")
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
        
        self.log.activity(f"test completed in {test_length} seconds")

        self.agent.peers.update_peer(self.agent.peers.local,
          known_networks={
            *(self.agent.peers.local.new_child(LanStatus, {
              "lan": l,
              "reachable": True,
            }, save=False) for p, l in reachable.values),
            *(self.agent.peers.local.new_child(LanStatus, {
              "lan": l,
              "reachable": False,
            }, save=False) for p, l in unreachable),
          })

        self.result_available_condition.trigger_value = True

        if test_length > self.max_test_delay:
          self.log.warning(f"test took longer than configured max delay: {test_length} > {self.max_test_delay}")
    except Exception as e:
      self._active = False
      self.log.error(f"exception in tester thread:")
      self.log.exception(e)
      raise e
    self.log.debug("tester stopped")



  def start(self, interface: str | None = None) -> None:
    if self._test_thread is not None:
      return
    self._active = True
    self._interface = interface
    self._test_thread = threading.Thread(target=self.run)
    self._test_thread.start()


  def stop(self) -> None:
    if self._test_thread is None:
      return
    self._active = False
    self.trigger()
    self._test_thread.join()
    self._test_thread = None
    self._interface = None
