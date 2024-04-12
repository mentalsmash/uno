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


  def serialize_address(self, val: ipaddress.IPv4Address, public: bool=False) -> str:
    return str(val)


  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)


  def serialize_subnet(self, val: ipaddress.IPv4Network, public: bool=False) -> str:
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
      parent.new_child(NicDescriptor, {
        "name": nic,
        "address": nic_addr["addr"],
        "subnet": nic_addr["subnet"],
      })
      for nic, nic_addrs in list_local_nics(*args, **kwargs)
        for nic_addr in nic_addrs
    ]