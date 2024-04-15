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
import contextlib

from uno.test.integration import Host, Experiment, Network
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ssh_client_test import ssh_client_test


def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__))


@pytest.fixture
def experiment_loader() -> Callable[[], None]:
  return load_experiment


def test(
  experiment: BasicExperiment,
  the_particles: list[Host],
  the_cells: list[Host],
  the_hosts: list[Host],
  the_fully_routed_cell_networks: list[Network],
):
  experiment.log.info(
    "testing communication between {} particles, {} cells, and {} hosts",
    len(the_particles),
    len(the_cells),
    len(the_hosts),
  )

  def _test_particle_w_cell(particle, cell):
    with particle.particle_wg_up(cell.cell):
      experiment.log.activity(
        "testing particle {} with {} hosts via cell {}", particle, len(the_hosts), cell
      )
      ssh_client_test(experiment, ((particle, h) for h in the_hosts))
      experiment.log.info("particle CELL OK: {} via {}", particle, cell)

  with contextlib.ExitStack() as stack:
    for host in the_hosts:
      stack.enter_context(host.ssh_server())
    for particle in the_particles:
      experiment.log.info("particle tests BEGIN: {}", particle)
      for cell in the_cells:
        experiment.log.info("particle test BEGIN: {}, {}", particle, cell)
        if not cell.cell.enable_particles_vpn:
          with pytest.raises(Exception):
            _test_particle_w_cell(particle, cell)
          continue
        else:
          _test_particle_w_cell(particle, cell)
      experiment.log.info("particle test OK: {}", particle)
    experiment.log.info("particle tests ALL {} OK", len(the_particles))
