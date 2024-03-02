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
import os
from pathlib import Path
from typing import Optional, Tuple, Union, Sequence
from collections.abc import Generator
import gnupg
import yaml
import secrets

from enum import Enum

from .uvn_id import UvnId, CellId, ParticleId
from .exec import exec_command
from .log import Logger as log

class GpgKeyType(Enum):
  ROOT = 0
  CELL = 1
  PARTICLE = 2


class GpgKeyId:
  def __init__(self,
      key_type: GpgKeyType,
      owner: str,
      target: str) -> None:
    self.key_type = key_type
    self.owner = owner
    self.target = target


  def __eq__(self, other):
    if not isinstance(other, GpgKeyId):
      return False
    return (self.owner == other.owner
      and self.key_type == other.key_type
      and self.target == other.target)


  def __hash__(self) -> int:
    return hash((self.key_type, self.owner, self.target))


  def __str__(self) -> str:
    return f"{self.key_type}/{self.owner}/{self.target}"


  def __repr__(self) -> str:
    return f"GpgKeyId(GpgKeyType.{self.key_type.name}, {repr(self.owner)}, {repr(self.target)})"


  def query(self,
    key_type: Optional[str] = None,
    owner: Optional[str] = None,
    target: Optional[str] = None) -> bool:
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
  def deserialize(serialized: dict) -> "GpgKeyId":
    return GpgKeyId(
      key_type=GpgKeyType[serialized["key_type"]],
      owner=serialized["owner"],
      target=serialized["target"])


  @staticmethod
  def parse_key_description(key_desc: str) -> "GpgKeyId":
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
      return GpgKeyId.deserialize(key_info)
    except Exception as e:
      raise ValueError("failed to parse key description", key_desc)


  @staticmethod
  def from_uvn_id(id: Union[UvnId, CellId, ParticleId]) -> "GpgKeyId":
    if isinstance(id, UvnId):
      return GpgKeyId(key_type=GpgKeyType.ROOT, owner=id.owner, target=id.name)
    elif isinstance(id, CellId):
      return GpgKeyId(key_type=GpgKeyType.CELL, owner=id.owner, target=id.name)
    elif isinstance(id, ParticleId):
      return GpgKeyId(key_type=GpgKeyType.PARTICLE, owner=id.owner, target=id.name)
    else:
      raise ValueError(id)


class GpgKey:
  def __init__(self,
      db: "GpgDatabase",
      fingerprint: str,
      id: GpgKeyId) -> None:
    self._db = db
    self.id = id
    self.fingerprint = fingerprint
    self.pubkey = None
    self.privkey = None


  def load(self,
      with_privkey: bool = False,
      passphrase: Optional[str] = None) -> None:
    return self._db.load_key(self,
      with_privkey=with_privkey, passphrase=passphrase)


  def __str__(self) -> str:
    return f"{self.id}/{self.fingerprint}"


  def __repr__(self) -> str:
    return f"GpgKey({repr(self._db)}, {repr(self.fingerprint)}, {repr(self.id)})"


  def __eq__(self, other):
    if not isinstance(other, GpgKey):
      return False
    return (self._db == other._db
      and self.fingerprint == other.fingerprint)


  def __hash__(self) -> int:
    return hash(self.fingerprint)



