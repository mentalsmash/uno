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
from pathlib import Path
from functools import cached_property, wraps
from typing import Iterable, Callable, Generator, TYPE_CHECKING
# from collections.abc import Mapping, KeysView, ItemsView, ValuesView
from enum import Enum
import yaml
import json

from ..core.time import Timestamp
from ..core.log import Logger

from .database_object import DatabaseObject, DatabaseObjectOwner, OwnableDatabaseObject, inject_db_cursor

if TYPE_CHECKING:
  from .database import Database


def strip_serialized_secrets(serialized: dict) -> dict:
  return strip_serialized_fields(serialized, {
    "privkey": "<omitted>",
    "psk": "<omitted>",
    "psks": "<omitted>",
  })


def strip_serialized_fields(serialized: dict, replacements: dict) -> dict:
  # Remove some fields or replace them with another value
  def _strip(tgt: dict) -> dict:
    updated = {}
    for k, v in tgt.items():
      if k in replacements:
        if callable(replacements[k]):
          v = replacements[k](v)
        else:
          v = replacements[k]
      elif isinstance(v, dict):
        v = _strip(v)
      elif isinstance(v, list) and v and isinstance(v[0], dict):
        v = [_strip(e) for e in v]
      if v is not False and not v:
        continue
      updated[k] = v
    return updated
  return _strip(serialized)



def strip_tuples(serialized: dict) -> dict:
  def _strip(tgt: dict) -> dict:
    updated = {}
    for k, v in list(tgt.items()):
      if isinstance(v, dict):
        updated[k] = _strip(v)
      elif isinstance(v, tuple):
        updated[k] = list(v)
      else:
        updated[k] = v
    return updated
  return _strip(serialized)


def _log_secret_val(obj: "Versioned", val: object, desc: "Versioned.PropertyDescriptor|None"=None) -> object:
  if Logger.DEBUG or (desc is None or not desc.secret):
    return val
  return obj.OMITTED


def disabled_if_readonly(wrapped):
  @wraps(wrapped)
  def _wrapped(self, *a, **kw):
    if self.readonly:
      raise TypeError("cannot invoke method on readonly object", self.__class__, wrapped.__name__)
    return wrapped(self, *a, **kw)
  return _wrapped



def noop_if_readonly(retval: object|None=None):
  def _noop_if_readonly(wrapped):
    @wraps(wrapped)
    def _wrapped(self: "Versioned", *a, **kw):
      if self.readonly:
        self.log.debug("OP DISABLED {}", wrapped.__name__)
        if callable(retval):
          return retval()
        else:
          return retval
      return wrapped(self, *a, **kw)
    return _wrapped
  return _noop_if_readonly


def dispatch_if_readonly(other: str|Callable):
  if callable(other):
    dispatch = lambda self, *a, **kw: other(self, *a, **kw)
  else:
    dispatch = lambda self, *a, **kw: getattr(self, other)(*a, **kw)
  def _dispatch_if_readonly(wrapped):
    @wraps(wrapped)
    def _wrapped(self: "Versioned", *a, **kw):
      if self.readonly:
        self.log.debug("OP DISABLED {} -> {}", wrapped.__name__, other)
        return dispatch(self, *a, **kw)
      return wrapped(self, *a, **kw)
    return _wrapped
  return _dispatch_if_readonly


