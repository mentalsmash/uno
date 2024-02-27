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
from functools import cached_property
from typing import Optional, Mapping, Iterable, Union, Tuple, Sequence
import ipaddress
from enum import Enum

from .ns import NameserverRecord
from .ip import ipv4_netmask_to_cidr
from .time import Timestamp
from .deployment import DeploymentStrategyKind

class TimingProfile(Enum):
  DEFAULT = 0
  FAST = 1
  # MINIMAL = 2


  @property
  def participant_liveliness_lease_duration(self) -> int:
    if self == TimingProfile.FAST:
      return 10
    # elif self == TimingProfile.MINIMAL:
    #   return 300
    else:
      return 300 # 5m


  @property
  def participant_liveliness_assert_period(self) -> int:
    if self == TimingProfile.FAST:
      return 3
    # elif self == TimingProfile.MINIMAL:
    #   return 120 # 2m
    else:
      return 120 # 2m


  @property
  def participant_liveliness_detection_period(self) -> int:
    if self == TimingProfile.FAST:
      return 6
    # elif self == TimingProfile.MINIMAL:
    #   return 200
    else:
      return 300 # 5m


  @property
  def initial_participant_announcements(self) -> int:
    if self == TimingProfile.FAST:
      return 60
    # elif self == TimingProfile.MINIMAL:
    #   return 60
    else:
      return 60


  @property
  def initial_participant_announcement_period(self) -> Tuple[int, int]:
    if self == TimingProfile.FAST:
      return (1, 5)
    # elif self == TimingProfile.MINIMAL:
    #   return (1, 5)
    else:
      return (5, 15)


  @property
  def ospf_dead_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 5
    # elif self == TimingProfile.MINIMAL:
    #   return 300
    else:
      return 240 # 4m


  @property
  def ospf_hello_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 1
    # elif self == TimingProfile.MINIMAL:
    #   return 100
    else:
      return 60 # 1m


  @property
  def ospf_retransmit_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 2
    # elif self == TimingProfile.MINIMAL:
    #   return 200
    else:
      # return 90 # 1m 30s
      return 2


  @property
  def tester_max_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 30
    # elif self == TimingProfile.MINIMAL:
    #   return 600
    else:
      return 120 # 2m


  @property
  def status_min_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 10
    # elif self == TimingProfile.MINIMAL:
    #   return 60
    else:
      return 30


class VpnSettings:
  DEFAULT_PORT = 1
  DEFAULT_PEER_PORT = None
  DEFAULT_SUBNET = "0.0.0.0/32"
  DEFAULT_INTERFACE = "vpn{}"
  DEFAULT_ALLOWED_IPS = []
  DEFAULT_PEER_MTU = None


  def __init__(self,
      port: Optional[int]=None,
      peer_port: Optional[int]=None,
      subnet: Optional[Union[str, ipaddress.IPv4Network]]=None,
      interface: Optional[str]=None,
      allowed_ips: Optional[Iterable[str]]=None,
      peer_mtu: Optional[int]=None) -> None:
    self._port = port
    self._peer_port = peer_port
    self._subnet = None if subnet is None else ipaddress.ip_network(subnet)
    self._interface = interface
    self._allowed_ips = list(allowed_ips) if allowed_ips else None
    self._peer_mtu = peer_mtu


  @cached_property
  def allowed_ips(self) -> Sequence[str]:
    if self._allowed_ips is None:
      return self.DEFAULT_ALLOWED_IPS
    return self._allowed_ips


  @cached_property
  def interface(self) -> str:
    if self._interface is None:
      return self.DEFAULT_INTERFACE
    return self._interface


  @cached_property
  def port(self) -> int:
    if self._port is None:
      return self.DEFAULT_PORT
    return self._port


  @cached_property
  def peer_port(self) -> int:
    if self._peer_port is None:
      if self.DEFAULT_PEER_PORT is None:
        return self.port
      return self.DEFAULT_PEER_PORT
    return self._peer_port


  @cached_property
  def peer_mtu(self) -> Optional[int]:
    if self._peer_mtu is None:
      return self.DEFAULT_PEER_MTU
    return self._peer_mtu


  @cached_property
  def subnet(self) -> ipaddress.IPv4Network:
    if self._subnet is None:
      return ipaddress.ip_network(self.DEFAULT_SUBNET)
    return self._subnet


  @cached_property
  def base_ip(self) -> int:
    return self.subnet.network_address


  @cached_property
  def netmask(self) -> int:
    return ipv4_netmask_to_cidr(self.subnet.netmask)


  def serialize(self) -> dict:
    serialized = {
      "port": self.port,
      "peer_port": self.peer_port,
      "subnet": str(self.subnet),
      "interface": self.interface,
      "allowed_ips": list(self.allowed_ips),
      "peer_mtu": self.peer_mtu,
    }
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
    if self.peer_mtu is None:
      del serialized["peer_mtu"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, cls: Optional[type]=None) -> "VpnSettings":
    if cls is None:
      cls = VpnSettings
    return cls(
      port=serialized.get("port"),
      peer_port=serialized.get("peer_port"),
      subnet=serialized.get("subnet"),
      interface=serialized.get("interface"),
      allowed_ips=serialized.get("allowed_ips"),
      peer_mtu=serialized.get("peer_mtu"))


