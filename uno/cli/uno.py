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
import argparse
from typing import Optional

import ipaddress

from uno.uvn.uvn_id import print_serialized, TimingProfile
from uno.uvn.registry import Registry
from uno.uvn.cell_agent import CellAgent
from uno.uvn.registry_agent import RegistryAgent
from uno.uvn.log import set_verbosity, level as log_level, Logger as log
from uno.uvn.deployment import DeploymentStrategyKind
from uno.uvn.graph import backbone_deployment_graph
from uno.uvn.ask import ask_assume_no, ask_assume_yes
from uno.uvn.agent_net import UvnNetService, UvnAgentService
from uno.uvn.keys import KeyId

###############################################################################
###############################################################################
# Registry Commands
###############################################################################
###############################################################################
def registry_configure_args(args):
  return {
    **{
      k_on: False if getattr(args, k_off, False) else None
      for k_on, k_off in [
        ("enable_particles_vpn", "disable_particles_vpn"),
        ("enable_root_vpn", "disable_root_vpn"),
      ]
    },
    **{
      k: getattr(args, k, None)
      for k in [
        "owner_id",
        "address",
        "timing_profile",
        "rti_license",
        "root_vpn_push_port",
        "root_vpn_pull_port",
        "root_vpn_subnet",
        "root_vpn_mtu",
        "particles_vpn_port",
        "particles_vpn_subnet",
        "particles_vpn_mtu",
        "backbone_vpn_port",
        "backbone_vpn_subnet",
        "backbone_vpn_mtu",
        "deployment_strategy",
        "deployment_strategy_args",
        "master_secret",
        "dds_domain",
        "enable_dds_security",
      ]
    }
  }


def _update_registry_agent(registry: Registry) -> None:
  agent = RegistryAgent(registry)
  agent.net.generate_configuration()


def registry_load(args) -> Registry:
  registry = Registry.load(args.root or Path.cwd())
  return registry


def registry_configure(args):
  configure_args = registry_configure_args(args)
  if not args.update:
    registry = Registry.create(
      root=args.root,
      name=args.name,
      **configure_args)
    _update_registry_agent(registry)
  else:
    registry = registry_load(args)
    modified = registry.configure(
      **configure_args,
      force=args.force)
    modified = args.force or modified
    if modified:
      _update_registry_agent(registry)
    if args.print:
      print_serialized(registry, verbose=args.verbose > 0)
    if not modified and not args.print:
      log.warning("[REGISTRY] loaded successfuly")


def registry_action(args):
  registry = registry_load(args)
  action_args = {}
  action = None
  config_args = {}
  agent_args = {
    "registry": registry,
  }
  if args.action == "cell-ban":
    action = registry.uvn_id.ban_cell
    action_args = {
      "name": args.name,
    }
  elif args.action == "cell-unban":
    action = registry.uvn_id.unban_cell
    action_args = {
      "name": args.name,
    }
  elif args.action == "cell-delete":
    action = registry.uvn_id.delete_cell
    action_args = {
      "name": args.name,
    }
  elif args.action in ("cell-define", "cell-config"):
    action_args = {
      "name": args.name,
      "owner_id": args.owner_id,
      "address": args.address,
      "allowed_lans": args.network if args.network else None,
      "enable_particles_vpn": False if args.disable_particles_vpn else None,
      "httpd_port": args.httpd_port,
    }
    if args.action == "cell-config":
      action = registry.uvn_id.update_cell
    else:
      action = registry.uvn_id.add_cell
  elif args.action == "particle-ban":
    action = registry.uvn_id.ban_particle
    action_args = {
      "name": args.name,
    }
  elif args.action == "particle-unban":
    action = registry.uvn_id.unban_particle
    action_args = {
      "name": args.name,
    }
  elif args.action == "particle-delete":
    action = registry.uvn_id.delete_particle
    action_args = {
      "name": args.name,
    }
  elif args.action in ("particle-define", "particle-config"):
    action_args = {
      "name": args.name,
      "owner_id": args.owner_id,
    }
    if args.action == "particle-config":
      action = registry.uvn_id.update_particle
    else:
      action = registry.uvn_id.add_particle
  elif args.action == "redeploy":
    config_args = {
      "deployment_strategy": args.deployment_strategy,
      "deployment_strategy_args": args.deployment_strategy_args,
      "redeploy": True,
    }
  elif args.action == "plot":
    if not args.output:
      output_file = registry.root / f"{registry.uvn_id.name}-backbone.png"
    else:
      output_file = args.output
    backbone_deployment_graph(
      uvn_id=registry.uvn_id,
      deployment=registry.backbone_vpn_config.deployment,
      output_file=output_file)
    log.warning(f"backbone plot generated: {output_file}")
  elif args.action == "rekey-particle":
    registry = registry.rekeyed_registry or registry
    action_args = {
      "particle": next(p for p in registry.uvn_id.particles.values() if p.name == args.name),
      "cells": [
        next(c for c in registry.uvn_id.cells.values() if c.name == name)
        for name in args.cell
      ] if args.cell else None,
    }
    config_args = {
      "allow_rekeyed": True,
    }
    action = registry.rekey_particle
  elif args.action == "rekey-cell":
    registry = registry.rekeyed_registry or registry
    action_args = {
      "cell": next(c for c in registry.uvn_id.cells.values() if c.name == args.name),
      "root_vpn": args.root_vpn,
      "particles_vpn": args.particles_vpn,
    }
    config_args = {
      "allow_rekeyed": True,
    }
    action = registry.rekey_cell
    # Don't regenerate static config if 
    # rekeying the root vpn
    if args.root_vpn:
      agent_args = {}
  elif args.action == "rekey-uvn":
    registry = registry.rekeyed_registry or registry
    if not (args.root_vpn or args.particles_vpn):
      raise RuntimeError("nothing to rekey")
    config_args = {
      "drop_keys_root_vpn": args.root_vpn,
      "drop_keys_particles_vpn": args.particles_vpn,
      "allow_rekeyed": True,
    }
    # Don't regenerate static config if 
    # rekeying the root vpn
    if args.root_vpn:
      agent_args = {}
  else:
    raise NotImplementedError(args.action)

  if action:
    result = action(**action_args)
    if getattr(args, "print", False):
      print_serialized(result, verbose=args.verbose > 0)
  
  if action or config_args:
    modified = registry.configure(**config_args)
    if modified and agent_args:
      _update_registry_agent(**agent_args)


