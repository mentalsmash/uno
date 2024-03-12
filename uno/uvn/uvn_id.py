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
from pathlib import Path
from typing import Optional, Mapping, Iterable, Union, Tuple, Callable
import ipaddress
from enum import Enum
import pprint
import yaml

from .ip import ipv4_netmask_to_cidr
from .time import Timestamp
from .deployment import DeploymentStrategyKind, P2PLinksMap
from .log import Logger as log

class ClashingNetworksError(Exception):
  def __init__(self, clashes: Mapping[ipaddress.IPv4Network, set[Tuple[object, ipaddress.IPv4Network]]], *args: object) -> None:
    clash_str = repr({
      str(n): [
        (str(o), str(n))
        for o, n in matches
      ]
        for n, matches in clashes.items()
    })
    super().__init__(f"clashing networks detected: {clash_str}", *args)


def load_inline_yaml(val: str) -> dict:
  # Try to interpret the string as a Path
  args_file = Path(val)
  if args_file.is_file():
    return yaml.safe_load(args_file.read_text())
  # Interpret the string as inline YAML
  return yaml.safe_load(val)


def parse_owner_id(input: str | None) -> Tuple[str, str]:
  if input is None:
    return (None, None)

  owner_start = input.find("<")
  if owner_start < 0:
    # Interpret the string as just the owner (i.e. e-mail)
    owner = input
    owner_start = len(owner)
  else:
    owner_end = input.find(">")
    if owner_end < 0:
      raise ValueError("malformed owner id, expected: 'NAME <EMAIL>'", input)
    owner = input[owner_start+1:owner_end].strip()

  if not owner:
    raise ValueError("empty owner id", input)

  owner_name = input[:owner_start].strip()
  return (
    owner,
    owner_name if owner_name else None
  )

def strip_serialized_secrets(serialized: dict) -> dict:
  return strip_serialized_fields(serialized, {
    "privkey": "<omitted>",
    "psk": "<omitted>",
    "psks": "<omitted>",
  })


def strip_serialized_fields(serialized: dict, replacements: dict) -> dict:
  # Remove all secrets
  def _strip(tgt: dict) -> dict:
    updated = {}
    for k, v in tgt.items():
      if k in replacements:
        v = replacements[k]
      elif isinstance(v, dict):
        v = _strip(v)
      elif isinstance(v, list) and v and isinstance(v[0], dict):
        v = [_strip(e) for e in v]
      if v is not False and not v:
        continue
      updated[k] = v
    return updated
  return _strip(serialized)

def print_serialized(obj: object, verbose: bool=False) -> None:
  serialized = strip_serialized_secrets(obj.serialize())
  if not verbose:
    serialized = strip_serialized_fields(serialized, {
      "generation_ts": None,
      "init_ts": None,
    })
  print(yaml.safe_dump(serialized))


class TimingProfile(Enum):
  DEFAULT = 0
  FAST = 1


  @staticmethod
  def parse(val: str) -> "TimingProfile":
    return TimingProfile[val.upper().replace("-", "_")]


  @property
  def participant_liveliness_lease_duration(self) -> int:
    if self == TimingProfile.FAST:
      return 5
    else:
      return 60


  @property
  def participant_liveliness_assert_period(self) -> int:
    if self == TimingProfile.FAST:
      return 2
    else:
      return 20


  @property
  def participant_liveliness_detection_period(self) -> int:
    if self == TimingProfile.FAST:
      return 6
    else:
      return 30


  @property
  def initial_participant_announcements(self) -> int:
    if self == TimingProfile.FAST:
      return 60
    else:
      return 60


  @property
  def initial_participant_announcement_period(self) -> Tuple[int, int]:
    if self == TimingProfile.FAST:
      return (1, 5)
    else:
      return (3, 15)


  @property
  def ospf_dead_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 5
    else:
      return 60


  @property
  def ospf_hello_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 1
    else:
      return 15


  @property
  def ospf_retransmit_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 2
    else:
      return 5


  @property
  def tester_max_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 30
    else:
      return 3600 # 1h


  @property
  def status_min_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 10
    else:
      return 30


class Versioned:
  def __init__(self,
      generation_ts: str | None = None,
      init_ts: str | None = None,
      deserializing: bool=False) -> None:
    self._generation_ts = generation_ts or Timestamp.now().format()
    self._init_ts = init_ts or Timestamp.now().format()
    self._changed = False
    self._loaded = False


  def __str__(self) -> str:
    return f"{self.__class__.__name__}({self.generation_ts}{'*' if self.peek_changed else ''})"


  @property
  def peek_changed(self) -> bool:
    return self._changed


  @property
  def changed(self) -> Tuple[bool, dict]:
    """Return and reset the object's 'changed' flag."""
    changed = self._changed
    self._changed = False
    prev_values = {}
    for attr in {a[8:] for a in dir(self) if a.startswith("__prev__")}:
      prev_values[attr] = getattr(self, f"__prev__{attr}")
      delattr(self, f"__prev__{attr}")
    return changed, prev_values


  @property
  def generation_ts(self) -> str:
    return self._generation_ts


  @property
  def init_ts(self) -> str:
    return self._init_ts


  def update(self, attr: str, val: object) -> None:
    _attr = f"_{attr}"
    if not hasattr(self, _attr):
      setattr(self, _attr, None)
    current = getattr(self, _attr)
    if current != val:
      setattr(self, _attr, val)
      setattr(self, f"__prev__{attr}", current)
      if self.loaded:
        log.debug(f"[{self}] {attr} = {val}")
      self.updated()


  def updated(self) -> None:
    if not self.loaded:
      return
    self._generation_ts = Timestamp.now().format()
    self._changed = True
    # log.debug(f"[{self}] updated")


  @property
  def loaded(self) -> bool:
    return self._loaded
  

  @loaded.setter
  def loaded(self, val: bool) -> None:
    self._loaded = val
    log.debug(f"[{self}] loaded ({self.generation_ts})")

  def serialize(self) -> dict:
    return {
      "generation_ts": self.generation_ts,
      "init_ts": self.init_ts,
    }

  @staticmethod
  def deserialize_args(serialized: dict) -> dict:
    return {
      "generation_ts": serialized["generation_ts"],
      "init_ts": serialized["init_ts"],
      "deserializing": True,
    }


  def collect_changes(self) -> list[Tuple["Versioned", dict]]:
    changed, prev_values = self.changed
    if changed:
      return [(self, prev_values)]
    else:
      return []


