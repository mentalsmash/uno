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
from typing import Optional, Mapping, Tuple, Iterable
import shutil

import ipaddress
import yaml
import networkx
import matplotlib.pyplot as plt

from .uvn_id import (
  UvnId,
  CellId,
  ParticleId,
  BackboneVpnSettings,
  ParticlesVpnSettings,
  RootVpnSettings,
  Versioned,
)
from .deployment import (
  DeploymentStrategy,
  DeploymentStrategyKind,
  StaticDeploymentStrategy,
  CrossedDeploymentStrategy,
  CircularDeploymentStrategy,
  RandomDeploymentStrategy,
  FullMeshDeploymentStrategy,
)
from .vpn_config import CentralizedVpnConfig, P2PVpnConfig
from .gpg import IdentityDatabase
from .log import Logger as log
from .dds_keymat import DdsKeyMaterial
from .dds import locate_rti_license, UvnTopic
from .exec import exec_command
from .particle import generate_particle_packages


class Registry(Versioned):
  UVN_FILENAME = "uvn.yaml"
  CONFIG_FILENAME = "registry.yaml"
  AGENT_PACKAGE_FILENAME = "{}.uvn-agent"
  AGENT_CONFIG_FILENAME = "agent.yaml"
  UVN_SECRET = "uvn.secret"

  AGENT_REGISTRY_TOPICS = {
    "writers": [
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
    ],

    "readers": {
      UvnTopic.CELL_ID: {},
      # UvnTopic.DNS: {},
    },
  }

  AGENT_CELL_TOPICS = {
    "writers": [
      UvnTopic.CELL_ID,
      # UvnTopic.DNS,
    ],

    "readers": {
      UvnTopic.CELL_ID: {},
      # UvnTopic.DNS: {},
      UvnTopic.UVN_ID: {},
      UvnTopic.BACKBONE: {},
    }
  }


  @staticmethod
  def create(
      name: str,
      owner_id: str,
      root: Path | None = None,
      **configure_args):
    root = root or Path.cwd() / name
    log.activity(f"[REGISTRY] initializing UVN {name} in {root}")
    root_empty = next(root.glob("*"), None) is None
    if root.is_dir() and not root_empty:
      raise RuntimeError("target directory not empty", root)

    uvn_id = UvnId(name=name, owner_id=owner_id)
    registry = Registry(root=root, uvn_id=uvn_id)
    registry.configure(**configure_args)
    # Make sure we have an RTI license, since we're gonna need it later.
    # The check occurs implicitly when the attribute is accessed.
    # Set the attribute so the file is copied to the registry's root.
    registry.rti_license = registry.rti_license

    log.warning(f"[REGISTRY] initialized UVN {registry.uvn_id.name}: {registry.root}")

    return registry


  def __init__(self,
      root: Path,
      uvn_id: UvnId,
      root_vpn_config: Optional[CentralizedVpnConfig]=None,
      particles_vpn_configs: Optional[Mapping[int, CentralizedVpnConfig]]=None,
      backbone_vpn_config: Optional[P2PVpnConfig]=None,
      rti_license: Optional[Path]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    self.root = root.resolve()
    self.uvn_id = uvn_id
    self.root_vpn_config = root_vpn_config
    self.particles_vpn_configs = particles_vpn_configs
    self.backbone_vpn_config = backbone_vpn_config
    self.rti_license = rti_license
    self.dds_keymat = DdsKeyMaterial(
      root=self.root,
      org=self.uvn_id.name,
      generation_ts=self.uvn_id.init_ts)
    self.loaded = True


  @property
  def deployed(self) -> bool:
    return (
      self.backbone_vpn_config is not None
      and self.backbone_vpn_config.deployment is not None
      and self.backbone_vpn_config.deployment.generation_ts is not None
    )


  @property
  def rti_license(self) -> Path:
    rti_license = self._rti_license
    if rti_license is None:
      rti_license = locate_rti_license(search_path=[self.root])
    if not rti_license or not rti_license.is_file():
      raise RuntimeError("RTI license not found", rti_license)
    return rti_license


  @rti_license.setter
  def rti_license(self, val: Path | None) -> None:
    # Copy file to registry's root
    if val is not None:
      rti_license = self.root / "rti_license.dat"
      if val != rti_license:
        log.warning(f"[REGISTRY] caching RTI license: {val} -> {rti_license}")
        exec_command(["cp", val, rti_license])
    else:
      rti_license = None
    self.update("_rti_license", rti_license)


  @property
  def cells_dir(self) -> Path:
    return self.root / "cells"


  @property
  def particles_dir(self) -> Path:
    return self.root / "particles"


  def configure(
      self,
      rti_license: Path | None = None,
      drop_keys_root_vpn: bool=False,
      drop_keys_particles_vpn: bool=False,
      drop_keys_dds: bool=False,
      # drop_keys_gpg: bool=False,
      redeploy: bool=False,
      **uvn_args) -> bool:

    if uvn_args:
      self.uvn_id.configure(**uvn_args)

    if rti_license is not None:
      self.rti_license = rti_license

    changed = self.collect_changes()
    changed_uvn = next((c for c in changed if isinstance(c, UvnId)), None) is not None
    changed_cell = next((c for c in changed if isinstance(c, CellId)), None) is not None
    changed_particle = next((c for c in changed if isinstance(c, ParticleId)), None) is not None
    changed_dds_keymat = changed_uvn or drop_keys_dds
    changed_root_vpn = (
      changed_uvn
      or changed_cell
      or drop_keys_root_vpn
      or next((c for c in changed if isinstance(c, RootVpnSettings)), None) is not None
    )
    changed_particles_vpn = (
      changed_uvn
      or changed_cell
      or changed_particle
      or drop_keys_particles_vpn
      or next((c for c in changed if isinstance(c, ParticlesVpnSettings)), None) is not None
    )
    changed_backbone_vpn = (
      changed_cell
      or redeploy
      or next((c for c in changed if isinstance(c, BackboneVpnSettings)), None) is not None
    )

    # changed_gpg = changed_uvn or drop_keys_gpg
    # if changed_gpg:
    #   self._configure_gpg_keys(drop_keys=drop_keys_gpg)

    if changed_dds_keymat:
      self._configure_dds_keymat(drop_keys=drop_keys_dds)

    if changed_root_vpn:
      self._configure_root_vpn(drop_keys=drop_keys_root_vpn)

    if changed_particles_vpn:
      self._configure_particles_vpns(drop_keys=drop_keys_particles_vpn)

    if changed_backbone_vpn:
      self._configure_backbone_vpn()

    modified = (
      changed_dds_keymat
      or changed_root_vpn
      or changed_particles_vpn
      or changed_backbone_vpn
    )

    if modified:
      log.warning("[REGISTRY] configuration updated")
      self._generate_agents()
      self._save_to_disk()

    return modified



  def _configure_gpg_keys(self) -> None:
    id_db = IdentityDatabase(self.root)
    id_db.assert_gpg_keys(self.uvn_id)


  def _configure_root_vpn(self, drop_keys: bool=False) -> None:
    if self.root_vpn_config and not drop_keys:
      log.debug(f"[REGISTRY] preserving existing keys for Root VPN")
      keymat = self.root_vpn_config.keymat
    elif self.root_vpn_config and drop_keys:
      log.warning(f"[REGISTRY] dropping existing keys for Root VPN")
      keymat = None
    else:
      keymat = None
      log.warning(f"[REGISTRY] generating keys for Root VPN")
    
    # Check that the UVN has an address if any cell is private
    private_cells = list(map(str, self.uvn_id.private_cells))
    if not self.uvn_id.supports_reconfiguration:
      log.error(f"[REGISTRY] the UVN requires a registry address to support reconfiguration of private cells: {private_cells}")

    self.root_vpn_config = CentralizedVpnConfig(
      root_endpoint=self.uvn_id.address if private_cells else None,
      peer_endpoints={
        c.id: c.address
        for c in self.uvn_id.cells.values()
      },
      peer_ids=self.uvn_id.cells.keys(),
      settings=self.uvn_id.settings.root_vpn,
      keymat=keymat)
    self.root_vpn_config.generate()


  def _configure_particles_vpns(self, drop_keys: bool=False) -> None:
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


  def _configure_backbone_vpn(self) -> None:
    peer_endpoints = {c.id: c.address for c in self.uvn_id.cells.values()}
    # Inject all the attached networks as allowed ips
    serialized = self.uvn_id.settings.backbone_vpn.serialize()
    backbone_vpn_settings = BackboneVpnSettings.deserialize(serialized)
    allowed_lans = [str(l) for c in self.uvn_id.cells.values() for l in c.allowed_lans]
    if allowed_lans:
      backbone_vpn_settings.allowed_ips = [
        *backbone_vpn_settings.allowed_ips,
        *allowed_lans,
      ]
    # Always regenerate key material
    self.backbone_vpn_config = P2PVpnConfig(
      settings=backbone_vpn_settings,
      peer_endpoints=peer_endpoints)
    self.backbone_vpn_config.generate(self.deployment_strategy)

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
        log.warning(f"[REGISTRY] {peer_a} ->")
        logged.append(peer_a)
      log.warning(f"[REGISTRY]   [{peer_a_port_i}] {peer_a_endpoint} {arrow} {peer_b}[{peer_b_port_i}] {peer_b_endpoint}")

    if self.backbone_vpn_config.deployment.peers:
      log.warning(f"[REGISTRY] UVN backbone links updated [{self.backbone_vpn_config.deployment.generation_ts}]")
      self.uvn_id.log_deployment(
        deployment=self.backbone_vpn_config.deployment,
        logger=_log_deployment)
    elif self.uvn_id.cells:
      log.error(f"[REGISTRY] UVN has {len(self.uvn_id.cells)} cells but no backbone links!")


  def _configure_dds_keymat(self, drop_keys: bool=False) -> None:
    peers = {
      "root": ([
        dw.value
        for dw in Registry.AGENT_REGISTRY_TOPICS["writers"]
      ], [
        dr.value
        for dr in Registry.AGENT_REGISTRY_TOPICS["readers"].keys()
      ])
    }
    peers.update({
      c.name: ([
        dw.value
        for dw in Registry.AGENT_CELL_TOPICS["writers"]
      ], [
        dr.value
        for dr in Registry.AGENT_CELL_TOPICS["readers"].keys()
      ])
      for c in self.uvn_id.cells.values()
    })
    self.dds_keymat.init(peers, reset=drop_keys)


  @property
  def deployment_strategy(self) -> DeploymentStrategy:
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
    return strategy



  def _generate_agents(self) -> None:
    from .agent import CellAgent

    log.activity("[REGISTRY] regenerating cell and particle artifacts")

    if self.cells_dir.is_dir():
      import shutil
      shutil.rmtree(self.cells_dir)

    for cell in self.uvn_id.cells.values():
      CellAgent.generate(
        registry=self,
        cell=cell,
        output_dir=self.cells_dir)

    if self.particles_dir.is_dir():
      import shutil
      shutil.rmtree(self.particles_dir)

    generate_particle_packages(
      uvn_id=self.uvn_id,
      particle_vpn_configs=self.particles_vpn_configs,
      output_dir=self.particles_dir)
  


  def collect_changes(self) -> list[Versioned]:
    changed = super().collect_changes()
    changed.extend(self.uvn_id.collect_changes())
    return changed


  def serialize(self) -> dict:
    sup_serialized = super().serialize()
    sup_serialized.update({
      "root_vpn": self.root_vpn_config.serialize() if self.root_vpn_config else None,
        "particles_vpn": {
          p: cfg.serialize()
          for p, cfg in self.particles_vpn_configs.items()
        },
        "backbone_vpn": self.backbone_vpn_config.serialize()
          if self.backbone_vpn_config else None,
    })
    if not sup_serialized["root_vpn"]:
      del sup_serialized["root_vpn"]
    if not sup_serialized["backbone_vpn"]:
      del sup_serialized["backbone_vpn"]
    if not sup_serialized["particles_vpn"]:
      del sup_serialized["particles_vpn"]

    serialized = {
      "uvn": self.uvn_id.serialize(),
      "config": sup_serialized
    }
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


  def _save_to_disk(self) -> None:
    config_file = self.root / self.CONFIG_FILENAME
    uvn_file = self.root / self.UVN_FILENAME
    serialized = self.serialize()
    uvn_file.write_text(yaml.safe_dump(serialized["uvn"]))
    log.warning(f"[REGISTRY] updated UVN configuration: {uvn_file}")
    config_file.write_text(yaml.safe_dump(serialized.get("config", {})))
    config_file.chmod(0o600)
    uvn_file.chmod(0o600)
    log.warning(f"[REGISTRY] updated registry state: {config_file}")
