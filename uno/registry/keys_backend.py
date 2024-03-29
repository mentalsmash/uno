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
from pathlib import Path
from typing import Iterable, Generator
from enum import Enum
import os
import secrets
import yaml

from .cell import Cell
from .uvn import Uvn
from .particle import Particle
from .key_id import KeyId
from .key import Key

from .versioned import Versioned


class KeysBackend(Versioned):
  PROPERTIES = [
    "root",
  ]
  EQ_PROPERTIES = [
    "root",
  ]

  REQ_PROPERTIES = [
    "root",
  ]

  PASSPHRASE_LEN = 16
  PASSPHRASE_FILENAME = ".uno-auth-{}"
  PASSPHRASE_VAR = "UVN_AUTH_{}"


  def __getitem__(self, id: KeyId|Uvn|Cell|Particle) -> Key:
    key = self.get_key(id)
    if key is None:
      raise KeyError(id)
    return key


  def get_key(self, id: KeyId|Uvn|Cell|Particle) -> Key|None:
    if isinstance(id, (Uvn, Cell, Particle)):
      id = KeyId.from_uvn(id)
    matches = list(self.search_keys(owner=id.owner, target=id.target, key_type=id.key_type))
    if len(matches) > 1:
      raise KeyError(id)
    elif len(matches) == 0:
      return None
    assert(id == matches[0].id)
    return matches[0]


  @classmethod
  def random_passphrase(cls) -> str:
    return secrets.token_urlsafe(cls.PASSPHRASE_LEN)


  def export_key_passphrase(self,
      key: Key,
      output_dir: Path|None=None,
      passphrase: str|None=None) -> Path:
    if passphrase is None:
      passphrase = self.load_key_passphrase(key)
    if output_dir is None:
      output_dir = self.root
    output_file = output_dir / KeysBackend.PASSPHRASE_FILENAME.format(key.id.target)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(passphrase)
    output_file.chmod(0o600)
    return output_file


  def load_key_passphrase(self, key: Key) -> str:
    passphrase_var = self.PASSPHRASE_VAR.format(key.id.target)
    passphrase_val = os.environ.get(passphrase_var)
    if passphrase_val is None:
      passphrase_filename = self.PASSPHRASE_FILENAME.format(key.id.target)
      passphrase_file = self.root / passphrase_filename
      if passphrase_file.is_file():
        passphrase_val = passphrase_file.read_text()
    if not passphrase_val:
      raise RuntimeError("failed to get passphrase", key)
    return passphrase_val


  def search_keys(self,
      owner: str|None = None,
      target: str|None = None,
      key_type: str|None = None) -> Generator[Key, None, int]:
    raise NotImplementedError()


  def load_key(self,
      key: Key,
      with_privkey: bool = False,
      passphrase: str|None = None) -> Key:
    raise NotImplementedError()


  def generate_key(self, id: KeyId) -> Key:
    raise NotImplementedError()


  def import_key(self,
      key_id: KeyId,
      key_files: Iterable[Path]) -> Key:
    raise NotImplementedError()


  def export_key(self,
      key: Key,
      output_dir: Path,
      with_privkey: bool = False) -> set[Path]:
    raise NotImplementedError()


  def sign_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    raise NotImplementedError()


  def verify_signature(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    raise NotImplementedError()


  def encrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    raise NotImplementedError()


  def decrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    raise NotImplementedError()


  def drop_key(self, key: Key) -> None:
    raise NotImplementedError()


  def drop_keys(self) -> None:
    raise NotImplementedError()
