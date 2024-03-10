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
from typing import Optional, Mapping, Iterable, Tuple, Union, Callable, TYPE_CHECKING
import threading
from enum import Enum
import ipaddress

import rti.connextdds as dds

from .uvn_id import UvnId, CellId, ParticleId, Versioned
from .ip import LanDescriptor
from .time import Timestamp
from .wg import WireGuardInterface
from .log import Logger as log


class UvnPeerStatus(Enum):
  DECLARED = 0
  ONLINE = 1
  OFFLINE = 2


class UvnPeer(Versioned):
  class VpnStatus(Versioned):
    def __init__(self,
        parent: "UvnPeer",
        intf: WireGuardInterface,
        online: bool=False) -> None:
      self.parent = parent
      self.intf = intf
      super().__init__()
      self.online = online
      self.loaded = True


    @property
    def online(self) -> Timestamp:
      return self._online


    @online.setter
    def online(self, val: bool) -> None:
      self.update("online", val)



  def __init__(self,
      parent: "UvnPeersList",
      id: int,
      name: str,
      registry_id: str|None=None,
      status: UvnPeerStatus|None=None,
      routed_networks: Iterable[LanDescriptor]|None=None,
      reachable_networks: Iterable[LanDescriptor]|None=None,
      unreachable_networks: Iterable[LanDescriptor]|None=None,
      ih: dds.InstanceHandle|None=None,
      ih_dw: dds.InstanceHandle|None=None,
      ts_start: int|str|Timestamp|None=None,
      particle: bool=False,
      vpn_status: Mapping[WireGuardInterface, Mapping[str, object]]|None=None,
      **init_args) -> None:
    self._parent = parent
    self._id = id
    self._particle = particle
    self._name = name
    super().__init__(**init_args)
    self.registry_id = registry_id
    self.status = status or UvnPeerStatus.DECLARED
    self.ts_start = ts_start
    self.routed_networks = routed_networks
    self.reachable_networks = reachable_networks
    self.unreachable_networks = unreachable_networks
    self.ih = ih
    self.ih_dw = ih_dw
    self.vpn_status = vpn_status
    self.loaded = True


  @property
  def id(self) -> int:
    return self._id


  @property
  def name(self) -> str:
    return self._name


  @property
  def registry_id(self) -> str:
    return self._registry_id


  @registry_id.setter
  def registry_id(self, val: str) -> None:
    self.update("registry_id", val)


  @property
  def status(self) -> UvnPeerStatus:
    return self._status


  @status.setter
  def status(self, val: UvnPeerStatus) -> None:
    self.update("status", val)
    # prev = getattr(self, "_status", None)
    # if prev != UvnPeerStatus.ONLINE and val == UvnPeerStatus.ONLINE:
    #   back = "" if prev == UvnPeerStatus.DECLARED else "back "
    #   log.warning(f"[PEER] {back}ONLINE: {self}")
    # elif prev == UvnPeerStatus.ONLINE and val == UvnPeerStatus.OFFLINE:
    #   log.error(f"[PEER] OFFLINE: {self}")


  @property
  def routed_networks(self) -> set[LanDescriptor]:
    return self._routed_networks


  @routed_networks.setter
  def routed_networks(self, val: Iterable[LanDescriptor]) -> set[LanDescriptor]:
    self.update("routed_networks", set(val or []))


  @property
  def reachable_networks(self) -> set[LanDescriptor]:
    return self._reachable_networks


  @reachable_networks.setter
  def reachable_networks(self, val: Iterable[LanDescriptor]) -> set[LanDescriptor]:
    self.update("reachable_networks", set(val or []))


  @property
  def unreachable_networks(self) -> set[LanDescriptor]:
    return self._unreachable_networks


  @unreachable_networks.setter
  def unreachable_networks(self, val: Iterable[LanDescriptor]) -> set[LanDescriptor]:
    self.update("unreachable_networks", set(val or []))


  @property
  def ih(self) -> dds.InstanceHandle:
    return self._ih


  @ih.setter
  def ih(self, val: dds.InstanceHandle) -> None:
    self.update("ih", val)


  @property
  def ih_dw(self) -> dds.InstanceHandle:
    return self._ih_dw


  @ih.setter
  def ih_dw(self, val: dds.InstanceHandle) -> None:
    self.update("ih_dw", val)


  @property
  def ts_start(self) -> Timestamp:
    return self._ts_start


  @ts_start.setter
  def ts_start(self, val: int|str|Timestamp) -> None:
    if val is not None:
      val = Timestamp.unix(val) if not isinstance(val, Timestamp) else val
    self.update("ts_start", val)


  @property
  def local(self) -> bool:
    return self._parent._local_peer_id == self.id


  @property
  def registry(self) -> bool:
    return 0 == self.id


  @property
  def vpn_status(self) -> "Mapping[WireGuardInterface, UvnPeer.VpnStatus]":
    return self._vpn_status
  

  @vpn_status.setter
  def vpn_status(self, val: Mapping[WireGuardInterface, Mapping[str, object]]) -> None:
    val = val or {}
    current = getattr(self, "_vpn_status", {})
    updated = True if not hasattr(self, "_vpn_status") else False
    for vpn, peer_status in val.items():
      peer_current = current.get(vpn)
      if peer_current is None:
        updated = True
        current[vpn] = UvnPeer.VpnStatus(parent=self, intf=vpn)
      for k, v in peer_status.items():
        if k not in ("online",):
          continue
        setattr(current[vpn], k, v)
        updated = updated or current[vpn].peek_changed
    existing_keys = set(current.keys())
    gone_keys = existing_keys - set(val.keys())
    updated = updated or len(gone_keys) > 0
    for k in gone_keys:
      del current[k]
    if updated:
      self.update("vpn_status", current)


  @property
  def cell(self) -> CellId|None:
    if self.registry or self._particle:
      return None
    return self._parent.uvn_id.cells[self.id]


  @property
  def particle(self) -> ParticleId|None:
    if self.cell or self.registry:
      return None
    return self._parent.uvn_id.particles[self.id]


  @property
  def reachable_subnets(self) -> set[ipaddress.IPv4Network]:
    return {s.nic.subnet for s in self.reachable_networks}



  @property
  def peek_changed(self) -> bool:
    return (
      super().peek_changed
      or next((True for v in self.vpn_status.values() if v.peek_changed), False)
    )


  def collect_changes(self) -> list[Tuple[Versioned, dict]]:
    return [ch
      for o in (super(), *self.vpn_status.values())
        for ch in o.collect_changes()
    ]


  def __eq__(self, other: object) -> TYPE_CHECKING:
    if not isinstance(other, UvnPeer):
      return False
    return self._particle == other._particle and self.id == other.id


  def __hash__(self) -> int:
    return hash(self.id)


  def __str__(self) -> str:
    return self.name



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


  def on_event_reachable_networks(self, new_reachable: set[Tuple[UvnPeer, LanDescriptor]], gone_reachable: set[Tuple[UvnPeer, LanDescriptor]]) -> None:
    pass


  def on_event_fully_routed_uvn(self) -> None:
    pass


  def on_event_vpn_connections(self, new_online: set[UvnPeer.VpnStatus], gone_online: set[UvnPeer.VpnStatus]) -> None:
    pass



