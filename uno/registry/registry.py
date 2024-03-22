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
import hashlib

from ..core.ask import ask_yes_no

from .uvn import Uvn
from .cell import Cell
from .particle import Particle
from .user import User
from .versioned import Versioned, noop_if_readonly, disabled_if_readonly

from .deployment import (
  P2pLinksMap,
  P2pLinkAllocationMap,
  DeploymentStrategy,
  DeploymentStrategyKind,
  StaticDeploymentStrategy,
  CrossedDeploymentStrategy,
  CircularDeploymentStrategy,
  RandomDeploymentStrategy,
  FullMeshDeploymentStrategy,
)
from .vpn_keymat import CentralizedVpnKeyMaterial, P2pVpnKeyMaterial
from .vpn_config import UvnVpnConfig
from .dds import locate_rti_license
from .id_db import IdentityDatabase
from .keys_backend_dds import DdsKeysBackend
from .database import Database
from .database_object import DatabaseObjectOwner, inject_db_cursor
from .agent_config import AgentConfig
from .package import Packager

from ..core.exec import exec_command


class Registry(Versioned):
  PROPERTIES = [
    "uvn_id",
    "deployment",
    "rti_license",
    "rekeyed_root_config_id",
    "config_id",
  ]
  STR_PROPERTIES = [
    "uvn_id"
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
    # "vpn_config",
    "config_id",
  ]
  PROPERTY_GROUPS = {
    "users": ["config_id"],
    "particles": [
      "config_id",
      "particles_vpn_keymats",
    ],
    "cells": [
      "config_id",
      "deployment_config",
      "root_vpn_keymat",
      "backbone_vpn_keymat",
      "particles_vpn_keymats",
    ]
  }
  CACHED_PROPERTIES = [
    "uvn",
    "users",
    "config_id",
    "rekeyed_root_vpn_keymat",
    "root_vpn_keymat",
    "backbone_vpn_keymat",
    "particles_vpn_keymats",
  ]
  INITIAL_RTI_LICENSE = lambda self: self.root / "rti_license.dat"
  INITIAL_CONFIG_ID = lambda self: self.generate_config_id()

  DB_TABLE = "registry"
  DB_TABLE_PROPERTIES = [
    "uvn_id",
    "deployment",
    "rekeyed_root_config_id",
    "config_id",
  ]

  UVN_FILENAME = "uvn.yaml"
  CONFIG_FILENAME = "registry.yaml"
  AGENT_PACKAGE_FILENAME = "{}.uvn-agent"
  AGENT_CONFIG_FILENAME = "agent.yaml"


  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.readonly = not isinstance(self.local_object, Uvn)


  @classmethod
  def create(cls,
      name: str,
      owner: str,
      password: str,
      root: Path | None = None,
      registry_config: dict | None = None):
    root = root or Path.cwd() / name
    cls.log.activity("initializing UVN {} in {}", name, root)
    root_empty = next(root.glob("*"), None) is None
    if root.is_dir() and not root_empty:
      raise RuntimeError("target directory not empty", root)

    db = Database(root, create=True)
    db.initialize()

    owner_email, owner_name = User.parse_user_id(owner)
    owner = db.new(User, {
      "email": owner_email,
      "name": owner_name,
      "realm": name,
      "password": password,
    })
    uvn = db.new(Uvn, {"name": name}, owner=owner)
    # db.save_all([owner, uvn], chown={owner: [uvn]})
    registry = db.new(Registry, {"uvn_id": uvn.id}, save=False)
    registry.configure(**registry_config)

    # Make sure we have an RTI license, since we're gonna need it later.
    if not registry.rti_license.is_file():
      rti_license = locate_rti_license(search_path=[registry.root])
      if not rti_license or not rti_license.is_file():
        raise RuntimeError("please specify an RTI license file")
      else:
        registry.rti_license = rti_license

    registry.generate_artifacts()
    registry.log.info("initialized UVN {}: {}", registry.uvn.name, registry.root)
    return registry


  @staticmethod
  def open(root: Path, readonly: bool=False) -> "Registry":
    db = Database(root)
    return next(db.load(Registry, load_args={
      "readonly": readonly if readonly else None,
    }, id=1))


  @property
  def root(self) -> Path:
    return self.db.root


  @cached_property
  @inject_db_cursor
  def local_object(self, cursor: Database.Cursor) -> Uvn|Cell:
    # Read id.yaml to determine the owner
    id_file = self.root / "id.yaml"
    if id_file.exists():
      self.log.debug("loading identity marker: {}", id_file)
      id_cfg = self.yaml_load(id_file.read_text())
      owner = self.db.load_object_id(id_cfg["owner"], cursor=cursor)
    else:
      self.log.debug("identity marker not found: {}", id_file)
      owner = self.uvn
    return owner


  @property
  def cells_dir(self) -> Path:
    return self.root / "cells"


  @property
  def particles_dir(self) -> Path:
    return self.root / "particles"


  @property
  def id_db(self) -> IdentityDatabase:
    backend = self.new_child(DdsKeysBackend, {
      "root": self.root / "id",
      "org": self.uvn.name,
    })
    return self.new_child(IdentityDatabase, {
      "registry": self,
      "backend": backend,
    })


  @cached_property
  def vpn_config(self) -> UvnVpnConfig:
    return self.new_child(UvnVpnConfig)


  @cached_property
  def root_vpn_keymat(self) -> CentralizedVpnKeyMaterial:
    return self.new_child(CentralizedVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:root",
      "peer_ids": [c.id for c in self.uvn.cells.values()],
    })


  @cached_property
  def rekeyed_root_vpn_keymat(self) -> CentralizedVpnKeyMaterial:
    return self.new_child(CentralizedVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:root",
      "peer_ids": [c.id for c in self.uvn.cells.values()],
      "prefer_dropped": True,
      "readonly": True,
    })


  @cached_property
  def backbone_vpn_keymat(self) -> P2pVpnKeyMaterial:
    return self.new_child(P2pVpnKeyMaterial, {
      "prefix": f"{self.uvn.name}:vpn:backbone",
    })


  @cached_property
  def particles_vpn_keymats(self) -> dict[int, CentralizedVpnKeyMaterial]:
    return {
      cell.id: self.new_child(CentralizedVpnKeyMaterial, {
        "prefix": f"{self.uvn.name}:vpn:particles:{cell.id}",
        "peer_ids": [p.id for p in self.uvn.particles.values()],
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
      self.log.activity("caching RTI license: {} → {}", val, self.rti_license)
      exec_command(["cp", "-v", val, self.rti_license])
      self.rti_license.chmod(0o644)
      # Mark object updated since we're never actually updating the property
      self.updated_property("rti_license")
    return None


  def serialize_rti_license(self, val: Path, public: bool=False) -> str:
    return str(val)


  def prepare_deployment(self, val: str | dict | P2pLinksMap) -> P2pLinksMap:
    return self.new_child(P2pLinksMap, val)


  @cached_property
  @inject_db_cursor
  def uvn(self, cursor: Database.Cursor) -> Uvn:
    return next(self.db.load(Uvn, id=self.uvn_id, cursor=cursor))


  @cached_property
  @inject_db_cursor
  def users(self, cursor: Database.Cursor) -> dict[int, User]:
    return {
      user.id: user
        for user in self.db.load(User, where="realm = ?", params=(self.uvn.name,), cursor=cursor)
    }


  @property
  def deployed(self) -> bool:
    return self.deployment is not None


  # @cached_property
  def generate_config_id(self) -> str:
    h = hashlib.sha256()
    h.update(self.generation_ts.format().encode())
    for n in sorted(self.nested, key=lambda n: str(n.id)):
      h.update(n.generation_ts.format().encode())
    return h.hexdigest()


  def save_rekeyed(self) -> None:
    self.root_vpn_keymat.clean_dropped_keys()
    self.rekeyed_root_config_id = None
    self.reset_cached_properties()


  def configure(self, **config_args) -> None:
    super().configure(**config_args)
    if self.uvn.settings.backbone_vpn.changed_properties:
      self.updated_property("deployment_config")


  @inject_db_cursor
  def load_cell(self, name: str, cursor: Database.Cursor) -> Cell:
    return next(self.db.load(Cell, where="name = ?", params=(name,), cursor=cursor))


  @disabled_if_readonly
  def add_cell(self, name: str, owner: User | None=None, **cell_config) -> Cell:
    if owner is None:
      owner = self.uvn.owner

    cell = self.uvn.new_child(Cell, {
      "uvn_id": self.uvn.id,
      "name": name,
      **cell_config,
    }, owner=owner)

    self.uvn.updated_property("cell_properties")
    self.updated_property("cells")
    self.log.info("new cell added to uvn {}: {}", self.uvn, cell)
    return cell


  @noop_if_readonly(None)
  def update_cell(self, cell: Cell, owner: User|None=None, **config) -> None:
    if owner:
      cell.set_ownership(owner)
    cell.configure(**config)
    if cell.dirty:
      self.uvn.updated_property("cell_properties")
      self.updated_property("cells")


  @disabled_if_readonly
  def delete_cell(self, cell: Cell) -> None:
    ask_yes_no(f"delete cell {cell.name} from uvn {self.uvn.name}?")
    self.particles_vpn_keymats[cell.id].drop_keys(delete=True)
    del self.particles_vpn_keymats[cell.id]
    self.db.delete(cell)
    self.uvn.updated_property("cell_properties")
    self.updated_property("cells")
    self.log.info("cell deleted from uvn {}: {}", self.uvn, cell)


  @inject_db_cursor
  def load_particle(self, name: str, cursor: Database.Cursor) -> Particle:
    return next(self.db.load(Particle, where="name = ?", params=(name,), cursor=cursor))


  @disabled_if_readonly
  def add_particle(self, name: str, owner: User|None=None, **particle_config) -> Particle:
    if owner is None:
      owner = self.uvn.owner
    particle = self.uvn.new_child(Particle, {
      "uvn_id": self.uvn.id,
      "name": name,
      **particle_config,
    }, owner=owner)
    self.uvn.updated_property("particle_properties")
    self.updated_property("particles")
    self.log.info("new particle added to {}: {}", self.uvn, particle)
    return particle


  @noop_if_readonly(None)
  def update_particle(self, particle: Particle, owner: User|None=None, **config) -> None:
    if owner:
      particle.set_ownership(owner)
    particle.configure(config)
    if particle.dirty:
      self.updated_property("particles")
    self.db.save(particle)


  @disabled_if_readonly
  def delete_particle(self, particle: Particle) -> None:
    ask_yes_no(f"delete particle {particle.name} from uvn {self.uvn.name}?")
    self.db.delete(particle)
    self.uvn.updated_property("particle_properties")
    self.updated_property("particles")
    self.log.info("particle deleted from uvn {}: {}", self.uvn, particle)


  @inject_db_cursor
  def load_user(self, email: str, cursor: Database.Cursor) -> User:
    return next(self.db.load(User, where="email = ?", params=[email], cursor=cursor))


  @disabled_if_readonly
  def add_user(self, email: str, **user_args) -> User:
    user_args["realm"] = self.uvn.name
    user = self.new_child(User, {
      "email": email,
      **user_args,
    })
    self.updated_property("users")
    self.log.info("new user added to uvn {}: {}", self.uvn, user)
    return user


  @noop_if_readonly(None)
  def update_user(self, user: User, **config) -> None:
    user.configure(**config)
    if user.dirty:
      self.updated_property("users")


  @disabled_if_readonly
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
    self.log.info("user deleted from uvn {}: {}", self.uvn, user)


  @disabled_if_readonly
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
      self.updated_property("cells")
    if modified_particles:
      self.uvn.updated_property("particle_properties")
      self.updated_property("particles")
    if modified_users:
      self.updated_property("users")


  @property
  def needs_redeployment(self) -> None:
    return not self.deployed or "deployment_config" in self.changed_properties


  @noop_if_readonly(None)
  def redeploy(self, drop_keys: bool=True, backbone_vpn_settings: dict|None=None) -> None:
    if backbone_vpn_settings:
      self.uvn.settings.backbone_vpn.configure(**backbone_vpn_settings)
    self.log.activity("generating new backbone deployment")
    if drop_keys:
      self.backbone_vpn_keymat.drop_keys(delete=True)
    network_map = P2pLinkAllocationMap(
      subnet=self.uvn.settings.backbone_vpn.subnet)
    new_deployment =  self.deployment_strategy.deploy(network_map=network_map)
    self.deployment = new_deployment
    if self.deployment.peers:
      self.log.info("UVN backbone links updated [{}]", self.deployment.generation_ts)
      self.uvn.log_deployment(self.deployment)
    elif len(self.uvn.cells) > 1:
      self.log.warning("UVN has {} cells but no backbone links!", len(self.uvn.cells))
    else:
      self.log.debug("UVN has no backbone")
    self.clear_changed(["deployment_config"])
    if drop_keys:
      self.db.save(self.backbone_vpn_keymat)
    self.updated_property("config_id")


  def drop_particles_vpn_keymats(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for all particle vpns in uvn {self.uvn.name}?")
    self.log.warning("dropping all keys for Particle VPNs")
    for keymat in self.particles_vpn_keymats.values():
      keymat.drop_keys(delete=True)
    del self.particles_vpn_keymats
    self.updated_property("config_id")


  def drop_root_vpn_keymat(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for the root vpn of uvn {self.uvn.name}?")
    self.log.warning("dropping existing keys for Root VPN")
    if self.rekeyed_root_config_id is None:
      self.rekeyed_root_config_id = self.config_id
    self.root_vpn_keymat.drop_keys()
    self.updated_property("config_id")


  @noop_if_readonly(None)
  def purge_keys(self) -> None:
    self.root_vpn_keymat.purge_gone_peers(list(self.uvn.all_cells), delete=True)

    for cell in self.uvn.all_cells.values():
      keymat = self.particles_vpn_keymats[cell.id]
      keymat.purge_gone_peers(list(self.uvn.all_particles), delete=True)
    
    if self.needs_redeployment:
      self.backbone_vpn_keymat.drop_keys(delete=True)


  @noop_if_readonly(None)
  def assert_keys(self) -> None:
    self.vpn_config.assert_keys()
    self.id_db.assert_keys()
    

  @noop_if_readonly(None)
  def generate_artifacts(self, force: bool=False) -> bool:
    # Save modified objects and log them for the user
    def _save() -> int:
      self.log.trace("checking modified elements:")
      changed_elements_vals = dict(self.collect_changes())
      changed_elements = set(changed_elements_vals.keys())
      if len(changed_elements) > 0:
        self.log.activity("{} changed elements", len(changed_elements_vals))
        for ch, _ in changed_elements_vals.items():
          self.log.activity("- {}: [{}]", ch, ", ".join(sorted(ch.changed_properties)))
        # _log_changed(changed_elements_vals)
      else:
        self.log.debug("nothing changed in {}", self)
      self.config_id = self.generate_config_id()
      self.db.save(self, dirty=not force)
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
    if not changed and not force:
      self.log.info("unchanged")
      return False

    for cell in self.uvn.cells.values():
      Packager.generate_cell_agent_package(self, cell, self.cells_dir)

    for particle in self.uvn.particles.values():
      Packager.generate_particle_package(self, particle, self.particles_dir)

    self.log.info("updated")
    return True



  def rekey_uvn(self) -> None:
    ask_yes_no(f"drop and regenerate all vpn keys for uvn {self.uvn.name}?")
    if self.rekeyed_root_config_id is None:
      self.rekeyed_root_config_id = self.config_id
    self.root_vpn_keymat.drop_keys(delete=False)
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
      self.log.warning("dropping Root VPN key for cell: {}", cell)
      if self.rekeyed_root_config_id is None:
        self.rekeyed_root_config_id = self.config_id
      self.root_vpn_keymat.purge_gone_peers((c.id for c in cells))

    if particles_vpn:
      self.particles_vpn_keymats[cell.id].drop_keys(delete=True)


  @property
  def deployment_strategy(self) -> DeploymentStrategy:
    peers = set(self.uvn.cells)
    private_peers = set(c.id for c in self.uvn.cells.values() if not c.address)

    if self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CROSSED:
      strategy = self.new_child(CrossedDeploymentStrategy,{
        "peers": peers,
        "private_peers": private_peers,
        "args": self.uvn.settings.backbone_vpn.deployment_strategy_args
      })
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.RANDOM:
      strategy = self.new_child(RandomDeploymentStrategy, {
        "peers": peers,
        "private_peers": private_peers,
        "args": self.uvn.settings.backbone_vpn.deployment_strategy_args
      })
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.CIRCULAR:
      strategy = self.new_child(CircularDeploymentStrategy, {
        "peers": peers,
        "private_peers": private_peers,
        "args": self.uvn.settings.backbone_vpn.deployment_strategy_args
      })
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.FULL_MESH:
      strategy = self.new_child(FullMeshDeploymentStrategy, {
        "peers": peers,
        "private_peers": private_peers,
        "args": self.uvn.settings.backbone_vpn.deployment_strategy_args
      })
    elif self.uvn.settings.backbone_vpn.deployment_strategy == DeploymentStrategyKind.STATIC:
      strategy = self.new_child(StaticDeploymentStrategy, {
        "peers": peers,
        "private_peers": private_peers,
        "args": self.uvn.settings.backbone_vpn.deployment_strategy_args
      })
    else:
      raise RuntimeError("unknown deployment strategy or invalid configuration", self.uvn.settings.backbone_vpn.deployment_strategy)

    self.log.activity("deployment strategy arguments:")
    self.log.activity("- strategy: {}", strategy)
    self.log.activity("- public peers [{}]: [{}]",
      len(strategy.public_peers),
      ', '.join(map(str, map(self.uvn.cells.__getitem__, strategy.public_peers))))
    self.log.activity("- private peers [{}]: [{}]",
      len(strategy.private_peers),
      ', '.join(map(str, map( self.uvn.cells.__getitem__, strategy.private_peers))))
    self.log.activity("- extra args: {}", strategy.args)
    return strategy


  def export_cell_database(self, db: "Database", cell: Cell) -> None:
    self.db.export_tables(db, [Uvn, Cell, Particle, User, Registry])
    priv_keymat = [
      *self.root_vpn_keymat.get_peer_material(cell.id, private=True),
      *self.backbone_vpn_keymat.get_peer_material(cell.id, private=True),
      *self.particles_vpn_keymats[cell.id].get_peer_material(0, private=True),
    ]
    self.log.activity("exporting {} private keys for {}", len(priv_keymat), cell)
    for k in priv_keymat:
      self.log.activity("- {}", k)
    self.db.export_objects(db, priv_keymat)

    pub_keymat = [
      *self.root_vpn_keymat.get_peer_material(cell.id),
      *self.particles_vpn_keymats[cell.id].get_peer_material(0),
      *self.backbone_vpn_keymat.get_peer_material(cell.id),
    ]
    self.log.activity("exporting {} public keys for {}", len(pub_keymat), cell)
    for k in pub_keymat:
      self.log.activity("- {}", k)
    self.db.export_objects(db, pub_keymat, public=True)
    agent_config = self.cell_agent_configs[cell.id]
    db.save(agent_config, dirty=False, force_insert=True)


  @property
  def registry_agent_config(self) -> AgentConfig:
    return self.assert_agent_config(self.uvn)


  @property
  def cell_agent_configs(self) -> set[AgentConfig]:
    return {
      cell.id: self.assert_agent_config(cell)
        for cell in self.uvn.cells.values()
    }


  def assert_agent_config(self, owner: Uvn|Cell) -> AgentConfig:
    def _assert_agent_config(owner: Uvn|Cell, init_args: dict, **search_args) -> AgentConfig:
      existing = self.load_child(AgentConfig, **search_args)
      if existing:
        return existing
      if self.readonly:
        raise RuntimeError("missing agent configuration", owner)
      return self.new_child(AgentConfig, {
        "registry_id": self.config_id,
        "deployment": self.deployment,
        **init_args,
      }, owner=owner)

    if isinstance(owner, Cell):
      cell = owner
      return _assert_agent_config(cell, {
        "root_vpn_config": self.vpn_config.root_vpn.peer_config(cell.id),
        "particles_vpn_config": self.vpn_config.particles_vpn(cell),
        "backbone_vpn_config": self.vpn_config.backbone_vpn.peer_config(cell.id),
        "enable_router": True,
        "enable_httpd": True,
        "enable_peers_tester": True,
      },
      where="owner_id = ? AND registry_id = ?",
      params=(self.json_dump(cell.object_id), self.config_id,))
    else:
      assert(isinstance(owner, Uvn))
      return _assert_agent_config(self.uvn, {
        "registry_id": self.config_id,
        "deployment": self.deployment,
        "root_vpn_config": self.vpn_config.root_vpn.root_config,
      },
      where="owner_id = ? AND registry_id = ?",
      params=(self.json_dump(self.uvn.object_id), self.config_id,))

