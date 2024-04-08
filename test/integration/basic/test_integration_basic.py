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
import subprocess
import contextlib

from uno.test.integration import Experiment, Host, Experiment, HostRole
from uno.test.integration.experiments.basic import BasicExperiment

def load_scenario() -> Experiment:
  return BasicExperiment.define(Path(__file__), config={
    # "networks_count": 1,
    # "networks_count": 6,
    # "relays_count": 0,
    # # "hosts_count": 1,
    # "registry_host": None,
  })


@pytest.fixture
def experiment() -> Generator[Experiment, None, None]:
  e = load_scenario()
  with e.begin():
    yield e


def _other_hosts(host: Host, hosts: list[Host]) -> list[Host]:
  return sorted((h for h in hosts if h != host), key=lambda h: h.container_name)


def _agents(experiment: Experiment) -> list[Host]:
  return sorted((h for h in experiment.hosts if h.role == HostRole.CELL), key=lambda h: h.container_name)


def test_integration_basic_ping(experiment: Experiment, the_hosts: list[Host], the_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = list(the_fully_routed_agents)
  experiment.log.activity("testing PING communication on {} hosts and {} agents",
    len(the_hosts), len(agents))
  # Try to ping every host from every other host
  # Try also to ping every agent
  for host in the_hosts:
    for other_host in _other_hosts(host, the_hosts):
      host.ping_test(other_host, other_host.default_address)
    for agent in agents:
      assert(len(agent.cell_addresses) > 0)
      for addr in agent.cell_addresses:
        host.ping_test(agent, addr)


def test_integration_basic_iperf(experiment: Experiment, the_hosts: list[Host]):
  # Try to perform an iperf TCP and UDP test between all hosts
  experiment.log.activity("testing IPERF communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  for host in the_hosts:
    for other_host in _other_hosts(host, the_hosts):
      other_host.iperf_test(host, tcp=True)
      other_host.iperf_test(host, tcp=False)


def test_integration_basic_ssh(experiment: Experiment, the_hosts: list[Host]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(the_hosts), [h.container_name for h in the_hosts])
  for host in the_hosts:
    for other_host in _other_hosts(host, the_hosts):
      other_host.ssh_test(host)


def test_integration_basic_httpd(experiment: Experiment, the_hosts: list[Host], the_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = list(the_fully_routed_agents)
  # Try to connect to the httpd server of the agents
  experiment.log.activity("testing HTTPD server of {} agent from {} hosts: {}",
    len(agents), len(the_hosts), agents)
  for host in the_hosts:
    for agent in agents:
      if not agent.cell_addresses:
        continue
      host.agent_httpd_test(agent)


def test_integration_basic_registry_sync(experiment: Experiment, the_registry: Host, the_agents: dict[Host, subprocess.Popen]):
  if not experiment.registry.middleware.supports_agent():
    experiment.log.debug("agent test disabled by middleware", test_integration_basic_registry_sync)
    return
  the_registry.uno("sync", "--max-wait-time", "120000")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)


def test_integration_basic_registry_redeploy(experiment: Experiment, the_registry: Host, the_agents: dict[Host, subprocess.Popen]):
  if not experiment.registry.middleware.supports_agent():
    experiment.log.debug("agent test disabled by middleware", test_integration_basic_registry_redeploy)
    return
  the_registry.uno("redeploy")
  the_registry.uno("service", "down")
  the_registry.uno("sync", "--max-wait-time", "120000")
  for agent in the_agents.keys():
    assert(agent.cell_fully_routed)


def test_integration_basic_particles(experiment: Experiment, the_particles: list[Host], the_agents: dict[Host, subprocess.Popen], the_hosts: list[Host]):
  experiment.log.info("testing communication between {} particles, {} agents, and {} hosts", len(the_particles), len(the_agents), len(the_hosts))
  with contextlib.ExitStack() as stack:
    for host in the_hosts:
      stack.enter_context(host.ssh_server())
    for particle in the_particles:
      for agent in the_agents:
        experiment.log.activity("testing particle {} through cell {}", particle, agent)
        with particle.particle_wg_up(agent.cell):
          for host in the_hosts:
            experiment.log.activity("testing connection between {} and {} via {}", particle, host, agent)
            particle.ping_test(host, host.default_address)
            particle.ssh_test(host)
            experiment.log.activity("connection OK: {} to {} via {}", particle, host, agent)
        experiment.log.info("particle test completed: {} via {}", particle, agent)
      experiment.log.info("particle test completed: {}", particle)
    experiment.log.info("particles test completed for {} particles", len(the_particles))

