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


def test_redeploy_default(
  experiment: Experiment, the_registry: Host, the_agents: dict[Host, subprocess.Popen]
):
  """Generate, and push a new deployment, using the default deployment strategy.
  Verify that the UVN regain consistency afterwards."""
  if experiment is None:
    pytest.skip()
  the_registry.uno("redeploy")
  the_registry.uno("service", "down")
  the_registry.uno("sync", "--max-wait-time", "300")
  # TODO(asorbini) investigate why the following test
  # fails sometimes on ARM
  for agent in the_agents.keys():
    assert agent.cell_fully_routed
