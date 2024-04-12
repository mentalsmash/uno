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
from typing import Generator
from pathlib import Path
from uno.test.integration import Host, Experiment, Network
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ping_test import ping_test
from uno.test.integration.units.ssh_client_test import ssh_client_test

def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__), config={
    "use_cli": True,
  })

@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


@pytest.mark.skip(reason="unnecessary if SSH is tested")
def test_ping(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to ping every host from every other host
  experiment.log.activity("testing PING communication on {} hosts", len(the_hosts))
  ping_test(experiment,
    ((h, o, o.default_address) for h in the_hosts for o in experiment.other_hosts(h, the_hosts)))


def test_ssh(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  ssh_client_test(experiment, ((h, s)
    for h in the_hosts
      for s in experiment.other_hosts(h, the_hosts)))