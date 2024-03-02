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
from typing import Optional, Mapping, Iterable, Tuple
import ipaddress

from .wg import (
  WireGuardConfig,
  WireGuardInterfaceConfig,
  WireGuardInterfacePeerConfig,
)
from .uvn_id import VpnSettings
from .deployment import DeploymentStrategy, P2PLinkAllocationMap, P2PLinksMap
from .paired_map import PairedValuesMap

from .vpn_keymat import CentralizedVpnKeyMaterial, P2PVpnKeyMaterial

from .ip import ipv4_netmask_to_cidr
from .time import Timestamp


class CentralizedVpnConfig:
  DEFAULT_KEEPALIVE = 25

  def __init__(self,
      peer_ids: Iterable[int],
      settings: VpnSettings,
      root_endpoint: Optional[str]=None,
      peer_endpoints: Optional[Mapping[int, str]]=None,
      root_config: Optional[WireGuardConfig]=None,
      peer_configs: Optional[Mapping[int, WireGuardConfig]]=None,
      keymat: Optional[CentralizedVpnKeyMaterial]=None,
      generation_ts: Optional[str]=None) -> None:
    self.peer_ids = list(peer_ids)
    self.settings = settings
    self.root_endpoint = root_endpoint
    self.peer_endpoints = dict(peer_endpoints or {})
    self.root_config = root_config
    self.peer_configs = peer_configs or {}
    self.keymat = keymat or CentralizedVpnKeyMaterial()
    self.generation_ts = generation_ts or Timestamp.now().format()



  def generate(self, tunnel: bool=False) -> None:
    self.keymat.assert_keys(self.peer_ids)

    vpn_base_ip = self.settings.base_ip
    allowed_vpn_net = str(self.settings.subnet) if not self.settings.allowed_ips else ",".join(map(str, self.settings.allowed_ips))

    root_ip = vpn_base_ip + 1
    peer_ips = {
      peer_id: root_ip + peer_id
        for peer_id in self.peer_ids
    }

    self.root_config = WireGuardConfig(
      intf=WireGuardInterfaceConfig(
        name=self.settings.interface.format(1),
        privkey=self.keymat.root_key.privkey,
        address=root_ip,
        netmask=self.settings.netmask,
        port=None if self.root_endpoint is None else self.settings.port,
        endpoint=f"{self.root_endpoint}:{self.settings.port}" if self.root_endpoint is not None else None,
        mtu=self.settings.peer_mtu),
      peers=[
        WireGuardInterfacePeerConfig(
          id=peer_id,
          pubkey=peer_key.pubkey,
          psk=peer_psk,
          address=peer_ips[peer_id],
          allowed=[str(peer_ips[peer_id])],
          endpoint=None if peer_endpoint is None else f"{peer_endpoint}:{self.settings.peer_port}",
          keepalive=None if self.root_endpoint is not None else self.DEFAULT_KEEPALIVE)
        for peer_id in self.peer_ids
          for peer_key, peer_psk in [self.keymat.get_peer_material(peer_id)]
            for peer_endpoint in [self.peer_endpoints.get(peer_id)]
      ],
      tunnel=tunnel,
      tunnel_root=True)


    self.peer_configs = {
      peer_id: WireGuardConfig(
        intf=WireGuardInterfaceConfig(
          name=self.settings.interface.format(0),
          privkey=peer_key.privkey,
          address=peer_ips[peer_id],
          netmask=self.settings.netmask,
          port=None if not peer_endpoint else self.settings.peer_port,
          endpoint=f"{peer_endpoint}:{self.settings.peer_port}" if peer_endpoint else None,
          mtu=self.settings.peer_mtu),
        peers=[
          WireGuardInterfacePeerConfig(
            id=0,
            pubkey=self.keymat.root_key.pubkey,
            psk=peer_psk,
            address=root_ip,
            allowed=[str(allowed_vpn_net)],
            # Prefer a "push" architecture, where the root will connect to each
            # peer, unless the peer has not public endpoint, in which case the
            # peer will need to connect to the root
            endpoint=None if self.root_endpoint is None or peer_endpoint else f"{self.root_endpoint}:{self.settings.port}",
            # Configure the interface with a non-zero keepalive period so
            # that it will keep the connection to the server open and allow
            # the server to push packets to it if needed. The assumption is
            # that the peer will be behind NAT, and thus require the NAT mapping
            # to be kept valid for communication to be initiated by the server.
            keepalive=None if peer_endpoint else self.DEFAULT_KEEPALIVE)
        ],
        tunnel=tunnel,
        tunnel_root=False)
       for peer_id in self.peer_ids
          for peer_key, peer_psk in [self.keymat.get_peer_material(peer_id)]
            for peer_endpoint in [self.peer_endpoints.get(peer_id)]
    }


  def serialize(self) -> dict:
    serialized = {
      "settings": self.settings.serialize(),
      "root_config": self.root_config.serialize() if self.root_config is not None else None,
      "root_endpoint": self.root_endpoint,
      "peer_configs": {
        k: v.serialize()
          for k, v in self.peer_configs.items()
      },
      "peer_endpoints": self.peer_endpoints,
      "keymat": self.keymat.serialize(),
      "generation_ts": self.generation_ts,
    }
    if not serialized["root_endpoint"]:
      del serialized["root_endpoint"]
    if not serialized["peer_endpoints"]:
      del serialized["peer_endpoints"]
    if not serialized["root_config"]:
      del serialized["root_config"]
    if not serialized["peer_configs"]:
      del serialized["peer_configs"]
    if not serialized["keymat"]:
      del serialized["keymat"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, settings_cls: Optional[type]=None) -> "CentralizedVpnConfig":
    if settings_cls is None:
      settings_cls = VpnSettings
    peers_config = {
      k: WireGuardConfig.deserialize(v)
        for k, v in serialized.get("peer_configs", {}).items()
    }
    peer_ids = list(peers_config.keys())
    return CentralizedVpnConfig(
      peer_ids=peer_ids,
      peer_configs=peers_config,
      settings=settings_cls.deserialize(serialized["settings"]),
      root_endpoint=serialized.get("root_endpoint"),
      peer_endpoints=serialized.get("peer_endpoints", []),
      root_config=WireGuardConfig.deserialize(serialized.get("root_config", {})),
      keymat=CentralizedVpnKeyMaterial.deserialize(serialized.get("keymat", {})),
      generation_ts=serialized["generation_ts"])




