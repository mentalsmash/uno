#!/usr/bin/env python3
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
import os
import argparse

from uno.cli.cli_helpers import cli_command_main, cli_command
from uno.test.integration import Experiment
from uno.core.log import Logger

log = Logger.sublogger("runner")


def _parser(parser: argparse.ArgumentParser) -> None:
  subparsers = parser.add_subparsers(help="Top-level Commands")

  #############################################################################
  # uno host ...
  #############################################################################
  cmd_host = cli_command(
    subparsers, "host", cmd=runner_host, help="Run an integration test host's main()"
  )

  cmd_host.add_argument("test_case", help="Test case that the runner is a part of.", type=Path)

  cmd_host.add_argument("container_name", help="Name of the container where the runner is deployed")


def runner_host(args: argparse.Namespace) -> None:
  # UNO_TEST_RUNNER must have been set in the environment
  # to signal that the code is running inside Docker
  assert bool(os.environ.get("UNO_TEST_RUNNER"))
  # Load test case file as a module
  log.info("loading test case experiment: {}", args.test_case)
  test_case_filef = Path("/experiment") / args.test_case
  experiment: Experiment = Experiment.import_test_case(test_case_filef)
  # Find host for the current container
  log.info("loading host configuration: {}", args.container_name)
  host = next(h for h in experiment.hosts if h.container_name == args.container_name)
  host.log_configuration()
  # Perform host initialization steps
  host.init()
  # Run test-case's main()
  host.run()


def main():
  cli_command_main(_parser)


if __name__ == "__main__":
  main()
