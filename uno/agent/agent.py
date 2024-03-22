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
from typing import Iterable, Callable, Mapping
from functools import cached_property

import ipaddress
import sdnotify

from ..registry.uvn import Uvn
from ..registry.cell import Cell
from ..registry.particle import Particle
from ..registry.lan_descriptor import LanDescriptor
from ..registry.nic_descriptor import NicDescriptor
from ..registry.deployment import P2pLinksMap
from ..registry.id_db import IdentityDatabase
from ..registry.agent_config import AgentConfig
from ..registry.versioned import Versioned
from ..registry.package import Packager
from ..registry.registry import Registry
from ..registry.key_id import KeyId
from ..core.render import Templates

from ..core.time import Timestamp
from ..core.exec import exec_command
from ..core.wg import WireGuardInterface
from ..core.ip import (
  ipv4_from_bytes,
  ipv4_get_route,
)
from .dds_data import cell_agent_status
from .dds import DdsParticipant, DdsParticipantConfig, UvnTopic
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer, LanStatus, UvnPeerListener, VpnInterfaceStatus
from .graph import backbone_deployment_graph, cell_agent_status_plot
from .agent_net import AgentNetworking
from .tester import UvnPeersTester
from .router import Router
from .www import UvnHttpd
from .routes_monitor import RoutesMonitor, RoutesMonitorListener


class _AgentSpinner:
  def __init__(self, agent: "Agent") -> None:
    self.agent = agent
  
  def __enter__(self) -> "Agent":
    self.agent._start(boot=True)
    return self.agent

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.agent._stop()



