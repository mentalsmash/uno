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
from typing import Generator, Iterable, Callable, TYPE_CHECKING
import threading
from enum import Enum
import ipaddress

import rti.connextdds as dds

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.versioned import Versioned, prepare_timestamp
from ..registry.database import DatabaseObjectOwner, OwnableDatabaseObject

from ..core.time import Timestamp
from ..core.wg import WireGuardInterface
from ..core.log import Logger as log


class UvnPeerStatus(Enum):
  DECLARED = 0
  ONLINE = 1
  OFFLINE = 2


class UvnPeerType(Enum):
  REGISTRY = 0
  CELL = 1
  PARTICLE = 2

  @classmethod
  def from_object(cls, obj: object) -> "UvnPeerType":
    if isinstance(obj, Particle):
      return UvnPeerType.PARTICLE
    elif isinstance(obj, Cell):
      return UvnPeerType.CELL
    elif isinstance(obj, Uvn):
      return UvnPeerType.REGISTRY
    else:
      raise NotImplementedError(obj)


class UvnPeer(Versioned, DatabaseObjectOwner, OwnableDatabaseObject):
  DB_TABLE = "peers"
  DB_OWNER = [Uvn, Cell, Particle]
  DB_OWNER_TABLE = {
    Uvn: "peer_owner_uvns",
    Cell: "peer_owner_cells",
    Particle: "peer_owner_particle",
  }

  PROPERTIES = [
    "registry_id",
    "status",
    "networks",
    "routed_networks",
    "reachable_networks",
    "unreachable_networks",
    "ih",
    "ih_dw",
    "vpn_interfaces",
    "ts_start",
  ]
  INITIAL_STATUS = UvnPeerStatus.DECLARED
  INITIAL_VPN_INTERFACES = lambda self: set()


  def prepare_lan_descriptor(self, val: Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    return self.deserialize_collection(LanDescriptor, val, set, self.deserialize_child)


  def prepare_routed_networks(self, val: Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    return self.prepare_lan_descriptor(val)


  def prepare_reachable_networks(self, val: Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    return self.prepare_lan_descriptor(val)


  def prepare_unreachable_networks(self, val: Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    return self.prepare_lan_descriptor(val)


  def prepare_ts_start(self, val: int|str|Timestamp) -> None:
    return prepare_timestamp(self.db, val)


  @property
  def peer_type(self) -> UvnPeerType:
    return UvnPeerType.from_object(self.owner)


  @property
  def peer_id(self) -> int:
    return self.owner.id


  @property
  def local(self) -> bool:
    return (self.peer_type == self.parent.local_peer_type and self.parent.local_peer_id == self.peer_id)


  @property
  def particle(self) -> Particle|None:
    if self.peer_type != UvnPeerType.PARTICLE:
      return None
    return self.owner


  @property
  def cell(self) -> Cell|None:
    if self.peer_type != UvnPeerType.CELL:
      return None
    return self.owner


  @property
  def registry(self) -> bool:
    return self.peer_type != UvnPeerType.REGISTRY


  def prepare_vpn_interfaces(self, vpn_stats: dict[WireGuardInterface, dict[str, object]]) -> "set[VpnInterfaceStatus]":
    for intf, intf_stats in vpn_stats.items():
      intf_status = next((s for s in self.vpn_interfaces if s == intf), None)
      if intf_status is None:
        intf_status = self.deserialize_child(VpnInterfaceStatus, {
          "intf": intf,
          **intf_stats,
        })
        self.vpn_interfaces.add(intf_status)
      else:
        intf_status.configure(**intf_stats)
    return self.vpn_interfaces


  @property
  def reachable_subnets(self) -> set[ipaddress.IPv4Network]:
    return {s.nic.subnet for s in self.reachable_networks}


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for status in self.vpn_interfaces:
      yield status


class VpnInterfaceStatus(Versioned, OwnableDatabaseObject):
  DB_TABLE = "peers_vpn_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"

  PROPERTIES = [
    "intf",
    "online",
  ]
  REQ_PROPERTIES = [
    "intf",
  ]
  INITIAL_ONLINE = False


class LanStatus(Versioned, OwnableDatabaseObject):
  DB_TABLE = "peers_lan_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"

  PROPERTIES = [
    "lan",
    "local",
    "reachable",
  ]
  REQ_PROPERTIES = [
    "lan",
  ]
  INITIAL_REACHABLE = False



class UvnPeerListener:
  class Event(Enum):
    ONLINE_CELLS = 0
    ALL_CELLS_CONNECTED = 1
    REGISTRY_CONNECTED = 2
    ROUTED_NETWORKS = 3
    ROUTED_NETWORKS_DISCOVERED = 4
    CONSISTENT_CONFIG_CELLS = 5
    CONSISTENT_CONFIG_UVN = 6
    LOCAL_REACHABLE_NETWORKS = 7
    REACHABLE_NETWORKS = 8
    FULLY_ROUTED_UVN = 9
    VPN_CONNECTIONS = 10


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
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
    "uvn",
    "local_peer_id",
    "local_peer_type",
    "registry_id",
    "status_all_cell_connected",
    "status_consistent_config_uvn",
    "status_routed_networks_discovered",
    "status_fully_routed_uvn",
    "status_registry_connected",
    "peers",
  ]
  REQ_PROPERTIES = [
    "uvn",
    "local_peer_id",
    "local_peer_type",
    "registry_id",
  ]
  INITIAL_ALL_CELL_CONNECTED = False
  INITIAL_CONSISTENT_CONFIG_UVN = False
  INITIAL_ROUTED_NETWORKS_DISCOVERED = False
  INITIAL_FULLY_ROUTED_UVN = False
  INITIAL_REGISTRY_CONNECTED = False


  def __init__(self, **properties) -> None:
    self.updated_condition = dds.GuardCondition()
    self.listeners: list[UvnPeerListener] = list()
    self._peers = []
    self._update_lock = threading.Lock()
    super().__init__(**properties)


  def _notify(self, event: UvnPeerListener.Event, *args) -> None:
    if self.local.status != UvnPeerStatus.ONLINE:
      return
    for l in self.listeners:
      getattr(l, f"on_event_{event.name.lower()}")(*args)


  def assert_peers(self):
    peers = []
    for uvn_obj in (self.uvn, *self.uvn.all_cells.values(), *self.uvn.all_particles.values()):
      try:
        peer = self[uvn_obj]
      except KeyError:
        peer = None
      except IndexError:
        peer = None
      if peer is None:
        peer = self.deserialize_child(UvnPeer, {
          "id": uvn_obj.id,
          "name": uvn_obj.name,
        })


        peer = UvnPeer(
          parent=self,
          id=0 if uvn_obj == uvn_id else uvn_obj.id,
          name=uvn_obj.name,
          particle=isinstance(uvn_obj, ParticleId))
      peers.append(peer)
    self._uvn_id = uvn_id
    self._peers = sorted(peers, key=lambda v: v.id)
    


  @property
  def local(self) -> UvnPeer:
    return self[self._local_peer_id]


  @property
  def registry(self) -> UvnPeer:
    return self[0]


  @property
  def cells(self) -> Iterable[UvnPeer]:
    return (p for p in self if p.cell)


  @property
  def particles(self) -> Iterable[UvnPeer]:
    return (p for p in self if p.particle)


  @property
  def other_cells(self) -> Iterable[UvnPeer]:
    return (p for p in self.cells if p.id != self._local_peer_id)


  @property
  def online_cells(self) -> Iterable[UvnPeer]:
    return (p for p in self.cells if p.status == UvnPeerStatus.ONLINE)


  @property
  def consistent_config_cells(self) -> Iterable[UvnPeer]:
    return (c for c in self.cells if c.registry_id == self.registry_id)


  @property
  def fully_routed_cells(self) -> Iterable[UvnPeer]:
    expected_subnets = {l for c in self.uvn_id.cells.values() for l in c.allowed_lans}
    return (
      c for c in self.cells if {l.nic.subnet for l in c.reachable_networks} == expected_subnets
    )


  @property
  def status_all_cell_connected(self) -> bool:
    return self._status_all_cell_connected


  @status_all_cell_connected.setter
  def status_all_cell_connected(self, val: bool) -> None:
    self.update("status_all_cell_connected", val)


  @property
  def status_registry_connected(self) -> bool:
    return self._status_registry_connected


  @status_registry_connected.setter
  def status_registry_connected(self, val: bool) -> None:
    self.update("status_registry_connected", val)


  @property
  def status_routed_networks_discovered(self) -> bool:
    return self._status_routed_networks_discovered


  @status_routed_networks_discovered.setter
  def status_routed_networks_discovered(self, val: bool) -> None:
    self.update("status_routed_networks_discovered", val)


  @property
  def status_consistent_config_uvn(self) -> bool:
    return self._status_consistent_config_uvn


  @status_consistent_config_uvn.setter
  def status_consistent_config_uvn(self, val: bool) -> None:
    self.update("status_consistent_config_uvn", val)


  @property
  def status_fully_routed_uvn(self) -> bool:
    return self._status_fully_routed_uvn


  @status_fully_routed_uvn.setter
  def status_fully_routed_uvn(self, val: bool) -> None:
    self.update("status_fully_routed_uvn", val)


  @property
  def peek_changed(self) -> bool:
    return (
      super().peek_changed
      or next((True for p in self if p.peek_changed), False)
    )


  def collect_changes(self) -> list[tuple[Versioned, dict]]:
    return [ch
      for o in (super(), *self)
        for ch in o.collect_changes()
    ]


  def online(self, **local_peer_fields) -> None:
    self.update_peer(self.local,
      status=UvnPeerStatus.ONLINE,
      **local_peer_fields)
    self.process_updates()


  def offline(self) -> None:
    if self.local.status == UvnPeerStatus.OFFLINE:
      return

    self.update_all(
      status=UvnPeerStatus.OFFLINE,
      registry_id=None,
      routed_networks=None,
      reachable_networks=None,
      unreachable_networks=None,
      ih=None,
      ih_dw=None,
      ts_start=None)
  
    self.process_updates()
  

  def update_peer(self,
      peer: UvnPeer,
      **updated_fields) -> bool:
    with self._update_lock:
      for f, v in updated_fields.items():
        setattr(peer, f, v)
      # updated = peer.update(**updated_fields)
      if not peer.peek_changed:
        return False
      log.activity(f"updated: {peer} → {list(updated_fields)}")
      self.updated_condition.trigger_value = True
      return True


  def update_all(self,
      peers: Iterable[UvnPeer] | None = None,
      query: Callable[[UvnPeer], bool] | None = None,
      **updated_fields) -> bool:
    with self._update_lock:
      updated = set()
      for peer in peers or self:
        if query and not query(peer):
          continue
        # p_updated = peer.update(**updated_fields)
        for f, v in updated_fields.items():
          setattr(peer, f, v)
        if peer.peek_changed:
          log.activity(f"updated: {peer} → {list(updated_fields)}")
          updated.add(peer)
      if not updated:
        return False
      self.updated_condition.trigger_value = True
      return True


  def process_updates(self) -> None:
    with self._update_lock:
      changed = self.collect_changes()
    
    if not changed:
      return
  
    log.activity(f"[STATUS] processing {len(changed)} updated objects")

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
      all_cell_connected = sum(1 for c in self.online_cells) == len(self.uvn_id.cells)
      if all_cell_connected != self.status_all_cell_connected:
        self.status_all_cell_connected = all_cell_connected
        self._notify(UvnPeerListener.Event.ALL_CELLS_CONNECTED)

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
      expected_subnets = set(l for c in self.uvn_id.cells.values() for l in c.allowed_lans)
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
      consistent_config_uvn = sum(1 for c in self.consistent_config_cells) == len(self.uvn_id.cells)
      if consistent_config_uvn != self.status_consistent_config_uvn:
        self.status_consistent_config_uvn = consistent_config_uvn
        self._notify(UvnPeerListener.Event.CONSISTENT_CONFIG_UVN)

    ###########################################################################
    # Check if any agent has changed their reachable/unreachable networks
    ###########################################################################
    changed_reachable = {
      c: prev_vals["reachable_networks"] or set()
        for c, prev_vals in changed
          if isinstance(c, UvnPeer) and not c.registry
            and "reachable_networks" in prev_vals
    }

    if self.local in changed_reachable:
      ###########################################################################
      # Check if the local agent's reachable/unreachable networks changed
      ###########################################################################
      prev_reachable = changed_reachable[self.local]
      current_reachable = self.local.reachable_networks
      gone_reachable = prev_reachable - current_reachable
      new_reachable = current_reachable - prev_reachable
      self._notify(UvnPeerListener.Event.LOCAL_REACHABLE_NETWORKS, new_reachable, gone_reachable)

    ###########################################################################
    # Check if the other agents' reachable/unreachable networks changed
    ###########################################################################
    prev_reachable = {(c, l) for c, reachable in changed_reachable.items() if c != self.local for l in reachable}
    current_reachable = {(c, l) for c in changed_reachable if c != self.local for l in c.reachable_networks}
    gone_reachable = prev_reachable - current_reachable
    new_reachable = current_reachable - prev_reachable
    if gone_reachable or new_reachable:
      self._notify(UvnPeerListener.Event.REACHABLE_NETWORKS, new_reachable, gone_reachable)

    if changed_reachable:
      ###########################################################################
      # Check if all networks are reachable from everywhere
      ###########################################################################
      fully_routed_uvn = sum(1 for c in self.fully_routed_cells) == len(self.uvn_id.cells)
      if fully_routed_uvn != self.status_fully_routed_uvn:
        self.status_fully_routed_uvn = fully_routed_uvn
        self._notify(UvnPeerListener.Event.FULLY_ROUTED_UVN)


  def __len__(self) -> int:
    return len(self._peers)


  def __iter__(self):
    return iter(self._peers)


  def __getitem__(self, i: None | str | int | Uvn | Cell | Particle | dds.InstanceHandle) -> UvnPeer:
    if isinstance(i, int):
      if i == 0:
        return self._peers[0]
      try:
        return next(p for p in self._peers[1:] if p.id == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, str):
      try:
        return next(p for p in self._peers if p.name == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, dds.InstanceHandle):
      try:
        return next(p for p in self._peers if p.ih == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, Uvn):
      try:
        return next(p for p in self._peers[:0] if self.uvn_id == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, Cell):
      try:
        return next(p for p in self._peers[1:] if p.cell == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, ParticleId):
      try:
        return next(p for p in self._peers[1:] if p.particle == i)
      except StopIteration:
        raise KeyError(i) from None
    elif i is None:
      return self._peers[0]
    else:
      raise IndexError(i)

