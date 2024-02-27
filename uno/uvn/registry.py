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
from typing import Optional, Mapping, Tuple
import shutil

import yaml
import networkx
import matplotlib.pyplot as plt

from .uvn_id import UvnId, BackboneVpnSettings, ParticlesVpnSettings, RootVpnSettings
from .deployment import (
  DeploymentStrategyKind,
  StaticDeploymentStrategy,
  CrossedDeploymentStrategy,
  CircularDeploymentStrategy,
  RandomDeploymentStrategy,
  FullMeshDeploymentStrategy,
)
from .vpn_config import CentralizedVpnConfig, P2PVpnConfig, P2PLinksMap
from .gpg import IdentityDatabase
from .log import Logger as log
from .dds_keymat import DdsKeyMaterial, CertificateSubject

class Registry:
  UVN_FILENAME = "uvn.yaml"
  CONFIG_FILENAME = "registry.yaml"
  AGENT_PACKAGE_FILENAME = "{}.uvn-agent"
  AGENT_CONFIG_FILENAME = "agent.yaml"
  AGENT_LICENSE = "rti_license.dat"
  UVN_SECRET = "uvn.secret"

  def __init__(self,
      root: Path,
      uvn_id: UvnId,
      root_vpn_config: Optional[CentralizedVpnConfig]=None,
      particles_vpn_configs: Optional[Mapping[int, CentralizedVpnConfig]]=None,
      backbone_vpn_config: Optional[P2PVpnConfig]=None) -> None:
    self.root = root.resolve()
    self.uvn_id = uvn_id
    self.root_vpn_config = root_vpn_config
    self.particles_vpn_configs = particles_vpn_configs or {}
    self.backbone_vpn_config = backbone_vpn_config
    self.dds_keymat = DdsKeyMaterial(
      root=self.root,
      org=self.uvn_id.name,
      generation_ts=self.uvn_id.init_ts)


  @property
  def deployed(self) -> bool:
    return (
      self.backbone_vpn_config is not None
      and self.backbone_vpn_config.deployment is not None
      and self.backbone_vpn_config.deployment.generation_ts is not None
    )

  @property
  def rti_license(self) -> Path:
    return self.root / self.AGENT_LICENSE


  @property
  def uvn_secret(self) -> Path:
    return self.root / self.UVN_SECRET


  def install_rti_license(self, license: Path) -> None:
    self.rti_license.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license, self.rti_license)
    log.activity(f"[REGISTRY] RTI license installed: {license}")


  def configure(self) -> None:
    # self.assert_gpg_keys()
    self.configure_root_vpn()
    self.configure_particles_vpns()
    self.configure_backbone_vpn()
    self.configure_dds_keymat()


  def assert_gpg_keys(self) -> None:
    id_db = IdentityDatabase(self.root)
    id_db.assert_gpg_keys(self.uvn_id)


  def configure_root_vpn(self, drop_keys: bool=False) -> None:
    peer_endp = {
        c.id: c.address
        for c in self.uvn_id.cells.values()
      }
    if self.root_vpn_config and not drop_keys:
      log.debug(f"[REGISTRY] preserving existing keys for Root VPN")
      keymat = self.root_vpn_config.keymat
    elif self.root_vpn_config and drop_keys:
      log.warning(f"[REGISTRY] dropping existing keys for Root VPN")
      keymat = None
    else:
      keymat = None
      log.warning(f"[REGISTRY] generating keys for Particle VPN")
    self.root_vpn_config = CentralizedVpnConfig(
      root_endpoint=self.uvn_id.address
        if next((c for c in self.uvn_id.cells.values() if not c.address), None) else None,
      peer_endpoints={
        c.id: c.address
        for c in self.uvn_id.cells.values()
      },
      peer_ids=self.uvn_id.cells.keys(),
      settings=self.uvn_id.settings.root_vpn,
      keymat=keymat)
    self.root_vpn_config.generate()


  def configure_particles_vpns(self, drop_keys: bool=False) -> None:
    particle_ids = list(self.uvn_id.particles.keys())
    new_particles_vpn_configs = {}
    for cell in self.uvn_id.cells.values():
      existing_config = self.particles_vpn_configs.get(cell.id)
      if existing_config and not drop_keys:
        log.debug(f"[REGISTRY] preserving existing keys for Particle VPN: {cell}")
        keymat = existing_config.keymat
      elif existing_config and drop_keys:
        log.warning(f"[REGISTRY] dropping existing keys for Particle VPN: {cell}")
        keymat = None
      else:
        keymat = None
        log.warning(f"[REGISTRY] generating keys for Particle VPN: {cell}")
      new_particles_vpn_configs[cell.id] = particles_vpn = CentralizedVpnConfig(
        root_endpoint=cell.address,
        peer_ids=particle_ids,
        settings=self.uvn_id.settings.particles_vpn,
        keymat=keymat)
      particles_vpn.generate(tunnel=True)
    self.particles_vpn_configs = new_particles_vpn_configs


  def configure_backbone_vpn(self, drop_keys: bool=False) -> None:
    peer_endpoints = {c.id: c.address for c in self.uvn_id.cells.values()}
    if self.backbone_vpn_config and not drop_keys:
      log.debug("[REGISTRY] preserving existing keys for Backbone VPN")
      keymat = self.backbone_vpn_config.keymat
    elif self.backbone_vpn_config and drop_keys:
      log.warning("[REGISTRY] dropping existing keys for Backbone VPN")
      keymat = None
    else:
      keymat=None
      log.warning("[REGISTRY] generating keys for Backbone VPN")
    # Inject all the attached networks as allowed ips
    backbone_vpn_settings = BackboneVpnSettings.deserialize(
      self.uvn_id.settings.backbone_vpn.serialize())
    backbone_vpn_settings.allowed_ips = [
      *backbone_vpn_settings.allowed_ips,
      *(str(l) for c in self.uvn_id.cells.values() for l in c.allowed_lans),
    ]
    self.backbone_vpn_config = P2PVpnConfig(
      settings=backbone_vpn_settings,
      peer_endpoints=peer_endpoints,
      keymat=keymat)
    self.deploy()


  def configure_dds_keymat(self, drop_keys: bool=False) -> None:
    peers = {
      "root": ([
        "uno/uvn/info",
        "uno/uvn/deployment",
      ], [
        "uno/uvn/ns",
        "uno/cell/info",
      ])
    }
    peers.update({
      c: ([
        "uno/uvn/ns",
        "uno/cell/info",
      ], [
        "uno/uvn/info",
        "uno/uvn/ns",
        "uno/uvn/deployment",
        "uno/cell/info",
      ])
      for c in self.uvn_id.cells.values()
    })
    self.dds_keymat.init(peers, reset=drop_keys)


  def deploy(self) -> str:
    peers = set(self.uvn_id.cells)
    private_peers = set(c.id for c in self.uvn_id.cells.values() if not c.address)

    if self.uvn_id.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CROSSED:
      strategy = CrossedDeploymentStrategy(
        peers=peers,
        private_peers=private_peers,
        args=self.uvn_id.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn_id.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.RANDOM:
      strategy = RandomDeploymentStrategy(
        peers=peers,
        private_peers=private_peers,
        args=self.uvn_id.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn_id.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CIRCULAR:
      strategy = CircularDeploymentStrategy(
        peers=peers,
        private_peers=private_peers,
        args=self.uvn_id.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn_id.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.FULL_MESH:
      strategy = FullMeshDeploymentStrategy(
        peers=peers,
        private_peers=private_peers,
        args=self.uvn_id.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn_id.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.STATIC:
      strategy = StaticDeploymentStrategy(
        peers=peers,
        private_peers=private_peers,
        args=self.uvn_id.settings.backbone_vpn.deployment_strategy_args)
    else:
      raise RuntimeError("unknown deployment strategy or invalid configuration", self.uvn_id.settings.backbone_vpn.deployment_strategy)

    log.activity(f"[REGISTRY] deployment strategy arguments:")
    log.activity(f"[REGISTRY] - strategy: {strategy}")
    log.activity(f"[REGISTRY] - public peers [{len(strategy.public_peers)}]: [{', '.join(map(str, map(self.uvn_id.cells.__getitem__, strategy.public_peers)))}]")
    log.activity(f"[REGISTRY] - private peers [{len(strategy.private_peers)}]: [{', '.join(map(str, map( self.uvn_id.cells.__getitem__, strategy.private_peers)))}]")
    log.activity(f"[REGISTRY] - extra args: {strategy.args}")

    self.backbone_vpn_config.keymat.drop_keys()
    self.backbone_vpn_config.generate(strategy)

    log.warning(f"[REGISTRY] new backbone deployment generated [{self.backbone_vpn_config.deployment.generation_ts}]")

    for peer_a_id, peer_a_cfg in sorted(self.backbone_vpn_config.deployment.peers.items(), key=lambda t: t[0]):
      peer_a = self.uvn_id.cells[peer_a_id]
      log.warning(f"[REGISTRY] {peer_a} ->")
      for peer_b_id, (peer_a_port_i, peer_a_addr, peer_b_addr, link_subnet) in sorted(
          peer_a_cfg["peers"].items(), key=lambda t: t[1][0]):
        peer_b = self.uvn_id.cells[peer_b_id]
        peer_b_port_i = self.backbone_vpn_config.deployment.peers[peer_b_id]["peers"][peer_a_id][0]
        if not peer_a.address:
          peer_a_endpoint = "private LAN"
        else:
          peer_a_endpoint = f"{peer_a.address}:{self.uvn_id.settings.backbone_vpn.port + peer_a_port_i}"
        if not peer_b.address:
          peer_b_endpoint = "private LAN"
          arrow = "<-- "
        else:
          peer_b_endpoint = f"{peer_b.address}:{self.uvn_id.settings.backbone_vpn.port + peer_b_port_i}"
          if peer_a.address:
            arrow = "<-->"
          else:
            arrow = " -->"
        log.warning(f"[REGISTRY]   [{peer_a_port_i}] {peer_a_endpoint} {arrow} {peer_b}[{peer_b_port_i}] {peer_b_endpoint}")

    return self.backbone_vpn_config.deployment.generation_ts


  def serialize(self) -> dict:
    serialized = {
      "uvn": self.uvn_id.serialize(),
      "config": {
        "root_vpn": self.root_vpn_config.serialize() if self.root_vpn_config else None,
        "particles_vpn": {
          p: cfg.serialize()
          for p, cfg in self.particles_vpn_configs.items()
        },
        "backbone_vpn": self.backbone_vpn_config.serialize()
          if self.backbone_vpn_config else None,
      }
    }
    if not serialized["config"]["root_vpn"]:
      del serialized["config"]["root_vpn"]
    if not serialized["config"]["backbone_vpn"]:
      del serialized["config"]["backbone_vpn"]
    if not serialized["config"]["particles_vpn"]:
      del serialized["config"]["particles_vpn"]
    if not serialized["config"]:
      del serialized["config"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, root: Path) -> "Registry":
    root_vpn_config = serialized.get("config", {}).get("root_vpn")
    backbone_vpn_config = serialized.get("config", {}).get("backbone_vpn", {})
    return Registry(
      root=root,
      uvn_id=UvnId.deserialize(serialized["uvn"]),
      root_vpn_config=CentralizedVpnConfig.deserialize(
        root_vpn_config,
        settings_cls=RootVpnSettings) if root_vpn_config else None,
      particles_vpn_configs={
        p: CentralizedVpnConfig.deserialize(cfg, settings_cls=ParticlesVpnSettings)
        for p, cfg in serialized.get("config", {}).get("particles_vpn", {}).items()
      },
      backbone_vpn_config=P2PVpnConfig.deserialize(
        backbone_vpn_config,
        settings_cls=BackboneVpnSettings) if backbone_vpn_config else None)


  @staticmethod
  def load(root: Path) -> "Registry":
    uvn_file = root / Registry.UVN_FILENAME
    config_file = root / Registry.CONFIG_FILENAME
    serialized = {
      "uvn": yaml.safe_load(uvn_file.read_text()),
      "config": yaml.safe_load(config_file.read_text()),
    }
    registry = Registry.deserialize(serialized, root)
    return registry


  def save_to_disk(self) -> None:
    config_file = self.root / self.CONFIG_FILENAME
    uvn_file = self.root / self.UVN_FILENAME
    serialized = self.serialize()
    uvn_file.write_text(yaml.safe_dump(serialized["uvn"]))
    config_file.write_text(yaml.safe_dump(serialized.get("config", {})))
    config_file.chmod(0o600)
    uvn_file.chmod(0o600)
    log.activity(f"[REGISTRY] configuration file UPDATED: {config_file}")

