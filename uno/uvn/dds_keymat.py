import tempfile
from typing import Optional, Mapping, Tuple, Iterable
from pathlib import Path
import shutil
import datetime
import yaml
import json

from .exec import exec_command
from .log import Logger as log
from .render import Templates
from .time import Timestamp


def ecc_encrypt(cert: Path, input: Path, output: Path) -> None:
  # Extract public key from certificate
  tmp_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_pub_key = Path(tmp_pub_key_h.name)
  exec_command([
    "openssl", "x509", "-pubkey", "-nocert", "-in", cert, "-out", tmp_pub_key
  ])

  # Generate a temporary, ephemeral, private key
  ephem_priv_key = exec_command([
    "openssl", "ecparam", "-genkey", "-param_enc", "explicit", "-name", "secp384r1"
  ], capture_output=True).stdout.decode("utf-8").strip()
  tmp_priv_key_h = tempfile.NamedTemporaryFile()
  tmp_priv_key = Path(tmp_priv_key_h.name)
  tmp_priv_key.write_text(ephem_priv_key)

  # Derive a symmetric key using sha-256, using the temporary key and the public key
  shared_sec = exec_command([
    "sh", "-c", f"openssl pkeyutl -derive -inkey {tmp_priv_key} -peerkey {tmp_pub_key} | openssl dgst -sha256"
  ], capture_output=True).stdout.decode("utf-8").split("(stdin)= ")[1].strip()

  tmp_enc_h = tempfile.NamedTemporaryFile()
  tmp_enc = Path(tmp_enc_h.name)
  # Encrypt file using 0 IV and sha-256 as key
  exec_command([
    "openssl", "enc", "-aes-256-ofb", "-iv", "0"*32, "-K", shared_sec, "-base64", "-in", input, "-out", tmp_enc,
  ])
  
  # generate HMAC for encrypted file
  hmac = exec_command([
    "openssl", "dgst", "-sha256", "-hmac", shared_sec, tmp_enc
  ], capture_output=True).stdout.decode("utf-8").split("= ")[1].strip()

  tmp_out_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_out_pub = Path(tmp_out_pub_key_h.name)
  
  exec_command([
    "openssl", "ec", "-param_enc", "explicit", "-pubout", "-out", tmp_out_pub, "-in", tmp_priv_key
  ], capture_output=True).stdout.decode("utf-8").strip()

  output.write_text(json.dumps({
    "data": tmp_enc.read_text(),
    "pubkey": tmp_out_pub.read_text(),
    "hmac": hmac,
  }),)



def ecc_decrypt(key: Path, input: Path, output: Path) -> None:
  # Read input data from YAML
  data = yaml.safe_load(input.read_text())
  
  tmp_enc_h = tempfile.NamedTemporaryFile()
  tmp_enc = Path(tmp_enc_h.name)
  tmp_enc.write_text(data["data"])

  tmp_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_pub_key = Path(tmp_pub_key_h.name)
  tmp_pub_key.write_text(data["pubkey"])

  shared_sec = exec_command([
    "sh", "-c", f"openssl pkeyutl -derive -inkey {key} -peerkey {tmp_pub_key} | openssl dgst -sha256"
  ], capture_output=True).stdout.decode("utf-8").split("(stdin)= ")[1].strip()

  # generate HMAC for encrypted file
  expected_hmac = exec_command([
    "openssl", "dgst", "-sha256", "-hmac", shared_sec, tmp_enc
  ], capture_output=True).stdout.decode("utf-8").split("= ")[1].strip()

  if expected_hmac != data["hmac"]:
    raise RuntimeError("shared secret HMACs don't match")

  exec_command([
    "openssl", "enc", "-d", "-aes-256-ofb", "-iv", "0"*32, "-K", shared_sec, "-base64", "-in", tmp_enc, "-out", output,
  ])


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


  @staticmethod
  def extract(cert: Path) -> "CertificateSubject":
    subject = exec_command(
      ["openssl", "x509", "-noout", "-subject", "-in", cert],
      capture_output=True).stdout.decode("utf-8").split("subject=")[1].strip().replace(" = ", "=").replace(", ", "/")
    subject = "/" + subject
    return CertificateSubject.parse(subject)


