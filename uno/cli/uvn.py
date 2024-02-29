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
from uno.uvn.agent import CellAgent
from uno.uvn.registry_agent import RegistryAgent
from uno.uvn.log import set_verbosity, level as log_level, Logger as log
from uno.uvn.deployment import DeploymentStrategyKind
from uno.uvn.graph import backbone_deployment_graph


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
      ]
    }
  }

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
  else:
    registry = registry_load(args)
    if args.print:
      print_serialized(registry, verbose=args.verbose > 0)
    modified = registry.configure(**configure_args)
    if not modified and not args.print:
      log.warning("[REGISTRY] loaded successfuly")


def registry_cell(args):
  registry = registry_load(args)
  config_args = {
    "owner_id": args.owner_id,
    "address": args.address,
    "allowed_lans": args.network if args.network else None,
    "enable_particles_vpn": False if args.disable_particles_vpn else None,
  }
  if args.update:
    method = registry.uvn_id.update_cell
  else:
    method = registry.uvn_id.add_cell
  cell = method(name=args.name, **config_args)
  if args.print:
    print_serialized(cell, verbose=args.verbose > 0)
  registry.configure()


def registry_particle(args):
  registry = registry_load(args)
  config_args = {
    "owner_id": args.owner_id,
  }
  if args.update:
    method = registry.uvn_id.update_particle
  else:
    method = registry.uvn_id.add_particle
  particle = method(name=args.name, **config_args)
  if args.print:
    print_serialized(particle, verbose=args.verbose > 0)
  registry.configure()


def registry_redeploy(args):
  registry = registry_load(args)

  registry.configure(
    deployment_strategy=args.deployment_strategy,
    deployment_strategy_args=args.deployment_strategy_args,
    redeploy=True)


def registry_sync(args, registry: Optional[Registry]=None):
  registry = registry or registry_load(args)
  agent = RegistryAgent(registry)
  agent.spin_until_consistent(
    config_only=args.consistent_config,
    max_spin_time=args.max_wait_time)


def registry_common_args(parser: argparse.ArgumentParser):
  parser.add_argument("-r", "--root",
    default=Path.cwd(),
    type=Path,
    help="UVN root directory.")
  parser.add_argument("-v", "--verbose",
    action="count",
    default=0,
    help="Increase output verbosity. Repeat for increased verbosity.")


def registry_agent(args):
  registry = registry_load(args)
  agent = RegistryAgent(registry)
  agent.spin()


def registry_plot(args):
  registry = registry_load(args)
  if not args.output:
    output_file = registry.root / f"{registry.uvn_id.name}-backbone.png"
  else:
    output_file = args.output
  backbone_deployment_graph(
    uvn_id=registry.uvn_id,
    deployment=registry.backbone_vpn_config.deployment,
    output_file=output_file)
  log.warning(f"backbone plot generated: {output_file}")


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
    pass

