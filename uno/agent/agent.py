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
import rti.connextdds as dds
from pathlib import Path
from typing import Iterable, Callable, Mapping, Generator, ContextManager
from functools import cached_property
import contextlib
from enum import Enum
import os
import tempfile
import shutil
import signal
import time
import queue

import ipaddress
import sdnotify

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.nic_descriptor import NicDescriptor
from ..registry.deployment import P2pLinksMap
from ..registry.id_db import IdentityDatabase
from ..registry.versioned import disabled_if, error_if, max_rate
from ..registry.package import Packager
from ..registry.registry import Registry
from ..registry.key_id import KeyId
from ..registry.database_object import (
  OwnableDatabaseObject,
  DatabaseObjectOwner,
  inject_db_cursor
)
from ..registry.agent_config import AgentConfig
from ..registry.database import Database

from ..core.render import Templates
from ..core.time import Timestamp
from ..core.exec import exec_command
from ..core.wg import WireGuardInterface
from ..core.ip import (
  ipv4_from_bytes,
  ipv4_get_route,
)

from .dds_data import cell_agent_status, uvn_info, cell_agent_config
from .dds import DdsParticipant, UvnTopic
from .uvn_peers_list import UvnPeersList, UvnPeerListener
from .uvn_peer import UvnPeer, UvnPeerStatus, LanStatus, VpnInterfaceStatus
from .graph import backbone_deployment_graph, cell_agent_status_plot
# from .agent_net import AgentNetworking
from .uvn_net import UvnNet
from .uvn_peers_tester import UvnPeersTester
from .router import Router
from .webui import WebUi
from .routes_monitor import RoutesMonitor, RoutesMonitorListener
from .agent_service import AgentService
from .runnable import Runnable
from .systemd_service import SystemdService
from .agent_static_service import AgentStaticService


class AgentReload(Exception):
  def __init__(self, agent: "Agent | None"=None, *args) -> None:
    self.agent = agent
    super().__init__(*args)


class AgentTimedout(Exception):
  pass


def registry_method(wrapped):
  return disabled_if(lambda self, *a, **kw: not isinstance(self.owner, Uvn))(wrapped)

def cell_method(wrapped):
  return disabled_if(lambda self, *a, **kw: not isinstance(self.owner, Cell))(wrapped)

def registry_exclusive_method(wrapped):
  return error_if(lambda self, *a, **kw: not isinstance(self.owner, Uvn))(wrapped)

def cell_exclusive_method(wrapped):
  return error_if(lambda self, *a, **kw: not isinstance(self.owner, Cell))(wrapped)


