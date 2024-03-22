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
from functools import cached_property
import threading
from enum import Enum
import ipaddress

import rti.connextdds as dds

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.versioned import Versioned, prepare_timestamp, prepare_enum, serialize_enum
from ..registry.database import DatabaseObjectOwner, OwnableDatabaseObject

from ..core.time import Timestamp
from ..core.wg import WireGuardInterface


class UvnPeerStatus(Enum):
  DECLARED = 0
  ONLINE = 1
  OFFLINE = 2


class UvnPeer(Versioned, DatabaseObjectOwner, OwnableDatabaseObject):
  PROPERTIES = [
    "registry_id",
    "status",
    "routed_networks",
    "ih",
    "ih_dw",
    "ts_start",
  ]
  VOLATILE_PROPERTIES = [
    "ih",
    "ih_dw",
  ]
  CACHED_PROPERTIES = [
    "reachable_networks",
    "unreachable_networks",
    "known_networks",
    "vpn_interfaces",
  ]
  EQ_PROPERTIES = [
    "owner",
  ]
  STR_PROPERTIES = [
    "owner",
  ]
  PROPERTY_GROUPS = {
    "know_networks": ["reachable_networks", "unreachable_networks"],
  }
  INITIAL_STATUS = UvnPeerStatus.DECLARED
  INITIAL_VPN_INTERFACES = lambda self: self.load_children(VpnInterfaceStatus, owner=self)
  INITIAL_KNOWN_NETWORKS = lambda self: self.load_children(LanStatus, owner=self)
  INITIAL_ROUTED_NETWORKS = lambda self: set()

  DB_TABLE = "peers"
  DB_OWNER = [Uvn, Cell, Particle]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = [
    "registry_id",
    "status",
    "ts_start",
    "routed_networks",
    "owner_id",
  ]

  @cached_property
  def vpn_interfaces(self):
    return self.load_children(VpnInterfaceStatus, owner=self)


  @cached_property
  def known_networks(self):
    return self.load_children(LanStatus, owner=self)


  def prepare_routed_networks(self, val: str|Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return self.deserialize_collection(LanDescriptor, val, set, self.new_child)


  def prepare_ts_start(self, val: int|str|Timestamp) -> None:
    return prepare_timestamp(self.db, val)


  def prepare_status(self, val: str|UvnPeerStatus) -> UvnPeerStatus:
    return prepare_enum(self.db, val)


  def configure_vpn_interfaces(self, peer_vpn_stats: dict[WireGuardInterface, dict]) -> None:
    for intf, intf_stats in peer_vpn_stats.items():
      intf_status = next((s for s in self.vpn_interfaces if s == intf), None)
      if intf_status is None:
        intf_status = self.new_child(VpnInterfaceStatus, {
          "intf": intf,
          **intf_stats,
        })
        self.vpn_interfaces.add(intf_status)
        self.updated_property("vpn_interfaces")
      else:
        intf_status.configure(**intf_stats)


  def configure_known_networks(self, known_networks: None|list[dict]) -> None:
    for net_cfg in (known_networks or []):
      known_net = self.new_child(LanStatus, net_cfg, save=False)
      prev_known_net = next((n for n in self.known_networks if n == known_net), None)
      if prev_known_net is None:
        known_net = self.new_child(LanStatus, known_net)
        self.known_networks.add(known_net)
        self.updated_property("known_networks")
      else:
        prev_known_net.configure(net_cfg)
        self.known_networks.add(prev_known_net)


  @property
  def local(self) -> bool:
    assert(self.parent.owner is not None)
    assert(self.owner is not None)
    return self.parent.parent == self.owner


  @property
  def particle(self) -> Particle|None:
    owner = self.owner
    if not isinstance(owner, Particle):
      return None
    return self.owner


  @property
  def cell(self) -> Cell|None:
    owner = self.owner
    if not isinstance(owner, Cell):
      return None
    return self.owner


  @property
  def registry(self) -> bool:
    owner = self.owner
    if not isinstance(owner, Uvn):
      return False
    return True


  @property
  def uvn(self) -> Uvn:
    if self.registry:
      return self.owner
    else:
      return self.owner.uvn


  @cached_property
  def reachable_networks(self) -> Generator["LanStatus", None, None]:
    for n in self.known_networks:
      if not n.reachable:
        continue
      yield n


  @cached_property
  def unreachable_networks(self) -> Generator["LanStatus", None, None]:
    for n in self.known_networks:
      if n.reachable:
        continue
      yield n


  def prepare_vpn_interfaces(self, vpn_stats: dict[WireGuardInterface, dict[str, object]]) -> "set[VpnInterfaceStatus]":
    for intf, intf_stats in vpn_stats.items():
      intf_status = next((s for s in self.vpn_interfaces if s == intf), None)
      if intf_status is None:
        intf_status = self.new_child(VpnInterfaceStatus, {
          "intf": intf,
          **intf_stats,
        })
        self.vpn_interfaces.add(intf_status)
        self.updated_property("vpn_interfaces")
      else:
        intf_status.configure(**intf_stats)
    return self.vpn_interfaces


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for status in self.vpn_interfaces:
      yield status
    for net in self.known_networks:
      yield net



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
  EQ_PROPERTIES = [
    "intf",
  ]
  INITIAL_ONLINE = False


class LanStatus(Versioned, OwnableDatabaseObject):
  DB_TABLE = "peers_lan_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"

  PROPERTIES = [
    "lan",
    "reachable",
  ]
  REQ_PROPERTIES = [
    "lan",
  ]
  EQ_PROPERTIES = [
    "lan",
  ]
  INITIAL_REACHABLE = False

  @property
  def local(self) -> bool:
    return self.lan in self.owner.routed_networks

  def prepare_lan(self, val: str | dict | LanDescriptor) -> LanDescriptor:
    return self.new_child(LanDescriptor, val)



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
    "registry_id",
    "status_all_cell_connected",
    "status_consistent_config_uvn",
    "status_routed_networks_discovered",
    "status_fully_routed_uvn",
    "status_registry_connected",
  ]
  REQ_PROPERTIES = [
    "uvn",
    "registry_id",
  ]
  PROPERTY_GROUPS = {
    "uvn": [
      "local",
      "cells",
      "registry",
      "particles",
    ],
    "cells": [
      "other_cells",
      "online_cells",
      "consistent_config_cells",
      "fully_routed_cells",
    ],
  }
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


  def _assert_peers(self, uvn: Uvn) -> None:
    with self._update_lock:
      peers_changed = False
      peers = []
      for uvn_obj in (uvn, *uvn.cells.values(), *uvn.particles.values()):
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
            peers_changed = True

        peers.append(peer)
      self._peers = peers
      if peers_changed:
        # Mark property as updated so cached properties are reset
        self.updated_property("uvn")


  def prepare_uvn(self, val: Uvn) -> Uvn:
    self._peers = self._assert_peers(val)
    return val


  @cached_property
  def local(self) -> UvnPeer:
    return self[self.parent]


  @cached_property
  def registry(self) -> UvnPeer:
    return self[self.uvn]


  @cached_property
  def cells(self) -> list[UvnPeer]:
    return [p for p in self if p.cell]


  @cached_property
  def particles(self) -> list[UvnPeer]:
    return [p for p in self if p.particle]


  @cached_property
  def other_cells(self) -> list[UvnPeer]:
    return [p for p in self.cells if p.cell != self.parent]


  @cached_property
  def online_cells(self) -> list[UvnPeer]:
    return [p for p in self.cells if p.status == UvnPeerStatus.ONLINE]


  @cached_property
  def consistent_config_cells(self) -> list[UvnPeer]:
    return [c for c in self.cells if c.registry_id == self.registry_id]


  @cached_property
  def fully_routed_cells(self) -> list[UvnPeer]:
    expected_subnets = {l for c in self.uvn.cells.values() for l in c.allowed_lans}
    return [
      c for c in self.cells if {l.lan.nic.subnet for l in c.reachable_networks} == expected_subnets
    ]


  def online(self, **local_peer_fields) -> None:
    self.update_peer(self.local,
      status=UvnPeerStatus.ONLINE,
      **local_peer_fields)


  def offline(self) -> None:
    if self.local.status == UvnPeerStatus.OFFLINE:
      return

    self.update_all(
      status=UvnPeerStatus.OFFLINE,
      registry_id=None,
      routed_networks=None,
      known_networks=None,
      ih=None,
      ih_dw=None,
      ts_start=None)
  

  def update_peer(self,
      peer: UvnPeer,
      **updated_fields) -> None:
    with self._update_lock:
      peer.configure(**updated_fields)
      self._process_updates()


  def update_all(self,
      peers: Iterable[UvnPeer] | None = None,
      query: Callable[[UvnPeer], bool] | None = None,
      **updated_fields) -> None:
    with self._update_lock:
      for peer in peers or self:
        if query and not query(peer):
          continue
        peer.configure(**updated_fields)
      self._process_updates()


  def configure(self, **properties) -> None:
    super().configure(**properties)
    with self._update_lock:
      self._process_updates()


  def _process_updates(self) -> None:
    changed = self.collect_changes()
    if not changed:
      return

    self.log.activity("processing {} updated objects", len(changed))

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
      self.updated_property("online_cells")
      all_cell_connected = sum(1 for c in self.online_cells) == len(self.uvn.cells)
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
      self.updated_property("consistent_config_cells")
      consistent_config_uvn = sum(1 for c in self.consistent_config_cells) == len(self.uvn.cells)
      if consistent_config_uvn != self.status_consistent_config_uvn:
        self.status_consistent_config_uvn = consistent_config_uvn
        self._notify(UvnPeerListener.Event.CONSISTENT_CONFIG_UVN)

    ###########################################################################
    # Check if any agent has changed their reachable/unreachable networks
    ###########################################################################
    changed_reachable = {
      c: prev_vals["reachable"]
        for c, prev_vals in changed
          if isinstance(c, LanStatus) and "reachable" in prev_vals
    }
    local_changed_reachable = {lan for lan in changed_reachable if lan.owner == self.local}
    if local_changed_reachable:
      ###########################################################################
      # Check if the local agent's reachable/unreachable networks changed
      ###########################################################################
      # prev_reachable = changed_reachable[self.local]
      prev_reachable = {lan for lan in local_changed_reachable if changed_reachable[lan]}
      current_reachable = {lan for lan in self.local.reachable_networks}
      gone_reachable = prev_reachable - current_reachable
      new_reachable = current_reachable - prev_reachable
      self._notify(UvnPeerListener.Event.LOCAL_REACHABLE_NETWORKS, new_reachable, gone_reachable)

    ###########################################################################
    # Check if the other agents' reachable/unreachable networks changed
    ###########################################################################
    prev_reachable = {n for n, reachable in changed_reachable.items() if n.owner != self.local and reachable}
    current_reachable = {n for p in self if not p.local for n in p.known_networks if n.reachable}
    gone_reachable = prev_reachable - current_reachable
    new_reachable = current_reachable - prev_reachable
    if gone_reachable or new_reachable:
      self._notify(UvnPeerListener.Event.REACHABLE_NETWORKS, new_reachable, gone_reachable)

    if changed_reachable:
      ###########################################################################
      # Check if all networks are reachable from everywhere
      ###########################################################################
      self.updated_property("fully_routed_cells")
      fully_routed_uvn = sum(1 for c in self.fully_routed_cells) == len(self.uvn.cells)
      if fully_routed_uvn != self.status_fully_routed_uvn:
        self.status_fully_routed_uvn = fully_routed_uvn
        self._notify(UvnPeerListener.Event.FULLY_ROUTED_UVN)
    
    self.updated_condition.trigger_value = True
    self.db.save(self)


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
        return next(p for p in self._peers[:0] if self.uvn == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, Cell):
      try:
        return next(p for p in self._peers[1:] if p.cell == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, Particle):
      try:
        return next(p for p in self._peers[1:] if p.particle == i)
      except StopIteration:
        raise KeyError(i) from None
    elif i is None:
      return self._peers[0]
    else:
      raise IndexError(i)

