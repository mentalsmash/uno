from typing import Generator, Iterable
from pathlib import Path
from .keys import KeysBackend, Key, KeyId
from .exec import exec_command
import gnupg


class GpgKey(Key):
  def __init__(self, backend: KeysBackend, id: KeyId, fingerprint: str) -> None:
    super().__init__(backend, id)
    self.fingerprint = fingerprint


class GpgKeysBackend(KeysBackend):
  KEY_ALGO = "RSA"
  KEY_LENGTH = 4096
  KEY_ENCODING = "utf-8"
  EXT_ENCRYPTED = ".gpg"
  EXT_DECRYPTED = ".orig"
  EXT_SIGNED = ".asc"
  EXT_PUBKEY = ".pub.asc"
  EXT_PRIVKEY = ".key.asc"


  def __init__(self, root: Path) -> None:
    super().__init__(root)
    self._gpg = gnupg.GPG(gnupghome=str(self.root))
    self._gpg.encoding = self.KEY_ENCODING
    self.loaded = True


  def search_keys(self,
      owner: str|None = None,
      target: str|None = None,
      key_type: str|None = None) -> Generator[Key, None, int]:
    lookup_count = 0
    for k in self._gpg.list_keys(keys=owner):
      uids = k.get("uids")
      trust = k.get("trust")
      # Ignore keys that don't have a description field, or
      # that don't have a sufficient level of trust
      if not uids or trust not in ("u", "f"):
        continue
      try:
        key_id = KeyId.parse_key_description(uids[0])
        if not key_id.query(owner=owner, key_type=key_type, target=target):
          continue
        key_fingerprint = k.get("fingerprint")
        if not key_fingerprint:
          # Ignore key with invalid fingerprint
          continue
        key = GpgKey(db=self, id=key_id)
      except Exception as e:
        # Ignore keys that fail to parse
        continue
      lookup_count += 1
      yield key
    return lookup_count


  def load_key(self,
      key: GpgKey,
      with_privkey: bool = False,
      passphrase: str|None = None) -> Key:
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


  def generate_key(self, id: KeyId) -> Key:
    if passphrase is None:
      passphrase = self.random_passphrase()
    if not passphrase:
      raise ValueError("invalid key passphrase", passphrase)
    self.save_passphrase(id, passphrase)
    gpg_input = self._gpg.gen_key_input(
      key_type=self.KEY_ALGO,
      key_length=self.KEY_LENGTH,
      name_real=str(id),
      name_comment=id.key_description(),
      name_email=id.owner,
      passphrase=passphrase)
    gpg_key = self._gpg.gen_key(gpg_input)
    key = GpgKey(db=self, fingerprint=str(gpg_key), id=id)
    key.load(with_privkey=True, passphrase=passphrase)
    return key


  def import_key(self,
      key_id: KeyId,
      base_dir: Path,
      key_files: Iterable[Path]) -> Key:
    key_files = set(key_files)
    def _read_file(filename: str) -> str|None:
      found = next((f for f in key_files if f.name == filename), None)
      if found:
        return found.read_text()
      return None
    pubkey = _read_file(f"{key_id.owner}.pub")
    privkey = _read_file(f"{key_id.owner}.key")
    passphrase = _read_file(f"{key_id.owner}.pass")

    def _gpg_import_key(key_data: str) -> int:
      import_result = self._gpg.import_keys(key_data)
      if import_result.count == 0:
        raise RuntimeError("failed to import key")
      if import_result.count != 1:
        raise RuntimeError("unexpected number of imported keys", key, import_result.count)
      fingerp = import_result.fingerprints[0]
      trust_result = self._gpg.trust_keys(fingerp, "TRUST_ULTIMATE")
      if not trust_result:
        raise RuntimeError("failed to set key trustlevel", fingerp, trust_result)
      return fingerp

    if privkey is not None:
      _gpg_import_key(base_dir / privkey)
    _gpg_import_key(base_dir / pubkey)

    if passphrase is not None:
      self.save_passphrase(key_id, base_dir / passphrase)
    
    key = self[key_id]
    return self.load_key(key, with_privkey=privkey is not None)


  def export_key(self,
      key: Key,
      output_dir: Path,
      with_privkey: bool = False) -> set[Path]:
    raise NotImplementedError()


  def sign_file(self,
      key: GpgKey,
      input: Path,
      output: Path) -> None:
    if passphrase is None:
      passphrase = self.load_key_passphrase(key)
    with input.open("rb") as input:
      # output.parent.mkdir(parents=True, exist_ok=True)
      sign_result = self._gpg.sign_file(input,
        keyid=key.fingerprint,
        passphrase=passphrase,
        detach=False,
        output=str(output))
      if not sign_result:
        raise RuntimeError("failed to generate file signature", self.root, key.fingerprint, input, output)


  def verify_signature(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    with input.open("rb") as input:
      try:    
        verified = self._gpg.verify_file(input)
        # TODO(asorbini) extract original data to output
      except Exception as e:
        raise RuntimeError("failed to verify signature", input)
    if verified.trust_level is None or verified.trust_level < verified.TRUST_FULLY:
      raise RuntimeError("insufficient trust level for signature", input, verified.trust_level)


  def encrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> Path:
    with input.open("rb") as input:
      encrypt_result = self._gpg.encrypt_file(input,
        key.fingerprint,
        passphrase=None,
        output=str(output),
        armor=False)
      if not encrypt_result.ok:
        raise RuntimeError("failed to encrypt file", self.root, key.fingerprint, input, output)


  def decrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> Path:
    passphrase = self.load_key_passphrase(key)
    with input.open("rb") as input:
      decrypt_result = self._gpg.decrypt_file(
        input,
        key,
        passphrase=passphrase,
        output=str(output))
      if not decrypt_result.ok:
        raise RuntimeError("failed to decrypt file", input, key)


  def drop_key(self, key: Key) -> None:
    secret = key.privkey is not None
    del_result = self._gpg.delete_keys(
      [key.fingerprint],
      secret=secret,
      passphrase=self.load_key_passphrase(key) if secret else None,
      expect_passphrase=secret)
    if not del_result.ok:
      raise RuntimeError("failed to delete key", key)


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

