from pathlib import Path
from functools import cached_property
from enum import Enum
from typing import Generator, Callable, TYPE_CHECKING
from functools import wraps
from collections.abc import Iterable

if TYPE_CHECKING:
  from .database import Database

class DatabaseSchema:
  _Types: "set[type[DatabaseObject]]" = set()
  _Objects: "set[type[DatabaseObject]]" = set()
  _Ownables: "set[type[OwnableDatabaseObject]]" = set()
  _Owners: "set[type[DatabaseObjectOwner]]" = set()
  _ObjectsByTable: "dict[str, type[DatabaseObject]]" = dict()


  @classmethod
  def register_type(cls, db_type: type["DatabaseObject"]) -> None:
    cls._Types.add(db_type)
    if db_type.DB_TABLE is not None:
      cls._Objects.add(db_type)
      assert(isinstance(db_type.DB_TABLE, str))
      existing_cls = cls._ObjectsByTable.get(db_type.DB_TABLE)
      if existing_cls is not None and not issubclass(db_type, existing_cls):
        raise ValueError("DB_TABLE already in use", db_type.DB_TABLE, existing_cls)
      elif existing_cls is None:
        cls._ObjectsByTable[db_type.DB_TABLE] = db_type


  @classmethod
  def register_ownable(cls, db_type: type["OwnableDatabaseObject"]) -> None:
      if db_type.DB_OWNER is not None:
        cls._Ownables.add(db_type)
        for owner in db_type.owner_types():
          assert(issubclass(owner, DatabaseObjectOwner) or
            (isinstance(owner, Iterable)
            and next((o for o in owner
              if not issubclass(owner, DatabaseObjectOwner)), None) is None))
          owner.DB_OWNED = getattr(owner, "DB_OWNED") or set()
          owner.DB_OWNED.add(db_type)


  @classmethod
  def register_owner(cls, db_type: type["DatabaseObjectOwner"]) -> None:
    cls._Owners.add(db_type)


  @classmethod
  def types(cls) -> "set[type[DatabaseObject]]":
    return cls._Types


  @classmethod
  def objects(cls) -> "set[type[DatabaseObject]]":
    return cls._Objects


  @classmethod
  def exportables(cls) -> "Generator[type[DatabaseObject], None, None]":
    for t in cls._Objects:
      if not t.DB_EXPORTABLE:
        continue
      yield t


  @classmethod
  def importables(cls) -> "Generator[type[DatabaseObject], None, None]":
    for t in cls._Objects:
      if not t.DB_IMPORTABLE:
        continue
      yield t



  @classmethod
  def ownables_types(cls) -> "set[type[OwnableDatabaseObject]]":
    return cls._Ownables


  @classmethod
  def ownables_objects(cls) -> "set[type[OwnableDatabaseObject]]":
    return cls._Objects & cls._Ownables


  @classmethod
  def lookup_owner_table_by_object(cls,
      target: "OwnableDatabaseObject|type[OwnableDatabaseObject]",
      required: bool=True,
      owner_cls: "type[DatabaseObjectOwner]|None"=None) -> tuple[str, str, str]|tuple[None, None, None]:
    if not isinstance(target, OwnableDatabaseObject) and not issubclass(target, OwnableDatabaseObject):
      if required:
        raise ValueError("not ownable", target)
      return None
    tgt_tables = dict(target.owner_tables())
    try:
      if owner_cls is not None:
          (table, owner_col, owned_col) = tgt_tables[owner_cls]
      else:
        owner_cls, (table, owner_col, owned_col) = next(iter(tgt_tables.items()))
      return (table, owner_col, owned_col)
    except (KeyError, StopIteration):
      if required:
        raise KeyError(target, owner_cls) from None
      return None, None, None


  @classmethod
  def lookup_owner_tables_by_object(cls,
      target: "OwnableDatabaseObject|type[OwnableDatabaseObject]") -> Generator[tuple[str, str, str], None, None]:
    for owner_cls in target.owner_types():
      yield cls.lookup_owner_table_by_object(target, owner_cls=owner_cls)



  @classmethod
  def lookup_table_by_object(cls, target: "DatabaseObject|type[DatabaseObject]", required: bool=True) -> str | None:
    if not isinstance(target, DatabaseObject) and not issubclass(target, DatabaseObject):
      if required:
        raise ValueError("not an object", target)
      return None
    try:
      table = target.DB_TABLE
    except AttributeError:
      table = None
    if table is None and required:
      raise KeyError(target)
    return table


  @classmethod
  def lookup_id_table_by_object(cls, target: "DatabaseObject|type[DatabaseObject]", required: bool=True) -> str | None:
    if target.DB_ID_POOL is not None:
      return target.DB_ID_POOL
    else:
      return cls.lookup_table_by_object(target)


  @classmethod
  def lookup_object_by_table(cls, table: str, required: bool=True) -> type["DatabaseObject"] | None:
    try:
      return cls._ObjectsByTable[table]
    except KeyError:
      if required:
        raise KeyError(table) from None


  @classmethod
  def iter_owner_types(cls, target: "OwnableDatabaseObject|type[OwnableDatabaseObject]") -> "Generator[type[DatabaseObjectOwner], None, None]":
    if not isinstance(target, OwnableDatabaseObject) and not issubclass(target, OwnableDatabaseObject):
      raise ValueError("not an ownable", target)
    if not isinstance(target.DB_OWNER, type) and callable(target.DB_OWNER):
      owner = target.DB_OWNER()
    else:
      owner = target.DB_OWNER
    if isinstance(owner, Iterable):
      for o in owner:
        yield o
    else:
      yield owner


  @classmethod
  def iter_owner_tables(cls, target: "OwnableDatabaseObject|type[OwnableDatabaseObject]") -> Generator[tuple[type["DatabaseObjectOwner"] , tuple[str, str, str]], None, None]:
    if target.DB_OWNER_TABLE is not None and isinstance(target.DB_OWNER_TABLE, str):
      # assert(len(owner_types) == 1)
      for owner_cls in target.owner_types():
        yield (owner_cls, (target.DB_OWNER_TABLE, "owner", "target"))
    elif target.DB_OWNER_TABLE is not None and isinstance(target.DB_OWNER_TABLE, dict):
      # assert(len(target.DB_OWNER_TABLE) == len(owner_types))
      for owner_cls in target.owner_types():
        yield (owner_cls, (target.DB_OWNER_TABLE[owner_cls], "owner", "target"))
    elif isinstance(target.DB_OWNER_TABLE_COLUMN, str):
      for owner in target.owner_types():
        yield (owner, (target.DB_TABLE, target.DB_OWNER_TABLE_COLUMN, "id"))


  @classmethod
  def iter_owned_types(cls, target: "DatabaseObjectOwner|type[DatabaseObjectOwner]") -> Generator[type["OwnableDatabaseObject"], None, None]:
    for owned in (target.DB_OWNED or []):
      yield owned