class GpgDatabase:
  KEY_ALGO = "RSA"
  KEY_LENGTH = 4096
  KEY_ENCODING = "utf-8"
  EXT_ENCRYPTED = ".gpg"
  EXT_DECRYPTED = ".orig"
  EXT_SIGNED = ".asc"
  EXT_PUBKEY = ".pub.asc"
  EXT_PRIVKEY = ".key.asc"
  PASSPHRASE_LEN = 32
  PASSPHRASE_VAR = "UVN_AUTH_{}"
  PASSPHRASE_FILENAME = ".uvn-auth-{}"


  def __init__(self, root: Path) -> None:
    self.root = root.resolve()
    self._gpg = gnupg.GPG(gnupghome=str(self.root))
    self._gpg.encoding = self.KEY_ENCODING


  def __eq__(self, other):
    if not isinstance(other, GpgDatabase):
      return False
    return self.root == other.root


  def __hash__(self) -> int:
    return hash(self.root)


  def random_passphrase(self) -> str:
    return secrets.token_urlsafe(self.PASSPHRASE_LEN)


  def export_key_passphrase(self,
      key: GpgKey,
      output_dir: Path,
      passphrase: Optional[str]=None) -> Path:
    if passphrase is None:
      passphrase = self.load_key_passphrase(key)
    output_file = output_dir / self.PASSPHRASE_FILENAME.format(key.id.target)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(passphrase)
    return output_file


  def load_key_passphrase(self, key: GpgKey) -> str:
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
      owner: Optional[str] = None,
      target: Optional[str] = None,
      key_type: Optional[str] = None) -> Generator[GpgKey, None, int]:
    lookup_count = 0
    for k in self._gpg.list_keys(keys=owner):
      uids = k.get("uids")
      trust = k.get("trust")
      # Ignore keys that don't have a description field, or
      # that don't have a sufficient level of trust
      if not uids or trust not in ("u", "f"):
        continue
      try:
        key_id = GpgKeyId.parse_key_description(uids[0])
        if not key_id.query(owner=owner, key_type=key_type, target=target):
          continue
        key_fingerprint = k.get("fingerprint")
        if not key_fingerprint:
          # Ignore key with invalid fingerprint
          continue
        key = GpgKey(db=self, fingerprint=key_fingerprint, id=key_id)
      except Exception as e:
        # Ignore keys that fail to parse
        continue
      lookup_count += 1
      yield key
    return lookup_count


  def __getitem__(self, id: GpgKeyId) -> GpgKey:
    key = self.get(id)
    if key is None:
      raise KeyError(id)
    return key


  def get(self, id: GpgKeyId) -> Optional[GpgKey]:
    matches = list(self.search_keys(owner=id.owner, target=id.target, key_type=id.key_type))
    if len(matches) > 1:
      raise KeyError(id)
    elif len(matches) == 0:
      return None
    assert(id == matches[0].id)
    return matches[0]


  def load_key(self,
      key: GpgKey,
      with_privkey: bool = False,
      passphrase: Optional[str] = None) -> GpgKey:
    key.pubkey = self._gpg.export_keys([key.fingerprint])
    if not key.pubkey:
      raise RuntimeError("failed to load public key", self.root, key.fingerprint)
    if with_privkey:
      if passphrase is None:
        passphrase = self.load_key_passphrase(key)
      key.privkey = self._gpg.export_keys(
        [key.fingerprint],
        secret=True,
        passphrase=passphrase)
      if not key.privkey:
        raise RuntimeError("failed to load private key", self.root, key.fingerprint)
    return key


  def save_passphrase(self,
      id: GpgKeyId,
      passphrase: str) -> Path:
    passphrase_file = self.root / self.PASSPHRASE_FILENAME.format(id.target)
    passphrase_file.write_text(passphrase)
    return passphrase_file


  def generate_key(self,
      id: GpgKeyId,
      owner_name: Optional[str]=None,
      passphrase: Optional[str]=None,
      save_passphrase: bool=False) -> GpgKey:    
    if owner_name is None:
      owner_name = id.owner
    if passphrase is None:
      passphrase = self.random_passphrase()
    if not passphrase:
      raise ValueError("invalid key passphrase", passphrase)
    if save_passphrase:
      self.save_passphrase(id, passphrase)
    gpg_input = self._gpg.gen_key_input(
      key_type=self.KEY_ALGO,
      key_length=self.KEY_LENGTH,
      name_real=owner_name,
      name_comment=id.key_description(),
      name_email=id.owner,
      passphrase=passphrase)
    gpg_key = self._gpg.gen_key(gpg_input)
    key = GpgKey(db=self, fingerprint=str(gpg_key), id=id)
    key.load(with_privkey=True, passphrase=passphrase)
    return key


  def import_key(self,
      key_id: GpgKeyId,
      pubkey: str,
      privkey: Optional[str]=None,
      passphrase: Optional[str]=None,
      trustlevel: str="TRUST_ULTIMATE",
      save_passphrase: bool=False) -> Sequence[str]:
    def _gpg_import_key(key_data: str) -> int:
      import_result = self._gpg.import_keys(key_data)
      if import_result.count == 0:
        raise RuntimeError("failed to import key")
      if import_result.count != 1:
        raise RuntimeError("unexpected number of imported keys", key, import_result.count)
      fingerp = import_result.fingerprints[0]
      trust_result = self._gpg.trust_keys(fingerp, trustlevel)
      if not trust_result:
        raise RuntimeError("failed to set key trustlevel", fingerp, trust_result)
      return fingerp

    if privkey is not None:
      _gpg_import_key(privkey)
    _gpg_import_key(pubkey)

    if passphrase is not None and save_passphrase:
      self.save_passphrase(key_id, passphrase)
    
    key = self[key_id]

    return self.load_key(
      key,
      with_privkey=privkey is not None,
      passphrase=passphrase if not save_passphrase else None)


  def sign_file(self,
      key: GpgKey,
      input_file: Path,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None,
      passphrase: Optional[str] = None) -> Path:
    if passphrase is None:
      passphrase = self.load_key_passphrase(key)
    if output_file is None:
      if output_dir is None:
        output_dir = input_file.parent
      output_file = output_dir / f"{input_file.name}{self.EXT_SIGNED}"
    with input_file.open("rb") as input:
      output_file.parent.mkdir(parents=True, exist_ok=True)
      sign_result = self._gpg.sign_file(input,
        keyid=key.fingerprint,
        passphrase=passphrase,
        detach=True,
        output=str(output_file))
      if not sign_result:
        raise RuntimeError("failed to generate file signature", self.root, key.fingerprint, input_file, output_file)
    return output_file


  def encrypt_file(self,
      key: GpgKey,
      input_file: Path,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None,
      passphrase: Optional[str] = None) -> Path:
    if output_file is None:
      if output_dir is None:
        output_dir = input_file.parent
      output_file = output_dir / f"{input_file.name}{self.EXT_ENCRYPTED}"
    with input_file.open("rb") as input:
      output_file.parent.mkdir(parents=True, exist_ok=True)
      encrypt_result = self._gpg.encrypt_file(input,
        key.fingerprint,
        passphrase=passphrase,
        output=str(output_file),
        armor=False)
      if not encrypt_result.ok:
        raise RuntimeError("failed to encrypt file", self.root, key.fingerprint, input_file, output_file)
    return output_file


  def decrypt_file(self,
      key: GpgKey,
      input_file: Path,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None,
      passphrase: Optional[str] = None,
      signature_file: Optional[Path]=None) -> Path:
    if passphrase is None:
      passphrase = self.load_key_passphrase(key)
    if output_file is None:
      if output_dir is None:
        output_dir = input_file.parent
      if input_file.name.endswith(self.EXT_ENCRYPTED):
        output_filename = input_file.name[:input_file.name.rfind(self.EXT_ENCRYPTED)]
      else:
        output_filename = f"{input_file.name}{self.EXT_DECRYPTED}"
      output_file = output_dir / output_filename
    with input_file.open("rb") as input:
      decrypt_result = self._gpg.decrypt_file(
        input,
        key,
        passphrase=passphrase,
        output=str(output_file))
      if not decrypt_result.ok:
        raise RuntimeError("failed to decrypt file", input_file, key)
    if signature_file is not None:
      with signature_file.open("rb") as input:
        try:    
            verified = self._gpg.verify_file(input, str(output_file))
        except Exception as e:
            raise RuntimeError("failed to verify signature for decrypted file", output_file, signature_file)
        if verified.trust_level is None or verified.trust_level < verified.TRUST_FULLY:
          raise RuntimeError("insufficient trust level for signature", output_file, signature_file, verified.trust_level)
    return output_file    


