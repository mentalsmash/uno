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
from typing import Optional, Callable, Union, Sequence

class PairedValuesMap(dict):
  @classmethod
  def pair_key(cls, peer_a: int, peer_b: int):
    if (peer_a > peer_b):
      return (peer_b, peer_a)
    else:
      return (peer_a, peer_b)


  def generate_val(self, peer_a: int, peer_b: int) -> object:
    raise NotImplementedError()


  def assert_pair(self,
      peer_a: int,
      peer_b: int,
      val: Optional[Union[object, Callable]] = None) -> object:
    k = self.pair_key(peer_a, peer_b)
    stored = self.get(k)
    generated = False
    if stored is None:
      stored = (
        val() if callable(val) else
        val if val is not None else
        self.generate_val(peer_a, peer_b)
      )
      if stored is None:
        raise RuntimeError("failed to generate value")
      self[k] = stored
      generated = True
    return stored, generated


  def purge_peer(self, peer: int) -> dict:
    purged = {}
    for peer_a, peer_b in list(self):
      if peer != peer_a and peer != peer_b:
        continue
      k = (peer_a, peer_b)
      purged = self[k]
      del self[k]
    return purged


  def get_pair(self, peer_a: int, peer_b: int) -> str:
    return self[self.pair_key(peer_a, peer_b)]


  @classmethod
  def pick(cls, peer_a: int, peer_b: int, peer_target: int, val: Sequence[object]) -> object:
    key = PairedValuesMap.pair_key(peer_a, peer_b)
    peer_i = 0 if key[0] == peer_target else 1
    return val[peer_i]
