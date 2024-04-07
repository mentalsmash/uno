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
from pathlib import Path
import pytest
import subprocess

from uno.test.integration import Experiment, Host, Scenario, HostRole
from uno.test.integration.scenarios.basic import BasicScenario

def load_scenario() -> Scenario:
  return BasicScenario(Path(__file__), {
    "networks_count": 6,
    "relays_count": 2,
    # # "hosts_count": 1,
    # "registry_host": None,
  })


@pytest.fixture
def scenario() -> Scenario:
  return load_scenario()


def _other_hosts(host: Host, hosts: list[Host]) -> list[Host]:
  return sorted((h for h in hosts if h != host), key=lambda h: h.container_name)


def _agents(experiment: Experiment) -> list[Host]:
  return sorted((h for h in experiment.hosts if h.role == HostRole.AGENT), key=lambda h: h.container_name)


def test_integration_basic_ping(experiment: Experiment, hosts: list[Host], uno_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = list(uno_fully_routed_agents)
  experiment.log.activity("testing PING communication on {} hosts and {} agents",
    len(hosts), len(agents))
  # Try to ping every host from every other host
  # Try also to ping every agent
  for host in hosts:
    for other_host in _other_hosts(host, hosts):
      host.ping_test(other_host, other_host.default_address)
    for agent in agents:
      assert(len(agent.cell_addresses) > 0)
      for addr in agent.cell_addresses:
        host.ping_test(agent, addr)
  # # Try also to ping every host from every agent
  # experiment.log.activity("testing PING communication between {} agents and {} hosts: {}",
  #   len(agents), len(hosts), [h.container_name for h in agents])
  # for agent in agents:
  #   for host in hosts:
  #     agent.ping_test(host)


def test_integration_basic_iperf(experiment: Experiment, hosts: list[Host]):
  # Try to perform an iperf TCP and UDP test between all hosts
  experiment.log.activity("testing IPERF communication between {} hosts: {}", len(hosts), [h.container_name for h in hosts])
  for host in hosts:
    for other_host in _other_hosts(host, hosts):
      other_host.iperf_test(host, tcp=True)
      other_host.iperf_test(host, tcp=False)


def test_integration_basic_ssh(experiment: Experiment, hosts: list[Host]):
  # Try to connect with ssh
  experiment.log.activity("testing SSH communication between {} hosts: {}", len(hosts), [h.container_name for h in hosts])
  for host in hosts:
    for other_host in _other_hosts(host, hosts):
      other_host.ssh_test(host)


def test_integration_basic_httpd(experiment: Experiment, hosts: list[Host], uno_fully_routed_agents: dict[Host, subprocess.Popen]):
  agents = uno_fully_routed_agents
  # Try to connect to the httpd server of the agents
  experiment.log.activity("testing HTTPD server of {} agent from {} hosts: {}",
    len(agents), len(hosts), list(agents.keys()))
  for host in hosts:
    for agent in agents.keys():
      if not agent.cell_addresses:
        continue
      host.agent_httpd_test(agent)


def test_integration_basic_registry_sync(experiment: Experiment, registry: Host, uno_agents: dict[Host, subprocess.Popen]):
  if not experiment.registry.middleware.supports_agent():
    experiment.log.debug("agent test disabled by middleware", test_integration_basic_registry_sync)
    return
  registry.uno("sync", "--max-wait-time", "120000")


def test_integration_basic_registry_redeploy(experiment: Experiment, registry: Host, uno_agents: dict[Host, subprocess.Popen]):
  if not experiment.registry.middleware.supports_agent():
    experiment.log.debug("agent test disabled by middleware", test_integration_basic_registry_redeploy)
    return
  registry.uno("redeploy")
  registry.uno("service", "down")
  registry.uno("sync", "--max-wait-time", "120000")

