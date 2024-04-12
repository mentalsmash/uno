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
def test_httpd(
    experiment: Experiment,
    the_hosts: list[Host],
    the_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = list(the_fully_routed_agents)
  # Try to connect to the httpd server of the agents
  experiment.log.activity("testing HTTPD server of {} agent from {} hosts: {}",
    len(agents), len(the_hosts), agents)
  for host in the_hosts:
    for agent in agents:
      if not agent.cell_addresses:
        continue
      host.agent_httpd_test(agent)

