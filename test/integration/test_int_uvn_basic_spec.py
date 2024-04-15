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
from itertools import chain
from typing import Callable
from pathlib import Path
import pytest

from uno.test.integration import Host, Experiment, Network
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ping_test import ping_test
from uno.test.integration.units.ssh_client_test import ssh_client_test


def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__))


@pytest.fixture
def experiment_loader() -> Callable[[], None]:
  return load_experiment


@pytest.mark.skip(reason="unnecessary if SSH is tested")
def test_ping(
  experiment: Experiment,
  the_hosts: list[Host],
  the_cells: list[Host],
  the_fully_routed_cell_networks: list[Network],
):
  # Try to ping every host from every other host
  # Try also to ping every agent
  experiment.log.activity(
    "testing PING communication on {} hosts and {} cells", len(the_hosts), len(the_cells)
  )
  ping_test(
    experiment,
    chain(
      ((h, o, o.default_address) for h in the_hosts for o in experiment.other_hosts(h, the_hosts)),
      ((h, c, a) for h in the_hosts for c in the_cells for a in c.cell_addresses),
    ),
  )


@pytest.mark.skip(reason="unnecessary if SSH is tested")
def test_iperf(
  experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]
):
  # Try to perform an iperf TCP and UDP test between all hosts
  experiment.log.activity(
    "testing IPERF communication between {} hosts: {}",
    len(the_hosts),
    [h.container_name for h in the_hosts],
  )
  for host in the_hosts:
    for other_host in experiment.other_hosts(host, the_hosts):
      other_host.iperf_test(host, tcp=True)
      other_host.iperf_test(host, tcp=False)


def test_ssh(
  experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]
):
  # Try to connect with ssh
  experiment.log.activity(
    "testing SSH communication between {} hosts: {}",
    len(the_hosts),
    [h.container_name for h in the_hosts],
  )
  ssh_client_test(
    experiment, ((h, s) for h in the_hosts for s in experiment.other_hosts(h, the_hosts))
  )
