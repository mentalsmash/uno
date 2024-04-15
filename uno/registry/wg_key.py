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

from uno.registry.database import Database
from ..core.wg import genkeypair, genkeypreshared
from .versioned import Versioned

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
