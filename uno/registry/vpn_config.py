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
from functools import cached_property
import ipaddress

from ..core.wg import (
  WireGuardConfig,
  WireGuardInterfaceConfig,
  WireGuardInterfacePeerConfig,
)
from .versioned import Versioned, disabled_if
from .cell import Cell
from .uvn import Uvn
from ..core.paired_map import PairedValuesMap
from ..core.ip import ipv4_netmask_to_cidr

if TYPE_CHECKING:
  from .registry import Registry
  

class CentralizedVpnConfig(Versioned):
  PROPERTIES = [
    "settings",
    "keymat",
    "peer_ids",
    "root_endpoint",
    "peer_endpoints",
  ]
  EQ_PROPERTIES = [
    "settings",
    "keymat",
    # "peer_ids",
  ]
  REQ_PROPERTIES = [
    "settings",
    "keymat",
  ]
  INITIAL_PEER_IDS = lambda self: {}
  INITIAL_PEER_ENDPOINTS = lambda self: {}


  def prepare_root_config(self, val: str | dict | WireGuardConfig) -> WireGuardConfig:
    return self.new_child(WireGuardConfig, val)


  def prepare_peer_configs(self, val: str | dict | dict[int, WireGuardConfig]) -> dict[int, WireGuardConfig]:
    def _mktuple(cls, v):
      peer_id, val = v
      cfg = self.new_child(cls, val)
      return (peer_id, cfg)
    return self.deserialize_collection(WireGuardConfig, val, dict, _mktuple)

  @property
  def root_ip(self) -> ipaddress.IPv4Address:
    return self.settings.base_ip + 1

  def peer_ip(self, peer: int) -> ipaddress.IPv4Address:
    return self.root_ip + peer

  @property
  def peer_port(self) -> int:
    return self.settings.peer_port if self.settings.peer_port else self.settings.port


  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.assert_keys()


  @disabled_if("readonly")
  def assert_keys(self) -> None:
    self.keymat.assert_keys()
    _ = self.root_config
    for peer in self.peer_ids:
      _ = self.peer_config(peer)


  @cached_property
  def root_config(self) -> WireGuardConfig:
    return WireGuardConfig(
      intf=WireGuardInterfaceConfig(
        name=self.settings.interface.format(1),
        privkey=self.keymat.root_key.private,
        address=self.root_ip,
        netmask=self.settings.netmask,
        port=None if self.root_endpoint is None else self.settings.port,
        endpoint=f"{self.root_endpoint}:{self.settings.port}" if self.root_endpoint is not None else None,
        mtu=self.settings.peer_mtu),
      peers=[
        WireGuardInterfacePeerConfig(
          id=peer_id,
          pubkey=peer_key.public,
          psk=peer_psk.value,
          address=self.peer_ip(peer_id),
          allowed=[str(self.peer_ip(peer_id))],
          endpoint=None if peer_endpoint is None else f"{peer_endpoint}:{self.peer_port}",
          keepalive=self.settings.keepalive if peer_endpoint else None)
        for peer_id in self.peer_ids
          for peer_key, peer_psk in [self.keymat.get_peer_material(peer_id, private=True)]
            for peer_endpoint in [self.peer_endpoints.get(peer_id)]
      ],
      masquerade=self.settings.masquerade,
      forward=self.settings.forward,
      tunnel=self.settings.tunnel,
      tunnel_root=True)


  def peer_config(self, peer: int) -> WireGuardConfig:
    peer_key, peer_psk = self.keymat.get_peer_material(peer, private=True)
    # peer_key, peer_psk = self.keymat.get_pair_material(0, peer)
    peer_endpoint = self.peer_endpoints.get(peer)
    return WireGuardConfig(
      intf=WireGuardInterfaceConfig(
        name=self.settings.interface.format(0),
        privkey=peer_key.private,
        address=self.peer_ip(peer),
        netmask=self.settings.netmask,
        port=None if not peer_endpoint else self.peer_port,
        endpoint=f"{peer_endpoint}:{self.peer_port}" if peer_endpoint else None,
        mtu=self.settings.peer_mtu),
      peers=[
        WireGuardInterfacePeerConfig(
          id=0,
          pubkey=self.keymat.root_key.public,
          psk=peer_psk.value,
          address=self.root_ip,
          allowed=[str(self.root_ip)],
          # allowed=[str(allowed_vpn_net)],

          # Prefer a "push" architecture, where the root will connect to each
          # peer, unless the peer has not public endpoint, in which case the
          # peer will need to connect to the root
          endpoint=None if self.root_endpoint is None or peer_endpoint else f"{self.root_endpoint}:{self.settings.port}",
          # Configure the interface with a non-zero keepalive period so
          # that it will keep the connection to the server open and allow
          # the server to push packets to it if needed. The assumption is
          # that the peer will be behind NAT, and thus require the NAT mapping
          # to be kept valid for communication to be initiated by the server.
          keepalive=self.settings.keepalive if not peer_endpoint else None)
      ],
      masquerade=self.settings.masquerade,
      forward=self.settings.forward,
      tunnel=self.settings.tunnel,
      tunnel_root=False)


