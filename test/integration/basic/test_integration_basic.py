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
from typing import Generator, Iterable
from pathlib import Path
import pytest
import subprocess
import contextlib
import ipaddress

from uno.test.integration import Experiment, Host, Experiment, Network, agent_test
from uno.test.integration.experiments.basic import BasicExperiment
from uno.test.integration.units.ping_test import ping_test
from uno.test.integration.units.ssh_client_test import ssh_client_test

def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__), config={
    # "networks_count": 1,
    # "relays_count": 0,
  })


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


def test_integration_basic_ping(experiment: Experiment, the_hosts: list[Host], the_cells: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to ping every host from every other host
  # Try also to ping every agent
  experiment.log.activity("testing PING communication on {} hosts and {} cells",
    len(the_hosts), len(the_cells))
  ping_test(experiment, chain(
    ((h, o, o.default_address) for h in the_hosts for o in experiment.other_hosts(h, the_hosts)),
    ((h, c, a) for h in the_hosts for c in the_cells for a in c.cell_addresses)))


@pytest.mark.skip(reason="unnecessary for basic validation if SSH is tested")
def test_integration_basic_iperf(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to perform an iperf TCP and UDP test between all hosts
  experiment.log.activity("testing IPERF communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  for host in the_hosts:
    for other_host in experiment.other_hosts(host, the_hosts):
      other_host.iperf_test(host, tcp=True)
      other_host.iperf_test(host, tcp=False)


def test_integration_basic_ssh(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  ssh_client_test(experiment, ((h, s)
    for h in the_hosts
      for s in experiment.other_hosts(h, the_hosts)))


def test_integration_basic_particles(
    experiment: Experiment,
    the_particles: list[Host],
    the_cells: list[Host],
    the_hosts: list[Host],
    the_fully_routed_cell_networks: list[Network]):
  experiment.log.info("testing communication between {} particles, {} cells, and {} hosts", len(the_particles), len(the_cells), len(the_hosts))
  with contextlib.ExitStack() as stack:
    for host in the_hosts:
      stack.enter_context(host.ssh_server())
    for particle in the_particles:
      for cell in the_cells:
        with particle.particle_wg_up(cell.cell):
          experiment.log.activity("testing particle {} with {} hosts via cell {}", particle, len(the_hosts), cell)
          ping_test(experiment, ((particle, h, h.default_address) for h in the_hosts))
          ssh_client_test(experiment, ((particle, h) for h in the_hosts))
          experiment.log.info("particle CELL OK: {} via {}", particle, cell)
      experiment.log.info("particle OK: {}", particle)
    experiment.log.info("particles ALL {} OK", len(the_particles))


@agent_test
def test_integration_basic_httpd(
    experiment: Experiment,
    the_hosts: list[Host],
    the_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = list(the_fully_routed_agents)
  # Try to connect to the httpd server of the agents
  experiment.log.activity("testing HTTPD server of {} agent from {} hosts: {}",
    len(agents), len(the_hosts), agents)
  for host in the_hosts:
    for agent in agents:
      if not agent.cell_addresses:
        continue
      host.agent_httpd_test(agent)


@agent_test
def test_integration_basic_registry_sync(
    experiment: Experiment,
    the_registry: Host,
    the_agents: dict[Host, subprocess.Popen]):
  the_registry.uno("sync", "--max-wait-time", "90")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)


@agent_test
def test_integration_basic_registry_redeploy(
    experiment: Experiment,
    the_registry: Host,
    the_agents: dict[Host, subprocess.Popen]):
  the_registry.uno("redeploy")
  the_registry.uno("service", "down")
  the_registry.uno("sync", "--max-wait-time", "90")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)

