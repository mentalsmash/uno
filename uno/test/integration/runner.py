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
from uno.test.integration import Experiment, ExperimentView
from uno.core.log import Logger

log = Logger.sublogger("runner")

_InContainer = bool(os.environ.get("UNO_TEST_RUNNER"))


def _parser(parser: argparse.ArgumentParser) -> None:
  subparsers = parser.add_subparsers(help="Top-level Commands")

  #############################################################################
  # runner host ...
  #############################################################################
  cmd_host = cli_command(
    subparsers, "host", cmd=runner_host, help="Run an integration test host's main()"
  )

  cmd_host.add_argument("test_case", help="Test case that the runner is a part of.", type=Path)

  cmd_host.add_argument("container_name", help="Name of the container where the runner is deployed")

  #############################################################################
  # runner view-experiment ...
  #############################################################################
  cmd_view_exp = cli_command(
    subparsers, "view", cmd=runner_view_experiment, help="Open an experiment in a view"
  )
  cmd_view_exp.add_argument("test_case", help="Test case to load.", type=Path)
  cmd_view_exp.add_argument("-V", "--view", help="View to use")
  mut_opts = cmd_view_exp.add_mutually_exclusive_group()
  mut_opts.add_argument("-A", "--agents", help="Start agents")
  mut_opts.add_argument("-N", "--network", help="Bring up uvn network services.")
  mut_opts.add_argument("-R", "--routed", help="Wait for UVN to be fully routed.")


def _load_experiment(test_case: str | Path) -> Experiment:
  if _InContainer:
    base_dir = Path("/experiment")
  else:
    base_dir = Path.cwd()
  # Load test case file as a module
  log.info("loading test case experiment: {}", test_case)
  test_case_filef = base_dir / test_case
  return Experiment.import_test_case(test_case_filef)


def runner_host(args: argparse.Namespace) -> None:
  # This command must be used from inside a container
  assert _InContainer
  experiment = _load_experiment(args.test_case)
  # Find host for the current container
  log.info("loading host configuration: {}", args.container_name)
  host = next(h for h in experiment.hosts if h.container_name == args.container_name)
  host.log_configuration()
  # Perform host initialization steps
  host.init()
  # Run test-case's main()
  host.run()


def runner_view_experiment(args: argparse.Namespace) -> None:
  # Import available view plugins so that they are registered with the factory
  from uno.test.integration.views import (
    TmuxExperimentView,  # noqa: F401
  )

  # This command is to be used on the host, not a container
  assert not _InContainer
  experiment = _load_experiment(args.test_case)
  view = ExperimentView.load(args.view, experiment)
  if view.Live:
    with experiment.begin():
      if args.agents:
        agents = next(experiment.agent_processes)
        if args.routed:
          experiment.wait_for_fully_routed_agents(agents)
      elif args.routed:
        experiment.wait_for_fully_routed_networks()
      view.display()
  else:
    view.display()


def main():
  cli_command_main(_parser)


if __name__ == "__main__":
  main()
