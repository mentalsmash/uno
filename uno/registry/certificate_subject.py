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

from ..core.exec import exec_command


class CertificateSubject:
  def __init__(
    self,
    org: str,
    cn: str,
    country: str | None = "US",
    state: str | None = "Denial",
    location: str | None = "Springfield",
  ) -> None:
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
      cn=subject_m.group(5),
    )

  @staticmethod
  def extract(cert: Path) -> "CertificateSubject":
    subject = (
      exec_command(["openssl", "x509", "-noout", "-subject", "-in", cert], capture_output=True)
      .stdout.decode("utf-8")
      .split("subject=")[1]
      .strip()
      .replace(" = ", "=")
      .replace(", ", "/")
    )
    subject = "/" + subject
    return CertificateSubject.parse(subject)
