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

  def serialize_gw(self, val: ipaddress.IPv4Address, public: bool = False) -> str:
    return str(val)

  def prepare_nic(self, val: str | dict | NicDescriptor) -> NicDescriptor:
    return self.new_child(NicDescriptor, val)

  def prepare_next_hop(self, val: str | int | ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    return ipaddress.ip_address(val)

  def serialize_next_hop(
    self, val: ipaddress.IPv4Address | None, public: bool = False
  ) -> str | None:
    if val is None:
      return val
    return str(val)
