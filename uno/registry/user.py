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
from .versioned import Versioned, prepare_name
from .database_object import DatabaseObjectOwner
from ..core.htdigest import htdigest_generate, htdigest_verify

if TYPE_CHECKING:
  from .cell import Cell
  from .uvn import Uvn
  from .particle import Particle


class User(Versioned, DatabaseObjectOwner):
  PROPERTIES = [
    "email",
    "name",
    "realm",
    "password",
    "excluded",
  ]
  INITIAL_EXCLUDED = False

  RO_PROPERTIES = [
    "email",
    "realm",
  ]
  REQ_PROPERTIES = [
    "email",
    "password",
    "realm",
  ]
  STR_PROPERTIES = [
    "email",
  ]
  CACHED_PROPERTIES = [
    "guessed_username",
    "owned_cells",
    "owned_particles",
    "owned_uvns",
  ]

  DB_TABLE = "users"
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_IMPORT_DROPS_EXISTING = True

  @classmethod
  def parse_user_id(cls, input: str) -> tuple[str | None, str | None]:
    if input is None:
      return (None, None)

    owner_start = input.find("<")
    if owner_start < 0:
      # Interpret the string as just the owner (i.e. e-mail)
      owner = input
      owner_start = len(owner)
    else:
      owner_end = input.find(">")
      if owner_end < 0:
        raise ValueError("malformed owner id, expected: 'NAME <EMAIL>'", input)
      owner = input[owner_start + 1 : owner_end].strip()

    if not owner:
      raise ValueError("empty owner id", input)

    owner_name = input[:owner_start].strip()
    return (owner, owner_name if owner_name else None)

  def prepare_password(self, val: str) -> str:
    if val.startswith("htdigest:"):
      return val
    digest = htdigest_generate(user=self.email, realm=self.realm, password=val)
    phash = digest.split(":")[2]
    return f"htdigest:{phash}"

  def prepare_name(self, val: str) -> None:
    return prepare_name(self.db, val)

  def login(self, password: str) -> bool:
    # user_password = htdigest_generate(user=self.email, realm=self.realm, password=password).split(":")[2]
    # return self.password[len("htdigest:"):] == user_password
    digest = htdigest_generate(
      user=self.email, realm=self.realm, password_hash=self.password[len("htdigest:") :]
    )
    return htdigest_verify(digest, user=self.email, realm=self.realm, password=password)

  @cached_property
  def owned_cells(self) -> "set[Cell]":
    from .cell import Cell

    return set(o for o in self.owned if isinstance(o, Cell))

  @cached_property
  def owned_particles(self) -> "set[Particle]":
    from .particle import Particle

    return set(o for o in self.owned if isinstance(o, Particle))

  @cached_property
  def owned_uvns(self) -> "set[Uvn]":
    from .uvn import Uvn

    return set(o for o in self.owned if isinstance(o, Uvn))

  @cached_property
  def guessed_username(self) -> str:
    return self.email.split("@")[0]
