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
from .nic_descriptor import NicDescriptor

from .versioned import Versioned

class LanDescriptor(Versioned):
  PROPERTIES = [
    "nic",
    "gw",
    "next_hop",
  ]

  REQ_PROPERTIES = [
    "nic",
    "gw",
  ]

  EQ_PROPERTIES = [
    "nic",
    "gw",
  ]

  STR_PROPERTIES = [
    "nic",
    "gw",
  ]


  def prepare_gw(self, val: str | int | ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    return ipaddress.ip_address(val)


  def serialize_gw(self, val: ipaddress.IPv4Address, public: bool=False) -> str:
    return str(val)


  def prepare_nic(self, val: str | dict | NicDescriptor) -> NicDescriptor:
    return self.new_child(NicDescriptor, val)


  def prepare_next_hop(self, val: str | int | ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    return ipaddress.ip_address(val)


  def serialize_next_hop(self, val: ipaddress.IPv4Address | None, public: bool=False) -> str | None:
    if val is None:
      return val
    return str(val)

