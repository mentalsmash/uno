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


def load_experiment() -> Experiment:
  return BasicExperiment.define(Path(__file__), config={
    # "networks_count": 1,
    # "relays_count": 0,
  })


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  yield from Experiment.as_fixture(load_experiment)


def _ping_test(experiment: Experiment, ping_config: Iterable[tuple[Host, Host, ipaddress.IPv4Address]], batch_size: int|None=None):
  ping_count = 3
  ping_max_wait = 10
  if batch_size is None:
    batch_size = len(experiment.networks)
  
  # Start tests in batches using popen, then wait for them to terminate
  def _wait_batch(batch: list[tuple[Host, Host, ipaddress.IPv4Address, subprocess.Popen]]):
    for host, other_host, address, test in batch:
      rc = test.wait(ping_max_wait)
      assert rc == 0, f"PING FAILED {host} → {other_host}@{address}"
      experiment.log.info("PING OK {} → {}@{}", host, other_host, address)

  batch = []
  for host, other_host, address in ping_config:
    if len(batch) == batch_size:
      _wait_batch(batch)
      batch = []
    experiment.log.activity("PING START {} → {}@{}", host, other_host, address)
    test = host.popen("ping", "-c", f"{ping_count}", str(address))
    batch.append((host, other_host, address, test))
  if batch:
    _wait_batch(batch)
    batch = []


def test_integration_basic_ping(experiment: Experiment, the_hosts: list[Host], the_cells: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to ping every host from every other host
  # Try also to ping every agent
  experiment.log.activity("testing PING communication on {} hosts and {} cells",
    len(the_hosts), len(the_cells))
  _ping_test(experiment, chain(
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


def _ssh_test(experiment: Experiment, test_config: Iterable[tuple[Host, Host]], batch_size: int|None=None):
  def _start(host: Host, server: Host) -> subprocess.Popen:
    # Connect via SSH and run a "dummy" test (e.g. verify that the hostname is what we expect)
    # We mostly want to make sure we can establish an SSH connection through the UVN
    experiment.log.activity("SSH START: {} → {}@{}", host, server, server.default_address)
    host.exec("sh", "-c", f"ssh-keyscan -p 22 -H {server.default_address} >> ~/.ssh/known_hosts",
      user="uno")
    return host.popen("sh", "-c", f"ssh uno@{server.default_address} 'echo THIS_IS_A_TEST_ON $(hostname)' | grep 'THIS_IS_A_TEST_ON {server.hostname}'",
      user="uno",
      capture_output=True)

  def _wait(host: Host, server: Host, test: subprocess.Popen, timeout: float=30.) -> None:
    stdout, stderr = test.communicate(timeout=timeout)
    rc = test.wait(timeout)
    assert rc == 0, f"SSH FAILED {host} → {server}@{server.default_address}: rc = {rc}"
    assert stdout.decode().strip() == f"THIS_IS_A_TEST_ON {server.hostname}", f"SSH FAILED {host} → {server}@{server.default_address}: invalid output"
    experiment.log.info("SSH OK: {}", server)

  if batch_size is None:
    batch_size = len(experiment.networks)
  
  # Start tests in batches using popen, then wait for them to terminate
  def _wait_batch(batch: list[tuple[Host, Host, ipaddress.IPv4Address, subprocess.Popen]]):
    for host, server, test in batch:
      _wait(host, server, test)
  
  test_config = list(test_config)
  servers = {s for _, s in test_config}

  with contextlib.ExitStack() as stack:
    for server in servers:
      stack.enter_context(server.ssh_server())
    batch = []
    for host, server in test_config:
      if len(batch) == batch_size:
        _wait_batch(batch)
        batch = []
      test = _start(host, server)
      batch.append((host, server, test))
    if batch:
      _wait_batch(batch)
      batch = []


def test_integration_basic_ssh(experiment: Experiment, the_hosts: list[Host], the_fully_routed_cell_networks: list[Network]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  _ssh_test(experiment, ((h, s)
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
          _ping_test(experiment, ((particle, h, h.default_address) for h in the_hosts))
          _ssh_test(experiment, ((particle, h) for h in the_hosts))
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
  the_registry.uno("sync", "--max-wait-time", "120000")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)


@agent_test
def test_integration_basic_registry_redeploy(
    experiment: Experiment,
    the_registry: Host,
    the_agents: dict[Host, subprocess.Popen]):
  the_registry.uno("redeploy")
  the_registry.uno("service", "down")
  the_registry.uno("sync", "--max-wait-time", "120000")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)

