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
from typing import Callable
from pathlib import Path
import pytest
import subprocess

from uno.test.integration import Host, Experiment
from uno.test.integration.experiments.basic import BasicExperiment


def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__), requires_agents=True)


@pytest.fixture
def experiment_loader() -> Callable[[], None]:
  return load_experiment


def test_httpd(
  experiment: Experiment,
  the_hosts: list[Host],
  the_fully_routed_agents: dict[Host, subprocess.Popen],
):
  if experiment is None:
    pytest.skip()
  agents = list(the_fully_routed_agents)
  # Try to connect to the httpd server of the agents
  experiment.log.activity(
    "testing HTTPD server of {} agent from {} hosts: {}", len(agents), len(the_hosts), agents
  )
  for host in the_hosts:
    for agent in agents:
      if not agent.cell_addresses:
        continue
      host.agent_httpd_test(agent)