class IdentityDatabase:
  def __init__(self, root: Path) -> None:
    self.root = root.resolve()
    self.gpg = GpgDatabase(self.root)

  def drop_keys(self) -> None:
    filenames = [
      "private-keys-v1.d",
      "pubring.kbx",
      "pubring.kbx~",
      "random_seed",
      "trustdb.gpg",
      "openpgp-revocs.d",
    ]
    deleted_files = [self.root / f for f in filenames]
    exec_command(["rm", "-rf", *deleted_files])
    # Make sure the files were deleted
    not_deleted = [f for f in deleted_files if f.exists()]
    if not_deleted:
      raise RuntimeError("failed to delete some files", not_deleted)


  def _assert_gpg_key(self, key_id: GpgKeyId, owner_name: str) -> GpgKey:
    key = self.gpg.get(key_id)
    if key is None:
      key = self.gpg.generate_key(
        id=key_id,
        owner_name=owner_name,
        save_passphrase=True)
    else:
      key.load(with_privkey=True)
    return key


  def assert_gpg_keys(self, uvn_id: UvnId) -> None:
    # Make sure we have a root key
    uvn_key_id = GpgKeyId.from_uvn_id(uvn_id)
    self._assert_gpg_key(uvn_key_id, uvn_id.owner_name)

    # Make sure there is a key for every cell
    for cell in uvn_id.cells.values():
      cell_key_id = GpgKeyId.from_uvn_id(cell)
      self._assert_gpg_key(cell_key_id, cell.owner_name)


  def sign_file(self,
      owner_id: Union[UvnId, CellId, ParticleId],
      input_file: Path,
      passphrase: Optional[str]=None,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None) -> Path:
    key_id = GpgKeyId.from_uvn_id(owner_id)
    key = self.gpg[key_id]
    key.load(with_privkey=True, passphrase=passphrase)
    return self.gpg.sign_file(
      key=key,
      input_file=input_file,
      output_dir=output_dir,
      output_file=output_file)


  def encrypt_file(self,
      owner_id: Union[UvnId, CellId, ParticleId],
      input_file: Path,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None) -> Path:
    key_id = GpgKeyId.from_uvn_id(owner_id)
    key = self.gpg[key_id]
    key.load()
    return self.gpg.encrypt_file(
      key=key,
      input_file=input_file,
      output_dir=output_dir,
      output_file=output_file)


  def decrypt_file(self,
      owner_id: Union[UvnId, CellId, ParticleId],
      input_file: Path,
      passphrase: Optional[str]=None,
      output_dir: Optional[Path] = None,
      output_file: Optional[Path] = None,
      signature_file: Optional[Path] = None) -> Path:
    key_id = GpgKeyId.from_uvn_id(owner_id)
    key = self.gpg[key_id]
    key.load(with_privkey=True, passphrase=passphrase)
    return self.gpg.decrypt_file(
      key=key,
      input_file=input_file,
      output_dir=output_dir,
      output_file=output_file,
      signature_file=signature_file)


  def export_key(self,
      owner_id: Union[UvnId, CellId, ParticleId],
      with_privkey: bool=False,
      passphrase: Optional[str]=None,
      with_passphrase: bool=False,
      output_dir: Optional[Path]=None,
      output_file_pubkey: Optional[Path]=None,
      output_file_privkey: Optional[Path]=None,
      output_file_passphrase: Optional[Path]=None) -> Tuple[Path, Optional[Path], Optional[Path]]:
    key_id = GpgKeyId.from_uvn_id(owner_id)
    key = self.gpg[key_id]
    key.load(with_privkey=with_privkey, passphrase=passphrase)

    if output_dir is None:
      output_dir = self.root
    if output_file_pubkey is None:
      output_file_pubkey = output_dir / f"{key_id.target}.pub"
    if output_file_privkey is None:
      output_file_privkey = output_dir / f"{key_id.target}.key"
    if output_file_passphrase is None:
      output_file_passphrase = output_dir / f"{key_id.target}.pass"

    output_file_pubkey.parent.mkdir(parents=True, exist_ok=True)
    output_file_pubkey.write_text(key.pubkey)

    if with_privkey:
      output_file_privkey.parent.mkdir(parents=True, exist_ok=True)
      output_file_privkey.write_text(key.privkey)
    else:
      output_file_privkey = None

    if with_passphrase:
      output_file_passphrase.parent.mkdir(parents=True, exist_ok=True)
      if passphrase is None:
        passphrase = self.gpg.load_key_passphrase(key)
      output_file_passphrase.write_text(passphrase)
    else:
      output_file_passphrase = None

    return [output_file_pubkey, output_file_privkey, output_file_passphrase]


  def import_key(self,
      owner_id: Union[UvnId, CellId, ParticleId],
      pubkey: str,
      privkey: Optional[str]=None,
      passphrase: Optional[str]=None,
      save_passphrase: bool=False) -> GpgKey:
    key_id = GpgKeyId.from_uvn_id(owner_id)
    return self.gpg.import_key(
      key_id=key_id,
      pubkey=pubkey,
      privkey=privkey,
      passphrase=passphrase,
      save_passphrase=save_passphrase)
