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
    default_cfg.update({
      "networks_count": 4,
      "relays_count": 1, #1,
      "hosts_count": 1,
      "particles_count": 1,
      "public_agent": True,
      "uvn_name": "test-uvn",
      "uvn_owner": "root@internet",
      "uvn_owner_password": "abc",
      "public_net": "internet",
      "public_net_subnet": ipaddress.ip_network("10.230.255.0/24"),
      "registry_host": "registry.internet",
      "registry_host_address": ipaddress.ip_address("10.230.255.254"),
    })
    return default_cfg


  @classmethod
  def default_derived_config(cls, config: dict) -> None:
    addrp = list(map(int, str(config["public_net_subnet"].network_address).split(".")))
    config["networks"] = [
      ipaddress.ip_network(f"{addrp[0]}.{addrp[1]}.{addrp[2] -1 - i}.{addrp[3]}/24")
        for i in range(config["networks_count"])
    ]


  # def define_uvn(self) -> None:
  #   self.uno("define", "uvn", self.config["uvn_name"],
  #     *(["-a", self.config["registry_host"]] if self.config["registry_host"] else []),
  #       "-o", self.config["uvn_owner"],
  #       "-p", self.config["uvn_owner_password"])

  #   for i, subnet in enumerate(self.config["networks"]):
  #     self.uno("define", "cell", f"cell{i+1}",
  #         "-N", str(subnet),
  #         "-a", f"router.net{i+1}.{self.config['public_net']}",
  #         "-o", self.config["uvn_owner"])

  #   # Define some cells for "relay" agents
  #   for relay_i in range(self.config["relays_count"]):
  #     self.uno("define", "cell", f"relay{relay_i+1}",
  #         "-a", f"relay{relay_i+1}.{self.config['public_net']}",
  #         "-o", self.config["uvn_owner"])

  #   # Define particles
  #   for p_i in range(self.config["particles_count"]):
  #     self.uno("define", "particle", f"particle{p_i+1}",
  #       "-o", self.config["uvn_owner"])


  def define_uvn(self) -> None:
    return self.define_uvn_from_config(
      name=self.config["uvn_name"],
      owner=self.config["uvn_owner"],
      address=self.config["registry_host"] if self.config["registry_host"] else None,
      password=self.config["uvn_owner_password"],
      uvn_spec={
      "cells": [
        *({
          "name": f"cell{i+1}",
          "address": f"router.net{i+1}.{self.config['public_net']}",
          "allowed_lans": [str(subnet)],
        } for i, subnet in enumerate(self.config["networks"])),
        *({
          "name": f"relay{i+1}",
          "address": f"relay{i+1}.{self.config['public_net']}",
        } for i in range(self.config["relays_count"])),
      ],
      "particles": [
        {
          "name": f"particle{i+1}",
        } for i in range(self.config["particles_count"])
      ]
    })



  def define_networks_and_hosts(self) -> None:
    # Define N private networks + an "internet" network to connect them
    networks = []
    internet = self.define_network(
      subnet=self.config["public_net_subnet"],
      name=self.config["public_net"])

    for i, subnet in enumerate(self.config["networks"]):
      net = self.define_network(
        subnet=subnet,
        name=f"net{i+1}")
      networks.append(net)

    for i, net in enumerate(networks):
      # Define a router for the network
      adjacent_networks = {
        internet: internet.allocate_address()
      }
      address = net.subnet.network_address + 254
      net.define_router(
        address=address,
        adjacent_networks=adjacent_networks,
        upstream_network=internet)

      # Define hosts for the network
      for host_i in range(self.config["hosts_count"]):
        address = net.subnet.network_address + 3 + host_i
        net.define_host(address=address)

      # Define the public agent for the network if enabled
      if self.config["public_agent"]:
        address = net.subnet.network_address + 2
        cell = next(c for c in self.registry.uvn.cells.values() if c.name == f"cell{i+1}")
        cell_package = self.registry.cells_dir / Packager.cell_archive_file(cell)
        net.define_agent(
          address=address,
          public=True,
          uvn=self.registry.uvn,
          cell_package=cell_package)

    # Define "relay" agent hosts
    for relay_i in range(self.config["relays_count"]):
      address = internet.allocate_address()
      hostname = f"relay{relay_i+1}"
      cell = next(c for c in self.registry.uvn.cells.values() if c.name == hostname)
      cell_package = self.registry.cells_dir / Packager.cell_archive_file(cell)
      internet.define_agent(
        address=address,
        hostname=hostname,
        public=False,
        uvn=self.registry.uvn,
        cell_package=cell_package)

    # Define "particle" hosts
    for p_i in range(self.config["particles_count"]):
      address = internet.allocate_address()
      hostname = f"particle{p_i+1}"
      particle = next(p for p in self.registry.uvn.particles.values() if p.name == hostname)
      particle_package = self.registry.particles_dir / Packager.particle_archive_file(particle)
      internet.define_particle(
        address=address,
        hostname=hostname,
        particle_package=particle_package)

    # Define registry node in the internet network
    # Assign it a "router" address, since this network
    # doesn't have a router
    if self.config["registry_host"]:
      hostname, netname = self.config["registry_host"].split(".")
      net = next(n for n in self.networks if n.name == netname)
      registry_h = net.define_registry(
        hostname=hostname,
        address=self.config["registry_host_address"])

