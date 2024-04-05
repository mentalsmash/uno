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
from typing import Generator, Iterable, TYPE_CHECKING
from enum import Enum

from ..middleware import Handle

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.versioned import Versioned

from .uvn_peer import UvnPeer, VpnInterfaceStatus, UvnPeerStatus, LanStatus

if TYPE_CHECKING:
  from .agent import Agent


class UvnPeerListener:
  class Event(Enum):
    ONLINE_CELLS = 0
    ONLINE_PARTICLES = 1
    ALL_CELLS_CONNECTED = 2
    REGISTRY_CONNECTED = 3
    ROUTED_NETWORKS = 4
    ROUTED_NETWORKS_DISCOVERED = 5
    CONSISTENT_CONFIG_CELLS = 6
    CONSISTENT_CONFIG_UVN = 7
    LOCAL_REACHABLE_NETWORKS = 8
    REACHABLE_NETWORKS = 9
    FULLY_ROUTED_UVN = 10
    VPN_CONNECTIONS = 11


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
    pass


  def on_event_online_particles(self, new_particles: set[UvnPeer], gone_particles: set[UvnPeer]) -> None:
    pass


  def on_event_all_cells_connected(self) -> None:
    pass


  def on_event_registry_connected(self) -> None:
    pass


  def on_event_routed_networks(self, new_routed, gone_routed) -> None:
    pass


  def on_event_routed_networks_discovered(self) -> None:
    pass


  def on_event_consistent_config_cells(self, new_consistent: set[UvnPeer], gone_consistent: set[UvnPeer]) -> None:
    pass


  def on_event_consistent_config_uvn(self) -> None:
    pass


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    pass


  def on_event_reachable_networks(self, new_reachable: set[tuple[UvnPeer, LanDescriptor]], gone_reachable: set[tuple[UvnPeer, LanDescriptor]]) -> None:
    pass


  def on_event_fully_routed_uvn(self) -> None:
    pass


  def on_event_vpn_connections(self, new_online: set[VpnInterfaceStatus], gone_online: set[VpnInterfaceStatus]) -> None:
    pass



