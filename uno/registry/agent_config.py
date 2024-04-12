from .versioned import Versioned
from .database_object import OwnableDatabaseObject
from .uvn import Uvn
from .cell import Cell


class AgentConfig(Versioned, OwnableDatabaseObject):
  PROPERTIES = [
    "config_id",
  ]
  REQ_PROPERTIES = [
    "config_id",
  ]
  EQ_PROPERTIES = ["owner_id", "config_id"]
  STR_PROPERTIES = [
    "owner",
    "config_id",
  ]
  DB_TABLE = "agents"
  DB_OWNER = [Uvn, Cell]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = [
    "config_id",
  ]
  DB_EXPORTABLE = True
  DB_IMPORTABLE = False
