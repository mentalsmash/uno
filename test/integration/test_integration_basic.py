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
from itertools import chain
from typing import Generator
from pathlib import Path
import pytest
import contextlib

from uno.test.integration import Experiment, Host, Experiment, Network
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ping_test import ping_test
from uno.test.integration.units.ssh_client_test import ssh_client_test

def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__))


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


@pytest.mark.skip(reason="unnecessary if SSH is tested")
def test_ping(experiment: Experiment, the_hosts: list[Host], the_cells: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to ping every host from every other host
  # Try also to ping every agent
  experiment.log.activity("testing PING communication on {} hosts and {} cells",
    len(the_hosts), len(the_cells))
  ping_test(experiment, chain(
    ((h, o, o.default_address) for h in the_hosts for o in experiment.other_hosts(h, the_hosts)),
    ((h, c, a) for h in the_hosts for c in the_cells for a in c.cell_addresses)))


@pytest.mark.skip(reason="unnecessary if SSH is tested")
def test_iperf(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to perform an iperf TCP and UDP test between all hosts
  experiment.log.activity("testing IPERF communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  for host in the_hosts:
    for other_host in experiment.other_hosts(host, the_hosts):
      other_host.iperf_test(host, tcp=True)
      other_host.iperf_test(host, tcp=False)


def test_ssh(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  ssh_client_test(experiment, ((h, s)
    for h in the_hosts
      for s in experiment.other_hosts(h, the_hosts)))
