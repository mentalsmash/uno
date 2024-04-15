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
from typing import Iterable, Generator, Callable, TYPE_CHECKING
import json

from ..core.paired_map import PairedValuesMap

from .wg_key import WireGuardKeyPair, WireGuardPsk
from .versioned import Versioned, disabled_if, error_if, static_if, dispatch_if
from .database_object import inject_db_cursor

if TYPE_CHECKING:
  from .database import Database


class MissingKeyMaterial(Exception):
  pass


class VpnKeysMap(Versioned, PairedValuesMap):
  PROPERTIES = [
    "prefix",
    "prefer_dropped",
    "dropped",
    "deleted",
  ]
  EQ_PROPERTIES = [
    "prefix",
    "prefer_dropped",
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
  VOLATILE_PROPERTIES = [
    "deleted",
    "dropped",
  ]
  KEYS: WireGuardKeyPair | WireGuardKeyPair | None = None
  INITIAL_PREFER_DROPPED = False

  def INITIAL_DROPPED(self) -> dict:
    return {}

  def INITIAL_DELETED(self) -> dict:
    return {}

  def __init__(self, db: "Database", **kwargs) -> None:
    super().__init__(db=db, **kwargs)
    super(PairedValuesMap, self).__init__(self.content)
    dict.update(self, self._load_content())

  def __init_subclass__(cls, *args, **kwargs):
    super().__init_subclass__(*args, **kwargs)

  @property
  def content(self) -> dict:
    return self

  @inject_db_cursor
  def _load_content(self, cursor: "Database.Cursor") -> dict:
    def _load_keys(dropped: bool):
      loaded = {}
      for key in self.db.load(
        self.KEYS,
        where="key_id LIKE ? AND dropped = ?",
        params=(f"{self.prefix}:%", dropped),
        cursor=cursor,
      ):
        key_id = key.key_id[len(self.prefix) + 1 :]
        key_id_start = key_id.find(":")
        if key_id_start > 0:
          pair_str = key_id[:key_id_start]
          key_id = key_id[key_id_start + 1 :]
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

  @dispatch_if("readonly", "_ro_assert_pair")
  def assert_pair(
    self, peer_a: int, peer_b: int, val: object | Callable | None = None
  ) -> tuple[object, bool]:
    value, asserted = super().assert_pair(peer_a, peer_b, val)
    if asserted:
      self.log.activity(
        "asserted pair: {}", value if not isinstance(value, Iterable) else list(map(str, value))
      )
      self.updated_property("content")
    return value, asserted

  def _ro_assert_pair(
    self, peer_a: int, peer_b: int, val: object | Callable | None = None
  ) -> tuple[object, bool]:
    try:
      return self.get_pair(peer_a, peer_b)
    except KeyError:
      raise MissingKeyMaterial(self.prefix, self.pair_key(peer_a, peer_b))

  @property
  def nested(self) -> Generator[Versioned, None, None]:
    for pair, key in self.items():
      for key in self.iterate_keys(pair, key):
        yield key
    # for pair, keys in self.dropped.items():
    #   for key in self.iterate_keys(pair, keys):
    #     yield key
    # for pair, keys in self.deleted.items():
    #   for key in self.iterate_keys(pair, keys):
    #     yield key

  def key_id(self, pair: tuple, extra: str | None = None) -> str:
    return f"{self.prefix}:{json.dumps(pair)}{':'+extra if extra else ''}"

  def save(self, cursor: "Database.Cursor | None" = None, **db_args) -> None:
    # Changed keys were already returned by a "collect_changes()"
    # so clear the state
    for pair, keys in self.dropped.items():
      for key in self.iterate_keys(pair, keys):
        self.db.save(key, cursor=cursor)
    self.dropped.clear()
    # Save remaining changes to this object (noop, other than resetting status flags)
    for pair, keys in self.deleted.items():
      for key in self.iterate_keys(pair, keys):
        self.db.delete(key, cursor=cursor)
    # Save remaining changes to this object (noop, other than resetting status flags)
    super().save(cursor=cursor, **db_args)

  @error_if("readonly")
  def _drop_pair(self, pair: tuple, keys: object, delete: bool = False) -> None:
    for key in self.iterate_keys(pair, keys):
      key.dropped = True
      # if delete:
      #   key.disposed = True
    if delete and pair not in self.deleted:
      self.deleted[pair] = keys
      self.updated_property("deleted")
    elif not delete and pair not in self.dropped:
      self.dropped[pair] = keys
      self.updated_property("dropped")

  @static_if("readonly", dict)
  @inject_db_cursor
  def purge_peer(
    self,
    peer: int,
    delete: bool = False,
    delete_map: dict | None = None,
    cursor: "Database.Cursor|None" = None,
  ) -> dict[tuple, object]:
    purged = super().purge_peer(peer)
    deleted = set()
    dropped = set()
    delete_map = delete_map or {}
    for pair, keys in purged.items():
      delete_pair = delete or delete_map.get(pair[0], False) or delete_map.get(pair[1], False)
      self._drop_pair(pair, keys, delete=delete_pair)
      if delete_pair:
        deleted.add((pair, keys))
      else:
        dropped.add((pair, keys))
    if dropped:
      self.log.activity("dropped {} paired keys for peer {}: {}", len(dropped), peer, dropped)
    if deleted:
      self.log.activity("deleted {} paired keys for peer {}: {}", len(deleted), peer, deleted)
      self.db.save(self, cursor=cursor)
    if dropped or deleted:
      self.updated_property("content")
    return purged

  @inject_db_cursor
  def clean_dropped_keys(self, cursor: "Database.Cursor|None" = None) -> None:
    self.db.delete_where(
      table=self.KEYS.DB_TABLE,
      where="key_id LIKE ? AND dropped = ?",
      params=(f"{self.prefix}:%", True),
      cursor=cursor,
      cls=self.KEYS,
    )

  @static_if("readonly", 0)
  @inject_db_cursor
  def drop_keys(
    self,
    delete: bool = False,
    delete_map: dict | None = None,
    cursor: "Database.Cursor|None" = None,
  ) -> int:
    deleted = set()
    dropped = set()
    delete_map = delete_map or {}
    for pair in list(self):
      delete_pair = delete or delete_map.get(pair[0], False) or delete_map.get(pair[1], False)
      self._drop_pair(pair, self[pair], delete=delete_pair)
      if delete_pair:
        deleted.add(pair)
      else:
        dropped.add(pair)
    self.clear()
    if deleted:
      self.db.save(self, cursor=cursor)
    if deleted or dropped:
      self.updated_property("content")
    count = len(deleted) + len(dropped)
    self.log.activity("dropped all ({}) keys (deleted={}, dropped={})", count, deleted, dropped)
    return count

  def serialize_content(self, _: None, public: bool = False) -> dict:
    return {json.dumps(k): self.serialize_pair(k, v, public=public) for k, v in self.items()}

  # def prepare_content(self, val: dict[tuple, object]) -> None:
  #   dict.update(self, {
  #      k: self.prepare_pair(k, v)
  #       for k_in, v in (val or {}).items()
  #         for k in [tuple(json.safe_load(k_in)) if not isinstance(k_in, tuple) else k_in]
  #   })
  #   return None

  def iterate_keys(self, pair: tuple, key: object) -> Generator[object, None, None]:
    yield key

  def load_key(self, loaded: dict, pair: tuple, key: object, key_id: str | None = None) -> None:
    raise NotImplementedError()

  def serialize_pair(self, pair: tuple, key: object, public: bool = False) -> object:
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

  def load_key(
    self, loaded: dict, pair: tuple, key: WireGuardPsk, key_id: str | None = None
  ) -> None:
    loaded[pair] = key

  def serialize_pair(self, pair: tuple, key: WireGuardPsk, public: bool = False) -> dict:
    return key.serialize(public=public)

  def prepare_pair(self, pair: tuple, serialized_key: dict) -> WireGuardPsk:
    return self.new_child(self.KEYS, serialized_key)

  @error_if("readonly")
  def generate_val(self, peer_a: int, peer_b: int) -> WireGuardPsk:
    pair = self.pair_key(peer_a, peer_b)
    self.log.activity("generated psk: {}", pair)
    return self.new_child(self.KEYS, {"key_id": self.key_id(pair)})


class PairedVpnKeysMap(VpnKeysMap):
  KEYS = WireGuardKeyPair

  def __init__(self, db: "Database", **kwargs) -> None:
    # raise RuntimeError("wtf")
    # self.foo = "baz"
    super().__init__(db, **kwargs)

  def __init_subclass__(cls, *args, **kwargs):
    super().__init_subclass__(*args, **kwargs)

  def load_key(
    self, loaded: dict, pair: tuple, key: WireGuardKeyPair, key_id: str | None = None
  ) -> None:
    key_i = int(key_id)
    pair_keys = loaded[pair] = loaded.get(pair, [])
    pair_keys.insert(key_i, key)

  def iterate_keys(
    self, pair: tuple, key: tuple[WireGuardKeyPair]
  ) -> Generator[WireGuardKeyPair, None, None]:
    for k in key:
      yield k

  @error_if("readonly")
  def generate_val(self, peer_a: int, peer_b: int) -> tuple[WireGuardKeyPair]:
    pair = self.pair_key(peer_a, peer_b)
    self.log.activity("generate keys: {}", pair)
    return [
      self.new_child(WireGuardKeyPair, {"key_id": f"{self.key_id(pair)}:{i}"}) for i in range(2)
    ]

  def serialize_pair(
    self, pair: tuple, key: tuple[WireGuardKeyPair], public: bool = False
  ) -> tuple[dict]:
    return [k.serialize(public=public) for k in key]

  def prepare_pair(
    self, pair: tuple, serialized_key: tuple[dict | WireGuardKeyPair]
  ) -> tuple[WireGuardKeyPair]:
    return self.deserialize_collection(
      (self.KEYS, serialized_key, tuple, lambda cls, val: self.new_child(cls, val, save=False))
    )


class CentralizedVpnKeyMaterial(Versioned):
  PROPERTIES = [
    "prefix",
    "peer_ids",
    "prefer_dropped",
    "root_key",
    "peer_keys",
    "preshared_keys",
    "dropped",
    "deleted",
  ]
  EQ_PROPERTIES = [
    "prefix",
    # "peer_ids",
    "prefer_dropped",
  ]
  REQ_PROPERTIES = [
    "prefix",
    "peer_ids",
  ]
  STR_PROPERTIES = ["prefix"]
  VOLATILE_PROPERTIES = [
    "deleted",
    "dropped",
  ]

  INITIAL_READONLY = False
  INITIAL_PREFER_DROPPED = False

  def INITIAL_DROPPED(self) -> set:
    return set()

  def INITIAL_DELETED(self) -> set:
    return set()

  @inject_db_cursor
  def load_root_key(self, cursor: "Database.Cursor") -> WireGuardKeyPair | None:
    def _load_key(dropped: bool) -> WireGuardKeyPair | None:
      return next(
        self.db.load(
          WireGuardKeyPair,
          where="key_id = ? and dropped = ?",
          params=(f"{self.prefix}:root", dropped),
          cursor=cursor,
        ),
        None,
      )

    loaded = None if not self.prefer_dropped else _load_key(True)
    if loaded is None:
      loaded = _load_key(False)
    return loaded

  @inject_db_cursor
  def load_peer_keys(self, cursor: "Database.Cursor") -> dict[int, WireGuardKeyPair]:
    prefix = f"{self.prefix}:peer:"

    def _load_keys(dropped: bool) -> dict:
      return {
        peer_id: key
        for key in self.db.load(
          WireGuardKeyPair,
          where="key_id LIKE ? AND dropped = ?",
          params=(
            f"{self.prefix}:peer:%",
            dropped,
          ),
          cursor=cursor,
        )
        for peer_id in [int(key.key_id[len(prefix) :])]
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

  def load_preshared_keys(self) -> PresharedKeysMap:
    return self.new_child(
      PresharedKeysMap,
      {
        "prefix": f"{self.prefix}:psks",
        "prefer_dropped": self.prefer_dropped,
        "readonly": self.readonly,
      },
    )

  @inject_db_cursor
  def load_nested(self, cursor: "Database.Cursor") -> None:
    self.root_key = self.load_root_key(cursor=cursor)
    self.peer_keys = self.load_peer_keys(cursor=cursor)
    self.preshared_keys = self.load_preshared_keys()

  @property
  def nested(self) -> Generator[Versioned, None, None]:
    if self.root_key:
      yield self.root_key
    for peer_key in self.peer_keys.values():
      yield peer_key
    for key in self.dropped:
      yield key
    yield self.preshared_keys

  def save(self, cursor: "Database.Cursor | None" = None, **db_args) -> None:
    # Changed keys were already returned by a "collect_changes()"
    # so clear the state
    self.dropped.clear()
    # Delete any key from the database that was dropped+delete
    for key in self.deleted:
      self.db.delete(key, cursor=cursor)
    self.deleted.clear()
    # Save remaining changes to this object (noop, other than resetting status flags)
    super().save(cursor=cursor, **db_args)

  @property
  def peers_with_dropped_key(self) -> set[int]:
    return set(k for k, v in self.peer_keys.items() if v is not None and v.dropped)

  @error_if("readonly")
  def _drop_key(self, key: WireGuardKeyPair, delete: bool = False) -> None:
    key.dropped = True
    if delete and key not in self.deleted:
      self.deleted.add(key)
      self.updated_property("deleted")
    elif not delete and key not in self.dropped:
      self.dropped.add(key)
      self.updated_property("dropped")

  @disabled_if("readonly")
  def assert_keys(self) -> None:
    self.log.trace("asserting keys for {} peers", len(self.peer_ids))
    if self.root_key is None:
      self.root_key = self.new_child(WireGuardKeyPair, {"key_id": f"{self.prefix}:root"})
      self.log.activity("generated root key: {}", self.root_key)
    for peer_id in self.peer_ids or []:
      peer_key = self.peer_keys.get(peer_id)
      if peer_key is None:
        self.peer_keys[peer_id] = self.new_child(
          WireGuardKeyPair, {"key_id": f"{self.prefix}:peer:{peer_id}"}
        )
        self.updated_property("peer_keys")
        self.log.activity("generated peer key: {}", self.peer_keys[peer_id])
      self.preshared_keys.assert_pair(0, peer_id)

  @static_if("readonly", tuple)
  @inject_db_cursor
  def purge_gone_peers(
    self,
    peer_ids: Iterable[int],
    delete: bool = False,
    delete_map: dict | None = None,
    cursor: "Database.Cursor|None" = None,
  ) -> list[int]:
    peer_ids = set(peer_ids)
    delete_map = delete_map or {}
    dropped = set()
    deleted = set()
    for peer_id in list(self.peer_keys):
      if peer_id not in peer_ids:
        self.log.activity("purging gone peer: {}", peer_id)
        delete_key = delete or delete_map.get(peer_id, False)
        self._drop_key(self.peer_keys[peer_id], delete=delete_key)
        del self.peer_keys[peer_id]
        self.preshared_keys.purge_peer(peer_id, delete=delete, delete_map=delete_map, cursor=cursor)
        if delete_key:
          deleted.add(peer_id)
        else:
          dropped.add(peer_id)
    if deleted:
      # Immediately drop keys from database by saving the object
      self.db.save(self, cursor=cursor)
    return [*deleted, *dropped]

  @static_if("readonly", 0)
  @inject_db_cursor
  # TODO(asorbini) inject transaction?
  def drop_keys(
    self,
    delete: bool = False,
    delete_map: dict | None = None,
    cursor: "Database.Cursor|None" = None,
  ) -> int:
    self.log.activity("dropping all keys")
    delete_map = delete_map or {}
    dropped = set()
    deleted = set()
    if self.root_key:
      delete_key = delete or delete_map.get(0, False)
      self._drop_key(self.root_key, delete=delete_key)
      self.root_key = None
      if delete_key:
        deleted.add(0)
      else:
        dropped.add(0)
    for peer_id, key in self.peer_keys.items():
      delete_key = delete or delete_map.get(peer_id, False)
      self._drop_key(key, delete=delete_key)
      if delete_key:
        deleted.add(peer_id)
      else:
        dropped.add(peer_id)
    self.peer_keys = {}
    count = len(deleted) + len(dropped)
    count_preshared = self.preshared_keys.drop_keys(
      delete=delete, delete_map=delete_map, cursor=cursor
    )
    if deleted:
      # Immediately drop deleted keys from database by saving the object
      self.db.save(self, cursor=cursor)
    self.log.activity(
      "dropped all ({} + {}) keys (deleted={}, dropped={})",
      count,
      count_preshared,
      deleted,
      dropped,
    )
    return count + count_preshared

  @inject_db_cursor
  # TODO(asorbini) inject transaction?
  def clean_dropped_keys(self, cursor: "Database.Cursor|None" = None) -> None:
    self.db.delete_where(
      table=WireGuardKeyPair.DB_TABLE,
      where="key_id LIKE ? AND dropped = ?",
      params=(f"{self.prefix}:%", True),
      cursor=cursor,
      cls=WireGuardKeyPair,
    )
    self.preshared_keys.clean_dropped_keys(cursor=cursor)

  def get_peer_material(
    self, peer: int, private: bool = False
  ) -> tuple[WireGuardKeyPair | WireGuardPsk]:
    try:
      result = []
      if peer == 0:
        if private:
          if self.root_key is None:
            raise KeyError(0)
          result.append(self.root_key)

        for peer in self.peer_ids:
          if not private:
            peer_key = self.peer_keys[peer]
            result.append(peer_key)
          else:
            peer_psk = self.preshared_keys.get_pair(0, peer)
            result.append(peer_psk)
      else:
        if private:
          peer_key = self.peer_keys[peer]
          result.append(peer_key)
          peer_psk = self.preshared_keys.get_pair(0, peer)
          result.append(peer_psk)
        else:
          if self.root_key is None:
            raise KeyError(0)
          result.append(self.root_key)
      return result
    except KeyError:
      raise MissingKeyMaterial(self.prefix, peer)


class P2pVpnKeyMaterial(Versioned):
  PROPERTIES = [
    "prefix",
    "pair_keys",
    "preshared_keys",
  ]
  EQ_PROPERTIES = [
    "prefix",
  ]
  STR_PROPERTIES = ["prefix"]

  # INITIAL_PAIR_KEYS = lambda self: self.new_child(PairedVpnKeysMap, {
  #   "prefix": f"{self.prefix}:pair",
  # })
  # INITIAL_PRESHARED_KEYS = lambda self: self.new_child(PresharedKeysMap, {
  #   "prefix": f"{self.prefix}:psks",
  # })

  def load_nested(self) -> None:
    if self.pair_keys is None:
      self.pair_keys = self.new_child(
        PairedVpnKeysMap,
        {
          "prefix": f"{self.prefix}:pair",
        },
      )
    if self.preshared_keys is None:
      self.preshared_keys = self.new_child(
        PresharedKeysMap,
        {
          "prefix": f"{self.prefix}:psks",
        },
      )

  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.pair_keys
    yield self.preshared_keys

  @static_if("readonly", 0)
  def drop_keys(self, delete: bool = False, cursor: "Database.Cursor|None" = None) -> int:
    self.log.activity("dropping all keys")
    count = 0
    count += self.pair_keys.drop_keys(delete=delete, cursor=cursor)
    count += self.preshared_keys.drop_keys(delete=delete, cursor=cursor)
    if delete:
      # Immediately drop keys from database by saving the object
      self.db.save(self)
    if count:
      self.log.activity("dropped all ({}) keys", count)
    return count

  def clean_dropped_keys(self, cursor: "Database.Cursor|None" = None) -> None:
    self.pair_keys.clean_dropped_keys(cursor=cursor)
    self.preshared_keys.clean_dropped_keys(cursor=cursor)

  @dispatch_if("readonly", "_ro_assert_pair")
  def assert_pair(
    self, peer_a: int, peer_b: int
  ) -> tuple[tuple[tuple[WireGuardKeyPair], WireGuardPsk], bool]:
    keys, asserted_k = self.pair_keys.assert_pair(peer_a, peer_b)
    psk, asserted_p = self.preshared_keys.assert_pair(peer_a, peer_b)
    asserted = asserted_k or asserted_p
    if asserted:
      self.log.activity("generated key pair: [{}]", self.pair_keys.pair_key(peer_a, peer_b))
    return ((keys, psk), asserted)

  def _ro_assert_pair(
    self, peer_a: int, peer_b: int
  ) -> tuple[tuple[tuple[WireGuardKeyPair], WireGuardPsk], bool]:
    keys, psk = self.get_pair_material(peer_a, peer_b)
    if keys is None or psk is None:
      raise MissingKeyMaterial(self.prefix, self.pair_keys.pair_key(peer_a, peer_b))
    return ((keys, psk), False)

  def get_pair_material(
    self, peer_a: int, peer_b: int
  ) -> tuple[tuple[WireGuardKeyPair], WireGuardPsk]:
    try:
      pair_key = self.pair_keys.get_pair(peer_a, peer_b)
      pair_psk = self.preshared_keys.get_pair(peer_a, peer_b)
      return (pair_key, pair_psk)
    except KeyError:
      raise MissingKeyMaterial(self.prefix, self.pair_keys.pair_key(peer_a, peer_b))

  def get_peer_material(
    self, peer: int, private: bool = False
  ) -> list[WireGuardKeyPair | WireGuardPsk]:
    material = []
    for pair, keys in self.pair_keys.items():
      if peer not in pair:
        continue
      other = next((p for p in pair if p != peer))
      key = self.pair_keys.pick(peer, other, peer if private else other, keys)
      material.append(key)

    if private:
      for pair, psk in self.preshared_keys.items():
        if peer not in pair:
          continue
        material.append(psk)

    return material
