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
from typing import Iterable, Generator
from functools import cached_property
import yaml

from ..core.ask import ask_yes_no

from .uvn import Uvn
from .cell import Cell
from .particle import Particle
from .user import User
from .versioned import Versioned

from .deployment import (
  P2PLinksMap,
  P2PLinkAllocationMap,
  DeploymentStrategy,
  DeploymentStrategyKind,
  StaticDeploymentStrategy,
  CrossedDeploymentStrategy,
  CircularDeploymentStrategy,
  RandomDeploymentStrategy,
  FullMeshDeploymentStrategy,
)
from .vpn_keymat import CentralizedVpnKeyMaterial, P2PVpnKeyMaterial
from .vpn_config import UvnVpnConfig
from .dds import locate_rti_license
from .id_db import IdentityDatabase
from .keys_dds import DdsKeysBackend
from .database import Database
from .database_object import DatabaseObjectOwner
from ..core.exec import exec_command
from ..core.log import Logger as log


class Registry(Versioned):
  PROPERTIES = [
    "uvn_id",
    "deployment",
    "rti_license",
    "rekeyed_root",
  ]
  RO_PROPERTIES = [
    "uvn_id",
  ]
  REQ_PROPERTIES = RO_PROPERTIES
  SERIALIZED_PROPERTIES = [
    "uvn",
    "root_vpn_keymat",
    "particles_vpn_keymats",
    "backbone_vpn_keymat",
    "vpn_config",
  ]
  CACHED_PROPERTIES = [
    "uvn",
    "users",
  ]

  INITIAL_REKEYED_ROOT = False
  INITIAL_RTI_LICENSE = lambda self: self.root / "rti_license.dat"
  
  DB_TABLE = "registry"
  DB_TABLE_PROPERTIES = [
    "uvn_id",
    "deployment",
    "rekeyed_root",
  ]

  UVN_FILENAME = "uvn.yaml"
  CONFIG_FILENAME = "registry.yaml"
  AGENT_PACKAGE_FILENAME = "{}.uvn-agent"
  AGENT_CONFIG_FILENAME = "agent.yaml"

  @staticmethod
  def create(
      name: str,
      owner: str,
      password: str,
      root: Path | None = None,
      registry_config: dict | None = None):
    root = root or Path.cwd() / name
    log.activity(f"[REGISTRY] initializing UVN {name} in {root}")
    root_empty = next(root.glob("*"), None) is None
    if root.is_dir() and not root_empty:
      raise RuntimeError("target directory not empty", root)

    db = Database(root)
    db.initialize()

    owner_email, owner_name = User.parse_user_id(owner)
    owner = User(db=db,
      email=owner_email,
      name=owner_name,
      realm=name,
      password=password)
    uvn = Uvn(db=db, name=name)
    db.save_all([owner, uvn], chown={owner: [uvn]})
    registry = Registry(db=db, uvn_id=uvn.id)
    registry.configure(**registry_config)

    # Make sure we have an RTI license, since we're gonna need it later.
    if not registry.rti_license.is_file():
      rti_license = locate_rti_license(search_path=[registry.root])
      if not rti_license or not rti_license.is_file():
        log.error(f"[REGISTRY] RTI license not found, cell agents will not be available")
        raise RuntimeError("please specify an RTI license file")
      else:
        registry.rti_license = rti_license

    registry.generate()
    log.info(f"[REGISTRY] initialized UVN {registry.uvn.name}: {registry.root}")
    return registry


  @staticmethod
  def open(root: Path) -> "Registry":
    db = Database(root)
    return next(db.load(Registry, id=1))


  @property
  def root(self) -> Path:
    return self.db.root


  @property
  def id_db(self) -> IdentityDatabase:
    backend = self.deserialize_child(DdsKeysBackend, {
      "root": self.root / "id",
      "org": self.uvn.name,
      "generation_ts": self.uvn.generation_ts,
      "init_ts": self.uvn.init_ts,
    })
    return self.deserialize_child(IdentityDatabase, {
      "backend": backend,
      "local_id": self.uvn,
      "uvn": self.uvn,
    })


  @cached_property
  def vpn_config(self) -> UvnVpnConfig:
    return self.deserialize_child(UvnVpnConfig)


  @cached_property
  def root_vpn_keymat(self) -> CentralizedVpnKeyMaterial:
    return self.deserialize_child(CentralizedVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:root",
    })


  @cached_property
  def rekeyed_root_vpn_keymat(self) -> CentralizedVpnKeyMaterial:
    return self.deserialize_child(CentralizedVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:root",
      "prefer_dropped": True,
    })


  @cached_property
  def backbone_vpn_keymat(self) -> P2PVpnKeyMaterial:
    return self.deserialize_child(P2PVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:backbone",
    })


  @cached_property
  def particles_vpn_keymats(self) -> dict[int, CentralizedVpnKeyMaterial]:
    return {
      cell.id: self.deserialize_child(CentralizedVpnKeyMaterial, {
        "prefix": f"{self.uvn.name}:vpn:particles:{cell.id}",
      }) for cell in self.uvn.all_cells.values()
    }


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.uvn
    for u in self.users.values():
      yield u
    yield self.root_vpn_keymat
    for p in self.particles_vpn_keymats.values():
      yield p
    yield self.backbone_vpn_keymat
    # yield self.vpn_config


  def prepare_uvn_id(self, val: int) -> int:
    if not val:
      raise ValueError("invalid db id", val)
    return val


  def prepare_rti_license(self, val: str | Path) -> None:
    if val is not None and val != self.INITIAL_RTI_LICENSE():
      log.activity(f"[REGISTRY] caching RTI license: {val} → {self.rti_license}")
      exec_command(["cp", val, self.rti_license])
      self.rti_license.chmod(0o644)
      # Mark object updated since we're never actually updating the property
      self.updated_property("rti_license")
    return None


  def serialize_rti_license(self, val: Path) -> str:
    return str(val)


  def prepare_deployment(self, val: str | dict | P2PLinksMap) -> P2PLinksMap:
    return self.deserialize_child(P2PLinksMap, val)


  @cached_property
  def uvn(self) -> Uvn:
    return next(self.db.load(Uvn, id=self.uvn_id))


  @cached_property
  def users(self) -> dict[int, User]:
    return {
      user.id: user
        for user in self.db.load(User, where="realm = ?", params=(self.uvn.name,))
    }


  @property
  def deployed(self) -> bool:
    return self.deployment is not None


  @property
  def config_id(self) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(self.generation_ts.format().encode())
    return h.hexdigest()


  def save_rekeyed(self) -> None:
    self.root_vpn_keymat.clean_dropped_keys()
    self.rekeyed_root = False


  def configure(self, **config_args) -> None:
    super().configure(**config_args)
    if self.uvn.settings.backbone_vpn.changed_properties:
      self.updated_property("deployment_config")


  def load_cell(self, name: str) -> Cell:
    return next(self.db.load(Cell, where="name = ?", params=(name,)))


  def add_cell(self, name: str, owner: User | None=None, **cell_config) -> Cell:
    if owner is None:
      owner = self.uvn.owner
    # else:
    #   owner = self.load_user(owner)
    cell = self.db.new(Cell, owner=owner, uvn_id=self.uvn.id, name=name, **cell_config)
    self.uvn.updated_property("cell_properties")
    self.updated_property("deployment_config")
    log.info(f"[REGISTRY] new cell added to {self.uvn}: {cell}")
    return cell


  def update_cell(self, cell: Cell, owner: User|None=None, **config) -> None:
    if owner:
      cell.set_ownership(owner)
    cell.configure(**config)
    if {"address",} & cell.changed_properties:
      self.uvn.updated_property("cell_properties")
      self.updated_property("deployment_config")


  def delete_cell(self, cell: Cell) -> None:
    ask_yes_no(f"delete cell {cell.name} from uvn {self.uvn.name}?")
    self.particles_vpn_keymats[cell.id].drop_keys(delete=True)
    del self.particles_vpn_keymats[cell.id]
    self.db.delete(cell)
    self.uvn.updated_property("cell_properties")
    self.updated_property("deployment_config")
    log.info(f"[REGISTRY] cell deleted from uvn {self.uvn.name}: {cell}")


  def load_particle(self, name: str) -> Particle:
    return next(self.db.load(Particle, where="name = ?", params=(name,)))


  def add_particle(self, name: str, owner: User|None=None, **particle_config) -> Particle:
    if owner is None:
      owner = self.uvn.owner
    # else:
    #   owner = next(self.db.load(User, where=f"email = ?", params=[owner]))
    owner_id = owner.id
    particle = self.db.new(Particle, owner=owner, uvn_id=self.uvn.id, name=name, owner_id=owner_id, **particle_config)
    self.uvn.updated_property("particle_properties")
    log.info(f"[REGISTRY] new particle added to {self.uvn}: {particle}")
    return particle


  def update_particle(self, particle: Particle, owner: User|None=None, **config) -> None:
    if owner:
      particle.set_ownership(owner)
    particle.configure(config)
    self.db.save(particle)


  def delete_particle(self, particle: Particle) -> None:
    ask_yes_no(f"delete particle {particle.name} from uvn {self.uvn.name}?")
    self.db.delete(particle)
    self.uvn.updated_property("particle_properties")
    log.info(f"[REGISTRY] particle deleted from uvn {self.uvn.name}: {particle}")


  def load_user(self, email: str) -> User:
    return next(self.db.load(User, where="email = ?", params=[email]))


  def add_user(self, email: str, **user_args) -> User:
    user_args["realm"] = self.uvn.name
    user = self.db.new(User, email=email, **user_args)
    self.updated_property("users")
    log.info(f"[REGISTRY] new user added to {self.uvn}: {user}")
    return user


  def update_user(self, user: User, **config) -> None:
    user.configure(**config)


  def delete_user(self, user: User) -> None:
    if self.uvn in user.owned_uvns:
      raise ValueError("uvn owner cannot be deleted", self.uvn, user)
    owned_cells = [c for c in user.owned_cells if c.uvn == self.uvn]
    owned_particles = [p for p in user.owned_particles if p.uvn == self.uvn]
    
    if owned_cells or owned_particles:
      ask_yes_no(
        f"user {user.email} owns {len(owned_cells)} cells and {len(owned_particles)}." "\n"
        f"ownership for these elements will be transfered to {self.uvn.owner.email}." "\n"
        f"do you want to continue with the operation?")
    else:
      ask_yes_no(f"delete user {user}?")

    for owned in (*owned_cells, *owned_particles):
      owned.set_ownership(self.uvn.owner)

    self.db.delete(user)
    self.updated_property("users")
    log.info(f"[REGISTRY] user deleted from uvn {self.uvn.name}: {user}")


  def ban(self,
      targets: Iterable[Cell|Particle|User],
      banned: bool=False,
      unban_owned: bool=True) -> None:
    # Check that we are not trying to ban a uvn owner
    uvn_owners = [t
      for t in targets
      if isinstance(t, User)
        and next((o for o in t.owned if isinstance(o, Uvn)), None) is not None]
    if uvn_owners:
      raise ValueError("cannot ban/unban uvn owners", uvn_owners)

    collected_targets = set()
    for target in targets:
      if (banned or unban_owned) and isinstance(target, DatabaseObjectOwner):
        owned = [t
          for t in self.db.owned(target)
          if isinstance(t, (Cell, Particle))
            and t.excluded != banned]
      else:
        owned = set()
      if banned:
        msg = f"ban {target}"
      else:
        msg = f"unban {target}"
      if owned:
        msg += f" and {len(owned)} owned objects ({', '.join(map(str, owned))})"

      answer = ask_yes_no(msg)
      if not answer:
        continue
      collected_targets = collected_targets.union({*owned, target})

    modified_users = []
    modified_cells = []
    modified_particles = []
    for target in collected_targets:
      target.excluded = banned
      if "excluded" not in target.changed_properties:
        if isinstance(target, User):
          modified_users.append(target)
        elif isinstance(target, Cell):
          modified_cells.append(target)
        elif isinstance(target, Particle):
          modified_particles.append(target)

    if modified_cells:
      self.uvn.updated_property("cell_properties")
      self.updated_property("deployment_config")
    if modified_particles:
      self.uvn.updated_property("particle_properties")


  @property
  def needs_redeployment(self) -> None:
    return not self.deployed or "deployment_config" in self.changed_properties


  def redeploy(self, drop_keys: bool=True, backbone_vpn_settings: dict|None=None) -> None:
    if backbone_vpn_settings:
      self.uvn.settings.backbone_vpn.configure(**backbone_vpn_settings)
    log.activity("[REGISTRY] generating new backbone deployment")
    if drop_keys:
      self.backbone_vpn_keymat.drop_keys(delete=True)
    network_map = P2PLinkAllocationMap(
      subnet=self.uvn.settings.backbone_vpn.subnet)
    new_deployment =  self.deployment_strategy.deploy(network_map=network_map)
    if self.deployment is None:
      self.deployment = new_deployment
    else:
      self.deployment.peers = new_deployment.peers
    if self.deployment.peers:
      log.info(f"[REGISTRY] UVN backbone links updated [{self.deployment.generation_ts}]")
      self.uvn.log_deployment(self.deployment)
    elif len(self.uvn.cells) > 1:
      log.warning(f"[REGISTRY] UVN has {len(self.uvn.cells)} cells but no backbone links!")
    else:
      log.warning(f"[REGISTRY] UVN has no backbone")
    self.clear_changed(["deployment_config"])
    if drop_keys:
      self.db.save(self.backbone_vpn_keymat)


  def drop_particles_vpn_keymats(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for all particle vpns in uvn {self.uvn.name}?")
    log.warning(f"[REGISTRY] dropping all keys for Particle VPNs")
    for keymat in self.particles_vpn_keymats.values():
      keymat.drop_keys(delete=True)
    del self.particles_vpn_keymats


  def drop_root_vpn_keymat(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for the root vpn of uvn {self.uvn.name}?")
    log.warning(f"[REGISTRY] dropping existing keys for Root VPN")
    self.root_vpn_keymat.drop_keys()
    self.rekeyed_root = True


  def purge_keys(self) -> None:
    self.root_vpn_keymat.purge_gone_peers(list(self.uvn.all_cells), delete=True)

    for cell in self.uvn.all_cells.values():
      keymat = self.particles_vpn_keymats[cell.id]
      keymat.purge_gone_peers(list(self.uvn.all_particles), delete=True)
    
    if self.needs_redeployment:
      self.backbone_vpn_keymat.drop_keys(delete=True)


  def assert_keys(self) -> None:
    self.vpn_config.assert_keys()
    self.id_db.assert_keys()
    

  def generate(self) -> bool:
    # Save modified objects and log them for the user
    def _save() -> int:
      changed_elements_vals = dict(self.collect_changes())
      changed_elements = set(changed_elements_vals.keys())
      if len(changed_elements) > 0:
        log.activity("[REGISTRY] {} changed elements", len(changed_elements_vals))
        for ch, _ in changed_elements_vals.items():
          log.activity("[REGISTRY] - {}: [{}]", ch, ", ".join(sorted(ch.changed_properties)))
        # _log_changed(changed_elements_vals)
        self.db.save(self)
      return len(changed_elements)

    # Purge all keys that belong to deleted owners
    self.purge_keys()
    # Regenerate deployment configuration if needed
    if self.needs_redeployment:
      # Don't drop keys, since we already dropped them
      # as part of purge_keys()
      self.redeploy(drop_keys=False)
    changed_elements = _save()


    # Generate all missing keys 
    self.assert_keys()
    changed_elements += _save()

    changed = changed_elements > 0
    if not changed:
      log.activity("[REGISTRY] unchanged")
    return changed


  def rekey_uvn(self) -> None:
    ask_yes_no(f"drop and regenerate all vpn keys for uvn {self.uvn.name}?")
    self.root_vpn_keymat.drop_keys(delete=False)
    self.rekeyed_root = True
    for keymat in self.particles_vpn_keymats.values():
      keymat.drop_keys(delete=True)
    self.backbone_vpn_keymat.drop_keys(delete=True)


  def rekey_particle(self, particle: Particle, cells: Iterable[Cell]|None=None):
    if not cells:
      cells = list(self.uvn.cells.values())
      ask_yes_no(f"drop and regenerate vpn keys for particle {particle.name} of uvn {self.uvn.name} for cells {', '.join(c.name for c in cells)}?")
    else:
      ask_yes_no(f"drop and regenerate all vpn keys for particle {particle.name} of uvn {self.uvn.name}?")
    
    particles = list(p for p in self.uvn.all_particles if p != particle)
    for cell in cells:
      keymat = self.particles_vpn_keymats[cell.id]
      keymat.purge_gone_peers((p.id for p in particles), delete=True)
  

  def rekey_cell(self, cell: Cell, root_vpn: bool=False, particles_vpn: bool=False):
    if not (root_vpn or particles_vpn):
      raise RuntimeError("nothing to rekey")

    if root_vpn:
      ask_yes_no(f"drop and regenerate root vpn keys for cell {cell.name} of uvn {self.uvn.name}?")
    if particles_vpn:
      ask_yes_no(f"drop and regenerate all particle vpn keys for cell {cell.name} of uvn {self.uvn.name}?")

    cells = list(c for c in self.uvn.cells.values() if c != cell)
    if root_vpn:
      log.warning(f"[REGISTRY] dropping Root VPN key for cell: {cell}")
      self.root_vpn_keymat.purge_gone_peers((c.id for c in cells))
      self.rekeyed_root = True

    if particles_vpn:
      self.particles_vpn_keymats[cell.id].drop_keys(delete=True)


  @property
  def deployment_strategy(self) -> DeploymentStrategy:
    peers = set(self.uvn.cells)
    private_peers = set(c.id for c in self.uvn.cells.values() if not c.address)

    if self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CROSSED:
      strategy = self.new_child(CrossedDeploymentStrategy,
        peers=peers,
        private_peers=private_peers,
        args=self.uvn.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.RANDOM:
      strategy = self.new_child(RandomDeploymentStrategy,
        peers=peers,
        private_peers=private_peers,
        args=self.uvn.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CIRCULAR:
      strategy = self.new_child(CircularDeploymentStrategy,
        peers=peers,
        private_peers=private_peers,
        args=self.uvn.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.FULL_MESH:
      strategy = self.new_child(FullMeshDeploymentStrategy,
        peers=peers,
        private_peers=private_peers,
        args=self.uvn.settings.backbone_vpn.deployment_strategy_args)
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.STATIC:
      strategy = self.new_child(StaticDeploymentStrategy,
        peers=peers,
        private_peers=private_peers,
        args=self.uvn.settings.backbone_vpn.deployment_strategy_args)
    else:
      raise RuntimeError("unknown deployment strategy or invalid configuration", self.uvn.settings.backbone_vpn.deployment_strategy)

    log.activity(f"[REGISTRY] deployment strategy arguments:")
    log.activity(f"[REGISTRY] - strategy: {strategy}")
    log.activity(f"[REGISTRY] - public peers [{len(strategy.public_peers)}]: [{', '.join(map(str, map(self.uvn.cells.__getitem__, strategy.public_peers)))}]")
    log.activity(f"[REGISTRY] - private peers [{len(strategy.private_peers)}]: [{', '.join(map(str, map( self.uvn.cells.__getitem__, strategy.private_peers)))}]")
    log.activity(f"[REGISTRY] - extra args: {strategy.args}")
    return strategy

