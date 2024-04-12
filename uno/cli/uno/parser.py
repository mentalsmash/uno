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
import argparse
import ipaddress
from pathlib import Path

from uno.registry.timing_profile import TimingProfile
from uno.registry.deployment_strategy import DeploymentStrategyKind
from uno.registry.cloud import CloudProvider

from ..cli_helpers import cli_command_group, cli_command
from .cmd_registry import (
  registry_define_uvn,
  registry_define_cell,
  registry_define_particle,
  registry_config_uvn,
  registry_config_cell,
  registry_config_particle,
  registry_rekey_uvn,
  registry_rekey_cell,
  registry_rekey_particle,
  registry_delete_cell,
  registry_delete_particle,
  registry_ban_cell,
  registry_ban_particle,
  registry_unban_cell,
  registry_unban_particle,
  registry_redeploy,
  registry_define_user,
  registry_config_user,
  registry_delete_user,
  registry_ban_user,
  registry_unban_user,
  registry_export_cloud,
  registry_notify_cell,
  registry_notify_particle,
  registry_notify_user,
  registry_notify_uvn,
)
from .cmd_agent import (
  agent_sync,
  agent_run,
  agent_service_install,
  agent_service_remove,
  agent_service_down,
  agent_service_up,
  agent_service_status,
  agent_install,
  agent_install_cloud,
  agent_update,
)


def _parser_args_config(parser: argparse._SubParsersAction):
  parser.add_argument(
    "-U",
    "--update",
    help="Update the configuration to the specified values, otherwise print the current value.",
    default=False,
    action="store_true",
  )


def _parser_args_registry(parser: argparse._SubParsersAction, owner_id_required: bool = False):
  parser.add_argument(
    "-o",
    "--owner",
    metavar="OWNER",
    required=owner_id_required,
    help="'NAME <EMAIL>', or just 'EMAIL', of the UVN's administrator.",
  )

  parser.add_argument(
    "-a",
    "--address",
    # required=True,
    help="The public address for the UVN registry.",
  )

  parser.add_argument(
    "--timing-profile",
    default=None,
    choices=[v.name.lower().replace("_", "-") for v in TimingProfile],
    help="Timing profile to use.",
  )

  parser.add_argument("--disable-root-vpn", help="", default=False, action="store_true")

  parser.add_argument("--root-vpn-push-port", metavar="PORT", help="", default=None, type=int)

  parser.add_argument("--root-vpn-pull-port", metavar="PORT", help="", default=None, type=int)

  parser.add_argument(
    "--root-vpn-subnet", metavar="SUBNET", help="", default=None, type=ipaddress.IPv4Network
  )

  parser.add_argument("--root-vpn-mtu", metavar="MTU", help="", default=None, type=int)

  parser.add_argument("--disable-particles-vpn", help="", default=False, action="store_true")

  parser.add_argument("--particles-vpn-port", metavar="PORT", help="", default=None, type=int)

  parser.add_argument(
    "--particles-vpn-subnet", metavar="SUBNET", help="", default=None, type=ipaddress.IPv4Network
  )

  parser.add_argument("--particles-vpn-mtu", metavar="MTU", help="", default=None, type=int)

  parser.add_argument("--backbone-vpn-port", metavar="PORT", help="", default=None, type=int)

  parser.add_argument(
    "--backbone-vpn-subnet", metavar="SUBNET", help="", default=None, type=ipaddress.IPv4Network
  )

  parser.add_argument("--backbone-vpn-mtu", metavar="MTU", help="", default=None, type=int)

  # parser.add_argument("-L", "--rti-license",
  #   metavar="FILE",
  #   help="Path to a valid RTI license file to be used by the UVN agents.",
  #   default=None,
  #   type=Path)

  parser.add_argument(
    "-p", "--password", metavar="PASSWORD", help="A password for the UVN's owner.", default=None
  )

  parser.add_argument(
    "--dds-domain",
    metavar="DOMAIN_ID",
    help="Custom DDS Domain ID to use for agent communication.",
    default=None,
    type=int,
  )

  parser.add_argument(
    "--enable-dds-security",
    help="Use DDS Security features to procet agent communication. Requires RTI Connext DDS to be installed and loaded in the agent's environment.",
    default=False,
    action="store_true",
  )


