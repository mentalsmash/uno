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
import ipaddress

from ..core.ip import ipv4_netmask_to_cidr

from .versioned import Versioned


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
    "keepalive",
  ]
  REQ_PROPERTIES = [
    "port",
    "subnet",
    "interface",
  ]
  EQ_PROPERTIES = [
    "port",
    "peer_port",
    "subnet",
    "interface",
    "peer_mtu",
    "masquerade",
    "forward",
    "tunnel",
    "keepalive",
  ]

  def INITIAL_ALLOWED_IPS(self) -> set:
    return set()

  INITIAL_MASQUERADE = False
  INITIAL_FORWARD = False
  INITIAL_TUNNEL = False
  INITIAL_KEEPALIVE = 25

  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)

  def serialize_subnet(self, val: ipaddress.IPv4Network, public: bool = False) -> str:
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
  INITIAL_PORT = 63450
  INITIAL_SUBNET = ipaddress.ip_network("10.255.192.0/20")
  INITIAL_INTERFACE = "uwg-b{}"
  # INITIAL_ALLOWED_IPS = [
  #   "224.0.0.5/32",
  #   "224.0.0.6/32",
  # ]
  INITIAL_LINK_NETMASK = 31
  INITIAL_PEER_MTU = 1320
  INITIAL_FORWARD = True
