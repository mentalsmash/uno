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
import ipaddress

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.versioned import Versioned, prepare_timestamp, prepare_enum, prepare_collection
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
    "instance",
    "writer",
    "ts_start",
    "vpn_interfaces",
    "known_networks",
  ]
  VOLATILE_PROPERTIES = [
    "instance",
    "writer",
  ]
  EQ_PROPERTIES = [
    "owner",
  ]
  STR_PROPERTIES = [
    "owner",
  ]
  INITIAL_STATUS = UvnPeerStatus.DECLARED
  INITIAL_ROUTED_NETWORKS = lambda self: set()
  INITIAL_VPN_INTERFACES = lambda self: set()
  INITIAL_KNOWN_NETWORKS = lambda self: set()

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
  DB_EXPORTABLE = False
  DB_IMPORTABLE = False

  # def __init__(self, **properties) -> None:
  #   super().__init__(**properties)

  def load_nested(self) -> None:
    self.vpn_interfaces = set(self.load_children(VpnInterfaceStatus, owner=self))
    # for status in self.vpn_interfaces:
    #   status.configure(online=False)
    self.known_networks = set(self.load_children(LanStatus, owner=self))

  @property
  def name(self) -> str:
    return self.owner.name

  def prepare_routed_networks(
    self, val: str | Iterable[dict | LanDescriptor]
  ) -> set[LanDescriptor]:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return self.deserialize_collection(LanDescriptor, val, set, self.new_child)

  def serialize_routed_networks(self, val: set[LanDescriptor], public: bool = False) -> list[dict]:
    return [l.serialize() for l in val]

  def prepare_ts_start(self, val: int | str | Timestamp) -> None:
    return prepare_timestamp(self.db, val)

  def prepare_status(self, val: str | UvnPeerStatus) -> UvnPeerStatus:
    return prepare_enum(self.db, UvnPeerStatus, val)

  def configure_vpn_interfaces(self, peer_vpn_stats: dict[WireGuardInterface, dict]) -> bool:
    changed = False
    configured = set()
    for intf, intf_stats in peer_vpn_stats.items():
      intf_status = next((s for s in self.vpn_interfaces if s.intf == intf.config.intf.name), None)
      if intf_status is None:
        intf_status = self.new_child(
          VpnInterfaceStatus,
          {
            "intf": intf.config.intf.name,
          },
          owner=self,
          save=False,
        )
        changed = True
      changed_cfg = intf_status.configure(**intf_stats)
      changed = changed or len(changed_cfg) > 0
      configured.add(intf_status)
    if changed:
      self.updated_property("vpn_interfaces")
    previous = self.vpn_interfaces
    self.vpn_interfaces = configured
    gone = previous - self.vpn_interfaces
    changed = changed or len(gone) > 0
    for intf_status in gone:
      self.db.delete(intf_status)
    return changed

  def configure_known_networks(self, known_networks: None | dict[LanDescriptor, bool]) -> bool:
    changed = False
    configured = set()
    for lan, reachable in (known_networks or {}).items():
      known_net = next((n for n in self.known_networks if n.lan == lan), None)
      cfg = {"reachable": reachable}
      if known_net is None:
        known_net = self.new_child(LanStatus, {"lan": lan}, owner=self, save=False)
        changed = True
      changed_cfg = known_net.configure(**cfg)
      changed = changed or len(changed_cfg) > 0
      configured.add(known_net)
    if changed:
      self.updated_property("known_networks")
    previous = self.known_networks
    self.known_networks = configured
    gone = previous - self.known_networks
    changed = changed or len(gone) > 0
    for known_net in gone:
      self.db.delete(known_net)
    return changed

  @property
  def agent(self) -> "Agent":
    assert self.parent.parent is not None
    return self.parent.parent

  @property
  def local(self) -> bool:
    assert self.owner is not None
    return self.agent.owner == self.owner

  @property
  def particle(self) -> Particle | None:
    owner = self.owner
    if not isinstance(owner, Particle):
      return None
    return self.owner

  @property
  def cell(self) -> Cell | None:
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

  # def prepare_vpn_interfaces(self, vpn_stats: dict[WireGuardInterface, dict[str, object]]) -> "set[VpnInterfaceStatus]":
  #   self.configure_vpn_interfaces(vpn_stats)
  #   return self.vpn_interfaces

  # def prepare_known_networks(self, known_networks: None|list[dict]) -> "set[LanStatus]":
  #   self.configure_known_networks(known_networks)
  #   return self.known_networks

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
    "owner",
  ]
  STR_PROPERTIES = [
    "intf",
    "owner",
  ]
  INITIAL_ONLINE = False
  INITIAL_TRANSFER = lambda self: {"recv": 0, "send": 0}
  INITIAL_ENDPOINT = lambda self: {"address": None, "port": None}
  INITIAL_ALLOWED_IPS = lambda self: set()

  DB_TABLE = "peers_vpn_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_EXPORTABLE = False
  DB_IMPORTABLE = False

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.log.local_level = self.log.Level.quiet

  def serialize_allowed_ips(
    self, val: set[ipaddress.IPv4Network], public: bool = False
  ) -> list[str]:
    return list(map(str, sorted(val)))

  def prepare_allowed_ips(
    self, val: str | list[str | ipaddress.IPv4Network]
  ) -> set[ipaddress.IPv4Network]:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return prepare_collection(self.db, val, ipaddress.IPv4Network, set)

  def prepare_transfer(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val

  def prepare_endpoint(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val

  def serialize_endpoint(self, val: dict, public: bool = False) -> dict:
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
  PROPERTIES = [
    "lan",
    "reachable",
  ]
  REQ_PROPERTIES = [
    "lan",
  ]
  EQ_PROPERTIES = [
    "lan",
    "owner",
  ]
  STR_PROPERTIES = [
    "lan",
    "owner",
  ]
  INITIAL_REACHABLE = False

  DB_TABLE = "peers_lan_status"
  DB_OWNER = UvnPeer
  DB_OWNER_TABLE_COLUMN = "peer"
  DB_TABLE_PROPERTIES = [
    "lan",
    "reachable",
  ]
  DB_EXPORTABLE = False
  DB_IMPORTABLE = False

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.log.local_level = self.log.Level.quiet

  @property
  def local(self) -> bool:
    return self.lan in self.owner.routed_networks

  def prepare_lan(self, val: str | dict | LanDescriptor) -> LanDescriptor:
    return self.new_child(LanDescriptor, val)