class Versioned(DatabaseObject):
  class PropertyDescriptor:
    PREFIX_PREV = "__prevprop__"

    def __init__(self, schema: "Versioned.Schema", name: str, cls_attr: Callable[["Versioned"], object]|None=None) -> None:
      self.schema = schema
      self.name = name
      if cls_attr is not None and callable(cls_attr):
        self._get_cls_attr = lambda self: cls_attr(self)
      else:
        self._get_cls_attr = None
      self.attr_default = f"INITIAL_{self.name.upper()}"
      self.attr_prepare = f"prepare_{self.name}"
      self.attr_prev = f"{self.PREFIX_PREV}{self.name}"
      self.attr_storage = f"_{self.name}"
      self.prepare_fn = getattr(self.schema.cls, self.attr_prepare, None)
      self.has_default = hasattr(self.schema.cls, self.attr_default)
      self.group = self.schema.property_groups.get(self.name, frozenset())


    def __str__(self) -> str:
      return f"{self.schema.cls.__qualname__}.{self.name}"


    def __get__(self, obj: "Versioned", objtype: type|None=None) -> object:
      return self.get(obj)


    def __set__(self, obj: "Versioned", value: object) -> None:
      return self.set(obj, value)


    @cached_property
    def serialized(self) -> bool:
      return self.name in self.schema.serialized_properties


    @cached_property
    def volatile(self) -> bool:
      return self.name in self.schema.volatile_properties


    @cached_property
    def required(self) -> bool:
      return self.name in self.schema.required_properties


    @cached_property
    def reserved(self) -> bool:
      return self.name in self.schema.reserved_properties
  

    @cached_property
    def track_changes(self) -> bool:
      return not self.reserved

  
    @cached_property
    def secret(self) -> bool:
      return self.name in self.schema.secret_properties


    @cached_property
    def readonly(self) -> bool:
      return self.name in self.schema.readonly_properties
  

    @cached_property
    def eq(self) -> bool:
      return self.name in self.schema.eq_properties


    @cached_property
    def str(self) -> bool:
      return self.name in self.schema.str_properties


    @cached_property
    def cached(self) -> bool:
      return self.name in self.schema.cached_properties


    @cached_property
    def json(self) -> bool:
      return self.name in self.schema.json_properties


    def get(self, obj: "Versioned") -> object | None:
      if self._get_cls_attr:
        return self._get_cls_attr(obj)
      return getattr(obj, self.attr_storage, None)


    def set(self, obj: "Versioned", val: object) -> None:
      # if obj.readonly:
      #   raise TypeError("object is readonly", obj.__class__)

      if self.prepare_fn:
        set_val = val
        val = self.prepare_fn(obj, val)
        if val is None:
          obj.log.tracedbg("SET {} prevented by prepare(): {}", self.name, set_val)
          return

      current = getattr(obj, self.attr_storage)
      readonly = self.readonly or obj.readonly
      # Allow "read-only" attribute to be set only once
      if (not self.reserved
          and obj.loaded
          and readonly
          and current != val):
        raise RuntimeError("attribute is read-only", self.schema.cls.__qualname__, self.name)

      if isinstance(current, Versioned) and isinstance(val, dict):
        current.configure(**val)
        if current.dirty:
          obj.log.debug("CONFIGURED {} = {}", self.name, _log_secret_val(obj, getattr(obj, self.name), self))
          obj.updated_property(self.name)
      elif current != val:
        setattr(obj, self.attr_storage, val)
        # if not self.reserved and obj.loaded:
        if obj.loaded:
          setattr(obj, self.attr_prev, current)
        if not self.reserved:
          obj.log.debug("SET {} = {}", self.name, _log_secret_val(obj, getattr(obj, self.name), self))
          obj.updated_property(self.name)
      else:
        obj.log.tracedbg("NOT SET {} (unchanged): {} == {}", self.name, val, current)

      # else:
      #   obj.log.trace("SAME {} = {}", self.name, _log_secret_val(obj, val, self))


    def init(self, obj: "Versioned", init_val: object|None=None) -> None:
      if self.has_default:
        def_val = getattr(obj, self.attr_default)
        if callable(def_val):
          def_val = def_val()
      else:
        def_val = None

      setattr(obj, self.attr_storage, def_val)

      if self.required and getattr(obj, self.name) is None and init_val is None:
        raise ValueError("missing required property", obj.__class__.__qualname__, self.name)

      if init_val is not None:
        setattr(obj, self.name, init_val)
      
      obj.log.trace("DEF {} = {}", self.name, _log_secret_val(obj, getattr(obj, self.attr_storage), self))


    def prev(self, obj: "Versioned") -> object|None:
      return getattr(obj, self.attr_prev, None)


    def clear_prev(self, obj: "Versioned") -> object|None:
      if hasattr(obj, self.attr_prev):
        delattr(obj, self.attr_prev)



  class Schema:
    def __init__(self, cls: type) -> None:
      assert(issubclass(cls, Versioned))
      self.cls = cls
      self.descriptors: list[Versioned.PropertyDescriptor] = []
      for prop in self.defined_properties:
        cls_attr = getattr(self.cls, prop, None)
        desc = Versioned.PropertyDescriptor(self, prop, cls_attr)
        setattr(self.cls, prop, desc)
        self.descriptors.append(desc)


    def descriptor(self, property: str) -> "Versioned.PropertyDescriptor|None":
      return next((d for d in self.descriptors if d.name == property), None)


    def init(self, obj: "Versioned", initial_values: dict|None=None):
      initial_values = initial_values or {}
      assert(obj.__class__ == self.cls)
      if self.transient and obj.parent is None:
        raise ValueError("transient object requires a parent", obj)
      for prop in self.descriptors:
        init_val = initial_values.get(prop.name)
        prop.init(obj, init_val)


    def _mro_yield_map_attr(self,
        attr: str,
        initial_values: dict|None=None,
        filter_value: Callable[[object], bool]|None=None,
        value_to_yield: Callable[[object], object]|None=None) -> Generator[object, None, None]:
      return self._mro_yield_attr(attr, initial_values, filter_value,
        iter_values=lambda values: values.items(),
        value_to_key=lambda v: v[0],
        value_to_yield=value_to_yield,
        collection_cls=dict)


    def _mro_yield_attr(self,
        attr: str,
        initial_values: Iterable[object]|None=None,
        filter_value: Callable[[object], bool]|None=None,
        iter_values: Callable[[Iterable[object]], Iterable[object]]|None=None,
        value_to_key: Callable[[object], object]|None=None,
        value_to_yield: Callable[[object], object]|None=None,
        collection_cls: type=list) -> Generator[object, None, None]:
      returned = []
      filter_value = filter_value or (lambda o: True)
      iter_values = iter_values or (lambda values: values)
      value_to_key = value_to_key or (lambda o: o)
      value_to_yield = value_to_yield or (lambda o: o)
      if initial_values is None:
        initial_values = collection_cls()
      
      def _yield(values):
        for val in iter_values(values):
          val_key = value_to_key(val)
          if not filter_value(val_key) or val_key in returned:
            continue
          returned.append(val_key)
          yield val
      for y in _yield(initial_values):
        yield y

      mro = self.cls.mro()
      mro.reverse()
      for tgt_cls in mro:
        for y in _yield(getattr(tgt_cls, attr, collection_cls())):
          yield y


    @cached_property
    def ownable(self) -> bool:
      return isinstance(self.cls, OwnableDatabaseObject)


    @cached_property
    def owner(self) -> bool:
      return isinstance(self.cls, DatabaseObjectOwner)


    @cached_property
    def transient(self) -> bool:
      return self.cls.transient_object()


    @cached_property
    def defined_properties(self) -> tuple[str]:
      return tuple(self._mro_yield_attr("PROPERTIES"))


    @cached_property
    def serialized_properties(self) -> tuple[str]:
      volatile = set(self.volatile_properties)
      return tuple(self._mro_yield_attr("SERIALIZED_PROPERTIES",
        initial_values={
          *self.defined_properties,
          # *(["owner_id"] if self.transient else []),
        },
        filter_value=lambda v: v not in volatile))


    @cached_property
    def json_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("JSON_PROPERTIES"))


    @cached_property
    def volatile_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("VOLATILE_PROPERTIES"))


    @cached_property
    def required_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("REQ_PROPERTIES"))


    @cached_property
    def reserved_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("RESERVED_PROPERTIES"))


    @cached_property
    def secret_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("SECRET_PROPERTIES"))


    @cached_property
    def cached_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("CACHED_PROPERTIES"))


    @cached_property
    def readonly_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("RO_PROPERTIES"))


    @cached_property
    def eq_properties(self) -> frozenset[str]:
      props = self.cls.EQ_PROPERTIES
      if not props:
        props = self.default_eq_properties
      return frozenset(props)


    @cached_property
    def str_properties(self) -> frozenset[str]:
      props = self.cls.STR_PROPERTIES
      if not props:
        props = self.default_str_properties
      return frozenset(props)


    @cached_property
    def default_eq_properties(self) -> frozenset[str]:
      return frozenset(["db", "object_id", "init_ts", "generation_ts"])


    @cached_property
    def default_str_properties(self) -> frozenset[str]:
      if self.transient:
        return frozenset(["parent_str_id"])
      return frozenset(["id"])


    @cached_property
    def property_groups(self) -> dict[str, frozenset[str]]:
      # TODO(asorbini) make this a "frozendict"
      return dict(self._mro_yield_map_attr("PROPERTY_GROUPS",
        value_to_yield=lambda v: tuple(v[0], frozenset(v[1]))))


    @cached_property
    def db_table_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("DB_TABLE_PROPERTIES"))


  SCHEMA = None

  # Some day we might want to create a DSL...
  RESERVED_KEYWORDS = [
    "root",
    "registry",
    "agent",
    "uvn",
    "cell",
    "particle",
    "user",
    "network",
    "lan",
    "vpn",
    "port",
    "server",
    "address",
    "owner",
  ]

  PROPERTIES = [
    "readonly",
    "generation_ts",
    "init_ts",
  ]
  RESERVED_PROPERTIES = [
    *PROPERTIES,
    "parent",
    "db",
  ]
  SECRET_PROPERTIES = []
  REQ_PROPERTIES = []
  STR_PROPERTIES = []
  EQ_PROPERTIES = []
  SERIALIZED_PROPERTIES = []
  JSON_PROPERTIES = [
    "object_id",
    "owner_id",
    "parent_id",
  ]
  VOLATILE_PROPERTIES = [
    # "init_ts",
    # "generation_ts",
    "readonly",
  ]
  PROPERTY_GROUPS = {}
  CACHED_PROPERTIES = [
    "log",
  ]
  RO_PROPERTIES = []

  INITIAL_READONLY = False
  INITIAL_INIT_TS = lambda self: Timestamp.now()
  INITIAL_GENERATION_TS = lambda self: Timestamp.now()

  DB_TABLE_PROPERTIES = [
    "id",
    "generation_ts",
    "init_ts",
  ]

  def __init__(self, db: "Database", id: "object|None"=None, parent: "Versioned|None"=None, **properties) -> None:
    super().__init__(db=db, id=id, parent=parent)
    self._readonly = False
    self.SCHEMA.init(self, properties)
    self.__update_str_repr__()
    self.__update_hash__()


  def validate(self) -> None:
    pass


  # @cached_property
  # def log(self) -> UvnLogger:
  #   raise RuntimeError("wtf")
  #   # return self.__class__.sublogger(str(self.id) if self.id is not None else "<new>")
  #   return self.__class__.sublogger(self.__str_repr)


  @classmethod
  def yaml_dump(cls, val: object, public: bool=False) -> str:
    if hasattr(val, "serialize") and callable(val.serialize):
      val = val.serialize(public=public)
    if public and isinstance(val, dict):
      val = strip_serialized_secrets(val)
    if isinstance(val, tuple):
      val = list(val)
    elif isinstance(val, set):
      val = sorted(val)
    elif isinstance(val, dict):
      val = strip_tuples(val)
    return yaml.dump(val)


  @classmethod
  def yaml_load(cls, val: str) -> object:
    return yaml.safe_load(val)


  @classmethod
  def json_dump(cls, val: object, public: bool=False) -> str:
    if hasattr(val, "serialize") and callable(val.serialize):
      val = val.serialize(public=public)
    if public and isinstance(val, dict):
      val = strip_serialized_secrets(val)
    return json.dumps(val)


  @classmethod
  def json_load(cls, val: str) -> object:
    return json.loads(val)


  @classmethod
  def yaml_load_inline(cls, val: str | Path) -> dict:
    # Try to interpret the string as a Path
    yml_val = val
    args_file = Path(val)
    if args_file.is_file():
      yml_val = args_file.read_text()
    # Interpret the string as inline YAML
    if not isinstance(yml_val, str):
      raise ValueError("failed to load yaml", val)
    return cls.yaml_load(yml_val)


  def __str__(self) -> str:
    return self.__str_repr


  def __repr__(self) -> str:
    return str(self)
    # return f"{self.__class__.__qualname__}({self.db.root}, {self.id}){'*' if self.dirty else ''}"


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, self.__class__):
      return False
    for prop in self.SCHEMA.eq_properties:
      if getattr(self, prop) != getattr(other, prop):
        return False
    return True


  def __hash__(self) -> int:
    return self.__cachedhash__


  def __update_hash__(self) -> int:
    self.__cachedhash__ = hash(tuple(getattr(self, p) for p in sorted(self.SCHEMA.eq_properties)))


  def __update_str_repr__(self) -> None:
    props = sorted(self.SCHEMA.str_properties)
    fields = []
    for p in props:
      v = getattr(self, p)
      if v is None:
        v = "null"
      fields.append(v)
    fields = ', '.join(map(str, fields))
    cls_name = self.log.camelcase_to_kebabcase(self.__class__.__qualname__)
    dirty_str = ("*" if self.dirty else "") if not self.SCHEMA.transient else ""
    self.__str_repr = f"{cls_name}({fields}){dirty_str}"
    if self.log is None:
      self.log = Logger.sublogger(self.__str_repr)
    else:
      self.log.context = self.__str_repr


  def prepare_db(self, val: "Database | None") -> "Database":
    if val is None and self.DB_TABLE is None:
      val = self.parent.db
    assert(val is not None)
    return val


  def prepare_generation_ts(self, val: str | Timestamp) -> Timestamp:
    return prepare_timestamp(self.db, val)


  def serialize_generation_ts(self, val: Timestamp, public: bool=False) -> str:
    return serialize_timestamp(val)


  def prepare_init_ts(self, val: str | Timestamp) -> Timestamp:
    return prepare_timestamp(self.db, val)


  def serialize_init_ts(self, val: Timestamp, public: bool=False) -> str:
    return serialize_timestamp(val)



  # @property
  # def readonly(self) -> bool:
  #   return self._readonly


  # @readonly.setter
  # def readonly(self, val: bool) -> None:
  #   self._readonly = val
  #   if val:
  #     raise RuntimeError("waeaads")



  @property
  def changed_values(self) -> dict:
    """Return and reset the object's 'changed' flag."""
    changed = len(self.changed_properties) > 0
    if not changed:
      return {}
    prev_values = {}
    for desc in self.SCHEMA.descriptors:
      prev_values[desc.name] = desc.prev(self)
    return prev_values


  def clear_changed(self, properties: Iterable[str]|None=None) -> None:
    super().clear_changed(properties)
    if properties is None:
      for desc in self.SCHEMA.descriptors:
        desc.clear_prev(self)
    else:
      for prop in properties:
        desc = self.SCHEMA.descriptor(prop)
        if desc:
          desc.clear_prev(self)
    self.__update_str_repr__()


  def updated_property(self, attr: str) -> None:
    # Always regenerate str represenation,
    # easier than trying to do it only when needed
    self.__update_str_repr__()

    # Check if we have a descriptor for the attribute
    desc = self.SCHEMA.descriptor(attr)
    if (desc and desc.eq) or attr in self.SCHEMA.eq_properties:
      self.__update_hash__()
    cached = (desc and desc.cached) or attr in self.SCHEMA.cached_properties
    if cached:
      self.__dict__.pop(attr, None)
    # Check if the property is a group
    group = desc.group if desc else self.SCHEMA.property_groups.get(attr)
    if group:
      for v in group:
        self.updated_property(v)

    if (desc is None or desc.track_changes) or self.track_changes:
      self.generation_ts = Timestamp.now().format()
      self.changed_properties.add(attr)
      self.saved = False
      self.log.trace("UPDATED {}", attr)


  def reset_cached_properties(self) -> None:
    super().reset_cached_properties()
    for cached in self.SCHEMA.cached_properties:
      self.updated_property(cached)


  def updated_property_groups(self) -> None:
    for group in self.SCHEMA.property_groups:
      self.updated_property(group)


  def save(self, cursor: "Database.Cursor|None"=None, create: bool=False, public: bool=False) -> None:
    if not self.SCHEMA.db_table_properties:
      return
    
    def _dump_field(prop, val, desc):
      if val == self.OMITTED:
        return None
      elif isinstance(val, self.db.DB_TYPES):
        return val
      elif ((desc is not None and desc.json)
            or (desc is None and prop in self.SCHEMA.json_properties)):
        return self.json_dump(val)
      else:
        return self.yaml_dump(val)

    serialized = self.serialize(public=public)
    fields = {
      prop: _dump_field(prop, ser_val, desc)
      for prop in self.SCHEMA.db_table_properties
        for ser_val in [serialized.get(prop)]
          for desc in [self.SCHEMA.descriptor(prop)]
    }
    table = self.db.SCHEMA.lookup_table_by_object(self, required=False)
    if table and fields:
      self.db.create_or_update(self,
        fields=fields,
        create=create,
        cursor=cursor,
        table=table)


  def serialize(self, public: bool=False) -> dict:
    serialized = {}
    props = self.SCHEMA.serialized_properties
    for k in props:
      serializer = getattr(self, f"serialize_{k}", None)
      val = getattr(self, k)
      if k in self.SCHEMA.secret_properties and public:
        val = self.OMITTED
      elif serializer:
        val = serializer(val, public=public)
      elif hasattr(val, "serialize"):
        val = val.serialize(public=public)
      elif isinstance(val, Enum):
        val = serialize_enum(val)
      elif isinstance(val, Timestamp):
        val = serialize_timestamp(val)
      elif (not isinstance(val, str)
            and isinstance(val, Iterable)
            and (
              isinstance(next(iter(val), None), Versioned)
              or (hasattr(val, "values")
                  and isinstance(next(iter(val.values()), None), Versioned))
            )):
        if hasattr(val, "values"):
          val = val.values()
        val = [v.serialize(public=public) for v in sorted(val, key=lambda v: v.object_id)]
      if val is not None:
        if isinstance(val, tuple):
          val = list(val)
        serialized[k] = val
    return serialized


  @classmethod
  def deserialize_args(cls, db: "Database", serialized: dict) -> dict:
    deserialized = {}
    for k in cls.SCHEMA.defined_properties:
      deserializer = getattr(cls, f"deserialize_{k}", lambda v: v)
      val = deserializer(serialized.get(k))
      if val is not None:
        deserialized[k] = val
    return {"db": db, **deserialized}


  @property
  def nested(self) -> "Generator[Versioned, None, None]":
    for i in []:
      yield i


  @property
  def track_changes(self) -> bool:
    return self.loaded or self.SCHEMA.transient


  def collect_changes(self) -> Generator[tuple["Versioned", dict], None, None]:
    for o in self.collect_nested(dirty=True):
      prev = o.changed_values
      yield (o, prev)


  def collect_nested(self, dirty: bool=False) -> Generator["Versioned", None, None]:
    remaining = [self] if not dirty or self.dirty else []
    while remaining:
      o = remaining.pop(0)
      remaining.extend(n for n in o.nested if not dirty or n.dirty)
      yield o


  def configure(self, __all: bool=False, **config_args) -> None:
    relevant = [(k, v)
      for k, v in config_args.items()
        if hasattr(self, k)
          and v is not None
          and (__all or k not in self.SCHEMA.readonly_properties)]
    if not relevant:
      self.log.debug("CONF nothing new in [{}]", ", ".join(config_args.keys()))
      return
    self.log.debug("CONF [{}]", ', '.join(k for k, v in relevant))
    for k, v in relevant:
      s_k_configure = getattr(self, f"configure_{k}", None)
      if callable(s_k_configure):
        s_k_configure(v)
        continue
      k_configure = getattr(getattr(self, k), "configure", None)
      if callable(k_configure):
        k_configure(**v)
        continue
      setattr(self, k, v)
    self.validate()


  @inject_db_cursor
  def load_owned(self, cls: type, cursor: "Database.Cursor") -> "set[Versioned]":
    return set(self.db.load(cls, owner=self, cursor=cursor))


  def new_child(self,
      cls: type,
      val: "str | dict | Versioned | None"=None,
      owner: DatabaseObjectOwner|None=None,
      save: bool=True) -> "Versioned":
    if isinstance(val, cls):
      if getattr(val, "parent", None) == self:
        if save:
          self.db.save(val)
        return val
      elif hasattr(val, "serialize") and callable(val.serialize):
        val = val.serialize()
      else:
        raise NotImplementedError("cannot transfer parent", val)

    val = val or {}
    if isinstance(val, str):
      val = self.yaml_load(val)
    return self.db.new(cls, properties={
      **val,
      "parent": self,
      "readonly": self.readonly,
      "init_ts": self.init_ts,
      "generation_ts": self.generation_ts,
    }, owner=owner, save=save)


  def load_child(self, cls: type, **search_args) -> "Versioned|None":
    return next(self.load_children(cls, **search_args), None)
  

  @inject_db_cursor
  def load_children(self, cls: type, cursor: "Database.Cursor|None"=None, **search_args) -> Generator["Versioned", None, None]:
    return self.db.load(cls, **search_args, load_args={
      "parent": self,
    }, cursor=cursor)


  def deserialize_collection(self,
      cls: type,
      val: str | Iterable[object],
      collection_cls: type=list,
      load_child: Callable|None=None,
      force: bool=False) -> Iterable[object]:
    if not load_child:
      load_child = lambda cls, child: cls(child)
    if not val:
      return collection_cls()
    if isinstance(val, str):
      val = self.yaml_load(val)
    def _values():
      if hasattr(val, "items") and callable(val.items):
        return val.items()
      elif hasattr(val, "values") and callable(val.values):
        return val.values()
      else:
        return val
    if not force and isinstance(val, collection_cls):
      # Check the first element in the collection and assume
      # all others are of the same type
      if isinstance(next(iter(_values()), None), cls):
        return val
    return collection_cls(load_child(cls, c) for c in _values())


  @classmethod
  def define_properties(cls) -> None:
    # This function should be called only once for every class
    assert(cls.__dict__.get("SCHEMA") is None)
    cls.SCHEMA = Versioned.Schema(cls)
    cls.log = Logger.sublogger(cls.__qualname__)


  def __init_subclass__(cls, *args, **kwargs) -> None:
    cls.define_properties()
    super().__init_subclass__(*args, **kwargs)


