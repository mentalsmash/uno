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
import yaml
from pathlib import Path
import argparse
from typing import Tuple, Optional
import shutil

import ipaddress

from uno.uvn.uvn_id import UvnId, UvnSettings, BackboneVpnSettings, TimingProfile
from uno.uvn.registry import Registry
from uno.uvn.agent import CellAgent
from uno.uvn.registry_agent import RegistryAgent
from uno.uvn.log import set_verbosity, level as log_level, Logger as log
from uno.uvn.deployment import DeploymentStrategyKind
from uno.uvn.time import Timestamp
from uno.uvn.particle import generate_particle_packages
from uno.uvn.graph import backbone_deployment_graph

def parse_id_str(admin: str) -> Tuple[str, str]:
  owner = admin[admin.find("<")+1:admin.rfind(">")].strip()
  owner_name=admin[:admin.find("<")].strip()
  return owner, owner_name


def _load_inline_yaml(val: str) -> dict:
  # Try to interpret the string as a Path
  args_file = Path(val)
  if args_file.is_file():
    return yaml.safe_load(args_file.read_text())
  # Interpret the string as inline YAML
  return yaml.safe_load(val)

###############################################################################
###############################################################################
# Registry Commands
###############################################################################
###############################################################################
def registry_init(args):
  if args.configuration:
    log.activity(f"[REGISTRY] loading UVN configuration: {args.configuration}")
    serialized = yaml.safe_load(args.configuration.read_text())
    uvn_id = UvnId.deserialize(serialized)
  else:
    log.activity(f"[REGISTRY] creating new UVN configuration")
    owner, owner_name = parse_id_str(args.admin)
    uvn_id=UvnId(
      name=args.name,
      address=args.address,
      owner=owner,
      owner_name=owner_name)
    if args.strategy:
      uvn_id.settings.backbone_vpn.deployment_strategy = DeploymentStrategyKind[args.strategy.upper().replace("-", "_")]
    if args.deployment_args:
      uvn_id.settings.backbone_vpn.deployment_strategy_args = _load_inline_yaml(args.deployment_args)
    if args.timing:
      uvn_id.settings.timing_profile = TimingProfile[args.timing.upper().replace("-", "_")]
  log.activity(f"[REGISTRY] UVN configuration:")
  log.activity(yaml.safe_dump(uvn_id.serialize()))
  root = args.root or Path.cwd() / uvn_id.name
  if root.is_dir() and next(root.glob("*"), None) is not None:
    raise RuntimeError("target directory not empty", root)
  root.mkdir(parents=True, exist_ok=True)
  registry = Registry(root=root, uvn_id=uvn_id)
  registry.save_to_disk()
  registry.install_rti_license(args.license)
  log.warning(f"[REGISTRY] initialized: {registry.root}")


def registry_load(args) -> Registry:
  registry = Registry.load(args.root or Path.cwd())
  if getattr(args, "print", False):
    print(yaml.safe_dump(registry.serialize()))
  return registry


def registry_add_cell(args):
  registry = registry_load(args)
  if args.admin:
    owner, owner_name = parse_id_str(args.admin)
  else:
    owner = registry.uvn_id.owner
    owner_name = registry.uvn_id.owner_name
  cell = registry.uvn_id.add_cell(
    name=args.name if args.name is not None else args.address,
    address=args.address,
    owner=owner,
    owner_name=owner_name,
    allowed_lans=args.network,
    **({"enable_particles_vpn": False} if args.no_particles else {}))
  # registry.configure()
  registry.save_to_disk()


def registry_add_particle(args):
  registry = registry_load(args)
  if args.admin:
    owner, owner_name = parse_id_str(args.admin)
  else:
    owner = registry.uvn_id.owner
    owner_name = registry.uvn_id.owner_name
  particle = registry.uvn_id.add_particle(
    name=args.name if args.name is not None else args.address,
    owner=owner,
    owner_name=owner_name)
  # registry.configure()
  registry.save_to_disk()