class _OmittedValue:
  def __str__(self) -> str:
    return "<omitted>"

import yaml
yaml.add_representer(_OmittedValue, lambda dumper, data: dumper.represent_none(None))


TransactionHandler = Callable[[Callable[[], None], None], None]

def _define_inject_cursor(wrapped, get_db: Callable[[object], "Database"]):
  @wraps(wrapped)
  def _inject_cursor(self, *a, cursor: "Database.Cursor|None"=None, **kw):
    drop_cursor = False
    db = get_db(self)
    if cursor is None:
      db.log.tracedbg("inject cursor in call to {}({}, {})",
        wrapped.__name__,
        ", ".join(map(str, a)),
        ", ".join(f"{k}={v}" for k, v in kw.items()))
      if db._cursor is None:
        db.log.tracedbg("cursor CREATE")
        db._cursor = db._db.cursor()
        drop_cursor = True
      cursor = db._cursor
    res = wrapped(self, *a, cursor=cursor, **kw)
    if drop_cursor:
      db.log.tracedbg("cursor DELETE")
      db._cursor = None
    return res
  return _inject_cursor


def inject_cursor(wrapped):
  return _define_inject_cursor(wrapped, get_db=lambda o: o)


def inject_db_cursor(wrapped):
  return _define_inject_cursor(wrapped, get_db=lambda o: o.db)


