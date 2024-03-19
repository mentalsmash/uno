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
from functools import cached_property
from typing import Iterable, Callable, Generator, TYPE_CHECKING
# from collections.abc import Mapping, KeysView, ItemsView, ValuesView
from enum import Enum
import yaml

from ..core.time import Timestamp
from ..core.log import Logger as log, log_debug, DEBUG

from .database_object import DatabaseObject

if TYPE_CHECKING:
  from .database import Database


def load_inline_yaml(val: str) -> dict:
  # Try to interpret the string as a Path
  args_file = Path(val)
  if args_file.is_file():
    return yaml.safe_load(args_file.read_text())
  # Interpret the string as inline YAML
  return yaml.safe_load(val)


def strip_serialized_secrets(serialized: dict) -> dict:
  return strip_serialized_fields(serialized, {
    "privkey": "<omitted>",
    "psk": "<omitted>",
    "psks": "<omitted>",
  })


def strip_serialized_fields(serialized: dict, replacements: dict) -> dict:
  # Remove all secrets
  def _strip(tgt: dict) -> dict:
    updated = {}
    for k, v in tgt.items():
      if k in replacements:
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



# class DictView(Mapping):
#   def __init__(self, contents: dict, filter: Callable[[object], bool]) -> None:
#     self._contents = contents
#     self._filter = filter
#     super().__init__()


#   def __getitem__(self, key: object) -> object:
#     if not self._filter(key):
#       raise KeyError(key)
#     return self._contents.__getitem__(key)


#   def keys(self) -> KeysView:
#     return (k for k in self.keys() if self._filter(k))


#   def values(self) -> ValuesView:
#     return (v for _, v in self.items())


#   def items(self) -> ItemsView:
#     return (t for t in self.items() if self._filter(t[0]))


