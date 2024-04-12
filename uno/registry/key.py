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
from typing import TYPE_CHECKING

from .key_id import KeyId


if TYPE_CHECKING:
  from .keys_backend import KeysBackend

class Key:
  def __init__(self,
      backend: "KeysBackend",
      id: KeyId) -> None:
    self._backend = backend
    self.id = id
    self.pubkey = None
    self.privkey = None


  def load(self,
      with_privkey: bool = False,
      passphrase: str | None = None) -> None:
    return self._backend.load_key(self,
      with_privkey=with_privkey,
      passphrase=passphrase)


  def __str__(self) -> str:
    return str(self.id)


  def __repr__(self) -> str:
    return f"Key({repr(self._backend)}, {repr(self.id)})"


  def __eq__(self, other):
    if not isinstance(other, Key):
      return False
    return (self._backend == other._backend
      and self.id == other.id)


  def __hash__(self) -> int:
    return hash((self._backend, self.id))


  def export(self,
      output_dir: Path,
      with_privkey: bool = False) -> set[Path]:
    return self._backend.export_key(self,
      output_dir=output_dir,
      with_privkey=with_privkey)

