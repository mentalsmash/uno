import os
import pytest
import time
from typing import Generator
from uno.test.integration import Experiment, Host, HostRole, Scenario


@pytest.fixture
def experiment(scenario: Scenario):
  # scenario = scenario()
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
def hosts(experiment: Experiment) -> list[Host]:
  return sorted((h for h in experiment.hosts if h.role == HostRole.HOST), key=lambda h: h.container_name)


@pytest.fixture
def registry(experiment: Experiment) -> list[Host]:
  return next(h for h in experiment.hosts if h.role == HostRole.REGISTRY)


@pytest.fixture
def uno_up(experiment: Experiment) -> Generator[Experiment, None, None]:
  # No need to wait, since we are starting container in a "synchronous" fashion
  # (by waiting for them to signal us that they're ready)
  # wait_t = 5
  # experiment.log.activity("waiting {} seconds for routers to discover each other", wait_t)
  # time.sleep(wait_t)
  yield experiment


import subprocess

@pytest.fixture
def uno_agents(experiment: Experiment, uno_up) -> Generator[dict[Host, subprocess.Popen], None, None]:
  import contextlib
  with contextlib.ExitStack() as stack:
    agents = {}
    for host in experiment.hosts:
      if host.role != HostRole.AGENT:
        continue
      # agents.append(host.uno_agent())
      agents[host] = stack.enter_context(host.uno_agent())
    yield agents