class VpnSettings(Versioned):
  DEFAULT_PORT = 1
  DEFAULT_PEER_PORT = None
  DEFAULT_SUBNET = "0.0.0.0/32"
  DEFAULT_INTERFACE = "vpn{}"
  DEFAULT_ALLOWED_IPS = []
  DEFAULT_PEER_MTU = None
  DEFAULT_MASQUERADE = False
  DEFAULT_FORWARD = False
  DEFAULT_TUNNEL = False


  def __init__(self,
      port: Optional[int]=None,
      peer_port: Optional[int]=None,
      subnet: Optional[Union[str, ipaddress.IPv4Network]]=None,
      interface: Optional[str]=None,
      allowed_ips: Optional[Iterable[str]]=None,
      peer_mtu: Optional[int]=None,
      masquerade: Optional[bool]=None,
      tunnel: Optional[bool]=None,
      forward: Optional[bool]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    self.port = port
    self.peer_port = peer_port
    self.subnet = None if subnet is None else ipaddress.ip_network(subnet)
    self.interface = interface
    self.allowed_ips = allowed_ips
    self.peer_mtu = peer_mtu
    self.masquerade = masquerade
    self.tunnel = tunnel
    self.forward = forward


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, VpnSettings):
      return False
    return (
      self.allowed_ips == other.allowed_ips
      and self.interface == other.interface
      and self.port == other.port
      and self.peer_port == other.peer_port
      and self.peer_mtu == other.peer_mtu
      and self.masquerade == other.masquerade
      and self.forward == other.forward
      and self.tunnel == other.tunnel
    )


  def __hash__(self) -> int:
    return hash(self.allowed_ips, self.interface, self.port, self.peer_port, self.peer_mtu, self.masquerade, self.forward, self.tunnel)


  @property
  def allowed_ips(self) -> set[str]:
    if self._allowed_ips is None:
      return self.DEFAULT_ALLOWED_IPS
    return self._allowed_ips


  @allowed_ips.setter
  def allowed_ips(self, val: Iterable[str] | None) -> None:
    val = set(val) if val is not None else None
    self.update("allowed_ips", val)


  @property
  def interface(self) -> str:
    if self._interface is None:
      return self.DEFAULT_INTERFACE
    return self._interface


  @interface.setter
  def interface(self, val: str | None) -> None:
    self.update("interface", val)


  @property
  def port(self) -> int:
    if self._port is None:
      return self.DEFAULT_PORT
    return self._port


  @port.setter
  def port(self, val: int) -> None:
    self.update("port", val)


  @property
  def peer_port(self) -> int:
    if self._peer_port is None:
      if self.DEFAULT_PEER_PORT is None:
        return self.port
      return self.DEFAULT_PEER_PORT
    return self._peer_port


  @peer_port.setter
  def peer_port(self, val: int | None) -> None:
    self.update("peer_port", val)


  @property
  def peer_mtu(self) -> Optional[int]:
    if self._peer_mtu is None:
      return self.DEFAULT_PEER_MTU
    return self._peer_mtu


  @peer_mtu.setter
  def peer_mtu(self, val: int | None) -> None:
    self.update("peer_mtu", val)


  @property
  def subnet(self) -> ipaddress.IPv4Network:
    if self._subnet is None:
      return ipaddress.ip_network(self.DEFAULT_SUBNET)
    return self._subnet


  @subnet.setter
  def subnet(self, val: ipaddress.IPv4Network | None) -> None:
    self.update("subnet", val)


  @property
  def masquerade(self) -> bool:
    if self._masquerade is None:
      return self.DEFAULT_MASQUERADE
    return self._masquerade


  @masquerade.setter
  def masquerade(self, val: bool|None) -> None:
    self.update("masquerade", val)


  @property
  def forward(self) -> bool:
    if self._forward is None:
      return self.DEFAULT_FORWARD
    return self._forward


  @forward.setter
  def forward(self, val: bool|None) -> None:
    self.update("forward", val)


  @property
  def tunnel(self) -> bool:
    if self._tunnel is None:
      return self.DEFAULT_TUNNEL
    return self._tunnel


  @tunnel.setter
  def tunnel(self, val: bool|None) -> None:
    self.update("tunnel", val)


  @property
  def base_ip(self) -> ipaddress.IPv4Address:
    return self.subnet.network_address


  @property
  def netmask(self) -> int:
    return ipv4_netmask_to_cidr(self.subnet.netmask)


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "port": self.port,
      "peer_port": self.peer_port,
      "subnet": str(self.subnet),
      "interface": self.interface,
      "allowed_ips": sorted(self.allowed_ips),
      "peer_mtu": self.peer_mtu,
      "masquerade": self.masquerade,
      "forward": self.forward,
      "tunnel": self.tunnel,
    })
    if self._allowed_ips is None:
      del serialized["allowed_ips"]
    if self._port is None:
      del serialized["port"]
    if self._peer_port is None:
      del serialized["peer_port"]
    if self._subnet is None:
      del serialized["subnet"]
    if self._interface is None:
      del serialized["interface"]
    if self._peer_mtu is None:
      del serialized["peer_mtu"]
    if self._masquerade is None:
      del serialized["masquerade"]
    if self._forward is None:
      del serialized["forward"]
    if self._tunnel is None:
      del serialized["tunnel"]
    return serialized


  @staticmethod
  def deserialize_args(serialized: dict) -> dict:
    return {
      "port": serialized.get("port"),
      "peer_port": serialized.get("peer_port"),
      "subnet": serialized.get("subnet"),
      "interface": serialized.get("interface"),
      "allowed_ips": serialized.get("allowed_ips"),
      "peer_mtu": serialized.get("peer_mtu"),
      "masquerade": serialized.get("masquerade"),
      "forward": serialized.get("forward"),
      "tunnel": serialized.get("tunnel"),
      **Versioned.deserialize_args(serialized)
    }


