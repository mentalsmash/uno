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