def registry_deploy(args):
  registry = registry_load(args)

  strategy_args = _load_inline_yaml(args.deployment_args) if args.deployment_args else None
  updated = False
  if args.strategy:
    strategy = DeploymentStrategyKind[args.strategy.upper().replace("-", "_")]
    if registry.uvn_id.settings.backbone_vpn.deployment_strategy != strategy:
      registry.uvn_id.settings.backbone_vpn.deployment_strategy = strategy
      updated = True
      # Reset args (unless the user already provided some)
      if strategy_args is None:
        strategy_args = {}

  if strategy_args is not None:
    registry.uvn_id.settings.backbone_vpn.deployment_strategy_args = strategy_args
    updated = True

  if updated:
    registry.uvn_id.generation_ts = Timestamp.now().format()

  registry.configure()
  registry.save_to_disk()

  if args.push:
    registry_generate_agents(args)


def registry_generate_agents(args, registry: Optional[Registry]=None):
  registry = registry or registry_load(args)

  cells_dir = registry.root / "cells"
  if cells_dir.is_dir():
    import shutil
    shutil.rmtree(cells_dir)  
  CellAgent.generate_all(
    registry,
    cells_dir,
    bootstrap_package=True)

  particles_dir = registry.root / "particles"
  if particles_dir.is_dir():
    import shutil
    shutil.rmtree(particles_dir)  
  generate_particle_packages(
    uvn_id=registry.uvn_id,
    particle_vpn_configs=registry.particles_vpn_configs,
    output_dir=particles_dir)


  if args.push:
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


def registry_check_status(args):
  registry = registry_load(args)
  agent = RegistryAgent(registry)
  agent.spin_until_consistent(
    config_only=args.consistent_config,
    max_spin_time=args.max_wait_time)


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
  agent = CellAgent.bootstrap(
    package=args.package,
    root=args.root,
    system=args.system)


