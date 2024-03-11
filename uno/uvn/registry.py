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

import yaml

from .uvn_id import (
  UvnId,
  UvnSettings,
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
from .log import Logger as log
from .dds import locate_rti_license
from .exec import exec_command
from .particle import generate_particle_packages
from .id_db import IdentityDatabase
from .keys_dds import DdsKeysBackend
from .ask import ask_yes_no

class Registry(Versioned):
  UVN_FILENAME = "uvn.yaml"
  CONFIG_FILENAME = "registry.yaml"
  AGENT_PACKAGE_FILENAME = "{}.uvn-agent"
  AGENT_CONFIG_FILENAME = "agent.yaml"


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
    registry.configure(**configure_args, init=True)

    # Make sure we have an RTI license, since we're gonna need it later.
    if not registry.rti_license.is_file():
      rti_license = locate_rti_license(search_path=[registry.root])
      if not rti_license or not rti_license.is_file():
        log.error(f"[REGISTRY] RTI license not found, cell agents will not be available")
        raise RuntimeError("please specify an RTI license file")
      else:
        registry.rti_license = rti_license
    
    log.warning(f"[REGISTRY] initialized UVN {registry.uvn_id.name}: {registry.root}")

    return registry


  def __init__(self,
      root: Path,
      uvn_id: UvnId,
      root_vpn_config: Optional[CentralizedVpnConfig]=None,
      particles_vpn_configs: Optional[Mapping[int, CentralizedVpnConfig]]=None,
      excluded_particles_vpn_configs: Optional[Mapping[int, CentralizedVpnConfig]]=None,
      backbone_vpn_config: Optional[P2PVpnConfig]=None,
      **super_args) -> None:
    super().__init__(**super_args)
    self.root = root.resolve()
    self.uvn_id = uvn_id
    self.root_vpn_config = root_vpn_config
    self.particles_vpn_configs = particles_vpn_configs or {}
    self.excluded_particles_vpn_configs = excluded_particles_vpn_configs or {}
    self.backbone_vpn_config = backbone_vpn_config
    self.id_db = IdentityDatabase(
      backend=DdsKeysBackend(
        root=self.root / "id",
        org=self.uvn_id.name,
        generation_ts=self.uvn_id.generation_ts,
        init_ts=self.uvn_id.init_ts),
      local_id=self.uvn_id,
      uvn_id=self.uvn_id)
    self.loaded = True
    self._rekeyed_root_vpn = set()
    self._rekeyed_particles_vpn = set()


  @property
  def deployed(self) -> bool:
    return (
      self.backbone_vpn_config is not None
      and self.backbone_vpn_config.deployment is not None
      and self.backbone_vpn_config.deployment.generation_ts is not None
    )


  @property
  def id(self) -> int:
    import hashlib
    h = hashlib.sha256()
    h.update("".join([
      str(self.backbone_vpn_config.deployment.generation_ts)
        if self.backbone_vpn_config.deployment else "",
      self.root_vpn_config.generation_ts,
      *(c.generation_ts for c in sorted(self.particles_vpn_configs.values(), key=lambda v: v.generation_ts))
    ]).encode())
    return h.hexdigest()


  @property
  def rti_license(self) -> Path:
    return self.root / "rti_license.dat"


  @rti_license.setter
  def rti_license(self, val: Path | None) -> None:
    # Copy file to registry's root
    if val != self.rti_license:
      log.warning(f"[REGISTRY] caching RTI license: {val} → {self.rti_license}")
      exec_command(["cp", val, self.rti_license])
      self.rti_license.chmod(0o644)
      self.updated()


  @property
  def cells_dir(self) -> Path:
    return self.root / "cells"


  @property
  def particles_dir(self) -> Path:
    return self.root / "particles"


  @property
  def rekeyed_registry(self) -> "Registry|None":
    rekeyed_uvn = self.root / f"{Registry.UVN_FILENAME}.rekeyed"
    rekeyed_reg = self.root / f"{Registry.CONFIG_FILENAME}.rekeyed"
    if rekeyed_uvn.exists() and rekeyed_reg.exists():
      return Registry.load(self.root, uvn_config=rekeyed_uvn, registry_config=rekeyed_reg)
    return None


  def save_rekeyed(self) -> None:
    rekeyed_registry = self.rekeyed_registry
    if not rekeyed_registry:
      raise RuntimeError("no rekeyed registry to save")
    rekeyed_registry._save_to_disk(noninteractive=True)
    self.drop_rekeyed()


  def drop_rekeyed(self) -> None:
    rekeyed_uvn = self.root / f"{Registry.UVN_FILENAME}.rekeyed"
    rekeyed_reg = self.root / f"{Registry.CONFIG_FILENAME}.rekeyed"
    if rekeyed_uvn.exists():
      rekeyed_uvn.unlink()
    if rekeyed_reg.exists():
      rekeyed_reg.unlink()


  def configure(
      self,
      rti_license: Path | None = None,
      drop_keys_root_vpn: bool=False,
      drop_keys_particles_vpn: bool=False,
      drop_keys_id_db: bool=False,
      # drop_keys_gpg: bool=False,
      redeploy: bool=False,
      init: bool=False,
      allow_rekeyed: bool=False,
      **uvn_args) -> bool:
    if not allow_rekeyed and self.rekeyed_registry:
      raise RuntimeError("pending rekeying changes. run 'uno sync' or delete the *.rekeyed files")
    
    if drop_keys_root_vpn and self.uvn_id.excluded_cells:
      log.warning(f"[REGISTRY] banned cells will need to be manually updated in order to rejoin the uvn {list(self.uvn_id.excluded_cells.values())}")
      ask_yes_no("Continue with rekeying?")

    if not self.root.is_dir():
      self.root.mkdir(parents=True, mode=0o700)

    if uvn_args:
      self.uvn_id.configure(**uvn_args)

    if rti_license is not None:
      self.rti_license = rti_license

    rekeyed_root = len(self._rekeyed_root_vpn) > 0
    rekeyed_particles = len(self._rekeyed_particles_vpn) > 0
    self._rekeyed_root_vpn.clear()
    self._rekeyed_particles_vpn.clear()
    
    changed = self.collect_changes()
    changed_uvn = next((c for c, _ in changed if isinstance(c, (UvnId, UvnSettings))), None) is not None
    changed_cell = next((c for c, _ in changed if isinstance(c, CellId)), None) is not None
    changed_particle = next((c for c, _ in changed if isinstance(c, ParticleId)), None) is not None
    changed_root_vpn = (
      init
      or changed_uvn
      or changed_cell
      or drop_keys_root_vpn
      or rekeyed_root
      or next((c for c, _ in changed if isinstance(c, RootVpnSettings)), None) is not None
    )
    changed_particles_vpn = (
      init
      or changed_uvn
      or changed_cell
      or changed_particle
      or drop_keys_particles_vpn
      or rekeyed_particles
      or next((c for c, _ in changed if isinstance(c, ParticlesVpnSettings)), None) is not None
    )
    changed_backbone_vpn = (
      init
      or changed_uvn
      or changed_cell
      or redeploy
      or next((c for c, _ in changed if isinstance(c, BackboneVpnSettings)), None) is not None
    )

    for cell in self.uvn_id.excluded_cells.values():
      cell_particles_vpn_config = self.particles_vpn_configs.get(cell.id)
      if not cell_particles_vpn_config:
        continue
      self.excluded_particles_vpn_configs[cell.id] = cell_particles_vpn_config
      del self.particles_vpn_configs[cell.id]

    for cell in self.uvn_id.cells.values():
      was_excluded = cell.id in self.excluded_particles_vpn_configs
      if not was_excluded:
        continue
      self.particles_vpn_configs[cell.id] = self.excluded_particles_vpn_configs[cell.id]
      del self.excluded_particles_vpn_configs[cell.id]

    if changed_uvn or changed_cell or changed_particle:
      self.id_db.uvn_id = self.uvn_id

    if changed_root_vpn:
      self._configure_root_vpn(drop_keys=drop_keys_root_vpn)

    if changed_particles_vpn:
      self._configure_particles_vpns(drop_keys=drop_keys_particles_vpn)

    if changed_backbone_vpn:
      self._configure_backbone_vpn()

    if (redeploy
        or changed
        or changed_root_vpn
        or changed_particles_vpn
        or changed_backbone_vpn):
      log.warning("[REGISTRY] configuration updated")
      self._save_to_disk(
        drop_keys_id_db=drop_keys_id_db,
        rekeyed=rekeyed_root or drop_keys_root_vpn)

    return bool(changed)


  def _configure_root_vpn(self, drop_keys: bool=False) -> None:
    if self.root_vpn_config and not drop_keys:
      log.debug(f"[REGISTRY] preserving existing keys for Root VPN")
      keymat = self.root_vpn_config.keymat
      keymat.purge_gone_peers([c.id for c in self.uvn_id.all_cells])
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

    cells = sorted(self.uvn_id.all_cells, key=lambda v: v.id)

    self.root_vpn_config = CentralizedVpnConfig(
      root_endpoint=self.uvn_id.address,
      peer_endpoints={c.id: c.address for c in cells},
      peer_ids=[c.id for c in cells],
      settings=self.uvn_id.settings.root_vpn,
      keymat=keymat)
    self.root_vpn_config.generate()


  def _configure_particles_vpns(self, drop_keys: bool=False) -> None:
    particle_ids = sorted(self.uvn_id.particles.keys())
    new_particles_vpn_configs = {}
    for cell in self.uvn_id.cells.values():
      existing_config = self.particles_vpn_configs.get(cell.id)
      if existing_config and not drop_keys:
        log.debug(f"[REGISTRY] preserving existing keys for Particle VPN: {cell}")
        keymat = existing_config.keymat
        keymat.purge_gone_peers([c.id for c in (*self.uvn_id.particles.values(), *self.uvn_id.excluded_particles.values())])
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

    if self.backbone_vpn_config.deployment.peers:
      log.warning(f"[REGISTRY] UVN backbone links updated [{self.backbone_vpn_config.deployment.generation_ts}]")
      self.uvn_id.log_deployment(
        deployment=self.backbone_vpn_config.deployment)
    elif self.uvn_id.cells:
      log.error(f"[REGISTRY] UVN has {len(self.uvn_id.cells)} cells but no backbone links!")


  def rekey_particle(self, particle: ParticleId, cells: Iterable[CellId]|None=None):
    if not cells:
      cells = list(self.uvn_id.cells.values())
    
    particles = list(p for p in self.uvn_id.all_particles if p != particle)
    for cell in cells:
      particles_vpn_config = self.particles_vpn_configs[cell.id]
      particles_vpn_config.keymat.purge_gone_peers((p.id for p in particles))
      self._rekeyed_particles_vpn.add(cell)
    
    self._rekeyed_particles_vpn.add(particle)
    self.updated()
  

  def rekey_cell(self, cell: CellId, root_vpn: bool=False, particles_vpn: bool=False):
    if not (root_vpn or particles_vpn):
      raise RuntimeError("nothing to rekey")

    cells = list(c for c in self.uvn_id.cells.values() if c != cell)
    if root_vpn:
      log.warning(f"[REGISTRY] dropping Root VPN key for cell: {cell}")
      self.root_vpn_config.keymat.purge_gone_peers((c.id for c in cells))
      self._rekeyed_root_vpn.add(cell)
    
    if particles_vpn:
      log.warning(f"[REGISTRY] dropping Particles VPN keys for cell: {cell}")
      self.particles_vpn_configs[cell.id].keymat.drop_keys()
      self._rekeyed_particles_vpn.add(cell)
      for p in self.uvn_id.particles.values():
        self._rekeyed_particles_vpn.add(p)

    self.updated()


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
    from .cell_agent import CellAgent
    import shutil

    log.activity("[REGISTRY] regenerating cell and particle artifacts")

    if self.cells_dir.is_dir():
      shutil.rmtree(self.cells_dir)

    for cell in self.uvn_id.cells.values():
      CellAgent.generate(
        registry=self,
        cell=cell,
        output_dir=self.cells_dir)

    if self.particles_dir.is_dir():
      shutil.rmtree(self.particles_dir)

    generate_particle_packages(
      uvn_id=self.uvn_id,
      particle_vpn_configs=self.particles_vpn_configs,
      output_dir=self.particles_dir)
  


  def collect_changes(self) -> list[Tuple[Versioned, dict]]:
    changed = super().collect_changes()
    changed.extend(self.uvn_id.collect_changes())
    return changed


  @property
  def peek_changed(self) -> bool:
    return (
      super().peek_changed
      or self.uvn_id.peek_changed
    )


  def serialize(self) -> dict:
    sup_serialized = super().serialize()
    sup_serialized.update({
      "root_vpn": self.root_vpn_config.serialize() if self.root_vpn_config else None,
      "particles_vpn": {
        p: cfg.serialize()
        for p, cfg in self.particles_vpn_configs.items()
      },
      "excluded_particles_vpn": {
        p: cfg.serialize()
        for p, cfg in self.excluded_particles_vpn_configs.items()
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
    if not sup_serialized["excluded_particles_vpn"]:
      del sup_serialized["excluded_particles_vpn"]

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
      excluded_particles_vpn_configs={
        p: CentralizedVpnConfig.deserialize(cfg, settings_cls=ParticlesVpnSettings)
        for p, cfg in serialized.get("config", {}).get("excluded_particles_vpn", {}).items()
      },
      backbone_vpn_config=P2PVpnConfig.deserialize(
        backbone_vpn_config,
        settings_cls=BackboneVpnSettings) if backbone_vpn_config else None)


  @staticmethod
  def load(
      root: Path,
      uvn_config: Path|None=None,
      registry_config: Path|None=None) -> "Registry":
    uvn_file = uvn_config or root / Registry.UVN_FILENAME
    config_file = registry_config or root / Registry.CONFIG_FILENAME
    serialized = {
      "uvn": yaml.safe_load(uvn_file.read_text()),
      "config": yaml.safe_load(config_file.read_text()),
    }
    registry = Registry.deserialize(serialized, root)
    return registry


  def _save_to_disk(self, drop_keys_id_db: bool=False, rekeyed: bool=False, noninteractive: bool=False) -> None:
    if not noninteractive:
      ask_yes_no("Save updated registry to disk?")

    serialized = self.serialize()

    uvn_file = self.root / self.UVN_FILENAME
    if rekeyed:
      uvn_file = Path(f"{uvn_file}.rekeyed")
    uvn_file.parent.mkdir(parents=True, exist_ok=True)
    uvn_file.write_text(yaml.safe_dump(serialized["uvn"]))
    uvn_file.chmod(0o600)
    log.warning(f"[REGISTRY] updated UVN configuration: {uvn_file}")

    config_file = self.root / self.CONFIG_FILENAME
    if rekeyed:
      config_file = Path(f"{config_file}.rekeyed")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(serialized.get("config", {})))
    config_file.chmod(0o600)
    log.warning(f"[REGISTRY] updated registry state: {config_file}")

    if drop_keys_id_db:
      raise NotImplementedError()
    self.id_db.assert_keys()
    self._generate_agents()