def registry_common_args(parser: argparse.ArgumentParser):
  parser.add_argument("-r", "--root",
    metavar="DIR",
    default=Path.cwd(),
    type=Path,
    help="UVN root directory.")
  parser.add_argument("-v", "--verbose",
    action="count",
    default=0,
    help="Increase output verbosity. Repeat for increased verbosity.")
  opts = parser.add_argument_group("User Interaction Options")
  opts.add_argument("-y", "--yes",
    help="Do not prompt the user with questions, and always assume "
    "'yes' is the answer.",
    action="store_true",
    default=False)
  opts.add_argument("--no",
    help="Do not prompt the user with questions, and always assume "
    "'no' is the answer.",
    action="store_true",
    default=False)


def registry_agent(args):
  registry = registry_load(args)
  agent = RegistryAgent(registry)
  with agent.start():
    agent.spin()


def registry_sync(args):
  registry = registry_load(args)
  agent = RegistryAgent(registry)
  with agent.start():
    if agent.needs_rekeying:
      agent.spin_until_rekeyed(
        config_only=args.consistent_config,
        max_spin_time=args.max_wait_time)
    else:
      agent.spin_until_consistent(
        config_only=args.consistent_config,
        max_spin_time=args.max_wait_time)


###############################################################################
###############################################################################
# Cell Commands
###############################################################################
###############################################################################
def cell_bootstrap(args):
  if not args.update:
    agent = CellAgent.extract(
        package=args.package,
        root=args.root)
  else:
    agent = CellAgent.load(args.root)
    if args.package:
      import tempfile
      tmp_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_h.name)
      updated_agent = CellAgent.extract(
        package=args.package, root=tmp_dir)
      agent.reload(updated_agent)
    agent.net.generate_configuration()
    agent.save_to_disk()
    if agent.net.uvn_agent.uvn_net.enabled():
      agent.net.uvn_agent.uvn_net.uvn_net_stop()
      agent.net.uvn_agent.uvn_net.uvn_net_start()
  # if args.update and agent.net.uvn_agent.uvn_net.enabled():
  #   agent.net.uvn_agent.uvn_net.restart()


