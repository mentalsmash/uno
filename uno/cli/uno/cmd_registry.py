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


def _print_result(args: argparse.Namespace, result: Versioned) -> None:
  if getattr(args, "print", False):
    print(Versioned.yaml_dump(result, public=True))


def registry_action(action: Callable[[argparse.Namespace, Registry], None]) -> Callable[[argparse.Namespace], None]:
  def _wrapped(args: argparse.Namespace) -> None:
    registry = Registry.open(args.root)
    action(args, registry)
    changed = registry.generate()
    if changed:
      # regenerate agents
      pass
  return _wrapped;


def registry_define_uvn(args: argparse.Namespace) -> None:
  registry = Registry.create(
    name=args.name,
    owner=args.owner,
    password=args.password,
    root=args.root,
    registry_config=args.config_registry(args))
  _print_result(args, registry)


@registry_action
def registry_config_uvn(args: argparse.Namespace, registry: Registry) -> None:
  if args.owner:
    owner = registry.load_user(args.owner)
    registry.uvn.set_ownership(owner)
  registry.configure(**args.config_registry(args))


@registry_action
def registry_rekey_uvn(args: argparse.Namespace, registry: Registry) -> None:
  registry.rekey_uvn()


@registry_action
def registry_define_cell(args: argparse.Namespace, registry: Registry) -> None:
  owner = registry.load_user(args.owner) if args.owner else None
  registry.add_cell(
    name=args.name,
    owner=owner,
    **args.config_cell(args))


@registry_action
def registry_config_cell(args: argparse.Namespace, registry: Registry) -> None:
  cell = registry.load_cell(args.name)
  if args.owner:
    owner = next(u for u in registry.users if u.email == args.owner)
    cell.set_ownership(owner)
  registry.update_cell(cell, **args.config_cell(args))


@registry_action
def registry_delete_cell(args: argparse.Namespace, registry: Registry) -> None:
  cell = registry.load_cell(args.name)
  registry.delete_cell(cell)


@registry_action
def registry_rekey_cell(args: argparse.Namespace, registry: Registry) -> None:
  cell = registry.load_cell(args.name)
  registry.rekey_cell(cell,
    root_vpn=args.root_vpn,
    particles_vpn=args.particles_vpn)


@registry_action
def registry_ban_cell(args: argparse.Namespace, registry: Registry) -> None:
  cell = registry.load_cell(args.name)
  registry.ban([cell], banned=True)


@registry_action
def registry_unban_cell(args: argparse.Namespace, registry: Registry) -> None:
  cell = registry.load_cell(args.name)
  registry.ban([cell], banned=False)


@registry_action
def registry_define_particle(args: argparse.Namespace, registry: Registry) -> None:
  owner = registry.load_user(args.owner) if args.owner else None
  registry.add_particle(
    name=args.name,
    owner=owner,
    **args.config_particle(args))


@registry_action
def registry_config_particle(args: argparse.Namespace, registry: Registry) -> None:
  particle = registry.load_particle(args.name)
  if args.owner:
    owner = next(u for u in registry.users if u.email == args.owner)
    particle.set_ownership(owner)
  registry.update_particle(particle, **args.config_particle(args))


@registry_action
def registry_delete_particle(args: argparse.Namespace, registry: Registry) -> None:
  particle = registry.load_particle(args.name)
  registry.delete_particle(particle)


@registry_action
def registry_rekey_particle(args: argparse.Namespace, registry: Registry) -> None:
  particle = registry.load_particle(args.name)
  registry.rekey_particle(particle, cells=None if not args.cell else args.cell)


@registry_action
def registry_ban_particle(args: argparse.Namespace, registry: Registry) -> None:
  particle = registry.load_particle(args.name)
  registry.ban([particle], banned=True)


@registry_action
def registry_unban_particle(args: argparse.Namespace, registry: Registry) -> None:
  particle = registry.load_particle(args.name)
  registry.ban([particle], banned=False)


@registry_action
def registry_ban_user(args: argparse.Namespace, registry: Registry) -> None:
  user = registry.load_user(args.email)
  registry.ban([user], banned=True)


@registry_action
def registry_unban_user(args: argparse.Namespace, registry: Registry) -> None:
  user = registry.load_user(args.email)
  registry.ban([user], banned=False)


@registry_action
def registry_redeploy(args: argparse.Namespace, registry: Registry) -> None:
  registry.redeploy(
    backbone_vpn_settings=args.config_registry(args)["uvn"]["settings"]["backbone_vpn"])


@registry_action
def registry_define_user(args: argparse.Namespace, registry: Registry) -> None:
  registry.add_user(email=args.email, **args.config_user(args))


@registry_action
def registry_config_user(args: argparse.Namespace, registry: Registry) -> None:
  print("WTF!!!")
  user = registry.load_user(args.email)
  registry.update_user(user, **args.config_user(args))


@registry_action
def registry_delete_user(args: argparse.Namespace, registry: Registry) -> None:
  user = registry.load_user(args.email)
  registry.delete_user(user)
