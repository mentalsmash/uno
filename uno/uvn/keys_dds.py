from typing import Generator, Iterable, Optional
from pathlib import Path
from datetime import datetime
import tempfile
import json
import yaml

from .keys import KeysBackend, Key, KeyId
from .exec import exec_command
from .time import Timestamp
from .dds import UvnTopic
from .render import Templates
from .log import Logger as log


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


  def init(self) -> None:
    log.debug(f"[DDS] initializing CA: {self.root}")
    self.root.mkdir(parents=False, exist_ok=False, mode=0o700)
    self.db_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
  
    for f, contents in {
        self.index: "",
        self.serial: "01",
      }.items():
      f.write_text(contents)
      f.chmod(0o600)

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


class DdsKeysBackend(KeysBackend):
  GRANT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
  REGISTRY_TOPICS = {
    "published": [
      UvnTopic.UVN_ID,
      UvnTopic.BACKBONE,
    ],

    "subscribed": {
      UvnTopic.CELL_ID: {},
      # UvnTopic.DNS: {},
    },
  }

  CELL_TOPICS = {
    "published": [
      UvnTopic.CELL_ID,
      # UvnTopic.DNS,
    ],

    "subscribed": {
      UvnTopic.CELL_ID: {},
      # UvnTopic.DNS: {},
      UvnTopic.UVN_ID: {},
      UvnTopic.BACKBONE: {},
    }
  }

  def __init__(self, root: Path, org: str, **load_args) -> None:
    super().__init__(root, **load_args)
    self.ca = CertificateAuthority(
      root=self.root / "ca",
      id=CertificateSubject(org=org, cn="Identity Certificate Authority"))
    self.perm_ca = CertificateAuthority(
      root=self.root / "ca-perm",
      id=CertificateSubject(org=org, cn="Permissions Certificate Authority"))
    self.loaded = True
  

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
    return Timestamp.parse(self.init_ts).format(self.GRANT_TIME_FORMAT)
  

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

