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
from uno.test.integration import Scenario, Experiment

class BasicScenario(Scenario):
  @property
  def default_config(self) -> dict:
    default_cfg = super().default_config
    networks_count = 4
    public_net_subnet = ipaddress.ip_network("10.230.255.0/24")
    addrp = list(map(int, str(public_net_subnet.network_address).split(".")))
    networks = [
      ipaddress.ip_network(f"{addrp[0]}.{addrp[1]}.{addrp[2] -1 - i}.{addrp[3]}/24")
        for i in range(networks_count)
    ]
    default_cfg.update({
      "relays_count": 1, #1,
      "hosts_count": 1,
      "public_agent": True,
      "uvn_name": "test-uvn",
      "uvn_owner": "root@internet",
      "uvn_owner_password": "abc",
      "public_net": "internet",
      "registry_host": "registry.internet",
      "public_net_subnet": public_net_subnet,
      "networks": networks,
    })
    return default_cfg


  def _define_uvn(self) -> None:
    self.uno("define", "uvn", self.config["uvn_name"],
      *(["-a", self.config["registry_host"]] if self.config["registry_host"] else []),
        "-o", self.config["uvn_owner"],
        "-p", self.config["uvn_owner_password"])

    for i, subnet in enumerate(self.config["networks"]):
      self.uno("define", "cell", f"cell{i+1}",
          "-N", str(subnet),
          "-a", f"router.net{i+1}.{self.config['public_net']}",
          "-o", self.config["uvn_owner"])

    # Define some cells for "relay" agents
    for relay_i in range(self.config["relays_count"]):
      self.uno("define", "cell", f"relay{relay_i+1}",
          "-a", f"relay{relay_i+1}.{self.config['public_net']}",
          "-o", self.config["uvn_owner"])


  def _define_experiment(self, experiment: Experiment) -> None:
    # Define N private networks + an "internet" network to connect them
    networks = []
    internet = experiment.define_network(
      subnet=self.config["public_net_subnet"],
      name=self.config["public_net"])

    for i, subnet in enumerate(self.config["networks"]):
      net = experiment.define_network(
        subnet=subnet,
        name=f"net{i+1}")
      networks.append(net)

    for i, net in enumerate(networks):
      # Define a router for the network
      adjacent_networks = {
        internet: internet.subnet.network_address + i + 2
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
      address = internet.subnet.network_address + len(networks) + 2 + relay_i
      hostname = f"relay{relay_i+1}"
      cell = next(c for c in self.registry.uvn.cells.values() if c.name == hostname)
      cell_package = self.registry.cells_dir / Packager.cell_archive_file(cell)
      internet.define_agent(
        address=address,
        hostname=hostname,
        public=False,
        uvn=self.registry.uvn,
        cell_package=cell_package)

    # Define registry node in the internet network
    # Assign it a "router" address, since this network
    # doesn't have a router
    registry_h = internet.define_registry(
      address=internet.subnet.network_address + 254)

