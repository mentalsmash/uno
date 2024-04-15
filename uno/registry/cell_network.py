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

from .versioned import Versioned
from .database_object import OwnableDatabaseObject


class CellNetwork(Versioned, OwnableDatabaseObject):
  DB_TABLE = "cell_networks"
  DB_TABLE_PROPERTIES = [
    "subnet",
  ]

  @classmethod
  def DB_OWNER(cls) -> type:
    from .cell import Cell

    return Cell

  DB_OWNER_TABLE_COLUMN = "cell_id"

  PROPERTIES = [
    "subnet",
  ]

  REQ_PROPERTIES = [
    "subnet",
  ]

  def prepare_subnet(self, val: str | int | ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(val)
