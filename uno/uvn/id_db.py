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

from .uvn_id import Versioned, UvnId, CellId, ParticleId
from .keys import KeysBackend, KeyId, Key
from .log import Logger as log


class IdentityDatabase(Versioned):
  def __init__(self,
      backend: KeysBackend,
      local_id: UvnId|CellId|ParticleId,
      uvn_id: UvnId,
      **load_args) -> None:
    self.backend = backend
    self._uvn_id = uvn_id
    self.local_id = local_id
    super().__init__(**load_args)
    self.loaded = True


  @property
  def uvn_id(self) -> UvnId:
    return self._uvn_id


  @uvn_id.setter
  def uvn_id(self, val: UvnId) -> None:
    self._uvn_id = val


  @property
  def peers(self) -> list[UvnId|CellId|ParticleId]:
    return [self.uvn_id, *self.uvn_id.all_cells]


  def assert_keys(self) -> None:
    log.debug(f"[ID] asserting keys for UVN {self.uvn_id}")
    
    self.backend.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    asserted = {}
    for peer in self.peers:
      log.debug(f"[ID] assert keys for {peer}")
      key_id = KeyId.from_uvn_id(peer)
      key = self.backend.get_key(key_id)
      if key is None:
        log.warning(f"[ID] key not found: {key_id}")
        key = self.backend.generate_key(key_id)
        asserted[peer] = key
    log.debug(f"[ID] asserted {len(asserted)} keys for UVN {self.uvn_id}")


  def export_keys(self, output_dir: Path, target: UvnId|CellId|ParticleId|None=None) -> set[Path]:
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


  def import_keys(self, base_dir: Path, exported_files: set[Path]) -> Mapping[UvnId|CellId|ParticleId, Key]:
    exported_files = set(exported_files)
    log.debug(f"[ID] importing keys from {len(exported_files)} files")
    imported = {}
    for peer in self.peers:
      key_id = KeyId.from_uvn_id(peer)
      imported[peer] = self.backend.import_key(key_id=key_id, base_dir=base_dir, key_files=exported_files)
    return imported

