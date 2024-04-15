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
from typing import TYPE_CHECKING
from functools import cached_property

from .user import User

from .versioned import Versioned, prepare_name
from .database_object import OwnableDatabaseObject, DatabaseObjectOwner, inject_db_cursor
from .database import Database

if TYPE_CHECKING:
  from .uvn import Uvn


class Particle(Versioned, OwnableDatabaseObject, DatabaseObjectOwner):
  PROPERTIES = ["uvn_id", "name", "excluded"]
  RO_PROPERTIES = [
    "uvn_id",
    "name",
  ]
  REQ_PROPERTIES = RO_PROPERTIES
  STR_PROPERTIES = [
    # "id",
    "name",
  ]
  DB_TABLE_PROPERTIES = [
    *PROPERTIES,
    "owner_id",
  ]
  DB_TABLE = "particles"
  # DB_ID_POOL = "uvns"
  DB_OWNER = User
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_IMPORT_DROPS_EXISTING = True

  INITIAL_EXCLUDED = False

  @cached_property
  @inject_db_cursor
  def uvn(self, cursor: Database.Cursor) -> "Uvn":
    from .uvn import Uvn

    return next(self.db.load(Uvn, id=self.uvn_id, cursor=cursor))

  def prepare_name(self, val: str) -> None:
    return prepare_name(self.db, val)
