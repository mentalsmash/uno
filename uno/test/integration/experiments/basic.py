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
import ipaddress
import pprint
from uno.registry.package import Packager
from uno.test.integration import Experiment


class BasicExperiment(Experiment):
  ################################################################################
  # Experiment Configuration
  ################################################################################
  # ┌───────────────────────────────────────────────────────────────────────────┐
  # │                            CONNECTION LAYOUT                              │
  # ├───────────────────────────────────────────────────────────────────────────┤
  # |                                                                           |
  # |                                ┌──────────┐                               |
  # │            ┌───────────────┐   │ registry │   ┌───────────────┐           │
  # │            │       ┌── router ───┐  │  ┌─── router ──┐        │           │
  # │            │ agent │       │   │ │  │  │  │   │      │  agent │           │
  # │            │   │ ┌─┴──┐    │   │ │  │  │  │   │    ┌─┴──┐ │   │           │
  # │            │   └─┤net1│    │   │ │  │  │  │   │    │net2├─┘   │           │
  # │            │     └─┬──┘    │   │ │  │  │  │   │    └─┬──┘     │           │
  # │            │       │       │   │ │  │  │  │   │      │        │           │
  # │            │      host     │   │┌┴──┴──┴─┐│   │     host      │           │
  # │            └───────────────┘   ││internet├──┐ └───────────────┘           │
  # │                                │└┬──┬────┘│ │                             │
  # │            ┌───────────────┐   │ │  │     │ │ ┌───────────────┐           │
  # │            │       ┌── router ───┘  │     │ router ──┐        │           │
  # │            │ agent │       │   │  relay1  │   │      │  agent │           │
  # │            │   │ ┌─┴──┐    │   └──────────┘   │    ┌─┴──┐ │   │           │
  # │            │   └─┤net3│    │                  │    │net4├─┘   │           │
  # │            │     └─┬──┘    │                  │    └─┬──┘     │           │
  # │            │       │       │                  │      │        │           │
  # │            │      host     │                  │     host      │           │
  # │            └───────────────┘                  └───────────────┘           │
  # |                                                                           |
  # └───────────────────────────────────────────────────────────────────────────┘

  @classmethod
  def default_config(cls) -> dict:
    default_cfg = super(cls, cls).default_config()
    default_cfg.update(
      {
        "networks_count": 4,
        "private_networks_count": 1,
        "relays_count": 1,
        "hosts_count": 1,
        "particles_count": 1,
        "uvn_name": "test-uvn",
        "uvn_owner": "root@example.com",
        "public_net_subnet": ipaddress.ip_network("10.230.255.0/24"),
        "registry_host": "registry.internet1",
        "registry_host_address": ipaddress.ip_address("10.230.255.254"),
        "use_cli": False,
        "uvn_users": [
          {
            "name": "Root",
            "email": "root@example.com",
            "password": "rootspassword",
          },
          {
            "name": "John Doe",
            "email": "john@example.com",
            "password": "johnspassword",
          },
          {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "password": "janespassword",
          },
        ],
        "cell_owners": {
          0: "root@example.com",
          1: "jane@example.com",
          2: "john@example.com",
        },
      }
    )
    return default_cfg

  @classmethod
  def network_subnet(
    cls, base_subnet: ipaddress.IPv4Network, network_id: int
  ) -> ipaddress.IPv4Network:
    addrp = list(map(int, str(base_subnet).split(".")))
    return ipaddress.ip_network(f"{addrp[0]}.{addrp[1]}.{addrp[2] -1 - network_id}.{addrp[3]}/24")

  @classmethod
  def particle_vpn_enabled(cls, cell_name: str) -> bool:
    return not cell_name.startswith("cell") or bool(int(cell_name[len("cell") :]) % 2)

  @classmethod
  def default_derived_config(cls, config: dict) -> None:
    config["networks"] = [
      cls.network_subnet(config["public_net_subnet"].network_address, i)
      for i in range(config["networks_count"])
    ]
    config["private_networks"] = [
      cls.network_subnet(config["public_net_subnet"].network_address, config["networks_count"] + i)
      for i in range(config["private_networks_count"])
    ]

  @property
  def uvn_spec(self) -> dict:
    spec = {
      "name": self.config["uvn_name"],
      "owner": self.config["uvn_owner"],
      "address": self.config["registry_host"],
      "users": self.config["uvn_users"],
      "cells": [
        *(
          {
            "name": cell_name,
            "address": f"router.publan{i+1}.internet1",
            "allowed_lans": [str(subnet)],
            "owner": self.config["cell_owners"][i % len(self.config["cell_owners"])],
            "settings": {
              "enable_particles_vpn": self.particle_vpn_enabled(cell_name),
            },
          }
          for i, subnet in enumerate(self.config["networks"])
          for cell_name in [f"cell{i+1}"]
        ),
        *(
          {
            "name": cell_name,
            "address": f"relay{i+1}.internet1",
            "owner": self.config["cell_owners"][i % len(self.config["cell_owners"])],
            "settings": {
              "enable_particles_vpn": self.particle_vpn_enabled(cell_name),
            },
          }
          for i in range(self.config["relays_count"])
          for cell_name in [f"relay{i+1}"]
        ),
        *(
          {
            "name": cell_name,
            "allowed_lans": [str(subnet)],
            "owner": self.config["cell_owners"][i % len(self.config["cell_owners"])],
            "settings": {
              "enable_particles_vpn": self.particle_vpn_enabled(cell_name),
            },
          }
          for i, subnet in enumerate(self.config["private_networks"])
          for cell_name in [f"private{i+1}"]
        ),
      ],
      "particles": [
        {
          "name": f"particle{i+1}",
          "owner": self.config["cell_owners"][i % len(self.config["cell_owners"])],
        }
        for i in range(self.config["particles_count"])
      ],
    }
    self.log.info("test UVN spec:")
    self.log.info(pprint.pformat(spec))
    return spec

  def _define_uvn_cli(self) -> None:
    owner = next(u for u in self.config["uvn_owner"] if u["email"] == self.config["uvn_owner"])
    self.uno(
      "define",
      "uvn",
      self.config["uvn_name"],
      *(["-a", self.config["registry_host"]] if self.config["registry_host"] else []),
      "-o",
      f"{owner['name']} <{owner['email']}>",
      "-p",
      owner["password"],
    )

    for user in self.config["uvn_users"]:
      if user["email"] == owner["email"]:
        continue
      self.uno("define", "user", user["email"], "-n", user["name"], "-p", user["password"])

    for i, subnet in enumerate(self.config["networks"]):
      cell_name = f"cell{i+1}"
      self.uno(
        "define",
        "cell",
        cell_name,
        "-N",
        str(subnet),
        "-a",
        f"router.publan{i+1}.internet1",
        "-o",
        self.config["cell_owners"][i % len(self.config["cell_owners"])],
        *(["--disable-particles-vpn"] if self.particle_vpn_enabled(cell_name) else []),
      )

    for i, subnet in enumerate(self.config["private_networks"]):
      cell_name = f"private{i+1}"
      self.uno(
        "define",
        "cell",
        cell_name,
        "-N",
        str(subnet),
        "-o",
        self.config["cell_owners"][i % len(self.config["cell_owners"])],
        *(["--disable-particles-vpn"] if self.particle_vpn_enabled(cell_name) else []),
      )

    # Define some cells for "relay" agents
    for i in range(self.config["relays_count"]):
      self.uno(
        "define",
        "cell",
        f"relay{i+1}",
        "-a",
        f"relay{i+1}.internet1",
        "-o",
        self.config["cell_owners"][i % len(self.config["cell_owners"])],
        *(["--disable-particles-vpn"] if self.particle_vpn_enabled(cell_name) else []),
      )

    # Define particles
    for i in range(self.config["particles_count"]):
      self.uno(
        "define",
        "particle",
        f"particle{i+1}",
        "-o",
        self.config["cell_owners"][i % len(self.config["cell_owners"])],
      )

  def define_uvn(self) -> None:
    if self.config["use_cli"]:
      return self._define_uvn_cli()

    return self.define_uvn_from_config(self.config["uvn_name"], self.uvn_spec)

  def define_networks_and_hosts(self) -> None:
    # Define N private networks + an "internet" network to connect them
    networks = []
    internet = self.define_network(
      subnet=self.config["public_net_subnet"],
      transit_wan=True,
    )

    for i, subnet in enumerate(self.config["networks"]):
      net = self.define_network(subnet=subnet)
      networks.append(net)

    for i, subnet in enumerate(self.config["private_networks"]):
      net = self.define_network(subnet=subnet, private_lan=True)
      networks.append(net)

    for i, net in enumerate(networks):
      # Define a router for the network
      adjacent_networks = {internet: internet.allocate_address()}
      address = net.subnet.network_address + 254
      net.define_router(
        address=address, adjacent_networks=adjacent_networks, upstream_network=internet
      )

      # Define hosts for the network
      for host_i in range(self.config["hosts_count"]):
        address = net.subnet.network_address + 3 + host_i
        net.define_host(address=address)

      # Define the agent for the network if enabled
      address = net.subnet.network_address + 2
      cell_name = f"cell{net.i+1}" if not net.private_lan else f"private{net.i+1}"
      cell = next(c for c in self.registry.uvn.cells.values() if c.name == cell_name)
      cell_package = self.registry.cells_dir / Packager.cell_archive_file(cell)
      net.define_agent(
        address=address,
        public=not net.private_lan,
        agent_ports=None if net.private_lan else self.registry.uvn.agent_ports,
        cell=cell,
        cell_package=cell_package,
      )

    # Define "relay" agent hosts
    for i in range(self.config["relays_count"]):
      address = internet.allocate_address()
      hostname = f"relay{i+1}"
      cell = next(c for c in self.registry.uvn.cells.values() if c.name == hostname)
      cell_package = self.registry.cells_dir / Packager.cell_archive_file(cell)
      internet.define_agent(
        address=address,
        hostname=hostname,
        public=False,
        cell=cell,
        cell_package=cell_package,
      )

    # Define "particle" hosts
    for i in range(self.config["particles_count"]):
      address = internet.allocate_address()
      hostname = f"particle{i+1}"
      particle = next(p for p in self.registry.uvn.particles.values() if p.name == hostname)
      particle_package = self.registry.particles_dir / Packager.particle_archive_file(particle)
      internet.define_particle(
        address=address, hostname=hostname, particle=particle, particle_package=particle_package
      )

    # Define registry node in the internet network
    # Assign it a "router" address, since this network
    # doesn't have a router
    if self.config["registry_host"]:
      hostname, netname = self.config["registry_host"].split(".")
      net = next(n for n in self.networks if n.name == netname)
      _ = net.define_registry(hostname=hostname, address=self.config["registry_host_address"])
