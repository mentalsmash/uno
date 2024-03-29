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
from ..registry.versioned import Versioned, prepare_timestamp, prepare_enum, serialize_enum, prepare_collection
from ..registry.database import DatabaseObjectOwner, OwnableDatabaseObject

from ..core.time import Timestamp
from ..core.wg import WireGuardInterface

if TYPE_CHECKING:
  from .agent import Agent

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
  # INITIAL_VPN_INTERFACES = lambda self: set(self.load_children(VpnInterfaceStatus, owner=self))
  # INITIAL_KNOWN_NETWORKS = lambda self: set(self.load_children(LanStatus, owner=self))
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
    return set(self.load_children(VpnInterfaceStatus, owner=self))


  @cached_property
  def known_networks(self):
    return set(self.load_children(LanStatus, owner=self))


  def prepare_routed_networks(self, val: str|Iterable[dict|LanDescriptor]) -> set[LanDescriptor]:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return self.deserialize_collection(LanDescriptor, val, set, self.new_child)


  def prepare_ts_start(self, val: int|str|Timestamp) -> None:
    return prepare_timestamp(self.db, val)


  def prepare_status(self, val: str|UvnPeerStatus) -> UvnPeerStatus:
    return prepare_enum(self.db, UvnPeerStatus, val)


  def configure_vpn_interfaces(self, peer_vpn_stats: dict[WireGuardInterface, dict]) -> bool:
    for intf, intf_stats in peer_vpn_stats.items():
      intf_status = next((s for s in self.vpn_interfaces if s.intf == intf.config.intf.name), None)
      if intf_status is None:
        self.log.debug("new vpn interface status for {}: {}", intf, intf_stats)
        intf_status = self.new_child(VpnInterfaceStatus, {
          "intf": intf.config.intf.name,
          **intf_stats,
        }, owner=self)
        self.vpn_interfaces.add(intf_status)
        self.updated_property("vpn_interfaces")
        return True
      else:
        changed = intf_status.configure(**intf_stats)
        if changed:
          self.updated_property("vpn_interfaces")
          return True
      return False


  def configure_known_networks(self, known_networks: None|list[dict]) -> bool:
    for net_cfg in (known_networks or []):
      known_net = self.new_child(LanStatus, net_cfg, save=False)
      prev_known_net = next((n for n in self.known_networks if n == known_net), None)
      if prev_known_net is None:
        known_net = self.new_child(LanStatus, known_net, owner=self)
        self.known_networks.add(known_net)
        self.updated_property("known_networks")
        return True
      else:
        changed = prev_known_net.configure(net_cfg)
        if changed:
          return True
      return False


  @property
  def local(self) -> bool:
    assert(self.parent.parent is not None)
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


  @property
  def reachable_networks(self) -> Generator["LanStatus", None, None]:
    for n in self.known_networks:
      if not n.reachable:
        continue
      yield n


  @property
  def unreachable_networks(self) -> Generator["LanStatus", None, None]:
    for n in self.known_networks:
      if n.reachable:
        continue
      yield n


  def prepare_vpn_interfaces(self, vpn_stats: dict[WireGuardInterface, dict[str, object]]) -> "set[VpnInterfaceStatus]":
    self.configure_vpn_interfaces(vpn_stats)
    return self.vpn_interfaces


  def prepare_known_networks(self, known_networks: None|list[dict]) -> "set[LanStatus]":
    self.configure_known_networks(known_networks)
    return self.known_networks


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for status in self.vpn_interfaces:
      yield status
    for net in self.known_networks:
      yield net



class VpnInterfaceStatus(Versioned, OwnableDatabaseObject):
  PROPERTIES = [
    "intf",
    "online",
    "last_handshake",
    "transfer",
    "endpoint",
    "allowed_ips",
  ]
  REQ_PROPERTIES = [
    "intf",
  ]
  EQ_PROPERTIES = [
    "intf",
  ]
  STR_PROPERTIES = [
    "intf",
  ]
  INITIAL_ONLINE = False
  INITIAL_TRANSFER = lambda self: {"recv": 0, "send": 0}
  INITIAL_ENDPOINT = lambda self: {"address": None, "port": None}
  INITIAL_ALLOWED_IPS = lambda self: set()

  DB_TABLE = "peers_vpn_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"
  DB_TABLE_PROPERTIES = PROPERTIES


  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.log.local_level = self.log.Level.quiet


  def serialize_allowed_ips(self, val: set[ipaddress.IPv4Network], public: bool=False) -> list[str]:
    return list(map(str, sorted(val)))

  def prepare_allowed_ips(self, val: str | list[str | ipaddress.IPv4Network]) -> set[ipaddress.IPv4Network]:
    if isinstance(val, str):
      val = self.yaml_load(val)
    # print("---- PREPARE ALLOWED IPS", repr(val))
    return prepare_collection(self.db, val, ipaddress.IPv4Network, set)

  def prepare_transfer(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val

  def prepare_endpoint(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val

  def serialize_endpoint(self, val: dict, public: bool=False) -> dict:
    val = dict(val)
    val["address"] = str(val["address"])
    return val

  # def prepare_intf(self, val: str | WireGuardInterface) -> WireGuardInterface | None:
  #   if isinstance(val, str):
  #     val = next((i for i in self.owner.parent.agent.vpn_interfaces if i.config.intf.name == val), None)
  #     if val is None:
  #       self.log.warning("VPN interface no longer available")
  #   return val

  # def serialize_intf(self, val: WireGuardInterface | None, public: bool=False) -> str | None:
  #   if val is None:
  #     return None
  #   return val.config.intf.name

  def prepare_last_handshake(self, val: str | Timestamp) -> Timestamp:
    return prepare_timestamp(self.db, val)


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

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.log.local_level = self.log.Level.quiet


  @property
  def local(self) -> bool:
    return self.lan in self.owner.routed_networks


  def prepare_lan(self, val: str | dict | LanDescriptor) -> LanDescriptor:
    return self.new_child(LanDescriptor, val)