class CertificateAuthority:
  def __init__(self,
      root: Path,
      id: CertificateSubject,
      read_only: bool=False) -> None:
    self.root = root
    self.id = id
    self.db_dir = self.root / "db"
    self.read_only = read_only

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
    assert(not self.read_only)

    log.debug(f"[DDS] initializing CA: {self.root}")

    if not reset and self.cert.is_file():
      log.debug(f"[DDS] assuming CA is initialized by cert file: {self.cert}")
      return
  
    if not self.root.is_dir():
      self.root.mkdir(parents=False, exist_ok=False, mode=0o700)

    if self.db_dir.is_dir():
      self.db_dir.unlink()
    self.db_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    for f, contents in {
        self.index: "",
        self.serial: "01",
      }.items():
      if f.is_file():
        f.unlink()
      f.write_text(contents)
      f.chmod(0o600)

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
    self.cert.chmod(0o644)

    log.debug(f"[DDS] CA created: {self.id}")


  def sign_cert(self, csr: Path, cert: Path) -> None:
    # cert.parent.mkdir(parents=True, exist_ok=True)
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
    cert.chmod(0o644)


  def sign_file(self, input: Path, output: Path, mode: int=0o644) -> None:
    # output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
      output.unlink()
    exec_command([
      "openssl",
        "smime",
        "-sign",
        "-in", input,
        "-text",
        "-nocerts",
        "-out", output,
        "-signer", self.cert,
        "-inkey", self.key,
    ])
    output.chmod(mode)


  def verify_signature(self, input: Path, output: Path, mode: int=0o644) -> None:
    if output.is_file():
      output.unlink()
    exec_command([
      "openssl",
        "smime",
        "-verify",
        "-noverify",
        "-in", input,
        "-text",
        "-out", output,
        "-nointern",
        "-certfile", self.cert,
        # "-signer", self.cert,
        # "-nochain",
    ])
    output.chmod(mode)



  def encrypt_file(self, cert: Path, input: Path, output: Path, mode: int=0o644) -> None:
    signed_input_h = tempfile.NamedTemporaryFile()
    signed_input = Path(signed_input_h.name)
    self.sign_file(input, signed_input)
    if output.is_file():
      output.unlink()
    ecc_encrypt(cert, signed_input, output)
    output.chmod(mode)


  def decrypt_file(self, key: Path, input: Path, output: Path, mode: int=0o644) -> None:
    signed_input_h = tempfile.NamedTemporaryFile()
    signed_input = Path(signed_input_h.name)
    ecc_decrypt(key, input, signed_input)
    self.verify_signature(signed_input, output, mode=mode)


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
    csr.chmod(0o644)
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
    self.keys_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    if self.certs_dir.is_dir() and reset:
      shutil.rmtree(self.certs_dir)
    self.certs_dir.mkdir(mode=0o755, parents=True, exist_ok=True)

    if not self.governance.is_file() or reset:
      tmp_file_h = tempfile.NamedTemporaryFile()
      tmp_file = Path(tmp_file_h.name)
      Templates.generate(tmp_file, "dds/governance.xml", {})
      self.perm_ca.sign_file(tmp_file, self.governance)

    log.debug(f"[DDS] assert key material for {len(peers)} peers: {list(peers.keys())}")

    if not self.permissions_dir.is_dir():
      self.permissions_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    for peer, (published, subscribed) in peers.items():
      peer_key = self.key(peer)
      peer_cert = self.cert(peer)

      if not reset and (peer_key.is_file() or peer_cert.is_file()):
        if not (peer_key.is_file() and peer_cert.is_file()):
          raise RuntimeError("incomplete DDS material for peer", peer_key, peer_cert)
        log.debug(f"[DDS] peer key material already updated: {peer}")
        continue

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
    Templates.generate(tmp_file, "dds/permissions.xml", {
      "peer": peer,
      "subject": subject,
      "published": published,
      "subscribed": subscribed,
      "not_before": self.not_before,
      "not_after": self.not_after,
    }, mode=0o644)
    self.perm_ca.sign_file(tmp_file, peer_perms, mode=0o644)