def cell_agent(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.enable_www = args.www
  agent.enable_systemd = args.systemd
  # HACK set NDDSHOME so that the Connext Python API finds the license file
  import os
  os.environ["NDDSHOME"] = str(agent.root)
  with agent.start():
    agent.spin(
      max_spin_time=args.max_run_time
      if args.max_run_time >= 0 else None)


def cell_service_enable(args):
  root = args.root or Path.cwd()
  # Load the agent to make sure the directory contains a valid configuration
  agent = CellAgent.load(root)

  agent.net.uvn_agent.install()
  agent.net.uvn_agent.uvn_net.configure(agent.net.config_dir)

  if args.boot:
    if args.agent:
      agent.net.uvn_agent.enable_boot()
    else:
      agent.net.uvn_agent.disable_boot()
      agent.net.uvn_agent.uvn_net.enable_boot()

  if args.start:
    if args.agent:
      agent.net.uvn_agent.start()
    else:
      agent.net.uvn_agent.uvn_net.start()


def cell_service_disable(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.net.uvn_agent.remove()

###############################################################################
###############################################################################
# Load agent
###############################################################################
###############################################################################

def _load_agent(args):
  # if running as a systemd service, read the root location
  # from the global marker for the uvn-net service
  if getattr(args, "systemd", False):
    if args.registry:
      svc = UvnNetService.Root
    else:
      svc = UvnNetService.Cell
    
    root = svc.global_uvn_dir
    if root is None:
      raise RuntimeError("no global agent directory configured", str(svc), svc.global_uvn_id)
    root = root.parent
    log.warning(f"global directory for {svc}: {root}")

    if args.registry:
      registry = Registry.load(root)
      agent = RegistryAgent(registry)
    else:
      agent = CellAgent.load(root)
  else:
    # Try to load the current directory, first as a cell,
    # and if that fails, as the registry
    root = args.root or Path.cwd()
    try:
      agent = CellAgent.load(root)
      log.debug(f"loaded cell agent: {root}")
    except Exception as e:
      log.debug(f"failed to load as a cell agent: {root}")
      log.exception(e)
      try:
        log.debug(f"trying to load as registry: {root}")
        registry = Registry.load(root)
        agent = RegistryAgent(registry)
        log.debug(f"loaded registry agent: {root}")
      except:
        raise RuntimeError(f"failed to load an agent from directory: {root}") from None

  # HACK set NDDSHOME so that the Connext Python API finds the license file
  import os
  os.environ["NDDSHOME"] = str(agent.root)
  return agent
###############################################################################
###############################################################################
# Net commands
###############################################################################
###############################################################################
  
def uvn_net_up(args):
  agent = _load_agent(args)
  agent.net.start()


def uvn_net_down(args):
  agent = _load_agent(args)
  agent.net.stop(assert_stopped=True)


###############################################################################
###############################################################################
# Agent commands
###############################################################################
###############################################################################
  
def uno_agent(args):
  agent = _load_agent(args)
  agent.enable_www = True
  agent.enable_systemd = args.systemd
  with agent.start():
    agent.spin()


###############################################################################
###############################################################################
# Encrypt commands
###############################################################################
###############################################################################
  
def uno_encrypt(args):
  agent = _load_agent(args)

  try:
    cell = next(c for c in agent.uvn_id.all_cells if c.name == args.cell) if args.cell else agent.cell
  except StopIteration:
    raise RuntimeError("unknown cell", args.cell) from None

  if not cell:
    raise RuntimeError("no cell specified")

  key_id = KeyId.from_uvn_id(cell)
  key = agent.id_db.backend[key_id]

  if args.action == "encrypt":
    agent.id_db.backend.encrypt_file(key, args.input, args.output)
  else:
    agent.id_db.backend.decrypt_file(key, args.input, args.output)



###############################################################################
###############################################################################
# Command parser helpers
###############################################################################
###############################################################################

def _define_registry_config_args(parser, owner_id_required: bool=False):
  parser.add_argument("-o", "--owner-id",
    metavar="OWNER",
    required=owner_id_required,
    help="'NAME <EMAIL>', or just 'EMAIL', of the UVN's administrator.")

  parser.add_argument("-a", "--address",
    # required=True,
    help="The public address for the UVN registry.")

  parser.add_argument("--timing-profile",
    default=None,
    choices=[v.name.lower().replace("_", "-") for v in TimingProfile],
    help="Timing profile to use.")

  parser.add_argument("--disable-root-vpn",
    help="",
    default=False,
    action="store_true")

  parser.add_argument("--root-vpn-push-port",
    metavar="PORT",
    help="",
    default=None,
    type=int)

  parser.add_argument("--root-vpn-pull-port",
    metavar="PORT",
    help="",
    default=None,
    type=int)
  
  parser.add_argument("--root-vpn-subnet",
    metavar="SUBNET",
    help="",
    default=None,
    type=ipaddress.IPv4Network)

  parser.add_argument("--root-vpn-mtu",
    metavar="MTU",
    help="",
    default=None,
    type=int)

  parser.add_argument("--disable-particles-vpn",
    help="",
    default=False,
    action="store_true")

  parser.add_argument("--particles-vpn-port",
    metavar="PORT",
    help="",
    default=None,
    type=int)
  
  parser.add_argument("--particles-vpn-subnet",
    metavar="SUBNET",
    help="",
    default=None,
    type=ipaddress.IPv4Network)

  parser.add_argument("--particles-vpn-mtu",
    metavar="MTU",
    help="",
    default=None,
    type=int)

  parser.add_argument("--backbone-vpn-port",                
    metavar="PORT",
    help="",
    default=None,
    type=int)
  
  parser.add_argument("--backbone-vpn-subnet",
    metavar="SUBNET",
    help="",
    default=None,
    type=ipaddress.IPv4Network)

  parser.add_argument("--backbone-vpn-mtu",
    metavar="MTU",
    help="",
    default=None,
    type=int)

  parser.add_argument("-L", "--rti-license",
    metavar="FILE",
    help="Path to a valid RTI license file to be used by the UVN agents.",
    default=None,
    type=Path)

  parser.add_argument("-m", "--master-secret",
    metavar="PASSWORD",
    help="A password that will be used to protect access to the UVN agents.",
    default=None)

  parser.add_argument("--dds-domain",
    metavar="DOMAIN_ID",
    help="Custom DDS Domain ID to use for agent communication.",
    default=None,
    type=int)

  parser.add_argument("--enable-dds-security",
    help="Use DDS Security features to procet agent communication. Requires RTI Connext DDS to be installed and loaded in the agent's environment.",
    default=False,
    action="store_true")

  _define_deployment_args(parser)
  _define_print_args(parser)


def _define_print_args(parser):
  parser.add_argument("-p", "--print",
    default=False,
    action="store_true",
    help="Print UVN configuration to stdout.")


def _define_deployment_args(parser):
  parser.add_argument("-S", "--deployment-strategy",
    help="Algorithm used to generate the UVN backbone's deployment map.",
    default=None,
    choices=[k.name.lower().replace("_", "-") for k in DeploymentStrategyKind])

  parser.add_argument("-D", "--deployment-strategy-args",
    metavar="YAML",
    help="A YAML file or an inline string specifying custom arguments for the selected deployment strategy.",
    default=None)


def _define_cell_config_args(parser):
  parser.add_argument("-a", "--address",
    # required=True,
    default=None,
    help="The public address for the UVN cell.")

  parser.add_argument("-o", "--owner-id",
    metavar="OWNER",
    help="'NAME <EMAIL>', or just 'EMAIL', of the cell's administrator.")

  parser.add_argument("-N", "--network",
    metavar="A.B.C.D/n",
    default=[],
    action="append",
    type=ipaddress.IPv4Network,
    help="IP subnetwork that the cell will attach to the UVN. Repeat to attach multiple networks.")

  parser.add_argument("--disable-particles-vpn",
    help="Disable particles VPN for this cell.",
    default=False,
    action="store_true")

  parser.add_argument("--httpd-port",
    metavar="PORT",
    help="Port used by the cell's agent to serve HTTPS requests.",
    default=None,
    type=int)

  _define_print_args(parser)


def _define_particle_config_args(parser):
  parser.add_argument("-o", "--owner-id",
    metavar="OWNER",
    help="'NAME <EMAIL>', or just 'EMAIL', of the particle's administrator.")
  _define_print_args(parser)


def _define_sync_args(parser):
  parser.add_argument("-C", "--consistent-config",
    help="Wait only until all cell agents have a consistent,"
      " updated, configuration, instead of waiting until the UVN is fully"
      " routed.",
    default=False,
    action="store_true")

  parser.add_argument("-t", "--max-wait-time",
    metavar="SECONDS",
    help="Maximum time to wait for cells agents and UVN to become consistent."
    " Default: %(default)s sec",
    default=3600,
    type=int)

from argparse import HelpFormatter
from operator import attrgetter
class SortingHelpFormatter(HelpFormatter):
  def add_arguments(self, actions):
    actions = sorted(actions, key=attrgetter('option_strings'))
    super(SortingHelpFormatter, self).add_arguments(actions)
  
  def _iter_indented_subactions(self, action):
    try:
      get_subactions = action._get_subactions
    except AttributeError:
      pass
    else:
      self._indent()
      if isinstance(action, argparse._SubParsersAction):
        for subaction in sorted(get_subactions(), key=lambda x: x.dest):
            yield subaction
      else:
        for subaction in get_subactions():
            yield subaction
      self._dedent()


###############################################################################
###############################################################################
#  Main Script
###############################################################################
###############################################################################

def main():
  #############################################################################
  # define arguments parser
  #############################################################################
  parser = argparse.ArgumentParser(
    formatter_class=SortingHelpFormatter)
  parser.set_defaults(cmd=None)

  subparsers = parser.add_subparsers(help="Top-level Commands")

  #############################################################################
  # uno define ...
  #############################################################################
  cmd_define = subparsers.add_parser("define",
    help="Create a new UVN, add cells, add particles.",
    formatter_class=SortingHelpFormatter)
  subparsers_define = cmd_define.add_subparsers(help="UVN definition")

  #############################################################################
  # uno define uvn ...
  #############################################################################
  cmd_define_uvn = subparsers_define.add_parser("uvn",
    help="Create a new UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_define_uvn.set_defaults(
    cmd=registry_configure,
    update=False)

  cmd_define_uvn.add_argument("name",
    help="A unique name for the UVN.")

  # cmd_define_uvn.add_argument("-p", "--passphrase",
  #   help="A password that will be used to protect access to the UVN.")

  _define_registry_config_args(cmd_define_uvn, owner_id_required=True)
  registry_common_args(cmd_define_uvn)

  #############################################################################
  # uno define cell ...
  #############################################################################
  cmd_define_cell = subparsers_define.add_parser("cell",
    help="Add a new cell to the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_define_cell.set_defaults(
    cmd=registry_action,
    action="cell-define")

  cmd_define_cell.add_argument("name",
    help="A unique name for the cell.")

  _define_cell_config_args(cmd_define_cell)
  registry_common_args(cmd_define_cell)

  #############################################################################
  # uno define particle ...
  #############################################################################
  cmd_define_particle = subparsers_define.add_parser("particle",
    help="Add a new particle to the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_define_particle.set_defaults(
    cmd=registry_action,
    action="particle-define")

  cmd_define_particle.add_argument("name",
    help="A unique name for the particle.")

  _define_particle_config_args(cmd_define_particle)
  registry_common_args(cmd_define_particle)


  #############################################################################
  # uno config ...
  #############################################################################
  cmd_config = subparsers.add_parser("config",
    help="Modify the configuration of the UVN, cells, particles.",
    formatter_class=SortingHelpFormatter)
  subparsers_config = cmd_config.add_subparsers(help="UVN configuration")


  #############################################################################
  # uno config uvn ...
  #############################################################################
  cmd_config_uvn = subparsers_config.add_parser("uvn",
    help="Update the UVN's configuration.",
    formatter_class=SortingHelpFormatter)
  cmd_config_uvn.set_defaults(
    cmd=registry_configure,
    update=True)

  _define_registry_config_args(cmd_config_uvn)
  registry_common_args(cmd_config_uvn)

  cmd_config_uvn.add_argument("-f", "--force",
    help="Force processing and regeneration of all registry configuration",
    default=False,
    action="store_true")

  #############################################################################
  # uno config cell ...
  #############################################################################
  cmd_config_cell = subparsers_config.add_parser("cell",
    help="Update a cell's configuration.",
    formatter_class=SortingHelpFormatter)
  cmd_config_cell.set_defaults(
    cmd=registry_action,
    action="cell-config")

  cmd_config_cell.add_argument("name",
    help="The cell's unique name.")

  _define_cell_config_args(cmd_config_cell)
  registry_common_args(cmd_config_cell)

  #############################################################################
  # uno config particle ...
  #############################################################################
  cmd_config_particle = subparsers_config.add_parser("particle",
    help="Add a new particle to the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_config_particle.set_defaults(
    cmd=registry_action,
    action="particle-config")

  cmd_config_particle.add_argument("name",
    help="The particle's unique name.")

  _define_particle_config_args(cmd_config_particle)
  registry_common_args(cmd_config_particle)

  #############################################################################
  # uno redeploy ...
  #############################################################################
  cmd_redeploy = subparsers.add_parser("redeploy",
    help="Update the UVN configuration with a new backbone deployment.",
    formatter_class=SortingHelpFormatter)
  cmd_redeploy.set_defaults(
    cmd=registry_action,
    action="redeploy")
  _define_deployment_args(cmd_redeploy)
  registry_common_args(cmd_redeploy)
  
  
  #############################################################################
  # uno sync ...
  #############################################################################
  cmd_sync = subparsers.add_parser("sync",
    help="Push current configuration to cell agents.",
    formatter_class=SortingHelpFormatter)
  cmd_sync.set_defaults(cmd=registry_sync)

  _define_sync_args(cmd_sync)
  registry_common_args(cmd_sync)


  # #############################################################################
  # # uno plot
  # #############################################################################
  # cmd_plot = subparsers.add_parser("plot",
  #   help="Generate an image of the current backbone deployment.")
  # cmd_plot.set_defaults(
  #   cmd=registry_action,
  #   action="plot")

  # cmd_plot.add_argument("-o", "--output",
  #   help="Save the generated image to a custom path.",
  #   default=None,
  #   type=Path)

  # registry_common_args(cmd_plot)


  # #############################################################################
  # # uno cell ...
  # #############################################################################
  # cmd_cell = subparsers.add_parser("cell",
  #   help="Perform operation on a deployed cell.")
  # subparsers_cell = cmd_cell.add_subparsers(help="Cell operations")


  #############################################################################
  # uno install ...
  #############################################################################
  cmd_install = subparsers.add_parser("install",
    help="Install an agent package.",
    formatter_class=SortingHelpFormatter)
  cmd_install.set_defaults(
    cmd=cell_bootstrap,
    update=False)

  cmd_install.add_argument("package",
    help="Package file to install.",
    type=Path)

  registry_common_args(cmd_install)

  #############################################################################
  # uno cell update ...
  #############################################################################
  cmd_update = subparsers.add_parser("update",
    help="Update an existing cell agent by regenerating its configuration.")
  cmd_update.set_defaults(
    cmd=cell_bootstrap,
    update=True)

  cmd_update.add_argument("-p", "--package",
    help="Optionally, a new package file to install.",
    type=Path,
    default=None)

  registry_common_args(cmd_update)

  #############################################################################
  # uno cell agent ...
  #############################################################################
  # cmd_cell_agent = subparsers_cell.add_parser("agent",
  #   help="Start a UVN cell agent.")
  # cmd_cell_agent.set_defaults(cmd=cell_agent)
  # registry_common_args(cmd_cell_agent)

  # cmd_cell_agent.add_argument("-t", "--max-run-time",
  #   metavar="SECONDS",
  #   help="Maximum time to run.",
  #   default=-1,
  #   type=int)
  
  # cmd_cell_agent.add_argument("-W", "--www",
  #   default=False,
  #   action="store_true",
  #   help="Start a webserver to serve the agent's status.")

  # #############################################################################
  # # uno net ...
  # #############################################################################
  # cmd_net = subparsers.add_parser("net",
  #   help="Control the UVN's network services.")
  # subparsers_cell_net = cmd_net.add_subparsers(help="UVN network operations")


  # #############################################################################
  # # uno net up
  # #############################################################################
  # cmd_net_up = subparsers_cell_net.add_parser("up",
  #   help="Enable all system services required to connect the host to the UVN.")
  # cmd_net_up.set_defaults(cmd=uvn_net_up)

  # registry_common_args(cmd_net_up)

  # #############################################################################
  # # uno net down
  # #############################################################################
  # cmd_net_down = subparsers_cell_net.add_parser("down",
  #   help="Stop all system services used to connect the UVN.")
  # cmd_net_down.set_defaults(cmd=uvn_net_down)

  # registry_common_args(cmd_net_down)


  #############################################################################
  # uno service ...
  #############################################################################
  cmd_service = subparsers.add_parser("service",
    help="Install and control the UVN connection (and cell agent) as a systemd service.",
    formatter_class=SortingHelpFormatter)
  subparsers_service = cmd_service.add_subparsers(help="Systemd service configuration")


  #############################################################################
  # uno service install ...
  #############################################################################
  cmd_service_enable = subparsers_service.add_parser("install",
    help="Install the uvn-net and uvn-agent systemd services, and enable them for the selected directory.",
    formatter_class=SortingHelpFormatter)
  cmd_service_enable.set_defaults(
    cmd=cell_service_enable)

  cmd_service_enable.add_argument("-s", "--start",
    help="Start the service after installing it..",
    default=False,
    action="store_true")
  
  cmd_service_enable.add_argument("-a", "--agent",
    help="Run the uvn-agent service instead of uvn-net.",
    default=False,
    action="store_true")

  cmd_service_enable.add_argument("-b", "--boot",
    help="Enable the service at boot",
    default=False,
    action="store_true")

  registry_common_args(cmd_service_enable)


  #############################################################################
  # uno service remove ...
  #############################################################################
  cmd_service_disable = subparsers_service.add_parser("remove",
    help="Disable the uvn-net and uvn-agent systemd services. Stop them if they are active.",
    formatter_class=SortingHelpFormatter)
  cmd_service_disable.set_defaults(
    cmd=cell_service_disable)

  registry_common_args(cmd_service_disable)


  #############################################################################
  # uno agent ..
  #############################################################################
  cmd_agent = subparsers.add_parser("agent",
    help="Start an agent for the selected directory (either cell or registry).",
    formatter_class=SortingHelpFormatter)
  cmd_agent.set_defaults(
    cmd=uno_agent)

  cmd_agent.add_argument("-t", "--max-run-time",
    metavar="SECONDS",
    help="Run the agent for the specified time instead of indefinitely.",
    default=None,
    type=int)

  cmd_agent.add_argument("--systemd",
    help=argparse.SUPPRESS,
    default=False,
    action="store_true")


  cmd_agent.add_argument("--registry",
    help=argparse.SUPPRESS,
    default=False,
    action="store_true")

  registry_common_args(cmd_agent)

  #############################################################################
  # uno ban ...
  #############################################################################
  cmd_ban = subparsers.add_parser("ban",
    help="Exclude a particle or a cell from the UVN.",
    formatter_class=SortingHelpFormatter)
  subparsers_ban = cmd_ban.add_subparsers(help="Banishing commands")


  #############################################################################
  # uno ban cell
  #############################################################################
  cmd_ban_cell = subparsers_ban.add_parser("cell",
    help="Exclude a cell from the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_ban_cell.set_defaults(
    cmd=registry_action,
    action="cell-ban")

  cmd_ban_cell.add_argument("name",
    help="The cell's unique name.")

  registry_common_args(cmd_ban_cell)


  #############################################################################
  # uno ban particle
  #############################################################################
  cmd_ban_particle = subparsers_ban.add_parser("particle",
    help="Exclude a particle from the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_ban_particle.set_defaults(
    cmd=registry_action,
    action="particle-ban")

  cmd_ban_particle.add_argument("name",
    help="The particle's unique name.")

  registry_common_args(cmd_ban_particle)


  #############################################################################
  # uno unban ...
  #############################################################################
  cmd_unban = subparsers.add_parser("unban",
    help="Allow a particle or a cell back into the UVN.",
    formatter_class=SortingHelpFormatter)
  subparsers_unban = cmd_unban.add_subparsers(help="Unbanishing commands")


  #############################################################################
  # uno unban cell
  #############################################################################
  cmd_unban_cell = subparsers_unban.add_parser("cell",
    help="Allow a cell back into the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_unban_cell.set_defaults(
    cmd=registry_action,
    action="cell-unban")

  cmd_unban_cell.add_argument("name",
    help="The cell's unique name.")

  registry_common_args(cmd_unban_cell)


  #############################################################################
  # uno ban particle
  #############################################################################
  cmd_unban_particle = subparsers_unban.add_parser("particle",
    help="Allow a particle back into the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_unban_particle.set_defaults(
    cmd=registry_action,
    action="particle-unban")

  cmd_unban_particle.add_argument("name",
    help="The particle's unique name.")

  registry_common_args(cmd_unban_particle)


  #############################################################################
  # uno delete ...
  #############################################################################
  cmd_del = subparsers.add_parser("delete",
    help="Permanently delete a particle or a cell.",
    formatter_class=SortingHelpFormatter)
  subparsers_del = cmd_del.add_subparsers(help="Unbanishing commands")


  #############################################################################
  # uno delete cell
  #############################################################################
  cmd_del_cell = subparsers_del.add_parser("cell",
    help="Delete a cell from the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_del_cell.set_defaults(
    cmd=registry_action,
    action="cell-delete")

  cmd_del_cell.add_argument("name",
    help="The cell's unique name.")

  registry_common_args(cmd_del_cell)


  #############################################################################
  # uno delete particle
  #############################################################################
  cmd_del_particle = subparsers_del.add_parser("particle",
    help="Delete a particle from the UVN.",
    formatter_class=SortingHelpFormatter)
  cmd_del_particle.set_defaults(
    cmd=registry_action,
    action="particle-delete")

  cmd_del_particle.add_argument("name",
    help="The particle's unique name.")

  registry_common_args(cmd_del_particle)


  #############################################################################
  # uno encrypt ...
  #############################################################################
  cmd_encrypt = subparsers.add_parser("encrypt",
    help="Encrypt a file for a UVN cell.",
    formatter_class=SortingHelpFormatter)
  cmd_encrypt.set_defaults(
    cmd=uno_encrypt,
    action="encrypt")

  cmd_encrypt.add_argument("-c", "--cell",
    default=None,
    help="Name of the cell receiving the file.")

  cmd_encrypt.add_argument("-in", "--input",
    type=Path,
    required=True,
    help="File to encrypt.")
  
  cmd_encrypt.add_argument("-out", "--output",
    type=Path,
    required=True,
    help="File to generate.")

  registry_common_args(cmd_encrypt)


  #############################################################################
  # uno decrypt ...
  #############################################################################
  cmd_decrypt = subparsers.add_parser("decrypt",
    help="Decrypt a file received by a UVN cell.",
    formatter_class=SortingHelpFormatter)
  cmd_decrypt.set_defaults(
    cmd=uno_encrypt,
    action="decrypt")


  cmd_decrypt.add_argument("-c", "--cell",
    default=None,
    help="Name of the cell receiving the file.")

  cmd_decrypt.add_argument("-in", "--input",
    type=Path,
    required=True,
    help="File to encrypt.")
  
  cmd_decrypt.add_argument("-out", "--output",
    type=Path,
    required=True,
    help="File to generate.")

  registry_common_args(cmd_decrypt)


  #############################################################################
  # uno rekey ...
  #############################################################################
  cmd_rekey = subparsers.add_parser("rekey",
    help="Regenerate the key material for a particle or a cell.",
    formatter_class=SortingHelpFormatter)
  subparsers_rekey = cmd_rekey.add_subparsers(help="Rekeying commands")


  #############################################################################
  # uno rekey particle
  #############################################################################
  cmd_rekey_particle = subparsers_rekey.add_parser("particle",
    help="Regenerate the key material for a particle.",
    formatter_class=SortingHelpFormatter)
  cmd_rekey_particle.set_defaults(
    cmd=registry_action,
    action="rekey-particle")

  cmd_rekey_particle.add_argument("name",
    help="The particle's unique name.")

  cmd_rekey_particle.add_argument("-c", "--cell",
    metavar="NAME",
    help="Restrict the rekeying to the specified cell. Repeat to select multiple.",
    default=[],
    action="append")

  registry_common_args(cmd_rekey_particle)


  #############################################################################
  # uno rekey cell
  #############################################################################
  cmd_rekey_cell = subparsers_rekey.add_parser("cell",
    help="Regenerate the key material for a cell.",
    formatter_class=SortingHelpFormatter)
  cmd_rekey_cell.set_defaults(
    cmd=registry_action,
    action="rekey-cell")

  cmd_rekey_cell.add_argument("name",
    help="The cell's unique name.")

  cmd_rekey_cell.add_argument("-R", "--root-vpn",
    help="Regenerate the Root VPN key.",
    default=False,
    action="store_true")

  cmd_rekey_cell.add_argument("-P", "--particles-vpn",
    help="Regenerate all Particles VPN keys.",
    default=False,
    action="store_true")

  registry_common_args(cmd_rekey_cell)


  #############################################################################
  # uno rekey uvn
  #############################################################################
  cmd_rekey_uvn = subparsers_rekey.add_parser("uvn",
    help="Regenerate the key material for the uvn.",
    formatter_class=SortingHelpFormatter)
  cmd_rekey_uvn.set_defaults(
    cmd=registry_action,
    action="rekey-uvn")

  cmd_rekey_uvn.add_argument("-R", "--root-vpn",
    help="Regenerate the Root VPN keys.",
    default=False,
    action="store_true")

  cmd_rekey_uvn.add_argument("-P", "--particles-vpn",
    help="Regenerate all Particles VPN keys.",
    default=False,
    action="store_true")

  registry_common_args(cmd_rekey_uvn)


  #############################################################################
  # parse arguments and run selected command
  #############################################################################
  args = parser.parse_args()

  cmd = args.cmd
  if cmd is None:
    raise RuntimeError("no command specified")

  if args.verbose >= 2:
    set_verbosity(log_level.debug)
  elif args.verbose >= 1:
    set_verbosity(log_level.activity)
  else:
    set_verbosity(log_level.warning)

  yes = getattr(args, "yes", False)
  if yes:
    ask_assume_yes()

  no = getattr(args, "no", False)
  if no:
    ask_assume_no()

  try:
    cmd(args)
  except KeyboardInterrupt:
    pass
