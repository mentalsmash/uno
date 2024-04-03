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

from uno.registry.database import Database
from ..core.wg import genkeypair, genkeypreshared
from .versioned import Versioned, serialize_enum

if TYPE_CHECKING:
  from .database import Database

class WireGuardKeyPair(Versioned):
  PROPERTIES = [
    "key_id",
    "public",
    "private",
    "dropped",
  ]
  REQ_PROPERTIES = [
    "key_id",
    # "private",
    "public",
  ]
  SECRET_PROPERTIES = [
    "private",
  ]
  STR_PROPERTIES = [
    "key_id",
    "dropped",
  ]
  EQ_PROPERTIES = [
    "key_id",
    "dropped",
  ]
  INITIAL_DROPPED = False
  DB_TABLE = "asymm_keys"
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_TABLE_KEYS: list[str] = [
    ["key_id", "dropped"],
    ["public", "dropped"],
    ["private", "dropped"],
  ]
  # Prevent dropped keys from being imported
  DB_IMPORTABLE_WHERE = ("dropped = ?", (False,))
  DB_ORDER_BY: dict[str, bool] = {
    "key_id": True,
    "dropped": True,
  }


  @classmethod
  def generate_new(cls, db: "Database", **properties) -> dict:
    privkey, pubkey = genkeypair()
    return {
      "public": pubkey,
      "private": privkey,
    }


class WireGuardPsk(Versioned):
  PROPERTIES = [
    "key_id",
    "value",
    "dropped",
  ]
  REQ_PROPERTIES = [
    "key_id",
    "value",
  ]
  SECRET_PROPERTIES = [
    "value",
  ]
  STR_PROPERTIES = [
    "key_id",
    "dropped",
  ]
  EQ_PROPERTIES = [
    "key_id",
    "dropped",
  ]
  INITIAL_DROPPED = False
  DB_TABLE = "symm_keys"
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_TABLE_KEYS: list[str] = [
    ["key_id", "dropped"],
    ["value", "dropped"],
  ]
  # Prevent dropped keys from being imported
  DB_IMPORTABLE_WHERE = ("dropped = ?", (False,))
  DB_ORDER_BY: dict[str, bool] = {
    "key_id": True,
    "dropped": True,
  }


  @classmethod
  def generate_new(cls, db: "Database", **properties) -> dict:
    return {"value": genkeypreshared()}
