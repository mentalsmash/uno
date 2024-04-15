###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from pathlib import Path
from typing import Callable
import argparse
from operator import attrgetter

from uno.core.log import Logger
from uno.core.ask import ask_assume_no, ask_assume_yes


class SortingHelpFormatter(argparse.HelpFormatter):
  def add_arguments(self, actions):
    actions = sorted(actions, key=attrgetter("option_strings"))
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


def cli_parser_args_common(
  parser: argparse._SubParsersAction | argparse.ArgumentParser, version: str | None = None
):
  parser.add_argument(
    "-r", "--root", metavar="DIR", default=Path.cwd(), type=Path, help="UVN root directory."
  )
  parser.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    help="Increase output verbosity. Repeat for increased verbosity.",
  )
  parser.add_argument(
    "-q", "--quiet", action="count", default=False, help="Suppress all logger output."
  )
  opts = parser.add_argument_group("User Interaction Options")
  opts.add_argument(
    "-y",
    "--yes",
    help="Do not prompt the user with questions, and always assume " "'yes' is the answer.",
    action="store_true",
    default=False,
  )
  opts.add_argument(
    "--no",
    help="Do not prompt the user with questions, and always assume " "'no' is the answer.",
    action="store_true",
    default=False,
  )


def cli_command_group(
  parent: argparse._SubParsersAction | argparse.ArgumentParser, name: str, title: str, help: str
) -> argparse._SubParsersAction:
  cmd_group = parent.add_parser(name, formatter_class=SortingHelpFormatter, help=help)
  cmd_group_subparsers = cmd_group.add_subparsers(help=title)
  return cmd_group_subparsers


def cli_command(
  parent: argparse._SubParsersAction | argparse.ArgumentParser,
  name: str,
  cmd: Callable[[argparse.Namespace], None],
  help: str,
  defaults: dict | None = None,
) -> argparse._SubParsersAction:
  command = parent.add_parser(name, help=help)
  command.set_defaults(cmd=cmd, **(defaults or {}))
  cli_parser_args_common(command)
  return command


def cli_command_main(
  define_parser: Callable[[argparse._SubParsersAction], None], version: str | None = None
):
  parser = argparse.ArgumentParser(formatter_class=SortingHelpFormatter)
  if version is not None:
    parser.add_argument("--version", action="version", version=version)
  define_parser(parser)
  args = parser.parse_args()

  cmd = getattr(args, "cmd", None)
  if cmd is None:
    raise RuntimeError("no command specified")

  Logger.min_level = None if args.quiet else args.verbose

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
