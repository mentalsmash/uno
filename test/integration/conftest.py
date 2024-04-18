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
import pytest
import subprocess
from typing import Generator, Callable

from uno.test.integration import Experiment, Host, Network


@pytest.fixture
def experiment(experiment_loader: Callable[[], None]) -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(experiment_loader)


@pytest.fixture
def the_hosts(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return experiment.host_hosts


@pytest.fixture
def the_routers(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return experiment.router_hosts


@pytest.fixture
def the_cells(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return experiment.cell_hosts


@pytest.fixture
def the_registry(experiment: Experiment) -> Host:
  if experiment is None:
    return []
  return experiment.registry_host


@pytest.fixture
def the_particles(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return experiment.particle_hosts


@pytest.fixture
def the_fully_routed_cell_networks(experiment: Experiment) -> Generator[set[Network], None, None]:
  if experiment is None:
    yield set()
  else:
    experiment.wait_for_fully_routed_networks()
    yield experiment.uvn_networks


@pytest.fixture
def the_agents(experiment: Experiment) -> Generator[dict[Host, subprocess.Popen], None, None]:
  if experiment is None:
    yield {}
    return
  yield from experiment.agent_processes


@pytest.fixture
def the_fully_routed_agents(
  experiment: Experiment, the_agents: dict[Host, subprocess.Popen]
) -> Generator[dict[Host, subprocess.Popen], None, None]:
  if experiment is None:
    yield {}
    return
  experiment.wait_for_fully_routed_agents(the_agents)
  yield the_agents
