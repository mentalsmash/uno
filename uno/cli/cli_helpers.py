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
from typing import Callable
import argparse
from operator import attrgetter

from uno.core.log import Logger, level as log_level
from uno.core.ask import ask_assume_no, ask_assume_yes

class SortingHelpFormatter(argparse.HelpFormatter):
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



def cli_parser_args_common(parser: argparse._SubParsersAction|argparse.ArgumentParser):
  parser.add_argument("-r", "--root",
    metavar="DIR",
    default=Path.cwd(),
    type=Path,
    help="UVN root directory.")
  parser.add_argument("-v", "--verbose",
    action="count",
    default=0,
    help="Increase output verbosity. Repeat for increased verbosity.")
  parser.add_argument("-q", "--quiet",
    action="count",
    default=False,
    help="Suppress all logger output.")
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



def cli_command_group(parent: argparse._SubParsersAction|argparse.ArgumentParser, name: str, title: str, help: str) -> argparse._SubParsersAction:
  cmd_group = parent.add_parser(name, formatter_class=SortingHelpFormatter, help=help)
  cmd_group_subparsers = cmd_group.add_subparsers(help=title)
  return cmd_group_subparsers


def cli_command(parent: argparse._SubParsersAction|argparse.ArgumentParser, name: str, cmd: Callable[[argparse.Namespace], None], help: str, defaults: dict | None = None) -> argparse._SubParsersAction:
  command = parent.add_parser(name, help=help)
  command.set_defaults(cmd=cmd, **(defaults or {}))
  cli_parser_args_common(command)
  return command


def cli_command_main(define_parser: Callable[[argparse._SubParsersAction], None]):
  parser = argparse.ArgumentParser(
    formatter_class=SortingHelpFormatter)
  define_parser(parser)
  args = parser.parse_args()

  cmd = args.cmd
  if cmd is None:
    raise RuntimeError("no command specified")

  Logger.level = None if args.quiet else args.verbose

  # if getattr(args, "systemd", False):
  #   Logger.enable_syslog = True

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
  except Exception as e:
    Logger.error("exception detected")
    Logger.exception(e)
    import sys
    sys.exit(1)

