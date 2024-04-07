import os
import pytest
import time
import subprocess
from typing import Generator

from uno.test.integration import Experiment, Host, HostRole, Scenario
from uno.core.time import Timer

@pytest.fixture
def experiment(scenario: Scenario):
  scenario.experiment.create()
  try:
    scenario.experiment.start()
    yield scenario.experiment
  finally:
    KEEP_DOCKER = os.environ.get("KEEP_DOCKER", False)
    scenario.experiment.stop()
    if not KEEP_DOCKER:
      scenario.experiment.tear_down(assert_stopped=True)
    scenario.experiment.log.info("done")


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
def the_fully_routed_agents(experiment: Experiment, uno_agents: dict[Host, subprocess.Popen]) -> Generator[dict[Host, subprocess.Popen], None, None]:
  def _check_all_consistent() -> bool:
    for agent in uno_agents:
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
  yield uno_agents

