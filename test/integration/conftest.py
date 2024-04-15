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

from uno.test.integration import Experiment, Host, HostRole, Network
from uno.core.time import Timer


@pytest.fixture
def experiment(experiment_loader: Callable[[], None]) -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(experiment_loader)


@pytest.fixture
def the_hosts(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return sorted(
    (h for h in experiment.hosts if h.role == HostRole.HOST), key=lambda h: h.container_name
  )


@pytest.fixture
def the_routers(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return sorted(
    (h for h in experiment.hosts if h.role == HostRole.ROUTER), key=lambda h: h.container_name
  )


@pytest.fixture
def the_cells(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return sorted(
    (h for h in experiment.hosts if h.role == HostRole.CELL), key=lambda h: h.container_name
  )


@pytest.fixture
def the_registry(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return next(h for h in experiment.hosts if h.role == HostRole.REGISTRY)


@pytest.fixture
def the_particles(experiment: Experiment) -> list[Host]:
  if experiment is None:
    return []
  return sorted(
    (h for h in experiment.hosts if h.role == HostRole.PARTICLE), key=lambda h: h.container_name
  )


@pytest.fixture
def the_fully_routed_cell_networks(
  experiment: Experiment, the_cells: list[Host]
) -> Generator[set[Network], None, None]:
  if experiment is None:
    yield set()
    return

  def _check_all_ready() -> bool:
    if experiment is None:
      return

    for cell in the_cells:
      if not cell.local_router_ready:
        return False
    return True

  timer = Timer(
    experiment.config["uvn_fully_routed_timeout"],
    0.5,
    _check_all_ready,
    experiment.log,
    "waiting for UVN to become consistent",
    "UVN not consistent yet",
    "UVN fully routed",
    "UVN failed to reach consistency",
  )
  timer.wait()
  yield experiment.uvn_networks


@pytest.fixture
def the_agents(experiment: Experiment) -> Generator[dict[Host, subprocess.Popen], None, None]:
  if experiment is None:
    yield {}
    return

  import contextlib

  with contextlib.ExitStack() as stack:
    agents = {}
    for host in experiment.hosts:
      if host.role != HostRole.CELL:
        continue
      # agents.append(host.uno_agent())
      agents[host] = stack.enter_context(host.uno_agent())
    yield agents


@pytest.fixture
def the_fully_routed_agents(
  experiment: Experiment, the_agents: dict[Host, subprocess.Popen]
) -> Generator[dict[Host, subprocess.Popen], None, None]:
  if experiment is None:
    yield {}
    return

  def _check_all_consistent() -> bool:
    for agent in the_agents:
      if not agent.cell_fully_routed:
        return False
    return True

  timer = Timer(
    experiment.config["uvn_fully_routed_timeout"],
    0.5,
    _check_all_consistent,
    experiment.log,
    "waiting for UVN to become consistent",
    "UVN not consistent yet",
    "UVN fully routed",
    "UVN failed to reach consistency",
  )
  timer.wait()
  yield the_agents
