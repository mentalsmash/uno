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
from typing import Optional, Mapping, Iterable, Sequence, Tuple, Union, Callable, TYPE_CHECKING

import rti.connextdds as dds

from enum import Enum

import ipaddress

from .uvn_id import UvnId, CellId
from .dds import UvnTopic
from .ip import LanDescriptor, NicDescriptor, ipv4_from_bytes
from .time import Timestamp
from .log import Logger as log

class UvnPeerStatus(Enum):
  DECLARED = 0
  ONLINE = 1
  OFFLINE = 2


class UvnPeer:
  def __init__(self,
      uvn_id: UvnId,
      deployment_id: Optional[str]=None,
      root_vpn_id: Optional[str]=None,
      particles_vpn_id: Optional[str]=None,
      backbone_vpn_ids: Optional[Iterable[str]]=None,
      cell: Optional[CellId]=None,
      local: bool=False,
      status: Optional[UvnPeerStatus]=None,
      routed_sites: Optional[Iterable[LanDescriptor]]=None,
      reachable_sites: Optional[Iterable[LanDescriptor]]=None,
      backbone_peers: Optional[Iterable[int]]=None,
      ih: Optional[dds.InstanceHandle]=None,
      ih_dns: Optional[dds.InstanceHandle]=None,
      ih_dw: Optional[dds.InstanceHandle]=None,
      last_update_ts: Optional[str]=None,
      updated_fields: Optional[Iterable[str]]=None) -> None:
    self.uvn_id = uvn_id
    self.deployment_id = deployment_id
    self.root_vpn_id = root_vpn_id
    self.particles_vpn_id = particles_vpn_id
    self.backbone_vpn_ids = list(backbone_vpn_ids or [])
    self.cell = cell
    self._status = status or UvnPeerStatus.DECLARED
    self.routed_sites = set(routed_sites or [])
    self.reachable_sites = set(reachable_sites or [])
    self.backbone_peers = set(backbone_peers or [])
    self.local = local
    self.ih = ih
    self.ih_dns = ih_dns
    self.ih_dw = ih_dw
    self.last_update_ts = last_update_ts
    self.updated_fields = set(updated_fields or [])


  @property
  def id(self) -> int:
    if self.cell:
      return self.cell.id
    else:
      return 0


  @property
  def status(self) -> UvnPeerStatus:
    return self._status
  

  @status.setter
  def status(self, val: UvnPeerStatus) -> UvnPeerStatus:
    assert(val != UvnPeerStatus.DECLARED)
    prev = self._status
    self._status = val
    if prev != UvnPeerStatus.ONLINE and val == UvnPeerStatus.ONLINE:
      back = "" if prev == UvnPeerStatus.DECLARED else "back "
      log.warning(f"[PEER] {back}ONLINE: {self}")
    elif prev == UvnPeerStatus.ONLINE and val == UvnPeerStatus.OFFLINE:
      log.error(f"[PEER] OFFLINE: {self}")


  def __eq__(self, other: object) -> TYPE_CHECKING:
    if not isinstance(other, UvnPeer):
      return False
    return self.uvn_id == other.uvn_id and self.cell == other.cell


  def __hash__(self) -> int:
    return hash((self.uvn_id, self.cell))


  def __str__(self) -> str:
    return self.name


  @property
  def name(self) -> str:
    if not self.cell:
      return self.uvn_id.name
    else:
      return self.cell.name


  def update(self, **updated_fields) -> bool:
    updated = []
    for f in [
          "deployment_id",
          "root_vpn_id",
          "particles_vpn_id",
          "backbone_vpn_ids",
          "status",
          "routed_sites",
          "reachable_sites",
          "backbone_peers",
          "ih",
          "ih_dns",
          "ih_dw",
        ]:
      if f not in updated_fields:
        continue
      updated_val = updated_fields[f]
      if getattr(self, f) != updated_val:
        setattr(self, f, updated_val)
        updated.append(f)
    if updated:
      self.last_update_ts = Timestamp.now()
      self.updated_fields = set(updated).union(self.updated_fields)
      return True
    return False


  def serialize(self) -> dict:
    serialized = {
      "id": self.id,
      "deployment_id": self.deployment_id,
      "root_vpn_id": self.root_vpn_id,
      "particles_vpn_id": self.particles_vpn_id,
      "backbone_vpn_ids": list(self.backbone_vpn_ids),
      "status": self.status.name,
      "routed_sites": [r.serialize() for r in self.routed_sites],
      "reachable_sites": [r.serialize() for r in self.reachable_sites],
      "backbone_peers": sorted(self.backbone_peers),
      "local": self.local,
      "last_update_ts": self.last_update_ts.format()
        if self.last_update_ts else None,
      "updated_fields": list(self.updated_fields),
    }
    if not serialized["deployment_id"]:
      del serialized["deployment_id"]
    if not serialized["root_vpn_id"]:
      del serialized["root_vpn_id"]
    if not serialized["backbone_vpn_ids"]:
      del serialized["backbone_vpn_ids"]
    if not serialized["particles_vpn_id"]:
      del serialized["particles_vpn_id"]
    if not serialized["routed_sites"]:
      del serialized["routed_sites"]
    if not serialized["reachable_sites"]:
      del serialized["reachable_sites"]
    if not serialized["local"]:
      del serialized["local"]
    if not serialized["backbone_peers"]:
      del serialized["backbone_peers"]
    if not serialized["last_update_ts"]:
      del serialized["last_update_ts"]
    if not serialized["updated_fields"]:
      del serialized["updated_fields"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, uvn_id: UvnId) -> "UvnPeer":
    id = serialized["id"]
    cell = None if id == 0 else uvn_id.cells[id]
    last_update_ts = serialized.get("last_update_ts")
    if last_update_ts:
      last_update_ts = Timestamp.parse(last_update_ts)
    return UvnPeer(
      uvn_id=uvn_id,
      deployment_id=serialized.get("deployment_id"),
      root_vpn_id=serialized.get("root_vpn_id"),
      particles_vpn_id=serialized.get("particles_vpn_id"),
      backbone_vpn_ids=serialized.get("backbone_vpn_ids"),
      cell=cell,
      status=UvnPeerStatus[serialized["status"]],
      local=serialized.get("local", False),
      routed_sites=[
        LanDescriptor.deserialize(r)
          for r in serialized.get("routed_sites", [])
      ],
      reachable_sites=[
        LanDescriptor.deserialize(r)
          for r in serialized.get("reachable_sites", [])
      ],
      backbone_peers=serialized.get("backbone_peers", []),
      last_update_ts=last_update_ts,
      updated_fields=serialized.get("updated_fields"))


