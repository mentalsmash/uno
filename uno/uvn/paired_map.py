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
  @staticmethod
  def pair_key(peer_a: int, peer_b: int):
    if (peer_a > peer_b):
      return (peer_b, peer_a)
    else:
      return (peer_a, peer_b)


  def generate_val(self, peer_a: int, peer_b: int) -> object:
    raise NotImplementedError()


  def assert_pair(self,
      peer_a: int,
      peer_b: int,
      val: Optional[Union[object, Callable]] = None) -> Optional[object]:
    k = self.pair_key(peer_a, peer_b)
    stored = self.get(k)
    if stored is None:
      stored = self[k] = (
        val() if callable(val) else
        val if val is not None else
        self.generate_val(peer_a, peer_b)
      )
    return stored


  def purge_peer(self, peer: int) -> None:
    for peer_a, peer_b in list(self):
      if peer != peer_a and peer != peer_b:
        continue
      del self[(peer_a, peer_b)]


  def get_pair(self, peer_a: int, peer_b: int) -> str:
    return self[self.pair_key(peer_a, peer_b)]


  @staticmethod
  def pick(peer_a: int, peer_b: int, peer_target: int, val: Sequence[object]) -> object:
    key = PairedValuesMap.pair_key(peer_a, peer_b)
    peer_i = 0 if key[0] == peer_target else 1
    return val[peer_i]