def _parser_args_print(parser):
  parser.add_argument(
    "-P", "--print", default=False, action="store_true", help="Print UVN configuration to stdout."
  )
  parser.add_argument(
    "-Q",
    "--query",
    default=None,
    help="A query expression to select parts of the printed data structure.",
  )
  parser.add_argument(
    "-J",
    "--json",
    default=False,
    action="store_true",
    help="Print result in JSON format instead of YAML.",
  )


def _parser_args_deployment(parser):
  parser.add_argument(
    "-S",
    "--strategy",
    help="Algorithm used to generate the UVN backbone's deployment map.",
    default=None,
    choices=[k.name.lower().replace("_", "-") for k in DeploymentStrategyKind],
  )

  parser.add_argument(
    "-D",
    "--strategy-args",
    metavar="YAML",
    help="A YAML file or an inline string specifying custom arguments for the selected deployment strategy.",
    default=None,
  )


def _parser_args_cell(parser):
  parser.add_argument(
    "-a",
    "--address",
    # required=True,
    default=None,
    help="The public address for the UVN cell.",
  )

  parser.add_argument(
    "-o",
    "--owner",
    metavar="OWNER",
    help="'NAME <EMAIL>', or just 'EMAIL', of the cell's administrator.",
  )

  parser.add_argument(
    "-N",
    "--network",
    metavar="A.B.C.D/n",
    default=[],
    action="append",
    type=ipaddress.IPv4Network,
    help="IP subnetwork that the cell will attach to the UVN. Repeat to attach multiple networks.",
  )

  parser.add_argument(
    "--disable-particles-vpn",
    help="Disable particles VPN for this cell.",
    default=False,
    action="store_true",
  )

  parser.add_argument(
    "--httpd-port",
    metavar="PORT",
    help="Port used by the cell's agent to serve HTTPS requests.",
    default=None,
    type=int,
  )


def _parser_args_particle(parser):
  parser.add_argument(
    "-o",
    "--owner",
    metavar="OWNER",
    help="'NAME <EMAIL>', or just 'EMAIL', of the particle's administrator.",
  )


def _parser_args_user(parser):
  parser.add_argument(
    "-p", "--password", metavar="PASSWORD", help="A password for user.", default=None
  )
  parser.add_argument("-n", "--name", metavar="NAME", help="A name for the user.", default=None)


def _parser_args_generate(parser):
  parser.add_argument(
    "-g",
    "--generate",
    help="Force operation to regenerate files even if no changes were detected.",
    default=False,
    action="store_true",
  )


def _parser_args_sync(parser):
  parser.add_argument(
    "-C",
    "--consistent-config",
    help="Wait only until all cell agents have a consistent,"
    " updated, configuration, instead of waiting until the UVN is fully"
    " routed.",
    default=False,
    action="store_true",
  )

  parser.add_argument(
    "-t",
    "--max-wait-time",
    metavar="SECONDS",
    help="Maximum time to wait for cells agents and UVN to become consistent."
    " Default: %(default)s sec",
    default=3600,
    type=int,
  )


def _parser_args_cloud_provider(parser: argparse._SubParsersAction):
  parser.add_argument(
    "--cloud-provider",
    help="Cloud provider plugin to use.",
    choices=sorted(CloudProvider.Plugins.keys()),
    required=True,
  )

  parser.add_argument(
    "--cloud-provider-args",
    help="Arguments passed to the cloud provider plugin. The value must be an inline JSON/YAML dictionary or the path of a file containing one.",
    default=None,
  )


def _parser_notify(parser: argparse._SubParsersAction):
  parser.add_argument("-S", "--subject", help="Message subject", required=True)

  parser.add_argument("-B", "--body", help="Message body", required=True)

  _parser_args_cloud_provider(parser)


def _empty_config(parsed_values: dict) -> bool:
  def _check_recur(cur: dict | list) -> None:
    if isinstance(cur, dict):
      values = cur.values()
    else:
      values = cur
    for v in values:
      if isinstance(v, (dict, list)):
        empty = _check_recur(v)
        if not empty:
          return False
      elif v is not None:
        # Found a non-null value
        return False
    return True

  return _check_recur(parsed_values)


def _config_cloud_provider(args: argparse.Namespace) -> dict | None:
  cloud_provider_args = getattr(args, "cloud_provider_args", None)
  result = {
    "class": getattr(args, "cloud_provider", None),
    "args": _yaml_load_inline(cloud_provider_args) if cloud_provider_args else None,
  }
  if _empty_config(result):
    return None
  else:
    return result