class RootVpnSettings(VpnSettings):
  DEFAULT_PORT = 63447
  DEFAULT_PEER_PORT = 63448
  DEFAULT_SUBNET = "10.255.128.0/22"
  DEFAULT_INTERFACE = "uwg-v{}"

  @staticmethod
  def deserialize(serialized: dict) -> "RootVpnSettings":
    return VpnSettings.deserialize(serialized, cls=RootVpnSettings)


class ParticlesVpnSettings(VpnSettings):
  DEFAULT_PORT = 63449
  DEFAULT_SUBNET = "10.254.0.0/16"
  DEFAULT_INTERFACE = "uwg-p{}"
  DEFAULT_ALLOWED_IPS = [
    # "0.0.0.0/0",
  ]
  # Lower MTU to allow for WireGuard headers
  DEFAULT_PEER_MTU = 1348

  @staticmethod
  def deserialize(serialized: dict) -> "ParticlesVpnSettings":
    return VpnSettings.deserialize(serialized, cls=ParticlesVpnSettings)


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

  def __init__(self,
      port: int | None = None,
      subnet: str | ipaddress.IPv4Network | None = None,
      interface: str | None = None,
      deployment_strategy: Optional[DeploymentStrategyKind]=None,
      deployment_strategy_args: Optional[dict]=None) -> None:
    self._deployment_strategy = deployment_strategy
    self.deployment_strategy_args = dict(deployment_strategy_args or {})
    super().__init__(port, subnet, interface)


  @property
  def deployment_strategy(self) -> DeploymentStrategyKind:
    if self._deployment_strategy is None:
      return self.DEFAULT_DEPLOYMENT_STRATEGY
    return self._deployment_strategy


  @deployment_strategy.setter
  def deployment_strategy(self, val: Union[str, DeploymentStrategyKind]) -> None:
    self._deployment_strategy = (
      DeploymentStrategyKind[val.upper()] if isinstance(val, str) else
      val
    )


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
    return BackboneVpnSettings(
      port=serialized.get("port"),
      subnet=serialized.get("subnet"),
      interface=serialized.get("interface"),
      deployment_strategy=deployment_strategy,
      deployment_strategy_args=serialized.get("deployment_strategy_args"))


class UvnSettings:
  # DEFAULT_TIMING_PROFILE = TimingProfile.FAST
  DEFAULT_TIMING_PROFILE = TimingProfile.DEFAULT
  DEFAULT_ENABLE_PARTICLES_VPN = True
  DEFAULT_ENABLE_ROOT_VPN = True

  def __init__(self,
      root_vpn: Optional[RootVpnSettings]=None,
      particles_vpn: Optional[ParticlesVpnSettings]=None,
      backbone_vpn: Optional[BackboneVpnSettings]=None,
      timing_profile: Optional[TimingProfile]=None,
      enable_particles_vpn: Optional[bool]=None,
      enable_root_vpn: Optional[bool]=None) -> None:
    self.root_vpn = root_vpn or RootVpnSettings()
    self.particles_vpn = particles_vpn or ParticlesVpnSettings()
    self.backbone_vpn = backbone_vpn or BackboneVpnSettings()
    self._timing_profile = timing_profile
    self._enable_particles_vpn = enable_particles_vpn
    self._enable_root_vpn = enable_root_vpn
    self.full_mesh = False

  @property
  def timing_profile(self) -> TimingProfile:
    if self._timing_profile is None:
      return self.DEFAULT_TIMING_PROFILE
    return self._timing_profile


  @timing_profile.setter
  def timing_profile(self, val: TimingProfile) -> None:
    self._timing_profile = val


  @property
  def enable_particles_vpn(self) -> bool:
    if self._enable_particles_vpn is None:
      return self.DEFAULT_ENABLE_PARTICLES_VPN
    return self._enable_particles_vpn


  @enable_particles_vpn.setter
  def enable_particles_vpn(self, val: bool) -> None:
    self._enable_particles_vpn = val


  @property
  def enable_root_vpn(self) -> bool:
    if self._enable_root_vpn is None:
      return self.DEFAULT_ENABLE_ROOT_VPN
    return self._enable_root_vpn


  @enable_root_vpn.setter
  def enable_root_vpn(self, val: bool) -> None:
    self._enable_root_vpn = val


  def serialize(self) -> dict:
    serialized = {
      "root_vpn": self.root_vpn.serialize(),
      "particles_vpn": self.particles_vpn.serialize(),
      "backbone_vpn": self.backbone_vpn.serialize(),
      "timing_profile": self.timing_profile.name,
      "enable_particles_vpn": self.enable_particles_vpn,
      "enable_root_vpn": self.enable_root_vpn,
    }
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
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "UvnSettings":
    timing_profile = serialized.get("timing_profile")
    return UvnSettings(
      root_vpn=RootVpnSettings.deserialize(serialized.get("root_vpn", {})),
      particles_vpn=ParticlesVpnSettings.deserialize(serialized.get("particles_vpn", {})),
      backbone_vpn=BackboneVpnSettings.deserialize(serialized.get("backbone_vpn", {})),
      timing_profile=TimingProfile[timing_profile] if timing_profile else None,
      enable_particles_vpn=serialized.get("enable_particles_vpn"),
      enable_root_vpn=serialized.get("enable_root_vpn"))


