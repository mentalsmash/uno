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

from uno.registry.versioned import Versioned

if TYPE_CHECKING:
  from .cloud_provider import CloudProvider


class CloudEmailServer(Versioned):
  PROPERTIES = [
    "root",
  ]
  REQ_PROPERTIES = [
    "root",
  ]

  def prepare_root(self, val: str | Path) -> Path:
    return Path(val)

  # def __update_str_repr__(self) -> str:
  #   cls_name = self.log.camelcase_to_kebabcase(CloudEmailServer.__qualname__)
  #   self._str_repr = f"{cls_name}({self.parent})"

  @property
  def provider(self) -> "CloudProvider":
    from .cloud_provider import CloudProvider

    assert isinstance(self.parent, CloudProvider)
    return self.parent

  def send(self, sender: str, to: list[str], subject: str, body: str) -> None:
    raise NotImplementedError()