def _config_notify(args: argparse.Namespace) -> dict | None:
  result = {
    "subject": getattr(args, "subject", None),
    "body": getattr(args, "body", None),
  }
  if _empty_config(result):
    return None
  else:
    return result


def _config_args_registry(args: argparse.Namespace) -> dict | None:
  uvn_spec = getattr(args, "spec", None)
  if uvn_spec:
    uvn_spec = _yaml_load_inline(uvn_spec)
  result = {
    "cloud_provider": _config_cloud_provider(args),
    "uvn": {
      "address": getattr(args, "address", None),
      "settings": {
        "timing_profile": getattr(args, "timing_profile", None),
        "enable_particles_vpn": False if getattr(args, "disable_particles_vpn", False) else None,
        "enable_root_vpn": False if getattr(args, "disable_root_vpn", False) else None,
        "enable_dds_security": True if getattr(args, "enable_dds_security", False) else None,
        "dds_domain": getattr(args, "dds_domain", None),
        "deployment": {
          "strategy": getattr(args, "strategy", None),
          "strategy_args": getattr(args, "strategy_args", None),
        },
        "root_vpn": {
          "port": getattr(args, "root_vpn_pull_port", None),
          "peer_port": getattr(args, "root_vpn_push_port", None),
          "subnet": getattr(args, "root_vpn_subnet", None),
          "peer_mtu": getattr(args, "root_vpn_mtu", None),
        },
        "particles_vpn": {
          "port": getattr(args, "particles_vpn_port", None),
          "subnet": getattr(args, "particles_vpn_subnet", None),
          "peer_mtu": getattr(args, "particles_vpn_mtu", None),
        },
        "backbone_vpn": {
          "port": getattr(args, "backbone_vpn_port", None),
          "subnet": getattr(args, "backbone_vpn_subnet", None),
          "peer_mtu": getattr(args, "backbone_vpn_mtu", None),
        },
      },
    },
    "uvn_spec": uvn_spec,
  }
  if _empty_config(result):
    return None
  else:
    return result


def _config_args_cell(args: argparse.Namespace) -> dict | None:
  allowed_lans = getattr(args, "network", [])
  if getattr(args, "delete_networks", False):
    allowed_lans = []
  elif not allowed_lans:
    allowed_lans = None
  result = {
    "address": getattr(args, "address", None),
    "settings": {
      "enable_particles_vpn": False if getattr(args, "disable_particles_vpn", False) else None,
      "httpd_port": getattr(args, "httpd_port", None),
      "location": getattr(args, "address", None),
    },
    "allowed_lans": allowed_lans,
  }
  if _empty_config(result):
    return None
  else:
    return result


def _config_args_particle(args: argparse.Namespace) -> dict | None:
  return None


def _config_args_user(args: argparse.Namespace) -> dict | None:
  result = {
    "password": getattr(args, "password", None),
    "name": getattr(args, "name", None),
  }
  if _empty_config(result):
    return None
  else:
    return result


def _yaml_load_inline(val: str | Path) -> dict:
  import yaml

  # Try to interpret the string as a Path
  yml_val = val
  args_file = Path(val)
  if args_file.is_file():
    yml_val = args_file.read_text()
  # Interpret the string as inline YAML
  if not isinstance(yml_val, str):
    raise ValueError("failed to load yaml", val)
  return yaml.safe_load(yml_val)


def _config_cloud_storage(args: argparse.Namespace) -> dict | None:
  storage_args = getattr(args, "cloud_storage_args", None)
  result = _yaml_load_inline(storage_args) if storage_args else {}
  if _empty_config(result):
    return None
  else:
    return result


