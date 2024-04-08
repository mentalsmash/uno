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
import pytest
import subprocess
from typing import Generator

from uno.test.integration import Experiment, Host, HostRole
from uno.core.time import Timer


@pytest.fixture
def the_hosts(experiment: Experiment) -> list[Host]:
  return sorted((h for h in experiment.hosts if h.role == HostRole.HOST), key=lambda h: h.container_name)


@pytest.fixture
def the_registry(experiment: Experiment) -> list[Host]:
  return next(h for h in experiment.hosts if h.role == HostRole.REGISTRY)


@pytest.fixture
def the_particles(experiment: Experiment) -> list[Host]:
  return sorted((h for h in experiment.hosts if h.role == HostRole.PARTICLE), key=lambda h: h.container_name)


@pytest.fixture
def the_agents(experiment: Experiment) -> Generator[dict[Host, subprocess.Popen], None, None]:
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
def the_fully_routed_agents(experiment: Experiment, the_agents: dict[Host, subprocess.Popen]) -> Generator[dict[Host, subprocess.Popen], None, None]:
  def _check_all_consistent() -> bool:
    for agent in the_agents:
      if not agent.cell_fully_routed:
        return False
    return True
  timer = Timer(experiment.config["uvn_fully_routed_timeout"], 1, _check_all_consistent,
    experiment.log,
    "waiting for UVN to become consistent",
    "UVN not consistent yet",
    "UVN fully routed",
    "UVN failed to reach consistency")
  timer.wait()
  yield the_agents