def _define_inject_transaction(wrapped, get_db: Callable[[object], "Database"], inject_cursor: Callable[[Callable], Callable]):
  @wraps(wrapped)
  def _inject_transaction(self, *a, cursor: "Database.Cursor|None"=None, **kw):
    db = get_db(self)
    if cursor is None:
      db.log.tracedbg("inject transaction in call to {}({}, {})",
        wrapped.__name__,
        ", ".join(map(str, a)),
        ", ".join(f"{k}={v}" for k, v in kw.items()))
      def do_in_transaction(action: Callable[[], None]):
        db.log.tracedbg("transaction BEGIN")
        with db._db:
          res = action()
        db.log.tracedbg("transaction END")
        return res
    else:
      def do_in_transaction(action: Callable[[], None]):
        return action()
    return inject_cursor(wrapped)(self, *a, cursor=cursor, do_in_transaction=do_in_transaction, **kw)
  return _inject_transaction


def inject_transaction(wrapped):
  return _define_inject_transaction(wrapped, get_db=lambda o: o, inject_cursor=inject_cursor)


def inject_db_transaction(wrapped):
  return _define_inject_transaction(wrapped, get_db=lambda o: o.db, inject_cursor=inject_db_cursor)


class DatabaseObject:
  OMITTED = _OmittedValue()
  DB_SCHEMA: DatabaseSchema = DatabaseSchema
  DB_TABLE: str = None
  DB_ID_POOL: str = None
  DB_TABLE_PROPERTIES: list[str] = []
  DB_TABLE_KEYS: list[str] = []
  DB_CACHED: bool = True
  DB_EXPORTABLE: bool = True
  DB_IMPORTABLE: bool = True
  DB_IMPORTABLE_WHERE: tuple[str, tuple] | None = None
  DB_IMPORT_DROPS_EXISTING: bool = False

  def __init__(self,
      db: "Database",
      id: object|None=None,
      parent: "DatabaseObject|None"=None,
      **properties) -> None:
    self._db = db
    assert(issubclass(self.db.SCHEMA, self.DB_SCHEMA))
    self._parent = parent
    self._id = id
    self._loaded = False
    self._saved = False
    self._disposed = False
    self._updated = set()
    super().__init__()
    assert(self.DB_TABLE is not None or self.parent is not None)


  def __init_subclass__(cls, *a, **kw) -> None:
    cls.DB_SCHEMA.register_type(cls)
    super().__init_subclass__(*a, **kw)


  @classmethod
  def importable_query(cls, table: str) -> tuple[str, tuple | None] | tuple[None, None]:
    if not cls.DB_IMPORTABLE:
      return (None, None)
    if cls.DB_IMPORTABLE_WHERE is not None:
      where, params = cls.DB_IMPORTABLE_WHERE
      query = f"SELECT * FROM {table} WHERE {where}"
    else:
      query = f"SELECT * FROM {table}"
      params = None
    return (query, params)


  @property
  def db(self) -> "Database":
    return self._db


  @property
  def id(self) -> object | None:
    return self._id


  @id.setter
  def id(self, val: object) -> None:
    if self._id is not None and self._id != val:
      raise ValueError("cannot change already set id", self)
    self._id = val


  @property
  def parent(self) -> "DatabaseObject|None":
    return self._parent


  @property
  def parent_id(self) -> tuple|None:
    if self.parent is None:
      return None
    if self.parent.object_id is None:
      return


  @cached_property
  def object_id(self) -> tuple[str, object] | None:
    if self.transient_object():
      return self.parent.object_id if self.parent else None
    if self.id is None:
      return None
    return (self.DB_TABLE, self.id)


  @cached_property
  def parent_str_id(self) -> str | object | None:
    if self.transient_object():
      return self.parent.parent_str_id if self.parent else None
    return str(self)


  @classmethod
  def object_table(cls) -> str | None:
    return cls.DB_SCHEMA.lookup_object_table(cls, required=False)


  @classmethod
  def transient_object(cls) -> bool:
    return cls.DB_TABLE is None


  def reset_cached_properties(self) -> None:
    self.__dict__.pop("object_id", None)
    self.__dict__.pop("parent_str_id", None)


  def save(self, cursor: "Database.Cursor|None"=None, **db_args) -> None:
    raise NotImplementedError()


  def validate(self) -> None:
    raise NotImplementedError()


  def clear_changed(self, properties: Iterable[str]|None=None) -> None:
    if properties is None:
      self.changed_properties.clear()
    else:
      for prop in properties:
        try:
          self.changed_properties.remove(prop)
        except KeyError:
          pass


  @property
  def nested(self) -> "Generator[DatabaseObject, None, None]":
    for i in []:
      yield i


  def collect_nested(self, predicate: Callable[["DatabaseObject"], bool]|None=None) -> Generator["DatabaseObject", None, None]:
    def _yield_nested_recur(cur: DatabaseObject) -> Generator["DatabaseObject", None, None]:
      nested = list(cur.nested)
      for o in nested:
        for n in _yield_nested_recur(o):
          yield n
      if predicate is None or predicate(cur):
        yield cur
    return _yield_nested_recur(self)


  def collect_changes(self, predicate: Callable[["DatabaseObject"], bool]|None=None) -> Generator[tuple["DatabaseObject", dict], None, None]:
    def _predicate(o: DatabaseObject) -> bool:
      if predicate is not None and not predicate(o):
        return False
      return o.dirty # and not o.SCHEMA.transient
    for o in self.collect_nested(_predicate):
      prev = o.changed_values
      yield (o, prev)


  @property
  def changed_values(self) -> dict:
    raise NotImplementedError()


  @property
  def loaded(self) -> bool:
    return self._loaded
  

  @loaded.setter
  def loaded(self, val: bool) -> None:
    self._loaded = val


  @property
  def saved(self) -> bool:
    nested_change = next(self.collect_nested(lambda o: o is not self and not o.saved), None)
    return self._saved and nested_change is None
  

  @saved.setter
  def saved(self, val: bool) -> None:
    self._saved = val
    # if not self._initialized:
    #   # Don't propagate changes unless we're initialized
    #   return
    # Propagate "not saved" to parent
    if not self._saved and self.parent is not None:
      self.parent.saved = False
    # Propagate "saved" to transient children
    elif self._saved:
      for n in self.nested:
        if not n.transient_object():
          continue
        n.saved = True


  @property
  def disposed(self) -> bool:
    return self._disposed
  

  @disposed.setter
  def disposed(self, val: bool) -> None:
    self._disposed = val


  @property
  def dirty(self) -> bool:
    # if self.DB_TABLE:
    #   dirty = not self.saved
    # else:
    #   dirty = len(self.changed_properties) > 0
    
    # if dirty:
    #   return dirty

    # return next(self.collect_nested(lambda o: o is not self and o.dirty), None) is None
    return not self.saved


  @property
  def changed_properties(self) -> set[str]:
    return self._updated


  @classmethod
  def load(cls, db: "Database", serialized: dict) -> tuple["DatabaseObject", bool]:
    return db.deserialize(cls, serialized)


  @classmethod
  def generate_new(cls, db: "Database", **properties) -> dict:
    return {}


  @classmethod
  def new(cls, db: "Database", **properties) -> "DatabaseObject":
    loaded, cached = db.deserialize(cls, {
      **properties,
      **cls.generate_new(db, **properties),
    }, use_cache=False)
    assert(not cached)
    return loaded