def uno_parser(parser: argparse.ArgumentParser):
  subparsers = parser.add_subparsers(help="Top-level Commands")

  #############################################################################
  # uno define ...
  #############################################################################
  grp_define = cli_command_group(
    subparsers, "define", title="UVN Definition", help="Create a new UVN, add cells, add particles."
  )

  #############################################################################
  # uno define uvn ...
  #############################################################################
  cmd_define_uvn = cli_command(grp_define, "uvn", cmd=registry_define_uvn, help="Create a new UVN.")

  cmd_define_uvn.add_argument("name", help="A unique name for the UVN.")

  cmd_define_uvn.add_argument(
    "-s",
    "--spec",
    help="Define UVN elements from the specified configuration. "
    "The value must be an inline JSON/YAML dictionary or the path of a file containing one.",
  )

  _parser_args_registry(cmd_define_uvn, owner_id_required=True)
  _parser_args_deployment(cmd_define_uvn)
  _parser_args_print(cmd_define_uvn)

  #############################################################################
  # uno define cell ...
  #############################################################################
  cmd_define_cell = cli_command(
    grp_define, "cell", cmd=registry_define_cell, help="Add a new cell to the UVN."
  )

  cmd_define_cell.add_argument("name", help="A unique name for the cell.")

  _parser_args_cell(cmd_define_cell)
  _parser_args_print(cmd_define_cell)

  #############################################################################
  # uno define particle ...
  #############################################################################
  cmd_define_particle = cli_command(
    grp_define, "particle", cmd=registry_define_particle, help="Add a new particle to the UVN."
  )

  cmd_define_particle.add_argument("name", help="A unique name for the particle.")

  _parser_args_particle(cmd_define_particle)
  _parser_args_print(cmd_define_particle)

  #############################################################################
  # uno define user ...
  #############################################################################
  cmd_define_user = cli_command(
    grp_define, "user", cmd=registry_define_user, help="Add a new user to the UVN."
  )

  cmd_define_user.add_argument("email", help="A unique email for the user.")

  _parser_args_user(cmd_define_user)
  _parser_args_print(cmd_define_user)

  #############################################################################
  # uno config ...
  #############################################################################
  grp_config = cli_command_group(
    subparsers,
    "config",
    title="UVN configuration",
    help="Modify the configuration of the UVN, cells, particles.",
  )

  #############################################################################
  # uno config uvn ...
  #############################################################################
  cmd_config_uvn = cli_command(
    grp_config, "uvn", cmd=registry_config_uvn, help="Update the UVN's configuration."
  )

  _parser_args_config(cmd_config_uvn)
  _parser_args_print(cmd_config_uvn)
  _parser_args_registry(cmd_config_uvn)
  _parser_args_deployment(cmd_config_uvn)
  _parser_args_generate(cmd_config_uvn)

  #############################################################################
  # uno config cell ...
  #############################################################################
  cmd_config_cell = cli_command(
    grp_config, "cell", cmd=registry_config_cell, help="Update a cell's configuration."
  )

  cmd_config_cell.add_argument("name", help="The cell's unique name.")

  _parser_args_config(cmd_config_cell)
  _parser_args_print(cmd_config_cell)
  _parser_args_cell(cmd_config_cell)
  _parser_args_generate(cmd_config_cell)

  #############################################################################
  # uno config particle ...
  #############################################################################
  cmd_config_particle = cli_command(
    grp_config, "particle", cmd=registry_config_particle, help="Update a particle's configuration."
  )

  cmd_config_particle.add_argument("name", help="The particle's unique name.")

  _parser_args_config(cmd_config_particle)
  _parser_args_print(cmd_config_particle)
  _parser_args_particle(cmd_config_particle)
  _parser_args_generate(cmd_config_particle)

  #############################################################################
  # uno config user ...
  #############################################################################
  cmd_config_user = cli_command(
    grp_config, "user", cmd=registry_config_user, help="Update a user's configuration."
  )

  cmd_config_user.add_argument("email", help="The user's unique email.")

  _parser_args_config(cmd_config_user)
  _parser_args_print(cmd_config_user)
  _parser_args_user(cmd_config_user)
  _parser_args_generate(cmd_config_user)

  #############################################################################
  # uno redeploy ...
  #############################################################################
  cmd_redeploy = cli_command(
    subparsers,
    "redeploy",
    cmd=registry_redeploy,
    help="Update the UVN configuration with a new backbone deployment.",
  )

  _parser_args_deployment(cmd_redeploy)

  #############################################################################
  # uno sync ...
  #############################################################################
  cmd_sync = cli_command(
    subparsers, "sync", cmd=agent_sync, help="Push current configuration to cell agents."
  )

  _parser_args_sync(cmd_sync)

  #############################################################################
  # uno install ...
  #############################################################################
  cmd_install = cli_command(
    subparsers, "install", cmd=agent_install, help="Install an agent package."
  )

  cmd_install.add_argument("package", help="Package file to install.", type=Path)

  #############################################################################
  # uno install-cloud ...
  #############################################################################
  cmd_install_cloud = cli_command(
    subparsers,
    "install-cloud",
    cmd=agent_install_cloud,
    help="Install an agent package by dowloading it from a cloud storage.",
  )

  _parser_args_cloud_provider(cmd_install_cloud)

  cmd_install_cloud.add_argument("-u", "--uvn", help="Name of the UVN", required=True)

  cmd_install_cloud.add_argument("-c", "--cell", help="Name of the cell", required=True)

  cmd_install_cloud.add_argument(
    "--cloud-storage-args",
    help="Arguments passed to the storage component of the cloud provider plugin. "
    "The value must be an inline JSON/YAML dictionary or the path of a file containing one.",
    default=None,
  )

  #############################################################################
  # uno export-cloud ...
  #############################################################################
  cmd_export_cloud = cli_command(
    subparsers,
    "export-cloud",
    cmd=registry_export_cloud,
    help="Export the registry to cloud storage.",
  )

  _parser_args_cloud_provider(cmd_export_cloud)

  cmd_export_cloud.add_argument(
    "--cloud-storage-args",
    help="Arguments passed to the storage component of the cloud provider plugin. "
    "The value must be an inline JSON/YAML dictionary or the path of a file containing one.",
    default=None,
  )

  #############################################################################
  # uno update ...
  #############################################################################
  cmd_update = cli_command(
    subparsers,
    "update",
    cmd=agent_update,
    help="Update an existing cell agent by regenerating its configuration.",
  )

  cmd_update.add_argument(
    "-p", "--package", help="Optionally, a new package file to install.", type=Path, default=None
  )

  #############################################################################
  # uno service ...
  #############################################################################
  grp_service = cli_command_group(
    subparsers,
    "service",
    title="Systemd service configuration",
    help="Install and control the UVN connection (and cell agent) as a systemd service.",
  )

  #############################################################################
  # uno service install ...
  #############################################################################
  cmd_service_enable = cli_command(
    grp_service,
    "install",
    cmd=agent_service_install,
    help="Install the uvn-net and uvn-agent systemd services, and enable them for the selected directory.",
  )

  cmd_service_enable.add_argument(
    "-s",
    "--start",
    help="Start the service after installing it..",
    default=False,
    action="store_true",
  )

  # cmd_service_enable.add_argument("-a", "--agent",
  #   help="Run the uvn-agent service instead of uvn-net.",
  #   default=False,
  #   action="store_true")

  cmd_service_enable.add_argument(
    "-b", "--boot", help="Enable the service at boot", default=False, action="store_true"
  )

  #############################################################################
  # uno service remove ...
  #############################################################################
  # cmd_service_disable
  cli_command(
    grp_service,
    "remove",
    cmd=agent_service_remove,
    help="Disable the uvn-net and uvn-agent systemd services. Stop them if they are active.",
  )

  #############################################################################
  # uno service up ...
  #############################################################################
  cmd_service_up = cli_command(
    grp_service, "up", cmd=agent_service_up, help="Start agent services as Systemd units."
  )

  cmd_service_up.add_argument(
    "service",
    nargs="?",
    # default=[],
    help="Start all services up to the specified one.",
  )

  #############################################################################
  # uno service down ...
  #############################################################################
  cmd_service_down = cli_command(
    grp_service, "down", cmd=agent_service_down, help="Stop agent services run as Systemd units."
  )

  cmd_service_down.add_argument(
    "service",
    nargs="?",
    # default=[],
    help="Stop all services down to the specified one.",
  )

  #############################################################################
  # uno service status
  #############################################################################
  # cmd_service_statis
  cli_command(
    grp_service,
    "status",
    cmd=agent_service_status,
    help="Check the status of the agent services run as Systemd units.",
  )

  #############################################################################
  # uno agent ..
  #############################################################################
  cmd_agent = cli_command(
    subparsers,
    "agent",
    cmd=agent_run,
    help="Start an agent for the selected directory (either cell or registry).",
  )

  # cmd_agent.add_argument("-t", "--max-run-time",
  #   metavar="SECONDS",
  #   help="Run the agent for the specified time instead of indefinitely.",
  #   default=None,
  #   type=int)

  cmd_agent.add_argument("--systemd", help=argparse.SUPPRESS, default=False, action="store_true")

  cmd_agent.add_argument("--registry", help=argparse.SUPPRESS, default=False, action="store_true")

  #############################################################################
  # uno ban ...
  #############################################################################
  grp_ban = cli_command_group(
    subparsers, "ban", title="Banishing commands", help="Exclude a particle or a cell from the UVN."
  )

  #############################################################################
  # uno ban cell
  #############################################################################
  cmd_ban_cell = cli_command(
    grp_ban, "cell", cmd=registry_ban_cell, help="Exclude a cell from the UVN."
  )

  cmd_ban_cell.add_argument("name", help="The cell's unique name.")

  #############################################################################
  # uno ban particle
  #############################################################################
  cmd_ban_particle = cli_command(
    grp_ban, "particle", cmd=registry_ban_particle, help="Exclude a particle from the UVN."
  )

  cmd_ban_particle.add_argument("name", help="The particle's unique name.")

  #############################################################################
  # uno ban user
  #############################################################################
  cmd_ban_user = cli_command(
    grp_ban, "user", cmd=registry_ban_user, help="Exclude a user from the UVN."
  )

  cmd_ban_user.add_argument("email", help="The user's unique email.")

  #############################################################################
  # uno unban ...
  #############################################################################
  grp_unban = cli_command_group(
    subparsers,
    "unban",
    title="Unbanishing commands",
    help="Allow a particle or a cell back into the UVN.",
  )

  #############################################################################
  # uno unban cell
  #############################################################################
  cmd_unban_cell = cli_command(
    grp_unban, "cell", cmd=registry_unban_cell, help="Allow a cell back into the UVN."
  )

  cmd_unban_cell.add_argument("name", help="The cell's unique name.")

  #############################################################################
  # uno unban particle
  #############################################################################
  cmd_unban_particle = cli_command(
    grp_unban, "particle", cmd=registry_unban_particle, help="Allow a particle back into the UVN."
  )

  cmd_unban_particle.add_argument("name", help="The particle's unique name.")

  #############################################################################
  # uno unban user
  #############################################################################
  cmd_unban_user = cli_command(
    grp_unban, "user", cmd=registry_unban_user, help="Allow a user back into the UVN."
  )

  cmd_unban_user.add_argument("email", help="The user's unique email.")

  #############################################################################
  # uno delete ...
  #############################################################################
  grp_del = cli_command_group(
    subparsers,
    "delete",
    title="Unbanishing commands",
    help="Permanently delete a particle or a cell.",
  )

  #############################################################################
  # uno delete cell
  #############################################################################
  cmd_del_cell = cli_command(
    grp_del, "cell", cmd=registry_delete_cell, help="Delete a cell from the UVN."
  )

  cmd_del_cell.add_argument("name", help="The cell's unique name.")

  #############################################################################
  # uno delete particle
  #############################################################################
  cmd_del_particle = cli_command(
    grp_del, "particle", cmd=registry_delete_particle, help="Delete a particle from the UVN."
  )

  cmd_del_particle.add_argument("name", help="The particle's unique name.")

  #############################################################################
  # uno delete user
  #############################################################################
  cmd_del_user = cli_command(
    grp_del, "user", cmd=registry_delete_user, help="Delete a user from the UVN."
  )

  cmd_del_user.add_argument("email", help="The user's unique email.")

  # #############################################################################
  # # uno encrypt ...
  # #############################################################################
  # cmd_encrypt = cli_command(parser, "encrypt",
  #   cmd=dispatch_action,
  #   help="Encrypt a file for a UVN cell.",
  #   defaults={"action": "encrypt"})

  # cmd_encrypt.add_argument("-c", "--cell",
  #   default=None,
  #   help="Name of the cell receiving the file.")

  # cmd_encrypt.add_argument("-in", "--input",
  #   type=Path,
  #   required=True,
  #   help="File to encrypt.")

  # cmd_encrypt.add_argument("-out", "--output",
  #   type=Path,
  #   required=True,
  #   help="File to generate.")

  # #############################################################################
  # # uno decrypt ...
  # #############################################################################
  # cmd_decrypt = cli_command(parser, "decrypt",
  #   cmd=dispatch_action,
  #   help="Decrypt a file received by a UVN cell.",
  #   defaults={"action": "decrypt"})

  # cmd_decrypt.add_argument("-c", "--cell",
  #   default=None,
  #   help="Name of the cell receiving the file.")

  # cmd_decrypt.add_argument("-in", "--input",
  #   type=Path,
  #   required=True,
  #   help="File to encrypt.")

  # cmd_decrypt.add_argument("-out", "--output",
  #   type=Path,
  #   required=True,
  #   help="File to generate.")

  #############################################################################
  # uno rekey ...
  #############################################################################
  grp_rekey = cli_command_group(
    subparsers,
    "rekey",
    title="Rekeying commands",
    help="Regenerate the key material for a particle or a cell.",
  )

  #############################################################################
  # uno rekey particle
  #############################################################################
  cmd_rekey_particle = cli_command(
    grp_rekey,
    "particle",
    cmd=registry_rekey_particle,
    help="Regenerate the key material for a particle.",
  )

  cmd_rekey_particle.add_argument("name", help="The particle's unique name.")

  cmd_rekey_particle.add_argument(
    "-c",
    "--cell",
    metavar="NAME",
    help="Restrict the rekeying to the specified cell. Repeat to select multiple.",
    default=[],
    action="append",
  )

  #############################################################################
  # uno rekey cell
  #############################################################################
  cmd_rekey_cell = cli_command(
    grp_rekey, "cell", cmd=registry_rekey_cell, help="Regenerate the key material for a cell."
  )

  cmd_rekey_cell.add_argument("name", help="The cell's unique name.")

  cmd_rekey_cell.add_argument(
    "-R", "--root-vpn", help="Regenerate the Root VPN key.", default=False, action="store_true"
  )

  cmd_rekey_cell.add_argument(
    "-P",
    "--particles-vpn",
    help="Regenerate all Particles VPN keys.",
    default=False,
    action="store_true",
  )

  #############################################################################
  # uno rekey uvn
  #############################################################################
  cmd_rekey_uvn = cli_command(
    grp_rekey, "uvn", cmd=registry_rekey_uvn, help="Regenerate the key material for the uvn."
  )

  cmd_rekey_uvn.add_argument(
    "-R", "--root-vpn", help="Regenerate the Root VPN keys.", default=False, action="store_true"
  )

  cmd_rekey_uvn.add_argument(
    "-P",
    "--particles-vpn",
    help="Regenerate all Particles VPN keys.",
    default=False,
    action="store_true",
  )

  #############################################################################
  # uno notify ...
  #############################################################################
  grp_notify = cli_command_group(
    subparsers, "notify", title="Notification commands", help="Send a message to a UVN user."
  )

  #############################################################################
  # uno notify user ...
  #############################################################################
  cmd_notify_user = cli_command(
    grp_notify, "user", cmd=registry_notify_user, help="Send a message to a UVN user."
  )

  cmd_notify_user.add_argument("email", help="The user's unique email.")

  _parser_notify(cmd_notify_user)

  #############################################################################
  # uno notify cell ...
  #############################################################################
  cmd_notify_cell = cli_command(
    grp_notify, "cell", cmd=registry_notify_cell, help="Send a message to a UVN cell's owner."
  )

  cmd_notify_cell.add_argument("name", help="The cell's unique name.")

  _parser_notify(cmd_notify_cell)

  #############################################################################
  # uno notify particle ...
  #############################################################################
  cmd_notify_particle = cli_command(
    grp_notify,
    "particle",
    cmd=registry_notify_particle,
    help="Send a message to a UVN particle's owner.",
  )

  cmd_notify_particle.add_argument("name", help="The particle's unique name.")

  _parser_notify(cmd_notify_particle)

  #############################################################################
  # uno notify uvn ...
  #############################################################################
  cmd_notify_uvn = cli_command(
    grp_notify, "uvn", cmd=registry_notify_uvn, help="Send a message to a UVN's owner."
  )

  _parser_notify(cmd_notify_uvn)

  #############################################################################
  # Automatic parser
  #############################################################################
  parser.set_defaults(
    config_registry=lambda self: _config_args_registry(self),
    config_cell=lambda self: _config_args_cell(self),
    config_particle=lambda self: _config_args_particle(self),
    config_user=lambda self: _config_args_user(self),
    config_cloud_storage=lambda self: _config_cloud_storage(self),
    config_notify=lambda self: _config_notify(self),
  )
