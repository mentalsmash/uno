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


class CloudStorageError(Exception):
  pass


class CloudStorageFileType(Enum):
  UVN_REGISTRY = 0
  CELL_PACKAGE = 1
  PARTICLE_PACKAGE = 2

  def mimetype(self) -> str:
    if self == CloudStorageFileType.CELL_PACKAGE:
      return "application/x-xz"
    elif self == CloudStorageFileType.PARTICLE_PACKAGE:
      return "application/zip"
    else:
      raise NotImplementedError()


class CloudStorageFile:
  def __init__(
    self,
    type: CloudStorageFileType,
    name: str,
    local_path: Path | None = None,
    remote_url: str | None = None,
  ) -> None:
    self.type = type
    self.name = name
    self.local_path = local_path
    self.remote_url = remote_url

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, CloudStorageFile):
      return False
    return self.type == other.type and self.name == other.name

  def __hash__(self) -> int:
    return hash((self.type, self.name))

  def __str__(self) -> str:
    return f"{self.type.name.lower()}({self.name})"


class CloudStorage(Versioned):
  RegisteredPlugins: dict[str, type["CloudStorage"]] = {}

  PROPERTIES = [
    "root",
  ]
  REQ_PROPERTIES = [
    "root",
  ]
  DB_TABLE = "cloud_storage_plugins"

  def prepare_root(self, val: str | Path) -> Path:
    return Path(val)

  def __init_subclass__(cls, *a, **kw) -> None:
    cls_svc_class = cls.svc_class()
    assert cls_svc_class not in CloudStorage.RegisteredPlugins
    CloudStorage.RegisteredPlugins[cls.svc_class()] = cls
    super().__init_subclass__(*a, **kw)

  # def connect(self) -> None:
  #   raise NotImplementedError()

  # def disconnect(self) -> None:
  #   raise NotImplementedError()

  def upload(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    raise NotImplementedError()

  def download(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    raise NotImplementedError()

  @classmethod
  def svc_class(cls) -> str:
    cls_name = cls.__qualname__
    cls_name = cls_name[0].lower() + cls_name[1:]
    return Logger.camelcase_to_kebabcase(cls_name)
