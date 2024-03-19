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
from typing import Iterable, Generator, Callable, TYPE_CHECKING
import json
from functools import cached_property

from ..core.paired_map import PairedValuesMap
from ..core.log import Logger as log
from .wg_key import WireGuardKeyPair, WireGuardPsk
from .versioned import Versioned

if TYPE_CHECKING:
  from .database import Database

class VpnKeysMap(Versioned, PairedValuesMap):
  PROPERTIES = [
    "prefix",
    "prefer_dropped",
    "purged",
    "deleted",
  ]
  REQ_PROPERTIES = [
    "prefix",
  ]
  STR_PROPERTIES = [
    "prefix",
  ]
  SERIALIZED_PROPERTIES = [
    "content",
  ]
  CACHED_PROPERTIES = [
    "content",
  ]
  KEYS: WireGuardKeyPair | WireGuardKeyPair | None = None
  INITIAL_PREFER_DROPPED = False
  INITIAL_PURGED = lambda self: set()
  INITIAL_DELETED = lambda self: set()


  def __init__(self, db: "Database", **kwargs) -> None:
    super().__init__(db=db, **kwargs)
    super(PairedValuesMap, self).__init__(self.content)


  def __init_subclass__(cls, *args, **kwargs):
    super().__init_subclass__(*args, **kwargs)


  @cached_property
  def content(self) -> dict:
    def _load_keys(dropped: bool):
      loaded = {}
      for key in self.db.load(self.KEYS,
          where="id LIKE ? AND dropped = ?",
          params=(f"{self.prefix}:%", dropped)):
        key_id = key.id[len(self.prefix)+1:]
        key_id_start = key_id.find(":")
        if key_id_start > 0:
          pair_str = key_id[:key_id_start]
          key_id = key_id[key_id_start+1:]
        else:
          pair_str = key_id
          key_id = None
        pair = tuple(json.loads(pair_str))
        self.load_key(loaded, pair, key, key_id or None)
      return loaded

    if self.prefer_dropped:
      loaded = _load_keys(True)
      for pair, key in _load_keys(False).items():
        if pair in loaded:
          continue
        loaded[pair] = key
    else:
      loaded = _load_keys(False)
    return loaded


  def assert_pair(self,
      peer_a: int,
      peer_b: int,
      val: object|Callable|None = None) -> tuple[object, bool]:
    value, asserted = super().assert_pair(peer_a, peer_b, val)
    if asserted:
      log.activity("[{}] asserted pair: {}", self, value if not isinstance(value, Iterable) else list(map(str, value)))
      self.updated_property("content")
    return value, asserted


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for pair, key in self.content.items():
      for key in self.iterate_keys(pair, key):
        yield key


  def key_id(self, pair: tuple, extra: str|None=None) -> str:
    return f"{self.prefix}:{json.dumps(pair)}{':'+extra if extra else ''}"


  def save(self, cursor: "Database.Cursor | None" = None, create: TYPE_CHECKING = False) -> None:
    for pair in self.purged:
      self.db.update_where(
        table=self.KEYS.DB_TABLE,
        where="id LIKE ? AND dropped = ?",
        params=(f"{self.key_id(pair)}:%", False),
        fields={
          "dropped": True,
        },
        cursor=cursor)
    self.purged.clear()
    for pair in self.deleted:
      self.db.delete_where(
        table=self.KEYS.DB_TABLE,
        where="id LIKE ? AND dropped = ?",
        params=(f"{self.key_id(pair)}:%", False),
        cursor=cursor,
        cls=self.KEYS)
    self.deleted.clear()
    super().save(cursor=cursor, create=create)


  def _drop_pair(self, pair: tuple, keys: object, delete: bool=False) -> None:
    # for key in self.iterate_keys(pair, keys):
    #   key.dropped = True
    if delete and pair not in self.deleted:
      self.deleted.add(pair)
      self.updated_property("deleted")
    elif not delete and pair not in self.purged:
      self.purged.add(pair)
      self.updated_property("purged")


  def purge_peer(self, peer: int, delete: bool=False) -> dict[tuple, object]:
    purged = super().purge_peer(peer)
    s_purged = set()
    for pair, keys in purged:
      self._drop_pair(pair, keys, delete=delete)
      s_purged.add(pair)
    if delete:
      total = self.deleted
    else:
      total = self.purged
    if s_purged:
      log.activity("[{}] peer {} {}: {}", self, peer, "deleted" if delete else "purged", ', '.join(map(str, sorted(total))))
      self.updated_property("content")
    return purged


  def clean_dropped_keys(self, cursor: "Database.Cursor|None"=None) -> None:
    self.db.delete_where(
      table=self.KEYS.DB_TABLE,
      where="id LIKE ? AND dropped = ?",
      params=(f"{self.prefix}:%", True),
      cursor=cursor,
      cls=self.KEYS)
    self.deleted.clear()
    self.purged.clear()


  def drop_keys(self, delete: bool=False, cursor: "Database.Cursor|None"=None) -> None:
    for pair in list(self):
      self._drop_pair(pair, self[pair], delete=delete)
    self.clear()
    log.activity("[{}] dropped all content", self)
    self.updated_property("content")


  def serialize_content(self, _: None) -> dict:
    return {
        json.dumps(k): self.serialize_pair(k, v)
          for k, v in self.items()
    }


  def prepare_content(self, val: dict[tuple, object]) -> None:
    dict.update(self, {
       k: self.prepare_pair(k, v)
        for k_in, v in (val or {}).items()
          for k in [tuple(json.safe_load(k_in)) if not isinstance(k_in, tuple) else k_in]
    })
    return None


  def iterate_keys(self, pair: tuple, key: object) -> Generator[object, None, None]:
    yield key


  def load_key(self, loaded: dict, pair: tuple, key: object, key_id: str | None=None) -> None:
    raise NotImplementedError()


  def serialize_pair(self, pair: tuple, key: object) -> object:
    raise NotImplementedError()


  def prepare_pair(self, pair: tuple, serialized_key: object) -> object:
    raise NotImplementedError()



