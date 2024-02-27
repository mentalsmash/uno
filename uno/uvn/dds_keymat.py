import tempfile
from typing import Optional, Mapping, Tuple, Iterable
from pathlib import Path
import shutil
import datetime

from .exec import exec_command
from .log import Logger as log
from .render import Templates
from .time import Timestamp

class CertificateSubject:
  def __init__(self,
      org: str,
      cn: str,
      country: Optional[str]="US",
      state: Optional[str]="Denial",
      location: Optional[str]="Springfield") -> None:
    self.org = org
    self.cn = cn
    self.country = country
    self.state = state
    self.location = location


  def __eq__(self, other: object) -> bool:
    if isinstance(other, str):
      return str(self) == other
    if not isinstance(other, CertificateSubject):
      return False
    return (
      self.org == other.org
      and self.cn == other.cn
      and self.country == other.country
      and self.state == other.state
      and self.location == other.location
    )


  def __hash__(self) -> int:
    return hash((self.org, self.cn, self.country, self.state, self.location))


  def __str__(self) -> str:
    return f"/C={self.country}/ST={self.state}/L={self.location}/O={self.org}/CN={self.cn}"


  @staticmethod
  def parse(val: str) -> "CertificateSubject":
    import re
    subject_re = re.compile(r"/C=([^/]+)/ST=([^/]+)/L=([^/]+)/O=([^/]+)/CN=([^/]+)")
    subject_m = subject_re.match(val)
    if not subject_m:
      raise ValueError("invalid certificate subject", val)
    return CertificateSubject(
      country=subject_m.group(1),
      state=subject_m.group(2),
      location=subject_m.group(3),
      org=subject_m.group(4),
      cn=subject_m.group(5))


