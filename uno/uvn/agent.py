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
from typing import Iterable, Optional, Callable, Tuple
import time
import ipaddress
import sdnotify

from .uvn_id import UvnId, CellId
from .wg import WireGuardInterface
from .ip import (
  LanDescriptor,
  NicDescriptor,
  ipv4_from_bytes,
)
from .dds import DdsParticipant, DdsParticipantConfig, UvnTopic
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer, UvnPeerListener
from .vpn_config import P2PLinksMap
from .time import Timestamp
from .graph import backbone_deployment_graph
from .agent_net import AgentNetworking
from .router import Router
from .routes_monitor import RoutesMonitor, RoutesMonitorListener
from .id_db import IdentityDatabase
from .exec import exec_command
from .log import Logger as log

class _AgentSpinner:
  def __init__(self, agent: "Agent") -> None:
    self.agent = agent
  
  def __enter__(self) -> "Agent":
    self.agent._start(boot=True)
    return self.agent

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.agent._stop()


class Agent(UvnPeerListener, RoutesMonitorListener):
  class Service:
    def start(self) -> None:
      raise NotImplementedError()

    def stop(self) -> None:
      raise NotImplementedError()

  KNOWN_NETWORKS_TABLE_FILENAME = "networks.known"
  LOCAL_NETWORKS_TABLE_FILENAME = "networks.local"
  REACHABLE_NETWORKS_TABLE_FILENAME = "networks.reachable"
  UNREACHABLE_NETWORKS_TABLE_FILENAME = "networks.unreachable"

  def __init__(self) -> None:
    self.create_ts = int(time.time())
    self.dp = DdsParticipant()
    self.started = False
    self._started_services = []
    self._uvn_backbone_plot_dirty = True
    self.routes_monitor = RoutesMonitor(log_dir=self.log_dir)
    self.routes_monitor.listeners.append(self)
    # Only enable Systemd support on request
    self.enable_systemd = False
    self.ts_start = Timestamp.now()
    # Store an updated agent instance upon receiving new configuration
    # then reload it after finishing handling dds data (since reload
    # will cause DDS entities to be deleted)
    self._reload_agent = None
    super().__init__()


  def spin(self,
      until: Optional[Callable[[], bool]]=None,
      max_spin_time: Optional[int]=None) -> None:
    self._spin(until=until, max_spin_time=max_spin_time)
    # try:
    #   self._start(boot=True)
    #   self._spin(until=until, max_spin_time=max_spin_time)
    # finally:
    #   self._stop(exiting=True)


  def spin_until_consistent(self,
      max_spin_time: Optional[int]=None,
      config_only: bool=False) -> None:
    spin_state = {
      "consistent_config": False
    }
    def _until_consistent() -> bool:
      if not spin_state["consistent_config"] and self.peers.status_consistent_config_uvn:
        log.warning(f"[AGENT] spinning condition reached: consistent config uvn")
        spin_state["consistent_config"] = True
        if config_only:
          return True
      elif spin_state["consistent_config"] and self.peers.status_fully_routed_uvn:
        log.warning(f"[AGENT] spinning condition reached: fully routed uvn")
        return True
      # if not spin_state["consistent_config"]:
      #   log.debug(f"[AGENT] at configuration [{len(self.consistent_config_peers)}/{len(self.uvn_id.cells)}]: {list(map(str, self.inconsistent_config_peers))}")
      #   log.debug(f"[AGENT] not configured yet [{len(self.inconsistent_config_peers)}/{len(self.uvn_id.cells)}]: {list(map(str, self.inconsistent_config_peers))}")
      # else:
      #   log.debug(f"[AGENT] still waiting for UVN to become consistent")
    
    timedout = self.spin(until=_until_consistent, max_spin_time=max_spin_time)
    if timedout:
      raise RuntimeError("UVN failed to reach expected state before timeout")


  def _spin(self,
      until: Optional[Callable[[], bool]]=None,
      max_spin_time: Optional[int]=None) -> None:
    spin_start = Timestamp.now()
    log.debug(f"starting to spin on {spin_start}")
    while True:
      done, active_writers, active_readers, active_data, extra_conds = self.dp.wait()
      
      spin_time = Timestamp.now()
      spin_length = spin_time.subtract(spin_start)
      timedout = max_spin_time is not None and spin_length >= max_spin_time
      if timedout:
        log.debug(f"time out after {max_spin_time} sec")
        # If there is an exit condition, throw an error, since we
        # didn't reach it.
        if until:
          raise RuntimeError("timed out", max_spin_time)

      done = done or timedout

      if done:
        log.debug("done spinning")
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
        log.debug("exit condition reached")
        break

      self._on_spin(
        ts_start=spin_start,
        ts_now=spin_time,
        spin_len=spin_length)



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
    if not plot.is_file() or self._uvn_backbone_plot_dirty:
      generated = backbone_deployment_graph(
        uvn_id=self.uvn_id,
        deployment=self.deployment,
        output_file=plot,
        peers=self.peers,
        local_peer_id=self.peers.local.id)
      self._uvn_backbone_plot_dirty = False
      if generated:
        log.debug(f"[AGENT] backbone plot generated: {plot}")
      else:
        log.debug(f"[AGENT] backbone plot NOT generated")
    return plot


  @property
  def participant_xml_config(self) -> Path:
    return self.root / "uno_qos_profiles.xml"


  @property
  def cell(self) -> CellId|None:
    return None


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
    participant_xml_config, participant_profile, writers_and_readers = self.dds_xml_config
    return DdsParticipantConfig(
      participant_xml_config=participant_xml_config,
      participant_profile=participant_profile,
      user_conditions=self.user_conditions,
      **writers_and_readers)


  @property
  def dds_xml_config(self) -> Tuple[str, str, dict]:
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
  def services(self) -> list[Tuple["Agent.Service", dict]]:
    return [
      (self.routes_monitor, {}),
    ]


  @property
  def user_conditions(self) -> list[dds.GuardCondition]:
    return [
      self.peers.updated_condition,
      self.routes_monitor.updated_condition,
    ]


  @property
  def id_db(self) -> IdentityDatabase:
    raise NotImplementedError()


  def _validate_boot_config(self):
    pass


  def _reload(self, updated_agent: "Agent") -> None:
    raise NotImplementedError()


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
    if peer_uvn != self.uvn_id.name:
      log.debug(f"[AGENT] IGNORING update from foreign agent:"
                f" uvn={sample['id.uvn']}", f"cell={sample['id.n']}")
      return

    peer_cell_id = sample["id.n"]
    peer_cell = self.uvn_id.cells.get(peer_cell_id)
    if peer_cell is None:
      # Ignore sample from unknown cell
      log.warning(f"[AGENT] IGNORING update from unknown agent:"
                  f" uvn={sample['id.uvn']}, cell={sample['id.n']}")
      return

    def _site_to_descriptor(site):
      subnet_addr = ipv4_from_bytes(site["subnet.address.value"])
      subnet_mask = site["subnet.mask"]
      subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
      endpoint = ipv4_from_bytes(site["endpoint.value"])
      gw = ipv4_from_bytes(site["gw.value"])
      nic = site["nic"]
      return LanDescriptor(
        nic=NicDescriptor(
          name=nic,
          address=endpoint,
          subnet=subnet,
          netmask=subnet_mask),
        gw=gw)

    log.activity(f"[AGENT] cell info UPDATE: {peer_cell}")
    self.peers.update_peer(self.peers[peer_cell.id],
      registry_id=sample["registry_id"],
      status=UvnPeerStatus.ONLINE,
      routed_networks=[_site_to_descriptor(s) for s in sample["routed_networks"]],
      reachable_networks=[_site_to_descriptor(s) for s in sample["reachable_networks"]],
      unreachable_networks=[_site_to_descriptor(s) for s in sample["unreachable_networks"]],
      ih=info.instance_handle,
      ih_dw=info.publication_handle,
      ts_start=sample["ts_start"])


  def _on_reader_data_uvn_info(self,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> UvnPeer | None:
    peer_uvn = sample["name"]
    if peer_uvn != self.uvn_id.name:
      log.warning(f"[AGENT] IGNORING update for foreign UVN: uvn={sample['name']}")
      return None

    log.debug(f"[AGENT] uvn info UPDATE: {self.uvn_id}")
    self.peers.update_peer(self.peers.registry,
      status=UvnPeerStatus.ONLINE,
      uvn_id=self.uvn_id,
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
      log.debug(f"[AGENT] peer writer offline: {peer}")
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
      log.activity(f"[AGENT] marking {len(matched_peers)} peers on matched publications: {list(map(str, matched_peers))}")
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
    log.warning(f"[AGENT] stopping services to load new configuration: {updated_agent.registry_id}")
    self._stop()
    
    log.activity(f"[AGENT] updating configuration to {updated_agent.registry_id}")
    self._reload(updated_agent)

    # Copy files from the updated agent's root directory,
    # then rewrite agent configuration
    package_files = list(updated_agent.root.glob("*"))
    if package_files:
      exec_command(["cp", "-rv", *package_files, self.root])
    self.save_to_disk()

    log.activity(f"[AGENT] restarting services with new configuration: {self.registry_id}")
    self._start()

    log.warning(f"[AGENT] new configuration loaded: {self.registry_id}")


  def schedule_reload(self, updated_agent: "Agent") -> None:
    if self._reload_agent:
      log.warning(f"[AGENT] discarding previously scheduled reload: {self._reload_agent.registry_id}")
    self._reload_agent = updated_agent
    log.warning(f"[AGENT] reload scheduled: {self._reload_agent.registry_id}")


  def on_event_online_cells(self, new_cells: set[UvnPeer], gone_cells: set[UvnPeer]) -> None:
    if gone_cells:
      log.error(f"[STATUS] cells OFFLINE [{len(gone_cells)}]: {', '.join(c.name for c in gone_cells)}")
    if new_cells:
      log.warning(f"[STATUS] cells ONLINE [{len(new_cells)}]: {', '.join(c.name for c in new_cells)}")


  def on_event_all_cells_connected(self) -> None:
    if not self.peers.status_all_cell_connected:
      log.error(f"[STATUS] lost connection with some cells")
      # self.on_status_all_cells_connected(False)
    else:
      log.warning(f"[STATUS] all cells connected")
    self._uvn_backbone_plot_dirty = True


  def on_event_registry_connected(self) -> None:
    if not self.peers.status_registry_connected:
      log.error(f"[STATUS] lost connection with registry")
    else:
      log.warning(f"[STATUS] registry connected")


  def on_event_routed_networks(self, new_routed: set[LanDescriptor], gone_routed: set[LanDescriptor]) -> None:
    if gone_routed:
      log.error(f"[STATUS] networks  DETACHED [{len(gone_routed)}]: {', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in gone_routed)}")
    if new_routed:
      log.warning(f"[STATUS] networks ATTACHED [{len(new_routed)}]: {', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in new_routed)}")

    self._write_known_networks_file()


  def on_event_routed_networks_discovered(self) -> None:
    if not self.peers.status_routed_networks_discovered:
      log.error(f"[STATUS] some networks were DETACHED from uvn {self.uvn_id}")
    else:
      routed_networks = sorted(((c, l) for c in self.peers.cells for l in c.routed_networks),
        key=lambda v: (v[0].id, v[1].nic.name, v[1].nic.subnet))
      log.warning(f"[STATUS] all {len(routed_networks)} networks ATTACHED to uvn {self.uvn_id}")
      for c, l in routed_networks:
        log.warning(f"[STATUS] - {c.name} → {l.nic.subnet}")


  def on_event_consistent_config_cells(self, new_consistent: set[UvnPeer], gone_consistent: set[UvnPeer]) -> None:
    if gone_consistent:
      log.error(f"[STATUS] {len(gone_consistent)} cells have INCONSISTENT configuration: {', '.join(c.name for c in gone_consistent)}")
    if new_consistent:
      log.activity(f"[STATUS] {len(new_consistent)} cells have CONSISTENT configuration: {', '.join(c.name for c in new_consistent)}")


  def on_event_consistent_config_uvn(self) -> None:
    if not self.peers.status_consistent_config_uvn:
      log.error(f"[STATUS] some cells have inconsistent configuration:")
      for cell in (c for c in self.peers.cells if c.registry_id != self.registry_id):
        log.error(f"[STATUS] - {cell}: {cell.registry_id}")
    else:
      log.warning(f"[STATUS] all cells have consistent configuration: {self.registry_id}")
      self.uvn_id.log_deployment(deployment=self.deployment)


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    if gone_reachable:
      log.error(f"[STATUS] networks UNREACHABLE (local) [{len(gone_reachable)}]: {', '.join(str(n.nic.subnet) for n in gone_reachable)}")
    if new_reachable:
      log.warning(f"[STATUS] networks REACHABLE (local) [{len(new_reachable)}]: {', '.join(str(n.nic.subnet) for n in new_reachable)}")
    self._write_reachable_networks_files()


  def on_event_reachable_networks(self, new_reachable: set[Tuple[UvnPeer, LanDescriptor]], gone_reachable: set[Tuple[UvnPeer, LanDescriptor]]) -> None:
    if gone_reachable:
      log.error(f"[STATUS] networks UNREACHABLE (remote) [{len(gone_reachable)}]: {', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in gone_reachable)}")
    if new_reachable:
      log.warning(f"[STATUS] networks REACHABLE (remote) [{len(new_reachable)}]: {', '.join(c.name + ' → ' + str(n.nic.subnet) for c, n in new_reachable)}")


  def on_event_fully_routed_uvn(self) -> None:
    if not self.peers.status_fully_routed_uvn:
      log.error(f"[STATUS] uvn {self.uvn_id} is not fully routed:")
      for cell in (c for c in self.peers.cells if c.unreachable_networks):
        log.error(f"[STATUS] - {cell} → {', '.join(map(str, cell.unreachable_networks))}")
    else:
      routed_networks = sorted(
        {(c, l) for c in self.peers.cells for l in c.routed_networks},
        key=lambda n: (n[0].id, n[1].nic.name, n[1].nic.subnet))
      log.warning(f"[STATUS] {len(routed_networks)} networks REACHABLE from {len(self.uvn_id.cells)} cells in uvn {self.uvn_id}:")
      for c, l in routed_networks:
        log.warning(f"[STATUS] - {c} → {l.nic.subnet}")


  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    for r in new_routes:
      log.warning(f"[STATUS] route ADD: {r}")
    for r in gone_routes:
      log.warning(f"[STATUS] route DEL: {r}")
    if self.router:
      self.router.update_state()


  def _on_user_condition(self, condition: dds.GuardCondition):
    if condition == self.routes_monitor.updated_condition:
      self.routes_monitor.process_updates()
    elif condition == self.peers.updated_condition:
      self.peers.process_updates()


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
      ts_start=self.ts_start)

    if boot:
      self.net.uvn_agent.write_pid()

    self._on_started(boot=boot)

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
      log.exception(e)
      errors.append(e)
    try:
      self.dp.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop DDS participant:")
      log.exception(e)
      errors.append(e)
    for svc in list(self._started_services):
      try:
        svc.stop()
        self._started_services.remove(svc)
      except Exception as e:
        log.error(f"[AGENT] failed to stop service: {svc}")
        log.exception(e)
        errors.append(e)
    try:
      self.net.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop network services")
      log.exception(e)
      errors.append(e)
    try:
      if exiting:
        self.net.uvn_agent.delete_pid()
    except Exception as e:
      log.error(f"[AGENT failed to delete PID file: {self.net.uvn_agent.pid_file}")
      log.exception(e)
      errors.append(e)

    if errors:
      raise RuntimeError("failed to finalize agent", errors)
    log.activity("[AGENT] stopped")


  def _on_started(self, boot: bool=False) -> None:
    pass


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
