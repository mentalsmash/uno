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
from typing import Mapping, Iterable, TYPE_CHECKING

from ..core.wg import (
  WireGuardConfig,
  WireGuardInterfaceConfig,
  WireGuardInterfacePeerConfig,
)
from .vpn_settings import VpnSettings
from .deployment import P2PLinksMap
from .vpn_keymat import CentralizedVpnKeyMaterial, P2PVpnKeyMaterial
from .versioned import Versioned
from ..core.paired_map import PairedValuesMap
from ..core.ip import ipv4_netmask_to_cidr
from ..core.time import Timestamp
from ..core.log import Logger as log

if TYPE_CHECKING:
  from .registry import Registry
  

class CentralizedVpnConfig:
  DEFAULT_KEEPALIVE = 25


  def __init__(self,
      root_config: WireGuardConfig,
      peer_configs: Mapping[int, WireGuardConfig],
      generation_ts: Timestamp) -> None:
    self.root_config = root_config
    self.peer_configs = dict(peer_configs or {})
    self.generation_ts = generation_ts

  @staticmethod
  def generate(
      peer_ids: Iterable[int],
      settings: VpnSettings,
      keymat: CentralizedVpnKeyMaterial,
      root_endpoint: str | None = None,
      peer_endpoints: dict | None = None) -> "CentralizedVpnConfig":
    self = CentralizedVpnConfig(None, {}, Timestamp.now().format())

    peer_endpoints = dict(peer_endpoints or {})

    keymat.assert_keys(peer_ids)

    vpn_base_ip = settings.base_ip
    # allowed_vpn_net = str(settings.subnet) if not settings.allowed_ips else ",".join(map(str, settings.allowed_ips))

    root_ip = vpn_base_ip + 1
    peer_ips = {
      peer_id: root_ip + peer_id
        for peer_id in peer_ids
    }

    peer_mtu = settings.peer_mtu

    peer_port = settings.peer_port if settings.peer_port else settings.port

    self.root_config = WireGuardConfig(
      intf=WireGuardInterfaceConfig(
        name=settings.interface.format(1),
        privkey=keymat.root_key.private,
        address=root_ip,
        netmask=settings.netmask,
        port=None if root_endpoint is None else settings.port,
        endpoint=f"{root_endpoint}:{settings.port}" if root_endpoint is not None else None,
        mtu=peer_mtu),
      peers=[
        WireGuardInterfacePeerConfig(
          id=peer_id,
          pubkey=peer_key.public,
          psk=peer_psk.value,
          address=peer_ips[peer_id],
          allowed=[str(peer_ips[peer_id])],
          endpoint=None if peer_endpoint is None else f"{peer_endpoint}:{peer_port}",
          keepalive=self.DEFAULT_KEEPALIVE if peer_endpoint else None)
        for peer_id in peer_ids
          for peer_key, peer_psk in [keymat.get_peer_material(peer_id)]
            for peer_endpoint in [peer_endpoints.get(peer_id)]
      ],
      masquerade=settings.masquerade,
      forward=settings.forward,
      tunnel=settings.tunnel,
      tunnel_root=True)


    self.peer_configs = {
      peer_id: WireGuardConfig(
        intf=WireGuardInterfaceConfig(
          name=settings.interface.format(0),
          privkey=peer_key.private,
          address=peer_ips[peer_id],
          netmask=settings.netmask,
          port=None if not peer_endpoint else peer_port,
          endpoint=f"{peer_endpoint}:{peer_port}" if peer_endpoint else None,
          mtu=peer_mtu),
        peers=[
          WireGuardInterfacePeerConfig(
            id=0,
            pubkey=keymat.root_key.public,
            psk=peer_psk.value,
            address=root_ip,
            allowed=[str(root_ip)],
            # allowed=[str(allowed_vpn_net)],

            # Prefer a "push" architecture, where the root will connect to each
            # peer, unless the peer has not public endpoint, in which case the
            # peer will need to connect to the root
            endpoint=None if root_endpoint is None or peer_endpoint else f"{root_endpoint}:{settings.port}",
            # Configure the interface with a non-zero keepalive period so
            # that it will keep the connection to the server open and allow
            # the server to push packets to it if needed. The assumption is
            # that the peer will be behind NAT, and thus require the NAT mapping
            # to be kept valid for communication to be initiated by the server.
            keepalive=self.DEFAULT_KEEPALIVE if not peer_endpoint else None)
        ],
        masquerade=settings.masquerade,
        forward=settings.forward,
        tunnel=settings.tunnel,
        tunnel_root=False)
       for peer_id in peer_ids
          for peer_key, peer_psk in [keymat.get_peer_material(peer_id)]
            for peer_endpoint in [peer_endpoints.get(peer_id)]
    }

    return self


  def serialize(self, public: bool=False) -> dict:
    serialized = {
      "root_config": self.root_config.serialize(),
      "peer_configs": {
        k: v.serialize()
          for k, v in self.peer_configs.items()
      },
      "generation_ts": self.generation_ts.format(),
    }
    if not serialized["peer_configs"]:
      del serialized["peer_configs"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "CentralizedVpnConfig":
    return CentralizedVpnConfig(
      peer_configs={
        k: WireGuardConfig.deserialize(v)
          for k, v in serialized.get("peer_configs", {}).items()
      },
      root_config=WireGuardConfig.deserialize(serialized.get("root_config", {})),
      generation_ts=Timestamp.parse(serialized["generation_ts"]))



class P2PVpnConfig:
  DEFAULT_KEEPALIVE = 25


  def __init__(self,
      peer_configs: Mapping[int, WireGuardConfig] | None = None) -> None:
    self.peer_configs = dict(peer_configs or {})


  @staticmethod
  def generate(
      peer_endpoints: Mapping[int, str],
      settings: VpnSettings,
      keymat: P2PVpnKeyMaterial,
      deployment: P2PLinksMap) -> "P2PVpnConfig":
    self = P2PVpnConfig()

    self.peer_configs = {
      peer_a_id: [
        WireGuardConfig(
          intf=WireGuardInterfaceConfig(
            name=settings.interface.format(peer_a_port_local),
            port=settings.port + peer_a_port_local if peer_a_endpoint else 0,
            privkey=PairedValuesMap.pick(peer_a_id, peer_b_id, peer_a_id, peer_b_keymat).private,
            endpoint=f"{peer_a_endpoint}:{settings.port + peer_a_port_local}"
              if peer_a_endpoint else None,
            address=peer_a_address,
            netmask=ipv4_netmask_to_cidr(link_network.netmask),
            # netmask=32,
            mtu=settings.peer_mtu),
          peers=[
            WireGuardInterfacePeerConfig(
              id=peer_b_id,
              pubkey=PairedValuesMap.pick(peer_a_id, peer_b_id, peer_b_id, peer_b_keymat).public,
              psk=peer_b_psk.value,
              address=peer_b_address,
              allowed=[str(settings.subnet), *map(str, settings.allowed_ips)],
              endpoint=f"{peer_b_endpoint}:{settings.port + peer_b_port_local}"
                if peer_b_endpoint else None,
              keepalive=None if peer_a_endpoint is not None else self.DEFAULT_KEEPALIVE)
          ],
          masquerade=settings.masquerade,
          forward=settings.forward,
          tunnel=settings.tunnel)
        for peer_b_id, (peer_a_port_local, peer_a_address, peer_b_address, link_network) in peer_a_deploy_cfg["peers"].items()
            for peer_b_deploy_cfg in [deployment.peers[peer_b_id]]
              for peer_b_port_local, _, _, _ in [peer_b_deploy_cfg["peers"][peer_a_id]]
                for (peer_b_keymat, peer_b_psk), _ in [keymat.assert_pair(peer_a_id, peer_b_id)]
                  for peer_a_endpoint in [peer_endpoints[peer_a_id]]
                   for peer_b_endpoint in [peer_endpoints[peer_b_id]]
      ]
      for peer_a_id, peer_a_deploy_cfg in deployment.peers.items()
    }
    return self


  def serialize(self, public: bool=False) -> dict:
    serialized = {
      "peer_configs": {
        peer_id: [cfg.serialize() for cfg in peer_cfgs]
        for peer_id, peer_cfgs in self.peer_configs.items()
      },
    }
    if not serialized["peer_configs"]:
      del serialized["peer_configs"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "P2PVpnConfig":
    return P2PVpnConfig(
      peer_configs={
        peer_id: [
          WireGuardConfig.deserialize(cfg)
            for cfg in peer_cfgs
        ]
        for peer_id, peer_cfgs in serialized.get("peer_configs", {}).items()
      },
      deployment=P2PLinksMap.deserialize(serialized.get("deployment", {})))



def root_vpn_config(registry: "Registry", rekeyed: bool=False) -> CentralizedVpnConfig | None:
    if not registry.uvn.settings.enable_root_vpn:
      if not rekeyed:
        log.warning(f"[REGISTRY] root vpn disabled")
      return None

  # Check that the UVN has an address if any cell is private
    if not rekeyed and not registry.uvn.supports_reconfiguration:
      log.warning(f"[REGISTRY] the UVN requires a registry address to support reconfiguration of private cells.")

    cells = sorted(registry.uvn.all_cells.values(), key=lambda v: v.id)
    return CentralizedVpnConfig.generate(
      root_endpoint=registry.uvn.address,
      peer_endpoints={c.id: c.address for c in cells},
      peer_ids=[c.id for c in cells],
      settings=registry.uvn.settings.root_vpn,
      keymat=registry.root_vpn_keymat if not rekeyed else registry.rekeyed_root_vpn_keymat)


class UvnVpnConfig(Versioned):
  PROPERTIES = [
    "root_vpn",
    "rekeyed_root_vpn",
    "particles_vpns",
    "backbone_vpn",
  ]
  # def __init__(self, parent: "Registry") -> None:
  #   self.registry = registry


  # @property
  # def nested(self) -> Generator[Versioned, None, None]:
  #   for o in (
  #       self.root_vpn,
  #       self.rekeyed_root_vpn,
  #       *self.particles_vpns.values(),
  #       self.backbone_vpn ):
  #     yield o


  
  def INITIAL_ROOT_VPN(self) -> CentralizedVpnConfig | None:
    return root_vpn_config(self.parent)


  def INITIAL_REKEYED_ROOT_VPN(self) -> CentralizedVpnConfig | None:
    if self.parent.rekeyed_root:
      return root_vpn_config(self.parent, rekeyed=True)
    return None


  def INITIAL_PARTICLES_VPN(self) -> dict[int, CentralizedVpnConfig]:
    if not self.parent.uvn.settings.enable_particles_vpn:
      return {}

    particle_ids = sorted(self.parent.uvn.particles.keys())
    return {
      cell.id: CentralizedVpnConfig.generate(
        root_endpoint=cell.address,
        peer_ids=particle_ids,
        settings=self.parent.uvn.settings.particles_vpn,
        keymat=self.parent.particles_vpn_keymats[cell.id])
      for cell in self.parent.uvn.cells.values()
        if cell.settings.enable_particles_vpn
    }


  def INITIAL_BACKBONE_VPN(self) -> P2PVpnConfig | None:
    if not self.parent.deployment:
      return None
    # Inject cell lans as allowed ips on the backbone vpn links 
    self.parent.uvn.settings.backbone_vpn.allowed_ips = [
      *self.parent.uvn.settings.backbone_vpn.allowed_ips,
      *[str(l) for c in self.parent.uvn.cells.values() for l in c.allowed_lans],
    ]
    return P2PVpnConfig.generate(
      keymat=self.parent.backbone_vpn_keymat,
      settings=self.parent.uvn.settings.backbone_vpn,
      peer_endpoints={c.id: c.address for c in self.parent.uvn.cells.values()},
      deployment=self.parent.deployment)


  def assert_keys(self) -> None:
    _ = self.root_vpn
    if self.parent.rekeyed_root:
      _ = self.rekeyed_root_vpn
    _ = self.particles_vpns
    _ = self.backbone_vpn