class P2PVpnConfig:
  def __init__(self,
      peer_endpoints: Mapping[int, str],
      settings: VpnSettings,
      keymat: Optional[P2PVpnKeyMaterial]=None,
      peer_configs: Optional[Mapping[int, WireGuardConfig]]=None,
      deployment: Optional[P2PLinksMap]=None) -> None:
    self.peer_endpoints = dict(peer_endpoints)
    self.settings = settings
    self.keymat = keymat or P2PVpnKeyMaterial()
    self.peer_configs = peer_configs or {}
    self.deployment = deployment


  def generate(self, strategy: DeploymentStrategy) -> None:
    self.deployment = strategy.deploy(network_map=P2PLinkAllocationMap(self.settings.subnet))

    self.peer_configs = {
      peer_a_id: [
        WireGuardConfig(
          intf=WireGuardInterfaceConfig(
            name=self.settings.interface.format(peer_a_port_local),
            port=self.settings.port + peer_a_port_local if peer_a_endpoint else 0,
            privkey=PairedValuesMap.pick(peer_a_id, peer_b_id, peer_a_id, peer_b_keymat).privkey,
            endpoint=f"{peer_a_endpoint}:{self.settings.port + peer_a_port_local}"
              if peer_a_endpoint else None,
            address=peer_a_address,
            netmask=ipv4_netmask_to_cidr(link_network.netmask)),
          peers=[
            WireGuardInterfacePeerConfig(
              id=peer_b_id,
              pubkey=PairedValuesMap.pick(peer_a_id, peer_b_id, peer_b_id, peer_b_keymat).pubkey,
              psk=peer_b_psk,
              address=peer_b_address,
              allowed=[str(self.settings.subnet), *map(str, self.settings.allowed_ips)],
              endpoint=f"{peer_b_endpoint}:{self.settings.port + peer_b_port_local}"
                if peer_b_endpoint else None)
          ])
        for peer_b_id, (peer_a_port_local, peer_a_address, peer_b_address, link_network) in peer_a_deploy_cfg["peers"].items()
            for peer_b_deploy_cfg in [self.deployment.peers[peer_b_id]]
              for peer_b_port_local, _, _, _ in [peer_b_deploy_cfg["peers"][peer_a_id]]
                for peer_b_keymat, peer_b_psk in [self.keymat.assert_pair(peer_a_id, peer_b_id)]
                  for peer_a_endpoint in [self.peer_endpoints[peer_a_id]]
                   for peer_b_endpoint in [self.peer_endpoints[peer_b_id]]
      ]
      for peer_a_id, peer_a_deploy_cfg in self.deployment.peers.items()
    }


  def serialize(self) -> dict:
    serialized = {
      "settings": self.settings.serialize(),
      "peer_endpoints": dict(self.peer_endpoints),
      "keymat": self.keymat.serialize(),
      "peer_configs": {
        peer_id: [cfg.serialize() for cfg in peer_cfgs]
        for peer_id, peer_cfgs in self.peer_configs.items()
      },
      "deployment": self.deployment.serialize(),
    }
    if not serialized["peer_endpoints"]:
      del serialized["peer_endpoints"]
    if not serialized["deployment"]:
      del serialized["deployment"]
    if not serialized["keymat"]:
      del serialized["keymat"]
    if not serialized["peer_configs"]:
      del serialized["peer_configs"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, settings_cls: Optional[type]=None) -> "P2PVpnConfig":
    if settings_cls is None:
      settings_cls = VpnSettings
    return P2PVpnConfig(
      settings=settings_cls.deserialize(serialized["settings"]),
      peer_endpoints=serialized.get("peer_endpoints", {}),
      peer_configs={
        peer_id: [
          WireGuardConfig.deserialize(cfg)
            for cfg in peer_cfgs
        ]
        for peer_id, peer_cfgs in serialized.get("peer_configs", {}).items()
      },
      deployment=P2PLinksMap.deserialize(serialized.get("deployment", {})),
      keymat=P2PVpnKeyMaterial.deserialize(serialized.get("keymat", {})))