class RootVpnSettings(VpnSettings):
  DEFAULT_PORT = 63447
  DEFAULT_PEER_PORT = 63448
  DEFAULT_SUBNET = "10.255.128.0/22"
  DEFAULT_INTERFACE = "uwg-v{}"
  DEFAULT_PEER_MTU = 1320

  @staticmethod
  def deserialize(serialized: dict) -> "RootVpnSettings":
    self = RootVpnSettings(**VpnSettings.deserialize_args(serialized))
    self.loaded = True
    return self


class ParticlesVpnSettings(VpnSettings):
  DEFAULT_PORT = 63449
  DEFAULT_SUBNET = "10.254.0.0/16"
  DEFAULT_INTERFACE = "uwg-p{}"
  DEFAULT_ALLOWED_IPS = [
    # "0.0.0.0/0",
  ]
  DEFAULT_PEER_MTU = 1320
  DEFAULT_MASQUERADE = True
  DEFAULT_FORWARD = True
  DEFAULT_TUNNEL = True

  @staticmethod
  def deserialize(serialized: dict) -> "ParticlesVpnSettings":
    self = ParticlesVpnSettings(**VpnSettings.deserialize_args(serialized))
    self.loaded = True
    return self


class BackboneVpnSettings(VpnSettings):
  DEFAULT_PORT = 63450
  DEFAULT_SUBNET = "10.255.192.0/20"
  DEFAULT_INTERFACE = "uwg-b{}"
  DEFAULT_ALLOWED_IPS = [
    "224.0.0.5/32",
    "224.0.0.6/32",
  ]
  DEFAULT_LINK_NETMASK = 31
  DEFAULT_DEPLOYMENT_STRATEGY = DeploymentStrategyKind.CROSSED
  DEFAULT_PEER_MTU = 1320
  DEFAULT_FORWARD = True

  def __init__(self,
      deployment_strategy: DeploymentStrategyKind | None=None,
      deployment_strategy_args: dict | None=None,
      **super_args) -> None:
    super().__init__(**super_args)
    self.deployment_strategy = deployment_strategy
    self.deployment_strategy_args = deployment_strategy_args
  

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, BackboneVpnSettings):
      return False
    if not super().__eq__(other):
      return False
    return (
      self.deployment_strategy == other.deployment
      and 
      # Quite inefficient and brittle way to compare two
      # dictionaries, but good enough for now
      (pprint.pformat(self.deployment_strategy_args) ==
        pprint.pformat(other.deployment_strategy_args))
    )

  def __hash__(self) -> int:
    return hash((super().__hash__(), self.deployment_strategy, pprint.pformat(self.deployment_strategy_args)))



  @property
  def deployment_strategy(self) -> DeploymentStrategyKind:
    if self._deployment_strategy is None:
      return self.DEFAULT_DEPLOYMENT_STRATEGY
    return self._deployment_strategy


  @deployment_strategy.setter
  def deployment_strategy(self, val: DeploymentStrategyKind | None) -> None:
    self.update("deployment_strategy", val)


  @property
  def deployment_strategy_args(self) -> dict:
    return self._deployment_strategy_args


  @deployment_strategy_args.setter
  def deployment_strategy_args(self, val: dict | None) -> None:
    val = dict(val or {})
    self.update("deployment_strategy_args", val)


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "deployment_strategy": self.deployment_strategy.name,
      "deployment_strategy_args": self.deployment_strategy_args,
    })
    if self._deployment_strategy is None:
      del serialized["deployment_strategy"]
    if not self.deployment_strategy_args:
      del serialized["deployment_strategy_args"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "BackboneVpnSettings":
    deployment_strategy = serialized.get("deployment_strategy")
    if deployment_strategy is not None:
      deployment_strategy = DeploymentStrategyKind[deployment_strategy.upper()]
    self = BackboneVpnSettings(
      deployment_strategy=deployment_strategy,
      deployment_strategy_args=serialized.get("deployment_strategy_args"),
      **VpnSettings.deserialize_args(serialized))
    self.loaded = True
    return self


class UvnSettings(Versioned):
  # DEFAULT_TIMING_PROFILE = TimingProfile.FAST
  DEFAULT_TIMING_PROFILE = TimingProfile.DEFAULT
  DEFAULT_ENABLE_PARTICLES_VPN = True
  DEFAULT_ENABLE_ROOT_VPN = True
  DEFAULT_ENABLE_DDS_SECURITY = False
  DEFAULT_DDS_DOMAIN = 46

  def __init__(self,
      root_vpn: Optional[RootVpnSettings]=None,
      particles_vpn: Optional[ParticlesVpnSettings]=None,
      backbone_vpn: Optional[BackboneVpnSettings]=None,
      timing_profile: Optional[TimingProfile]=None,
      enable_particles_vpn: Optional[bool]=None,
      enable_root_vpn: Optional[bool]=None,
      dds_domain: Optional[int]=None,
      enable_dds_security: Optional[bool]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    self.root_vpn = root_vpn or RootVpnSettings()
    self.particles_vpn = particles_vpn or ParticlesVpnSettings()
    self.backbone_vpn = backbone_vpn or BackboneVpnSettings()
    self.timing_profile = timing_profile
    self.enable_particles_vpn = enable_particles_vpn
    self.enable_root_vpn = enable_root_vpn
    self.dds_domain = dds_domain
    self.enable_dds_security = enable_dds_security


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, UvnSettings):
      return False
    return (
      self.timing_profile == other.timing_profile
      and self.enable_particles_vpn == other.enable_particles_vpn
      and self.enable_root_vpn == other.enable_root_vpn
      and self.root_vpn == other.root_vpn
      and self.particles_vpn == other.particles_vpn
      and self.backbone_vpn == other.backbone_vpn
    )


  def __hash__(self) -> int:
    return hash((
      self.timing_profile,
      self.enable_particles_vpn,
      self.enable_root_vpn,
      self.root_vpn,
      self.particles_vpn,
      self.backbone_vpn))


  @property
  def root_vpn(self) -> RootVpnSettings:
    return self._root_vpn


  @root_vpn.setter
  def root_vpn(self, val: RootVpnSettings) -> None:
    self.update("root_vpn", val)


  @property
  def particles_vpn(self) -> ParticlesVpnSettings:
    return self._particles_vpn


  @particles_vpn.setter
  def particles_vpn(self, val: ParticlesVpnSettings) -> None:
    self.update("particles_vpn", val)


  @property
  def backbone_vpn(self) -> BackboneVpnSettings:
    return self._backbone_vpn


  @backbone_vpn.setter
  def backbone_vpn(self, val: BackboneVpnSettings) -> None:
    self.update("backbone_vpn", val)


  @property
  def timing_profile(self) -> TimingProfile:
    if self._timing_profile is None:
      return self.DEFAULT_TIMING_PROFILE
    return self._timing_profile


  @timing_profile.setter
  def timing_profile(self, val: TimingProfile | None) -> None:
    self.update("timing_profile", val)


  @property
  def enable_particles_vpn(self) -> bool:
    if self._enable_particles_vpn is None:
      return self.DEFAULT_ENABLE_PARTICLES_VPN
    return self._enable_particles_vpn


  @enable_particles_vpn.setter
  def enable_particles_vpn(self, val: bool | None) -> None:
    self.update("enable_particles_vpn", val)


  @property
  def enable_root_vpn(self) -> bool:
    if self._enable_root_vpn is None:
      return self.DEFAULT_ENABLE_ROOT_VPN
    return self._enable_root_vpn


  @enable_root_vpn.setter
  def enable_root_vpn(self, val: bool | None) -> None:
    self.update("enable_root_vpn", val)


  @property
  def dds_domain(self) -> int:
    if self._dds_domain is None:
      return self.DEFAULT_DDS_DOMAIN
    return self._dds_domain


  @dds_domain.setter
  def dds_domain(self, val: int | None) -> None:
    self.update("dds_domain", val)


  @property
  def enable_dds_security(self) -> int:
    if self._enable_dds_security is None:
      return self.DEFAULT_ENABLE_DDS_SECURITY
    return self._enable_dds_security


  @enable_dds_security.setter
  def enable_dds_security(self, val: int | None) -> None:
    self.update("enable_dds_security", val)


  def collect_changes(self) -> list[Tuple[Versioned, dict]]:
    changed = super().collect_changes()
    changed.extend(self.root_vpn.collect_changes())
    changed.extend(self.particles_vpn.collect_changes())
    changed.extend(self.backbone_vpn.collect_changes())
    return changed


  @property
  def peek_changed(self) -> bool:
    return (
      super().peek_changed
      or self.root_vpn.peek_changed
      or self.particles_vpn.peek_changed
      or self.backbone_vpn.peek_changed
    )


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "root_vpn": self.root_vpn.serialize(),
      "particles_vpn": self.particles_vpn.serialize(),
      "backbone_vpn": self.backbone_vpn.serialize(),
      "timing_profile": self.timing_profile.name,
      "enable_particles_vpn": self.enable_particles_vpn,
      "enable_root_vpn": self.enable_root_vpn,
      "dds_domain": self.dds_domain,
      "enable_dds_security": self.enable_dds_security,
    })
    if not serialized["root_vpn"]:
      del serialized["root_vpn"]
    if not serialized["particles_vpn"]:
      del serialized["particles_vpn"]
    if not serialized["backbone_vpn"]:
      del serialized["backbone_vpn"]
    if self._timing_profile is None:
      del serialized["timing_profile"]
    if self._enable_particles_vpn is None:
      del serialized["enable_particles_vpn"]
    if self._enable_root_vpn is None:
      del serialized["enable_root_vpn"]
    if self._dds_domain is None:
      del serialized["dds_domain"]
    if self._enable_dds_security is None:
      del serialized["enable_dds_security"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "UvnSettings":
    timing_profile = serialized.get("timing_profile")
    self = UvnSettings(
      root_vpn=RootVpnSettings.deserialize(serialized.get("root_vpn", {})),
      particles_vpn=ParticlesVpnSettings.deserialize(serialized.get("particles_vpn", {})),
      backbone_vpn=BackboneVpnSettings.deserialize(serialized.get("backbone_vpn", {})),
      timing_profile=TimingProfile[timing_profile] if timing_profile else None,
      enable_particles_vpn=serialized.get("enable_particles_vpn"),
      enable_root_vpn=serialized.get("enable_root_vpn"),
      enable_dds_security=serialized.get("enable_dds_security"),
      dds_domain=serialized.get("dds_domain"),
      **Versioned.deserialize_args(serialized))
    self.loaded = True
    return self


class CellId(Versioned):
  DEFAULT_ALLOW_PARTICLES = False
  DEFAULT_ALLOWED_LANS = []
  DEFAULT_IGNORED_LANS = []
  DEFAULT_LOCATION = "Earth"
  DEFAULT_ROAMING = False
  DEFAULT_ENABLE_PARTICLES_VPN = True
  DEFAULT_HTTPD_PORT = 443

  def __init__(self,
      id: int,
      name: str,
      owner_id: Optional[str]=None,
      owner: Optional[str]=None,
      owner_name: Optional[str]=None,
      address: Optional[str]=None,
      location: Optional[str] = None,
      allowed_lans: Optional[Iterable[ipaddress.IPv4Network]]=None,
      enable_particles_vpn: Optional[bool]=None,
      httpd_port: Optional[int]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    if owner_id:
      owner, owner_name = parse_owner_id(owner_id)
    self._id = id
    self.name = name
    self.owner = owner
    self.owner_name = owner_name
    self.address = address    
    self.location = location
    self.allowed_lans = allowed_lans
    self.enable_particles_vpn = enable_particles_vpn
    self.httpd_port = httpd_port


  def __str__(self) -> str:
    return self.name


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, CellId):
      return False
    return self.id == other.id


  def __hash__(self) -> int:
    return hash(self.id)


  def configure(self,
      owner_id: Optional[str]=None,
      address: Optional[str]=None,
      location: Optional[str] = None,
      allowed_lans: Optional[Iterable[ipaddress.IPv4Network]]=None,
      enable_particles_vpn: Optional[bool]=None,
      httpd_port: Optional[int]=None) -> None:
    owner, owner_name = parse_owner_id(owner_id)
    if owner is not None:
      self.owner = owner
      self.owner_name = owner_name
    if address is not None:
      self.address = address
    if location is not None:
      self.location = location
    if allowed_lans is not None:
      self.allowed_lans = allowed_lans
    if enable_particles_vpn is not None:
      self.enable_particles_vpn = enable_particles_vpn
    if httpd_port is not None:
      self.httpd_port = httpd_port


  @property
  def id(self) -> int:
    return self._id


  @property
  def name(self) -> str:
    return self._name


  @name.setter
  def name(self, val: str) -> None:
    UvnId.validate_name(val, "cell")
    self.update("name", val)


  @property
  def owner(self) -> str:
    return self._owner


  @owner.setter
  def owner(self, val: str) -> None:
    UvnId.validate_name(val, "cell owner")
    self.update("owner", val)


  @property
  def address(self) -> Optional[str]:
    return self._address


  @address.setter
  def address(self, val: str | None) -> None:
    self.update("address", val)


  @property
  def owner_name(self) -> str:
    if self._owner_name is None:
      return self.owner
    return self._owner_name


  @owner_name.setter
  def owner_name(self, val: str | None) -> str:
    UvnId.validate_name(val, "cell owner name")
    self.update("owner_name", val)


  @property
  def owner_id(self) -> str:
    if self._owner_name is None:
      return self.owner
    return f"{self.owner_name} <{self.owner}>"


  @property
  def location(self) -> str:
    if self._location is None:
      return self.DEFAULT_LOCATION
    return self._location
  

  @location.setter
  def location(self, val: str | None) -> None:
    self.update("location", val)


  @property
  def allowed_lans(self) -> set[ipaddress.IPv4Network]:
    if self._allowed_lans is None:
      return self.DEFAULT_ALLOWED_LANS
    return self._allowed_lans


  @allowed_lans.setter
  def allowed_lans(self, val: Iterable[ipaddress.IPv4Network] | None) -> None:
    val = set(val) if val is not None else None
    self.update("allowed_lans", val)


  @property
  def enable_particles_vpn(self) -> bool:
    if self.address is None:
      return False
    if self._enable_particles_vpn is None:
      return self.DEFAULT_ENABLE_PARTICLES_VPN
    return self._enable_particles_vpn


  @enable_particles_vpn.setter
  def enable_particles_vpn(self, val: bool | None) -> None:
    self.update("enable_particles_vpn", val)


  @property
  def httpd_port(self) -> int:
    if self._httpd_port is None:
      return self.DEFAULT_HTTPD_PORT
    return self._httpd_port


  @httpd_port.setter
  def httpd_port(self, val: int) -> None:
    self.update("httpd_port", val)


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "id": self.id,
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
      "address": self.address,
      "location": self.location,
      "allowed_lans": [str(l) for l in self.allowed_lans],
      "enable_particles_vpn": self.enable_particles_vpn,
      "httpd_port": self.httpd_port,
    })
    if self._address is None:
      del serialized["address"]
    if self._owner_name is None:
      del serialized["owner_name"]
    if self._location is None:
      del serialized["location"]
    if self._allowed_lans is None:
      del serialized["allowed_lans"]
    if self._enable_particles_vpn is None:
      del serialized["enable_particles_vpn"]
    if self._httpd_port is None:
      del serialized["httpd_port"]
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict) -> "CellId":
    allowed_lans = serialized.get("allowed_lans")
    self = CellId(
      id=serialized["id"],
      name=serialized["name"],
      owner=serialized["owner"],
      owner_name=serialized.get("owner_name"),
      address=serialized.get("address"),
      location=serialized.get("location"),
      allowed_lans=[
        ipaddress.ip_network(l)
        for l in allowed_lans
      ] if allowed_lans else None,
      enable_particles_vpn=serialized.get("enable_particles_vpn"),
      httpd_port=serialized.get("httpd_port"),
      **Versioned.deserialize_args(serialized))
    self.loaded = True
    return self


