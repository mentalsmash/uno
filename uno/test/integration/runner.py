#!/usr/bin/env python3
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
import sys
from pathlib import Path
import os

from uno.registry.registry import Registry
from uno.cli.cli_helpers import cli_command_main, cli_command
from uno.test.integration import Experiment, IntegrationTest, Scenario

import argparse


def _parser(parser: argparse.ArgumentParser) -> None:
  subparsers = parser.add_subparsers(help="Top-level Commands")

  #############################################################################
  # uno host ...
  #############################################################################
  cmd_host = cli_command(subparsers, "host",
    cmd=runner_host,
    help="Run an integration test host's main()")

  cmd_host.add_argument("test_case",
    help="Test case that the runner is a part of.",
    type=Path)

  cmd_host.add_argument("container_name",
    help="Name of the container where the runner is deployed")


def runner_host(args: argparse.Namespace) -> None:
  # Set UNO_TEST_RUNNER to inform tests that they're running inside Docker
  os.environ["UNO_TEST_RUNNER"] = "y"
  
  # Add /uno-middleware to python's module path if it exists
  middleware_plugin_dir = Path("/uno-middleware")
  if middleware_plugin_dir.is_dir():
    sys.path.insert(0, str(middleware_plugin_dir))
  test_case_filef = Path("/experiment") / args.test_case
  scenario: Scenario = IntegrationTest.import_test_case(test_case_filef)
  # Find host for the current container
  host = next(h for h in scenario.experiment.hosts if h.container_name == args.container_name)
  # Perform host initialization steps
  host.init()
  # Run test-case's main()
  host.run()


def main():
  cli_command_main(_parser)


if __name__ == "__main__":
  main()

