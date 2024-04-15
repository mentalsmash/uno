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
from typing import TYPE_CHECKING
from pathlib import Path
from enum import Enum

from uno.registry.versioned import Versioned

if TYPE_CHECKING:
  from .cloud_provider import CloudProvider


class CloudStorageError(Exception):
  pass


class CloudStorageFileType(Enum):
  UVN_REGISTRY = 0
  CELL_PACKAGE = 1
  CELL_GUIDE = 2
  PARTICLE_PACKAGE = 3

  def mimetype(self) -> str:
    if self == CloudStorageFileType.CELL_PACKAGE:
      return "application/x-xz"
    elif self == CloudStorageFileType.CELL_GUIDE:
      # return "text/markdown"
      return "text/html"
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

  def prepare_root(self, val: str | Path) -> Path:
    return Path(val)

  # def __update_str_repr__(self) -> str:
  #   cls_name = self.log.camelcase_to_kebabcase(CloudStorage.__qualname__)
  #   self._str_repr = f"{cls_name}({self.parent})"

  @property
  def provider(self) -> "CloudProvider":
    from .cloud_provider import CloudProvider

    assert isinstance(self.parent, CloudProvider)
    return self.parent

  def upload(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    raise NotImplementedError()

  def download(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    raise NotImplementedError()