class PresharedKeysMap(VpnKeysMap):
  KEYS = WireGuardPsk

  def __init__(self, db: "Database", **kwargs) -> None:
    # raise RuntimeError("wtf")
    super().__init__(db, **kwargs)
  
  def __init_subclass__(cls, *args, **kwargs):
    super().__init_subclass__(*args, **kwargs)


  def load_key(self, loaded: dict, pair: tuple, key: WireGuardPsk, key_id: str | None=None) -> None:
    loaded[pair] = key


  def serialize_pair(self, pair: tuple, key: WireGuardPsk) -> dict:
    return key.serialize()


  def prepare_pair(self, pair: tuple, serialized_key: dict) -> WireGuardPsk:
    return self.deserialize_child(self.KEYS, serialized_key)


  def generate_val(self, peer_a: int, peer_b: int) -> WireGuardPsk:
    pair = self.pair_key(peer_a, peer_b)
    log.activity("[{}] generated psk: {}", self, pair)
    return self.new_child(self.KEYS, id=self.key_id(pair))



class PairedVpnKeysMap(VpnKeysMap):
  KEYS = WireGuardKeyPair

  def __init__(self, db: "Database", **kwargs) -> None:
    # raise RuntimeError("wtf")
    # self.foo = "baz"
    super().__init__(db, **kwargs)

  def __init_subclass__(cls, *args, **kwargs):
    super().__init_subclass__(*args, **kwargs)

  def load_key(self, loaded: dict, pair: tuple, key: WireGuardKeyPair, key_id: str | None=None) -> None:
    key_i = int(key_id)
    pair_keys = loaded[pair] = loaded.get(pair, [])
    pair_keys.insert(key_i, key)


  def iterate_keys(self, pair: tuple, key: tuple[WireGuardKeyPair]) -> Generator[WireGuardKeyPair, None, None]:
    for k in key:
      yield k


  def generate_val(self, peer_a: int, peer_b: int) -> tuple[WireGuardKeyPair]:
    pair = self.pair_key(peer_a, peer_b)
    log.activity("[{}] generate keys: {}", self, pair)
    return [
      self.db.new(WireGuardKeyPair, id=f"{self.key_id(pair)}:{i}")
        for i in range(2)
    ]


  def serialize_pair(self, pair: tuple, key: tuple[WireGuardKeyPair]) -> tuple[dict]:
    return [k.serialize() for k in key]


  def prepare_pair(self, pair: tuple, serialized_key: tuple[dict | WireGuardKeyPair]) -> tuple[WireGuardKeyPair]:
    return self.deserialize_collection((self.KEYS, serialized_key, tuple, self.deserialize_child))


