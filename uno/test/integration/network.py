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
from typing import TYPE_CHECKING
from pathlib import Path
import ipaddress

from uno.core.exec import exec_command
from uno.registry.cell import Cell
from uno.registry.particle import Particle

from .host import Host
from .host_role import HostRole

if TYPE_CHECKING:
  from .experiment import Experiment


class Network:
  def __init__(
    self,
    experiment: "Experiment",
    name: str,
    subnet: ipaddress.IPv4Network,
    i: int,
    private_lan: bool = False,
    transit_wan: bool = False,
    masquerade_docker: bool = False,
  ) -> None:
    self.experiment = experiment
    self.name = name
    self.subnet = subnet
    self.i = i
    self.private_lan = private_lan
    self.transit_wan = transit_wan
    self.masquerade_docker = masquerade_docker
    self.hosts: list[Host] = []
    self.agents: list[Host] = []
    self.public_agent: Host | None = None
    self.router: Host | None = None
    self.registry: Host | None = None
    self.particles: list[Host] = []
    self.addresses = []
    self.log = self.experiment.log.sublogger(self.name)

  def __str__(self) -> str:
    return f"Network({self.name})"

  def __repr__(self) -> str:
    return str(self)

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Network):
      return False
    return self.name == other.name

  def __hash__(self) -> int:
    return hash(self.name)

  def __iter__(self):
    if self.router:
      yield self.router
    if self.public_agent:
      yield self.public_agent
    if self.registry:
      yield self.registry
    yield from self.agents
    yield from self.hosts
    yield from self.particles

  def __contains__(self, value: object) -> bool:
    if not isinstance(value, Host):
      return False
    if value.role == HostRole.REGISTRY:
      return value == self.registry
    if value.role == HostRole.ROUTER:
      return value == self.router
    if value.role == HostRole.CELL:
      return value == self.public_agent or value in self.agents
    if value.role == HostRole.PARTICLE:
      return value in self.particles
    if value.role == HostRole.HOST:
      return value in self.hosts
    return False

  @property
  def default_router(self) -> ipaddress.IPv4Address:
    # Address of the default gateway created by Docker
    return self.subnet.network_address + 1

  @property
  def router_address(self) -> ipaddress.IPv4Address:
    if self.router:
      return self.router.default_address
    return self.default_router

  @property
  def designated_agent(self) -> Host | None:
    if self.public_agent is not None:
      return self.public_agent
    return next(iter(self.agents), None)

  def allocate_address(self) -> ipaddress.IPv4Address:
    next_i = len(self.addresses) + 1
    addr = self.subnet.network_address + 1 + next_i
    self.addresses.append(addr)
    return addr

  def create(self) -> None:
    # Make sure the network doesn't exist then create it
    self.delete(ignore_errors=True)
    exec_command(
      [
        "docker",
        "network",
        "create",
        "--driver",
        "bridge",
        f"--subnet={self.subnet}",
        "-o",
        f"com.docker.network.bridge.enable_ip_masquerade={'true' if self.masquerade_docker else 'false'}",
        "-o",
        f"com.docker.network.bridge.name=br_{self.name}",
        self.name,
      ]
    )

  def delete(self, ignore_errors: bool = False) -> None:
    exec_command(["docker", "network", "rm", self.name], noexcept=ignore_errors)

  def define_router(
    self,
    address: ipaddress.IPv4Address,
    adjacent_networks: dict["Network", ipaddress.IPv4Address],
    upstream_network: "Network|None" = None,
    **host_args,
  ) -> "Host":
    assert self not in adjacent_networks
    assert len(adjacent_networks) > 0
    assert self.router is None
    assert address in self.subnet
    networks = {self: address}
    networks.update(adjacent_networks or {})
    self.router = Host(
      experiment=self.experiment,
      hostname="router",
      container_name=f"{self.experiment.name}-{self.name}-router",
      networks=networks,
      default_network=self,
      upstream_network=upstream_network,
      role=HostRole.ROUTER,
      **host_args,
    )
    self.experiment.hosts.append(self.router)
    return self.router

  def define_host(
    self,
    address: ipaddress.IPv4Address,
    hostname: str | None = None,
    container_name: str | None = None,
    **host_args,
  ) -> "Host":
    assert address in self.subnet
    if hostname is None:
      host_i = len(self.hosts) + 1
      hostname = f"host{host_i}"
    if container_name is None:
      container_name = f"{self.experiment.name}-{self.name}-{hostname}"
    host = Host(
      experiment=self.experiment,
      hostname=hostname,
      container_name=container_name,
      networks={self: address},
      default_network=self,
      role=HostRole.HOST,
      **host_args,
    )
    self.hosts.append(host)
    self.experiment.hosts.append(host)
    return host

  def define_agent(
    self,
    address: ipaddress.IPv4Address,
    cell: Cell,
    cell_package: Path,
    hostname: str | None = None,
    container_name: str | None = None,
    adjacent_networks: dict["Network", ipaddress.IPv4Address] | None = None,
    public: bool = True,
    agent_ports: list[int] | None = None,
    **host_args,
  ) -> "Host":
    assert address in self.subnet
    if hostname is None:
      if public:
        hostname = "agent"
      else:
        agent_i = len(self.agents) + 1
        hostname = f"agent{agent_i}"
    if container_name is None:
      container_name = f"{self.experiment.name}-{self.name}-{hostname}"
    networks = {self: address}
    networks.update(adjacent_networks or {})
    agent = Host(
      experiment=self.experiment,
      hostname=hostname,
      container_name=container_name,
      networks=networks,
      default_network=self,
      role=HostRole.CELL,
      cell=cell,
      cell_package=cell_package,
      **host_args,
    )
    if public:
      assert self.router is not None
      assert self.public_agent is None
      # Make sure the router forwards the necessary ports
      self.public_agent = agent
    else:
      self.agents.append(agent)
    if agent_ports:
      self.router.port_forward.update({(self, port): agent for port in agent_ports})
    self.experiment.hosts.append(agent)
    return agent

  def define_registry(
    self,
    address: ipaddress.IPv4Address,
    hostname: str | None = None,
    container_name: str | None = None,
    **host_args,
  ) -> None:
    assert address in self.subnet
    if hostname is None:
      hostname = "registry"
    if container_name is None:
      container_name = f"{self.experiment.name}-{self.name}-{hostname}"
    registry = Host(
      experiment=self.experiment,
      hostname=hostname,
      container_name=container_name,
      networks={self: address},
      default_network=self,
      role=HostRole.REGISTRY,
      **host_args,
    )
    assert self.registry is None
    self.registry = registry
    self.experiment.hosts.append(registry)
    return registry

  def define_particle(
    self,
    address: ipaddress.IPv4Address,
    particle: Particle,
    particle_package: Path,
    hostname: str | None = None,
    container_name: str | None = None,
    **host_args,
  ) -> None:
    assert address in self.subnet
    if hostname is None:
      particle_i = len(self.particles) + 1
      hostname = f"particle{particle_i}"
    if container_name is None:
      container_name = f"{self.experiment.name}-{self.name}-{hostname}"
    particle = Host(
      experiment=self.experiment,
      hostname=hostname,
      container_name=container_name,
      particle=particle,
      particle_package=particle_package,
      networks={self: address},
      default_network=self,
      role=HostRole.PARTICLE,
      **host_args,
    )
    self.particles.append(particle)
    self.experiment.hosts.append(particle)
    return particle

  def log_configuration(self) -> None:
    self.log.info("network configuration:")
    self.log.info("- addresses [{}]: {}", len(self.addresses), self.addresses)
    self.log.info("- agents [{}]: {}", len(self.agents), self.agents)
    self.log.info("- hosts [{}]: {}", len(self.hosts), self.hosts)
    self.log.info("- i: {}", self.i)
    self.log.info("- particles [{}]: {}", len(self.particles), self.particles)
    self.log.info("- private: {}", self.private_lan)
    self.log.info("- public agent: {}", self.public_agent)
    self.log.info("- registry: {}", self.registry)
    self.log.info("- router: {}", self.router)
    self.log.info("- subnet: {}", self.subnet)
    self.log.info("- wan: {}", self.transit_wan)