class Agent(AgentConfig, Runnable, UvnPeerListener, RoutesMonitorListener, OwnableDatabaseObject, DatabaseObjectOwner):
  class SyncMode(Enum):
    IMMEDIATE = 0
    CONNECTED = 1

  PID_FILE = Path("/run/uno/uno-agent.pid")

  PROPERTIES = [
    "config_id",
    # "participant_xml_config",
    # "peers",
    # "rti_license",
    # "dds_topics",
    # "lans",
    # "root_vpn",
    # "particles_vpn",
    # "backbone_vpns",
    # "dp",
    # "routes_monitor",
    # "router",
    # "webui",
    # "peers_tester",
    # "net",
    # "static_services",
    # "static",
    "uvn_backbone_plot_dirty",
    "uvn_status_plot_dirty",
    "enable_systemd",
    "initial_active_static_services",
  ]
  REQ_PROPERTIES = [
    "config_id",
  ]
  STR_PROPERTIES = [
    "owner",
  ]
  INITIAL_UVN_BACKBONE_PLOT_DIRTY = True
  INITIAL_UVN_STATUS_PLOT_DIRTY = True
  INITIAL_ENABLE_SYSTEMD = False
  INITIAL_SYNC_MODE = SyncMode.IMMEDIATE
  INITIAL_STARTED_SERVICES = lambda self: []
  INITIAL_INITIAL_ACTIVE_STATIC_SERVICES = lambda self: []

  DB_TABLE = "agents"
  DB_OWNER = [Uvn, Cell]
  DB_OWNER_TABLE_COLUMN = "owner_id"
  DB_TABLE_PROPERTIES = [
    "config_id",
    "started",
    "root",
    "uvn_backbone_plot",
    "uvn_status_plot",
  ]
  DB_EXPORTABLE = True
  DB_IMPORTABLE = False

  KNOWN_NETWORKS_TABLE_FILENAME = "networks.known"
  LOCAL_NETWORKS_TABLE_FILENAME = "networks.local"
  REACHABLE_NETWORKS_TABLE_FILENAME = "networks.reachable"
  UNREACHABLE_NETWORKS_TABLE_FILENAME = "networks.unreachable"

  @classmethod
  def open(cls,
      root: Path | None = None,
      **config_args) -> "Agent":
    owner_id, config_id = Registry.load_local_id(root)
    db = Database(root)
    if owner_id is not None:
      owner = db.load_object_id(owner_id)
      agent = next(db.load(Agent,
        owner=owner,
        where="config_id = ?",
        params=(config_id,)))
      assert(agent is not None)
      assert(agent.config_id == config_id)
    else:
      registry = Registry.open(root, db=db)
      agent = db.new(Agent, {
        "config_id": registry.config_id,
      }, owner=registry.uvn, save=False)
      assert(agent is not None)
      assert(agent.config_id == registry.config_id)
    if config_args:
      agent.configure(**config_args)
      if not isinstance(agent.owner, Uvn):
        db.save(agent)
    cls.log.info("loaded agent for {} at {}", agent.owner, agent.config_id)
    return agent


  @classmethod
  def install_package(cls, package: Path, root: Path) -> "Agent":
    Packager.extract_cell_agent_package(package, root)
    agent = cls._assert_agent(root)
    agent._finish_import_id_db_keys()
    cls.log.warning("bootstrap completed: {}@{} [{}]", agent.owner, agent.uvn, agent.root)
    return agent


  @classmethod
  def install_package_from_cloud(cls, uvn: str, cell: str, root: Path, storage_id: str, **storage_config) -> "Agent":
    import tempfile
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)
    cell_package = Registry.import_cell_package_from_cloud(uvn=uvn, cell=cell, root=tmp_dir, storage_id=storage_id, **storage_config)
    return cls.install_package(cell_package, root)


  def _finish_import_id_db_keys(self) -> None:
    id_db_dir = self.root / ".id-import"
    if id_db_dir.is_dir():
      package_files = [
        f.relative_to(id_db_dir)
          for f in id_db_dir.glob("**/*")
      ]
      self.id_db.import_keys(id_db_dir, package_files)
      # self.net.generate_configuration()
      exec_command(["rm", "-rf", id_db_dir])


  @classmethod
  def _assert_agent(cls, root: Path) -> "Agent":
    owner_id, config_id = Registry.load_local_id(root)
    db = Database(root)
    owner = db.load_object_id(owner_id)
    agent = next(db.load(Agent,
      owner=owner,
      where="config_id = ?",
      params=(config_id,)), None)
    if agent is None:
      agent = db.new(Agent, {"config_id": config_id}, owner=owner)
    return agent



  @error_if("started")
  # Reloading of the registry agent is only supported without importing
  # configuration from another agent
  @error_if(lambda self, agent: isinstance(self, Uvn) and agent is not None)
  def reload(self, agent: "Agent | None" = None) -> "Agent":
    if agent is not None:
      # Make sure the owner is the same
      if agent.owner != self.owner:
        raise ValueError("invalid agent owner", agent.owner)
      agent.log.warning("loading new configuration: {}", agent.registry_id)

      # Import database records via SQL
      self.registry.db.import_other(agent.db)

      # Extract the package contents on top of the agent's root.
      # Extract all files in the package except for the database.
      cell_package = Path(agent._reload_package.name)
      Packager.extract_cell_agent_package(cell_package, self.root, exclude=[Database.DB_NAME])
      # Make sure there is a database record for the new config id
      self._assert_agent(self.root)
      # Drop the downloaded cell package (stored in a temp file)
      agent._reload_package = None

    new_agent = Agent.open(self.root,
      enable_systemd=self.enable_systemd,
      initial_active_static_services=self.initial_active_static_services)
    if agent is not None:
      new_agent._finish_import_id_db_keys()
    new_agent.log.warning("loaded new configuration: {}", new_agent.registry_id)
    return new_agent


  def __init__(self, **properties) -> None:
    self._reload_agent = None
    self._reload_package = None
    self.reloading = False
    super().__init__(**properties)


  def load_nested(self) -> None:
    self.initial_active_static_services = [s.name for s in self.active_static_services]


  @cached_property
  def registry(self) -> Registry:
    return Registry.open(db=self.db, readonly=True)


  @cached_property
  @inject_db_cursor
  def local_id(self, cursor: Database.Cursor) -> tuple[Uvn|Cell, str]:
    owner_id, config_id = Registry.load_local_id(self.db.root)
    if config_id is None:
      owner = self.uvn
      config_id = self.config_id
    else:
      owner = self.db.load_object_id(owner_id, cursor=cursor)
    return (owner, config_id)


  @property
  def sync_mode(self) -> SyncMode:
    if self.registry.rekeyed_root_config_id is not None:
      return self.SyncMode.CONNECTED
    else:
      return self.SyncMode.IMMEDIATE


  @property
  def log_dir(self) -> Path:
    log_dir = self.root / "log"
    if not log_dir.is_dir():
      log_dir.mkdir(parents=True)
      # log_dir.chmod(0o755)
    return log_dir


  @property
  def config_dir(self) -> Path:
    return self.root / "static"


  @property
  def particles_dir(self) -> Path:
    return self.root / "particles"


  @property
  def uvn_backbone_plot(self) -> Path:
    plot = self.root / "uvn-backbone.png"
    if not plot.is_file() or self.uvn_backbone_plot_dirty:
      generated = backbone_deployment_graph(
        uvn=self.uvn,
        deployment=self.deployment,
        output_file=plot,
        peers=self.peers,
        local_peer=self.peers.local)
      self.uvn_backbone_plot_dirty = False
      if generated:
        self.log.debug("backbone plot generated: {}", plot)
      else:
        self.log.debug("backbone plot NOT generated")
        if plot.is_file():
          plot.unlink()
    return plot


  @property
  def uvn_status_plot(self) -> Path:
    status_plot = self.root / "uvn-status.png"
    if not status_plot.is_file() or self.uvn_status_plot_dirty:
      cell_agent_status_plot(self, status_plot, seed=self.init_ts.from_epoch())
      self.uvn_status_plot_dirty = False
      self.log.debug("status plot generated: {}", status_plot)
    return status_plot


  @cached_property
  def participant_xml_config(self) -> Path:
    config = self.root / "uno_qos_profiles.xml"
    if isinstance(self.owner, Uvn):
      self._generate_dds_xml_config_uvn(config)
    elif isinstance(self.owner, Cell):
      self._generate_dds_xml_config_cell(config)
    return config


  @property
  def local_object(self) -> Cell|Uvn:
    return self.owner


  @property
  def registry_id(self) -> str:
    return self.registry.config_id


  @property
  def deployment(self) -> P2pLinksMap:
    return self.registry.deployment


  @property
  def uvn(self) -> Uvn:
    return self.registry.uvn


  @property
  def id_db(self) -> IdentityDatabase:
    return self.registry.id_db


  @property
  def root(self) -> Path:
    return self.registry.root


  @cached_property
  def peers(self) -> UvnPeersList:
    peers = self.new_child(UvnPeersList)
    peers.listeners.append(self)
    return peers


  @cached_property
  def rti_license(self) -> Path:
    return self.root / "rti_license.dat"


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


  @property
  def allowed_lans(self) -> Generator[ipaddress.IPv4Network, None, None]:
    if not isinstance(self.owner, Cell):
      return
    for l in self.owner.allowed_lans:
      yield l


  @cached_property
  def lans(self) -> set[LanDescriptor]:
    allowed_lans = set(self.allowed_lans)
    def _allowed_nic(nic: NicDescriptor) -> bool:
      for allowed_lan in allowed_lans:
        if nic.address in allowed_lan:
          return True
      return False
    if not allowed_lans:
      return set()
    lans = []
    local_nics = NicDescriptor.list_local_networks(self,
      skip=[i.config.intf.name for i in self.vpn_interfaces])
    self.log.debug("local network interfaces: {}", local_nics)
    for nic in local_nics:
      if not _allowed_nic(nic):
        self.log.debug("interface not allowed: {}", nic)
        continue
      gw = ipv4_get_route(nic.subnet.network_address)
      lan = self.new_child(LanDescriptor, {"nic": nic, "gw": gw})
      lans.append(lan)
      self.log.info("LAN interface detected: {}", lan)
    return lans


  @property
  def bind_addresses(self) -> Generator[ipaddress.IPv4Address, None, None]:
    for l in self.lans:
      yield l.nic.address
    for v in self.vpn_interfaces:
      yield v.config.intf.address


  @cached_property
  def root_vpn(self) -> WireGuardInterface|None:
    vpn_config = None
    if isinstance(self.owner, Uvn):
      # Use the older, "rekeyed", root vpn configuration if available.
      # The agent will switch to the newer one after cells have received the update.
      if self.registry.vpn_config.rekeyed_root_vpn is not None:
        self.log.warning("loading rekeyed root VPN configuration: {}", self.registry.rekeyed_root_config_id)
        vpn_config = self.registry.vpn_config.rekeyed_root_vpn.root_config
      else:
        vpn_config = self.registry.vpn_config.root_vpn.root_config
    elif self.registry.vpn_config.root_vpn is not None:
      vpn_config = self.registry.vpn_config.root_vpn.peer_config(self.owner.id)
    if vpn_config is None:
      self.log.debug("root VPN disabled")
      return None
    return WireGuardInterface(vpn_config)


  @cached_property
  def particles_vpn(self) -> WireGuardInterface|None:
    vpn_config = None
    if isinstance(self.owner, Cell):
      particles_vpn = self.registry.vpn_config.particles_vpn(self.owner)
      if particles_vpn is not None:
        vpn_config = particles_vpn.root_config
    if vpn_config is None:
      self.log.debug("particles VPN disabled")
      return None
    return WireGuardInterface(vpn_config)


  @cached_property
  def backbone_vpns(self) -> list[WireGuardInterface]:
    configs = []
    if isinstance(self.owner, Cell) and self.registry.vpn_config.backbone_vpn is not None:
      configs = self.registry.vpn_config.backbone_vpn.peer_config(self.owner.id)
    if not configs:
      self.log.debug("backbone VPN disabled")
    return [
      WireGuardInterface(config)
        for config in configs
    ]


  @property
  def vpn_interfaces(self) -> Generator[WireGuardInterface, None, None]:
    for vpn in (
        self.root_vpn,
        self.particles_vpn,
        *self.backbone_vpns):
      if vpn is None:
        continue
      yield vpn


  @property
  def vpn_stats(self) -> Mapping[str, dict]:
    # now = Timestamp.now()
    intf_stats = {
      vpn: vpn.stat()
        for vpn in self.vpn_interfaces
    }
    traffic_rx = sum(peer["transfer"]["recv"]
      for stat in intf_stats.values()
        for peer in stat["peers"].values()
    )
    traffic_tx = sum(peer["transfer"]["send"]
      for stat in intf_stats.values()
        for peer in stat["peers"].values()
    )
    return {
      "interfaces": intf_stats,
      "traffic": {
        "rx": traffic_rx,
        "tx": traffic_tx,
      },
    }
    # self.vpn_stats_update_ts = now
    # return result


  @cached_property
  def dp(self) -> DdsParticipant|None:
    return self.new_service(DdsParticipant)


  @cached_property
  def routes_monitor(self) -> RoutesMonitor|None:
    return self.new_service(RoutesMonitor)


  @cached_property
  def router(self) -> Router|None:
    return self.new_service(Router)


  @cached_property
  def webui(self) -> WebUi|None:
    return self.new_service(WebUi)


  @cached_property
  def peers_tester(self) -> UvnPeersTester|None:
    return self.new_service(UvnPeersTester)


  @cached_property
  def net(self) -> UvnNet|None:
    return self.new_service(UvnNet)


  @property
  def services(self) -> Generator[AgentService, None, None]:
    yield self.dp
    yield self.net
    yield self.routes_monitor
    yield self.router
    yield self.peers_tester
    yield self.webui


  @property
  def iter_static_services(self) -> Generator[AgentStaticService, None, None]:
    prev_svc = None
    for svc in self.services:
      if svc.static is None:
        continue
      if prev_svc is not None:
        svc.static.previous_service = prev_svc
      prev_svc = svc.static
      yield svc.static
    agent_svc = self.static
    agent_svc.previous_service = prev_svc
    yield agent_svc


  @cached_property
  def static_services(self) -> list[AgentStaticService]:
    return list(self.iter_static_services)



  @property
  def active_static_services(self) -> Generator[AgentStaticService, None, None]:
    for svc in self.static_services:
      if not svc.active:
        continue
      yield svc


  @cached_property
  def static(self) -> AgentStaticService:
    return self.new_child(AgentStaticService, {
      "name": "agent",
    })


  def validate(self) -> None:
    # Check that the agent detected all of the expected networks
    allowed_lans = set(str(net) for net in self.allowed_lans)
    enabled_lans = set(str(lan.nic.subnet) for lan in self.lans)

    if allowed_lans and allowed_lans != enabled_lans:
      self.log.error("failed to detect all of the expected network interfaces:")
      self.log.error("- expected: {}", ', '.join(sorted(allowed_lans)))
      self.log.error("- detected: {}", ', '.join(sorted(enabled_lans)))
      self.log.error("- missing : {}", ', '.join(sorted(allowed_lans - enabled_lans)))
      raise RuntimeError("invalid network interfaces")


  # def __enter__(self) -> "Agent":
  #   self.start(boot=True)
  #   return self.agent


  # def __exit__(self, exc_type, exc_val, exc_tb):
  #   self.stop()


  @classmethod
  def stored_pid(cls) -> int | None:
    if not cls.PID_FILE.exists():
      return None
    try:
      agent_pid = int(cls.PID_FILE.read_text().strip())
      return agent_pid
    except Exception as e:
      cls.log.error("failed to read PID file: {}", cls.PID_FILE)
      cls.log.exception(e)
      return None


  @classmethod
  def external_agent_process(cls) -> int | None:
    agent_pid = cls.stored_pid()
    if agent_pid is None:
      return None

    if agent_pid == os.getpid():
      cls.log.debug("current process is the designated system agent")
      return None

    cls.log.debug("possible external agent process detected: {}", agent_pid)
    try:
      os.kill(agent_pid, 0)
      cls.log.debug("external agent process detected: {}", agent_pid)
      return agent_pid
    except OSError:
      cls.log.debug("process {} doesn't exist", agent_pid)
      if cls.PID_FILE.is_file():
        old_pid = cls.PID_FILE.read_text().strip()
        cls.log.warning("clearing stale PID file: {} [{}]", cls.PID_FILE, old_pid)
        cls.delete_pid_file()
      return None


  @classmethod
  def delete_pid_file(cls) -> None:
    try:
      cls.PID_FILE.unlink()
    except Exception as e:
      if cls.PID_FILE.is_file():
        raise e


  @classmethod
  def write_pid_file(cls) -> None:
    cls.PID_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    pid = str(os.getpid())
    cls.PID_FILE.write_text(pid)
    cls.log.activity("PID file [{}]: {}", pid, cls.PID_FILE)


  @contextlib.contextmanager
  def _pid_file(self) -> Generator["Agent", None, None]:
    external_process = self.external_agent_process()
    if external_process is not None:
      self.log.error("another instance of uno agent is already running on this host: {}", external_process)
      raise RuntimeError("agent already running on host", external_process)
    self.write_pid_file()
    try:
      yield self
    finally:
      self.delete_pid_file()
      self.log.info("shutdown complete")


  @contextlib.contextmanager
  def _on_started(self) -> Generator["Agent", None, None]:
    self.peers.online(
      registry_id=self.registry_id,
      routed_networks=self.lans,
      ts_start=self.init_ts)
    if self.enable_systemd:
      # Since the agent was started as a systemd unit, write static marker file
      self.static.write_marker()
      self.log.debug("notifying systemd")
      notifier = sdnotify.SystemdNotifier()
      notifier.notify("READY=1")
      self.log.debug("systemd notified")
    self._write_particle_configurations()
    self._write_cell_info(self.peers.local)
    self._write_uvn_info()
    if self.sync_mode == Agent.SyncMode.IMMEDIATE:
      self._write_agent_configs()
    self.log.warning("started")
    try:
      yield self
    finally:
      self.log.warning("shutting down...")
      self.static.delete_marker()
      self.peers.offline()
      # self._write_cell_info(self.peers.local)
      # self._write_uvn_info()


  @registry_exclusive_method
  def spin_until_consistent(self,
      max_spin_time: int|None=None,
      config_only: bool=False) -> None:
    self.log.info("waiting until agents{} are consistent: {}",
      ' and uvn' if not config_only else '',
      self.registry_id)

    def _until_consistent() -> bool:
      if config_only and self.peers.status_consistent_config_uvn:
        self.log.warning("exit condition reached: consistent config uvn")
        return True
      elif self.peers.status_consistent_config_uvn and self.peers.status_fully_routed_uvn:
        self.log.warning("exit condition reached: consistent config and fully routed uvn")
        return True
      else:
        self.log.debug("waiting for exit condition: consistent_config_uvn={}, fully_routed_uvn={}",
          self.peers.status_consistent_config_uvn, self.peers.status_fully_routed_uvn)
        return False

    rekeyed_state = {
      "stage": 0,
    }
    def _until_rekeyed_config_pushed() -> bool:
      if rekeyed_state["stage"] == 0:
        if self.peers.status_all_cells_connected:
          rekeyed_state["stage"] = 1
        else:
          self.log.debug("waiting to detect all cells ONLINE")
      if rekeyed_state["stage"] == 1:
        offline_cells = set(p.cell for p in self.peers.offline_cells)
        if offline_cells == self.registry.rekeyed_cells:
          # Drop the old key material and reload the agent
          self.log.warning("applying rekeyed configuration: {}", self.registry.config_id)
          self.registry.drop_rekeyed()
          self.db.save(self.registry)
          raise AgentReload()
        self.log.debug(
          "waiting for rekeyed cells to go OFFLINE {}/{}: {} != {}",
          len(offline_cells),
          len(self.registry.rekeyed_cells),
          offline_cells,
          self.registry.rekeyed_cells)
      return False

    if self.registry.rekeyed_root_config_id is not None:
      assert(len(self.registry.rekeyed_cells) > 0)
      self.log.warning(
        "pushing rekeyed configuration to {}/{} cells: {} → {}",
        len(self.registry.rekeyed_cells), len(self.registry.uvn.cells), self.registry.rekeyed_root_config_id, self.registry.config_id)
      condition = _until_rekeyed_config_pushed
    else:
      condition = _until_consistent

    return self.spin(until=condition, max_spin_time=max_spin_time)


  # @registry_exclusive_method
  # def spin_until_rekeyed(self,
  #     max_spin_time: int|None=None,
  #     config_only: bool=False) -> None:
  #   if not self._rekeyed_registry:
  #     raise RuntimeError("no rekeyed registry available")

  #   all_cells = set(c.name for c in self.uvn.cells.values())
    
  #   self.log.warning(
  #     "pushing rekeyed configuration to {} cells: {} → {}",
  #     len(all_cells), self.registry.rekeyed_root_config_id, self.registry.config_id)

  #   state = {
  #     "offline": set(),
  #     "stage": 0,
  #   }
  #   def _on_condition_check() -> bool:
  #     if state["stage"] == 0:
  #       self.log.debug("waiting to detect all cells ONLINE")
  #       if self.peers.status_all_cells_connected:
  #         state["stage"] = 1
  #     elif state["stage"] == 1:
  #       self.log.debug(
  #         "waiting to detect all cells OFFLINE {}/{} {}",
  #         len(state['offline']), len(all_cells), state['offline'])
  #       for p in (p for p in self.peers.cells if p.status == UvnPeerStatus.OFFLINE):
  #         state["offline"].add(p.name)
  #       if state["offline"] == all_cells:
  #         return True
  #     return False
  #   spin_start = Timestamp.now()

  #   self.spin(until=_on_condition_check, max_spin_time=max_spin_time)

  #   self.log.warning("applying rekeyed configuration: {}", self.registry.config_id)
  #   self.registry.drop_rekeyed()

  #   spin_len = Timestamp.now().subtract(spin_start).total_seconds()
  #   max_spin_time -= spin_len
  #   max_spin_time = max(0, max_spin_time)
  #   self.spin_until_consistent(max_spin_time=max_spin_time, config_only=config_only)


  @property
  def running_contexts(self) -> Generator[ContextManager, None, None]:
    yield self._pid_file()
    for svc in self.services:
      yield svc
    yield self._on_started()


  def spin(self,
      until: Callable[[], bool]|None=None,
      max_spin_time: int|None=None) -> None:
    with contextlib.ExitStack() as stack:
      for ctx_mgr in self.running_contexts:
        stack.enter_context(ctx_mgr)
      self._spin(until=until, max_spin_time=max_spin_time)


  def _spin(self,
      until: Callable[[], bool]|None=None,
      max_spin_time: int|None=None) -> None:
    spin_start = Timestamp.now()
    self.log.debug("starting to spin on {}", spin_start)
    while True:
      done, active_writers, active_readers, active_data, extra_conds = self.dp.wait()
      spin_time = Timestamp.now()
      spin_length = int(spin_time.subtract(spin_start).total_seconds())
      timedout = max_spin_time is not None and spin_length >= max_spin_time
      if timedout:
        self.log.debug("time out after {} sec", max_spin_time)
        # If there is an exit condition, throw an error, since we
        # didn't reach it.
        if until:
          raise AgentTimedout("timed out", max_spin_time)

      done = done or timedout
      if done:
        self.log.debug("done spinning")
        break

      for topic, writer in active_writers:
        # Read and reset status flags
        # We don't do anything with writer events for now
        status_mask = writer.status_changes
        pub_matched = writer.publication_matched_status
        liv_lost = writer.liveliness_lost_status
        qos_error = writer.offered_incompatible_qos_status


      for topic, reader in active_readers:
        # Read and reset status flags
        status_mask = reader.status_changes
        sub_matched = reader.subscription_matched_status
        liv_changed = reader.liveliness_changed_status
        qos_error = reader.requested_incompatible_qos_status

        if ((dds.StatusMask.LIVELINESS_CHANGED in status_mask
            or dds.StatusMask.SUBSCRIPTION_MATCHED in status_mask)):
          self._on_reader_status(topic, reader)

      for topic, reader, query_cond in active_data:
        for s in reader.select().condition(query_cond).take():
          if s.info.valid:
            self._on_reader_data(topic, reader, s.info, s.data)
          elif (s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_DISPOSED
                or s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_NO_WRITERS):
            self._on_reader_offline(topic, reader, s.info)

      for user_cond in extra_conds:
        if user_cond == self.peers_tester.updated_condition:
          # TODO(asorbini) do something with the updated result
          continue
        svc = next((s for s in self.services if s.updated_condition == user_cond), None)
        if svc is not None:
          svc.process_updates()
          continue

      # Test custom exit condition after event processing
      if until and until():
        self.log.debug("exit condition reached")
        break

      self._update_peer_vpn_stats()

      for svc in self.services:
        svc.spin_once()

      if self._reload_agent:
        new_agent = self._reload_agent
        self._reload_agent = None
        self.reloading = True
        raise AgentReload(new_agent)
      
      # now = Timestamp.now()
      # if (not self.vpn_stats_update_ts
      #     and int(now.subtract(self.vpn_stats_update_ts).total_seconds()) > 2):
      #   self.updated_property("vpn_stats")

  @max_rate(2)
  def _update_peer_vpn_stats(self) -> None:
    peers = {}
    for vpn, vpn_stats in self.vpn_stats["interfaces"].items():
      for peer_id, peer_stats in vpn_stats["peers"].items():
        peer = self.lookup_vpn_peer(vpn, peer_id)
        peer_result = peers[peer] = peers.get(peer, {})
        peer_result[vpn] = peer_stats

    for peer, vpn_stats in peers.items():
      # We assume there's only one vpn interface associated with a particle
      online = next(iter(vpn_stats.values()))["online"]
      # updated_status = (
      #   None if not peer.particle else
      #   UvnPeerStatus.ONLINE if online else
      #   UvnPeerStatus.OFFLINE if peer.status == UvnPeerStatus.OFFLINE else
      #   None
      # )
      # if updated_status is not None:
      #   self.peers.update_peer(peer, {"status": updated_status})
      update_args = {
        "vpn_interfaces": vpn_stats,
        "status": None if not peer.particle else
          UvnPeerStatus.ONLINE if online else
          UvnPeerStatus.OFFLINE if peer.status == UvnPeerStatus.OFFLINE else
          None #UvnPeerStatus.DECLARED
      }
      self.peers.update_peer(peer, **update_args)


  def _generate_dds_xml_config_uvn(self, output: Path) -> None:
    initial_peers = [p.address for p in self.root_vpn.config.peers]
    initial_peers = [f"[0]@{p}" for p in initial_peers]

    key_id = KeyId.from_uvn(self.registry.uvn)
    Templates.generate(output, "dds/uno.xml", {
      "uvn": self.registry.uvn,
      "cell": None,
      "initial_peers": initial_peers,
      "timing": self.registry.uvn.settings.timing_profile,
      "license_file": self.registry.rti_license.read_text(),
      "ca_cert": self.id_db.backend.ca.cert,
      "perm_ca_cert": self.id_db.backend.perm_ca.cert,
      "cert": self.id_db.backend.cert(key_id),
      "key": self.id_db.backend.key(key_id),
      "governance": self.id_db.backend.governance,
      "permissions": self.id_db.backend.permissions(key_id),
      "enable_dds_security": self.uvn.settings.enable_dds_security,
      "domain": self.uvn.settings.dds_domain,
      "domain_tag": self.uvn.name,
    })
  

  def _generate_dds_xml_config_cell(self, output: Path) -> None:
    # Pick the address of the first backbone port for every peer
    # and all addresses for peers connected directly to this one
    backbone_peers = {
      peer_b[1]
        for peer_a in self.deployment.peers.values()
          for peer_b_id, peer_b in peer_a["peers"].items()
            if peer_b[0] == 0 or peer_b_id == self.owner.id
    } - {
      vpn.config.intf.address
        for vpn in self.backbone_vpns
    }
    initial_peers = [
      *backbone_peers,
      *([self.root_vpn.config.peers[0].address] if self.root_vpn else []),
    ]
    initial_peers = [f"[0]@{p}" for p in initial_peers]

    key_id = KeyId.from_uvn(self.owner)
    Templates.generate(output, "dds/uno.xml", {
      "uvn": self.uvn,
      "cell": self.owner if isinstance(self.owner, Cell) else None,
      "initial_peers": initial_peers,
      "timing": self.uvn.settings.timing_profile,
      "license_file": self.rti_license.read_text(),
      "ca_cert": self.id_db.backend.ca.cert,
      "perm_ca_cert": self.id_db.backend.perm_ca.cert,
      "cert": self.id_db.backend.cert(key_id),
      "key": self.id_db.backend.key(key_id),
      "governance": self.id_db.backend.governance,
      "permissions": self.id_db.backend.permissions(key_id),
      "enable_dds_security": self.uvn.settings.enable_dds_security,
      "domain": self.uvn.settings.dds_domain,
      "domain_tag": self.uvn.name,
    })


  def lookup_vpn_peer(self, vpn: WireGuardInterface, peer_id: int) -> UvnPeer:
    if vpn == self.root_vpn:
      return self.peers[peer_id]
    elif vpn == self.particles_vpn:
      if peer_id == 0:
        return self.peers.local
      else:
        return next(p for p in self.peers.particles if p.owner.id == peer_id)
    elif vpn in self.backbone_vpns:
      return self.peers[peer_id]
    else:
      raise NotImplementedError()


  def new_service(self, svc_cls: type[AgentService], **properties) -> AgentService|None:
    svc = self.new_child(svc_cls, **properties)
    svc.listeners.append(self)
    return svc


  def _on_agent_config_received(self, package: bytes) -> None:
    try:
      # Cache received data to file and trigger handling
      tmp_file_h = tempfile.NamedTemporaryFile()
      tmp_file = Path(tmp_file_h.name)
      with tmp_file.open("wb") as output:
        output.write(package)
      # decoded_package_h = tempfile.NamedTemporaryFile()
      # decoded_package = Path(decoded_package_h.name)

      # # Decode package contents
      # key = self.id_db.backend[self.owner]
      # self.registry.id_db.backend.decrypt_file(key, tmp_file, decoded_package)

      cell_package = tmp_file
      cell_package_h = tmp_file_h

      tmp_dir_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_dir_h.name)

      self.log.info("extracting received package: {}", cell_package)
      updated_agent = Agent.install_package(cell_package, tmp_dir)
      updated_agent._reload_package = cell_package_h
    except Exception as e:
      self.log.error("failed to load updated agent")
      self.log.exception(e)
      return

    if updated_agent.config_id == self.config_id:
      self.log.activity("ignoring unchanged configuration: {}", updated_agent.config_id)
      return
    self.log.warning("new agent configuration available: {}", updated_agent.registry_id)
    self._reload_agent = updated_agent


  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    if topic == UvnTopic.CELL_ID:
      self._on_reader_data_cell_info(info, sample)
    elif topic == UvnTopic.UVN_ID:
      self._on_reader_data_uvn_info(info, sample)
    elif topic == UvnTopic.BACKBONE:
      if sample["registry_id"] == self.config_id:
        self.log.debug("ignoring current configuration: {}", self.config_id)
      else:
        self._on_agent_config_received(sample["package"])


  def _on_reader_data_cell_info(
      self,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    peer_uvn = sample["id.uvn"]
    if peer_uvn != self.uvn.name:
      self.log.debug("ignoring update from foreign agent: uvn={}, cell={}",
        sample['id.uvn'], sample['id.n'])
      return

    peer_cell_id = sample["id.n"]
    peer_cell = self.uvn.cells.get(peer_cell_id)
    if peer_cell is None:
      # Ignore sample from unknown cell
      self.log.warning("ignoring update from unknown agent: uvn={}, cell={}",
        sample['id.uvn'], sample['id.n'])
      return

    self.log.info("cell info UPDATE: {}", peer_cell)
    peer = self.peers[peer_cell]

    def _site_to_descriptor(site):
      subnet_addr = ipv4_from_bytes(site["subnet.address.value"])
      subnet_mask = site["subnet.mask"]
      subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
      endpoint = ipv4_from_bytes(site["endpoint.value"])
      gw = ipv4_from_bytes(site["gw.value"])
      nic = site["nic"]
      return {
        "nic": {
          "name": nic,
          "address": endpoint,
          "subnet": subnet,
        },
        "gw": gw,
      }
  
    def _site_to_lan_status(site, reachable):
      return {
        # "lan": _site_to_descriptor(site),
        "lan": peer.new_child(LanDescriptor, _site_to_descriptor(site), save=False),
        "reachable": reachable,
      }

    known_networks = [
      *(_site_to_lan_status(s, False) for s in sample["unreachable_networks"]),
      *(_site_to_lan_status(s, True) for s in sample["reachable_networks"]),
    ]
    self.peers.update_peer(peer,
      registry_id=sample["registry_id"],
      status=UvnPeerStatus.ONLINE,
      routed_networks=[_site_to_descriptor(s) for s in sample["routed_networks"]],
      known_networks=known_networks,
      ih=info.instance_handle,
      ih_dw=info.publication_handle,
      ts_start=sample["ts_start"])


  def _on_reader_data_uvn_info(self,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> UvnPeer | None:
    peer_uvn = sample["name"]
    if peer_uvn != self.uvn.name:
      self.log.warning("ignoring update for foreign UVN: uvn={}", sample['name'])
      return None

    self.log.info("uvn info UPDATE: {}", self.uvn)
    self.peers.update_peer(self.peers.registry,
      status=UvnPeerStatus.ONLINE,
      # uvn=self.uvn,
      registry_id=sample["registry_id"],
      ih=info.instance_handle,
      ih_dw=info.publication_handle)


  def _on_reader_offline(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo) -> None:
    if topic in (UvnTopic.CELL_ID, UvnTopic.UVN_ID):
      try:
        peer = self.peers[info.instance_handle]
      except KeyError:
        return
      self.log.debug("peer writer offline: {}", peer)
      self.peers.update_peer(peer,
        status=UvnPeerStatus.OFFLINE)


  def _on_reader_status(self, topic: UvnTopic, reader: dds.DataReader) -> None:
    if topic not in (UvnTopic.CELL_ID, UvnTopic.UVN_ID):
      return

    # Check go through the list of matched writers and assert
    # their associated peer statuses
    matched_writers = reader.matched_publications
    matched_peers = []
    if topic == UvnTopic.CELL_ID:
      matched_peers = [p for p in self.peers if p.ih_dw and p.ih_dw in matched_writers]
    elif topic == UvnTopic.UVN_ID:
      root_peer = self.peers.registry
      matched_peers = [root_peer] if root_peer.ih_dw and root_peer.ih_dw in matched_writers else []
    
    # Mark peers that we already discovered in the past as active again
    # They had transitioned because of a received sample, but the sample
    # might not be sent again. Don't transition peers we've never seen.
    if matched_peers:
      self.log.activity("marking {} peers on matched publications: {}",
        len(matched_peers), list(map(str, matched_peers)))
      self.peers.update_all(
        peers=(p for p in matched_peers if p.status == UvnPeerStatus.OFFLINE),
        status=UvnPeerStatus.ONLINE)


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
    if gone_cells:
      self.log.warning("cells OFFLINE [{}]: {}", len(gone_cells), [c.name for c in gone_cells])
    if new_cells:
      self.log.warning("cells ONLINE [{}]: {}", len(new_cells), [c.name for c in new_cells])
    # # trigger vpn stats update
    # self.updated_property("vpn_stats")
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()
    # Trigger peers tester
    self.peers_tester.trigger()


  def on_event_online_particles(self, new_particles: set[UvnPeer], gone_particles: set[UvnPeer]) -> None:
    if gone_particles:
      self.log.warning("particles OFFLINE [{}]: {}", len(gone_particles), [p.name for p in gone_particles])
    if new_particles:
      self.log.warning("particles ONLINE [{}]: {}", len(new_particles), [p.name for p in new_particles])
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_all_cells_connected(self) -> None:
    if not self.peers.status_all_cells_connected:
      offline_cells = sorted(self.peers.offline_cells, key=lambda c: c.name)
      self.log.error("lost connection with {} cells: {}", len(offline_cells), [c.name for c in offline_cells])
      # self.on_status_all_cells_connected(False)
    else:
      online_cells = sorted(self.peers.online_cells, key=lambda c: c.name)
      self.log.warning("all {} cells connected: {}", len(online_cells), [c.name for c in online_cells])
    self.uvn_backbone_plot_dirty = True
    if (self.sync_mode == self.SyncMode.CONNECTED
        and self.peers.status_all_cells_connected):
      self._write_agent_configs()
    # Update UI
    self.webui.request_update()


  def on_event_registry_connected(self) -> None:
    if not self.peers.status_registry_connected:
      self.log.warning("registry disconnected")
    else:
      self.log.warning("registry connected")
    # # trigger vpn stats update
    # self.updated_property("vpn_stats")
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_routed_networks(self, new_routed: set[LanDescriptor], gone_routed: set[LanDescriptor]) -> None:
    if gone_routed:
      self.log.warning("networks DETACHED [{}]: {}", len(gone_routed), sorted(f"{peer} → {lan}" for peer, lan in gone_routed))
    if new_routed:
      self.log.info("networks ATTACHED [{}]: {}", len(new_routed), sorted(f"{peer} → {lan}" for peer, lan in new_routed))

    self._write_known_networks_file()
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()
    # Trigger peers tester
    self.peers_tester.trigger()


  def on_event_routed_networks_discovered(self) -> None:
    if not self.peers.status_routed_networks_discovered:
      self.log.error("some networks were DETACHED from {}", self.uvn)
    else:
      routed_networks = sorted(((c, l) for c in self.peers.cells for l in c.routed_networks),
        key=lambda v: (v[0].id, v[1].nic.name, v[1].nic.subnet))
      self.log.warning("all {} networks ATTACHED to {}: {}", len(routed_networks), self.uvn,
        sorted(f"{c.name} → {l.nic.subnet}" for c, l in routed_networks))
    # Update UI
    self.webui.request_update()


  def on_event_consistent_config_cells(self, new_consistent: set[UvnPeer], gone_consistent: set[UvnPeer]) -> None:
    if gone_consistent:
      self.log.warning("{} cells have INCONSISTENT configuration: {}",
        len(gone_consistent), [c.name for c in gone_consistent])
    if new_consistent:
      self.log.info("{} cells have CONSISTENT configuration: {}",
        len(new_consistent), [c.name for c in new_consistent])
    # Update UI
    self.webui.request_update()


  def on_event_consistent_config_uvn(self) -> None:
    if not self.peers.status_consistent_config_uvn:
      inconsistent_cells = sorted(self.peers.inconsistent_config_cells, key=lambda c: c.name)
      self.log.error("at least {} cells have inconsistent configuration: {}", len(inconsistent_cells), inconsistent_cells)
    else:
      self.log.warning("all {} cells have consistent configuration: {}", len(self.registry.uvn.cells), self.registry_id)
      self.uvn.log_deployment(deployment=self.deployment)
    # Update UI
    self.webui.request_update()


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    total_routed = sum(1 for c in self.uvn.cells.values() for n in c.allowed_lans)

    if gone_reachable:
      self.log.error("networks UNREACHABLE (local) [{}/{}]: {}",
        len(gone_reachable), total_routed,
        sorted(str(status.lan.nic.subnet) for status in gone_reachable))
    if new_reachable:
      self.log.warning("networks REACHABLE (local) [{}/{}]: {}",
        len(new_reachable), total_routed,
        sorted(str(status.lan.nic.subnet) for status in new_reachable))
    self._write_reachable_networks_files()
    self._write_cell_info(self.peers.local)
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_reachable_networks(self, new_reachable: set[tuple[UvnPeer, LanDescriptor]], gone_reachable: set[tuple[UvnPeer, LanDescriptor]]) -> None:
    total_routed = sum(1 for c in self.uvn.cells.values() for n in c.allowed_lans)
    other_cells = list(self.peers.other_cells)
    total_reachable = total_routed * len(other_cells)
    if gone_reachable:
      self.log.error("networks UNREACHABLE (remote) [{}/{}]: {}",
        len(gone_reachable), total_reachable,
        sorted(f"{status.owner.name} → {status.lan.nic.subnet}" for status in gone_reachable))
    if new_reachable:
      self.log.warning("networks REACHABLE (remote) [{}/{}]: {}",
        len(new_reachable), total_reachable,
        sorted(f"{status.owner.name} → {status.lan.nic.subnet}" for status in new_reachable))
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()
    # Trigger peers tester
    self.peers_tester.trigger()


  def on_event_fully_routed_uvn(self) -> None:
    if not self.peers.status_fully_routed_uvn:
      self.log.error("{} is not fully routed", self.uvn)
    else:
      routed_networks = sorted(
        {(c, l) for c in self.peers.cells for l in c.routed_networks},
        key=lambda n: (n[0].id, n[1].nic.name, n[1].nic.subnet))
      self.log.warning("{} networks REACHABLE from {} cells in {}: {}",
        len(routed_networks), len(self.uvn.cells), self.uvn,
        sorted(f"{c.name} → {l.nic.subnet}" for c, l in routed_networks))
    # Update UI
    self.webui.request_update()


  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    for r in new_routes:
      self.log.warning("route ADD: {}", r)
    for r in gone_routes:
      self.log.warning("route DEL: {}", r)
    # Trigger peers tester
    self.peers_tester.trigger()
    # Update UI
    self.webui.request_update()


  def on_event_vpn_connections(self, new_online: set[VpnInterfaceStatus], gone_online: set[VpnInterfaceStatus]) -> None:
    for vpn in new_online:
      self.log.warning("vpn ON: {}", vpn)
    for vpn in gone_online:
      self.log.warning("vpn OFF: {}", vpn)
    # Update UI
    self.webui.request_update()


  @cell_method
  def _write_reachable_networks_files(self) -> None:
    def _write_output(output_file: Path, statuses: Iterable[LanStatus]) -> None:
      if not statuses:
        output_file.write_text("")
        return
      with output_file.open("w") as output:
        for status in statuses:
          if status.lan in local_lans:
            continue
          output.writelines(" ".join([
              f"{status.lan.nic.subnet.network_address}/{status.lan.nic.netmask}",
              str(local_lan.nic.address),
              # str(peer_status.lan.gw),
              "\n"
            ]) for local_lan in local_lans)

    local_lans = sorted(self.lans, key=lambda v: (v.nic.name, v.nic.subnet))
    output_file: Path = self.log_dir / self.REACHABLE_NETWORKS_TABLE_FILENAME
    _write_output(output_file,
      sorted(self.peers.local.reachable_networks,
        key=lambda v: (v.lan.nic.name, v.lan.nic.subnet)))
    output_file: Path = self.log_dir / self.UNREACHABLE_NETWORKS_TABLE_FILENAME
    _write_output(output_file,
      sorted(self.peers.local.unreachable_networks,
        key=lambda v: (v.lan.nic.name, v.lan.nic.subnet)))


  @cell_method
  def _write_known_networks_file(self) -> None:
    # Write peer status to file
    lans = sorted(self.lans, key=lambda v: (v.nic.name, v.nic.subnet))
    def _write_output(output_file: Path, sites: Iterable[LanDescriptor]) -> None:
      with output_file.open("w") as output:
        for site in sites:
          output.writelines(" ".join([
              f"{site.nic.subnet.network_address}/{site.nic.netmask}",
              str(lan.nic.address),
              "\n"
            ]) for lan in lans)
    output_file= self.log_dir / self.KNOWN_NETWORKS_TABLE_FILENAME
    _write_output(output_file,
      sorted((net for peer in self.peers for net in peer.routed_networks if net not in lans),
        key=lambda s: (s.nic.name, s.nic.subnet)))
    output_file= self.log_dir / self.LOCAL_NETWORKS_TABLE_FILENAME
    _write_output(output_file, lans)


  @registry_method
  def _write_uvn_info(self) -> None:
    sample = uvn_info(
      participant=self.dp,
      uvn=self.uvn,
      registry_id=self.registry_id)
    self.dp.writers[UvnTopic.UVN_ID].write(sample)
    self.log.activity("published uvn info: {}", self.uvn.name)


  @registry_method
  def _write_agent_configs(self, target_cells: list[Cell]|None=None):
    cells_dir = self.registry.root / "cells"
    for cell in self.uvn.cells.values():
      if target_cells is not None and cell not in target_cells:
        continue
      cell_package_name = Packager.cell_archive_file(cell)
      cell_package = cells_dir / cell_package_name

      # tmp_dir_h = tempfile.TemporaryDirectory()
      # enc_package = Path(tmp_dir_h.name) / f"{cell_package.name}.enc"
      # key = self.id_db.backend[cell]
      # print("PACKAGE SIZE", cell, exec_command([f"ls -l {cell_package}"], shell=True, capture_output=True).stdout.decode())
      # self.registry.id_db.backend.encrypt_file(key, cell_package, enc_package)
      # print("ENCODED PACKAGE SIZE", cell, exec_command([f"ls -l {enc_package}"], shell=True, capture_output=True).stdout.decode())
      # print("ENCODED PACKAGE CONTENTS", cell, exec_command([f"cat {enc_package}"], shell=True, capture_output=True).stdout.decode())
      # dec_package = Path(tmp_dir_h.name) / f"{cell_package.name}.enc.dec"
      # self.registry.id_db.backend.decrypt_file(key, enc_package, dec_package)
      # print("DECODED PACKAGE SIZE", cell, exec_command([f"ls -l {dec_package}"], shell=True, capture_output=True).stdout.decode())
      sample = cell_agent_config(
        participant=self.dp,
        uvn=self.uvn,
        cell_id=cell.id,
        registry_id=self.registry_id,
        package=cell_package)
      self.dp.writers[UvnTopic.BACKBONE].write(sample)
      self.log.activity("published agent configuration: {}", cell)


  @cell_method
  def _write_cell_info(self, peer: UvnPeer) -> None:
    assert(peer.cell is not None)
    reachable = [n.lan for n in peer.reachable_networks]
    unreachable = [n.lan for n in peer.unreachable_networks]
    # self.log.error("REACHABLE: {}", reachable)
    # self.log.error("UNREACHABLE: {}", unreachable)
    sample = cell_agent_status(
      participant=self.dp,
      uvn=peer.uvn,
      cell_id=peer.cell.id,
      registry_id=peer.registry_id,
      ts_start=peer.init_ts,
      lans=peer.routed_networks,
      reachable_networks=reachable,
      unreachable_networks=unreachable)
    self.dp.writers[UvnTopic.CELL_ID].write(sample)
    self.log.activity("published cell info: {}", peer.cell)


  @cell_method
  def _write_particle_configurations(self) -> None:
    if self.particles_dir.is_dir():
      shutil.rmtree(self.particles_dir)
    particles_vpn_config = self.registry.vpn_config.particles_vpn(self.owner)
    if not particles_vpn_config:
      return
    for particle in self.registry.uvn.particles.values():
    # for particle_id, particle_client_cfg in particles_vpn_config.peer_configs.items():
      particle_client_cfg = particles_vpn_config.peer_config(particle.id)
      particle = self.uvn.particles[particle.id]
      Packager.write_particle_configuration(
        particle, self.owner, particle_client_cfg, self.particles_dir)


  def find_backbone_peer_by_address(self, addr: str | ipaddress.IPv4Address) -> UvnPeer|None:
    addr = ipaddress.ip_address(addr)
    for vpn in self.backbone_vpns:
      if vpn.config.peers[0].address == addr:
        return self.peers[vpn.config.peers[0].id]
      elif vpn.config.intf.address == addr:
        return self.peers.local
    return None



  def start_static_services(self, up_to: str | None = None) -> None:
    if up_to is None:
      up_to = self.router.static.name
    tgt_svc = next((s for s in self.static_services if s.name == up_to), None)
    if tgt_svc is None:
      raise ValueError("unknown target service", up_to)
    highest_running = next(reversed(list(self.active_static_services)), None)
    if highest_running is not None:
      highest_running_i = self.static_services.index(highest_running)
      tgt_svc_i = self.static_services.index(tgt_svc)
      if highest_running_i >= tgt_svc_i:
        self.log.warning("service and all services below it already started: {}", tgt_svc)
        return
    self.log.debug("starting static services up to {}", tgt_svc)
    started = []
    try:
      for svc in self.static_services:
        svc.up()
        started.insert(0, svc)
        if svc == tgt_svc:
          break
    except:
      # Roll back changes and tear down services started so far
      for svc in started:
        try:
          svc.down()
        except Exception as svc_e:
          self.log.error("failed to tear down service: {}", svc.name)
          self.log.exception(svc_e)
      raise


  def stop_static_services(self, down_to: str | None = None, cleanup: bool=False) -> None:
    if down_to is None:
      down_to = self.net.static.name
    tgt_svc = next((s for s in self.static_services if s.name == down_to), None)
    if tgt_svc is None:
      raise ValueError("unknown target service", down_to)
    # highest_running = next(reversed(list(self.active_static_services)), None)
    # if highest_running is not None:
    #   highest_running_i = self.static_services.index(highest_running)
    #   tgt_svc_i = self.static_services.index(tgt_svc)
    #   if highest_running_i < tgt_svc_i:
    #     self.log.warning("service and all services above it already stopped: {}", tgt_svc)
    #     if not cleanup:
    #       return
    # if highest_running_i:
    #   self.log.activity("stopping static services down to {}", tgt_svc)
    # else:
    #   self.log.warning("no services detected, performing clean up")
    errors = []
    for svc in reversed(self.static_services):
      try:
        svc.down()
      except Exception as svc_e:
        self.log.error("failed to tear down service: {}", svc.name)
        self.log.exception(svc_e)
        errors.append(svc_e)
      if svc == tgt_svc:
        break
    if errors:
      raise RuntimeError("errors while stopping services", errors)


  def start_static(self) -> None:
    agent_pid = self.external_agent_process()
    if agent_pid is not None:
      self.log.warning("agent daemon already running: {}", agent_pid)
      return
    # Start agent as a separate process
    import subprocess
    verbosity_level = (
      5 if self.log.level >= self.log.Level.tracedbg else
      4 if self.log.level >= self.log.Level.trace else
      3 if self.log.level >= self.log.Level.debug else
      2 if self.log.level >= self.log.Level.activity else
      1 if self.log.level >= self.log.Level.info else
      0
    )
    agent_cmd = [
      self.static.uno_bin, "agent",
        "--systemd",
        "-r", self.root,
        *(["-" + ("v"*verbosity_level)] if verbosity_level > 0 else []),
    ]
    self.log.warning("starting agent daemon: {}", " ".join(map(str, agent_cmd)))
    agent_process = subprocess.Popen(agent_cmd,
      start_new_session=True,
      stdin=subprocess.DEVNULL)
    self.log.warning("agent daemon started: {}", agent_process.pid)

    # self.enable_systemd = True
    # self.spin()


  def stop_static(self) -> None:
    agent_pid = self.external_agent_process()
    if agent_pid is None:
      self.log.info("no agent detected")
      return
    try:
      max_wait = 30
      ts_start = Timestamp.now()
      self.log.warning("stopping agent daemon: {}", agent_pid)
      os.kill(agent_pid, signal.SIGINT)
      while True:
        external_agent = self.external_agent_process()
        if external_agent is None:
          break
        if Timestamp.now().subtract(ts_start).total_seconds() >= max_wait:
          raise RuntimeError(f"the agent failed to exit in {max_wait} seconds")
        time.sleep(1)
      self.log.warning("agent daemon stopped: {}", agent_pid)
    except Exception as e:
      raise RuntimeError("failed to terminate agent process: {}", agent_pid)

    
  # def _restore_static_services(self, services: list[str]) -> None:
  #   self.log.warning("restoring systemd services: {}", services)
  #   for svc in self.static_services:
  #     if svc.name not in services:
  #       continue
  #     if svc.current_marker is not None:
  #       self.log.warning("service still active: {}", svc.name)
  #       continue
  #     svc.up()

