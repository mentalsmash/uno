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
import contextlib

from uno.test.integration import Host, Experiment, Network
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ssh_client_test import ssh_client_test


def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__))


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


def test(
  experiment: Experiment,
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
  with contextlib.ExitStack() as stack:
    for host in the_hosts:
      stack.enter_context(host.ssh_server())
    for particle in the_particles:
      for cell in the_cells:
        with particle.particle_wg_up(cell.cell):
          experiment.log.activity(
            "testing particle {} with {} hosts via cell {}", particle, len(the_hosts), cell
          )
          ssh_client_test(experiment, ((particle, h) for h in the_hosts))
          experiment.log.info("particle CELL OK: {} via {}", particle, cell)
      experiment.log.info("particle OK: {}", particle)
    experiment.log.info("particles ALL {} OK", len(the_particles))
