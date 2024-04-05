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
from typing import Generator, Iterable
from pathlib import Path
from datetime import datetime
import tempfile

from .keys_backend import KeysBackend
from .key import Key
from .key_id import KeyId
from .topic import UvnTopic
from .certificate_subject import CertificateSubject
from .certificate_authority import CertificateAuthority

from ..core.exec import exec_command
from ..core.render import Templates


class DdsKeysBackend(KeysBackend):
  PROPERTIES = [
    "org",
    "keys_dir",
    "certs_dir",
    "permissions_dir",
    "governance",
    "ca",
    "perm_ca",
  ]
  REQ_PROPERTIES = [
    "org",
  ]
  GRANT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
  REGISTRY_TOPICS = {
    "published": [
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
    ],
    "subscribed": [
      UvnTopic.CELL_ID,
    ],
  }
  CELL_TOPICS = {
    "published": [
      UvnTopic.CELL_ID,
    ],
    "subscribed": [
      UvnTopic.CELL_ID,
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
    ]
  }

  def INITIAL_CA(self) -> CertificateAuthority:
    return CertificateAuthority(
      root=self.root / "ca",
      id=CertificateSubject(org=self.org, cn="Identity Certificate Authority"))


  def INITIAL_PERM_CA(self) -> CertificateAuthority:
    return CertificateAuthority(
      root=self.root / "ca-perm",
      id=CertificateSubject(org=self.org, cn="Permissions Certificate Authority"))

  INITIAL_KEYS_DIR = lambda self: self.root / "private"
  INITIAL_CERTS_DIR = lambda self: self.root / "public"
  INITIAL_PERMISSIONS_DIR = lambda self: self.root / "permissions"
  INITIAL_GOVERNANCE = lambda self: self.root / "governance.xml.p7s"


  @property
  def not_before(self) -> str:
    return self.init_ts.format(self.GRANT_TIME_FORMAT)
  

  @property
  def not_after(self) -> str:
    not_before = datetime.strptime(self.not_before, self.GRANT_TIME_FORMAT)
    not_after = datetime(
      # Use 12 so we can accomodate leap years
      year=not_before.year + 12,
      month=not_before.month,
      day=not_before.day,
      hour=not_before.hour,
      minute=not_before.minute,
      second=not_before.second)
    return not_after.strftime(self.GRANT_TIME_FORMAT)

  
  def permissions(self, id: str) -> Path:
    return self.permissions_dir / f"{id}-permissions.xml.p7s"


  def key(self, id: KeyId) -> Path:
    return self.keys_dir / id.key_type.name.lower() / f"{id.owner}/{id.target}-key.pem"


  def cert(self, id: KeyId) -> Path:
    return self.certs_dir / id.key_type.name.lower() / f"{id.owner}/{id.target}-cert.pem"


  def csr(self, id: KeyId) -> Path:
    return self.certs_dir / id.key_type.name.lower() / f"{id.owner}/{id.target}-cert.csr"
  

  def search_keys(self,
      owner: str|None = None,
      target: str|None = None,
      key_type: str|KeyId.Type|None = None) -> Generator[Key, None, int]:
    lookup_count = 0
    if key_type is not None and not isinstance(key_type, KeyId.Type):
      key_type = KeyId.Type[key_type.upper()]
    for key_t in KeyId.Type:
      if key_type is not None and key_t != key_type:
        continue
      for cert in self.certs_dir.glob(f"{key_t.name.lower()}/*/*-cert.pem"):
        key_o = cert.parent.name
        if owner is not None and key_o != owner:
          continue
        key_tgt = cert.name.replace("-cert.pem", "")
        if target is not None and key_tgt != target:
          continue
        key_id = KeyId(key_t, key_o, key_tgt)
        key = Key(backend=self, id=key_id)
        lookup_count += 1
        yield key
    return lookup_count
    

  def load_key(self,
      key: Key,
      with_privkey: bool = False,
      passphrase: str|None = None) -> Key:
    if with_privkey:
      key.privkey = self.key(key.id).read_text()
    key.pubkey = self.cert(key.id).read_text()
    return key


  def generate_key(self, id: KeyId) -> Key:
    if id.key_type == KeyId.Type.ROOT:
      self.ca.init()
      self.perm_ca.init()
      self.keys_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
      self.certs_dir.mkdir(mode=0o755, parents=False, exist_ok=False)
      self.permissions_dir.mkdir(mode=0o700, parents=False, exist_ok=False)

      tmp_file_h = tempfile.NamedTemporaryFile()
      tmp_file = Path(tmp_file_h.name)
      Templates.generate(tmp_file, "dds/governance.xml", {})
      self.perm_ca.sign_file(tmp_file, self.governance)

      return self._assert_peer(id, **DdsKeysBackend.REGISTRY_TOPICS)
    elif id.key_type == KeyId.Type.CELL:
      return self._assert_peer(id, **DdsKeysBackend.CELL_TOPICS)
    else:
      raise NotImplementedError()


  def _assert_peer(self, key_id: KeyId, published: Iterable[str], subscribed: Iterable[str]) -> Key:
    subject = CertificateSubject(
      cn=key_id.target,
      org=self.ca.id.org,
      country=self.ca.id.country,
      state=self.ca.id.state,
      location=self.ca.id.location)
    peer_key = self.key(key_id)
    peer_cert = self.cert(key_id)
    peer_cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    peer_key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    self.ca.create_cert(subject, peer_key, peer_cert)
    peer_perms = self.permissions(key_id)
    peer_perms.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_file_h = tempfile.NamedTemporaryFile()
    tmp_file = Path(tmp_file_h.name)
    Templates.generate(tmp_file, "dds/permissions.xml", {
      "peer": key_id.target,
      "subject": subject,
      "published": published,
      "subscribed": subscribed,
      "not_before": self.not_before,
      "not_after": self.not_after,
    }, mode=0o644)
    self.perm_ca.sign_file(tmp_file, peer_perms, mode=0o644)
    key = Key(backend=self, id=key_id)
    return self.load_key(key, with_privkey=True)



  def import_key(self,
      key_id: KeyId,
      base_dir: Path,
      key_files: Iterable[Path]) -> Key:
    key_files = set(key_files)
    def _find_file(filename: str) -> str|None:
      rel_path = f"{key_id.key_type.name.lower()}/{key_id.owner}/{key_id.target}-{filename}"
      return next(
        (f for f in key_files
          if str(f) == rel_path), None)

    cert = _find_file("cert.pem")
    key = _find_file("key.pem")
    permissions = _find_file("permissions.p7s")

    if not cert:
      raise RuntimeError("cannot import key without certificate", key_id, base_dir, key_files)

    cert_out = self.cert(key_id)
    cert_out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    exec_command(["cp", "-av", base_dir / cert, cert_out])

    if key:
      key_out = self.key(key_id)
      key_out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      exec_command(["cp", "-av", base_dir / key, key_out])

    if permissions:
      permissions_out = self.permissions(key_id)
      permissions_out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      exec_command(["cp", "-av", base_dir / permissions, permissions_out])

    if key_id.key_type == KeyId.Type.ROOT:
      governance = _find_file("governance.p7s")
      ca_pem = _find_file("ca.pem")
      perm_ca_pem = _find_file("perm-ca.pem")
      if governance is None or ca_pem is None or perm_ca_pem is None:
        raise RuntimeError("missing required key material", governance, ca_pem, perm_ca_pem)
      self.governance.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      exec_command(["cp", "-av", base_dir / governance, self.governance])
      self.ca.cert.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      exec_command(["cp", "-av", base_dir / ca_pem, self.ca.cert])
      self.perm_ca.cert.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      exec_command(["cp", "-av", base_dir / perm_ca_pem, self.perm_ca.cert])

    return Key(backend=self, id=key_id)


  def export_key(self,
      key: Key,
      output_dir: Path,
      with_privkey: bool = False) -> set[Path]:
    exported = set()
    key_dir = output_dir / f"{key.id.key_type.name.lower()}/{key.id.owner}/{key.id.target}"

    cert = self.cert(key.id)
    cert_out = Path(f"{key_dir}-cert.pem")
    cert_out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    exec_command(["cp", "-av", cert, cert_out])
    exported.add(cert_out.relative_to(output_dir))

    if with_privkey:
      key_file = self.key(key.id)
      key_out = Path(f"{key_dir}-key.pem")
      key_out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      exec_command(["cp", "-av", key_file, key_out])
      exported.add(key_out.relative_to(output_dir))

      permissions = self.permissions(key.id)
      permissions_out = Path(f"{key_dir}-permissions.p7s")
      permissions_out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      exec_command(["cp", "-av", permissions, permissions_out])
      exported.add(permissions_out.relative_to(output_dir))

    if key.id.key_type == KeyId.Type.ROOT:
      governance_out = Path(f"{key_dir}-governance.p7s")
      governance_out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      exec_command(["cp", "-av", self.governance, governance_out])
      exported.add(governance_out.relative_to(output_dir))

      ca_pem = Path(f"{key_dir}-ca.pem")
      ca_pem.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      exec_command(["cp", "-av", self.ca.cert, ca_pem])
      exported.add(ca_pem.relative_to(output_dir))

      ca_pem = Path(f"{key_dir}-perm-ca.pem")
      ca_pem.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      exec_command(["cp", "-av", self.perm_ca.cert, ca_pem])
      exported.add(ca_pem.relative_to(output_dir))


    return exported


  def sign_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    if key.id.key_type != KeyId.Type.ROOT:
      raise ValueError("unsupported key type", key)
    self.ca.sign_file(input, output)


  def verify_signature(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    if key.id.key_type != KeyId.Type.ROOT:
      raise ValueError("unsupported key type", key)
    self.ca.verify_signature(input, output)


  def encrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    cert = self.cert(key.id)
    self.ca.encrypt_file(cert, input, output)


  def decrypt_file(self,
      key: Key,
      input: Path,
      output: Path) -> None:
    key = self.key(key.id)
    self.ca.decrypt_file(key, input, output)


  def drop_key(self, key: Key) -> None:
    raise NotImplementedError()


  def drop_keys(self) -> None:
    raise NotImplementedError()()