class CentralizedVpnKeyMaterial(Versioned):
  PROPERTIES = [
    "prefix",
    "prefer_dropped",
    "root_key",
    "peer_keys",
    "preshared_keys",
    "purged",
    "deleted",
  ]
  STR_PROPERTIES = [
    "prefix"
  ]

  INITIAL_PREFER_DROPPED = False
  INITIAL_PURGED = lambda self: set()
  INITIAL_DELETED = lambda self: set()
  def INITIAL_ROOT_KEY(self) -> WireGuardKeyPair | None:
    return next(self.db.load(WireGuardKeyPair, where="id = ?", params=(f"{self.prefix}:root",)), None)
  def INITIAL_PEER_KEYS(self) -> dict[int, WireGuardKeyPair]:
    prefix = f"{self.prefix}:peer:"
    def _load_keys(dropped: bool) -> dict:
      return {
        peer_id: key
        for key in self.db.load(WireGuardKeyPair, where="id LIKE ? AND dropped = ?", params=(f"{self.prefix}:peer:%", dropped, ))
          for peer_id in [int(key.id[len(prefix):])]
      }
    if self.prefer_dropped:
      loaded = _load_keys(True)
      for peer, key in _load_keys(False).items():
        if peer in loaded:
          continue
        loaded[peer] = key
    else:
      loaded = _load_keys(False)
    return loaded
  def INITIAL_PRESHARED_KEYS(self) -> PresharedKeysMap:
    return self.deserialize_child(PresharedKeysMap, {
      "prefix": f"{self.prefix}:psks",
      "prefer_dropped": self.prefer_dropped,
    })


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    if self.root_key:
      yield self.root_key
    for peer_key in self.peer_keys.values():
      yield peer_key
    yield self.preshared_keys


  def save(self, cursor: "Database.Cursor | None" = None, create: TYPE_CHECKING = False) -> None:
    for key in self.purged:
      self.db.update_where(
        table=WireGuardKeyPair.DB_TABLE,
        where="id = ? AND dropped = ?",
        params=(key.id, False),
        fields={
          "dropped": True,
        },
        cursor=cursor,
        cls=WireGuardKeyPair)
    self.purged.clear()
    for key in self.deleted:
      self.db.delete_where(
        table=WireGuardKeyPair.DB_TABLE,
        where="id = ? AND dropped = ?",
        params=(key.id, False),
        cursor=cursor,
        cls=WireGuardKeyPair)
    self.deleted.clear()
    super().save(cursor=cursor, create=create)


  def _drop_key(self, key: WireGuardKeyPair, delete: bool=False) -> None:
    if delete and key not in self.deleted:
      self.deleted.add(key)
      self.updated_property("deleted")
    elif not delete and key not in self.purged:
      self.purged.add(key)
      self.updated_property("purged")


  def assert_keys(self, peer_ids: Iterable[int]=None) -> None:
    if self.root_key is None:
      self.root_key = self.db.new(WireGuardKeyPair, id=f"{self.prefix}:root")
      log.activity("[VPN-KEYS][{}] generated root key: {}", self.prefix, self.root_key)
    for peer_id in (peer_ids or []):
      peer_key = self.peer_keys.get(peer_id)
      if peer_key is None:
        self.peer_keys[peer_id] = self.db.new(WireGuardKeyPair, id=f"{self.prefix}:peer:{peer_id}")
        log.activity("[VPN-KEYS][{}] generated peer key: {}", self.prefix, self.peer_keys[peer_id])
      self.preshared_keys.assert_pair(0, peer_id)


  def purge_gone_peers(self, peer_ids: Iterable[int], delete: bool=False) -> None:
    peer_ids = set(peer_ids)
    for peer_id in list(self.peer_keys):
      if peer_id not in peer_ids:
        log.activity("[VPN-KEYS][{}] purging gone peer: {}", self.prefix, peer_id)
        self._drop_key(self.peer_keys[peer_id], delete=delete)
        del self.peer_keys[peer_id]
        self.preshared_keys.purge_peer(peer_id, delete)


  def drop_keys(self, delete: bool=False, cursor: "Database.Cursor|None"=None) -> None:
    log.activity("[VPN-KEYS][{}] dropping all keys", self.prefix)
    if self.root_key:
      self._drop_key(self.root_key, delete=delete)
      self.root_key = None
    for key in self.peer_keys.values():
      self._drop_key(key, delete=delete)
    self.peer_keys = {}
    self.preshared_keys.drop_keys(delete=delete, cursor=cursor)


  def clean_dropped_keys(self, cursor: "Database.Cursor|None"=None) -> None:
    self.db.delete_where(
      table=WireGuardKeyPair.DB_TABLE,
      where="id LIKE ? AND dropped = ?",
      params=(f"{self.prefix}:%", True),
      cursor=cursor,
      cls=WireGuardKeyPair)
    self.deleted.clear()
    self.purged.clear()
    self.preshared_keys.clean_dropped_keys(cursor=cursor)


  def get_peer_material(self, peer: int) -> tuple[WireGuardKeyPair, WireGuardPsk]:
    peer_key = self.peer_keys[peer]
    peer_psk = self.preshared_keys.get_pair(0, peer)
    return (peer_key, peer_psk)