class UvnPeersList(Versioned):
  PROPERTIES = [
    "status_all_cells_connected",
    "status_consistent_config_uvn",
    "status_routed_networks_discovered",
    "status_fully_routed_uvn",
    "status_registry_connected",
  ]
  EQ_PROPERTIES = [
    "agent",
  ]
  REQ_PROPERTIES = [
    "agent",
  ]
  INITIAL_STATUS_ALL_CELLS_CONNECTED = False
  INITIAL_STATUS_CONSISTENT_CONFIG_UVN = False
  INITIAL_STATUS_ROUTED_NETWORKS_DISCOVERED = False
  INITIAL_STATUS_FULLY_ROUTED_UVN = False
  INITIAL_STATUS_REGISTRY_CONNECTED = False


  def __init__(self, **properties) -> None:
    self.listeners: list[UvnPeerListener] = list()
    self._peers = []
    super().__init__(**properties)
    # Make sure that we have exactly one "local" peer in the list
    assert(self.local.local)
    assert(len(list(p for p in self if p.local)) == 1)


  def load_nested(self) -> None:
    peers = []
    for uvn_obj in (self.uvn, *self.uvn.all_cells.values(), *self.uvn.all_particles.values()):
      try:
        peer = self[uvn_obj]
      except KeyError:
        peer = None
      except IndexError:
        peer = None

      if peer is None:
        peer = self.load_child(UvnPeer, owner=uvn_obj)
        if peer is None:
          peer = self.new_child(UvnPeer, owner=uvn_obj)
          # peers_changed = True
        else:
          # Make sure peer properties are reset
          peer.configure(
            status=UvnPeerStatus.DECLARED,
            registry_id=self.ResetValue,
            routed_networks=[],
            known_networks=[],
            vpn_interfaces={},
            instance=self.ResetValue,
            writer=self.ResetValue,
            ts_start=self.ResetValue)
      peers.append(peer)
    self._peers = peers


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for peer in self:
      yield peer


  def _notify(self, event: UvnPeerListener.Event, *args) -> None:
    if self.local.status != UvnPeerStatus.ONLINE:
      self.log.trace("notification disabled by !ONLINE: {}", event)
      return
    for l in self.listeners:
      self.log.trace("notifying listener: {} -> {}", event, l)
      getattr(l, f"on_event_{event.name.lower()}")(*args)


  @property
  def agent(self) -> "Agent":
    return self.parent


  @property
  def registry_id(self) -> str:
    return self.agent.config_id


  @property
  def uvn(self) -> Uvn:
    return self.agent.uvn


  @property
  def local(self) -> UvnPeer:
    return self[self.parent.local_object]


  @property
  def registry(self) -> UvnPeer:
    return self[self.uvn]


  @property
  def cells(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self if p.cell]
    for p in self:
      if not p.cell or p.cell.excluded:
        continue
      yield p


  @property
  def excluded_cells(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self if p.cell]
    for p in self:
      if not p.cell or not p.cell.excluded:
        continue
      yield p


  @property
  def particles(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self if p.particle]
    for p in self:
      if not p.particle or p.particle.excluded:
        continue
      yield p


  @property
  def excluded_particles(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self if p.particle]
    for p in self:
      if not p.particle or not p.particle.excluded:
        continue
      yield p


  @property
  def other_cells(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self.cells if p.cell != self.parent]
    for p in self.cells:
      if p.cell == self.local.cell:
        continue
      yield p


  @property
  def online_cells(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self.cells if p.status == UvnPeerStatus.ONLINE]
    for p in self.cells:
      if p.status != UvnPeerStatus.ONLINE:
        continue
      yield p


  @property
  def offline_cells(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self.cells if p.status == UvnPeerStatus.ONLINE]
    for p in self.cells:
      if p.status != UvnPeerStatus.OFFLINE:
        continue
      yield p


  @property
  def unseen_cells(self) -> Generator[UvnPeer, None, None]:
    for p in self.cells:
      if p.status != UvnPeerStatus.DECLARED:
        continue
      yield p


  @property
  def online_particles(self) -> Generator[UvnPeer, None, None]:
    for p in self.particles:
      if p.status != UvnPeerStatus.ONLINE:
        continue
      yield p


  @property
  def offline_particles(self) -> Generator[UvnPeer, None, None]:
    # return [p for p in self.cells if p.status == UvnPeerStatus.ONLINE]
    for p in self.particles:
      if p.status == UvnPeerStatus.ONLINE:
        continue
      yield p


  @property
  def consistent_config_cells(self) -> Generator[UvnPeer, None, None]:
    # return [c for c in self.cells if c.registry_id == self.registry_id]
    for p in self.cells:
      if p.registry_id != self.registry_id:
        continue
      yield p


  @property
  def inconsistent_config_cells(self) -> Generator[UvnPeer, None, None]:
    # return [c for c in self.cells if c.registry_id == self.registry_id]
    for p in self.cells:
      if p.registry_id == self.registry_id:
        continue
      yield p


  @property
  def fully_routed_cells(self) -> Generator[UvnPeer, None, None]:
    expected_subnets = {l for c in self.uvn.cells.values() for l in c.allowed_lans}
    if not expected_subnets:
      return

    for c in self.cells:
      c_reachable = {l.lan.nic.subnet for l in c.reachable_networks}
      if (expected_subnets
          and (
            len(c_reachable) < len(expected_subnets)
            or (expected_subnets & c_reachable) != expected_subnets
          )):
        continue
      yield c


  def online(self, **local_peer_fields) -> None:
    self.update_peer(self.local,
      status=UvnPeerStatus.ONLINE,
      **local_peer_fields)


  def offline(self) -> None:
    if self.local.status == UvnPeerStatus.OFFLINE:
      return
    self.update_all(
      status=UvnPeerStatus.OFFLINE,
      registry_id=self.ResetValue,
      routed_networks=[],
      known_networks=[],
      vpn_interfaces={},
      instance=self.ResetValue,
      writer=self.ResetValue,
      ts_start=self.ResetValue)
  

  def update_peer(self,
      peer: UvnPeer,
      **updated_fields) -> None:
    return self.update_all([peer], **updated_fields)


  def update_all(self,
      peers: Iterable[UvnPeer] | None = None,
      **updated_fields) -> None:
    if peers is None:
      peers = self
    for peer in peers:
      peer.configure(**updated_fields)
    self._process_updates()


  def configure(self, **properties) -> set[str]:
    configured = super().configure(**properties)
    if configured:
      self._process_updates()
    return configured


  def _process_updates(self) -> None:
    changed = list(self.collect_changes())
    if not changed:
      # self.log.warning("nothing changed")
      return

    # self.log.warning("processing {} updated objects:", len(changed))
    # self.log.warning("changed: {}", changed)

    ###########################################################################
    # Check if there were updates related to VPN connections
    ###########################################################################
    vpn_changed = {
      c
      for c, prev_vals in changed
        if isinstance(c, VpnInterfaceStatus)
        and "online" in prev_vals
    }
    vpn_online = {c for c in vpn_changed if c.online}
    vpn_offline = {c for c in vpn_changed if not c.online}
    if vpn_online or vpn_offline:
      self._notify(UvnPeerListener.Event.VPN_CONNECTIONS, vpn_online, vpn_offline)


    ###########################################################################
    # Check status of cell agents (online/offline)
    ###########################################################################
    gone_cells = {
      c
      for c, prev_vals in changed
        if isinstance(c, UvnPeer) and c.cell
          and "status" in prev_vals
          and c.status == UvnPeerStatus.OFFLINE
    }
    new_cells = {
      c
      for c, prev_vals in changed
        if isinstance(c, UvnPeer) and c.cell
          and "status" in prev_vals
          and c.status == UvnPeerStatus.ONLINE
    }
    if gone_cells or new_cells:
      self._notify(UvnPeerListener.Event.ONLINE_CELLS, new_cells, gone_cells)

      #########################################################################
      # Check if all agents are online
      #########################################################################
      # self.updated_property("online_cells")
      all_cells_connected = sum(1 for c in self.online_cells) == len(self.uvn.cells)
      if all_cells_connected != self.status_all_cells_connected:
        self.status_all_cells_connected = all_cells_connected
        self._notify(UvnPeerListener.Event.ALL_CELLS_CONNECTED)

    ###########################################################################
    # Check status of particle agents (online/offline)
    ###########################################################################
    gone_particles = {
      c
      for c, prev_vals in changed
        if isinstance(c, UvnPeer) and c.particle
          and "status" in prev_vals
          and c.status == UvnPeerStatus.OFFLINE
    }
    new_particles = {
      c
      for c, prev_vals in changed
        if isinstance(c, UvnPeer) and c.particle
          and "status" in prev_vals
          and c.status == UvnPeerStatus.ONLINE
    }
    if gone_particles or new_particles:
      self._notify(UvnPeerListener.Event.ONLINE_PARTICLES, new_particles, gone_particles)

    ###########################################################################
    # Check status of registry agent (online/offline)
    ###########################################################################
    if next((c
      for c, prev_vals in  changed
        if isinstance(c, UvnPeer) and c.registry
          and "status" in prev_vals
          and c.status == UvnPeerStatus.OFFLINE),
      None) is not None:
      self.status_registry_connected = False
      self._notify(UvnPeerListener.Event.REGISTRY_CONNECTED)
    elif next((c
      for c, prev_vals in  changed
        if isinstance(c, UvnPeer) and c.registry
          and "status" in prev_vals
          and c.status == UvnPeerStatus.ONLINE),
      None) is not None:
      self.status_registry_connected = True
      self._notify(UvnPeerListener.Event.REGISTRY_CONNECTED)


    ###########################################################################
    # Check if any agent announced an attached network
    ###########################################################################
    changed_routed = {
      c: prev_vals["routed_networks"] or set()
      for c, prev_vals in changed
        if isinstance(c, UvnPeer) and not c.registry
          and "routed_networks" in prev_vals
    }
    prev_routed = {(c, l) for c, routed in changed_routed.items() for l in routed}
    current_routed = {(c, l) for c in changed_routed for l in c.routed_networks}
    gone_routed = prev_routed - current_routed
    new_routed = current_routed - prev_routed
    if gone_routed or new_routed:
      self._notify(UvnPeerListener.Event.ROUTED_NETWORKS, new_routed, gone_routed)

      ###########################################################################
      # Check if we've discovered all expected networks
      ###########################################################################
      routed_subnets = set(l.nic.subnet for c in self.cells for l in c.routed_networks)
      expected_subnets = set(l for c in self.uvn.cells.values() for l in c.allowed_lans)
      routed_networks_discovered = routed_subnets == expected_subnets
      if routed_networks_discovered != self.status_routed_networks_discovered:
        self.status_routed_networks_discovered = routed_networks_discovered
        self._notify(UvnPeerListener.Event.ROUTED_NETWORKS_DISCOVERED)

    ###########################################################################
    # Check if any agent changed their configuration id
    ###########################################################################
    changed_config = {
      c: prev_vals["registry_id"]
        for c, prev_vals in changed
        if isinstance(c, UvnPeer) and not c.registry
          and "registry_id" in prev_vals
    }
    prev_consistent = {
      c for c, rid in changed_config.items() if rid == self.registry_id
    }
    current_consistent = {
      c for c in changed_config if c.registry_id == self.registry_id
    }
    gone_consistent = prev_consistent - current_consistent
    new_consistent = current_consistent - prev_consistent
    if gone_consistent or new_consistent:
      self._notify(UvnPeerListener.Event.CONSISTENT_CONFIG_CELLS, new_consistent, gone_consistent)
    
      ###########################################################################
      # Check if all agents have the same configuration id as ours
      ###########################################################################
      # self.updated_property("consistent_config_cells")
      # consistent_cells = list(self.consistent_config_cells)
      # inconsistent_cells = list(self.inconsistent_config_cells)
      consistent_config_uvn = sum(1 for c in self.consistent_config_cells) == len(self.uvn.cells)
      if consistent_config_uvn != self.status_consistent_config_uvn:
        self.status_consistent_config_uvn = consistent_config_uvn
        self._notify(UvnPeerListener.Event.CONSISTENT_CONFIG_UVN)

    ###########################################################################
    # Check if any agent has changed their reachable networks
    ###########################################################################
    changed_reachable = {
      c: prev_vals["reachable"]
        for c, prev_vals in changed
          if isinstance(c, LanStatus) and "reachable" in prev_vals
    }
    local_changed_reachable = {status for status in changed_reachable if status.owner.local}
    if local_changed_reachable:
      ###########################################################################
      # Check if the local agent's reachable networks changed
      ###########################################################################
      # prev_reachable = changed_reachable[self.local]
      prev_reachable = {status for status in local_changed_reachable if changed_reachable[status]}
      current_reachable = set(self.local.reachable_networks)
      gone_reachable = prev_reachable - current_reachable
      new_reachable = current_reachable - prev_reachable
      self._notify(UvnPeerListener.Event.LOCAL_REACHABLE_NETWORKS, new_reachable, gone_reachable)

    remote_changed_reachable = {status for status in changed_reachable if not status.owner.local}
    if remote_changed_reachable:
      ###########################################################################
      # Check if the other agents' reachable networks changed
      ###########################################################################
      prev_reachable = {status for status in remote_changed_reachable if changed_reachable[status]}
      current_reachable = {status for p in self if not p.local for status in p.reachable_networks}
      gone_reachable = prev_reachable - current_reachable
      new_reachable = current_reachable - prev_reachable
      if gone_reachable or new_reachable:
        self._notify(UvnPeerListener.Event.REACHABLE_NETWORKS, new_reachable, gone_reachable)

    if changed_reachable:
      ###########################################################################
      # Check if all networks are reachable from everywhere
      ###########################################################################
      fully_routed_uvn = sum(1 for c in self.fully_routed_cells) == len(self.uvn.cells)

      # fully_routed = set(self.fully_routed_cells)
      # fully_routed_uvn = len(fully_routed) == len(self.uvn.cells)
      # not_fully_routed = set(self.cells) - fully_routed
      # if not_fully_routed:
      #   self.log.error("not yet fully routed: {}", not_fully_routed)
      #   for p in not_fully_routed:
      #     self.log.error("- {} ->", p)
      #     reachable = list(p.reachable_networks)
      #     unreachable = list(p.unreachable_networks)
      #     self.log.error("-    r[{}] = {}", len(reachable), reachable)
      #     self.log.error("-   ur[{}] = {}", len(unreachable), unreachable)
      if fully_routed_uvn != self.status_fully_routed_uvn:
        self.status_fully_routed_uvn = fully_routed_uvn
        self._notify(UvnPeerListener.Event.FULLY_ROUTED_UVN)

    self.db.save(self)


  def __len__(self) -> int:
    return len(self._peers)


  def __iter__(self):
    return iter(self._peers)


  def __getitem__(self, i: None | str | int | Uvn | Cell | Particle | Handle) -> UvnPeer:
    try:
      if isinstance(i, int):
        if i == 0:
          result = self._peers[0]
        else:
          result = next(p for p in self if p.cell and p.cell.id == i)
      elif isinstance(i, str):
        result = next(p for p in self if p.name == i)
      elif isinstance(i, Handle):
        result = next(p for p in self if p.instance == i)
      elif isinstance(i, Uvn):
        result = next(p for p in self._peers[:1] if self.uvn == i)
      elif isinstance(i, Cell):
        result = next(p for p in self if p.cell == i)
      elif isinstance(i, Particle):
        result = next(p for p in self if p.particle == i)
      elif i is None:
        result = self._peers[0]
      else:
        raise IndexError(i)
      return result
    except StopIteration:
      raise KeyError(i) from None

