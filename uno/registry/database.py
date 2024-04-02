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
from typing import Generator, Iterable, Mapping, Callable
from pathlib import Path
import sqlite3
import yaml
import json
from importlib.resources import files, as_file
from functools import cached_property, wraps
import tempfile

from collections import namedtuple

from .versioned import Versioned

from ..data import database as db_data
from ..core.time import Timestamp
from ..core.exec import exec_command
from ..core.log import Logger

from .database_object import (
  DatabaseObject,
  OwnableDatabaseObject,
  DatabaseObjectOwner,
  DatabaseSchema,
  inject_cursor,
  inject_transaction,
  TransactionHandler)

def namedtuple_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    cls = namedtuple("Row", fields)
    return cls._make(row)


# def adapt_timestamp(ts: Timestamp) -> str:
#   return ts.format()

# def convert_timestamp(val: bytes) -> Timestamp:
#   return Timestamp.parse(val.decode())



def _get_sqlite3_thread_safety():
    # Mape value from SQLite's THREADSAFE to Python's DBAPI 2.0
    # threadsafety attribute.
    sqlite_threadsafe2python_dbapi = {0: 0, 2: 1, 1: 3}
    conn = sqlite3.connect(":memory:")
    threadsafety = conn.execute(
        """
select * from pragma_compile_options
where compile_options like 'THREADSAFE=%'
"""
    ).fetchone()[0]
    conn.close()

    threadsafety_value = int(threadsafety.split("=")[1])

    return sqlite_threadsafe2python_dbapi[threadsafety_value]


