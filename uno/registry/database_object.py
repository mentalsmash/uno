from functools import cached_property
from enum import Enum
from typing import Generator, TYPE_CHECKING
from collections.abc import Iterable

if TYPE_CHECKING:
  from .database import Database

class DatabaseSchema:
  _Types: "set[DatabaseObject]" = set()


  @classmethod
  def types(cls) -> "set[DatabaseObject]":
    return cls._Types


  @classmethod
  def objects(cls) -> "set[DatabaseObject]":
    return {t for t in cls._Types if t.DB_TABLE is not None}


  @classmethod
  def ownables_types(cls) -> "set[OwnableDatabaseObject]":
    return {t for t in cls._Types if isinstance(t, OwnableDatabaseObject)}


  @classmethod
  def ownables_objects(cls) -> "set[OwnableDatabaseObject]":
    return {t for t in cls.objects() if isinstance(t, OwnableDatabaseObject)}



class DatabaseObject:
  DB_TABLE = None
  DB_TABLE_PROPERTIES = None
  DB_CACHED = True
  db: "Database" = None
  id: int|None = None


  def __init__(self, *a, **kw) -> None:
    super().__init__(*a, **kw)


  def __init_subclass__(cls, *a, **kw) -> None:
    DatabaseSchema._Types.add(cls)
    super().__init_subclass__(*a, **kw)


class OwnableDatabaseObject(DatabaseObject):
  DB_OWNER = None
  DB_OWNER_TABLE = None
  DB_OWNER_TABLE_COLUMN = None

  SERIALIZED_PROPERTIES = ["owner"]
  CACHED_PROPERTIES = ["owner"]

  def __init_subclass__(cls, *a, **kw) -> None:
    if cls.DB_OWNER is not None:
      for owner in cls.owner_types():
        assert(issubclass(owner, DatabaseObjectOwner))
        owner.DB_OWNED = getattr(owner, "DB_OWNED") or set()
        owner.DB_OWNED.add(cls)
    super().__init_subclass__(*a, **kw)


  @classmethod
  def owner_types(cls) -> "set[DatabaseObjectOwner]":
    if not isinstance(cls.DB_OWNER, type) and callable(cls.DB_OWNER):
      owner = cls.DB_OWNER()
    else:
      owner = cls.DB_OWNER
    if owner is None:
      return set()
    elif isinstance(owner, Iterable):
      return set(owner)
    else:
      return {owner}


  @cached_property
  def owner(self) -> "DatabaseObjectOwner | None":
    if self.id is None:
      return None
    return self.db.owner(self)


  def serialize_owner(self, val: "DatabaseObjectOwner | None") -> tuple[str, int]:
    if val is None:
      return tuple()
    return (val.DB_TABLE, val.id)


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
      


class DatabaseObjectOwner(DatabaseObject):
  DB_OWNED = None
  CACHED_PROPERTIES = ["owned"]

  @cached_property
  def owned(self) -> set[OwnableDatabaseObject]:
    return set(self.db.owned(self))
