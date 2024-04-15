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
from enum import Enum


class UvnTopic(Enum):
  UVN_ID = "uno/uvn"
  CELL_ID = "uno/cell"
  BACKBONE = "uno/config"

  @classmethod
  def parse(cls, topic_name: str) -> "UvnTopic":
    for val in (v for v in dir(cls) if v[0] != "_"):
      if val.value == topic_name:
        return val
    raise KeyError(topic_name)