class Database:
  Cursor = sqlite3.Cursor

  DB_NAME = "uno.db"

  DB_TYPES = (bool, int, float, str, None.__class__)

  SCHEMA = DatabaseSchema

  THREAD_SAFE = _get_sqlite3_thread_safety()

  def __init__(self,
      root: Path | None = None,
      create: bool=False) -> None:
    assert(self.THREAD_SAFE)
    if root is None:
      self.tmp_root = tempfile.TemporaryDirectory()
      root = Path(self.tmp_root.name)
      create  = True
    self.root = root.resolve()
    self.log = Logger.sublogger(f"db<{Logger.format_dir(self.root)}>")
    self._cursor = None
    self._cache = {}
    self.db_file = self.root / self.DB_NAME
    if not self.db_file.exists():
      if not create:
        raise ValueError("not a uno directory", self.root)
      self.db_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      self.db_file.touch(mode=0o600)
    elif create:
      raise ValueError("directory already initialized", self.root)
    self._db = sqlite3.connect(
      self.db_file,
      isolation_level="DEFERRED",
      detect_types=sqlite3.PARSE_DECLTYPES,
      check_same_thread=False)
    self._db.row_factory = namedtuple_factory
    def _tracer(query) -> None:
      self.log.tracedbg("exec SQL:\n{}", query)
    self._db.set_trace_callback(_tracer)
    if create:
      self.initialize()
    # sqlite3.register_adapter(Timestamp, adapt_timestamp)
    # sqlite3.register_converter("timestamp", convert_timestamp)
    # for t in [dict, list, set]:
    #   sqlite3.register_adapter(t, adapt_yaml)
    #   sqlite3.register_converter(t.__name__.lower(), convert_yaml)


  def __str__(self) -> str:
    return f"{self.__class__.__qualname__}({self.log.format_dir(self.root)})"


  def next_id(self, target: DatabaseObject|type[DatabaseObject]) -> int:
    table = self.SCHEMA.lookup_id_table_by_object(target)
    next_id = self._db.execute(
      f"SELECT next FROM next_id WHERE target = ?",
      (table,)).fetchone().next
    next_id += 1
    self._db.execute(
      f"UPDATE next_id SET next = ? WHERE target = ?",
      (next_id, table))
    return next_id


  def initialize(self) -> None:
    for script in [
      "initialize_registry.sql",
      "initialize_agent.sql"]:
      with as_file(files(db_data).joinpath(script)) as sql:
        self._db.executescript(sql.read_text())
    self.log.activity("initialized: {}", self.root)


  def close(self) -> None:
    self._db.close()


  @inject_transaction
  def save(self,
      obj: DatabaseObject,
      chown: Mapping[DatabaseObjectOwner, list[OwnableDatabaseObject]]|None=None,
      public: bool=False,
      import_record: bool=False,
      dirty: bool=True,
      force_insert: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None = None) -> list[DatabaseObject]:
    return self._save_all([obj],
      chown=chown,
      public=public,
      import_record=import_record,
      dirty=dirty,
      force_insert=force_insert,
      cursor=cursor,
      do_in_transaction=do_in_transaction)


  @inject_transaction
  def save_all(self,
      targets: Iterable[DatabaseObject],
      chown: Mapping[DatabaseObjectOwner, list[OwnableDatabaseObject]]|None=None,
      public: bool=False,
      import_record: bool=False,
      dirty: bool=True,
      force_insert: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None = None) -> list[DatabaseObject]:
    return self._save_all(targets,
      chown=chown,
      public=public,
      import_record=import_record,
      dirty=dirty,
      force_insert=force_insert,
      cursor=cursor,
      do_in_transaction=do_in_transaction)


  def _save_all(self,
      targets: Iterable[DatabaseObject],
      chown: Mapping[DatabaseObjectOwner, list[OwnableDatabaseObject]]|None=None,
      public: bool=False,
      import_record: bool=False,
      dirty: bool=True,
      force_insert: bool=False,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None = None) -> list[DatabaseObject]:

    def owner_str(tgt):
      if isinstance(tgt, OwnableDatabaseObject):
        return f" (owner: {tgt.owner})"
      return ""

    def iter_query_targets() -> Generator[DatabaseObject, None, None]:
      for tgt in sorted(targets, key=lambda v: v.__class__.__qualname__):
        changed = [t for t, _ in tgt.collect_changes()]
        nested = list(tgt.collect_nested())
        collected = changed if (dirty and not import_record) else nested
        for tgt in collected:
          tgt.validate()
          if isinstance(tgt, OwnableDatabaseObject) and tgt.id:
            owner = self.owner(tgt, cursor=cursor)
          else:
            owner = None
          yield tgt, owner

    def do_save():
      saved = []
      query_targets = dict(iter_query_targets())
      self.log.debug("save targets: {}", query_targets)
      for tgt, current_owner in query_targets.items():
        table = self.SCHEMA.lookup_table_by_object(tgt, required=False)
        create = table and (not tgt.loaded or force_insert)
        logger = self.log.trace if create else self.log.tracedbg
        logger_result = self.log.debug if create else self.log.trace
        if table:
          logger("{} {}: {}{}",
            "inserting new" if create else "saving",
            tgt.__class__.__qualname__,
            tgt,
            owner_str(tgt))
        else:
          logger("saving {}: {}", tgt.__class__.__qualname__, tgt)

        if tgt.disposed:
          self.delete(tgt, cursor=cursor, do_in_transaction=lambda action: action())
        else:
          tgt.save(
            cursor=cursor,
            create=create,
            import_record=import_record,
            public=public)
          tgt.clear_changed()
          tgt.saved = True
          tgt.loaded = table is not None

          if table:
            logger_result("{} {}: {}{}",
              "inserted" if create else "updated",
              tgt.__class__.__qualname__,
              tgt,
              owner_str(tgt))
          else:
            logger_result("saved {}: {}", tgt.__class__.__qualname__, tgt)
        saved.append(tgt)

      for owner, targets in (chown or {}).items():
        self._set_ownership(owner, targets, current_owners=query_targets, cursor=cursor)

      return saved

    return do_in_transaction(do_save)


  @inject_cursor
  def create_or_update(self,
      obj: DatabaseObject,
      fields: dict[str, object],
      # obj_id: int | None = None,
      table: str | None = None,
      cursor: "Database.Cursor | None" = None,
      **db_args):
    if table is None:
      table = self.SCHEMA.lookup_table_by_object(obj)
    # if obj_id is None:
    #   if obj.id is None:
    #     obj.id = self.next_id(obj)
    #   obj_id = obj.id

    if obj.id is None:
      obj.id = self.next_id(obj)


    if db_args["import_record"]:
      if obj.DB_TABLE_KEYS:
        # Check if records for the specified keys exist, and if so, delete them
        for key_fields in obj.DB_TABLE_KEYS:
          key_fields = sorted(key_fields)
          key_params = [getattr(obj, f) for f in key_fields]
          key_where = ' AND '.join(f + ' = ?' for f in key_fields)
          self.delete_where(table, where=key_where, params=key_params, cursor=cursor)

        create = True
      else:
        row = cursor.execute(f"SELECT id FROM {table} WHERE id = ?", (obj.id,)).fetchone()
        create = row is None
    else:
      create = db_args["create"]

    sorted_keys = sorted(f if f != obj.OMITTED else None for f in fields if f != "id")
    sorted_values = [fields[k] for k in sorted_keys]

    if create:
      values = ', '.join('?' for _ in range(len(sorted_keys)+1))
      keys = ', '.join(("id", *sorted_keys))
      query = (
        f"INSERT INTO {table} ({keys}) VALUES ({values})",
        (obj.id, *sorted_values),
      )
    else:
      fields = ", ".join(f"{f} = ?" for f in sorted_keys)
      query = (
        f"UPDATE {table} SET {fields} WHERE id = ?",
        (*sorted_values, obj.id),
      )
    cursor.execute(*query)
    if not db_args["import_record"]:
      obj.reset_cached_properties()


  @inject_cursor
  def update_where(self,
      table: str,
      where: str,
      fields: dict,
      params: tuple | None=None,
      cursor: "Database.Cursor | None" = None) -> None:
    s_fields = sorted(fields.items(), key=lambda i: i[0])
    query = (
      f"UPDATE {table} SET {', '.join(i[0] + ' = ?' for i in s_fields)} WHERE {where}",
      (*(i[1] for i in s_fields), *params),
    )
    cursor.execute(*query)


  @inject_cursor
  def _delete(self,
      table: str,
      query: str,
      params: tuple | None=None,
      cls: type|None=None,
      cursor: "Database.Cursor | None" = None) -> None:
    if cls is not None:
      assert(issubclass(cls, Versioned))
      # eq_props = sorted(cls.SCHEMA.eq_properties)
      # query = f"{query} RETURNING {', '.join(eq_props)}"
      query = f"{query} RETURNING id"
    self.log.trace("delete {} query: {} values {}", "rows" if cls is None else cls.__qualname__, query, params)
    result = cursor.execute(query, params or [])
    if cls is not None:
      for row in result:
        # self.log.debug(f"deleted record: {'{}'}, {', '.join('{} = {}' for _ in eq_props)}",
        #   table,
        #   *(f for p in eq_props for f in (p, getattr(row, p))))
        self.log.debug("deleted record: {}({})", table, row.id)


  @inject_cursor
  def delete_where(self,
      table: str,
      where: str,
      params: tuple,
      cls: type|None=None,
      cursor: "Database.Cursor | None" = None) -> None:
    query = (
      f"DELETE FROM {table} WHERE {where}",
      params,
    )
    return self._delete(table, *query, cls, cursor=cursor)
    # if cursor is None:
    #   cursor = self._db
    # cursor.execute(*query)



  @inject_transaction
  def new(self,
      cls: type[DatabaseObject],
      properties: dict|None=None,
      owner: DatabaseObjectOwner|None=None,
      save: bool=True,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> DatabaseObject:
    table = self.SCHEMA.lookup_table_by_object(cls, required=False)
    if not table:
      save = False
    def _new():
      assert(issubclass(cls, DatabaseObject))
      new_properties = dict(properties or {})
      new_properties["db"] = self
      new_properties["owner"] = owner
      created = cls.new(**new_properties)
      self.log.debug("new {}: {}", cls.__qualname__, created)
      chown = None
      if save and owner is not None and isinstance(created, OwnableDatabaseObject):
        chown = {owner: [created]}
      if save:
        self.save(created, chown=chown, cursor=cursor)
      return created
    return do_in_transaction(_new)


  @inject_cursor
  def load(self,
      cls: type | None = None,
      id: int | None = None,
      table: str | None = None,
      where: str | None = None,
      params: tuple | None = None,
      owner: DatabaseObjectOwner | None = None,
      load_args: dict[str, object] | None = None,
      use_cache: bool = True,
      cursor: "Database.Cursor|None" = None) -> Generator[Versioned, None, None]:

    if cls is None:
      if table is None:
        raise ValueError("one of cls or table must be specified")
      cls = self.SCHEMA.lookup_object_by_table(table)
    else:
      if not issubclass(cls, Versioned):
        raise TypeError(cls)
      table = self.SCHEMA.lookup_table_by_object(cls)

    cache = self._cache[table] = self._cache.get(table, {})
    
    def _check_cache(obj_id) -> Versioned|None:
      if not use_cache:
        return None
      cached = cache.get(obj_id)
      if cached:
        self.log.tracedbg("cache hit {}: {}", cached.__class__.__qualname__, cached)
      return cached


    def _load_targets() -> Generator[tuple, None, None]:
      # Load a specific object using its explicit id
      if id is not None:
        cached = _check_cache(id)
        if cached:
          yield cached
          return
        query = (
          f"SELECT * FROM {table} WHERE id = ?",
          (id,)
        )
        self.log.tracedbg("load {} by id: {}", cls.__qualname__, id)
        for row in cursor.execute(*query):
          yield row

      # Load objects by making a custom query on their db table
      elif where is not None:
        query = (
          f"SELECT * FROM {table} WHERE {where}",
          params
        )
        self.log.tracedbg("load {} by query: {} PARAMS {}", cls.__qualname__, where, params)
        for row in cursor.execute(*query):
          yield row

      # Load objects owned by the specified owner. If a where clause is specified,
      # Return only those objects matching the clause.
      elif owner is not None:
        self.log.tracedbg("load {} by owner: {}", cls.__qualname__, owner)
        owner_table, owner_col, owned_col = self.SCHEMA.lookup_owner_table_by_object(cls, owner_cls=owner.__class__)
        if where is None:
          owned = cursor.execute(f"SELECT {owned_col} FROM {owner_table} WHERE {owner_col} = ?", (json.dumps(owner.object_id), )).fetchone()
          if not owned:
            return
          owned_id = getattr(owned, owned_col)
          row = cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (owned_id,)).fetchone()
          if not row:
            return
          yield row
        else:
          for owned in cursor.execute(f"SELECT id FROM {table} WHERE {where}", params):
            for is_owner in cursor.execute(f"SELECT * FROM {owner_table} WHERE {owner_col} = ? AND {owned_col} = ?", (owner.id, owned.id, )):
              yield owned
      else:
        for row in cursor.execute(f"SELECT * FROM {table}"):
          yield row


    load_targets = list(_load_targets())
    if not load_targets:
      self.log.tracedbg("no {} matched by query", cls.__qualname__)
      return

    self.log.tracedbg("load targets: {}", load_targets)
    
    for row in load_targets:
      if isinstance(row, DatabaseObject):
        yield row
        continue
      
      serialized = row._asdict()
      serialized["owner"] = owner
      if load_args:
        serialized.update(load_args)

      loaded, cached = cls.load(self, serialized)
      if not cached:
        loaded.saved = True
        loaded.loaded = True

      yield loaded



  @inject_cursor
  def load_object_id(self,
      object_id: tuple[str, object],
      load_args: dict|None=None,
      cursor: "Database.Cursor | None" = None) -> "Versioned":
    table, obj_id = object_id
    obj_cls = self.SCHEMA.lookup_object_by_table(table)
    return next(self.load(obj_cls, id=obj_id, table=table, load_args=load_args, cursor=cursor))


  @inject_transaction
  def delete(self,
      obj: DatabaseObject,
      cursor: "Database.Cursor|None"=None,
      do_in_transaction: TransactionHandler | None=None) -> None:
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
    def _delete():
      targets = list(_query_targets())
      current_owners = {
        tgt: tgt.owner
        for tgt in targets
          if isinstance(tgt, OwnableDatabaseObject)
      }
      for tgt, owner in current_owners.items():
        if owner is None:
          continue
        self._set_ownership(owner, [tgt], owned=False)
      for tgt in _query_targets():
        table = self.SCHEMA.lookup_table_by_object(obj)
        self._cache.pop(tgt.id, None)
        self._delete(table, f"DELETE FROM {table} WHERE id = ?", [tgt.id], tgt.__class__,
          cursor=cursor)
        self.log.activity("deleted {}: {}", tgt.__class__.__qualname__, tgt)
    do_in_transaction(_delete)


  def deserialize(self, cls: type, serialized: dict, use_cache: bool=True) -> tuple[object, bool]:
    loaded = None
    table = self.SCHEMA.lookup_table_by_object(cls, required=False)
    cache = None
    cached = None
    if table is not None:
      cache = self._cache[table] = self._cache.get(table, {})

    if "id" in serialized and cache is not None and use_cache:
      cached = cache.get(serialized["id"])
      loaded = cached

    if loaded is None:
      if issubclass(cls, DatabaseObject):
        loaded = cls(db=self, **serialized)
        logger = (
          self.log.activity if loaded.DB_TABLE and loaded.DB_CACHED else 
          self.log.debug if loaded.DB_TABLE else
          self.log.trace
        )
      elif hasattr(cls, "deserialize"):
        loaded = cls.deserialize(serialized)
        logger = self.log.tracedbg
      else:
        raise NotImplementedError("cannot deserialize type", cls)
      logger("instance {}: {}", cls.__qualname__, loaded)
    else:
      self.log.tracedbg("cache hit {}: {}", loaded.__class__.__qualname__, loaded)

    loaded_id = getattr(loaded, "id", None)
    if (issubclass(cls, DatabaseObject)
        and cls.DB_CACHED
        and loaded_id
        and cache is not None
        and cached is None):
      cache[loaded_id] = loaded
      self.log.tracedbg("cached {}: {}", loaded.__class__.__qualname__, loaded)

    return loaded, cached is not None


  @inject_cursor
  def owner(self,
      target: OwnableDatabaseObject|type[OwnableDatabaseObject],
      target_id: int|None=None,
      cursor: "Database.Cursor | None" = None) -> DatabaseObjectOwner|None:
    # assert(target.id is not None)
    assert(isinstance(target, OwnableDatabaseObject) or issubclass(target, OwnableDatabaseObject))
    
    if target_id is None:
      if not isinstance(target, OwnableDatabaseObject):
        raise ValueError("a target id is required when searching owner by type", target)
      target_id = target.id
      search_target = (target,)
    else:
      if not isinstance(target, type):
        raise ValueError("target id can only be specified when searching by type")
      search_target = (target, target_id)

    result = None

    def _parse_owner_id(owner_id: str, attr: str) -> tuple[type[DatabaseObjectOwner], str, object]:
      owner_id = Versioned.yaml_load(owner_id)
      cls = self.SCHEMA.lookup_object_by_table(owner_id[0])
      return cls, *owner_id

    searched_tables = set()
    owner_types = list(target.owner_types())
    for owner_cls in owner_types:
      owner_table, owner_col, owned_col = self.SCHEMA.lookup_owner_table_by_object(target, owner_cls=owner_cls)
      if owner_table in searched_tables:
        continue
      searched_tables.add(owner_table)
      result = cursor.execute(f"SELECT {owner_col} FROM {owner_table} WHERE {owned_col} = ?", (target_id,)).fetchone()
      if result:
        owner_id = getattr(result, owner_col)
        if owner_id is None:
          result = None
          continue
        l_owner_cls, table, owner_id = _parse_owner_id(owner_id, owned_col)
        # It's possible that l_owner_cls != owner_cls
        # because multiple owner types can be encoded in the same table
        # In this case, let's makes sure the type is an owner
        assert(owner_cls == l_owner_cls or l_owner_cls in owner_types)
        owner_cls = l_owner_cls
        break

    if result:
      owner = next(self.load(owner_cls, table=table, id=owner_id))
      self.log.trace("loaded owner of {}: {}", search_target, owner)
      return owner

    self.log.trace("no owner: {}", search_target)
    return None


  @inject_transaction
  def set_ownership(self,
      owner: DatabaseObjectOwner,
      targets: Iterable[OwnableDatabaseObject],
      owned: bool=True,
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None = None) -> dict[DatabaseObjectOwner, bool]:
    if getattr(owner, "excluded", False) and owned:
      raise ValueError("cannot transfer ownership to excluded owner")

    def _set_owenership():
      current_owners = {
        tgt: self.owner(tgt, cursor=cursor)
          for tgt in targets
      }
      return self._set_ownership(owner, targets, owned=owned, current_owners=current_owners, cursor=cursor)

    return do_in_transaction(_set_owenership)


  @inject_cursor
  def _set_ownership(self,
      owner: DatabaseObjectOwner,
      targets: Iterable[OwnableDatabaseObject],
      owned: bool=True,
      current_owners: dict | None=None,
      cursor: "Database.Cursor | None" = None) -> dict[DatabaseObjectOwner, bool]:
    if owner.object_id is None:
      raise ValueError("invalid owner", owner)
    current_owners = dict(current_owners or {})
    result = {}
    for target in targets:
      result[target] = False
      current_owner = current_owners.get(target)
      if ((owned and current_owner == owner)
          or (not owned and current_owner != owner)):
        # Ownership unchanged
        self.log.debug("ownership unchanged for {}: {}", target, current_owner)
        continue
      owner_table, owner_col, owned_col = self.SCHEMA.lookup_owner_table_by_object(target, owner_cls=owner.__class__)
      if target.DB_OWNER_TABLE_COLUMN is not None:
        cursor.execute(
          f"UPDATE {owner_table} SET {owner_col} = ? WHERE {owned_col} = ?",
          (Versioned.json_dump(owner.object_id) if owned else None, target.id))
      else:
        if current_owner is None and owned:
          # Insert new row in dedicated owner table
          # TODO(asorbini) query self.SCHEMA for the list of columns
          cursor.execute(
            f"INSERT INTO {owner_table} SET (owner, target, owned) VALUES (?, ?, ?)",
            (Versioned.json_dump(owner.object_id), target.id, True))
        elif current_owner is not None and owned:
          cursor.execute(
            f"UPDATE {owner_table} SET {owner_col} = ? WHERE {owned_col} = ?",
            (Versioned.json_dump(owner.object_id) if owned else None, target.id))
        elif not owned:
          self._delete(owner_table,
            f"DELETE FROM {owner_table} WHERE {owner_col} = ? AND {owned_col} = ?",
            (Versioned.json_dump(owner.object_id), target.id),
            cursor=cursor)


      target.reset_cached_properties()
      target.__dict__.pop("owner", None)
      target.__dict__.pop("owner_id", None)

      if owned:
        self.log.debug("owner {}: {} -> {}", target, current_owner, owner)
      else:
        self.log.debug("owner {}: {} -> none", target, owner)
      
      result[target] = True

    return result


  @inject_transaction
  def export_tables(self,
      target: "Database",
      classes: Iterable[type[DatabaseObject]],
      cursor: "Database.Cursor | None" = None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    def _export():
      already_exported = set()
      
      exportable_types = list(self.SCHEMA.exportables())
      for exported_cls in classes:
        assert(issubclass(exported_cls, DatabaseObject))
        assert(exported_cls in exportable_types)

        table = self.SCHEMA.lookup_table_by_object(exported_cls)
        owner_tables = (
          list(t for t, _, _, in self.SCHEMA.lookup_owner_tables_by_object(exported_cls))
          if issubclass(exported_cls, OwnableDatabaseObject) else []
        )

        # Read table SQL definition
        # l_cursor = self._db.cursor()
        t_cursor = target._db.cursor()
        # table_sql_create = l_cursor.execute(
        #   f"SELECT sql FROM sqlite_master WHERE type = ? and name = ?",
        #   ("table", table)).fetchone().sql

        def _export_table(table) -> None:
          if table in already_exported:
            return
          table_count = 0
          self.log.debug("exporting table {} to {}", table, target)
          query, params = exported_cls.importable_query(table)
          assert(query is not None)
          # print(f"QUERY = '{query}'; PARAMS = '{params}';")
          for row in cursor.execute(query, params or tuple()):
            self.log.debug("export record {}: {}", table, row)
            t_cursor.execute(
              f"INSERT INTO {table} ({', '.join(f for f in row._fields)}) VALUES ({', '.join('?' for _ in row._fields)})",
              row)
            table_count += 1
          already_exported.add(table)
          self.log.activity("exported {} records for table {} to {}", table_count, table, target)

        with target._db:
          _export_table(table)

          for owner_table in owner_tables:
            _export_table(owner_table)

    return do_in_transaction(_export)

  def export_objects(self, target: "Database", objects: Iterable[Versioned], public: bool=False) -> None:
    target.save_all(objects, import_record=True, public=public, force_insert=True)


  @inject_transaction
  def import_other(self,
      target: "Database",
      cursor: "Database.Cursor|None"=None,
      do_in_transaction: TransactionHandler | None=None) -> None:
    # Make a backup of the current database
    db_file_bkp = f"{self.db_file}.bkp"
    exec_command(["cp", "-av", self.db_file, db_file_bkp])

    def _import() -> None:
      self.log.activity("importing database: {}", target)
      for cls in self.SCHEMA.importables():
        self.log.activity("importing {} objects", cls.__qualname__)
        if cls.DB_IMPORT_DROPS_EXISTING:
          self.log.debug("dropping all existing {} objects", cls.__qualname__)
          table = self.SCHEMA.lookup_table_by_object(cls)
          self.delete_where(table, where="id > ?", params=(0,), cls=cls)
        count = 0
        # query, params = cls.importable_query()
        for obj in target.load(cls):
          if isinstance(obj, OwnableDatabaseObject) and obj.owner:
            chown = {obj.owner: [obj]}
          else:
            chown = None
          self.log.activity("importing {}: {}", cls.__qualname__, obj)
          self.save(obj, chown=chown, import_record=True, cursor=cursor)
          count += 1
        self.log.info("imported {} {} objects", count, cls.__qualname__)
      self.log.info("imported database: {}", target)

    try:
      return do_in_transaction(_import)
    except Exception as e:
      # Restore backup
      self.log.debug("restoring database on error: {}", e)
      result = exec_command(["cp", "-av", db_file_bkp, self.db_file], noexcept=True)
      if result.returncode != 0:
        self.log.error("failed to restore database backup: {}", db_file_bkp)
      self.log.warning("database returned to previous state on error: {}", e)
      raise


  # def import_object(self, obj: DatabaseObject) -> None:
  #   self.log.activity("importing {}: {}", obj.__class__.__qualname__, obj)
  #   table = self.SCHEMA.lookup_table_by_object(obj)
  #   query = (
  #     f"UPSERT "
  #   )