class Agent(Versioned, UvnPeerListener, RoutesMonitorListener):
  @classmethod
  def open(cls, root: Path) -> None:
    registry = Registry.open(root, readonly=True)
    config = registry.assert_agent_config(registry.local_object)
    agent = registry.new_child(Agent, {
      "registry": registry,
      "config": config,
    })
    cls.log.info("loaded agent for {} at {}", agent.registry.local_object, agent.config.registry_id)
    return agent

  PROPERTIES = [
    "registry",
    "config",
    # Track state of plots so we can regenerate them on the fly
    "uvn_backbone_plot_dirty",
    "uvn_status_plot_dirty",
    # Store an updated agent instance upon receiving new configuration
    # then reload it after finishing handling dds data (since reload
    # will cause DDS entities to be deleted)
    "reload_agent",
    "started",
  ]
  REQ_PROPERTIES = [
    "registry",
    "config",
  ]
  INITIAL_UVN_BACKBONE_PLOT_DIRTY = True
  INITIAL_UVN_STATUS_PLOT_DIRTY = True
  INITIAL_STARTED = False

  class Service:
    def start(self) -> None:
      raise NotImplementedError()

    def stop(self) -> None:
      raise NotImplementedError()

  KNOWN_NETWORKS_TABLE_FILENAME = "networks.known"
  LOCAL_NETWORKS_TABLE_FILENAME = "networks.local"
  REACHABLE_NETWORKS_TABLE_FILENAME = "networks.reachable"
  UNREACHABLE_NETWORKS_TABLE_FILENAME = "networks.unreachable"


  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    # self.config = config
    self.dp = DdsParticipant()
    self._started_services = []

    self.routes_monitor = RoutesMonitor(log_dir=self.log_dir)
    self.routes_monitor.listeners.append(self)
    
    # Cached vpn statistics
    self._vpn_stats = None
    self._vpn_stats_update_ts = None
    self._vpn_stats_update = True


  def spin(self,
      until: Callable[[], bool]|None=None,
      max_spin_time: int|None=None) -> None:
    self._spin(until=until, max_spin_time=max_spin_time)


  def spin_until_consistent(self,
      max_spin_time: int|None=None,
      config_only: bool=False) -> None:
    self.log.warning("waiting until agents{} are consistent: {}",
      ' and uvn' if not config_only else '',
      self.registry_id)

    spin_state = {"consistent_config": False}
    def _until_consistent() -> bool:
      if not spin_state["consistent_config"] and self.peers.status_consistent_config_uvn:
        self.log.warning("spinning condition reached: consistent config uvn")
        spin_state["consistent_config"] = True
        if config_only:
          return True
      elif spin_state["consistent_config"] and self.peers.status_fully_routed_uvn:
        self.log.warning("spinning condition reached: fully routed uvn")
        return True
    
    timedout = self.spin(until=_until_consistent, max_spin_time=max_spin_time)
    if timedout:
      raise RuntimeError("UVN failed to reach expected state before timeout")


  def _spin(self,
      until: Callable[[], bool]|None=None,
      max_spin_time: int|None=None) -> None:
    spin_start = Timestamp.now()
    self.log.debug("starting to spin on {}", spin_start)
    while True:
      self._update_vpn_stats()

      done, active_writers, active_readers, active_data, extra_conds = self.dp.wait()
      spin_time = Timestamp.now()
      spin_length = int(spin_time.subtract(spin_start).total_seconds())
      timedout = max_spin_time is not None and spin_length >= max_spin_time
      if timedout:
        self.log.debug("time out after {} sec", max_spin_time)
        # If there is an exit condition, throw an error, since we
        # didn't reach it.
        if until:
          raise RuntimeError("timed out", max_spin_time)

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

      for active_cond in extra_conds:
        active_cond.trigger_value = False
        self._on_user_condition(active_cond)

      # Test custom exit condition after event processing
      if until and until():
        self.log.debug("exit condition reached")
        break

      self._on_spin(
        ts_start=spin_start,
        ts_now=spin_time,
        spin_len=spin_length)


  @property
  def owner(self) -> Uvn|Cell:
    return self.config.owner


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
        local_peer_id=self.peers.local.id)
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
    return self.root / "uno_qos_profiles.xml"


  @property
  def local_object(self) -> Cell|Uvn:
    return self.config.owner


  @property
  def registry_id(self) -> str:
    return self.registry.config_id


  @cached_property
  def deployment(self) -> P2pLinksMap:
    return self.registry.deployment


  @property
  def uvn(self) -> Uvn:
    return self.registry.uvn


  @cached_property
  def root(self) -> Path:
    return self.registry.root


  @cached_property
  def peers(self) -> UvnPeersList:
    return self.local_object.new_child(UvnPeersList, {
      "uvn": self.uvn,
      "registry_id": self.registry_id,
    })


  @cached_property
  def rti_license(self) -> Path:
    return self.root / "rti_license.dat"


  @property
  def dds_config(self) -> DdsParticipantConfig:
    # HACK set NDDSHOME so that the Connext Python API finds the license file
    import os
    os.environ["NDDSHOME"] = str(self.root)

    if isinstance(self.local_object, Uvn):
      self._generate_dds_xml_config_uvn(self.participant_xml_config)
    elif isinstance(self.local_object, Cell):
      self._generate_dds_xml_config_cell(self.participant_xml_config)

    return DdsParticipantConfig(
      participant_xml_config=self.participant_xml_config,
      user_conditions=self.user_conditions,
      **self.config.dds_topics)


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
            if peer_b[0] == 0 or peer_b_id == self.cell.id
    } - {
      vpn.config.intf.address
        for vpn in self.backbone_vpns
    }
    initial_peers = [
      *backbone_peers,
      *([self.root_vpn.config.peers[0].address] if self.root_vpn else []),
    ]
    initial_peers = [f"[0]@{p}" for p in initial_peers]

    key_id = KeyId.from_uvn(self.local_object)
    Templates.generate(output, "dds/uno.xml", {
      "uvn": self.uvn,
      "cell": self.local_object if isinstance(self.local_object, Cell) else None,
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


  @cached_property
  def root_vpn(self) -> WireGuardInterface|None:
    return (
      WireGuardInterface(self.config.root_vpn_config)
      if self.config.root_vpn_config else None
    )


  @cached_property
  def particles_vpn(self) -> WireGuardInterface|None:
    return (
      WireGuardInterface(self.config.particles_vpn_config)
      if self.config.particles_vpn_config else None
    )


  @cached_property
  def backbone_vpns(self) -> list[WireGuardInterface]:
    return (
      WireGuardInterface(cfg)
      for cfg in self.config.backbone_vpn_configs
    )


  @property
  def vpn_interfaces(self) -> set[WireGuardInterface]:
    result = set()
    for vpn in (
        self.root_vpn,
        self.particles_vpn,
        *self.backbone_vpns):
      if vpn is None:
        continue
      result.add(vpn)
    return result


  def lookup_vpn_peer(self, vpn: WireGuardInterface, peer_id: int) -> UvnPeer:
    if vpn == self.root_vpn:
      return self.peers[peer_id]
    elif vpn == self.particles_vpn:
      if peer_id == 0:
        return self.peers.local
      else:
        return next(p for p in self.peers.particles if p.id == peer_id)
    elif vpn in self.backbone_vpns:
      return self.peers[peer_id]
    else:
      raise NotImplementedError()


  @cached_property
  def routes_monitor(self) -> RoutesMonitor:
    routes_monitor = RoutesMonitor(log_dir=self.log_dir)
    routes_monitor.listeners.append(self)
    return routes_monitor


  @cached_property
  def router(self) -> Router|None:
    if not Router.check_enabled(self):
      return None
    return Router(self)


  @cached_property
  def www(self) -> UvnHttpd|None:
    if not UvnHttpd.check_enabled(self):
      return None
    return UvnHttpd(self)


  @cached_property
  def peers_tester(self) -> UvnPeersTester|None:
    if not self.config.enable_peers_tester:
      return None
    return UvnPeersTester(self,
      max_test_delay=self.uvn.settings.timing_profile.tester_max_delay)


  @cached_property
  def net(self) -> AgentNetworking:
    return AgentNetworking(
      config_dir=self.config_dir,
      allowed_lans=self.lans,
      vpn_interfaces=self.vpn_interfaces,
      router=self.router)


  @property
  def bind_addresses(self) -> list[ipaddress.IPv4Address]:
    return [
      *(l.nic.address for l in self.lans),
      *(v.config.intf.address for v in self.vpn_interfaces),
    ]


  @property
  def services(self) -> list[tuple["Agent.Service", dict]]:
    return [
      (self.routes_monitor, {}),
      *([(self.www, {
        "bind_addresses": self.bind_addresses
      })] if self.config.enable_httpd else []),
      *([self.peers_tester, {}] if self.config.enable_peers_tester else []),
    ]


  @property
  def user_conditions(self) -> list[dds.GuardCondition]:
    return [
      self.peers.updated_condition,
      self.routes_monitor.updated_condition,
      *([self.peers_tester.result_available_condition] if self.peers_tester else []),
    ]


  @property
  def id_db(self) -> IdentityDatabase:
    return self.registry.id_db


  @property
  def bind_addresses(self) -> list[ipaddress.IPv4Address]:
    return [
      *(l.nic.address for l in self.lans),
      *(v.config.intf.address for v in self.vpn_interfaces),
    ]


  @property
  def vpn_stats(self) -> Mapping[str, dict]:
    return self._vpn_stats or {
      "interfaces": {},
      "traffic": {
        "rx": 0,
        "tx": 0,
      },
    }


  def _update_vpn_stats(self) -> None:
    if (not self._vpn_stats_update
        and self._vpn_stats_update_ts
        and int(Timestamp.now().subtract(self._vpn_stats_update_ts).total_seconds()) < 2):
      return

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
    self._vpn_stats = {
      "interfaces": intf_stats,
      "traffic": {
        "rx": traffic_rx,
        "tx": traffic_tx,
      },
    }
    peers = {}
    for vpn, vpn_stats in self._vpn_stats["interfaces"].items():
      for peer_id, peer_stats in vpn_stats["peers"].items():
        peer = self.lookup_vpn_peer(vpn, peer_id)
        peer_result = peers[peer] = peers.get(peer, {})
        peer_result[vpn] = peer_stats
    
    for peer, vpn_stats in peers.items():
      # We assume there's only one vpn interface associated with a particle
      online = next(iter(vpn_stats.values()))["online"]
      update_args = {
        "vpn_intefaces": vpn_stats,
        "status": None if not peer.particle else
          UvnPeerStatus.ONLINE if online else
          UvnPeerStatus.OFFLINE if peer.status == UvnPeerStatus.ONLINE else
          UvnPeerStatus.DECLARED
      }
      self.peers.update_peer(peer, **update_args)

    self._vpn_stats_update_ts = Timestamp.now()
    self._vpn_stats_update= False


  @property
  def allowed_lans(self) -> set[ipaddress.IPv4Network]:
    if not isinstance(self.owner, Cell):
      return set()
    return self.owner.allowed_lans


  @property
  def lans(self) -> set[LanDescriptor]:
    def _allowed_nic(nic: NicDescriptor) -> bool:
      for allowed_lan in self.allowed_lans:
        if nic.address in allowed_lan:
          return True
      return False
    if not self.allowed_lans:
      return set()
    return {
      self.new_child(LanDescriptor, {"nic": nic, "gw": gw})
      for nic in NicDescriptor.list_local_networks(self,
        skip=[i.config.intf.name for i in self.vpn_interfaces])
        if _allowed_nic(nic)
        for gw in [ipv4_get_route(nic.subnet.network_address)]
    }


  def _validate_boot_config(self):
    # Check that the agent detected all of the expected networks
    allowed_lans = set(str(net) for net in self.allowed_lans)
    enabled_lans = set(str(lan.nic.subnet) for lan in self.lans)

    if allowed_lans and allowed_lans != enabled_lans:
      self.log.error("failed to detect all of the expected network interfaces:")
      self.log.error("- expected: {}", ', '.join(sorted(allowed_lans)))
      self.log.error("- detected: {}", ', '.join(sorted(enabled_lans)))
      self.log.error("- missing : {}", ', '.join(sorted(allowed_lans - enabled_lans)))
      raise RuntimeError("invalid network interfaces")


  def _reload(self, updated_agent: "Agent") -> None:
    # Copy the agent's database into our own
    pass
    # Reset all cached properties
    self.reset_cached_properties()
    self.peers.reset_cached_properties()
    self.id_db.reset_cached_properties()
    
    # # Trigger all property groups
    # self.updated_property_groups()

    self.uvn_backbone_plot_dirty = True
    self.uvn_status_plot_dirty = True
    self._vpn_stats_update = True
    self._vpn_stats = None


  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    if topic == UvnTopic.CELL_ID:
      self._on_reader_data_cell_info(info, sample)
    elif topic == UvnTopic.UVN_ID:
      self._on_reader_data_uvn_info(info, sample)


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
    peer = self.peers[peer_cell.id]
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
      uvn=self.uvn,
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
        peers=matched_peers,
        query=lambda p: p.status == UvnPeerStatus.OFFLINE,
        status=UvnPeerStatus.ONLINE)



  def _on_spin(self,
      ts_start: Timestamp,
      ts_now: Timestamp,
      spin_len: float) -> None:
    if self._reload_agent:
      reload_agent = self._reload_agent
      self._reload_agent = None
      self.reload(reload_agent)



  def reload(self, updated_agent: "Agent") -> None:
    was_started = self.started
    if was_started:
      self.log.warning("stopping services to load new configuration: {}", updated_agent.registry_id)
      self._stop()
    
    self.log.activity("updating configuration to {}", updated_agent.registry_id)
    self._reload(updated_agent)

    # Copy files from the updated agent's root directory,
    # then rewrite agent configuration
    package_files = list(updated_agent.root.glob("*"))
    if package_files:
      exec_command(["cp", "-rv", *package_files, self.root])
    self.save_to_disk()

    if was_started:
      self.log.activity("restarting services with new configuration: {}", self.registry_id)
      self._start()

    self.log.warning("new configuration loaded: {}", self.registry_id)


  def schedule_reload(self, updated_agent: "Agent") -> None:
    if self._reload_agent:
      self.log.warning("discarding previously scheduled reload: {}", self._reload_agent.registry_id)
    self._reload_agent = updated_agent
    self.log.warning("reload scheduled: {}", self._reload_agent.registry_id)


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
    if gone_cells:
      self.log.error("cells OFFLINE [{}]: {}", len(gone_cells), ', '.join(c.name for c in gone_cells))
    if new_cells:
      self.log.warning("cells ONLINE [{}]: {}", len(new_cells), ', '.join(c.name for c in new_cells))
    # trigger vpn stats update
    self._vpn_stats_update = True


  def on_event_all_cells_connected(self) -> None:
    if not self.peers.status_all_cell_connected:
      self.log.error("lost connection with some cells")
      # self.on_status_all_cells_connected(False)
    else:
      self.log.warning("all cells connected")
    self.uvn_backbone_plot_dirty = True


  def on_event_registry_connected(self) -> None:
    if not self.peers.status_registry_connected:
      self.log.error("lost connection with registry")
    else:
      self.log.warning("registry connected")


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


  def on_event_reachable_networks(self, new_reachable: set[tuple[UvnPeer, LanDescriptor]], gone_reachable: set[tuple[UvnPeer, LanDescriptor]]) -> None:
    if gone_reachable:
      self.log.error("networks UNREACHABLE (remote) [{}]: {}",
        len(gone_reachable),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in gone_reachable))
    if new_reachable:
      self.log.warning("networks REACHABLE (remote) [{}]: {}",
        len(new_reachable),
        ', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in new_reachable))


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
    # if self.router:
    #   self.router.update_state()


  def on_event_vpn_connections(self, new_online: set[VpnInterfaceStatus], gone_online: set[VpnInterfaceStatus]) -> None:
    for vpn in new_online:
      self.log.warning("vpn ON: {} → {}", vpn.parent, vpn.intf.config.intf.name)
    for vpn in gone_online:
      self.log.warning("vpn OFF: {} → {}", vpn.parent, vpn.intf.config.intf.name)


  def _on_user_condition(self, condition: dds.GuardCondition):
    if condition == self.routes_monitor.updated_condition:
      self.routes_monitor.process_updates()
    elif condition == self.peers.updated_condition:
      pass
    elif self.peers_tester is not None and condition == self.peers_tester.result_available_condition:#
      pass


  def start(self) -> _AgentSpinner:
    return _AgentSpinner(self)


  def _start(self, boot: bool=False) -> None:
    if boot:
      self._validate_boot_config()

    if not boot:
      self.net.configure(
        allowed_lans=self.lans,
        vpn_interfaces=self.vpn_interfaces,
        router=self.router)
    self.net.generate_configuration()
    self.net.start()

    self.dp.start(self.dds_config)

    for svc, svc_args in self.services:
      svc.start(**svc_args)
      self._started_services.append(svc)

    self.peers.online(
      registry_id=self.registry_id,
      routed_networks=self.lans,
      ts_start=self.init_ts)

    if boot:
      self.net.uvn_agent.write_pid()

    self._on_started(boot=boot)

    self.started = True

    # Trigger updates on the next spin
    self.dirty= True

    self.log.activity("started")

    # Notify systemd upon boot, if enabled
    if boot and self.config.enable_systemd:
      self.log.debug("notifying systemd")
      notifier = sdnotify.SystemdNotifier()
      notifier.notify("READY=1")
      self.log.debug("systemd notified")


  def _stop(self) -> None:
    self.log.activity("performing shutdown...")
    self.started = False
    errors = []
    try:
      self.peers.offline()
    except Exception as e:
      self.log.error("failed to transition agent to OFFLINE")
      self.log.exception(e)
      errors.append(e)
    try:
      self.dp.stop()
    except Exception as e:
      self.log.error("failed to stop DDS participant:")
      self.log.exception(e)
      errors.append(e)
    for svc in list(self._started_services):
      try:
        svc.stop()
        self._started_services.remove(svc)
      except Exception as e:
        self.log.error("failed to stop service: {}", svc)
        self.log.exception(e)
        errors.append(e)
    try:
      self.net.stop()
    except Exception as e:
      self.log.error("failed to stop network services")
      self.log.exception(e)
      errors.append(e)

    if errors:
      raise RuntimeError("failed to finalize agent", errors)
    self.log.activity("stopped")


  def _on_started(self, boot: bool=False) -> None:
    if isinstance(self.owner, Cell):
      self._write_particle_configurations()
      self._write_cell_info(self.peers.local)


  def _write_particle_configurations(self) -> None:
    if self.particles_dir.is_dir():
      exec_command(["rm", "-rf", self.particles_dir])
    if not isinstance(self.owner, Cell) and not self.particles_vpn:
      return
    for particle_id, particle_client_cfg in self.particles_vpn_config.peer_configs.items():
      particle = self.uvn.particles[particle_id]
      Packager.write_particle_configuration(particle, self.owner, particle_client_cfg, self.particles_dir)


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


  def _write_cell_info(self, peer: UvnPeer) -> None:
    assert(peer.cell is not None)
    sample = cell_agent_status(
      participant=self.dp,
      uvn=peer.uvn,
      cell_id=peer.cell.id,
      registry_id=peer.registry_id,
      ts_start=peer.start_ts,
      lans=peer.routed_networks,
      reachable_networks=[n.lan for n in peer.reachable_networks],
      unreachable_networks=[n.lan for n in peer.unreachable_networks])
    self.dp.writers[UvnTopic.CELL_ID].write(sample)
    self.log.activity("published cell info: {}", peer.cell)


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
    self.net.generate_configuration()
    exec_command(["rm", "-rf", id_db_dir])

    self.log.warning("bootstrap completed: {}@{} [{}]", self.local_object, self.uvn, self.root)


