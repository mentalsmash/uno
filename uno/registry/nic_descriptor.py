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
from typing import Sequence
from .versioned import Versioned

from ..core.ip import (
  ipv4_netmask_to_cidr,
  list_local_nics,
)


class NicDescriptor(Versioned):
  PROPERTIES = [
    "name",
    "address",
    "subnet",
  ]

  REQ_PROPERTIES = [
    "name",
    "address",
    "subnet",
  ]

  EQ_PROPERTIES = [
    "name",
    "address",
    "subnet",
  ]

  STR_PROPERTIES = [
    "name",
    "address",
    "netmask",
  ]

  SERIALIZED_PROPERTIES = [
    "netmask",
  ]

  def prepare_address(self, val: str | int | ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    return ipaddress.ip_address(val)

  def serialize_address(self, val: ipaddress.IPv4Address, public: bool = False) -> str:
    return str(val)

  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)

  def serialize_subnet(self, val: ipaddress.IPv4Network, public: bool = False) -> str:
    return str(val)

  @property
  def netmask(self) -> int:
    return ipv4_netmask_to_cidr(self.subnet.netmask)

  @classmethod
  def list_local_networks(cls, parent: "Versioned", *args, **kwargs) -> "Sequence[NicDescriptor]":
    """
    Return a list generator of all IPv4 networks associated with local nics.
    The list contains dict() elements describing each network
    """
    return [
      parent.new_child(
        NicDescriptor,
        {
          "name": nic,
          "address": nic_addr["addr"],
          "subnet": nic_addr["subnet"],
        },
      )
      for nic, nic_addrs in list_local_nics(*args, **kwargs)
      for nic_addr in nic_addrs
    ]