class CellId:
  DEFAULT_ALLOW_PARTICLES = False
  DEFAULT_ALLOWED_LANS = []
  DEFAULT_IGNORED_LANS = []
  DEFAULT_LOCATION = "Earth"
  DEFAULT_ROAMING = False
  DEFAULT_ENABLE_PARTICLES_VPN = True
  DEFAULT_ENABLE_ROOT_VPN = True

  def __init__(self,
      id: int,
      name: str,
      owner: str,
      owner_name: Optional[str]=None,
      address: Optional[str]=None,
      location: Optional[str] = None,
      allowed_lans: Optional[Iterable[ipaddress.IPv4Network]]=None,
      enable_particles_vpn: Optional[bool]=None) -> None:
    self.id = id
    self.name = name
    self.owner = owner
    self._owner_name = owner_name
    self._address = address
    
    self._location = location
    self._allowed_lans = set(allowed_lans) if allowed_lans is not None else None
    self._enable_particles_vpn = enable_particles_vpn

    if not self.name:
      raise ValueError("invalid UVN cell name")
    if not self.owner:
      raise ValueError("invalid UVN cell owner")
    if not self.owner_name:
      raise ValueError("invalid UVN cell owner name")


  def __str__(self) -> str:
    return self.name


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, CellId):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  @property
  def address(self) -> Optional[str]:
    return self._address


  @property
  def owner_name(self) -> str:
    if self._owner_name is None:
      return self.owner
    return self._owner_name


  @property
  def location(self) -> str:
    if self._location is None:
      return self.DEFAULT_LOCATION
    return self._location


  @property
  def allowed_lans(self) -> set[ipaddress.IPv4Network]:
    if self._allowed_lans is None:
      return self.DEFAULT_ALLOWED_LANS
    return self._allowed_lans


  @property
  def enable_particles_vpn(self) -> bool:
    if self.address is None:
      return False
    if self._enable_particles_vpn is None:
      return self.DEFAULT_ENABLE_PARTICLES_VPN
    return self._enable_particles_vpn


  def serialize(self) -> dict:
    serialized = {
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
      "address": self.address,
      "location": self.location,
      "allowed_lans": [str(l) for l in self.allowed_lans],
      "enable_particles_vpn": self.enable_particles_vpn,
    }
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
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict, id: int) -> "CellId":
    allowed_lans = serialized.get("allowed_lans")
    return CellId(
      id=id,
      name=serialized["name"],
      owner=serialized["owner"],
      owner_name=serialized.get("owner_name"),
      address=serialized.get("address"),
      location=serialized.get("location"),
      allowed_lans=[
        ipaddress.ip_network(l)
        for l in allowed_lans
      ] if allowed_lans else None,
      enable_particles_vpn=serialized.get("enable_particles_vpn"))