Versioned.define_properties()


def prepare_collection(
    db: "Database",
    val: Iterable[dict],
    elements_cls: type|None=None,
    collection_cls: type|None = tuple,
    mkelement: Callable[[object], object]|None=None) -> "Iterable[Versioned]":
  if elements_cls and hasattr(elements_cls, "deserialize_args"):
    deserializer = lambda v: db.deserialize(elements_cls, v)
  elif mkelement:
    deserializer = mkelement
  elif elements_cls:
    deserializer = elements_cls
  else:
    raise NotImplementedError()
  
  return collection_cls(map(deserializer, val))


def prepare_map(
    db: "Database",
    val: Iterable[dict],
    elements_cls: type|None=None,
    map_cls: type|None = dict,
    mkitem: Callable[[object], tuple[object, object]]|None=None) -> "set[Versioned]":
  if elements_cls and hasattr(elements_cls, "deserialize_args"):
    return map_cls(
      (d.id, d)
      for v in val
        for d in [db.deserialize(elements_cls, v)])
  elif mkitem:
    return map_cls(map(mkitem, val))
  else:
    raise NotImplementedError()


def prepare_timestamp(db: "Database", val: Timestamp|str) -> Timestamp:
  if isinstance(val, Timestamp):
    return val
  else:
    return Timestamp.parse(val)


def serialize_timestamp(val: Timestamp) -> str:
  return val.format()


def prepare_enum(db: "Database", cls: type, val: Enum|str) -> Enum:
  if isinstance(val, Enum):
    return val
  else:
    return cls[val.upper().replace("-", "_")]


def serialize_enum(val: Enum) -> str:
  return val.name.lower().replace("_", "-")


def prepare_name(db: "Database", val: str) -> str:
  if not val:
    raise ValueError("invalid name", val)
  if val.lower() in Versioned.RESERVED_KEYWORDS:
    raise RuntimeError(f"'{val}' is a reserved keyword")
  return val

