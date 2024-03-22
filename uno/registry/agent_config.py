from typing import TYPE_CHECKING
from pathlib import Path
from functools import cached_property

from .versioned import Versioned
from .database_object import OwnableDatabaseObject
from .uvn import Uvn
from .cell import Cell
from .particle import Particle
from .deployment import P2pLinksMap
from .vpn_config import CentralizedVpnConfig
from .dds import UvnTopic
from ..core.wg import WireGuardConfig

class AgentConfig(Versioned, OwnableDatabaseObject):
  PROPERTIES = [
    "registry_id",
    "deployment",
    "root_vpn_config",
    "particles_vpn_config",
    "backbone_vpn_configs",
    "enable_systemd",
    "enable_router",
    "enable_httpd",
    "enable_peers_tester",
  ]
  REQ_PROPERTIES = [
    "registry_id",
  ]
  EQ_PROPERTIES = [
    "owner_id",
    "registry_id"
  ]
  SECRET_PROPERTIES = [
    "root_vpn_config",
  ]
  CACHED_PROPERTIES = [
    "uvn",
  ]
  INITIAL_ENABLE_SYSTEMD = False
  INITIAL_ENABLE_ROUTER = False

  INITIAL_BACKBONE_VPN_CONFIGS = lambda self: []

  DB_TABLE = "agent_configs"
  DB_OWNER = [Uvn, Cell]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = [
    "owner_id",
    "registry_id",
  ]


  @cached_property
  def dds_topics(self) -> dict:
    if isinstance(self.owner, Cell):
      return {
        "writers": [
          UvnTopic.CELL_ID,
        ],

        "readers": {
          UvnTopic.CELL_ID: {},
          UvnTopic.UVN_ID: {},
          UvnTopic.BACKBONE: {},
        }
      }
    elif isinstance(self.owner, Uvn):
      return {
        "writers": [
          UvnTopic.UVN_ID,
          UvnTopic.BACKBONE,
        ],

        "readers": {
          UvnTopic.CELL_ID: {},
        },
      }


  @cached_property
  def uvn(self) -> Uvn:
    if isinstance(self.owner, Uvn):
      return self.owner
    elif isinstance(self.owner, (Cell, Particle)):
      return self.owner.uvn
    else:
      raise NotImplementedError()


  @cached_property
  def cell(self) -> Cell|None:
    if isinstance(self.owner, (Uvn, Particle)):
      return None
    elif isinstance(self.owner, Cell):
      return self.owner
    else:
      raise NotImplementedError()


  @cached_property
  def particle(self) -> Particle|None:
    if isinstance(self.owner, (Uvn, Cell)):
      return None
    elif isinstance(self.owner, Particle):
      return self.owner
    else:
      raise NotImplementedError()


  # def prepare_root_vpn_config(self, val: str | dict | WireGuardConfig) -> WireGuardConfig:
  #   return self.new_child(WireGuardConfig, val)


  # def prepare_deployment(self, val: str | dict | P2pLinksMap) -> P2pLinksMap:
  #   return self.new_child(P2pLinksMap, val)


  # def prepare_particles_vpn_config(self, val: str | dict | CentralizedVpnConfig) -> CentralizedVpnConfig:
  #   return self.new_child(CentralizedVpnConfig, val)


  # def prepare_backbone_vpn_configs(self, val: str | list[dict] | list[WireGuardConfig]) -> list[WireGuardConfig]:
  #   return self.deserialize_collection(WireGuardConfig, val, self.new_child)


