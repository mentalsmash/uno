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
from typing import Sequence, TYPE_CHECKING
from .versioned import Versioned

from ..core.ip import (
  ipv4_netmask_to_cidr,
  list_local_nics,
  ipv4_nic_network,
)

if TYPE_CHECKING:
  from .database import Database

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

  SERIALIZED_PROPERTIES = [
    "netmask",
  ]

  def prepare_address(self, val: str | int | ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    return ipaddress.ip_address(val)


  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)


  @property
  def netmask(self) -> int:
    return ipv4_netmask_to_cidr(self.subnet.netmask)


  @classmethod
  def list_local_networks(cls, parent: "Versioned", *args, **kwargs) -> "Sequence[NicDescriptor]":
    """
    Return a list generator of all IPv4 networks associated with local nics.
    The list contains dict() elements describing each network
    """
    roaming = kwargs.get("roaming")
    return [
      parent.new_child(NicDescriptor, {
        "name": nic,
        "address": ipaddress.IPv4Address(nic_addr["addr"]),
        "subnet": subnet
      })
      for nic, nic_addrs in list_local_nics(*args, **kwargs)
        for nic_addr in nic_addrs
          for subnet in [ipv4_nic_network(
              nic_addr["addr"],
              nic_addr["netmask"] if not roaming else 32)]
    ]