class UvnPeersList:
  def __init__(self,
      uvn_id: UvnId,
      local_peer_id: int,
      peers: Optional[Iterable[UvnPeer]]=None) -> None:
    self.updated_condition = dds.GuardCondition()
    self._uvn_id = uvn_id
    self._local_peer_id = local_peer_id
    self._set_uvn_id(uvn_id, peers or (
      UvnPeer(
        uvn_id=self.uvn_id,
        cell=cell,
        local=(
          (cell is None and not local_peer_id)
          or (cell is not None and cell.id == local_peer_id)
        ))
      for cell in (None, *self.uvn_id.cells.values())
    ))


  def _set_uvn_id(self, uvn_id: UvnId, peers: Iterable[UvnPeer]) -> None:
    self._uvn_id = uvn_id
    self._peers = sorted(peers, key=lambda v: v.id)
    self._on_peers_updated()


  def _on_peers_updated(self) -> None:
    self._online_peers_count = sum(1 for p in self.online_peers)
    self._offline_peers_count = sum(1 for p in self.offline_peers)

    # Check if the subnet intersects with any other
    by_subnet = {}
    clashes = {}
    subnets = set()
    for peer in self:
      for site in peer.routed_sites:
        subnet_peers = by_subnet[site.nic.subnet] = by_subnet.get(site.nic.subnet, set())
        subnet_peers.add((peer, site))
        if len(subnet_peers) > 1:
          clashes[site.nic.subnet] = subnet_peers
        for subnet in subnets:
          if subnet.overlaps(site.nic.subnet):
            by_subnet[subnet].add((peer, site))
            clashes[subnet] = by_subnet[subnet]
        subnets.add(site.nic.subnet)
    self._routed_sites_clashing = clashes

    self.updated_condition.trigger_value = True


  @property
  def uvn_id(self) -> UvnId:
    return self._uvn_id


  @uvn_id.setter
  def uvn_id(self, uvn_id: UvnId):
    peers = []

    for cell in (None, *uvn_id.cells.values()):
      try:
        peer = self[cell]
        peer.uvn_id = uvn_id
        peer.cell = cell
        peer.local = self.local_peer.cell == cell
      except KeyError:
        peer = None
      except IndexError:
        peer = None
      if not peer:
        peer = UvnPeer(uvn_id=uvn_id, cell=cell)
      peers.append(peer)

    self._set_uvn_id(uvn_id, peers)


  @property
  def local_peer(self) -> UvnPeer:
    return self[self._local_peer_id]


  @property
  def online_peers_count(self) -> int:
    return self._online_peers_count


  @property
  def online_peers(self) -> Iterable[UvnPeer]:
    return (p for p in self if p.id and p.status == UvnPeerStatus.ONLINE)


  @property
  def offline_peers_count(self) -> int:
    return self._offline_peers_count


  @property
  def offline_peers(self) -> Iterable[UvnPeer]:
    return (p for p in self if p.id and p.status != UvnPeerStatus.ONLINE)


  @property
  def active_routed_sites(self) -> Iterable[LanDescriptor]:
    return (s for p in self if p.id and p.status == UvnPeerStatus.ONLINE for s in p.routed_sites)


  @property
  def inactive_routed_sites(self) -> Iterable[LanDescriptor]:
    return {s for p in self if p.id and p.status != UvnPeerStatus.ONLINE for s in p.routed_sites}


  @property
  def clashing_routed_sites(self) -> Mapping[ipaddress.IPv4Network, set[Tuple[UvnPeer, LanDescriptor]]]:
    return self._routed_sites_clashing


  def clear(self) -> None:
    for p in self:
      p.updated_fields.clear()


  def update_peer(self,
      peer: UvnPeer,
      **updated_fields) -> bool:
    updated = peer.update(**updated_fields)
    if not updated:
      return False
    log.debug(f"updated peer fields: {peer} -> {peer.updated_fields}")
    self._on_peers_updated()
    return True


  def update_all(self,
      peers: Iterable[UvnPeer] | None = None,
      query: Callable[[UvnPeer], bool] | None = None,
      **updated_fields) -> bool:
    updated = {}
    for peer in peers or self:
      if query and not query(peer):
        continue
      p_updated = peer.update(**updated_fields)
      if p_updated:
        log.debug(f"updated peer fields: {peer} -> {peer.updated_fields}")
        updated[peer.id] = p_updated
    if not updated:
      return False
    self._on_peers_updated()
    return True


  def __len__(self) -> int:
    return len(self._peers)


  def __iter__(self):
    return iter(self._peers)


  def __getitem__(self, i: Union[int, Optional[CellId], dds.InstanceHandle]) -> UvnPeer:
    if isinstance(i, int):
      return self._peers[i]
    elif isinstance(i, dds.InstanceHandle):
      try:
        return next(p for p in self._peers if p.ih == i)
      except StopIteration:
        raise KeyError(i) from None
    elif isinstance(i, CellId):
      return self._peers[i.id]
    elif i is None:
      return self._peers[0]
    else:
      raise IndexError(i)


  def serialize(self) -> dict:
    serialized = {
      "uvn_id": self.uvn_id.serialize(),
      "local_peer_id": self.local_peer.id,
      "peers": [p.serialize() for p in self]
    }
    if not serialized["peers"]:
      del serialized["peers"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "UvnPeersList":
    uvn_id = UvnId.deserialize(serialized["uvn_id"])
    return UvnPeersList(
      uvn_id=uvn_id,
      local_peer_id=serialized["local_peer_id"],
      peers=[
        UvnPeer.deserialize(p, uvn_id)
          for p in serialized.get("peers", [])
      ])


