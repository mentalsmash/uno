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
from typing import Generator, TYPE_CHECKING
from functools import cached_property
import ipaddress

from .user import User

from .versioned import Versioned, prepare_name, prepare_address
from .database_object import OwnableDatabaseObject, DatabaseObjectOwner, inject_db_cursor
from .database import Database
from .cell_settings import CellSettings

if TYPE_CHECKING:
  from .uvn import Uvn


class Cell(Versioned, OwnableDatabaseObject, DatabaseObjectOwner):
  PROPERTIES = [
    "uvn_id",
    "settings",
    "address",
    "excluded",
    "name",
    "allowed_lans",
  ]
  RO_PROPERTIES = [
    "uvn_id",
    "name",
  ]
  REQ_PROPERTIES = RO_PROPERTIES
  STR_PROPERTIES = [
    # "id",
    "name",
  ]
  DB_TABLE = "cells"
  # DB_ID_POOL = "uvns"
  DB_TABLE_PROPERTIES = [
    *PROPERTIES,
    "owner_id",
  ]
  DB_OWNER = User
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_IMPORT_DROPS_EXISTING = True

  INITIAL_EXCLUDED = False

  # INITIAL_SETTINGS = lambda self: self.new_child(CellSettings)
  def INITIAL_ALLOWED_LANS(self) -> set:
    return set()

  def load_nested(self) -> None:
    if self.settings is None:
      self.settings = self.new_child(CellSettings)

  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.settings

  @cached_property
  @inject_db_cursor
  def uvn(self, cursor: Database.Cursor) -> "Uvn":
    from .uvn import Uvn

    return next(self.db.load(Uvn, id=self.uvn_id, cursor=cursor))

  @property
  def enable_particles_vpn(self) -> bool:
    return (
      self.uvn.settings.enable_particles_vpn and self.settings.enable_particles_vpn and self.address
    )

  def prepare_name(self, val: str) -> None:
    return prepare_name(self.db, val)

  def prepare_settings(self, val: "str | dict | CellSettings") -> CellSettings:
    return self.new_child(CellSettings, val)

  def prepare_allowed_lans(
    self, val: "str | list[str] | set[ipaddress.IPv4Network]"
  ) -> set[ipaddress.IPv4Network]:
    return self.deserialize_collection(ipaddress.IPv4Network, val, set)

  def serialize_allowed_lans(
    self, val: set[ipaddress.IPv4Network], public: bool = False
  ) -> set[str]:
    return sorted(str(v) for v in val)

  def prepare_address(self, val: str | None) -> str | None:
    return prepare_address(self.db, val)

  @property
  def private(self) -> bool:
    return self.address is None

  @property
  def relay(self) -> bool:
    return len(self.allowed_lans) == 0