class ParticleId:
  def __init__(self,
      id: int,
      name: str,
      owner: str,
      owner_name: Optional[str] = None) -> None:
    self.id = id
    self.name = name
    self.owner = owner
    self._owner_name = owner_name

    if not self.name:
      raise ValueError("invalid UVN particle name")
    if not self.owner:
      raise ValueError("invalid UVN particle owner")
    if not self.owner_name:
      raise ValueError("invalid UVN particle owner name")


  def __str__(self) -> str:
    return self.name


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, UvnId):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  @property
  def owner_name(self) -> str:
    if self._owner_name is None:
      return self.owner
    return self._owner_name


  def serialize(self) -> dict:
    serialized = {
      "id": self.id,
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
    }
    if self._owner_name is None:
      del serialized["owner_name"]
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict, id: int) -> "ParticleId":
    return ParticleId(
      id=id,
      name=serialized.get("name"),
      owner=serialized.get("owner"),
      owner_name=serialized.get("owner_name"))


class UvnId:
  def __init__(self,
      name: str,
      owner: str,
      owner_name: Optional[str] = None,
      address: Optional[str] = None,
      cells: Optional[Mapping[int, CellId]] = None,
      particles: Optional[Mapping[int, ParticleId]] = None,
      hosts: Optional[Iterable[NameserverRecord]] = None,
      settings: Optional[UvnSettings]=None,
      generation_ts: Optional[str]=None) -> None:
    self.name = name
    self.owner = owner
    self.owner_name = owner_name if owner_name is not None else self.owner
    self.address = address if address is not None else self.name
    self.cells = dict(cells) if cells is not None else {}
    self.particles = dict(particles) if particles is not None else {}
    self.hosts = {
      r.hostname: r
        for r in hosts or []
    }
    self.settings = settings or UvnSettings()
    self.generation_ts = generation_ts or Timestamp.now().format()

    if not self.name:
      raise ValueError("invalid UVN name")
    if not self.address:
      raise ValueError("invalid UVN name")
    if not self.owner:
      raise ValueError("invalid UVN owner")
    if not self.owner_name:
      raise ValueError("invalid UVN owner name")


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, UvnId):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  def __str__(self) -> str:
    return self.name


  def serialize(self) -> dict:
    serialized = {
      "name": self.name,
      "owner": self.owner,
      "owner_name": self.owner_name,
      "address": self.address,
      "cells": [c.serialize() for c in sorted(self.cells.values(), key=lambda v: v.id)],
      "particles": [p.serialize() for p in sorted(self.particles.values(), key=lambda v: v.id)],
      "hosts": {r.hostname: r.address for r in self.hosts},
      "generation_ts": self.generation_ts,
      "settings": self.settings.serialize(),
    }
    if self.name == self.address:
      del serialized["address"]
    if self.owner == self.owner_name:
      del serialized["owner_name"]
    if len(serialized["cells"]) == 0:
      del serialized["cells"]
    if len(serialized["particles"]) == 0:
      del serialized["particles"]
    if len(serialized["hosts"]) == 0:
      del serialized["hosts"]
    if not serialized["settings"]:
      del serialized["settings"]
    return serialized
    

  @staticmethod
  def deserialize(serialized: dict) -> "UvnId":
    cells = {
      i + 1: CellId.deserialize(c_cfg, i + 1)
        for i, c_cfg in enumerate(serialized.get("cells", []))
    }
    particles = {
      i + 1: ParticleId.deserialize(p_cfg, i + 1)
        for i, p_cfg in enumerate(serialized.get("particles", []))

    }
    hosts = [
      NameserverRecord(hostname=k, address=v)
        for k, v in serialized.get("hosts", {}).items()
    ]
    return UvnId(
      name=serialized.get("name"),
      owner=serialized.get("owner"),
      owner_name=serialized.get("owner_name"),
      address=serialized.get("address"),
      cells=cells,
      particles=particles,
      hosts=hosts,
      generation_ts=serialized.get("generation_ts"),
      settings=UvnSettings.deserialize(serialized.get("settings", {})))


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


  def add_cell(self, name: str, **cell_args) -> CellId:
    if next((c for c in self.cells.values() if c.name == name), None) is not None:
      raise KeyError("duplicate cell", name)
    cell_id = self._next_cell_id()
    default_cell_args = {
      "enable_particles_vpn": self.settings.enable_particles_vpn,
    }
    default_cell_args.update(cell_args)
    cell = CellId(id=cell_id, name=name, **default_cell_args)
    self.cells[cell.id] = cell
    self.generation_ts = Timestamp.now().format()
    return cell


  def add_particle(self, name: str, **particle_args) -> CellId:
    if next((c for c in self.particles.values() if c.name == name), None) is not None:
      raise KeyError("duplicate particle", name)
    particle_id = self._next_particle_id()
    particle = ParticleId(id=particle_id, name=name, **particle_args)
    self.particles[particle.id] = particle
    self.generation_ts = Timestamp.now().format()
    return particle
