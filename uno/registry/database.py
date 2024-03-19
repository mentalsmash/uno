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
from typing import Generator, Iterable, Mapping
from pathlib import Path
import sqlite3
import yaml
from importlib.resources import files, as_file

from collections import namedtuple

from .versioned import Versioned

from ..data import database as db_data
from ..core.time import Timestamp
from ..core.log import Logger as log, log_debug

from .database_object import DatabaseObject, OwnableDatabaseObject, DatabaseObjectOwner, DatabaseSchema

def namedtuple_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    cls = namedtuple("Row", fields)
    return cls._make(row)


# def adapt_timestamp(ts: Timestamp) -> str:
#   return ts.format()

# def convert_timestamp(val: bytes) -> Timestamp:
#   return Timestamp.parse(val.decode())

# def adapt_yaml(val: dict | list | set) -> str:
#   if isinstance(val, (set, list)):
#     val = sorted(val)
#   return yaml.safe_dump(val)

# def convert_yaml(val: bytes) -> dict | list:
#   return yaml.safe_load(val.decode())


class Database:
  Cursor = sqlite3.Cursor

  DB_NAME = "uno.db"

  DB_TYPES = (bool, int, float, str, None.__class__)


  def __init__(self,
      root: Path) -> None:
    self.root = root.resolve()
    self._cursor = None
    self._cache = {}
    self._db_file = self.root / self.DB_NAME
    if not self._db_file.exists():
      self._db_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      self._db_file.touch(mode=0o600)
    self._db = sqlite3.connect(
      self._db_file,
      isolation_level="DEFERRED",
      detect_types=sqlite3.PARSE_DECLTYPES)
    self._db.row_factory = namedtuple_factory
    def _tracer(query) -> None:
      log_debug("[DB-SQL] {}", query)
    self._db.set_trace_callback(_tracer)
    # sqlite3.register_adapter(Timestamp, adapt_timestamp)
    # sqlite3.register_converter("timestamp", convert_timestamp)
    # for t in [dict, list, set]:
    #   sqlite3.register_adapter(t, adapt_yaml)
    #   sqlite3.register_converter(t.__name__.lower(), convert_yaml)


  def __str__(self) -> str:
    return f"{self.__class__.__qualname__}({self.root})"


  def next_id(self, table: str) -> int:
    next_id = self._db.execute(
      f"SELECT next FROM next_id WHERE target = ?",
      (table,)).fetchone().next
    next_id += 1
    self._db.execute(
      f"UPDATE next_id SET next = ? WHERE target = ?",
      (next_id, table))
    return next_id


  def initialize(self) -> None:
    with as_file(files(db_data).joinpath("initialize.sql")) as init_script:
      self._db.executescript(init_script.read_text())


  def close(self) -> None:
    self._db.close()


  def object_credentials_table(self, target: OwnableDatabaseObject|type, required: bool=True, owner_cls: type|None=None) -> str:
    if target.DB_OWNER_TABLE is not None and isinstance(target.DB_OWNER_TABLE, str):
      if owner_cls is not None and owner_cls != target.DB_OWNER:
        raise ValueError("invalid owner class", owner_cls, target.DB_OWNER)
      table = target.DB_OWNER_TABLE
    elif target.DB_OWNER_TABLE is not None and isinstance(target.DB_OWNER_TABLE, dict):
      if owner_cls is not None:
        raise ValueError("an owner class is required")
      table = target.DB_OWNER_TABLE.get(owner_cls)
    elif target.DB_OWNER_TABLE_COLUMN:
      table = target.DB_TABLE
    if table is None and required:
      raise NotImplementedError("no owner table defined", target)
    return table


  def object_table(self, target: DatabaseObject|type, required: bool=True, owner_cls: type|None=None) -> str:
    table = getattr(target, "DB_TABLE", None)
    if table is None and required:
      raise NotImplementedError("no database table defined", target)
    return table
      

  def save(self,
      obj: DatabaseObject,
      chown: Mapping[DatabaseObjectOwner, list[OwnableDatabaseObject]]|None=None,
      cursor: sqlite3.Cursor | None = None) -> None:
    return self.save_all([obj], chown=chown, cursor=cursor)


  def save_all(self,
      targets: Iterable[DatabaseObject],
      chown: Mapping[DatabaseObjectOwner, list[OwnableDatabaseObject]]|None=None,
      cursor: sqlite3.Cursor | None = None) -> None:
    def _query_targets() -> Generator[object, None, None]:
      for tgt in targets:
        for changed, _ in tgt.collect_changes():
          yield changed

    query_targets = list(_query_targets())
    current_owners = {
      tgt: self.owner(tgt)
        for tgt in query_targets
          if isinstance(tgt, OwnableDatabaseObject) and tgt.id
    }
    log.debug("[DB] save input: {}", list(map(str, targets)))
    log.debug("[DB] save targets: {}", list(map(str, query_targets)))

    if cursor is None:
      cursor = self._db.cursor()
    with self._db:
      for tgt in query_targets:
        table = self.object_table(tgt, required=False)
        # if not table:
        #   continue
        create = table and not tgt.loaded
        if hasattr(tgt, "save"):
          if table is not None and tgt.id is None:
            tgt.id = self.next_id(table)
          if create:
            log.debug("[DB] insert new {}: {}", tgt.__class__.__qualname__, tgt)
          else:
            log.debug("[DB] saving {}: {}", tgt.__class__.__qualname__, tgt)
          tgt.save(cursor=cursor, create=create)
          tgt.saved = table is not None
          if not table:
            log.activity("[DB] saved {}: {}", tgt.__class__.__qualname__, tgt)
          else:
            if create:
              log.info("[DB] inserted {}: {}", tgt.__class__.__qualname__, tgt)
            else:
              log.info("[DB] updated  {}: {}", tgt.__class__.__qualname__, tgt)
          if hasattr(tgt, "clear_changed"):
            tgt.clear_changed()
        else:
          raise NotImplementedError()
      for user, targets in (chown or {}).items():
        self._set_ownership(user, targets, current_owners=current_owners, cursor=cursor)



  def create_or_update(self,
      obj: DatabaseObject,
      fields: dict[str, object],
      create: bool=False,
      cursor: sqlite3.Cursor | None = None,
      obj_id: int | None = None,
      table: str | None = None):
    if table is None:
      table = self.object_table(obj)
    if obj_id is None:
      if hasattr(obj, "id"):
        obj_id = obj.id
      else:
        raise NotImplementedError()
    if isinstance(obj, Versioned):
      fields.update({
        "generation_ts": obj.generation_ts.format(),
        "init_ts": obj.init_ts.format()
      })
    sorted_keys = sorted(fields)
    sorted_values = [fields[k] for k in sorted_keys]
    if create:
      query = (
        f"INSERT INTO {table} ({', '.join(('id', *sorted_keys))}) VALUES ({', '.join('?' for _ in range(len(fields)+1))})",
        (obj_id, *sorted_values),
      )
    else:
      query = (
        f"UPDATE {table} SET " + ", ".join(f"{f} = ?" for f in sorted_keys) + " WHERE id =  ? ",
        (*sorted_values, obj_id),
      )
    if cursor is None:
      cursor = self._db
    log.debug("[DB] issue SQL query '{}' values {}", *query)
    cursor.execute(*query)


  def update_where(self, table: str, where: str, fields: dict, params: tuple | None=None, cursor: Cursor|None=None) -> None:
    s_fields = sorted(fields.items(), key=lambda i: i[0])
    query = (
      f"UPDATE {table} SET {', '.join(i[0] + ' = ?' for i in s_fields)} WHERE {where}",
      (*(i[1] for i in s_fields), *params),
    )
    if cursor is None:
      cursor = self._db
    cursor.execute(*query)



  def _delete(self, table: str, query: str, params: tuple | None=None, cursor: "Database.Cursor|None"=None, cls: type|None=None) -> None:
    if cursor is None:
      cursor = self._db
    if cls is not None:
      assert(issubclass(cls, Versioned))
      eq_props = sorted(cls.SCHEMA.eq_properties)
      query = f"{query} RETURNING {', '.join(eq_props)}"
    log.debug("[DB] delete {} query: {} values {}", "rows" if cls is None else cls.__qualname__, query, params)
    result = cursor.execute(query, params or [])
    if cls is not None:
      for row in result:
        log.info(f"[DB] deleted record: {'{}'}, {', '.join('{} = {}' for _ in eq_props)}",
          table,
          *(f for p in eq_props for f in (p, getattr(row, p))))


  def delete_where(self, table: str, where: str, params: tuple, cursor: Cursor|None=None, cls: type|None=None) -> None:
    query = (
      f"DELETE FROM {table} WHERE {where}",
      params,
    )
    return self._delete(table, *query, cursor, cls)
    # if cursor is None:
    #   cursor = self._db
    # cursor.execute(*query)


  def new(self,
      cls: type,
      **properties) -> "Versioned":
    if not issubclass(cls, Versioned):
      raise TypeError(cls)
    created = cls.new(db=self, **properties)
    log.debug("[DB] created {}: {}", cls.__qualname__, (created, created.saved))
    chown = None
    if isinstance(created, OwnableDatabaseObject):
      owner = properties.get("owner")
      if owner is not None:
        chown = {owner: [created]}
    log.debug("[DB] new {}: {}", cls.__qualname__, (created, created.saved))
    self.save(created, chown=chown)
    return created


  def load(self,
      cls: type,
      id: int | None = None,
      where: str | None = None,
      params: tuple | None = None,
      owner: DatabaseObjectOwner | None = None) -> Generator[Versioned, None, None]:
    if not issubclass(cls, Versioned):
      raise TypeError(cls)

    table = self.object_table(cls)
    cache = self._cache[table] = self._cache.get(table, {})


    if id is not None:
      log.debug("[DB] load {}: id={}", cls.__qualname__, id)
      cached = cache.get(id)
      if cached:
        yield cached
        return

      query = (
        f"SELECT * FROM {table} WHERE id = ?",
        (id,)
      )
    elif where is not None:
      log.debug("[DB] load {}: where {} values {}", cls.__qualname__, where, params)
      query = (
        f"SELECT * FROM {table} WHERE {where}",
        params
      )
    elif owner is not None:
      log.debug("[DB] load {}: owner {}", cls.__qualname__, owner)
      query = (
        f"SELECT target from {table}_credentials WHERE user = ?",
        (owner.id,),
      )

    cur = self._db.execute(*query)
    for row in cur:
      if issubclass(cls, Versioned):
        if owner is not None:
          loaded = next(self.load(cls, id=row.target))
          yield loaded
          continue

        serialized = row._asdict()
        cached = cache.get(serialized["id"])
        if cached:
          log.debug("[DB] cache hit {}: {}", cached.__class__.__qualname__, cached)
          yield cached
          continue
      
        loaded = cls.load(self, serialized)
        loaded.loaded = True
        loaded.saved = True
        log.activity("[DB] loaded {}: {}", loaded.__class__.__qualname__, loaded)
        yield loaded
      else:
        raise NotImplementedError()


  def delete(self, obj: DatabaseObject) -> None:
    def _query_targets():
      remaining = [obj]
      processed = set()
      while len(remaining) > 0:
        tgt = remaining.pop(0)
        if isinstance(tgt, Versioned):
          if tgt in processed:
            yield tgt
            continue
          remaining.extend([*tgt.nested, tgt])
        else:
          yield tgt
        processed.add(tgt)
    cursor = self._db.cursor()
    targets = list(_query_targets())
    current_owners = {
      tgt: self.owner(tgt)
      for tgt in targets
        if isinstance(tgt, OwnableDatabaseObject) and tgt.id
    }
    with self._db:
      for tgt, owner in current_owners.items():
        if owner is None:
          continue
        self._set_ownership(owner, [tgt], owned=False)
      for tgt in _query_targets():
        table = self.object_table(obj)
        # cursor.execute(f"DELETE FROM {table} WHERE id = ?", [tgt.id])
        self._delete(table, f"DELETE FROM {table} WHERE id = ?", [tgt.id], cursor, tgt.__class__)
        log.info("[DB] deleted {}: {}", tgt.__class__.__qualname__, tgt)
        self._cache.pop(tgt.id, None)


  def deserialize(self, cls: type, serialized: dict) -> object:
    loaded = None
    table = self.object_table(cls, required=False)
    cache = None
    if table is not None:
      cache = self._cache[table] = self._cache.get(table, {})

    if "id" in serialized and cache is not None:
      loaded = cache.get(serialized["id"])

    if loaded is None:
      if issubclass(cls, Versioned):
        # print("DESER VERSIONED", cls)
        loaded = cls(db=self, **serialized)
      elif hasattr(cls, "deserialize"):
        # print("DESER DESERIALIZE", cls)
        loaded = cls.deserialize(serialized)
      else:
        # print("DESER NEW", cls)
        loaded = cls(**serialized)
    # else:
    #   print("ALREADY CACHED:", loaded)
    # log.debug("[DB] deser_loaded {}: {}", cls.__qualname__, (loaded, loaded.saved))

    loaded_id = getattr(loaded, "id", None)    
    if cls.DB_CACHED and loaded_id and cache is not None and loaded.id not in cache:
      cache[loaded_id] = loaded
      log.debug("[DB] cached {}: {}", loaded.__class__.__qualname__, loaded)

    log.debug("[DB] deserialized {}: {}", loaded.__class__.__qualname__, loaded)
    return loaded


  def owned(self, user: DatabaseObjectOwner) -> Generator[OwnableDatabaseObject, None, None]:
    for owned_cls in user.DB_OWNED:
      for owned in self.db.load(owned_cls, owner=user):
        yield owned


  def owner(self, target: OwnableDatabaseObject|type, target_id: int|None=None) -> DatabaseObjectOwner:
    assert(target.id is not None)
    assert(isinstance(target, OwnableDatabaseObject) or issubclass(target, OwnableDatabaseObject))
    
    if target_id is None:
      if not isinstance(target, type):
        target_id = target.id
      else:
        raise NotImplementedError()

    for owner_cls in target.owner_types():
      table = self.object_credentials_table(target, owner_cls=owner_cls)
      if target.DB_OWNER_TABLE_COLUMN:
        result_attr = target.DB_OWNER_TABLE_COLUMN
        where = "id = ?"
        params = (target_id,)
      else:
        result_attr = "owner"
        where = "target = ? AND owned = ?"
        params = (target_id, True)
      result = self._db.execute(
        f"SELECT {result_attr} FROM {table} WHERE {where}", params).fetchone()
      if result:
        owner_id = getattr(result, result_attr)
        owner = next(self.load(owner_cls, id=owner_id))
        log.debug(f"[DB] owner {owner}: {target}")
        return owner

    log.debug(f"[DB] no owner: {target}")
    return None


  def set_ownership(self,
      owner: DatabaseObjectOwner,
      targets: Iterable[OwnableDatabaseObject],
      owned: bool=True) -> dict[DatabaseObjectOwner, bool]:
    if getattr(owner, "excluded", False) and owned:
      raise ValueError("cannot transfer ownership to excluded owner")

    with self._db:
      current_owners = {
        tgt: self.owner(tgt)
          for tgt in targets
      }
      return self._set_ownership(owner, targets, owned=owned, current_owners=current_owners)


  def _set_ownership(self,
      owner: DatabaseObjectOwner,
      targets: Iterable[OwnableDatabaseObject],
      owned: bool=True,
      current_owners: dict | None=None,
      cursor: sqlite3.Cursor | None = None) -> dict[DatabaseObjectOwner, bool]:
    if cursor is None:
      cursor = self._db
    current_owners = dict(current_owners or {})
    result = {}
    for target in targets:
      result[target] = False
      current_owner = current_owners.get(target)
      if ((owned and current_owner == owner)
          or (not owned and current_owner != owner)):
        # Ownership unchanged
        continue
      table = self.object_credentials_table(target, owner_cls=owner.__class__)
      if target.DB_OWNER_TABLE_COLUMN:
        cursor.execute(
          f"UPDATE {table} SET {target.DB_OWNER_TABLE_COLUMN} = ? WHERE id = ?",
          (owner.id, target.id))
        continue

      if current_owner:
        # cursor.execute(
        #   f"DELETE FROM {table} WHERE owner = ? AND target = ?",
        #   (current_owner.id, target.id))
        self._delete(table,
          f"DELETE FROM {table} WHERE owner = ? AND target = ?",
          (current_owner.id, target.id),
          cursor)
      if owned:
        cursor.execute(
          f"INSERT INTO {table} (owner, target, owned) VALUES (?, ?, ?)",
          (owner.id, target.id, True))

      if owned:
        log.activity(f"[DB] owner {target}: {current_owner} -> {owner}")
      else:
        log.activity(f"[DB] owner {target}: {owner} -> None")
      
      result[target] = True

    return result
  