class Versioned(DatabaseObject):
  class PropertyDescriptor:
    PREFIX_PREV = "__prevprop__"

    def __init__(self, schema: "Versioned.Schema", name: str) -> None:
      self.schema = schema
      self.name = name
      self.attr_default = f"INITIAL_{self.name.upper()}"
      self.attr_prepare = f"prepare_{self.name}"
      self.attr_prev = f"{self.PREFIX_PREV}{self.name}"
      self.attr_storage = f"_{self.name}"
      self.prepare_fn = getattr(self.schema.cls, self.attr_prepare, None)
      self.has_default = hasattr(self.schema.cls, self.attr_default)
      self.is_nested_id = self.schema.nested and self.name == "id"


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
    def __versioned_property(self) -> bool:
      return self.name in Versioned.PROPERTIES


    def get(self, obj: "Versioned") -> object:
      if self.is_nested_id:
        return obj.parent.id
      else:
        return getattr(obj, self.attr_storage, None)


    def set(self, obj: "Versioned", val: object) -> None:
      if self.prepare_fn:
        val = self.prepare_fn(obj, val)
        if val is None:
          return
      current = getattr(obj, self.attr_storage)
      # Allow "read-only" attribute to be set only once
      if current != val and self.readonly and current is not None:
        raise RuntimeError("attribute is read-only", self.schema.cls.__qualname__, self.name)

      if current != val and (not self.readonly or current is None):
        setattr(obj, self.attr_storage, val)
        logger = (lambda *a, **kw: None) if self.reserved else log.activity
        logger("[{}] SET  {}.{} = {}", obj.__class__.__qualname__, obj.id or "<new>", self.name, val if (not self.secret or DEBUG) else "<secret>")
        # if not self.reserved and obj.loaded:
        if obj.loaded:
          setattr(obj, self.attr_prev, current)
        self.updated_property(obj)
      else:
        log.debug("[{}] SAME  {}.{} = {}", obj.__class__.__qualname__, obj.id or "<new>", self.name, val if (not self.secret or DEBUG) else "<secret>")


    def updated_property(self, obj: "Versioned") -> None:
      if self.eq:
        obj.__update_hash__()
      if self.cached:
        obj.__dict__.pop(self.name, None)

      # if self.str:
      #   obj.__update_str_repr__()

      # if self.reserved or self.__versioned_property:
      #   return

      # obj.generation_ts = Timestamp.now().format()
      # obj._updated.add(self.name)
      # obj.saved = False
      # log.debug("[{}] UPDATED  {}.{}", obj.__class__.__qualname__, obj.id or "<new>", self.name)


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
        # log_debug("[{}] INIT {}.{} = {}", self.__class__.__qualname__, self.id or "<new>", prop, init_val)
      else:
        log_debug("[{}] DEF  {}.{} = {}", obj.__class__.__qualname__, obj.id or "<new>", self.name,
          getattr(obj, self.attr_storage) if not self.secret or DEBUG else "<secret>")


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
        desc = Versioned.PropertyDescriptor(self, prop)
        setattr(self.cls, prop, desc)
        self.descriptors.append(desc)


    def descriptor(self, property: str) -> "Versioned.PropertyDescriptor|None":
      return next((d for d in self.descriptors if d.name == property), None)


    def init(self, obj: "Versioned", initial_values: dict|None=None):
      initial_values = initial_values or {}
      assert(obj.__class__ == self.cls)
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
    def nested(self) -> bool:
      return self.cls != Versioned and self.cls.DB_TABLE is None


    @cached_property
    def defined_properties(self) -> tuple[str]:
      initial = []
      if self.nested:
        initial.append("parent")
      return tuple(self._mro_yield_attr("PROPERTIES", initial_values=initial))


    @cached_property
    def serialized_properties(self) -> tuple[str]:
      volatile = set(self.volatile_properties)
      return tuple(self._mro_yield_attr("SERIALIZED_PROPERTIES",
        initial_values=set(self.defined_properties),
        filter_value=lambda v: v not in volatile))


    @cached_property
    def volatile_properties(self) -> frozenset[str]:
      return frozenset(self._mro_yield_attr("VOLATILE_PROPERTIES"))


    @cached_property
    def required_properties(self) -> frozenset[str]:
      initial = []
      if self.nested:
        initial.append("parent")
      return frozenset(self._mro_yield_attr("REQ_PROPERTIES", initial_values=initial))


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
      initial = []
      if self.nested:
        initial.append("id")
      return frozenset(self._mro_yield_attr("RO_PROPERTIES", initial_values=initial))


    @cached_property
    def eq_properties(self) -> frozenset[str]:
      return frozenset(self.cls.EQ_PROPERTIES)


    @cached_property
    def str_properties(self) -> frozenset[str]:
      return frozenset(self.cls.STR_PROPERTIES)


    @cached_property
    def property_groups(self) -> dict[str, frozenset[str]]:
      # TODO(asorbini) make this a "frozendict"
      return dict(self._mro_yield_map_attr("PROPERTY_GROUPS",
        value_to_yield=lambda v: tuple(v[0], frozenset(v[1]))))


    # def _define_properties(self) -> None:
    #   def _define_property(prop: str) -> None:
    #     attr_default = f"INITIAL_{prop.upper()}"
    #     attr_val = f"_{prop}"
    #     attr_prepare = f"prepare_{prop}"
    #     attr_prev = f"{cls.PREFIX_PREV}{prop}"
    #     attr_storage = f"_{prop}"
    #     attr_init = f"{cls.PREFIX_INIT}{prop}"
    #     prepare_fn = getattr(cls, attr_prepare, None)
    #     required = k in required_properties
    #     reserved = k in reserved_properties
    #     secret = k in secret_properties
    #     has_default = hasattr(cls, attr_default)
    #     attr_init_fn = None
    #     attr_property_fn = None

    #     if nested and prop == "id":
    #       @property
    #       def _parent_id(self) -> int | None:
    #         return self.parent.id
    #       attr_property_fn = _parent_id
    #       attr_init_fn = None
    #     else:
    #       @property
    #       def _getter(self) -> object:
    #         return getattr(self, attr_val, None)

    #       @_getter.setter
    #       def _setter(self, val: object) -> None:
    #         if prepare_fn:
    #           val = prepare_fn(self, val)
    #           if val is None:
    #             return
    #         current = getattr(self, attr_storage)
    #         if current != val:
    #           setattr(self, attr_storage, val)
    #           logger = (lambda *a, **kw: None) if reserved else log.activity
    #           logger("[{}] SET  {}.{} = {}", self.__class__.__qualname__, self.id or "<new>", prop, val if (not secret or DEBUG) else "<secret>")
    #           if not reserved and self.loaded:
    #             setattr(self, attr_prev, current)
    #             self.updated_property(prop)
    #         else:
    #           log.debug("[{}] SAME  {}.{} = {}", self.__class__.__qualname__, self.id or "<new>", prop, val if (not secret or DEBUG) else "<secret>")


    #       def _init(self, init_val: object | None) -> None:
    #         if has_default:
    #           def_val = getattr(self, attr_default)
    #           if callable(def_val):
    #             def_val = def_val()
    #         else:
    #           def_val = None

    #         setattr(self, attr_val, def_val)

    #         if required and getattr(self, prop) is None and init_val is None:
    #           raise ValueError("missing required property", self.__class__.__qualname__, prop)

    #         if init_val is not None:
    #           setattr(self, prop, init_val)
    #           # log_debug("[{}] INIT {}.{} = {}", self.__class__.__qualname__, self.id or "<new>", prop, init_val)
    #         else:
    #           log_debug("[{}] DEF  {}.{} = {}", self.__class__.__qualname__, self.id or "<new>", prop,
    #             getattr(self, attr_val) if not secret or DEBUG else "<secret>")
          
    #       attr_property_fn = _setter
    #       attr_init_fn = _init

    #     setattr(cls, prop, attr_property_fn)
    #     setattr(cls, attr_init, attr_init_fn)

    #   # properties = []
    #   # for tgt_cls in cls.mro():
    #   #   for prop in getattr(tgt_cls, "PROPERTIES", []):
    #   #     if prop in properties:
    #   #       continue
    #   #     properties.append(prop)

    #   properties = list(cls.defined_properties())
    #   required_properties = set(cls.required_properties())
    #   reserved_properties = set(cls.reserved_properties())
    #   secret_properties = set(cls.secret_properties())

    #   nested = cls != Versioned and cls.DB_TABLE is None

    #   for k in properties:
    #     _define_property(k)

    #   cls.__secret_properties = secret_properties
    #   cls.__reserved_properties = reserved_properties
    #   cls.__property_groups = cls.property_groups()
    #   cls.__cached_properties = set(cls.cached_properties())
    #   cls.__ro_properties = set(cls.readonly_properties())
    #   cls.__eq_properties = cls.eq_properties()
    #   cls.__str_properties = cls.str_properties()


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
    "db",
    "id",
    "generation_ts",
    "init_ts",
  ]
  RESERVED_PROPERTIES = [
    *PROPERTIES,
    "parent",
  ]
  SECRET_PROPERTIES = []
  REQ_PROPERTIES = [
    "db",
  ]
  STR_PROPERTIES = [
    "db",
    "id",
  ]
  EQ_PROPERTIES = [
    "id",
  ]
  SERIALIZED_PROPERTIES = []
  VOLATILE_PROPERTIES = [
    "db",
    "parent",
  ]
  PROPERTY_GROUPS = {}
  CACHED_PROPERTIES = []
  RO_PROPERTIES = []

  INITIAL_INIT_TS = lambda self: Timestamp.now()
  INITIAL_GENERATION_TS = lambda self: Timestamp.now()

  DB_TABLE_PROPERTIES = [
    "id",
    "generation_ts",
    "init_ts",
  ]

  def __init__(self, **properties) -> None:
    self._updated = set()
    self._loaded = False
    self._saved = False
    self.SCHEMA.init(self, properties)
    super().__init__()
    self.__update_str_repr__()
    self.__update_hash__()
    if self.id is None:
      self.validate_new()


  def validate_new(self) -> None:
    pass


  @classmethod
  def yaml_dump(cls, val: object, public: bool=False) -> str:
    if hasattr(val, "serialize") and callable(val.serialize):
      val = val.serialize(public=public)
    if public and isinstance(val, dict):
      val = strip_serialized_secrets(val)  
    return yaml.safe_dump(val)


  @classmethod
  def yaml_load(cls, val: str) -> object:
    return yaml.safe_load(val)


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
    fields = ', '.join(map(str, (getattr(self, p) for p in sorted(self.SCHEMA.str_properties))))
    cls_name = self.__class__.__qualname__
    dirty_str = "*" if self.dirty else ""
    self.__str_repr = f"{cls_name}({fields}){dirty_str}"


  def prepare_db(self, val: "Database | None") -> "Database":
    if val is None and self.DB_TABLE is None:
      val = self.parent.db
    assert(val is not None)
    return val


  def prepare_generation_ts(self, val: str | Timestamp) -> Timestamp:
    return prepare_timestamp(self.db, val)


  def serialize_generation_ts(self, val: Timestamp) -> str:
    return serialize_timestamp(val)


  def prepare_init_ts(self, val: str | Timestamp) -> Timestamp:
    return prepare_timestamp(self.db, val)


  def serialize_init_ts(self, val: Timestamp) -> str:
    return serialize_timestamp(val)


  @property
  def changed_properties(self) -> set[str]:
    return self._updated


  @property
  def changed_values(self) -> dict:
    """Return and reset the object's 'changed' flag."""
    changed = len(self._updated) > 0
    if not changed:
      return {}
    prev_values = {}
    for desc in self.SCHEMA.descriptors:
      prev_values[desc.name] = desc.prev(self)
    return prev_values


  def clear_changed(self, properties: Iterable[str]|None=None) -> None:
    if properties is None:
      self._updated.clear()
      for desc in self.SCHEMA.descriptors:
        desc.clear_prev(self)
    else:
      for prop in properties:
        try:
          self._updated.remove(prop)
        except KeyError:
          pass
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
    if desc:
      desc.updated_property(self)
    # Check if the property is a group
    elif attr in self.SCHEMA.property_groups:
      for v in self.SCHEMA.property_groups.get(attr, []):
        self.updated_property(v)

    if desc is None or not desc.reserved:
      self.generation_ts = Timestamp.now().format()
      self._updated.add(attr)
      self.saved = False
      log.debug("[{}] UPDATED  {}.{}", self.__class__.__qualname__, self.id or "<new>", attr)


  @property
  def loaded(self) -> bool:
    return self._loaded
  

  @loaded.setter
  def loaded(self, val: bool) -> None:
    self._loaded = val
    if val:
      log_debug("[{}] LOAD {} ({})", self.__class__.__qualname__, self.id or "<new>", self.generation_ts)


  @property
  def saved(self) -> bool:
    return self._saved
  

  @saved.setter
  def saved(self, val: bool) -> None:
    self._saved = val
    self.__update_str_repr__()
    # if val:
    #   log.activity("[{}] SAVED {} ({})", self.__class__.__qualname__, self.id or "<new>", self.generation_ts)


  @property
  def dirty(self) -> bool:
    if self.DB_TABLE:
      return not self.saved
    else:
      return len(self.changed_properties) > 0


  def save(self, cursor: "Database.Cursor|None"=None, create: bool=False) -> None:
    if not self.DB_TABLE_PROPERTIES:
      return
    
    def _dump_field(val):
      if isinstance(val, self.db.DB_TYPES):
        return val
      else:
        return self.yaml_dump(val)
    
    serialized = self.serialize(defined_only=True)
    fields = {
      prop: _dump_field(ser_val)
      for prop in self.DB_TABLE_PROPERTIES
        for ser_val in [serialized.get(prop)]
    }
    table = self.db.object_table(self, required=False)
    if table and fields:
      self.db.create_or_update(self,
        fields=fields,
        create=create,
        cursor=cursor,
        table=table)


  @classmethod
  def load(cls, db: "Database", serialized: dict) -> "Versioned":
    log_debug("[{}] DSER {}", cls.__qualname__, serialized)
    loaded = db.deserialize(cls, serialized)
    return loaded


  @classmethod
  def generate(cls, db: "Database", **properties) -> dict:
    return {}


  @classmethod
  def new(cls, db: "Database", **properties) -> "Versioned":
    return db.deserialize(cls, {
      **properties,
      **cls.generate(db, **properties)
    })



  def serialize(self, public: bool=False, defined_only: bool=False) -> dict:
    serialized = {}
    if defined_only:
      props = self.SCHEMA.defined_properties
    else:
      props = self.SCHEMA.serialized_properties
    for k in props:
      serializer = getattr(self, f"serialize_{k}", None)
      val = getattr(self, k)
      if k in self.SCHEMA.secret_properties and public:
        val = "<secret>"
      elif serializer:
        val = serializer(val)
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
        val = [v.serialize() for v in sorted(val, key=lambda v: v.id)]
      if val is not None:
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


  def collect_changes(self) -> list[tuple["Versioned", dict]]:
    collected = []
    remaining = [self]
    while remaining:
      o = remaining.pop(0)
      remaining.extend(n for n in o.nested)
      if o.dirty:
        prev = o.changed_values
        collected.append((o, prev))
    return collected


  def configure(self, __all: bool=False, **config_args) -> None:
    relevant = [(k, v)
      for k, v in config_args.items()
        if hasattr(self, k)
          and v is not None
          and (__all or k not in self.SCHEMA.readonly_properties)]
    if not relevant:
      log.debug("[{}] CONF {} nothing new in [{}]", self.__class__.__qualname__, self.id or "<new>", ", ".join(config_args.keys()))
      return
    log.debug("[{}] CONF {} [{}]", self.__class__.__qualname__, self.id or "<new>", ', '.join(k for k, v in relevant))
    for k, v in relevant:
      k_configure = getattr(getattr(self, k), "configure", None)
      if callable(k_configure):
        k_configure(**v)
      else:
        setattr(self, k, v)


  # def load_child(self, cls: type, **properties) -> "Versioned":
  #   loaded = next(self.db.load(cls, owner=self), None)
  #   if loaded is not None:
  #     return loaded
  #   return self.db.new(cls, **properties)


  def load_owned(self, cls: type) -> "set[Versioned]":
    return set(self.db.load(cls, owner=self))


  def new_child(self, cls: type, **properties) -> "Versioned":
    return self.db.new(cls, **{
      **properties,
      "parent": self,
    })


  def deserialize_child(self, cls: type, val: "str | dict | Versioned | None"=None) -> "Versioned":
    assert(issubclass(cls, Versioned))
    val = val or {}
    if isinstance(val, cls):
      return val
    if isinstance(val, str):
      val = yaml.safe_load(val)
    return self.db.deserialize(cls, {**val, "parent": self,})
  

  def deserialize_collection(self,
      cls: type,
      val: str | Iterable[object],
      collection_cls: type=list,
      load_child: Callable|None=None) -> Iterable[object]:
    if not load_child:
      load_child = lambda cls, child: cls(child)

    if not val:
      return collection_cls()
    if isinstance(val, str):
      val = self.yaml_load(val)
    def _values():
      if hasattr(val, "values") and callable(val.values):
        return val.values()
      else:
        return val
    if isinstance(val, collection_cls):
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