class ParticleId(Versioned):
  def __init__(self,
      id: int,
      name: str,
      owner_id: Optional[str]=None,
      owner: Optional[str]=None,
      owner_name: Optional[str] = None,
      **super_args) -> None:
    super().__init__(**super_args)
    if owner_id:
      owner, owner_name = parse_owner_id(owner_id)
    self._id = id
    self.name = name
    self.owner = owner
    self.owner_name = owner_name


  def __str__(self) -> str:
    return self.name


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, ParticleId):
      return False
    return self.id == other.id


  def __hash__(self) -> int:
    return hash(self.id)


  def configure(self,
      owner_id: Optional[str]=None) -> None:
    owner, owner_name = parse_owner_id(owner_id)
    if owner is not None:
      self.owner = owner
      self.owner_name = owner_name


  @property
  def id(self) -> int:
    return self._id


  @property
  def name(self) -> str:
    return self._name


  @name.setter
  def name(self, val: str) -> None:
    UvnId.validate_name(val, "particle")
    self.update("name", val)


  @property
  def owner(self) -> str:
    return self._owner


  @owner.setter
  def owner(self, val: str) -> None:
    UvnId.validate_name(val, "particle owner")
    self.update("owner", val)


  @property
  def owner_name(self) -> str:
    if self._owner_name is None:
      return self.owner
    return self._owner_name


  @owner_name.setter
  def owner_name(self, val: str | None) -> str:
    UvnId.validate_name(val, "particle owner name")
    self.update("owner_name", val)


  @property
  def owner_id(self) -> str:
    if self._owner_name is None:
      return self.owner
    return f"{self.owner_name} <{self.owner}>"


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "id": self.id,
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
    })
    if self._owner_name is None:
      del serialized["owner_name"]
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict) -> "ParticleId":
    self = ParticleId(
      id=serialized["id"],
      name=serialized.get("name"),
      owner=serialized.get("owner"),
      owner_name=serialized.get("owner_name"),
      **Versioned.deserialize_args(serialized))
    self.loaded = True
    return self


