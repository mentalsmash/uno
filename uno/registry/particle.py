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
from typing import Generator, TYPE_CHECKING
import yaml
from functools import cached_property

from .cell_settings import CellSettings
from .cell_network import CellNetwork
from .user import User
from ..core.log import Logger as log

from .versioned import Versioned, prepare_name
from .database_object import OwnableDatabaseObject, DatabaseObjectOwner

if TYPE_CHECKING:
  from .database import Database
  from .uvn import Uvn


class Particle(Versioned, OwnableDatabaseObject, DatabaseObjectOwner):
  PROPERTIES = [
    "uvn_id",
    "name",
    "excluded"
  ]
  RO_PROPERTIES = [
    "uvn_id",
    "name",
  ]
  REQ_PROPERTIES = RO_PROPERTIES
  STR_PROPERTIES = [
    "id",
    "name",
  ]
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_TABLE = "particles"
  DB_OWNER = User
  DB_OWNER_TABLE = "particles_credentials"

  INITIAL_EXCLUDED = False

  @cached_property
  def uvn(self) -> "Uvn":
    from .uvn import Uvn
    return next(self.db.load(Uvn, id=self.uvn_id))


  def validate_new(self) -> None:
    self.uvn.validate_particle(self)


  def prepare_name(self, val: str) -> None:
    return prepare_name(self.db, val)



