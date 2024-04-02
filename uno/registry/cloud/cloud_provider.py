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
from enum import Enum

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

  def prepare_root(self, val: str | Path) -> Path:
    return Path(val)


  def serialize_root(self, val: Path) -> str:
    return str(val)


  def __init_subclass__(cls, *a, **kw) -> None:
    cls_svc_class = cls.svc_class()
    assert(cls_svc_class not in CloudProvider.Plugins)
    CloudProvider.Plugins[cls.svc_class()] = cls
    super().__init_subclass__(*a, **kw)


  def storage(self, **config) -> CloudStorage:
    return self.new_child(self.STORAGE, {
      "root": self.root / "storage",
      **config,
    })


  def email_server(self, **config) -> CloudEmailServer:
    return self.new_child(self.EMAIL_SERVER, {
      "root": self.root / "email",
      **config,
    })


  @classmethod
  def svc_class(cls) -> str:
    cls_name = cls.__qualname__
    cls_name = cls_name[0].lower() + cls_name[1:]
    return Logger.camelcase_to_kebabcase(cls_name)

