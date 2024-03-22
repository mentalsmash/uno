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
from typing import Mapping

from .uvn import Uvn
from .cell import Cell
from .particle import Particle
from .versioned import Versioned

from .key import Key
from .key_id import KeyId


class IdentityDatabase(Versioned):
  PROPERTIES = [
    "registry",
    "backend",
  ]
  REQ_PROPERTIES = PROPERTIES
  VOLATILE_PROPERTIES = [
    "registry",
    "backend",
  ]


  @property
  def uvn(self) -> Uvn:
    return self.registry.uvn


  @property
  def local_id(self) -> Uvn|Cell:
    return self.registry.local_object


  @property
  def peers(self) -> list[Uvn|Cell|Particle]:
    return [self.uvn, *self.uvn.all_cells.values()]


  def assert_keys(self) -> None:
    self.log.debug("asserting keys for UVN {}", self.uvn)
    
    self.backend.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    asserted = {}
    for peer in self.peers:
      self.log.debug("assert keys for {}", peer)
      key_id = KeyId.from_uvn(peer)
      key = self.backend.get_key(key_id)
      if key is None:
        self.log.debug("key not found: {}", key_id)
        key = self.backend.generate_key(key_id)
        asserted[peer] = key
    self.log.debug("asserted {} keys for UVN {}", len(asserted), self.uvn)


  def export_keys(self, output_dir: Path, target: Uvn|Cell|Particle|None=None) -> set[Path]:
    if target is None:
      target = self.local_id
    exported = set()
    for peer in self.peers:
      key = self.backend[peer]
      peer_exported = key.export(
        output_dir = output_dir,
        with_privkey = peer == target)
      for p_rel in peer_exported:
        if p_rel in exported:
          raise RuntimeError("duplicate exported file", output_dir / p_rel)
        exported.add(p_rel)
    return exported


  def import_keys(self, base_dir: Path, exported_files: set[Path]) -> Mapping[Uvn|Cell|Particle, Key]:
    exported_files = set(exported_files)
    self.log.debug("importing keys from {} files", len(exported_files))
    imported = {}
    for peer in self.peers:
      key_id = KeyId.from_uvn(peer)
      imported[peer] = self.backend.import_key(key_id=key_id, base_dir=base_dir, key_files=exported_files)
    return imported