class CertificateAuthority:
  def __init__(self,
      root: Path,
      id: CertificateSubject) -> None:
    self.root = root
    self.id = id
    self.db_dir = self.root / "db"

  @property
  def index(self) -> Path:
    return self.db_dir / "index"


  @property
  def serial(self) -> Path:
    return self.db_dir / "serial"


  @property
  def key(self) -> Path:
    return self.root / "ca-key.pem"


  @property
  def cert(self) -> Path:
    return self.root / "ca-cert.pem"


  def init(self, reset: bool=False) -> None:
    log.debug(f"[DDS] initializing CA: {self.root}")

    if not reset and self.cert.is_file():
      log.debug(f"[DDS] assuming CA is initialized by cert file: {self.cert}")
      return

    if self.db_dir.is_dir():
      self.db_dir.unlink()
    self.db_dir.mkdir(parents=True, exist_ok=False)
    for f, contents in {
        self.index: "",
        self.serial: "01",
      }.items():
      if f.is_file():
        f.unlink()
      f.parent.mkdir(parents=True, exist_ok=True)
      f.write_text(contents)

    if self.key.is_file():
      self.key.unlink()
    if self.cert.is_file():
      self.cert.unlink()

    exec_command([
      "openssl", "req",
        "-nodes",
        "-x509",
        "-days", "1825",
        "-text",
        "-sha384",
        "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:secp384r1",
        "-keyout", self.key,
        "-out", self.cert,
        "-subj", str(self.id),
    ])
    self.key.chmod(0o600)

    log.debug(f"[DDS] CA created: {self.id}")


  def sign_cert(self, csr: Path, cert: Path) -> None:
    cert.parent.mkdir(parents=True, exist_ok=True)
    exec_command([
      "openssl", "x509",
        "-req",
        "-days", "730",
        "-sha384",
        "-text",
        "-CAserial", self.serial,
        "-CA", self.cert,
        "-CAkey", self.key,
        "-in", csr,
        "-out", cert,
    ])


  def sign_file(self, input: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    exec_command([
      "openssl",
        "smime",
        "-sign",
        "-in", input,
        "-text",
        "-out", output,
        "-signer", self.cert,
        "-inkey", self.key,
    ])
  

  def create_cert(self, subject: CertificateSubject, key: Path, cert: Path) -> None:
    csr_h = tempfile.NamedTemporaryFile()
    csr = Path(csr_h.name)
    if key.is_file():
      key.unlink()
    if csr.is_file():
      csr.unlink()
    exec_command([
      "openssl", "req", "-nodes",
        "-new",
        "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:secp384r1",
        "-subj", str(subject),
        "-keyout", key,
        "-out", csr,
      ])
    key.chmod(0o600)
    self.sign_cert(csr, cert)


class DdsKeyMaterial:
  GRANT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

  def __init__(self,
      root: Path,
      org: str,
      generation_ts: TimeoutError) -> None:
    self.root = root
    self.generation_ts = generation_ts
    self.ca = CertificateAuthority(
      root=self.root / "ca",
      id=CertificateSubject(org=org, cn="Identity Certificate Authority"))
    self.perm_ca = CertificateAuthority(
      root=self.root / "ca-perm",
      id=CertificateSubject(org=org, cn="Permissions Certificate Authority"))

  @property
  def keys_dir(self) -> Path:
    return self.root / "private"


  @property
  def certs_dir(self) -> Path:
    return self.root / "public"


  @property
  def permissions_dir(self) -> Path:
    return self.root / "permissions"


  @property
  def governance(self) -> Path:
    return self.root / "governance.xml.p7s"


  @property
  def not_before(self) -> str:
    return Timestamp.parse(self.generation_ts).format(self.GRANT_TIME_FORMAT)


  @property
  def not_after(self) -> str:
    not_before = datetime.datetime.strptime(self.not_before, self.GRANT_TIME_FORMAT)
    not_after = datetime.datetime(
      year=not_before.year + 10,
      month=not_before.month,
      day=not_before.day,
      hour=not_before.hour,
      minute=not_before.minute,
      second=not_before.second)
    return not_after.strftime(self.GRANT_TIME_FORMAT)


  def permissions(self, id: str) -> Path:
    return self.permissions_dir / f"{id}-permissions.xml.p7s"


  def key(self, id: str) -> Path:
    return self.keys_dir / f"{id}-key.pem"


  def cert(self, id: str) -> Path:
    return self.certs_dir / f"{id}-cert.pem"


  def csr(self, id: str) -> Path:
    return self.certs_dir / f"{id}-cert.csr"


  def init(self, peers: Mapping[str,Tuple[Iterable[str], Iterable[str]]], reset: bool=False) -> None:
    log.debug(f"[DDS] initializing security material: {self.root}")

    self.ca.init(reset=reset)
    self.perm_ca.init(reset=reset)

    if self.keys_dir.is_dir() and reset:
      shutil.rmtree(self.keys_dir)
    self.keys_dir.mkdir(parents=True, exist_ok=True)
    self.keys_dir.chmod(0o700)

    if self.certs_dir.is_dir() and reset:
      shutil.rmtree(self.certs_dir)
    self.certs_dir.mkdir(parents=True, exist_ok=True)

    if not self.governance.is_file() or reset:
      tmp_file_h = tempfile.NamedTemporaryFile()
      tmp_file = Path(tmp_file_h.name)
      tmp_file.write_text(Templates.render("dds/governance.xml", {}))
      if self.governance.is_file():
        self.governance.unlink()
      self.perm_ca.sign_file(tmp_file, self.governance)

    log.debug(f"[DDS] assert key material for {len(peers)} peers: {list(peers.keys())}")

    for peer, (published, subscribed) in peers.items():
      peer_key = self.key(peer)
      peer_cert = self.cert(peer)

      if not reset and (peer_key.is_file() or peer_cert.is_file()):
        if not (peer_key.is_file() and peer_cert.is_file()):
          raise RuntimeError("incomplete DDS material for peer", peer_key, peer_cert)
        log.debug(f"[DDS] peer key material already updated: {peer}")
        return

      try:
        self._assert_peer(peer, published, subscribed)
      except Exception as e:
        for f in [peer_key, peer_cert]:
          if f.is_file():
            f.unlink()
        raise e

    log.debug(f"[DDS] security material initialized: {self.root}")


  def _assert_peer(self, peer: str, published: Iterable[str], subscribed: Iterable[str]) -> None:
    log.debug(f"[DDS] creating peer certificate: {peer}")
    subject = CertificateSubject(
      cn=peer,
      org=self.ca.id.org,
      country=self.ca.id.country,
      state=self.ca.id.state,
      location=self.ca.id.location)
    peer_key = self.key(peer)
    peer_cert = self.cert(peer)
    self.ca.create_cert(subject, peer_key, peer_cert)
    peer_perms = self.permissions(peer)
    log.debug(f"[DDS] creating permission file: {peer_perms}")
    tmp_file_h = tempfile.NamedTemporaryFile()
    tmp_file = Path(tmp_file_h.name)
    tmp_file.write_text(Templates.render("dds/permissions.xml", {
      "peer": peer,
      "subject": subject,
      "published": published,
      "subscribed": subscribed,
      "not_before": self.not_before,
      "not_after": self.not_after,
    }))
    if peer_perms.is_file():
      peer_perms.unlink()
    self.perm_ca.sign_file(tmp_file, peer_perms)


