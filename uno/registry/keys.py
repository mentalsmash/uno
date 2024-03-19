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

from .versioned import Versioned

class KeyId:
  class Type(Enum):
    ROOT = 0
    CELL = 1
    PARTICLE = 2

  def __init__(self,
      key_type: "KeyId.Type",
      owner: str,
      target: str) -> None:
    self.key_type = key_type
    if not isinstance(self.key_type, KeyId.Type):
      raise RuntimeError("invalid key type", repr(self.key_type))
    self.owner = owner
    self.target = target


  def __eq__(self, other):
    if not isinstance(other, KeyId):
      return False
    return (self.owner == other.owner
      and self.key_type == other.key_type
      and self.target == other.target)


  def __hash__(self) -> int:
    return hash((self.key_type, self.owner, self.target))


  def __str__(self) -> str:
    return f"{self.key_type.name.lower()}/{self.owner}/{self.target}"


  def __repr__(self) -> str:
    return f"KeyId(KeyId.Type.{self.key_type.name}, {repr(self.owner)}, {repr(self.target)})"


  def query(self,
    key_type: str|None = None,
    owner: str|None = None,
    target: str|None = None) -> bool:
    return ((key_type is None or key_type == self.key_type)
      and (owner is None or owner == self.owner)
      and (target is None or target == self.target))


  def key_description(self) -> str:
    import json
    return json.dumps(self.serialize())


  def serialize(self) -> dict:
    return {
      "key_type": self.key_type.name,
      "owner": self.owner,
      "target": self.target,
    }


  @staticmethod
  def deserialize(serialized: dict) -> "KeyId":
    return KeyId(
      key_type=KeyId.Type[serialized["key_type"]],
      owner=serialized["owner"],
      target=serialized["target"])


  @staticmethod
  def parse_key_description(key_desc: str) -> "KeyId":
    key_info_start = key_desc.find("(")
    if key_info_start < 0:
      raise ValueError("invalid key description", key_desc)
    # skip "("
    key_info_start += 1
    key_info_end = key_desc.rfind(")")
    if key_info_end < 0 or key_info_start >= key_info_end:
      raise ValueError("invalid key description", key_desc)
    try:
      key_info = yaml.safe_load(key_desc[key_info_start:key_info_end])
      return KeyId.deserialize(key_info)
    except Exception as e:
      raise ValueError("failed to parse key description", key_desc)


  @staticmethod
  def from_uvn_id(id: Uvn|Cell|Particle) -> "KeyId":
    if isinstance(id, Uvn):
      return KeyId(key_type=KeyId.Type.ROOT, owner=id.owner.email, target=id.name)
    elif isinstance(id, Cell):
      return KeyId(key_type=KeyId.Type.CELL, owner=id.owner.email, target=id.name)
    elif isinstance(id, Particle):
      return KeyId(key_type=KeyId.Type.PARTICLE, owner=id.owner.email, target=id.name)
    else:
      raise ValueError(id)


class Key:
  def __init__(self,
      backend: "KeysBackend",
      id: KeyId) -> None:
    self._backend = backend
    self.id = id
    self.pubkey = None
    self.privkey = None


  def load(self,
      with_privkey: bool = False,
      passphrase: str | None = None) -> None:
    return self._backend.load_key(self,
      with_privkey=with_privkey,
      passphrase=passphrase)


  def __str__(self) -> str:
    return str(self.id)


  def __repr__(self) -> str:
    return f"Key({repr(self._backend)}, {repr(self.id)})"


  def __eq__(self, other):
    if not isinstance(other, Key):
      return False
    return (self._backend == other._backend
      and self.id == other.id)


  def __hash__(self) -> int:
    return hash((self._backend, self.id))


  def export(self,
      output_dir: Path,
      with_privkey: bool = False) -> set[Path]:
    return self._backend.export_key(self,
      output_dir=output_dir,
      with_privkey=with_privkey)


class KeysBackend(Versioned):
  PROPERTIES = [
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
      id = KeyId.from_uvn_id(id)
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