class P2pVpnConfig(Versioned):
  PROPERTIES = [
    "settings",
    "keymat",
    "deployment",
    "peer_ids",
    "peer_endpoints",
  ]
  EQ_PROPERTIES = [
    "settings",
    "keymat",
  ]
  REQ_PROPERTIES = [
    "settings",
    "keymat",
    "deployment",
  ]
  INITIAL_PEER_IDS = lambda self: []
  INITIAL_PEER_ENDPOINTS = lambda self: {}


  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.assert_keys()


  @disabled_if("readonly")
  def assert_keys(self) -> None:
    for peer in self.peer_ids:
      _ = self.peer_config(peer)


  def peer_config(self, peer: int) -> list[WireGuardConfig]:
    peer_deploy_cfg = self.deployment.peers.get(peer)
    if peer_deploy_cfg is None:
      self.log.debug("peer configuration not found: {}", peer)
      return []

    return [
      WireGuardConfig(
        intf=WireGuardInterfaceConfig(
          name=self.settings.interface.format(peer_a_port_local),
          port=self.settings.port + peer_a_port_local if peer_a_endpoint else 0,
          privkey=PairedValuesMap.pick(peer, peer_b_id, peer, peer_b_keymat).private,
          endpoint=f"{peer_a_endpoint}:{self.settings.port + peer_a_port_local}"
            if peer_a_endpoint else None,
          address=peer_a_address,
          netmask=ipv4_netmask_to_cidr(link_network.netmask),
          # netmask=32,
          mtu=self.settings.peer_mtu),
        peers=[
          WireGuardInterfacePeerConfig(
            id=peer_b_id,
            pubkey=PairedValuesMap.pick(peer, peer_b_id, peer_b_id, peer_b_keymat).public,
            psk=peer_b_psk.value,
            address=peer_b_address,
            allowed=[str(self.settings.subnet), *map(str, self.settings.allowed_ips)],
            endpoint=f"{peer_b_endpoint}:{self.settings.port + peer_b_port_local}"
              if peer_b_endpoint else None,
            keepalive=None if peer_a_endpoint is not None else self.settings.keepalive)
        ],
        masquerade=self.settings.masquerade,
        forward=self.settings.forward,
        tunnel=self.settings.tunnel)
      for peer_b_id, (peer_a_port_local, peer_a_address, peer_b_address, link_network) in peer_deploy_cfg["peers"].items()
          for peer_b_deploy_cfg in [self.deployment.peers[peer_b_id]]
            for peer_b_port_local, _, _, _ in [peer_b_deploy_cfg["peers"][peer]]
              for (peer_b_keymat, peer_b_psk), _ in [self.keymat.assert_pair(peer, peer_b_id)]
                for peer_a_endpoint in [self.peer_endpoints[peer]]
                  for peer_b_endpoint in [self.peer_endpoints[peer_b_id]]
    ]



class UvnVpnConfig(Versioned):
  EQ_PROPERTIES = [
    "object_id"
  ]

  @classmethod
  def root_vpn_config(cls, registry: "Registry", rekeyed: bool=False) -> CentralizedVpnConfig | None:
    if not registry.uvn.settings.enable_root_vpn:
      if not rekeyed:
        cls.log.warning(f"root vpn disabled")
      return None

    # Check that the UVN has an address if any cell is private
    if not rekeyed and not registry.uvn.supports_reconfiguration:
      cls.log.warning("the UVN requires a registry address to support reconfiguration of private cells.")

    cells = sorted(registry.uvn.all_cells.values(), key=lambda v: v.id)

    return registry.new_child(CentralizedVpnConfig, {
      "root_endpoint": registry.uvn.address,
      "peer_endpoints": {c.id: c.address for c in cells},
      "peer_ids": [c.id for c in cells],
      "settings": registry.uvn.settings.root_vpn,
      "keymat": registry.root_vpn_keymat if not rekeyed else registry.rekeyed_root_vpn_keymat
    })


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for o in (
        self.root_vpn,
        self.rekeyed_root_vpn,
        *self.particles_vpns.values(),
        self.backbone_vpn):
      if o is None:
        continue
      yield o


  @property
  def uvn(self) -> Uvn:
    return self.registry.uvn
  

  @property
  def registry(self) -> "Registry":
    return self.parent


  @cached_property
  def root_vpn(self) -> CentralizedVpnConfig | None:
    return self.root_vpn_config(self.parent)


  @cached_property
  def rekeyed_root_vpn(self) -> CentralizedVpnConfig | None:
    if self.parent.rekeyed_root_config_id:
      return self.root_vpn_config(self.parent, rekeyed=True)
    return None


  @property
  def particles_vpns(self) -> dict[int, CentralizedVpnConfig]:
    return {
      cell.id: self.particles_vpn(cell)
      for cell in self.uvn.cells.values()
    }


  def particles_vpn(self, cell: Cell) -> CentralizedVpnConfig | None:
    if (not self.uvn.settings.enable_particles_vpn
        or not cell.settings.enable_particles_vpn):
      return None
    return self.parent.new_child(CentralizedVpnConfig,{
      "root_endpoint": cell.address,
      "peer_ids": sorted(self.uvn.particles.keys()),
      "settings": self.uvn.settings.particles_vpn,
      "keymat": self.parent.particles_vpn_keymats[cell.id],
    })


  @cached_property
  def backbone_vpn(self) -> P2pVpnConfig | None:
    if not self.parent.deployment:
      return None
    # Inject cell lans as allowed ips on the backbone vpn links 
    self.uvn.settings.backbone_vpn.allowed_ips = [
      *self.uvn.settings.backbone_vpn.allowed_ips,
      *[str(l) for c in self.uvn.cells.values() for l in c.allowed_lans],
    ]
    cells = sorted(self.uvn.cells.values(), key=lambda v: v.id)
    return self.parent.new_child(P2pVpnConfig,{
      "keymat": self.parent.backbone_vpn_keymat,
      "settings": self.uvn.settings.backbone_vpn,
      "peer_ids": [c.id for c in cells],
      "peer_endpoints": {c.id: c.address for c in cells},
      "deployment": self.parent.deployment,
    })


  @disabled_if("readonly")
  def assert_keys(self) -> None:
    _ = self.root_vpn
    _ = self.backbone_vpn
    for _ in self.particles_vpns.values():
      pass
