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
from typing import Mapping, Sequence, Iterable, Optional, Tuple, Callable
import time
import ipaddress
import sdnotify

from .uvn_id import UvnId
from .wg import WireGuardInterface
from .ip import (
  LanDescriptor,
)
from .dds import DdsParticipant, DdsParticipantConfig, UvnTopic
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer
from .vpn_config import P2PLinksMap
from .time import Timestamp
from .graph import backbone_deployment_graph
from .agent_net import AgentNetworking
from .router import Router
from . import agent_run as Runner

from .log import Logger as log

class Agent:
  def __init__(self) -> None:
    self.create_ts = int(time.time())
    self.dp = DdsParticipant()
    self.started = False
    self.dirty = True
    self._discovery_completed = False
    self._registry_connected = False
    self._routed_sites = set()
    self._uvn_backbone_plot_dirty = True
    self._uvn_consistent_config = False
    self._uvn_consistent = False
    # Only enable Systemd support on request
    self.enable_systemd = False


  def spin(self,
      until: Optional[Callable[[], bool]]=None,
      max_spin_time: Optional[int]=None) -> None:
    try:
      self._start(boot=True)
      Runner.spin(
        dp=self.dp,
        peers=self.peers,
        until=until,
        max_spin_time=max_spin_time,
        on_reader_data=self._on_reader_data,
        on_reader_offline=self._on_reader_offline,
        on_spin=self._on_spin,
        on_user_condition=self._on_user_condition,
        on_peer_updated=self._on_peer_updated)
    finally:
      self._stop(exiting=True)


  def spin_until_consistent(self,
      max_spin_time: Optional[int]=None,
      config_only: bool=False) -> None:
    spin_state = {
      "consistent_config": False
    }
    def _until_consistent() -> bool:
      if not spin_state["consistent_config"] and self.uvn_consistent_config:
        spin_state["consistent_config"] = True
        if config_only:
          return True
      if self.uvn_consistent:
        return True
      if not spin_state["consistent_config"]:
        log.debug(f"[AGENT] at configuration [{len(self.consistent_config_peers)}/{len(self.uvn_id.cells)}]: {list(map(str, self.inconsistent_config_peers))}")
        log.debug(f"[AGENT] not configured yet [{len(self.inconsistent_config_peers)}/{len(self.uvn_id.cells)}]: {list(map(str, self.inconsistent_config_peers))}")
      else:
        log.debug(f"[AGENT] still waiting for UVN to become consistent")
    
    timedout = self.spin(until=_until_consistent, max_spin_time=max_spin_time)
    if timedout:
      raise RuntimeError("UVN failed to reach expected state before timeout")


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
  def discovery_completed(self) -> bool:
    return self._discovery_completed


  @discovery_completed.setter
  def discovery_completed(self, val: bool) -> None:
    prev = self._discovery_completed
    self._discovery_completed = val
    if prev != val:
      if val:
        online_peers = list(self.peers.online_peers)
        log.warning(f"[AGENT] all {len(online_peers)} UVN agents are online: {[str(p) for p in online_peers]}")
      else:
        offline_peers = list(p for p in self.peers.offline_peers if not p.local)
        if offline_peers:
          log.error(f"[AGENT] lost connection with {len(offline_peers)} UVN agents: {[str(p) for p in offline_peers]}")

      self.dirty = True

      self._on_discovery_completed_status(completed=val)


  @property
  def registry_connected(self) -> bool:
    return self._registry_connected


  @registry_connected.setter
  def registry_connected(self, val: bool) -> None:
    prev = self._registry_connected
    self._registry_connected = val
    if not prev and val:
      log.warning(f"[AGENT] UVN registry connection detected")
    elif prev and not val:
      log.error(f"[AGENT] lost connection to UVN registry")
    
    if prev != val:
      self.dirty = True



  @property
  def expected_subnets(self) -> set[ipaddress.IPv4Network]:
    return {n for c in self.uvn_id.cells.values() for n in c.allowed_lans}


  @property
  def routed_sites(self) -> set[LanDescriptor]:
    return self._routed_sites


  @property
  def routed_subnets(self) -> set[LanDescriptor]:
    return {s.nic.subnet for s in self._routed_sites}


  @routed_sites.setter
  def routed_sites(self, val: Iterable[LanDescriptor]) -> None:
    prev = self._routed_sites
    self._routed_sites = set(val)

    # Don't update state if the agen't isn't active
    if not self.started:
      return

    new_sites = self._routed_sites - prev
    for s in new_sites:
      log.activity(f"[AGENT] ATTACHED network: {s} gw {s.gw}")

    gone_sites = prev - self._routed_sites
    for s in gone_sites:
      log.activity(f"[AGENT] DETACHED network: {s} gw {s.gw}")

    if new_sites or gone_sites:
      self.dirty = True
      self._on_routed_sites_status(new_sites, gone_sites)


  @property
  def uvn_consistent_config(self) -> bool:
    return self._uvn_consistent_config


  @uvn_consistent_config.setter
  def uvn_consistent_config(self, val: bool) -> bool:
    prev = self._uvn_consistent_config
    self._uvn_consistent_config = val
    if prev != val:
      if val:
        log.warning(f"[AGENT] all {len(self.consistent_config_peers)} UVN agents have consistent configuration:")
        self.uvn_id.log_deployment(deployment=self.deployment)
      else:
        inconsitent = self.inconsistent_config_peers
        log.error(f"[AGENT] {len(inconsitent)} agents have inconsistent configuration: {list(map(str, inconsitent))}")
      
      self.dirty = True


  @property
  def consistent_config_peers(self) -> set[UvnPeer]:
    return set(
      p for p in self.peers
        # Mark peers as consistent if they are at the expected configuration IDs
        if p.cell
          and p.registry_id == self.registry_id
          # and p.deployment_id == self.deployment.generation_ts
          # and p.root_vpn_id == self.registry.root_vpn_config.peer_configs[p.id].generation_ts
          # and p.particles_vpn_id == self.registry.particles_vpn_configs[p.id].generation_ts
          # and next((cfg_id for i, cfg_id in enumerate(p.backbone_vpn_ids)
          #     if cfg_id != self.registry.backbone_vpn_config.peer_configs[p.id][i].generation_ts), None) is None
    )
  


  @property
  def inconsistent_config_peers(self) -> set[UvnPeer]:
    return set(p for p in self.peers if p.cell) - self.consistent_config_peers


  @property
  def connected_peers(self) -> set[UvnPeer]:
    return {
      p for p in self.peers if p.cell and p.reachable_subnets == self.expected_subnets
    }


  @property
  def disconnected_peers(self) -> set[UvnPeer]:
    return set(p for p in self.peers if p.cell) - self.connected_peers


  @property
  def uvn_consistent(self) -> bool:
    return self._uvn_consistent


  @uvn_consistent.setter
  def uvn_consistent(self, val: bool) -> bool:
    prev = self._uvn_consistent
    self._uvn_consistent = val
    if prev != val:
      if val:
        peers = self.connected_peers
        log.warning(f"[AGENT] UVN has reached consistency in all {len(peers)}/{len(self.uvn_id.cells)} cells:")
        for s in self.routed_sites:
          log.warning(f"[AGENT] - {s}")
      else:
        disconnected = self.disconnected_peers
        log.error(f"[AGENT] UVN has lost consistency in at least {len(disconnected)}/{len(self.uvn_id.cells)} cells: {list(map(str, disconnected))}")
      
      self.dirty = True


  @property
  def uvn_backbone_plot(self) -> Path:
    plot = self.www.root / "uvn-backbone.png"
    if not plot.is_file() or self._uvn_backbone_plot_dirty:
      generated = backbone_deployment_graph(
        uvn_id=self.uvn_id,
        deployment=self.deployment,
        output_file=plot,
        peers=self.peers,
        local_peer_id=self.peers.local_peer.id)
      self._uvn_backbone_plot_dirty = False
      if generated:
        log.debug(f"[AGENT] backbone plot generated: {plot}")
      else:
        log.debug(f"[AGENT] backbone plot NOT generated")
    return plot


  @property
  def registry_id(self) -> str:
    raise NotImplementedError()


  @property
  def deployment(self) -> P2PLinksMap:
    raise NotImplementedError()


  @property
  def uvn_id(self) -> UvnId:
    raise NotImplementedError()


  @property
  def root(self) -> Path:
    raise NotImplementedError()


  @property
  def peers(self) -> UvnPeersList:
    raise NotImplementedError()


  @property
  def dds_config(self) -> DdsParticipantConfig:
    raise NotImplementedError()


  @property
  def lans(self) -> set[LanDescriptor]:
    return set()


  @property
  def vpn_interfaces(self) -> set[WireGuardInterface]:
    return set()


  @property
  def router(self) -> Router|None:
    return None


  @property
  def net(self) -> AgentNetworking:
    raise NotImplementedError()


  @property
  def root_vpn_id(self) -> str:
    raise NotImplementedError()


  @property
  def backbone_vpn_ids(self) -> set[str]:
    raise NotImplementedError()


  @property
  def particles_vpn_id(self) -> str:
    raise NotImplementedError()


  @property
  def backbone_peers(self) -> str:
    raise NotImplementedError()


  def _validate_boot_config(self):
    pass


  def _start_services(self, boot: bool=False) -> None:
    pass


  def _stop_services(self, errors: list[Exception], exiting: bool=False) -> None:
    pass


  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    pass


  def _on_reader_offline(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo) -> None:
    pass


  def _on_spin(self,
      ts_start: Timestamp,
      ts_now: Timestamp,
      spin_len: float) -> None:
    # Reset dirty flag
    self.dirty = False


  def _on_discovery_completed_status(self, completed: bool) -> None:
    pass


  def _on_routed_sites_status(self, new: set[LanDescriptor], gone: set[LanDescriptor]) -> None:
    pass


  def _regenerate_plots(self) -> None:
    self._uvn_backbone_plot_dirty = True


  def _on_user_condition(self, condition: dds.GuardCondition):
    if condition == self.peers.updated_condition:
      # Peer statistics updated
      self._on_peers_updated()


  def _on_peer_updated(self, peer: UvnPeer) -> None:
    self._on_peers_updated()


  def _on_peers_updated(self) -> None:
    log.debug(f"[AGENT] checking updated peers status [{self.peers.online_peers_count}/{len(self.uvn_id.cells)} online]")

    self.discovery_completed = len(self.uvn_id.cells) == self.peers.online_peers_count

    # Check if any agent came online/offline
    fields = {"status", "routed_sites", "registry_id", "reachable_sites"}
    if next((p for p in self.peers
        if p.cell and (fields & p.updated_fields)), None) is not None:
      self.routed_sites = (r for p in self.peers for r in p.routed_sites)
      # print("CONSISTENT PEERS: ", list(map(str, self.consistent_config_peers)))
      # print("INCONSISTENT PEERS:", list(map(str, self.inconsistent_config_peers)))
      self.uvn_consistent_config = len(self.consistent_config_peers) == len(self.uvn_id.cells)
      self.uvn_consistent = self.uvn_consistent_config and len(self.connected_peers) == len(self.uvn_id.cells)
  
    # Check if the registry came online/offline
    if "status" in self.peers[0].updated_fields:
      self.registry_connected = self.peers[0].status == UvnPeerStatus.ONLINE

    # Reset list of latest changes for the next iteration
    self.peers.clear()


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

    self._start_services()

    self.peers.online(
      registry_id=self.registry_id,
      deployment_id=self.deployment.generation_ts,
      routed_sites=self.lans,
      root_vpn_id=self.root_vpn_id,
      particles_vpn_id=self.particles_vpn_id,
      backbone_vpn_ids=self.backbone_vpn_ids,
      backbone_peers=self.backbone_peers)

    if boot:
      self.net.uvn_agent.write_pid()

    self.started = True

    # Trigger updates on the next spin
    self.dirty= True

    log.activity("[AGENT] started")

    # Notify systemd upon boot, if enabled
    if boot and self.enable_systemd:
      log.debug("[AGENT] notifying systemd")
      notifier = sdnotify.SystemdNotifier()
      notifier.notify("READY=1")
      log.debug("[AGENT] systemd notified")


  def _stop(self, exiting: bool=False) -> None:
    log.activity("[AGENT] performing shutdown...")
    self.started = False
    errors = []
    try:
      self.peers.offline()
    except Exception as e:
      log.error(f"[AGENT] failed to transition agent to OFFLINE")
      # log.exception(e)
      errors.append(e)
    try:
      self.routed_sites = []
    except Exception as e:
      log.error(f"[AGENT] failed to reset routed sites")
      # log.exception(e)
      errors.append(e)
    try:
      self.discovery_completed = False
    except Exception as e:
      log.error(f"[AGENT] failed to reset discovery status")
      # log.exception(e)
      errors.append(e)
    try:
      self.registry_connected = False
    except Exception as e:
      log.error(f"[AGENT] failed to reset registry connection status")
      # log.exception(e)
      errors.append(e)

    try:
      self.dp.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop DDS participant:")
      # log.exception(e)
      errors.append(e)
    
    self._stop_services(errors=errors)

    try:
      self.net.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop network services")
      # log.exception(e)
      errors.append(e)

    try:
      if exiting:
        self.net.uvn_agent.delete_pid()
    except:
      log.error(f"[AGENT failed to delete PID file: {self.net.uvn_agent.pid_file}")
      errors.append(e)

    if errors:
      raise RuntimeError("failed to finalize agent", errors)
    log.activity("[AGENT] stopped")

