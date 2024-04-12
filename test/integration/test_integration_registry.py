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
from typing import Generator
from pathlib import Path
import pytest
import subprocess

from uno.test.integration import Experiment, Host, Experiment, agent_test
from uno.test.integration.experiments.basic import BasicExperiment

def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__))


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


@agent_test
def test_sync(
    experiment: Experiment,
    the_registry: Host,
    the_agents: dict[Host, subprocess.Popen]):
  the_registry.uno("sync", "--max-wait-time", "90")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)


@agent_test
def test_redeploy(
    experiment: Experiment,
    the_registry: Host,
    the_agents: dict[Host, subprocess.Popen]):
  the_registry.uno("redeploy")
  the_registry.uno("service", "down")
  the_registry.uno("sync", "--max-wait-time", "300")
  # TODO(asorbini) investigate why the following test
  # fails sometimes on ARM
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)

