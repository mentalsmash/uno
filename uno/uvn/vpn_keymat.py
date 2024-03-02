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
from typing import Optional, Tuple, Mapping, Sequence, Iterable
import yaml
import json

from .wg import WireGuardKeyPair, genkeypreshared
from .uvn_id import UvnId
from .paired_map import PairedValuesMap


class PresharedKeysMap(PairedValuesMap):
  def generate_val(self, peer_a: int, peer_b: int) -> str:
    return genkeypreshared()


  def serialize(self,
      target_peers: Optional[Sequence[int]] = None) -> dict:
    serialized = {
       json.dumps(k): v
        for k, v in self.items()
          if target_peers is None or
            (k[0] in target_peers or k[1] in target_peers)
    }
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "PresharedKeysMap":
    return PresharedKeysMap({
       tuple(yaml.safe_load(k)): v
        for k, v in serialized.items()
    })


class PairedVpnKeysMap(PairedValuesMap):
  def generate_val(self, peer_a: int, peer_b: int) -> Tuple[WireGuardKeyPair, WireGuardKeyPair]:
    return (WireGuardKeyPair.generate(), WireGuardKeyPair.generate())


  def serialize(self) -> dict:
    serialized = {
       json.dumps(k): [
         v[0].serialize(),
         v[1].serialize(),
       ] for k, v in self.items()
    }
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "PairedVpnKeysMap":
    return PairedVpnKeysMap({
       tuple(yaml.safe_load(k)): (
          WireGuardKeyPair.deserialize(v[0]),
          WireGuardKeyPair.deserialize(v[1])
        ) for k, v in serialized.items()
    })


class CentralizedVpnKeyMaterial:
  def __init__(self,
      root_key: Optional[WireGuardKeyPair]=None,
      peer_keys: Optional[Mapping[int, WireGuardKeyPair]]=None,
      preshared_keys: Optional[PresharedKeysMap]=None) -> None:
    self.root_key = root_key
    self.peer_keys = dict(peer_keys or {})
    self.preshared_keys = preshared_keys or PresharedKeysMap()


  def assert_keys(self, peer_ids: Optional[Iterable[int]]=None) -> None:
    if self.root_key is None:
      self.root_key = WireGuardKeyPair.generate()
    for cell_id in (peer_ids or []):
      cell_key = self.peer_keys.get(cell_id)
      if cell_key is None:
        self.peer_keys[cell_id] = WireGuardKeyPair.generate()
      self.preshared_keys.assert_pair(0, cell_id)


  def purge_gone_peers(self, peer_ids: Iterable[int]) -> None:
    peer_ids = set(peer_ids)
    for peer_id in list(self.peer_keys):
      if peer_id not in peer_ids:
        del self.peer_keys[peer_id]
        self.preshared_keys.purge_peer(peer_id)


  def drop_keys(self) -> None:
    self.root_key = None
    self.peer_keys = {}
    self.preshared_keys = PresharedKeysMap()


  def get_peer_material(self, peer: int) -> Tuple[WireGuardKeyPair, str]:
    peer_key = self.peer_keys[peer]
    peer_psk = self.preshared_keys.get_pair(0, peer)
    return (peer_key, peer_psk)


  def serialize(self) -> dict:
    serialized = {
      "root": self.root_key.serialize()
        if self.root_key is not None else None,
      "peers": {
        k: v.serialize()
          for k, v in self.peer_keys.items()
      },
      "psks": self.preshared_keys.serialize(),
    }
    if not serialized["root"]:
      del serialized["root"]
    if not serialized["psks"]:
      del serialized["psks"]
    if not serialized["peers"]:
      del serialized["peers"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "CentralizedVpnKeyMaterial":
    return CentralizedVpnKeyMaterial(
      root_key=WireGuardKeyPair.deserialize(serialized["root"]),
      peer_keys={
        k: WireGuardKeyPair.deserialize(v)
          for k, v in serialized.get("peers", {}).items()
      },
      preshared_keys=PresharedKeysMap.deserialize(serialized.get("psks", {})))


class P2PVpnKeyMaterial:
  def __init__(self,
      pair_keys: Optional[PairedVpnKeysMap]=None,
      preshared_keys: Optional[PresharedKeysMap]=None) -> None:
    self.pair_keys = pair_keys or PairedVpnKeysMap()
    self.preshared_keys = preshared_keys or PresharedKeysMap()


  def drop_keys(self) -> None:
    self.pair_keys = PairedVpnKeysMap()
    self.preshared_keys = PresharedKeysMap()


  def assert_pair(self, peer_a: int, peer_b: int) -> Tuple[Tuple[WireGuardKeyPair, WireGuardKeyPair], str]:
    keys = self.pair_keys.assert_pair(peer_a, peer_b)
    psk = self.preshared_keys.assert_pair(peer_a, peer_b)
    return (keys, psk)


  def get_pair_material(self, peer_a: int, peer_b: int) -> Tuple[Tuple[WireGuardKeyPair, WireGuardKeyPair], str]:
    pair_key = self.pair_keys.get_pair(peer_a, peer_b)
    pair_psk = self.preshared_keys.get_pair(peer_a, peer_b)
    return (pair_key, pair_psk)


  def serialize(self) -> dict:
    serialized = {
      "pairs": self.pair_keys.serialize(),
      "psks": self.preshared_keys.serialize()
    }
    if not serialized["psks"]:
      del serialized["psks"]
    if not serialized["pairs"]:
      del serialized["pairs"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "P2PVpnKeyMaterial":
    return P2PVpnKeyMaterial(
      pair_keys=PairedVpnKeysMap.deserialize(serialized.get("pairs", {})),
      preshared_keys=PresharedKeysMap.deserialize(serialized.get("psks", {})))


