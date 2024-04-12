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

  INITIAL_LAST_DEPLOYED_ON = lambda self: self.first_deployed_on
  INITIAL_DEPLOY_COUNT = 0

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
