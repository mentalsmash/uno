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
from pathlib import Path
import tempfile
import json
import yaml

from ..core.exec import exec_command


def ecc_encrypt(cert: Path, input: Path, output: Path) -> None:
  # Extract public key from certificate
  tmp_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_pub_key = Path(tmp_pub_key_h.name)
  exec_command(["openssl", "x509", "-pubkey", "-nocert", "-in", cert, "-out", tmp_pub_key])

  # Generate a temporary, ephemeral, private key
  ephem_priv_key = (
    exec_command(
      ["openssl", "ecparam", "-genkey", "-param_enc", "explicit", "-name", "secp384r1"],
      capture_output=True,
    )
    .stdout.decode("utf-8")
    .strip()
  )
  tmp_priv_key_h = tempfile.NamedTemporaryFile()
  tmp_priv_key = Path(tmp_priv_key_h.name)
  tmp_priv_key.write_text(ephem_priv_key)

  # Derive a symmetric key using sha-256, using the temporary key and the public key
  shared_sec = (
    exec_command(
      [
        "sh",
        "-c",
        f"openssl pkeyutl -derive -inkey {tmp_priv_key} -peerkey {tmp_pub_key} | openssl dgst -sha256",
      ],
      capture_output=True,
    )
    .stdout.decode("utf-8")
    .split("(stdin)= ")[1]
    .strip()
  )

  tmp_enc_h = tempfile.NamedTemporaryFile()
  tmp_enc = Path(tmp_enc_h.name)
  # Encrypt file using 0 IV and sha-256 as key
  exec_command(
    [
      "openssl",
      "enc",
      "-aes-256-ofb",
      "-iv",
      "0" * 32,
      "-K",
      shared_sec,
      "-base64",
      "-in",
      input,
      "-out",
      tmp_enc,
    ]
  )

  # generate HMAC for encrypted file
  hmac = (
    exec_command(["openssl", "dgst", "-sha256", "-hmac", shared_sec, tmp_enc], capture_output=True)
    .stdout.decode("utf-8")
    .split("= ")[1]
    .strip()
  )

  tmp_out_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_out_pub = Path(tmp_out_pub_key_h.name)

  exec_command(
    [
      "openssl",
      "ec",
      "-param_enc",
      "explicit",
      "-pubout",
      "-out",
      tmp_out_pub,
      "-in",
      tmp_priv_key,
    ],
    capture_output=True,
  ).stdout.decode("utf-8").strip()

  output.write_text(
    json.dumps(
      {
        "data": tmp_enc.read_text(),
        "pubkey": tmp_out_pub.read_text(),
        "hmac": hmac,
      }
    ),
  )


def ecc_decrypt(key: Path, input: Path, output: Path) -> None:
  # Read input data from YAML
  data = yaml.safe_load(input.read_text())

  tmp_enc_h = tempfile.NamedTemporaryFile()
  tmp_enc = Path(tmp_enc_h.name)
  tmp_enc.write_text(data["data"])

  tmp_pub_key_h = tempfile.NamedTemporaryFile()
  tmp_pub_key = Path(tmp_pub_key_h.name)
  tmp_pub_key.write_text(data["pubkey"])

  shared_sec = (
    exec_command(
      [
        "sh",
        "-c",
        f"openssl pkeyutl -derive -inkey {key} -peerkey {tmp_pub_key} | openssl dgst -sha256",
      ],
      capture_output=True,
    )
    .stdout.decode("utf-8")
    .split("(stdin)= ")[1]
    .strip()
  )

  # generate HMAC for encrypted file
  expected_hmac = (
    exec_command(["openssl", "dgst", "-sha256", "-hmac", shared_sec, tmp_enc], capture_output=True)
    .stdout.decode("utf-8")
    .split("= ")[1]
    .strip()
  )

  if expected_hmac != data["hmac"]:
    raise RuntimeError("shared secret HMACs don't match")

  exec_command(
    [
      "openssl",
      "enc",
      "-d",
      "-aes-256-ofb",
      "-iv",
      "0" * 32,
      "-K",
      shared_sec,
      "-base64",
      "-in",
      tmp_enc,
      "-out",
      output,
    ]
  )
