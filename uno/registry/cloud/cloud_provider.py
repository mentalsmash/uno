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
from pathlib import Path

from uno.core.log import Logger
from uno.registry.versioned import Versioned

from .cloud_storage import CloudStorage
from .cloud_email_server import CloudEmailServer


class CloudProviderError(Exception):
  pass


class CloudProvider(Versioned):
  Plugins: dict[str, type["CloudProvider"]] = {}

  STORAGE: type[CloudStorage] = None
  EMAIL_SERVER: type[CloudEmailServer] = None

  PROPERTIES = [
    "root",
  ]
  REQ_PROPERTIES = [
    "root",
  ]
  DB_TABLE = "cloud_plugins"
  DB_EXPORTABLE = False
  DB_IMPORTABLE = False

  def prepare_root(self, val: str | Path) -> Path:
    return Path(val)

  def serialize_root(self, val: Path) -> str:
    return str(val)

  def __init_subclass__(cls, *a, **kw) -> None:
    cls_svc_class = cls.svc_class()
    assert cls_svc_class not in CloudProvider.Plugins
    CloudProvider.Plugins[cls.svc_class()] = cls
    super().__init_subclass__(*a, **kw)

  def __update_str_repr__(self) -> str:
    cls_name = Logger.camelcase_to_kebabcase(CloudProvider.__qualname__)
    self._str_repr = f"{cls_name}({self.svc_class()})"

  def storage(self, **config) -> CloudStorage:
    return self.new_child(
      self.STORAGE,
      {
        "root": self.root / "storage",
        **config,
      },
      save=False,
    )

  def email_server(self, **config) -> CloudEmailServer:
    return self.new_child(
      self.EMAIL_SERVER,
      {
        "root": self.root / "email",
        **config,
      },
      save=False,
    )

  @classmethod
  def svc_class(cls) -> str:
    cls_name = cls.__qualname__
    cls_name = cls_name[0].lower() + cls_name[1:]
    return Logger.camelcase_to_kebabcase(cls_name)