def cell_agent(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.enable_www = args.www
  agent.enable_systemd = args.systemd
  # HACK set NDDSHOME so that the Connext Python API finds the license file
  import os
  os.environ["NDDSHOME"] = str(agent.root)
  agent.spin(
    max_spin_time=args.max_run_time
    if args.max_run_time >= 0 else None)


def cell_service_enable(args):
  root = args.root or Path.cwd()
  # Load the agent to make sure the directory contains a valid configuration
  agent = CellAgent.load(root)
  CellAgent.generate_services(root=agent.root)
  if args.boot:
    CellAgent.enable_service(agent=args.agent)
  if args.start:
    CellAgent.start_service(agent=args.agent)


def cell_service_disable(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  CellAgent.delete_services()


def cell_net_up(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.start()


def cell_net_down(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.stop()


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
    # required=True,
    type=Path)

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



def main():
  #############################################################################
  # define arguments parser
  #############################################################################
  parser = argparse.ArgumentParser()
  parser.set_defaults(cmd=None)

  subparsers = parser.add_subparsers(help="Top-level Commands")


  #############################################################################
  # uno define ...
  #############################################################################
  cmd_define = subparsers.add_parser("define",
    help="Create a new UVN, add cells, add particles.")
  subparsers_define = cmd_define.add_subparsers(help="UVN definition")

  #############################################################################
  # uno define uvn ...
  #############################################################################
  cmd_define_uvn = subparsers_define.add_parser("uvn",
    help="Create a new UVN.")
  cmd_define_uvn.set_defaults(
    cmd=registry_configure,
    update=False)

  cmd_define_uvn.add_argument("name",
    help="A unique name for the UVN.")

  _define_registry_config_args(cmd_define_uvn, owner_id_required=True)
  registry_common_args(cmd_define_uvn)

  #############################################################################
  # uno define cell ...
  #############################################################################
  cmd_define_cell = subparsers_define.add_parser("cell",
    help="Add a new cell to the UVN.")
  cmd_define_cell.set_defaults(
    cmd=registry_cell,
    update=False)

  cmd_define_cell.add_argument("name",
    help="A unique name for the cell.")

  _define_cell_config_args(cmd_define_cell)
  registry_common_args(cmd_define_cell)

  #############################################################################
  # uno define particle ...
  #############################################################################
  cmd_define_particle = subparsers_define.add_parser("particle",
    help="Add a new particle to the UVN.")
  cmd_define_particle.set_defaults(
    cmd=registry_particle,
    update=False)

  cmd_define_particle.add_argument("name",
    help="A unique name for the particle.")

  _define_particle_config_args(cmd_define_particle)
  registry_common_args(cmd_define_particle)


  #############################################################################
  # uno config ...
  #############################################################################
  cmd_config = subparsers.add_parser("config",
    help="Modify the configuration of the UVN, cells, particles.")
  subparsers_config = cmd_config.add_subparsers(help="UVN configuration")


  #############################################################################
  # uno config uvn ...
  #############################################################################
  cmd_config_uvn = subparsers_config.add_parser("uvn",
    help="Update the UVN's configuration.")
  cmd_config_uvn.set_defaults(
    cmd=registry_configure,
    update=True)

  _define_registry_config_args(cmd_config_uvn)
  registry_common_args(cmd_config_uvn)

  #############################################################################
  # uno config cell ...
  #############################################################################
  cmd_config_cell = subparsers_config.add_parser("cell",
    help="Update a cell's configuration.")
  cmd_config_cell.set_defaults(
    cmd=registry_cell,
    update=True)

  cmd_config_cell.add_argument("name",
    help="The cell's unique name.")

  _define_cell_config_args(cmd_config_cell)
  registry_common_args(cmd_config_cell)

  #############################################################################
  # uno config particle ...
  #############################################################################
  cmd_config_particle = subparsers_config.add_parser("particle",
    help="Add a new particle to the UVN.")
  cmd_config_particle.set_defaults(
    cmd=registry_particle,
    update=True)

  cmd_config_particle.add_argument("name",
    help="The particle's unique name.")

  _define_particle_config_args(cmd_config_particle)
  registry_common_args(cmd_config_particle)

  #############################################################################
  # uno redeploy ...
  #############################################################################
  cmd_redeploy = subparsers.add_parser("redeploy",
    help="Update the UVN configuration with a new backbone deployment.")
  cmd_redeploy.set_defaults(cmd=registry_redeploy)
  _define_deployment_args(cmd_redeploy)
  registry_common_args(cmd_redeploy)
  
  
  #############################################################################
  # uno sync ...
  #############################################################################
  cmd_sync = subparsers.add_parser("sync",
    help="Push current configuration to cell agents.")
  cmd_sync.set_defaults(cmd=registry_sync)

  _define_sync_args(cmd_sync)
  registry_common_args(cmd_sync)


  #############################################################################
  # uno plot
  #############################################################################
  cmd_plot = subparsers.add_parser("plot",
    help="Generate an image of the current backbone deployment.")
  cmd_plot.set_defaults(cmd=registry_plot)

  cmd_plot.add_argument("-o", "--output",
    help="Save the generated image to a custom path.",
    default=None,
    type=Path)

  registry_common_args(cmd_plot)


  #############################################################################
  # uno cell ...
  #############################################################################
  cmd_cell = subparsers.add_parser("cell",
    help="Perform operation on a deployed cell.")
  subparsers_cell = cmd_cell.add_subparsers(help="Cell operations")


  #############################################################################
  # uno cell install ...
  #############################################################################
  cmd_cell_install = subparsers_cell.add_parser("install",
    help="Install a cell agent package.")
  cmd_cell_install.set_defaults(
    cmd=cell_bootstrap,
    update=False)

  cmd_cell_install.add_argument("package",
    help="Package file to install.",
    type=Path)

  registry_common_args(cmd_cell_install)

  #############################################################################
  # uno cell update ...
  #############################################################################
  cmd_cell_update = subparsers_cell.add_parser("update",
    help="Update an existing cell agent with a new package.")
  cmd_cell_update.set_defaults(
    cmd=cell_bootstrap,
    update=True)

  cmd_cell_update.add_argument("package",
    help="New package file to install.",
    type=Path)

  registry_common_args(cmd_cell_update)

  #############################################################################
  # uno cell agent ...
  #############################################################################
  cmd_cell_agent = subparsers_cell.add_parser("agent",
    help="Start a UVN cell agent.")
  cmd_cell_agent.set_defaults(cmd=cell_agent)
  registry_common_args(cmd_cell_agent)

  cmd_cell_agent.add_argument("-t", "--max-run-time",
    metavar="SECONDS",
    help="Maximum time to run.",
    default=-1,
    type=int)
  
  cmd_cell_agent.add_argument("-W", "--www",
    default=False,
    action="store_true",
    help="Start a webserver to serve the agent's status.")

  cmd_cell_agent.add_argument("--systemd",
    # help="Start the agent with support for Systemd. Used when the agent is installed as a service.",
    help=argparse.SUPPRESS,
    default=False,
    action="store_true")

  #############################################################################
  # uno cell net ...
  #############################################################################
  cmd_cell_net = subparsers_cell.add_parser("net",
    help="Control the cell's network services.")
  subparsers_cell_net = cmd_cell_net.add_subparsers(help="Cell network operations")

  #############################################################################
  # uno cell net up
  #############################################################################
  cmd_cell_net_up = subparsers_cell_net.add_parser("up",
    help="Enable all system services required to connect the cell to the UVN.")
  cmd_cell_net_up.set_defaults(cmd=cell_net_up)

  registry_common_args(cmd_cell_net_up)

  #############################################################################
  # uno cell net down
  #############################################################################
  cmd_cell_net_down = subparsers_cell_net.add_parser("down",
    help="Stop all system services that the cell uses to connect the UVN.")
  cmd_cell_net_down.set_defaults(cmd=cell_net_down)

  registry_common_args(cmd_cell_net_down)


  #############################################################################
  # uno cell service ...
  #############################################################################
  cmd_cell_service = subparsers_cell.add_parser("service",
    help="Install and control the cell as a systemd service.")
  subparsers_service = cmd_cell_service.add_subparsers(help="Systemd service configuration")


  #############################################################################
  # uno cell service install ...
  #############################################################################
  cmd_cell_service_enable = subparsers_service.add_parser("install",
    help="Install the cell as a systemd service.")
  cmd_cell_service_enable.set_defaults(
    cmd=cell_service_enable)

  cmd_cell_service_enable.add_argument("-a", "--agent",
    help="Run the cell agent as a service instead of just starting network services.",
    default=False,
    action="store_true")

  cmd_cell_service_enable.add_argument("-s", "--start",
    help="Start the service after installing it..",
    default=False,
    action="store_true")

  cmd_cell_service_enable.add_argument("-b", "--boot",
    help="Enable the service at boot",
    default=False,
    action="store_true")

  registry_common_args(cmd_cell_service_enable)


  #############################################################################
  # uno cell service remove ...
  #############################################################################
  cmd_cell_service_disable = subparsers_service.add_parser("remove",
    help="Disable the cell from being available as a systemd service.")
  cmd_cell_service_disable.set_defaults(
    cmd=cell_service_disable)

  registry_common_args(cmd_cell_service_disable)


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

  try:
    cmd(args)
  except KeyboardInterrupt:
    pass