class OwnableDatabaseObject(DatabaseObject):
  DB_OWNER: type["DatabaseObjectOwner"] = None
  DB_OWNER_TABLE: str|dict[type["DatabaseObjectOwner"], str]|None = None
  DB_OWNER_TABLE_COLUMN: str|None = None

  SERIALIZED_PROPERTIES = ["owner_id"]
  # CACHED_PROPERTIES = [
  #   "owner",
  #   "owner_id",
  # ]
  # VOLATILE_PROPERTIES = ["owner"]


  def __init__(self,
      db: "Database",
      id: object|None=None,
      parent: "DatabaseObject|None"=None,
      owner: "DatabaseObjectOwner|None"=None,
      **properties) -> None:
    self._owner = owner
    super().__init__(db=db, id=id, parent=parent, **properties)


  def __init_subclass__(cls, *a, **kw) -> None:
    cls.DB_SCHEMA.register_ownable(cls)
    super().__init_subclass__(*a, **kw)


  @classmethod
  def owner_types(cls) -> "Generator[type[DatabaseObjectOwner], None, None]":
    return cls.DB_SCHEMA.iter_owner_types(cls)

  
  @cached_property
  @inject_db_cursor
  def owner(self, cursor: "Database.Cursor") -> "DatabaseObjectOwner | None":
    if self._owner is not None:
      return self._owner
    if self.id is None:
      return None
    return self.db.owner(self, cursor=cursor)


  @cached_property
  def owner_id(self) -> tuple[str, object] | tuple[None, None]:
    if self.owner is None:
      return (None, None)
    return (self.owner.DB_TABLE, self.owner.id)


  def serialize_owner_id(self, val: tuple, public: bool=False) -> list|None:
    if val[0] is None or val[1] is None:
      return None
    return list(val)


  def reset_cached_properties(self) -> None:
    super().reset_cached_properties()
    # self.__dict__.pop("owner", None)
    # self.__dict__.pop("owner_id", None)


  def set_ownership(self, owner: "DatabaseObjectOwner"):
    return self._set_ownership(owner)


  def reset_ownership(self) -> None:
    return self._set_ownership()


  def _set_ownership(self, owner: "DatabaseObjectOwner | None"=None):
    owned = owner is not None
    if owner is None:
      owner = self.owner
      if owner is None and not owned:
        # already no owner
        return
    changed = self.db.set_ownership(owner, targets=[self], owner=owned)
    if changed[self]:
      if hasattr(self, "updated_property"):
        self.updated_property("owner")
      if hasattr(owner, "updated_property"):
        owner.updated_property("owned")


  @classmethod
  def owner_tables(cls) -> Generator[tuple[type["DatabaseObjectOwner"], tuple[str, str, str]], None, None]:
    returned = 0
    for t in cls.DB_SCHEMA.iter_owner_tables(cls):
      returned += 1
      yield t
    if not returned:
      raise NotImplementedError("invalid owner table configuration", cls)



class DatabaseObjectOwner(DatabaseObject):
  DB_OWNED = None
  CACHED_PROPERTIES = ["owned"]


  def __init_subclass__(cls, *a, **kw) -> None:
    cls.DB_SCHEMA.register_owner(cls)
    super().__init_subclass__(*a, **kw)


  @classmethod
  def owned_types(cls) -> Generator[type[OwnableDatabaseObject], None, None]:
    return cls.DB_SCHEMA.iter_owned_types(cls)


  @cached_property
  @inject_db_cursor
  def owned(self, cursor: "Database.Cursor | None"=None) -> set[OwnableDatabaseObject]:
    return set(owned
      for owned_cls in self.owned_types()
        for owned in self.db.load(owned_cls, owner=self, cursor=cursor))

  
  def reset_cached_properties(self) -> None:
    super().reset_cached_properties()
    self.__dict__.pop("owned", None)


  