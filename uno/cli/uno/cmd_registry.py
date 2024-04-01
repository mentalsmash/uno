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
from typing import Callable
import argparse

from uno.registry.registry import Registry
from uno.registry.versioned import Versioned
from uno.core.log import Logger


def _print_result(args: argparse.Namespace, result: Versioned) -> None:
  if getattr(args, "print", False):
    print(Versioned.yaml_dump(result, public=not Logger.DEBUG))


def registry_action(action: Callable[[argparse.Namespace, Registry], None]) -> Callable[[argparse.Namespace], None]:
  def _wrapped(args: argparse.Namespace) -> None:
    registry = Registry.open(args.root)
    # generate = action(args, registry)
    action(args, registry)
    
    if registry.dirty:
      # changed = registry.generate_artifacts(force=getattr(args, "generate", False))
      changed = registry.generate_artifacts()
    else:
      registry.log.info("unchanged")
  return _wrapped;


def registry_define_uvn(args: argparse.Namespace) -> None:
  registry = Registry.create(
    name=args.name,
    owner=args.owner,
    password=args.password,
    root=args.root,
    registry_config=args.config_registry(args))


@registry_action
def registry_config_uvn(args: argparse.Namespace, registry: Registry) -> bool:
  config_registry = args.config_registry(args)
  if not args.owner and not config_registry:
    # Make registry readonly if no configuration arguments were passed
    registry.readonly = True
  if args.owner:
    owner = registry.load_user(args.owner)
    registry.uvn.set_ownership(owner)
  if config_registry:
    registry.configure(**config_registry)
  _print_result(args, registry)
  return registry.dirty


@registry_action
def registry_rekey_uvn(args: argparse.Namespace, registry: Registry) -> bool:
  registry.rekey_uvn(root_vpn=args.root_vpn, particles_vpn=args.particles_vpn)
  return True


@registry_action
def registry_define_cell(args: argparse.Namespace, registry: Registry) -> bool:
  owner = registry.load_user(args.owner) if args.owner else None
  registry.add_cell(
    name=args.name,
    owner=owner,
    **(args.config_cell(args) or {}))
  return True


@registry_action
def registry_config_cell(args: argparse.Namespace, registry: Registry) -> bool:
  cell = registry.load_cell(args.name)
  config_cell = args.config_cell(args)
  if not args.owner and not config_cell:
    # Make registry readonly if no configuration arguments were passed
    registry.readonly = True
  if args.owner:
    owner = next(u for u in registry.users if u.email == args.owner)
    cell.set_ownership(owner)
  if config_cell:
    registry.update_cell(cell, **config_cell)
  _print_result(args, cell)
  return cell.dirty


@registry_action
def registry_delete_cell(args: argparse.Namespace, registry: Registry) -> bool:
  cell = registry.load_cell(args.name)
  registry.delete_cell(cell)
  return True


@registry_action
def registry_rekey_cell(args: argparse.Namespace, registry: Registry) -> bool:
  cell = registry.load_cell(args.name)
  registry.rekey_cell(cell,
    root_vpn=args.root_vpn,
    particles_vpn=args.particles_vpn)
  return True


@registry_action
def registry_ban_cell(args: argparse.Namespace, registry: Registry) -> bool:
  cell = registry.load_cell(args.name)
  registry.ban([cell], banned=True)
  return True


@registry_action
def registry_unban_cell(args: argparse.Namespace, registry: Registry) -> bool:
  cell = registry.load_cell(args.name)
  registry.ban([cell], banned=False)
  return True


@registry_action
def registry_define_particle(args: argparse.Namespace, registry: Registry) -> bool:
  owner = registry.load_user(args.owner) if args.owner else None
  registry.add_particle(
    name=args.name,
    owner=owner,
    **(args.config_particle(args) or {}))
  return True


@registry_action
def registry_config_particle(args: argparse.Namespace, registry: Registry) -> bool:
  particle = registry.load_particle(args.name)
  config_particle = args.config_particle(args)
  if not args.owner and not config_particle:
    # Make registry readonly if no configuration arguments were passed
    registry.readonly = True
  if args.owner:
    owner = next(u for u in registry.users if u.email == args.owner)
    particle.set_ownership(owner)
  if config_particle:
    registry.update_particle(particle, **config_particle)
  _print_result(args, particle)
  return particle.dirty


@registry_action
def registry_delete_particle(args: argparse.Namespace, registry: Registry) -> bool:
  particle = registry.load_particle(args.name)
  registry.delete_particle(particle)
  return True


@registry_action
def registry_rekey_particle(args: argparse.Namespace, registry: Registry) -> bool:
  particle = registry.load_particle(args.name)
  registry.rekey_particle(particle, cells=None if not args.cell else args.cell)
  return True


@registry_action
def registry_ban_particle(args: argparse.Namespace, registry: Registry) -> bool:
  particle = registry.load_particle(args.name)
  registry.ban([particle], banned=True)
  return True


@registry_action
def registry_unban_particle(args: argparse.Namespace, registry: Registry) -> bool:
  particle = registry.load_particle(args.name)
  registry.ban([particle], banned=False)
  return True


@registry_action
def registry_ban_user(args: argparse.Namespace, registry: Registry) -> bool:
  user = registry.load_user(args.email)
  registry.ban([user], banned=True)
  return True


@registry_action
def registry_unban_user(args: argparse.Namespace, registry: Registry) -> bool:
  user = registry.load_user(args.email)
  registry.ban([user], banned=False)
  return True


@registry_action
def registry_redeploy(args: argparse.Namespace, registry: Registry) -> bool:
  config_deployment = (args.config_registry(args) or {}).get("uvn", {}).get("settings", {}).get("deployment")
  if config_deployment:
    registry.uvn.settings.deployment.configure(**config_deployment)
  registry.redeploy()
  registry.backbone_vpn_keymat.drop_keys(delete=True)
  return True


@registry_action
def registry_define_user(args: argparse.Namespace, registry: Registry) -> bool:
  registry.add_user(email=args.email, **(args.config_user(args) or {}))
  return True


@registry_action
def registry_config_user(args: argparse.Namespace, registry: Registry) -> bool:
  user = registry.load_user(args.email)
  config_user = args.config_user(args)
  if not config_user:
    # Make registry readonly if no configuration arguments were passed
    registry.readonly = True
  if config_user:
    registry.update_user(user, **config_user)
  _print_result(args, user)
  return user.dirty


@registry_action
def registry_delete_user(args: argparse.Namespace, registry: Registry) -> bool:
  user = registry.load_user(args.email)
  registry.delete_user(user)
  return True