class UvnPeersList(Versioned):
  def __init__(self,
      uvn_id: UvnId,
      registry_id: str,
      local_peer_id: int) -> None:
    self.updated_condition = dds.GuardCondition()
    self._local_peer_id = local_peer_id
    self._peers = []
    self.registry_id = registry_id
    self.listeners: list[UvnPeerListener] = list()
    self._update_lock = threading.Lock()
    super().__init__()
    self.uvn_id = uvn_id
    self.status_all_cell_connected = False
    self.status_consistent_config_uvn = False
    self.status_routed_networks_discovered = False
    self.status_fully_routed_uvn = False
    self.status_registry_connected = False
    self.loaded = True


  def _notify(self, event: UvnPeerListener.Event, *args) -> None:
    if self.local.status != UvnPeerStatus.ONLINE:
      return
    for l in self.listeners:
      getattr(l, f"on_event_{event.name.lower()}")(*args)


  @property
  def uvn_id(self) -> UvnId:
    return self._uvn_id


  @uvn_id.setter
  def uvn_id(self, uvn_id: UvnId):
    peers = []
    for uvn_obj in (uvn_id, *uvn_id.cells.values(), *uvn_id.particles.values()):
      try:
        peer = self[uvn_obj]
      except KeyError:
        peer = None
      except IndexError:
        peer = None
      if peer is None:
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


  def collect_changes(self) -> list[Tuple[Versioned, dict]]:
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
        if isinstance(c, UvnPeer.VpnStatus)
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


  def __getitem__(self, i: Union[None, str, int, UvnId, CellId, ParticleId, dds.InstanceHandle]) -> UvnPeer:
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
    elif isinstance(i, UvnId):
      try:
        return next(p for p in self._peers[:0] if self.uvn_id == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, CellId):
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