def cell_agent(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.enable_www = args.www
  import os
  os.environ["NDDSHOME"] = str(agent.root)
  agent.spin(
    max_spin_time=args.max_run_time
    if args.max_run_time >= 0 else None)


def cell_install_service(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.generate_service(root)


def cell_start(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.start()


def cell_stop(args):
  root = args.root or Path.cwd()
  agent = CellAgent.load(root)
  agent.stop()


def main():
  #############################################################################
  # define arguments parser
  #############################################################################
  parser = argparse.ArgumentParser()
  parser.set_defaults(cmd=None)

  subparsers = parser.add_subparsers(help="Available Commands")

  #############################################################################
  #############################################################################
  # registry commands
  #############################################################################
  #############################################################################
  cmd_registry = subparsers.add_parser("registry",
    help="Manipulate the UVN's global registry.")
  subparsers_registry = cmd_registry.add_subparsers(help="Registry Commands")


  #############################################################################
  # registry::create
  #############################################################################
  cmd_registry_init = subparsers_registry.add_parser("init",
    help="Initialize a directory with an empty UVN.")
  cmd_registry_init.set_defaults(cmd=registry_init)
  registry_common_args(cmd_registry_init)

  cmd_registry_init.add_argument("-a", "--address",
    # required=True,
    help="The public address for the UVN registry.")

  cmd_registry_init.add_argument("-n", "--name",
    default=None,
    help="A unique name for the UVN. The address will be used if unspecified")

  cmd_registry_init.add_argument("-A", "--admin",
    # required=True,
    metavar="'NAME <EMAIL>'",
    help="Name and email of the UVN's administrator.")

  cmd_registry_init.add_argument("-T", "--timing",
    default=None,
    choices=[v.name.lower().replace("_", "-") for v in TimingProfile],
    help="Timing profile to use.")

  cmd_registry_init.add_argument("-S", "--strategy",
    help="Algorithm used to generate the UVN backbone's deployment map.",
    default=None,
    choices=[k.name.lower().replace("_", "-") for k in DeploymentStrategyKind])

  cmd_registry_init.add_argument("-D", "--deployment-args",
    metavar="YAML",
    help="A YAML file or an inline string specifying custom arguments for the selected deployment strategy.",
    default=None)

  cmd_registry_init.add_argument("-C", "--configuration",
    metavar="YAML",
    type=Path,
    default=None,
    help="Load the whole UVN configuration from the specified YAML (file or inline). Other arguments will be ignored.")

  cmd_registry_init.add_argument("-L", "--license",
    metavar="RTI_LICENSE",
    help="Path to a valid RTI license file to be used by the UVN agents.",
    required=True,
    type=Path)

  # cmd_registry_init.add_argument("-r", "--root",
  #   default=None,
  #   type=Path,
  #   help="Custom root directory for the generated uvn. The directory must not exist or be empty.")


  #############################################################################
  # registry::load
  #############################################################################
  cmd_registry_load = subparsers_registry.add_parser("load",
    help="Load the registry and validate its configuration.")
  cmd_registry_load.set_defaults(cmd=registry_load)
  registry_common_args(cmd_registry_load)

  cmd_registry_load.add_argument("-p", "--print",
    default=False,
    action="store_true",
    help="Print registry configuration to stdout.")


  #############################################################################
  # registry::add_cell
  #############################################################################
  cmd_registry_add_cell = subparsers_registry.add_parser("add-cell",
    help="Add a new cell to the UVN.")
  cmd_registry_add_cell.set_defaults(cmd=registry_add_cell)
  registry_common_args(cmd_registry_add_cell)

  cmd_registry_add_cell.add_argument("-a", "--address",
    # required=True,
    default=None,
    help="The public address for the UVN cell.")

  cmd_registry_add_cell.add_argument("-n", "--name",
    # default=None,
    required=True,
    help="A unique name for the UVN cell.")

  cmd_registry_add_cell.add_argument("-A", "--admin",
    # required=True,
    metavar="'NAME <EMAIL>'",
    help="Name and email of the UVN cell's administrator.")

  cmd_registry_add_cell.add_argument("-N", "--network",
    metavar="A.B.C.D/n",
    default=[],
    action="append",
    type=ipaddress.IPv4Network,
    help="IP subnetwork that the cell will attach to the UVN. Repeat to attach multiple networks.")

  cmd_registry_add_cell.add_argument("--no-particles",
    help="Disable particles VPN for this cell.",
    default=False,
    action="store_true")

  #############################################################################
  # registry::add_particle
  #############################################################################
  cmd_registry_add_particle = subparsers_registry.add_parser("add-particle",
    help="Add a new particle to the UVN.")
  cmd_registry_add_particle.set_defaults(cmd=registry_add_particle)
  registry_common_args(cmd_registry_add_particle)

  cmd_registry_add_particle.add_argument("-n", "--name",
    required=True,
    default=None,
    help="A unique name for the UVN particle.")

  cmd_registry_add_particle.add_argument("-A", "--admin",
    # required=True,
    metavar="'NAME <EMAIL>'",
    help="Name and email of the UVN particle's administrator.")


  #############################################################################
  # registry::deploy
  #############################################################################
  cmd_registry_deploy = subparsers_registry.add_parser("deploy",
    help="Update the UVN configuration with a new backbone deployment.")
  cmd_registry_deploy.set_defaults(cmd=registry_deploy)
  registry_common_args(cmd_registry_deploy)

  cmd_registry_deploy.add_argument("-p", "--push",
    help="Push new deployment to cell agents.",
    default=False,
    action="store_true")
  
  cmd_registry_deploy.add_argument("-C", "--consistent-config",
    help="When pushing, waiting only until all cell agents have a consistent,"
      " updated, configuration, instead of waiting until the UVN is fully"
      " routed.",
    default=False,
    action="store_true")

  cmd_registry_deploy.add_argument("-t", "--max-wait-time",
    metavar="SECONDS",
    help="Maximum time to wait for cells agents and UVN to become consistent."
    " Default: %(default)s sec",
    default=3600,
    type=int)

  cmd_registry_deploy.add_argument("-S", "--strategy",
    help="Algorithm used to generate the UVN backbone's deployment map.",
    default=None,
    choices=[k.name.lower().replace("_", "-") for k in DeploymentStrategyKind])

  cmd_registry_deploy.add_argument("-D", "--deployment-args",
    help="A YAML file or an inline string specifying custom arguments for the selected deployment strategy.",
    default=None)


  #############################################################################
  # registry::generate-agents
  #############################################################################
  cmd_registry_generate_agents = subparsers_registry.add_parser("generate-agents",
    help="Generate packages to deploy individual UVN agents")
  cmd_registry_generate_agents.set_defaults(cmd=registry_generate_agents)
  registry_common_args(cmd_registry_generate_agents)

  cmd_registry_generate_agents.add_argument("-o", "--output-dir",
    help="Directory where to generate agent packages. The directory will be created if it doesn't exist.",
    default=None,
    type=Path)

  cmd_registry_generate_agents.add_argument("-p", "--push",
    help="Push configuration to cell agents.",
    default=False,
    action="store_true")

  cmd_registry_generate_agents.add_argument("-C", "--consistent-config",
    help="When pushing, waiting only until all cell agents have a consistent,"
      " updated, configuration, instead of waiting until the UVN is fully"
      " routed.",
    default=False,
    action="store_true")

  cmd_registry_generate_agents.add_argument("-t", "--max-wait-time",
    metavar="SECONDS",
    help="Maximum time to wait for cells agents and UVN to become consistent."
    " Default: %(default)s sec",
    default=3600,
    type=int)


  #############################################################################
  # registry::check-status
  #############################################################################
  cmd_registry_check_status = subparsers_registry.add_parser("check-status",
    help="Check the status of the UVN and validate its consistency.")
  cmd_registry_check_status.set_defaults(cmd=registry_check_status)
  registry_common_args(cmd_registry_check_status)

  cmd_registry_check_status.add_argument("-C", "--consistent-config",
    help="Waiting only until all cell agents have a consistent configuration,"
      " instead of waiting until the UVN is fully routed.",
    default=False,
    action="store_true")

  cmd_registry_check_status.add_argument("-t", "--max-wait-time",
    metavar="SECONDS",
    help="Maximum time to wait for cells agents and UVN to become consistent."
    " Default: %(default)s sec",
    default=3600,
    type=int)


  #############################################################################
  # registry::plot
  #############################################################################
  cmd_registry_plot = subparsers_registry.add_parser("plot",
    help="Generate an image of the current backbone deployment.")
  cmd_registry_plot.set_defaults(cmd=registry_plot)
  registry_common_args(cmd_registry_plot)

  cmd_registry_plot.add_argument("-o", "--output",
    help="Save the generated image to a custom path.",
    default=None,
    type=Path)


  #############################################################################
  #############################################################################
  # cell commands
  #############################################################################
  #############################################################################
  cmd_cell = subparsers.add_parser("cell",
    help="Manipulate a UVN cell.")
  subparsers_cell = cmd_cell.add_subparsers(help="Cell Commands")

  #############################################################################
  # cell::bootstrap
  #############################################################################
  cmd_cell_bootstrap = subparsers_cell.add_parser("bootstrap",
    help="Install a UVN cell agent.")
  cmd_cell_bootstrap.set_defaults(cmd=cell_bootstrap)
  registry_common_args(cmd_cell_bootstrap)

  cmd_cell_bootstrap.add_argument("package",
    help="Package file for the UVN cell agent.",
    type=Path)

  cmd_cell_bootstrap.add_argument("-s", "--system",
    help="Install the agent as the system agent. The agent configuration will be placed in /etc/uvn, and /etc/init.d/uvn will be created.",
    default=False,
    action="store_true")


  #############################################################################
  # cell::start
  #############################################################################
  cmd_cell_start = subparsers_cell.add_parser("start",
    help="Connect a cell to the UVN.")
  cmd_cell_start.set_defaults(cmd=cell_start)
  registry_common_args(cmd_cell_start)

  #############################################################################
  # cell::stop
  #############################################################################
  cmd_cell_stop = subparsers_cell.add_parser("stop",
    help="Disconnect a cell from the UVN.")
  cmd_cell_stop.set_defaults(cmd=cell_stop)
  registry_common_args(cmd_cell_stop)

  #############################################################################
  # cell::agent
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

  #############################################################################
  # cell::install-service
  #############################################################################
  cmd_cell_install_service = subparsers_cell.add_parser("install-service",
    help="Install a UVN cell agent as a system service.")
  cmd_cell_install_service.set_defaults(cmd=cell_install_service)
  registry_common_args(cmd_cell_install_service)


  #############################################################################
  # parse arguments and run selected command
  #############################################################################
  args = parser.parse_args()

  if args.verbose >= 2:
    set_verbosity(log_level.debug)
  elif args.verbose >= 1:
    set_verbosity(log_level.activity)
  else:
    set_verbosity(log_level.warning)

  cmd = args.cmd
  if cmd is None:
    raise RuntimeError("no command specified")

  cmd(args)