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
from functools import cached_property

from ..registry.versioned import Versioned, prepare_timestamp
from ..registry.database_object import OwnableDatabaseObject
from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..core.time import Timestamp


class DeployedConfig(Versioned, OwnableDatabaseObject):
  PROPERTIES = [
    "config_id",
    "first_deployed_on",
    "last_deployed_on",
    "deploy_count",
  ]
  REQ_PROPERTIES = [
    "config_id",
    "first_deployed_on",
  ]
  DB_TABLE = "agent_stats_deployed_configs"
  DB_OWNER = [Uvn, Cell]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_ORDER_BY = [
    "first_deployed_on",
    "last_deployed_on",
    "deploy_count",
  ]

  def INITIAL_LAST_DEPLOYED_ON(self) -> Timestamp:
    return self.first_deployed_on

  def INITIAL_DEPLOY_COUNT(self) -> int:
    return 0

  def prepare_first_deployed_on(self, val: str | dict | Timestamp):
    return prepare_timestamp(self.db, val)

  def prepare_last_deployed_on(self, val: str | dict | Timestamp):
    return prepare_timestamp(self.db, val)

  def deployed(self) -> None:
    self.deploy_count += 1
    self.last_deployed_on = Timestamp.now()


class AgentStatistics(Versioned, OwnableDatabaseObject):
  PROPERTIES = []
  REQ_PROPERTIES = []
  EQ_PROPERTIES = []
  STR_PROPERTIES = []

  DB_TABLE = "agents_stats"
  DB_OWNER = [Uvn, Cell]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = []
  DB_EXPORTABLE = True
  DB_IMPORTABLE = False

  def load_nested(self) -> None:
    self.deployed_configs = list(self.load_children(DeployedConfig, owner=self.owner))

  @cached_property
  def deployed_configs(self) -> list[DeployedConfig]:
    pass
