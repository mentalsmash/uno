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
from ..core.time import Timestamp
from ..core.render import Templates

from .uvn import Uvn
from .cell import Cell
from .particle import Particle
from .user import User
from .versioned import Versioned, disabled_if, error_if

from .deployment import P2pLinksMap, P2pLinkAllocationMap
from .deployment_strategy import DeploymentStrategy
from .vpn_keymat import CentralizedVpnKeyMaterial, P2pVpnKeyMaterial
from .vpn_config import UvnVpnConfig
from .id_db import IdentityDatabase
from .keys_backend_dds import DdsKeysBackend
from .database import Database
from .database_object import DatabaseObjectOwner, OwnableDatabaseObject, inject_db_cursor, inject_db_transaction, TransactionHandler
from .agent_config import AgentConfig
from .package import Packager
from .wg_key import WireGuardKeyPair, WireGuardPsk
from .cloud import CloudProvider, CloudStorageFileType, CloudStorageFile

from ..middleware import Middleware

from ..core.exec import exec_command
from ..core.wg import WireGuardConfig


class Registry(Versioned):
  PROPERTIES = [
    "uvn_id",
    "deployment",
    "rti_license",
    "rekeyed_root_config_id",
    "config_id",
    "cloud_provider",
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
    "users",
  ]
  VOLATILE_PROPERTIES = [
    "cloud_provider",
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
    "agent_configs",
    # "strategy",
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
  DB_IMPORT_DROPS_EXISTING = True


  def __init__(self, **properties) -> None:
    super().__init__(**properties)


  def load_nested(self) -> None:
    if not self.readonly:
      self.readonly = not isinstance(self.local_id[0], Uvn)


  @classmethod
  def create(cls,
      name: str,
      owner: str,
      password: str,
      root: Path | None = None,
      registry_config: dict | None = None,
      uvn_spec: dict|None=None):
    root = root or Path.cwd() / name
    cls.log.activity("initializing UVN {} in {}", name, root)
    root_empty = next(root.glob("*"), None) is None
    if root.is_dir() and not root_empty:
      raise RuntimeError("target directory not empty", root)

    db = Database(root, create=True)

    owner_email, owner_name = User.parse_user_id(owner)
    owner = db.new(User, {
      "email": owner_email,
      "name": owner_name,
      "realm": name,
      "password": password,
    })
    uvn = db.new(Uvn, {"name": name}, owner=owner)
    # db.save_all([owner, uvn], chown={owner: [uvn]})
    registry = db.new(Registry, {
      "uvn_id": uvn.id,
      # **registry_config,
    }, save=False)
    if registry_config:
      registry.configure(**registry_config)
    registry.generate_artifacts()
    registry.log.info("initialized UVN {}: {}", registry.uvn.name, registry.root)
    if uvn_spec is not None:
      registry.define_uvn(uvn_spec)
      if registry.dirty:
        registry.generate_artifacts()

    return registry


  @classmethod
  def open(cls, root: Path | None = None, readonly: bool=False, db: "Database|None"=None) -> "Registry":
    if db is None:
      db = Database(root)
    return next(db.load(Registry, load_args={
      "readonly": readonly if readonly else None,
    }, id=1))


  @classmethod
  def load_local_id(cls, root: Path) -> tuple[tuple[str, object], str] | None:
    # Read id.yaml to determine the owner
    id_file = root / "id.yaml"
    if not id_file.exists():
      cls.log.debug("identity marker not found: {}", id_file)
      return (None, None)
    cls.log.debug("loading identity marker: {}", id_file)
    id_cfg = cls.yaml_load(id_file.read_text())
    return (id_cfg["owner"], id_cfg["config_id"])


  @classmethod
  def is_uno_directory(cls, root: Path) -> bool:
    # For now we just check if there is a database file
    return (root / Database.DB_NAME).exists()


  @cached_property
  @inject_db_cursor
  def local_id(self, cursor: Database.Cursor) -> tuple[Uvn|Cell, str]:
    owner_id, config_id = self.load_local_id(self.root)
    if config_id is None:
      owner = self.uvn
      config_id = self.config_id
    else:
      owner = self.db.load_object_id(owner_id, cursor=cursor)
    return (owner, config_id)


  @cached_property
  def middleware(self) -> Middleware:
    return Middleware.load()


  @property
  def root(self) -> Path:
    return self.db.root


  @property
  def cells_dir(self) -> Path:
    return self.root / "cells"


  @property
  def particles_dir(self) -> Path:
    return self.root / "particles"


  @cached_property
  def id_db(self) -> IdentityDatabase:
    backend = self.new_child(DdsKeysBackend, {
      "root": self.root / "id",
      "org": self.uvn.name,
    })
    return self.new_child(IdentityDatabase, {
      "registry": self,
      "backend": backend,
    })


  # @cached_property
  @property
  def vpn_config(self) -> UvnVpnConfig:
    return self.new_child(UvnVpnConfig)


  def root_vpn_config(self, owner: Uvn|Cell) -> WireGuardConfig:
    if isinstance(owner, Uvn):
      # Use the older, "rekeyed", root vpn configuration if available.
      # The agent will switch to the newer one after cells have received the update.
      if self.vpn_config.rekeyed_root_vpn is not None:
        self.log.warning("loading rekeyed root VPN configuration: {}", self.rekeyed_root_config_id)
        vpn_config = self.vpn_config.rekeyed_root_vpn.root_config
      else:
        vpn_config = self.vpn_config.root_vpn.root_config
    elif self.vpn_config.root_vpn is not None:
      vpn_config = self.vpn_config.root_vpn.peer_config(owner.id)
    return vpn_config


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


  @cached_property
  def agent_configs(self) -> dict[int, AgentConfig]:
    configs = {
      c.id: c
      for c in self.load_children(AgentConfig,
        where="config_id = ?", params=(self.config_id,))
    }
    return configs


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


  def prepare_deployment(self, val: str | dict | P2pLinksMap) -> P2pLinksMap:
    return self.deployment_strategy.new_child(P2pLinksMap, val)


  @classmethod
  def load_cloud_provider(cls, svc_class: str, db: Database | None = None, **storage_config) -> CloudProvider:
    provider_cls = CloudProvider.Plugins[svc_class]
    return db.new(provider_cls, {
      **storage_config,
      "root": db.root / "cloud" / provider_cls.svc_class(),
    }, save=False)


  # Disable function on cells, since we are not propagating the state
  @disabled_if(lambda self, *a, **kw: not isinstance(self.local_id[0], Uvn))
  def prepare_cloud_provider(self, val: str | dict | CloudProvider) -> CloudProvider | None:
    if isinstance(val, CloudProvider):
      return val
    if isinstance(val, str):
      val = self.yaml_load(str)
    provider_class = val["class"].lower()
    provider_args = val["args"] or {}
    return self.load_cloud_provider(provider_class, db=self.db, **provider_args)


  def serialize_cloud_provider(self, val: CloudProvider | None) -> dict | None:
    if val is None:
      return None
    return {
      "class": val.svc_class(),
      "args": val.serialize(),
    }


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


  @cached_property
  def active_users(self) -> dict[int, User]:
    return {u.id: u for u in self.users.values() if not u.excluded}


  @property
  def deployed(self) -> bool:
    return self.deployment is not None


  def generate_config_id(self) -> str:
    h = hashlib.sha256()
    h.update(self.generation_ts.format().encode())
    for n in sorted(self.nested, key=lambda n: str(n.id)):
      h.update(n.generation_ts.format().encode())
    return h.hexdigest()


  def drop_rekeyed(self) -> None:
    self.root_vpn_keymat.clean_dropped_keys()
    self.rekeyed_root_config_id = None
    # self.reset_cached_properties()


  def configure(self, **config_args) -> set[str]:
    configured = super().configure(**config_args)
    if self.uvn.settings.deployment.changed_properties:
      self.updated_property("deployment_config")
    return configured


  @inject_db_cursor
  def load_cell(self, name: str, cursor: Database.Cursor) -> Cell:
    return next(self.db.load(Cell, where="name = ?", params=(name,), cursor=cursor))


  @disabled_if("readonly", error=True)
  def define_uvn(self, uvn_spec: dict) -> None:
    uvn_config = uvn_spec.get("config")
    if uvn_config:
      self.uvn.configure(**uvn_config)
    for cfg in uvn_spec.get("user", []):
      user = self.add_user(
        email=cfg["email"],
        password=cfg["password"],
        **cfg.get("config", {}))
    for cfg in uvn_spec.get("cells", []):
      owner = cfg.get("owner")
      if owner:
        owner = self.load_user(owner)
      cell = self.add_cell(
        name=cfg["name"],
        owner=owner,
        address=cfg.get("address"),
        allowed_lans=cfg.get("allowed_lans"),
        settings=cfg.get("settings"))
    for cfg in uvn_spec.get("particles", []):
      owner = cfg.get("owner")
      if owner:
        owner = self.load_user(owner)
      particle = self.add_particle(
        name=cfg["name"],
        owner=owner,
        **cfg.get("config", {}))


  @disabled_if("readonly", error=True)
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
    self.log.info("new cell added to {}: {}", self.uvn, cell)
    return cell


  @disabled_if("readonly")
  def update_cell(self, cell: Cell, owner: User|None=None, **config) -> None:
    if owner:
      cell.set_ownership(owner)
    cell.configure(**config)
    if cell.dirty:
      self.uvn.updated_property("cell_properties")
      self.updated_property("cells")
    # self.db.save(cell)


  @error_if("readonly")
  @inject_db_transaction
  def delete_cell(self,
      cell: Cell,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    def _delete():
      ask_yes_no(f"delete cell {cell.name} from {self.uvn}?")
      self.rekey_cell(cell, deleted=True, cursor=cursor)
      self.db.delete(cell, cursor=cursor)
      self.uvn.updated_property("cell_properties")
      self.updated_property("cells")
      self.log.info("cell deleted from {}: {}", self.uvn, cell)
    return do_in_transaction(_delete)


  @inject_db_cursor
  def load_particle(self, name: str, cursor: Database.Cursor) -> Particle:
    return next(self.db.load(Particle, where="name = ?", params=(name,), cursor=cursor))


  @error_if("readonly")
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


  @disabled_if("readonly")
  def update_particle(self, particle: Particle, owner: User|None=None, **config) -> None:
    if owner:
      particle.set_ownership(owner)
    particle.configure(config)
    if particle.dirty:
      self.updated_property("particles")
    # self.db.save(particle)


  @error_if("readonly")
  @inject_db_transaction
  def delete_particle(self,
      particle: Particle,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    ask_yes_no(f"delete particle {particle.name} from {self.uvn}?")
    def _delete():
      self.rekey_particle(particle, deleted=True, cursor=cursor)
      self.db.delete(particle, cursor=cursor)
      self.uvn.updated_property("particle_properties")
      self.updated_property("particles")
      self.log.info("particle deleted from {}: {}", self.uvn, particle)
    return do_in_transaction(_delete)


  @inject_db_cursor
  def load_user(self, email: str, cursor: Database.Cursor) -> User:
    return next(self.db.load(User, where="email = ?", params=[email], cursor=cursor))


  @error_if("readonly")
  def add_user(self, email: str, **user_args) -> User:
    user_args["realm"] = self.uvn.name
    user = self.new_child(User, {
      "email": email,
      **user_args,
    })
    self.updated_property("users")
    self.log.info("new user added to {}: {}", self.uvn, user)
    return user


  @disabled_if("readonly")
  def update_user(self, user: User, **config) -> None:
    user.configure(**config)
    if user.dirty:
      self.updated_property("users")
    # self.db.save(user)


  @error_if("readonly")
  @inject_db_transaction
  def delete_user(self,
      user: User,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    def _delete():
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

      self.db.delete(user, cursor=cursor)
      self.updated_property("users")
      self.log.info("user deleted from {}: {}", self.uvn, user)

    return do_in_transaction(_delete)


  @error_if("readonly")
  @inject_db_transaction
  def ban(self,
      targets: Iterable[Cell|Particle|User],
      banned: bool=False,
      unban_owned: bool=True,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    def _ban():
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
            for t in target.owned
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

        answer = ask_yes_no(msg, return_answer=True)
        if not answer:
          continue
        collected_targets = collected_targets.union({*owned, target})

      modified_users = []
      modified_cells = []
      modified_particles = []
      modified_other = []
      for target in collected_targets:
        target.excluded = banned
        if "excluded" in target.changed_properties:
          assert(target.dirty)
          if isinstance(target, User):
            modified_users.append(target)
          elif isinstance(target, Cell):
            modified_cells.append(target)
          elif isinstance(target, Particle):
            modified_particles.append(target)
          else:
            modified_other.append(target)
          if banned:
            self.log.warning("banned: {}", target)
          else:
            self.log.warning("unbanned: {}", target)
        else:
          self.log.info("already {}: {}", "banned" if banned else "unbanned", target)


      # all_modified = {
      #   *modified_cells,
      #   *modified_particles,
      #   *modified_users,
      #   *modified_other,
      # }
      # self.db.save_all(all_modified, cursor=cursor)

      if modified_cells:
        self.db.save_all(modified_cells, cursor=cursor)
        self.uvn.updated_property("cell_properties")
        self.updated_property("cells")
      if modified_particles:
        self.db.save_all(modified_particles, cursor=cursor)
        self.uvn.updated_property("particle_properties")
        self.updated_property("particles")
      if modified_users:
        self.db.save_all(modified_users, cursor=cursor)
        self.updated_property("users")
      if modified_other:
        self.db.save_all(modified_other, cursor=cursor)
    
    return do_in_transaction(_ban)


  @property
  def needs_redeployment(self) -> None:
    return not self.deployed or "deployment_config" in self.changed_properties


  @disabled_if("readonly")
  def redeploy(self) -> None:
    self.log.activity("generating new backbone deployment")
    new_deployment =  self.deployment_strategy.deploy(
      peers=set(self.uvn.cells),
      private_peers=set(c.id for c in self.uvn.cells.values() if not c.address),
      args=self.uvn.settings.deployment.strategy_args,
      network_map=P2pLinkAllocationMap(subnet=self.uvn.settings.backbone_vpn.subnet))
    self.deployment = new_deployment
    if self.deployment.peers:
      self.log.warning("UVN backbone links updated [{}]", self.deployment.generation_ts)
      self.uvn.log_deployment(self.deployment)
    elif len(self.uvn.cells) > 1:
      self.log.warning("UVN has {} cells but no backbone links!", len(self.uvn.cells))
    else:
      self.log.info("UVN has no backbone")
    # self.clear_changed(["deployment_config"])
    self.updated_property("config_id")


  def drop_particles_vpn_keymats(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for all particle vpns in {self.uvn}?")
    self.log.warning("dropping all keys for Particle VPNs")
    for keymat in self.particles_vpn_keymats.values():
      keymat.drop_keys(delete=True)
    del self.particles_vpn_keymats
    self.updated_property("config_id")


  def drop_root_vpn_keymat(self) -> None:
    ask_yes_no(f"drop and regenerate all keys for the root vpn of {self.uvn}?")
    self.log.warning("dropping existing keys for Root VPN")
    if self.rekeyed_root_config_id is None:
      self.rekeyed_root_config_id = self.config_id
    self.root_vpn_keymat.drop_keys()
    self.updated_property("config_id")


  @disabled_if("readonly")
  def purge_keys(self) -> None:
    self.root_vpn_keymat.purge_gone_peers(list(self.uvn.all_cells), delete=True)

    for cell in self.uvn.all_cells.values():
      keymat = self.particles_vpn_keymats[cell.id]
      keymat.purge_gone_peers(list(self.uvn.all_particles), delete=True)


  @disabled_if("readonly")
  def assert_keys(self) -> None:
    self.vpn_config.assert_keys()
    self.id_db.assert_keys()


  @disabled_if("readonly")
  def generate_artifacts(self, force: bool=False) -> bool:
    def _print_changes(cur: Versioned, changed_elements_vals: dict, depth: int=0) -> None:
      import pprint
      indent = "  " * depth
      # changed_elements = set(changed_elements_vals.keys())
      logger = self.log.info if depth == 0 else self.log.activity
      if len(changed_elements_vals) > 0:
        if depth == 0:
          self.log.info("{}{}: {} changed elements", indent, cur, len(changed_elements_vals))
        for ch, _ in changed_elements_vals.items():
          nested_changes = dict(ch.collect_changes(lambda o: o is not ch))
          assert(ch.dirty and not ch.saved)
          self.log.info("{}- {}{}{}: properties[{}]={}, nested[{}]={}", indent, ch,
            "*" if ch.dirty else "",
            "^" if not ch.saved else "",
            len(ch.changed_properties),
            # ", ".join(sorted(ch.changed_properties)),
            pprint.pformat(ch.changed_properties),
            
            len(nested_changes),
            # ", ".join(repr(o) for o in nested_changes)
            pprint.pformat(list(nested_changes))
            )

          # for o in nested_changes:
          #   _print_changes(o, nested_changes, depth+1)
        # _log_changed(changed_elements_vals)
      else:
        self.log.info("{}{}: nothing changed", indent, self)


    # Save modified objects and log them for the user
    def _save() -> int:
      changed_elements_vals = dict(self.collect_changes())
      _print_changes(self, changed_elements_vals)
      self.config_id = self.generate_config_id()
      self.db.save(self, dirty=not force)
      return len(changed_elements_vals)

    # Purge all keys that belong to deleted owners
    self.purge_keys()
    # Regenerate deployment configuration if needed
    if self.needs_redeployment:
      self.redeploy()
      self.backbone_vpn_keymat.drop_keys(delete=True)
    changed_elements = _save()


    # Generate all missing keys 
    self.assert_keys()
    changed_elements += _save()

    changed = changed_elements > 0
    if not changed and not force:
      self.log.info("unchanged")
      return False

    if self.cells_dir.is_dir():
      exec_command(["rm", "-rfv", self.cells_dir])
    for cell in self.uvn.cells.values():
      Packager.generate_cell_agent_package(self, cell, self.cells_dir)
      Packager.generate_cell_agent_install_guide(self, cell, self.cells_dir)

    if self.particles_dir.is_dir():
      exec_command(["rm", "-rfv", self.particles_dir])
    for particle in self.uvn.particles.values():
      Packager.generate_particle_package(self, particle, self.particles_dir)

    self.log.info("updated")
    return True


  @cached_property
  def rekeyed_cells(self) -> set[Cell]:
    return {
      next(c for c in self.uvn.cells.values() if c.id == peer)
        for peer in self.rekeyed_root_vpn_keymat.peers_with_dropped_key
     }


  @inject_db_transaction
  def rekey_uvn(self,
      root_vpn: bool=False,
      particles_vpn: bool=False,
      deleted: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    def _rekey():
      if not deleted:
        if not (root_vpn or particles_vpn):
          raise RuntimeError("nothing to rekey")

        if root_vpn:
          ask_yes_no(f"drop and regenerate all root vpn keys for {self.uvn}?")
        if particles_vpn:
          ask_yes_no(f"drop and regenerate all particle vpn keys for {self.uvn}?")

      if deleted or root_vpn:
        # If we haven't a pending rekeyeing, keep track of the current
        # configuration and assume that it is the configuration ID
        # for the agents. On the next sync, we will push the rekeyed config
        if not deleted and self.rekeyed_root_config_id is None:
          self.rekeyed_root_config_id = self.config_id

        # If a peer already has a dropped key in self.rekeyed_root_vpn_keymat
        # then we can delete the current root vpn key
        drop_or_delete = {
          cell.id: already_dropped
          for cell in self.uvn.cells.values()
            for already_dropped in [cell in self.rekeyed_cells]
        } if not deleted else None
        self.root_vpn_keymat.drop_keys(delete=deleted, delete_map=drop_or_delete, cursor=cursor)
      
      if deleted or particles_vpn:
        for keymat in self.particles_vpn_keymats.values():
          keymat.drop_keys(delete=True, cursor=cursor)

    return do_in_transaction(_rekey)


  @inject_db_transaction
  def rekey_particle(self,
      particle: Particle,
      cells: Iterable[Cell]|None=None,
      deleted: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None):
    def _rekey():
      if not deleted:
        if cells:
          ask_yes_no(f"drop and regenerate vpn keys for {particle} of {self.uvn} for cells {', '.join(c.name for c in cells)}?")
        else:
          ask_yes_no(f"drop and regenerate all vpn keys for {particle} of {self.uvn}?")
      target_cells = cells or list(self.uvn.cells.values())
      other_particles = list(p for p in self.uvn.all_particles.values() if p != particle)
      for cell in target_cells:
        keymat = self.particles_vpn_keymats[cell.id]
        keymat.purge_gone_peers((p.id for p in other_particles), delete=True, cursor=cursor)
    return do_in_transaction(_rekey)
  

  @inject_db_transaction
  def rekey_cell(self,
      cell: Cell,
      root_vpn: bool=False,
      particles_vpn: bool=False,
      deleted: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None):
    def _rekey():
      if not deleted:
        if not (root_vpn or particles_vpn):
          raise RuntimeError("nothing to rekey")
        if root_vpn:
          ask_yes_no(f"drop and regenerate root vpn keys for {cell} of {self.uvn}?")
        if particles_vpn:
          ask_yes_no(f"drop and regenerate all particle vpn keys for {cell} of {self.uvn}?")
      if deleted or root_vpn:
        self.log.warning("dropping Root VPN key for cell: {}", cell)
        if not deleted and self.rekeyed_root_config_id is None:
          self.rekeyed_root_config_id = self.config_id
        # If a peer already has a dropped key in self.rekeyed_root_vpn_keymat
        # then we can delete the current root vpn key
        drop_or_delete = {
          c.id: already_dropped
          for c in self.uvn.cells.values()
            for already_dropped in [(c == cell and deleted) or c in self.rekeyed_cells]
        }
        other_cells = list(c for c in self.uvn.cells.values() if c != cell)
        self.root_vpn_keymat.purge_gone_peers((c.id for c in other_cells), delete_map=drop_or_delete, cursor=cursor)

      if deleted or particles_vpn:
        self.particles_vpn_keymats[cell.id].drop_keys(delete=True, cursor=cursor)

    return do_in_transaction(_rekey)


  @property
  def deployment_strategy(self) -> DeploymentStrategy:
    strategy_cls = DeploymentStrategy.KnownStrategies[self.uvn.settings.deployment.strategy]
    return self.new_child(strategy_cls)



  def cell_key_material(self, cell: Cell) -> tuple[list[WireGuardPsk|WireGuardKeyPair], list[WireGuardPsk|WireGuardKeyPair]]:
    priv_keymat = [
      *self.root_vpn_keymat.get_peer_material(cell.id, private=True),
      *self.backbone_vpn_keymat.get_peer_material(cell.id, private=True),
      *(self.particles_vpn_keymats[cell.id].get_peer_material(0, private=True)
          if cell.enable_particles_vpn else []),
    ]
    pub_keymat = [
      *self.root_vpn_keymat.get_peer_material(cell.id),
      *self.backbone_vpn_keymat.get_peer_material(cell.id),
      *(self.particles_vpn_keymats[cell.id].get_peer_material(0)
          if cell.enable_particles_vpn else []),
    ]
    return priv_keymat, pub_keymat


  @inject_db_transaction
  def generate_cell_database(self,
      cell: Cell,
      root: Path | None = None,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> Database:
    def _generate():
      db = Database(root, create=True)
      self.db.export_tables(db, [Uvn, Cell, Particle, User, Registry], cursor=cursor)

      priv_keymat, pub_keymat = self.cell_key_material(cell)

      if priv_keymat:
        self.log.activity("exporting {} private keys for {}", len(priv_keymat), cell)
        for k in priv_keymat:
          self.log.activity("- {}", k)
        self.db.export_objects(db, priv_keymat)

      if pub_keymat:
        self.log.activity("exporting {} public keys for {}", len(pub_keymat), cell)
        for k in pub_keymat:
          self.log.activity("- {}", k)
        self.db.export_objects(db, pub_keymat, public=True)
    
      return db
    return do_in_transaction(_generate)



  def export_to_cloud(self, **storage_config) -> None:
    if self.cloud_provider is None:
      raise RuntimeError("no cloud provider configured")
    storage = self.cloud_provider.storage(**storage_config)
    archives = [
      # cell archives
      *(CloudStorageFile(
        type=CloudStorageFileType.CELL_PACKAGE,
        name=cell_archive,
        local_path=self.cells_dir / cell_archive)
      for cell in self.uvn.cells.values()
        for cell_archive in [Packager.cell_archive_file(cell)]),
      # cell install guides
      *(CloudStorageFile(
        type=CloudStorageFileType.CELL_GUIDE,
        name=cell_guide,
        local_path=self.cells_dir / cell_guide)
      for cell in self.uvn.cells.values()
        for cell_guide in [f"{Packager.cell_archive_file(cell, basename=True)}.html"]),
      # particle archives
      *(CloudStorageFile(
        type=CloudStorageFileType.PARTICLE_PACKAGE,
        name=particle_archive,
        local_path=self.particles_dir / particle_archive)
      for particle in self.uvn.particles.values()
        for particle_archive in [Packager.particle_archive_file(particle)])
    ]
    uploaded = storage.upload(archives)


  @classmethod
  def import_cell_package_from_cloud(cls, uvn: str, cell: str, root: Path, provider_class: str, provider_config: dict | None = None, storage_config: dict | None = None) -> Path:
    db = Database()
    provider = cls.load_cloud_provider(provider_class, db=db, **(provider_config or {}))
    storage = provider.storage(**(storage_config or {}))
    cell_archive = Packager.cell_archive_file(cell_name=cell, uvn_name=uvn)
    archives = [
      CloudStorageFile(
        type=CloudStorageFileType.CELL_PACKAGE,
        name=cell_archive,
        local_path=db.root / cell_archive),
    ]
    downloaded = storage.download(archives)
    assert(len(downloaded) == len(archives))
    root.mkdir(exist_ok=True, parents=True)
    exec_command(["mv", "-v", *(d.local_path for d in downloaded), root])
    return root / downloaded[0].local_path.name


  def send_email(self,
      to: str | OwnableDatabaseObject | User,
      subject: str,
      body: str,
      sender: str | User = None) -> None:
    if isinstance(to, OwnableDatabaseObject):
      if not isinstance(to.owner, User):
        raise ValueError("unsupported email receiver", to)
      to = to.owner
    if isinstance(to, User):
      to = to.email
    if self.cloud_provider is None:
      raise RuntimeError("no cloud provider configured")
    if sender is None:
      sender = self.uvn.owner
    if isinstance(sender, User):
      sender = sender.email
    subject = f"[{self.local_id[0]}] {subject}"
    body = Templates.render("notify/message", {
      "body": body,
      "sender": sender,
      "to": to,
      "subject": subject,
      "generation_ts": Timestamp.now(),
    })
    email_server = self.cloud_provider.email_server()
    email_server.send(sender=sender, to=to, subject=subject, body=body)

