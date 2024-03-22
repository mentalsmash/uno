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

from ..core.ip import ipv4_netmask_to_cidr

from .deployment import DeploymentStrategyKind, P2pLinksMap
from .versioned import Versioned, prepare_enum

class VpnSettings(Versioned):
  PROPERTIES = [
    "port",
    "peer_port",
    "subnet",
    "interface",
    "allowed_ips",
    "peer_mtu",
    "masquerade",
    "forward",
    "tunnel",
    "keepalive"
  ]
  REQ_PROPERTIES = [
    "port",
    "subnet",
    "interface",
  ]
  INITIAL_ALLOWED_IPS = lambda self: []
  INITIAL_MASQUERADE = False
  INITIAL_FORWARD = False
  INITIAL_TUNNEL = False
  INITIAL_KEEPALIVE = 25


  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)


  def serialize_subnet(self, val: ipaddress.IPv4Network, public: bool=False) -> str:
    return str(val)


  @property
  def base_ip(self) -> ipaddress.IPv4Address:
    return self.subnet.network_address


  @property
  def netmask(self) -> int:
    return ipv4_netmask_to_cidr(self.subnet.netmask)


class RootVpnSettings(VpnSettings):
  INITIAL_PORT = 63447
  INITIAL_PEER_PORT = 63448
  INITIAL_SUBNET = ipaddress.ip_network("10.255.128.0/22")
  INITIAL_INTERFACE = "uwg-v{}"
  INITIAL_PEER_MTU = 1320
  INITIAL_MASQUERADE = True


class ParticlesVpnSettings(VpnSettings):
  INITIAL_PORT = 63449
  INITIAL_SUBNET = ipaddress.ip_network("10.254.0.0/16")
  INITIAL_INTERFACE = "uwg-p{}"
  INITIAL_PEER_MTU = 1320
  INITIAL_MASQUERADE = True
  INITIAL_FORWARD = True
  INITIAL_TUNNEL = True


class BackboneVpnSettings(VpnSettings):
  PROPERTIES = [
    "deployment_strategy",
    "deployment_strategy_args",
  ]
  INITIAL_PORT = 63450
  INITIAL_SUBNET = ipaddress.ip_network("10.255.192.0/20")
  INITIAL_INTERFACE = "uwg-b{}"
  # INITIAL_ALLOWED_IPS = [
  #   "224.0.0.5/32",
  #   "224.0.0.6/32",
  # ]
  INITIAL_LINK_NETMASK = 31
  INITIAL_DEPLOYMENT_STRATEGY = DeploymentStrategyKind.CROSSED
  INITIAL_PEER_MTU = 1320
  INITIAL_FORWARD = True


  def prepare_deployment_strategy(self, val: str | DeploymentStrategyKind) -> DeploymentStrategyKind:
    return prepare_enum(self.db, DeploymentStrategyKind, val)


  def prepare_deployment_strategy_args(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val

