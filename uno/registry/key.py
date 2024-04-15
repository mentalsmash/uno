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
from typing import TYPE_CHECKING

from .key_id import KeyId


if TYPE_CHECKING:
  from .keys_backend import KeysBackend


class Key:
  def __init__(self, backend: "KeysBackend", id: KeyId) -> None:
    self._backend = backend
    self.id = id
    self.pubkey = None
    self.privkey = None

  def load(self, with_privkey: bool = False, passphrase: str | None = None) -> None:
    return self._backend.load_key(self, with_privkey=with_privkey, passphrase=passphrase)

  def __str__(self) -> str:
    return str(self.id)

  def __repr__(self) -> str:
    return f"Key({repr(self._backend)}, {repr(self.id)})"

  def __eq__(self, other):
    if not isinstance(other, Key):
      return False
    return self._backend == other._backend and self.id == other.id

  def __hash__(self) -> int:
    return hash((self._backend, self.id))

  def export(self, output_dir: Path, with_privkey: bool = False) -> set[Path]:
    return self._backend.export_key(self, output_dir=output_dir, with_privkey=with_privkey)
