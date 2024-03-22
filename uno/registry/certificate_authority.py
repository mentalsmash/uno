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
import tempfile

from .certificate_subject import CertificateSubject
from .ecc import ecc_encrypt, ecc_decrypt

from ..core.exec import exec_command
from ..core.log import Logger
log = Logger.sublogger("ca")


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
    log.debug("initializing CA: {}", self.root)
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

    log.debug("CA created: {}", self.id)


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

