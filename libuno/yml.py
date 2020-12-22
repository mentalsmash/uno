###############################################################################
# (C) Copyright 2020 Andrea Sorbini
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
import pathlib
import collections.abc
import json as sys_json

import yaml

def json(obj, **kwargs):
    return yml(obj, _json=True, **kwargs)

def yml(obj, **kwargs):
    serializer = YamlSerializer._class_serializer_assert_obj(obj)
    return serializer.to_yaml(obj, **kwargs)

def yml_obj(cls, yml_str, **kwargs):
    serializer = YamlSerializer._class_serializer_assert(cls)
    return serializer.from_yaml(yml_str, **kwargs)

def repr_yml(py_repr, **kwargs):
    serializer = YamlSerializer._class_serializer_assert_obj(py_repr)
    return serializer.repr_yml(py_repr, **kwargs)

def repr_py(cls, yml_repr, **kwargs):
    serializer = YamlSerializer._class_serializer_assert(cls)
    return serializer.repr_py(yml_repr, **kwargs)

class YamlError(Exception):
    def __init__(self, msg):
        self.msg = msg

def YamlObject(cls):
    """A decorator to explicitly enable YAML serialization on a class"""
    YamlSerializer._class_serializer_assert(cls)
    return cls

class YamlSerializer:

    _class_serializer_attr = "_serializer_yml"
    _class_serializer_name = "_YamlSerializer"

    _obj_serializer_attr = "yaml_serializer"
    
    @staticmethod
    def _class_serializer_assert(cls):
        serializer = getattr(cls, YamlSerializer._class_serializer_attr, None)
        if serializer is None:
            serializer_cls = getattr(cls,
                                    YamlSerializer._class_serializer_name,
                                    None)
            if (serializer_cls is None):
                if issubclass(cls, collections.abc.Mapping):
                    serializer = _MappingYamlSerializer(cls)
                elif issubclass(cls, collections.abc.Set):
                    serializer = _SetYamlSerializer(cls)
                elif issubclass(cls, collections.abc.Collection):
                    serializer = _CollectionYamlSerializer(cls)
                elif issubclass(cls, collections.abc.Iterable):
                    serializer = _IterableYamlSerializer(cls)
                else:
                    serializer = YamlSerializer()
            else:
                serializer = serializer_cls()
            try:
                setattr(cls, YamlSerializer._class_serializer_attr, serializer)
            except:
                # Ignore failure, assuming it's because we tried to cache
                # the serializer on a built-in type
                pass
            
        if not isinstance(serializer, YamlSerializer):
            raise YamlError(
                    "invalid YAML serializer for class: {}".format(cls))
        return serializer
    
    @staticmethod
    def _class_serializer_assert_obj(obj):
        serializer_obj = getattr(obj, YamlSerializer._obj_serializer_attr, None)
        if serializer_obj is None:
            serializer_obj = YamlSerializer._class_serializer_assert(obj.__class__)
        elif not isinstance(serializer_obj, YamlSerializer):
            raise YamlError(
                    "invalid YAML serializer for object: {}".format(obj))
        return serializer_obj

    def _yaml_doc_fmt(self, begin):
        if begin:
            return "---\n{}\n...\n"
        else:
            return "{}"
    
    def _file_format_out(self, yml_str, **kwargs):
        return yml_str
    
    def _file_format_in(self, yml_str, **kwargs):
        return yml_str

    def _file_write(self, file, contents, append):
        if isinstance(file, str):
            file = pathlib.Path(file)
        if append:
            f_mode = "a"
        else:
            f_mode = "w"
        
        parent_dir = file.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        with file.open(f_mode) as outfile:
            outfile.write(contents)
    
    def _file_read(self, file):
        if isinstance(file, str):
            file = pathlib.Path(file)
        with file.open("r") as f:
            return f.read()
    
    def _yaml_load(self, yml_str):
        return yaml.safe_load(yml_str)

    def _yaml_dump(self, yml_repr):
        return yaml.safe_dump(yml_repr)
    
    def _json_dump(self, yml_repr):
        return sys_json.dumps(yml_repr)

    def repr_yml(self, py_repr, **kwargs):
        return py_repr
    
    def repr_py(self, yml_repr, **kwargs):
        return yml_repr

    def to_yaml(self,
                obj,
                to_file=None,
                begin_doc=True,
                append_to_file=False,
                **kwargs):

        yml_str_fmt = self._yaml_doc_fmt(begin_doc)

        yaml_repr = self.repr_yml(obj, to_file=to_file, **kwargs)

        if kwargs.get("_json"):
            yml_str = self._json_dump(yaml_repr)
        else:
            yml_str = yml_str_fmt.format(self._yaml_dump(yaml_repr))

        if to_file is not None:
            file_contents = self._file_format_out(yml_str, **kwargs)
            self._file_write(to_file, file_contents, append_to_file)
        
        return yml_str

    def from_yaml(self,
                  yml_str,
                  **kwargs):
        
        if kwargs.get("from_file"):
            yml_str = self._file_read(yml_str)
            kwargs = {k: v for k,v in kwargs.items() if k != "from_file"}
            yml_str = self._file_format_in(yml_str, **kwargs)

        return self.repr_py(self._yaml_load(yml_str), **kwargs)

class _WrapperYamlSerializer(YamlSerializer):
    def __init__(self, tgt_cls):
        self._tgt_cls = tgt_cls
    
    def repr_py(self, yml_repr, **kwargs):
        py_repr = self._tgt_cls(yml_repr)
        return py_repr

class _MappingYamlSerializer(_WrapperYamlSerializer):
    def repr_yml(self, py_repr, **kwargs):
        yml_repr = {repr_yml(k, **kwargs): repr_yml(v, **kwargs) 
                        for k, v in py_repr.items()}
        return yml_repr

class _SetYamlSerializer(_WrapperYamlSerializer):
    def repr_yml(self, py_repr, **kwargs):
        yml_repr = set(repr_yml(el, **kwargs) for el in py_repr)
        return yml_repr

class _IterableYamlSerializer(_WrapperYamlSerializer):
    def repr_yml(self, py_repr, **kwargs):
        if isinstance(py_repr, str):
            yml_repr = py_repr
        else:
            yml_repr = list(repr_yml(el, **kwargs) for el in py_repr)
        return yml_repr

class _CollectionYamlSerializer(_IterableYamlSerializer):
    pass