class P2PVpnKeyMaterial(Versioned):
  PROPERTIES = [
    "prefix",
    "pair_keys",
    "preshared_keys",
  ]
  STR_PROPERTIES = [
    "prefix"
  ]

  def INITIAL_PAIR_KEYS(self) -> PairedVpnKeysMap:
    return self.deserialize_child(PairedVpnKeysMap, {
      "prefix": f"{self.prefix}:pair",
    })
  def INITIAL_PRESHARED_KEYS(self) -> PresharedKeysMap:
    return self.deserialize_child(PresharedKeysMap, {
      "prefix": f"{self.prefix}:psks",
    })

  
  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.pair_keys
    yield self.preshared_keys


  def drop_keys(self, delete: bool=False, cursor: "Database.Cursor|None"=None) -> None:
    self.pair_keys.drop_keys(delete=delete, cursor=cursor)
    self.preshared_keys.drop_keys(delete=delete, cursor=cursor)


  def clean_dropped_keys(self, cursor: "Database.Cursor|None"=None) -> None:
    self.pair_keys.clean_dropped_keys(cursor=cursor)
    self.preshared_keys.clean_dropped_keys(cursor=cursor)


  def assert_pair(self, peer_a: int, peer_b: int) -> tuple[tuple[tuple[WireGuardKeyPair], WireGuardPsk], bool]:
    keys, asserted_k = self.pair_keys.assert_pair(peer_a, peer_b)
    psk, asserted_p = self.preshared_keys.assert_pair(peer_a, peer_b)
    asserted = asserted_k or asserted_p
    if asserted:
      log.activity("[VPN-KEYS][{}] generated key pair: [{}, {}]", self.prefix, peer_a, peer_b)
    return ((keys, psk), asserted)


  def get_pair_material(self, peer_a: int, peer_b: int) -> tuple[tuple[WireGuardKeyPair], WireGuardPsk]:
    pair_key = self.pair_keys.get_pair(peer_a, peer_b)
    pair_psk = self.preshared_keys.get_pair(peer_a, peer_b)
    return (pair_key, pair_psk)

