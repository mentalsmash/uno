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
from .tester import UvnPeersTester
from .router import Router
from .webui import WebUi
from .routes_monitor import RoutesMonitor, RoutesMonitorListener
from .agent_service import AgentService
from .runnable import Runnable


class AgentReload(Exception):
  def __init__(self, agent: "Agent", *args) -> None:
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

  PID_FILE = Path("/run/uno/uvn-agent.pid")

  PROPERTIES = [
    "config_id",
    "uvn_backbone_plot_dirty",
    "uvn_status_plot_dirty",
    "enable_systemd",
    # "vpn_stats_update_ts",
  ]
  REQ_PROPERTIES = [
    "config_id",
  ]
  STR_PROPERTIES = [
    "owner_id",
  ]
  CACHED_PROPERTIES = [
    # "vpn_stats",
    # "peers"
    
    # "rti_license",
    # "dds_topics",
    # "participant_xml_config",
    # "allowed_lans",
    # "lans",
    # "bind_addresses",
    # "root_vpn",
    # "particles_vpn",
    # "backbone_vpns",
    # "dp",
    # "routes_monitor",
    # "router",
    # "webui",
    # "peers_tester",
    # "net",
  ]
  INITIAL_UVN_BACKBONE_PLOT_DIRTY = True
  INITIAL_UVN_STATUS_PLOT_DIRTY = True
  INITIAL_ENABLE_SYSTEMD = False
  # INITIAL_STARTED = False
  INITIAL_SYNC_MODE = SyncMode.IMMEDIATE
  INITIAL_STARTED_SERVICES = lambda self: []
  # INITIAL_PID_FILE = DEFAULT_PID_FILE

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

  KNOWN_NETWORKS_TABLE_FILENAME = "networks.known"
  LOCAL_NETWORKS_TABLE_FILENAME = "networks.local"
  REACHABLE_NETWORKS_TABLE_FILENAME = "networks.reachable"
  UNREACHABLE_NETWORKS_TABLE_FILENAME = "networks.unreachable"

  @classmethod
  def open(cls, root: Path|None=None, registry: Registry|None=None) -> None:
    if registry is None:
      registry = Registry.open(root, readonly=True)
    owner, config_id = registry.local_id
    assert(config_id == registry.config_id)
    # agent_cfg = registry.agent_configs[owner.id]
    # agent_cfg = self.new_child(AgentConfig, {
    #     "config_id": self.config_id,
    #   }, owner=cell)
    agent = registry.load_child(Agent,
      owner=owner,
      where="config_id = ?",
      params=(registry.config_id,))
    if agent is None:
      agent = registry.new_child(Agent, {
        "config_id": registry.config_id,
      }, owner=owner)
    assert(agent is not None)
    assert(agent.config_id == config_id)

    # if agent is None:
    #   agent = registry.new_child(Agent, {
    #     "config_id": config_id,
    #   }, owner=owner)
    cls.log.info("loaded agent for {} at {}", agent.owner, agent.config_id)
    return agent


  @cell_exclusive_method
  @error_if("started")
  def reload(self, new_agent: "Agent") -> "Agent":
    # Make sure the owner is the same
    if new_agent.owner != self.owner:
      raise ValueError("invalid agent owner", new_agent.owner)
    self.registry.import_cell_database(new_agent.db, new_agent.owner)
    return Agent.open(self.root)


  def __init__(self, **properties) -> None:
    self._reload_agent = None
    self.updated_services = queue.Queue()
    super().__init__(**properties)
    self._finish_import_package()

  @property
  def registry(self) -> Registry:
    return self.parent


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
    return self.new_child(UvnPeersList)


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
    return {
      self.new_child(LanDescriptor, {"nic": nic, "gw": gw})
      for nic in NicDescriptor.list_local_networks(self,
        skip=[i.config.intf.name for i in self.vpn_interfaces])
        if _allowed_nic(nic)
        for gw in [ipv4_get_route(nic.subnet.network_address)]
    }


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
      if self.registry.vpn_config.rekeyed_root_vpn is not None:
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
      vpn_config = self.registry.vpn_config.particles_vpn(self.owner).root_config
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
  def running_contexts(self) -> Generator[ContextManager, None, None]:
    yield self._pid_file()
    for svc in self.services:
      yield svc
    yield self._on_started()


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


  def __enter__(self) -> "Agent":
    self.start(boot=True)
    return self.agent


  def __exit__(self, exc_type, exc_val, exc_tb):
    self.stop()


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
      cls.log.warning("external agent process detected: {}", agent_pid)
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
    self.write_pid_file()
    try:
      yield self
    finally:
      self.delete_pid_file()


  @contextlib.contextmanager
  def _on_started(self) -> Generator["Agent", None, None]:
    self.peers.online(
      registry_id=self.registry_id,
      routed_networks=self.lans,
      ts_start=self.init_ts)
    if self.enable_systemd:
      self.log.debug("notifying systemd")
      notifier = sdnotify.SystemdNotifier()
      notifier.notify("READY=1")
      self.log.debug("systemd notified")
    self._write_particle_configurations()
    self._write_cell_info(self.peers.local)
    self._write_uvn_info()
    if self.sync_mode == Agent.SyncMode.IMMEDIATE:
      self._write_agent_configs()
    try:
      yield self
    finally:
      self.peers.offline()


  @registry_exclusive_method
  def spin_until_consistent(self,
      max_spin_time: int|None=None,
      config_only: bool=False) -> None:
    self.log.info("waiting until agents{} are consistent: {}",
      ' and uvn' if not config_only else '',
      self.registry_id)
    spin_state = {"consistent_config": False}
    def _until_consistent() -> bool:
      if not spin_state["consistent_config"] and self.peers.status_consistent_config_uvn:
        self.log.info("spinning condition reached: consistent config uvn")
        spin_state["consistent_config"] = True
        if config_only:
          return True
      elif spin_state["consistent_config"] and self.peers.status_fully_routed_uvn:
        self.log.info("spinning condition reached: fully routed uvn")
        return True
    return self.spin(until=_until_consistent, max_spin_time=max_spin_time)


  @registry_exclusive_method
  def spin_until_rekeyed(self,
      max_spin_time: int|None=None,
      config_only: bool=False) -> None:
    if not self._rekeyed_registry:
      raise RuntimeError("no rekeyed registry available")

    all_cells = set(c.name for c in self.uvn.cells.values())
    
    self.log.warning(
      "pushing rekeyed configuration to {} cells: {} → {}",
      len(all_cells), self.registry.rekeyed_root_config_id, self.registry.config_id)

    state = {
      "offline": set(),
      "stage": 0,
    }
    def _on_condition_check() -> bool:
      if state["stage"] == 0:
        self.log.debug("waiting to detect all cells ONLINE")
        if self.peers.status_all_cell_connected:
          state["stage"] = 1
      elif state["stage"] == 1:
        self.log.debug(
          "waiting to detect all cells OFFLINE {}/{} {}",
          len(state['offline']), len(all_cells), state['offline'])
        for p in (p for p in self.peers.cells if p.status == UvnPeerStatus.OFFLINE):
          state["offline"].add(p.name)
        if state["offline"] == all_cells:
          return True
      return False
    spin_start = Timestamp.now()

    self.spin(until=_on_condition_check, max_spin_time=max_spin_time)

    self.log.warning("applying rekeyed configuration: {}", self.registry.config_id)
    self.registry.drop_rekeyed()

    spin_len = Timestamp.now().subtract(spin_start).total_seconds()
    max_spin_time -= spin_len
    max_spin_time = max(0, max_spin_time)
    self.spin_until_consistent(max_spin_time=max_spin_time, config_only=config_only)


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

      try:
        while True:
          svc = self.updated_services.get_nowait()
          svc.process_updates()
      except queue.Empty:
        pass

      # Test custom exit condition after event processing
      if until and until():
        self.log.debug("exit condition reached")
        break

      self._update_peer_vpn_stats()

      for svc in self.services:
        svc.spin_once()

      if self._reload_agent:
        self._reload_agent = None
        raise AgentReload(self._reload_agent)
      
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

      tmp_dir_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_dir_h.name)

      self.log.activity("extracting received package: {}", tmp_file)
      Packager.extract_cell_agent_package(tmp_file, tmp_dir)
      updated_agent = Agent.open(tmp_dir)
    except Exception as e:
      self.log.error("failed to load updated agent")
      self.log.exception(e)

    if updated_agent.config_id == self.config_id:
      self.log.activity("ignoring unchanged configuration: {}", updated_agent.config_id)
      return

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
        "lan": _site_to_descriptor(site),
        "reachable": reachable,
      }

    self.log.activity("cell info UPDATE: {}", peer_cell)
    peer = self.peers[peer_cell]
    self.peers.update_peer(peer,
      registry_id=sample["registry_id"],
      status=UvnPeerStatus.ONLINE,
      routed_networks=[_site_to_descriptor(s) for s in sample["routed_networks"]],
      known_networks=[
        *(_site_to_lan_status(s, True) for s in sample["reachable_networks"]),
        *(_site_to_lan_status(s, False) for s in sample["unreachable_networks"]),
      ],
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

    self.log.debug("uvn info UPDATE: {}", self.uvn)
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


  # def reload(self, updated_agent: "Agent") -> None:
  #   was_started = self.started
  #   if was_started:
  #     self.log.warning("stopping services to load new configuration: {}", updated_agent.registry_id)
  #     self._stop()
    
  #   self.log.activity("updating configuration to {}", updated_agent.registry_id)
  #   self._reload(updated_agent)

  #   # Copy files from the updated agent's root directory,
  #   # then rewrite agent configuration
  #   package_files = list(updated_agent.root.glob("*"))
  #   if package_files:
  #     exec_command(["cp", "-rv", *package_files, self.root])
  #   self.save_to_disk()

  #   if was_started:
  #     self.log.activity("restarting services with new configuration: {}", self.registry_id)
  #     self._start()

  #   self.log.warning("new configuration loaded: {}", self.registry_id)


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
    if gone_cells:
      self.log.error("cells OFFLINE [{}]: {}", len(gone_cells), ', '.join(c.name for c in gone_cells))
    if new_cells:
      self.log.warning("cells ONLINE [{}]: {}", len(new_cells), ', '.join(c.name for c in new_cells))
    # # trigger vpn stats update
    # self.updated_property("vpn_stats")
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_all_cells_connected(self) -> None:
    if not self.peers.status_all_cell_connected:
      self.log.error("lost connection with some cells")
      # self.on_status_all_cells_connected(False)
    else:
      self.log.warning("all cells connected")
    self.uvn_backbone_plot_dirty = True
    if (self.sync_mode == self.SyncMode.CONNECTED
        and self.peers.status_all_cell_connected):
      self._write_agent_configs()


  def on_event_registry_connected(self) -> None:
    if not self.peers.status_registry_connected:
      self.log.error("lost connection with registry")
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
      self.log.error("networks  DETACHED [{}]: {}",
        len(gone_routed),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in gone_routed))
    if new_routed:
      self.log.warning("networks ATTACHED [{}]: {}",
        len(new_routed),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in new_routed))

    self._write_known_networks_file()
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()
    # Trigger peers tester
    self.peers_tester.trigger_service()


  def on_event_routed_networks_discovered(self) -> None:
    if not self.peers.status_routed_networks_discovered:
      self.log.error("some networks were DETACHED from uvn {}", self.uvn)
    else:
      routed_networks = sorted(((c, l) for c in self.peers.cells for l in c.routed_networks),
        key=lambda v: (v[0].id, v[1].nic.name, v[1].nic.subnet))
      self.log.warning("all {} networks ATTACHED to uvn {}", len(routed_networks), self.uvn)
      for c, l in routed_networks:
        self.log.warning("- {} → {}", c.name, l.nic.subnet)


  def on_event_consistent_config_cells(self, new_consistent: set[UvnPeer], gone_consistent: set[UvnPeer]) -> None:
    if gone_consistent:
      self.log.error("{} cells have INCONSISTENT configuration: {}",
        len(gone_consistent),
        ', '.join(c.name for c in gone_consistent))
    if new_consistent:
      self.log.activity("{} cells have CONSISTENT configuration: {}",
        len(new_consistent),
        ', '.join(c.name for c in new_consistent))


  def on_event_consistent_config_uvn(self) -> None:
    if not self.peers.status_consistent_config_uvn:
      self.log.error("some cells have inconsistent configuration:")
      for cell in (c for c in self.peers.cells if c.registry_id != self.registry_id):
        self.log.error("- {}: {}", cell, cell.registry_id)
    else:
      self.log.warning("all cells have consistent configuration: {}", self.registry_id)
      self.uvn.log_deployment(deployment=self.deployment)


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    if gone_reachable:
      self.log.error("networks UNREACHABLE (local) [{}]: {}",
        len(gone_reachable),
        ', '.join(str(n.nic.subnet) for n in gone_reachable))
    if new_reachable:
      self.log.warning("networks REACHABLE (local) [{}]: {}",
        len(new_reachable),
        ', '.join(str(n.nic.subnet) for n in new_reachable))
    self._write_reachable_networks_files()
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_reachable_networks(self, new_reachable: set[tuple[UvnPeer, LanDescriptor]], gone_reachable: set[tuple[UvnPeer, LanDescriptor]]) -> None:
    if gone_reachable:
      self.log.error("networks UNREACHABLE (remote) [{}]: {}",
        len(gone_reachable),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in gone_reachable))
    if new_reachable:
      self.log.warning("networks REACHABLE (remote) [{}]: {}",
        len(new_reachable),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in new_reachable))
    # Update status plot
    self.uvn_status_plot_dirty = True
    # Update UI
    self.webui.request_update()


  def on_event_fully_routed_uvn(self) -> None:
    if not self.peers.status_fully_routed_uvn:
      self.log.error("uvn {} is not fully routed:", self.uvn)
      for cell in (c for c in self.peers.cells if c.unreachable_networks):
        self.log.error("- {} → {}", cell, ', '.join(map(str, cell.unreachable_networks)))
    else:
      routed_networks = sorted(
        {(c, l) for c in self.peers.cells for l in c.routed_networks},
        key=lambda n: (n[0].id, n[1].nic.name, n[1].nic.subnet))
      self.log.warning("{} networks REACHABLE from {} cells in uvn {}:",
        len(routed_networks), len(self.uvn.cells), self.uvn)
      for c, l in routed_networks:
        self.log.warning("- {} → {}", c, l.nic.subnet)


  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    for r in new_routes:
      self.log.warning("route ADD: {}", r)
    for r in gone_routes:
      self.log.warning("route DEL: {}", r)
    # Trigger peers tester
    self.peers_tester.trigger_service()
    # Update UI
    self.webui.request_update()


  def on_event_vpn_connections(self, new_online: set[VpnInterfaceStatus], gone_online: set[VpnInterfaceStatus]) -> None:
    for vpn in new_online:
      self.log.warning("vpn ON: {} → {}", vpn.parent, vpn.intf.config.intf.name)
    for vpn in gone_online:
      self.log.warning("vpn OFF: {} → {}", vpn.parent, vpn.intf.config.intf.name)
    # Update UI
    self.webui.request_update()


  @cell_method
  def _write_reachable_networks_files(self) -> None:
    def _write_output(output_file: Path, lans: Iterable[LanDescriptor]) -> None:
      if not lans:
        output_file.write_text("")
        return
      with output_file.open("w") as output:
        for lan in lans:
          if lan in local_lans:
            continue
          output.writelines(" ".join([
              f"{lan.nic.subnet.network_address}/{lan.nic.netmask}",
              str(local_lan.nic.address),
              # str(peer_status.lan.gw),
              "\n"
            ]) for local_lan in local_lans)

    local_lans = sorted(self.lans, key=lambda v: (v.nic.name, v.nic.subnet))
    output_file: Path = self.log_dir / self.REACHABLE_NETWORKS_TABLE_FILENAME
    _write_output(output_file,
      sorted(self.peers.local.reachable_networks,
        key=lambda v: (v.nic.name, v.nic.subnet)))
    output_file: Path = self.log_dir / self.UNREACHABLE_NETWORKS_TABLE_FILENAME
    _write_output(output_file,
      sorted(self.peers.local.unreachable_networks,
        key=lambda v: (v.nic.name, v.nic.subnet)))


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
      cell_package = cells_dir / f"{self.uvn.name}__{cell.name}.uvn-agent"
      tmp_dir_h = tempfile.TemporaryDirectory()
      enc_package = Path(tmp_dir_h.name) / f"{cell_package.name}.enc"
      key = self.id_db.backend[cell]
      self.registry.id_db.backend.encrypt_file(key, cell_package, enc_package)
      sample = cell_agent_config(
        participant=self.dp,
        uvn=self.uvn,
        cell_id=cell.id,
        registry_id=self.registry_id,
        package=enc_package)
      self.dp.writers[UvnTopic.BACKBONE].write(sample)
      self.log.activity("published agent configuration: {}", cell)


  @cell_method
  def _write_cell_info(self, peer: UvnPeer) -> None:
    assert(peer.cell is not None)
    sample = cell_agent_status(
      participant=self.dp,
      uvn=peer.uvn,
      cell_id=peer.cell.id,
      registry_id=peer.registry_id,
      ts_start=peer.init_ts,
      lans=peer.routed_networks,
      reachable_networks=[n.lan for n in peer.reachable_networks],
      unreachable_networks=[n.lan for n in peer.unreachable_networks])
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



  def _finish_import_package(self) -> None:
    id_db_dir = self.root / ".id-import"
    if not id_db_dir.is_dir():
      return

    # Load the imported agent
    self.log.activity("loading imported agent")

    package_files = [
      f.relative_to(id_db_dir)
        for f in id_db_dir.glob("**/*")
    ]
    self.id_db.import_keys(id_db_dir, package_files)
    # self.net.generate_configuration()
    exec_command(["rm", "-rf", id_db_dir])

    self.log.debug("bootstrap completed: {}@{} [{}]", self.owner, self.uvn, self.root)