class UvnId(Versioned):
  RESERVED_KEYWORDS = [
    "root",
  ]

  @staticmethod
  def validate_name(val: str, which: str="uvn") -> None:
    # if val is None:
    #   return
    if not val:
      raise RuntimeError(f"no {which} name specified")
    val = val.lower()
    if val in UvnId.RESERVED_KEYWORDS:
      raise RuntimeError(f"'{val}' is a reserved keyword")


  @staticmethod
  def detect_network_clashes(
      records: Iterable[object],
      get_networks: Callable[[object],Iterable[ipaddress.IPv4Network]],
      checked_networks: Optional[Iterable[ipaddress.IPv4Network]]=None
      ) -> Mapping[ipaddress.IPv4Network, set[Tuple[object, ipaddress.IPv4Network]]]:
    checked_networks = set(checked_networks or [])
    by_subnet = {
      n: set()
        for n in checked_networks
    }
    explored = set()
    # subnets = set(checked_networks)
    for record in records:
      for net in get_networks(record):
        subnet_cells = by_subnet[net] = by_subnet.get(net, set())
        subnet_cells.add((record, net))
        for subnet in checked_networks or explored:
          if subnet.overlaps(net) or net.overlaps(subnet):
            by_subnet[subnet].add((record, net))
        explored.add(net)
    return {
      n: matches
      for n, matches in by_subnet.items()
        if (not checked_networks or n in checked_networks)
          and len(matches) > 0
    }


  def __init__(self,
      name: str,
      master_secret: Optional[str]=None,
      owner_id: Optional[str]=None,
      owner: Optional[str]=None,
      owner_name: Optional[str] = None,
      address: Optional[str] = None,
      cells: Optional[Mapping[int, CellId]] = None,
      excluded_cells: Optional[Mapping[int, CellId]]=None,
      particles: Optional[Mapping[int, ParticleId]] = None,
      excluded_particles: Optional[Mapping[int, ParticleId]] = None,
      settings: Optional[UvnSettings]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    if owner_id:
      owner, owner_name = parse_owner_id(owner_id)
    self._name = name
    self._master_secret = master_secret
    self.owner = owner
    self.owner_name = owner_name
    self.address = address
    self.cells = dict(cells or {})
    self.excluded_cells = dict(excluded_cells or {})
    self.particles = dict(particles or {})
    self.excluded_particles = dict(excluded_particles or {})
    self.settings = settings or UvnSettings()


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, UvnId):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  def __str__(self) -> str:
    return self.name


  def configure(
      self,
      owner_id: str | None = None,
      address: str | None = None,
      timing_profile: str | None = None,
      enable_particles_vpn: bool | None = None,
      enable_root_vpn: bool | None = None,
      root_vpn_push_port: int | None = None,
      root_vpn_pull_port: int | None = None,
      root_vpn_subnet: ipaddress.IPv4Network | None = None,
      root_vpn_mtu: int | None = None,
      particles_vpn_port: int | None = None,
      particles_vpn_subnet: ipaddress.IPv4Network | None = None,
      particles_vpn_mtu: int | None = None,
      backbone_vpn_port: int | None = None,
      backbone_vpn_subnet: ipaddress.IPv4Network | None = None,
      backbone_vpn_mtu: int | None = None,
      deployment_strategy: str | None = None,
      deployment_strategy_args: str | None = None,
      master_secret: str | None = None,
      dds_domain: int | None = None,
      enable_dds_security: bool | None = None):
    owner, owner_name = parse_owner_id(owner_id)
    if owner is not None:
      self.owner = owner
      self.owner_name = owner_name
    if address is not None:
      self.address = address
    if timing_profile is not None:
      self.settings.timing_profile = TimingProfile.parse(timing_profile)
    if enable_particles_vpn is not None:
      self.settings.enable_particles_vpn = enable_particles_vpn
    if enable_root_vpn is not None:
      self.settings.enable_root_vpn = enable_root_vpn
    if root_vpn_push_port is not None:
      self.settings.root_vpn.port = root_vpn_push_port
    if root_vpn_pull_port is not None:
      self.settings.root_vpn.peer_port = root_vpn_pull_port
    if root_vpn_subnet is not None:
      self.settings.root_vpn.subnet = root_vpn_subnet
    if root_vpn_mtu is not None:
      self.settings.root_vpn.peer_mtu = root_vpn_mtu
    if particles_vpn_port is not None:
      self.settings.particles_vpn.port = particles_vpn_port
    if particles_vpn_subnet is not None:
      self.settings.particles_vpn.subnet = particles_vpn_subnet
    if particles_vpn_mtu is not None:
      self.settings.particles_vpn.peer_mtu = particles_vpn_mtu
    if backbone_vpn_port is not None:
      self.settings.backbone_vpn.port = backbone_vpn_port
    if backbone_vpn_subnet is not None:
      self.settings.backbone_vpn.subnet = backbone_vpn_subnet
    if backbone_vpn_mtu is not None:
      self.settings.backbone_vpn.peer_mtu = backbone_vpn_mtu
    if deployment_strategy is not None:
      self.settings.backbone_vpn.deployment_strategy = DeploymentStrategyKind.parse(deployment_strategy)
    if deployment_strategy_args is not None:
      self.settings.backbone_vpn.deployment_strategy_args = load_inline_yaml(deployment_strategy_args)
    if master_secret is not None:
      from .htdigest import htdigest_generate
      master_secret = htdigest_generate(user=self.owner, realm=self.name, password=master_secret).split(":")[2]
      self.master_secret = master_secret
    if dds_domain is not None:
      self.settings.dds_domain = dds_domain
    if enable_dds_security is not None:
      self.settings.enable_dds_security = enable_dds_security


  @property
  def name(self) -> str:
    return self._name


  @property
  def owner(self) -> str:
    return self._owner


  @owner.setter
  def owner(self, val: str) -> None:
    UvnId.validate_name(val, "uvn owner")
    self.update("owner", val)

  @property
  def owner_name(self) -> str:
    if self._owner_name is None:
      return self.owner
    return self._owner_name


  @owner_name.setter
  def owner_name(self, val: str | None) -> str:
    UvnId.validate_name(val, "uvn owner name")
    self.update("owner_name", val)


  @property
  def owner_id(self) -> str:
    if self._owner_name is None:
      return self.owner
    return f"{self.owner_name} <{self.owner}>"


  @property
  def address(self) -> Optional[str]:
    return self._address


  @address.setter
  def address(self, val: str | None) -> None:
    self.update("address", val)


  @property
  def master_secret(self) -> str:
    return self._master_secret


  @master_secret.setter
  def master_secret(self, val: str) -> None:
    self.update("master_secret", val)


  @property
  def all_cells(self) -> set[CellId]:
    return {*self.cells.values(), *self.excluded_cells.values()}


  @property
  def public_cells(self) -> Iterable[CellId]:
    return (c for c in self.cells.values() if c.address)


  @property
  def private_cells(self) -> Iterable[CellId]:
    return (c for c in self.all_cells if not c.address)


  @property
  def supports_reconfiguration(self) -> bool:
    return next(self.private_cells, None) is None or bool(self.address)


  @property
  def all_particles(self) -> set[CellId]:
    return {*self.particles.values(), *self.excluded_particles.values()}


  def collect_changes(self) -> list[Tuple[Versioned, dict]]:
    return [ch
      for o in (
        super(),
        self.settings,
        *self.cells.values(),
        *self.excluded_cells.values(),
        *self.particles.values(),
        *self.excluded_particles.values())
        for ch in o.collect_changes()
    ]


  @property
  def peek_changed(self) -> bool:
    for o in (
        super(),
        self.settings,
        *self.cells.values(),
        *self.excluded_cells.values(),
        *self.particles.values(),
        *self.excluded_particles.values()
      ):
      if o.peek_changed:
        return True
    return False


  def serialize(self) -> dict:
    serialized = super().serialize()
    serialized.update({
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
      "address": self.address,
      "cells": [c.serialize() for c in sorted(self.cells.values(), key=lambda v: v.id)],
      "excluded_cells": [c.serialize() for c in sorted(self.excluded_cells.values(), key=lambda v: v.id)],
      "particles": [p.serialize() for p in sorted(self.particles.values(), key=lambda v: v.id)],
      "excluded_particles": [p.serialize() for p in sorted(self.excluded_particles.values(), key=lambda v: v.id)],
      "generation_ts": self.generation_ts,
      "init_ts": self.init_ts,
      "settings": self.settings.serialize(),
      "master_secret": self.master_secret,
    })
    if self._master_secret is None:
      del serialized["master_secret"]
    if self._address is None:
      del serialized["address"]
    if self._owner_name is None:
      del serialized["owner_name"]
    if len(serialized["cells"]) == 0:
      del serialized["cells"]
    if len(serialized["excluded_cells"]) == 0:
      del serialized["excluded_cells"]
    if len(serialized["particles"]) == 0:
      del serialized["particles"]
    if len(serialized["excluded_particles"]) == 0:
      del serialized["excluded_particles"]
    if not serialized["settings"]:
      del serialized["settings"]
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict) -> "UvnId":
    cells = {
      cell.id: cell
        for c_cfg in serialized.get("cells", [])
          for cell in [CellId.deserialize(c_cfg)]
    }
    excluded_cells = {
      cell.id: cell
        for c_cfg in serialized.get("excluded_cells", [])
          for cell in [CellId.deserialize(c_cfg)]
    }
    particles = {
      particle.id: particle
        for p_cfg in serialized.get("particles", [])
          for particle in [ParticleId.deserialize(p_cfg)]
    }
    excluded_particles = {
      particle.id: particle
        for p_cfg in serialized.get("excluded_particles", [])
          for particle in [ParticleId.deserialize(p_cfg)]
    }
    self = UvnId(
      name=serialized["name"],
      owner=serialized["owner"],
      master_secret=serialized.get("master_secret"),
      owner_name=serialized.get("owner_name"),
      address=serialized.get("address"),
      cells=cells,
      excluded_cells=excluded_cells,
      particles=particles,
      excluded_particles=excluded_particles,
      settings=UvnSettings.deserialize(serialized.get("settings", {})),
      **Versioned.deserialize_args(serialized))
    self.loaded = True
    return self


  def _next_id_not_in_use(self, in_use: Iterable[int], start_id: int=1) -> int:
    in_use = sorted(in_use)
    next_id = start_id
    iu = 0
    while iu < len(in_use) and next_id >= in_use[iu]:
      if next_id == in_use[iu]:
        next_id += 1
      iu += 1
    return next_id


  def _next_cell_id(self) -> int:
    return self._next_id_not_in_use(in_use=self.cells.keys())


  def _next_particle_id(self) -> int:
    return self._next_id_not_in_use(in_use=self.particles.keys())


  def validate_cell(self, cell: CellId) -> None:
    # Check that the cell's networks don't clash with any other cell's
    if cell.allowed_lans:
      clashes = UvnId.detect_network_clashes(
        records=(c for c in self.cells.values() if c != cell),
        get_networks=lambda c: c.allowed_lans,
        checked_networks=cell.allowed_lans)  
      if clashes:
        raise ClashingNetworksError(clashes)
    # Check that no other cell has the same address
    if cell.address:
      other = next((c for c in self.cells.values() if c != cell and c.address == cell.address), None)
      if other:
        raise RuntimeError(f"cell {cell} has the same address as cell {str(other)}")



  def add_cell(self,
      name: str,
      owner_id: str | None = None,
      **cell_args) -> CellId:
    dup = next((c
      for c in (
          self,
          *self.cells.values(),
          *self.excluded_cells.values(),
          *self.particles.values(),
          *self.excluded_particles.values(),
        )
        if c.name == name), None)
    if dup is not None:
      raise KeyError("name already in use", name, dup)
    cell_id = self._next_cell_id()
    if owner_id is None:
      owner_id = self.owner_id
    cell = CellId(id=cell_id, name=name, owner_id=owner_id)
    if not self.settings.enable_particles_vpn:
      cell_args["enable_particles_vpn"] = False
    if cell_args:
      cell.configure(**cell_args)
    self.validate_cell(cell)
    self.cells[cell.id] = cell
    log.warning(f"[UVN] new cell defined: {cell}")
    self.updated()
    return cell


  def update_cell(self, name: str, **cell_args) -> CellId:
    cell = next(c for c in self.cells.values() if c.name == name)
    cell.configure(**cell_args)
    if cell.peek_changed:
      self.validate_cell(cell)
      log.warning(f"[UVN] cell updated: {cell}")
      # self.updated()
    return cell


  def ban_cell(self, name: str) -> CellId:
    cell = next(c for c in self.cells.values() if c.name == name)
    del self.cells[cell.id]
    self.excluded_cells[cell.id] = cell
    cell.updated()
    self.updated()
    log.warning(f"[UVN] cell banned from {self}: {cell}")
    return cell


  def unban_cell(self, name: str) -> CellId:
    cell = next(c for c in self.excluded_cells.values() if c.name == name)
    del self.excluded_cells[cell.id]
    self.cells[cell.id] = cell
    cell.updated()
    self.updated()
    log.warning(f"[UVN] cell readded to {self}: {cell}")
    return cell


  def delete_cell(self, name: str) -> CellId:
    cell = next(c for c in self.all_cells if c.name == name)
    if cell.id in self.excluded_cells:
      del self.excluded_cells[cell.id]
    else:
      del self.cells[cell.id]
    self.updated()
    log.warning(f"[UVN] cell deleted from {self}: {cell}")
    return cell


  def add_particle(self,
      name: str,
      owner_id: str | None = None,
      **particle_args) -> CellId:
    dup = next((c
      for c in (
          self,
          *self.cells.values(),
          *self.excluded_cells.values(),
          *self.particles.values(),
          *self.excluded_particles.values(),
        )
        if c.name == name), None)
    if dup is not None:
      raise KeyError("name already in use", name, dup)
    particle_id = self._next_particle_id()
    if owner_id is None:
      owner_id = self.owner_id
    particle = ParticleId(id=particle_id, name=name, owner_id=owner_id)
    if particle_args:
      particle.configure(**particle_args)
    self.particles[particle.id] = particle
    self.updated()
    log.warning(f"[UVN] particle added to {self}: {particle}")
    return particle


  def update_particle(self, name: str, **particle_args) -> ParticleId:
    particle = next(p for p in self.particles.values() if p.name == name)
    particle.configure(**particle_args)
    if particle.peek_changed:
      log.warning(f"[UVN] particle updated: {particle}")
      # self.updated()
    return particle


  def ban_particle(self, name: str) -> ParticleId:
    particle = next(c for c in self.particles.values() if c.name == name)
    del self.particles[particle.id]
    self.excluded_particles[particle.id] = particle
    particle.updated()
    self.updated()
    log.warning(f"[UVN] particle banned from {self}: {particle}")
    return particle


  def unban_particle(self, name: str) -> ParticleId:
    particle = next(c for c in self.excluded_particles.values() if c.name == name)
    del self.excluded_particles[particle.id]
    self.particles[particle.id] = particle
    particle.updated()
    self.updated()
    log.warning(f"[UVN] particle readded to {self}: {particle}")
    return particle


  def delete_particle(self, name: str) -> ParticleId:
    particle = next(c for c in self.all_particles if c.name == name)
    if particle.id in self.excluded_particles:
      del self.excluded_particles[particle.id]
    else:
      del self.particles[particle.id]
    self.updated()
    log.warning(f"[UVN] particle deleted from {self}: {particle}")
    return particle


  def log_deployment(self,
      deployment: P2PLinksMap,
      logger: Callable[[CellId, int, str, CellId, int, str, str], None]|None=None) -> None:
    logged = []
    def _log_deployment(
        peer_a: CellId,
        peer_a_port_i: int,
        peer_a_endpoint: str,
        peer_b: CellId,
        peer_b_port_i: int,
        peer_b_endpoint: str,
        arrow: str) -> None:
      if not logged or logged[-1] != peer_a:
        log.warning(f"[BACKBONE] {peer_a} →")
        logged.append(peer_a)
      log.warning(f"[BACKBONE]   [{peer_a_port_i}] {peer_a_endpoint} {arrow} {peer_b}[{peer_b_port_i}] {peer_b_endpoint}")

    if logger is None:
      logger = _log_deployment

    for peer_a_id, peer_a_cfg in sorted(deployment.peers.items(), key=lambda t: t[0]):
      peer_a = self.cells[peer_a_id]
      for peer_b_id, (peer_a_port_i, peer_a_addr, peer_b_addr, link_subnet) in sorted(
          peer_a_cfg["peers"].items(), key=lambda t: t[1][0]):
        peer_b = self.cells[peer_b_id]
        peer_b_port_i = deployment.peers[peer_b_id]["peers"][peer_a_id][0]
        if not peer_a.address:
          peer_a_endpoint = "private LAN"
        else:
          peer_a_endpoint = f"{peer_a.address}:{self.settings.backbone_vpn.port + peer_a_port_i}"
        if not peer_b.address:
          peer_b_endpoint = "private LAN"
          arrow = "←  "
        else:
          peer_b_endpoint = f"{peer_b.address}:{self.settings.backbone_vpn.port + peer_b_port_i}"
          if peer_a.address:
            arrow = "← →"
          else:
            arrow = "  →"
        logger(peer_a, peer_a_port_i, peer_a_endpoint, peer_b, peer_b_port_i, peer_b_endpoint, arrow)