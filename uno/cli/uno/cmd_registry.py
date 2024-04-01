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
import yaml

from uno.registry.registry import Registry
from uno.registry.versioned import Versioned
from uno.core.log import Logger


def _get_collection_element(collection: list | dict, index_expr: str):
  import re
  index_component_re = re.compile(r"\[([^\]]+)\]")
  current_target = collection
  parsed_index = ""
  try:
    for index_component in index_component_re.findall(index_expr):
      if not parsed_index:
        parsed_index = f"[{index_component}]"
      else:
        parsed_index = f"{parsed_index}[{index_component}]"
      # Try to interpret index as an int
      try:
        int_index = int(index_component)
      except ValueError:
        int_index = None
      
      # Get the index outside of try/except to avoid accidentally
      # masking an exception thrown by the getter
      if int_index is not None:
        current_target = current_target[int_index]
        continue

      # The index was not an integer, parse it with yaml and use the result as index
      # If the value is a string, it will remain a string, otherwise, it might be
      # parsed into a data structure. If the result is a string, it will be converted
      # to a tuple, since we never use lists as dictionary keys.
      value_index = yaml.safe_load(index_component)
      if isinstance(value_index, list):
        value_index = tuple(value_index)
      current_target = current_target[value_index]
  except:
    raise ValueError(f"failed to parse index expression after: '{parsed_index}'", index_expr, collection)

  if current_target is collection:
    raise ValueError("invalid index expression", index_expr)
  return current_target

  # matched = index_components_re.match(index_expr)
  # if not matched:
  #   raise ValueError("invalid index expression", index_expr)
  # matched.gr

def _query_serialized(serialized: dict, query: str) -> object:
  def _query_recur(cur: object | dict, query_component: str, remaining: list[str], fqattr: str = "") -> object:
    index_start = query_component.find("[")
    if index_start > 0:
      attr = query_component[:index_start]
      attr_index = query_component[len(attr):]
    else:
      attr = query_component
      attr_index = None
    
    if isinstance(cur, dict) and attr in cur:
      v = cur[attr]
    else:
      v = getattr(cur, attr)

    if attr_index:
      v = _get_collection_element(v, attr_index)
    if len(remaining) == 0:
      return v

    if fqattr:
      fqattr = f"{fqattr}.{query_component}"
    else:
      fqattr = query_component
    
    return _query_recur(v, remaining[0], remaining[1:])

  query_parts = query.split(".")
  return _query_recur(serialized, query_parts[0], query_parts[1:], )



def _print_result(args: argparse.Namespace, result: Versioned) -> None:
  if getattr(args, "print", False):
    serialized = result.serialize(public=not Logger.DEBUG)
    query = getattr(args, "query", None)
    if query:
      serialized = _query_serialized(serialized, query)
    print_json = getattr(args, "json", False)
    print(Versioned.yaml_dump(serialized, public=not Logger.DEBUG, json=print_json))


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
  if not args.update:
    args.print = True
    if args.owner or config_registry:
      registry.log.warning("configuration arguments ignored, use --update to change configuration.")
  else:
    if not args.owner and not config_registry:
      raise ValueError("no configuration parameters specified")
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
  if not args.update:
    args.print = True
    if args.owner or config_cell:
      registry.log.warning("configuration arguments ignored, use --update to change configuration.")
  else:
    if not args.owner and not config_cell:
      raise ValueError("no configuration parameters specified")
    if args.owner:
      owner = next(u for u in registry.active_users if u.email == args.owner)
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
  if not args.update:
    args.print = True
    if args.owner or config_particle:
      registry.log.warning("configuration arguments ignored, use --update to change configuration.")
  else:
    if not args.owner and not config_particle:
      raise ValueError("no configuration parameters specified")
    if args.owner:
      owner = next(u for u in registry.active_users if u.email == args.owner)
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
  if not args.update:
    args.print = True
    if config_user:
      registry.log.warning("configuration arguments ignored, use --update to change configuration.")
  else:
    if not config_user:
      raise ValueError("no configuration parameters specified")
    if config_user:
      registry.update_user(user, **config_user)
  _print_result(args, user)
  return user.dirty


@registry_action
def registry_delete_user(args: argparse.Namespace, registry: Registry) -> bool:
  user = registry.load_user(args.email)
  registry.delete_user(user)
  return True
