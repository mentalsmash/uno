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
from typing import Callable, Sequence


class PairedValuesMap(dict):
  @classmethod
  def pair_key(cls, peer_a: int, peer_b: int):
    if peer_a > peer_b:
      return (peer_b, peer_a)
    else:
      return (peer_a, peer_b)

  def generate_val(self, peer_a: int, peer_b: int) -> object:
    raise NotImplementedError()

  def assert_pair(self, peer_a: int, peer_b: int, val: object | Callable | None = None) -> object:
    k = self.pair_key(peer_a, peer_b)
    stored = self.get(k)
    generated = False
    if stored is None:
      stored = (
        val() if callable(val) else val if val is not None else self.generate_val(peer_a, peer_b)
      )
      if stored is None:
        raise RuntimeError("failed to generate value")
      self[k] = stored
      generated = True
    return stored, generated

  def purge_peer(self, peer: int) -> dict[tuple[int, int], object]:
    purged = {}
    for peer_a, peer_b in list(self):
      if peer != peer_a and peer != peer_b:
        continue
      k = self.pair_key(peer_a, peer_b)
      purged[k] = self[k]
      del self[k]
    return purged

  def get_pair(self, peer_a: int, peer_b: int) -> str:
    return self[self.pair_key(peer_a, peer_b)]

  @classmethod
  def pick(cls, peer_a: int, peer_b: int, peer_target: int, val: Sequence[object]) -> object:
    key = PairedValuesMap.pair_key(peer_a, peer_b)
    peer_i = 0 if key[0] == peer_target else 1
    return val[peer_i]
