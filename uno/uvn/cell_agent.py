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
import rti.connextdds as dds
import shutil
from pathlib import Path
from typing import Mapping, Sequence, Iterable, Optional, Tuple, Callable
import ipaddress
import yaml
import tempfile
import time

import sdnotify

from .uvn_id import UvnId, CellId, ParticlesVpnSettings, RootVpnSettings
from .wg import WireGuardConfig, WireGuardInterface
from .ip import (
  list_local_networks,
  ipv4_from_bytes,
  ipv4_get_route,
  LanDescriptor,
  NicDescriptor,
)
from .ns import Nameserver, NameserverRecord
from .dds import DdsParticipant, DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer
from .exec import exec_command
from .vpn_config import P2PLinksMap, CentralizedVpnConfig
from .peer_test import UvnPeersTester, UvnPeerLanStatus
from .time import Timestamp
from .www import UvnHttpd
from .particle import write_particle_configuration
from .graph import cell_agent_status_plot, backbone_deployment_graph
from .render import Templates
from .dds_data import dns_database, cell_agent_status
from .agent_net import AgentNetworking
from .router import Router
from .agent import Agent
from .log import Logger as log


class CellAgent(Agent):
  DDS_CONFIG_TEMPLATE = "uno.xml"
  KNOWN_NETWORKS_TABLE_FILENAME = "networks.known"
  LOCAL_NETWORKS_TABLE_FILENAME = "networks.local"
  REACHABLE_NETWORKS_TABLE_FILENAME = "networks.reachable"
  UNREACHABLE_NETWORKS_TABLE_FILENAME = "networks.unreachable"
  
  GLOBAL_UVN_ID = Path("/etc/uno/root")

  def __init__(self,
      root: Path,
      uvn_id: UvnId,
      cell_id: int,
      registry_id: str,
      deployment: P2PLinksMap,
      backbone_vpn_configs: Sequence[WireGuardConfig],
      particles_vpn_config: CentralizedVpnConfig,
      root_vpn_config: WireGuardConfig) -> None:
    
    self._uvn_id = uvn_id
    self._deployment = deployment
    self._registry_id = registry_id

    self.cell = self.uvn_id.cells[cell_id]

    self.root_vpn_config = root_vpn_config
    self.root_vpn = WireGuardInterface(self.root_vpn_config)

    self.backbone_vpn_configs = list(backbone_vpn_configs)
    self.backbone_vpns = [WireGuardInterface(v) for v in self.backbone_vpn_configs]

    self.particles_vpn_config = particles_vpn_config
    self.particles_vpn = (
      WireGuardInterface(self.particles_vpn_config.root_config)
      if self.enable_particles_vpn else None
    )
    self._root: Path = root.resolve()

    self._peers = UvnPeersList(
      uvn_id=self.uvn_id,
      local_peer_id=cell_id)

    # self.ns = Nameserver(self.root, db=self.uvn_id.hosts)
    self.peers_tester = UvnPeersTester(self,
      max_test_delay=self.uvn_id.settings.timing_profile.tester_max_delay)

    self._router = Router(self)

    self._net = AgentNetworking(
      config_dir=self.config_dir,
      allowed_lans=self.lans,
      vpn_interfaces=self.vpn_interfaces,
      router=self.router)

    self.www = UvnHttpd(self)

    # Store configuration upon receiving it, so we can reload it
    # once we're done processing received data
    self._reload_config = None

    # Track state of plots so we can regenerate them on the fly
    self._regenerate_plots()

    # 
    self._reachable_sites = set()
    self._unreachable_sites = set()
    self._fully_routed = False

    # Only enable HTTP server if requested
    self.enable_www = False

    super().__init__()


  @property
  def registry_id(self) -> str:
    return self._registry_id


  @property
  def root(self) -> Path:
    return self._root


  @property
  def deployment(self) -> P2PLinksMap:
    return self._deployment


  @property
  def uvn_id(self) -> UvnId:
    return self._uvn_id


  @property
  def peers(self) -> UvnPeersList:
    return self._peers


  @property
  def router(self) -> Router|None:
    return self._router


  @property
  def net(self) -> AgentNetworking:
    return self._net


  @property
  def peer_online_attributes(self) -> Mapping[str, object]:
    return {
      "root_vpn_id": self.root_vpn.config.generation_ts if self.root_vpn else None,
      "particles_vpn_id": self.particles_vpn_config.generation_ts,
      "backbone_vpn_ids": [nic.config.generation_ts for nic in self.backbone_vpns],
      "backbone_peers": [p.id for nic in self.backbone_vpns for p in nic.config.peers]
    }


  @property
  def rti_license(self) -> Path:
    return self.root / "rti_license.dat"


  @property
  def pid_file(self) -> Path:
    return Path("/run/uno/uvn-agent.pid")


  @property
  def vpn_interfaces(self) -> Sequence[WireGuardInterface]:
    return [
      *self.backbone_vpns,
      *([self.root_vpn] if self.enable_root_vpn else []),
      *([self.particles_vpn] if self.enable_particles_vpn else []),
    ]


  @property
  def lans(self) -> set[LanDescriptor]:
    def _allowed_nic(nic: NicDescriptor) -> bool:
      for allowed_lan in self.cell.allowed_lans:
        if nic.address in allowed_lan:
          return True
      return False
    if not self.cell.allowed_lans:
      return set()
    return {
      LanDescriptor(nic=nic, gw=gw)
      for nic in list_local_networks(skip=[
        i.config.intf.name for i in self.vpn_interfaces
      ]) if _allowed_nic(nic)
        for gw in [ipv4_get_route(nic.subnet.network_address)]
    }


  @property
  def enable_particles_vpn(self) -> bool:
    return (
      self.uvn_id.particles
      and self.uvn_id.settings.enable_particles_vpn
      and self.cell.enable_particles_vpn)


  @property
  def enable_root_vpn(self) -> bool:
    return self.uvn_id.settings.enable_root_vpn


  def _regenerate_plots(self) -> None:
    self._uvn_status_plot_dirty = True
    super()._regenerate_plots()


  @property
  def uvn_status_plot(self) -> Path:
    status_plot = self.www.root / "uvn-status.png"
    if not status_plot.is_file() or self._uvn_status_plot_dirty:
      cell_agent_status_plot(self, status_plot, seed=self.create_ts)
      self._uvn_status_plot_dirty = False
      log.debug(f"[AGENT] status plot generated: {status_plot}")
    return status_plot


  def _on_discovery_completed_status(self, completed: bool) -> None:
    # Some peers went offline/online, trigger the tester to check their LANs
    self.peers_tester.trigger()


  def _on_routed_sites_status(self, new: set[LanDescriptor], gone: set[LanDescriptor]) -> None:
    # if new_sites:
    #   subnets = {l.nic.subnet for l in new_sites}
    #   log.debug(f"[AGENT] enabling {len(new_sites)} new routed sites: {list(map(str, new_sites))}")
    #   for backbone_vpn in self.backbone_vpns:
    #     backbone_vpn.allow_ips_for_peer(0, subnets)
    # if gone_sites:
    #   subnets = {l.nic.subnet for l in gone_sites}
    #   log.activity(f"[AGENT] disabling {len(gone_sites)} inactive routed sites: {list(map(str, gone_sites))}")
    #   for backbone_vpn in self.backbone_vpns:
    #     backbone_vpn.disallow_ips_for_peer(0, subnets)
    
    # Trigger tester to check the state of known and new sites
    self.peers_tester.trigger()

    # Check if all sites are reachable
    self._assert_fully_routed()

    self._write_known_networks_file()


  @property
  def reachable_sites(self) -> Iterable[UvnPeerLanStatus]:
    return self._reachable_sites


  @reachable_sites.setter
  def reachable_sites(self, val: Iterable[UvnPeerLanStatus]) -> None:
    prev = self._reachable_sites
    self._reachable_sites = set(val)

    if prev != self._reachable_sites:
      # log.error(f"CHANGED REACHABLE: {self._reachable_sites}")
      self.dirty= True
      # Check if all sites are reachable
      self._assert_fully_routed()
      self._write_reachable_networks_files(
        reachable=self._reachable_sites,
        unreachable=self._unreachable_sites)
    # else:
    #   log.error(f"NOT CHANGED REACHABLE: {self._reachable_sites}")


  @property
  def unreachable_sites(self) -> Iterable[UvnPeerLanStatus]:
    return self._unreachable_sites


  @unreachable_sites.setter
  def unreachable_sites(self, val: Iterable[UvnPeerLanStatus]) -> None:
    prev = self._unreachable_sites
    self._unreachable_sites = set(val)

    if prev != self._unreachable_sites:
      # if self._unreachable_sites:
      #   self.fully_routed = False
      self.dirty= True


  @property
  def fully_routed(self) -> bool:
    return self._fully_routed


  @fully_routed.setter
  def fully_routed(self, val: bool) -> None:
    prev = self._fully_routed
    self._fully_routed = val
    if prev != val:
      if prev:
        if self.reachable_sites or self.unreachable_sites:
          log.error(f"[AGENT] lost connection with some networks: reachable={[str(s.lan.nic.subnet) for s in self.reachable_sites]}, unreachable={[str(s.lan.nic.subnet) for s in self.unreachable_sites]}")
        # Don't print messages if offline
        elif self.started:
          log.error(f"[AGENT] disconnected from all networks!")
      else:
        log.warning(f"[AGENT] routing ALL {len(self.reachable_sites)} networks: {[str(s.lan.nic.subnet) for s in self.reachable_sites]}")
      self.dirty = True


  @property
  def dds_config(self) -> DdsParticipantConfig:
    # Pick the address of the first backbone port for every peer
    # and all addresses for peers connected directly to this one
    backbone_peers = {
      peer_b[1]
        for peer_a in self.deployment.peers.values()
          for peer_b_id, peer_b in peer_a["peers"].items()
            if peer_b[0] == 0 or peer_b_id == self.cell.id
    } - {
      cfg.intf.address
        for cfg in self.backbone_vpn_configs
    }
    initial_peers = [
      self.root_vpn_config.peers[0].address,
      *backbone_peers
    ]

    if not self.rti_license.is_file():
      log.error(f"RTI license file not found: {self.rti_license}")
      raise RuntimeError("RTI license file not found")

    xml_config_tmplt = Templates.compile(
      DdsParticipantConfig.load_config_template(self.DDS_CONFIG_TEMPLATE))
    
    xml_config = Templates.render(xml_config_tmplt, {
      "deployment_id": self.deployment.generation_ts,
      "uvn": self.uvn_id,
      "cell": self.cell,
      "initial_peers": initial_peers,
      "timing": self.uvn_id.settings.timing_profile,
      "license_file": self.rti_license.read_text(),
      "ca_cert": self.root / "ca-cert.pem",
      "perm_ca_cert": self.root / "perm-ca-cert.pem",
      "cert": self.root / "cert.pem",
      "key": self.root / "key.pem",
      "governance": self.root / "governance.p7s",
      "permissions": self.root / "permissions.p7s",
      "enable_dds_security": False,
    })

    return DdsParticipantConfig(
      participant_xml_config=xml_config,
      participant_profile=DdsParticipantConfig.PARTICIPANT_PROFILE_CELL,
      user_conditions=[
        self.peers_tester.result_available_condition,
        self.peers.updated_condition,
      ],
      **Registry.AGENT_CELL_TOPICS)


  @property
  def ns_records(self) -> Sequence[NameserverRecord]:
    return [
      NameserverRecord(
        hostname=f"registry.{self.uvn_id.address}",
        address=str(self.root_vpn_config.peers[0].address),
        server=self.uvn_id.name,
        tags=["registry", "vpn", "uvn"]),
      NameserverRecord(
        hostname=f"{self.cell.name}.vpn.{self.uvn_id.address}",
        address=str(self.root_vpn_config.intf.address),
        server=self.cell.name,
        tags=["cell", "vpn", "uvn"]),
      *(
        NameserverRecord(
          hostname=f"{peer.name}.{self.cell.name}.backbone.{self.uvn_id.address}",
          address=str(backbone_vpn.config.intf.address),
          server=self.cell.name,
          tags=["cell", "uvn", "backbone"])
        for backbone_vpn in self.backbone_vpns
          for peer in [self.uvn_id.cells[backbone_vpn.config.peers[0].id]]
      ),
    ]


  def _validate_boot_config(self):
    # Check that the agent detected all of the expected networks
    allowed_lans = set(str(net) for net in self.cell.allowed_lans)
    enabled_lans = set(str(lan.nic.subnet) for lan in self.lans)

    if allowed_lans and allowed_lans != enabled_lans:
      log.error(f"[AGENT] failed to detect all of the expected network interfaces for cell {self.cell}:")
      log.error(f"[AGENT] - expected: {', '.join(sorted(allowed_lans))}")
      log.error(f"[AGENT] - detected: {', '.join(sorted(enabled_lans))}")
      log.error(f"[AGENT] - missing : {', '.join(sorted(allowed_lans - enabled_lans))}")
      raise RuntimeError("invalid network interfaces")


  def _start_services(self, boot: bool=False) -> None:
    # TODO(asorbini) re-enable ns server once thought through
    # self.ns.assert_records(self.ns_records)
    # self.ns.start(self.uvn_id.address)
    self.peers_tester.start()

    # Write particle configuration to disk
    self._write_particle_configurations()

    # Start the internal web server on localhost
    # and on the VPN interfaces
    if self.enable_www:
      self.www.start([
        "localhost",
        *(vpn.config.intf.address for vpn in self.vpn_interfaces),
        *(l.nic.address for l in self.lans),
      ])


  def _stop_services(self, errors: list[Exception], exiting: bool=False) -> None:
    try:
      self.www.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop web server")
      # log.exception(e)
      errors.append(e)
    try:
      self.peers_tester.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop peers tester")
      # log.exception(e)
      errors.append(e)
    try:
      self.unreachable_sites = []
    except Exception as e:
      log.error(f"[AGENT] failed to reset unreachable sites")
      # log.exception(e)
      errors.append(e)
    try:
      self.reachable_sites = []
    except Exception as e:
      log.error(f"[AGENT] failed to reset reachable sites")
      # log.exception(e)
      errors.append(e)
  

  def _assert_fully_routed(self) -> None:
    reachable = set()
    for site in self.routed_sites:
      reach = next((s for s in self._reachable_sites if s.lan == site), None)
      if not reach:
        continue
      reachable.add(site)

    missing = self.routed_sites - reachable
    all_reachable = False
    if missing:
      log.activity(f"[AGENT] unreachable or not yet tested: {[str(l.nic.subnet) for l in missing]}")
    else:
      reachable_subnets = {l.nic.subnet for l in reachable}
      all_reachable = self.expected_subnets == reachable_subnets

    self.fully_routed = not bool(missing) and all_reachable


  def _on_spin(self,
      ts_start: Timestamp,
      ts_now: Timestamp,
      spin_len: float) -> None:
    if self._reload_config:
      new_config = self._reload_config
      self._reload_config = None
      # Parse/save/load new configuration
      self.reload(new_config, save_to_disk=True)

    new_routes, gone_routes = self.router.update_routes()
    if new_routes or gone_routes:
      for r in new_routes:
        log.activity(f"[AGENT] route ADD: {r}")
      for r in gone_routes:
        log.activity(f"[AGENT] route DEL: {r}")
      self.peers_tester.trigger()

    if self.dirty:
      self._write_cell_info()
      self._regenerate_plots()
      self.www.request_update()

    # Periodically update the status page for various statistics
    self.www.update()

    super()._on_spin(
      ts_start=ts_start,
      ts_now=ts_now,
      spin_len=spin_len)


  def _on_user_condition(self, condition: dds.GuardCondition):
    if condition == self.peers_tester.result_available_condition:#
      # New peers tester result 
      self._on_peers_tester_result()
    else:
      super()._on_user_condition(condition)



  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    if topic == UvnTopic.DNS:
      self._on_dns_data(info.instance_handle, sample)
    elif topic == UvnTopic.BACKBONE:
      new_config = sample["config"]
      try:
        new_config = yaml.safe_load(new_config)
        self._reload_config = new_config
      except Exception as e:
        log.error("failed to parse received configuration")
        log.exception(e)


  def _on_dns_data(self, instance: dds.InstanceHandle, sample: dds.DynamicData) -> None:
    ns_server_name = sample["cell.name"]
    ns_cell = next((c for c in self.uvn_id.cells.values() if c.name == ns_server_name), None)
    if ns_cell is None:
      log.debug(f"[AGENT] IGNORING DNS update from unknown cell: {ns_server_name}")
      return
    ns_peer = self.peers[ns_cell]
    ns_peer.ih_dns = instance
    ns_records = [
      NameserverRecord(
        hostname=entry["hostname"],
        address=ipv4_from_bytes(entry["address.value"]),
        tags=entry["tags"],
        server=ns_server_name)
      for entry in sample["entries"]  
    ]
    # self.ns.assert_records(ns_records)
    return


  def _on_reader_offline(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo) -> None:
    if topic == UvnTopic.DNS:
      ns_peer, purged_records = self._on_dns_offline(info.instance_handle)    
    return


  def _on_dns_offline(self, instance: dds.InstanceHandle) -> None:
    ns_peer = next((p for p in self.peers if p.ih_dns == instance), None)
    if not ns_peer:
      log.debug(f"[AGENT] DNS dispose for unknown instance: {instance}")
      return
    # self.ns.purge_server(ns_peer.cell.name)
    return


  def _write_cell_info(self) -> None:
    sample = cell_agent_status(
      participant=self.dp,
      uvn_id=self.uvn_id,
      cell_id=self.cell.id,
      deployment=self.deployment,
      registry_id=self.registry_id,
      root_vpn_config=self.root_vpn_config,
      particles_vpn_config=self.particles_vpn_config,
      backbone_vpn_configs=self.backbone_vpn_configs,
      lans=self.lans,
      reachable_sites=self.reachable_sites,
      unreachable_sites=self.unreachable_sites)
    self.dp.writers[UvnTopic.CELL_ID].write(sample)
    log.activity(f"[AGENT] published cell info: {self}")


  def _write_dns(self) -> None:
    sample = dns_database(
      participant=self.dp,
      uvn_id=self.uvn_id,
      ns=self.ns,
      server_name=self.cell.name)
    self.dp.writers[UvnTopic.DNS].write(sample)
    log.activity(f"[AGENT] published DNS info: {self}")


  def _on_peers_tester_result(self) -> None:
    reachable_sites, unreachable_sites, _ = self.peers_tester.peek_state()
    log.activity(
      f"[AGENT] tester results:"
      f" REACHABLE={[str(s.lan.nic.subnet) for s in reachable_sites]},"
      f" UNREACHABLE={[str(s.lan.nic.subnet) for s in unreachable_sites]}")
    self.unreachable_sites = unreachable_sites
    self.reachable_sites = reachable_sites
    self.peers.update_peer(self.peers.local_peer,
      reachable_sites={s.lan for s in self.reachable_sites},
      unreachable_sites={s.lan for s in self.unreachable_sites})
    self._on_peers_updated()


  def find_backbone_peer_by_address(self, addr: str | ipaddress.IPv4Address) -> Optional[UvnPeer]:
    addr = ipaddress.ip_address(addr)
    for bbone in self.backbone_vpn_configs:
      if bbone.peers[0].address == addr:
        return self.peers[bbone.peers[0].id]
      elif bbone.intf.address == addr:
        return self.peers.local_peer
    return None


  @property
  def vpn_stats(self) -> Mapping[str, dict]:
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


  def _write_known_networks_file(self) -> None:
    # Write peer status to file
    lans = sorted(self.lans, key=lambda v: v.nic.name)
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
      (site for peer in self.peers for site in peer.routed_sites if site not in lans))
    output_file= self.log_dir / self.LOCAL_NETWORKS_TABLE_FILENAME
    _write_output(output_file, lans)
          

  def _write_reachable_networks_files(self,
      reachable: Iterable[UvnPeerLanStatus],
      unreachable: Iterable[UvnPeerLanStatus]) -> None:
    def _write_output(output_file: Path, statuses: Iterable[UvnPeerLanStatus]) -> None:
      if not statuses:
        output_file.write_text("")
        return
      with output_file.open("w") as output:
        for peer_status in statuses:
          if peer_status.lan in lans:
            continue
          output.writelines(" ".join([
              f"{peer_status.lan.nic.subnet.network_address}/{peer_status.lan.nic.netmask}",
              str(lan.nic.address),
              # str(peer_status.lan.gw),
              "\n"
            ]) for lan in lans)

    lans = sorted(self.lans, key=lambda v: v.nic.name)
    output_file: Path = self.log_dir / self.REACHABLE_NETWORKS_TABLE_FILENAME
    _write_output(output_file, reachable)
    # output_file: Path = self.root / self.UNREACHABLE_NETWORKS_TABLE_FILENAME
    # _write_output(output_file, unreachable)


  def _write_particle_configurations(self) -> None:
    if self.particles_dir.is_dir():
      shutil.rmtree(self.particles_dir)
    if not self.enable_particles_vpn:
      return
    for particle_id, particle_client_cfg in self.particles_vpn_config.peer_configs.items():
      particle = self.uvn_id.particles[particle_id]
      write_particle_configuration(particle, particle_client_cfg, self.particles_dir)


  def reload(self, new_config: dict, save_to_disk: bool=False) -> bool:
    log.activity("[AGENT] parsing received configuration")
    updated_agent = CellAgent.deserialize(new_config, self.root)
    updaters = []

    if updated_agent.uvn_id.generation_ts != self.uvn_id.generation_ts:
      if updated_agent.cell.id != self.cell.id:
        raise RuntimeError("cell id cannot be changed", self.cell.id, updated_agent.cell.id)

      def _update_uvn_id():
        self._uvn_id = updated_agent.uvn_id
        self.cell = self.uvn_id.cells[self.cell.id]
        self.peers.uvn_id = self.uvn_id
        # self.ns = Nameserver(self.root, db=self.uvn_id.hosts)
        # self.ns.assert_records(self.ns_records())
      log.warning(f"[AGENT] UVN configuration changed: {self.uvn_id.generation_ts} -> {updated_agent.uvn_id.generation_ts}")
      updaters.append(_update_uvn_id)
    
    if updated_agent.root_vpn_config.generation_ts != self.root_vpn_config.generation_ts:
      def _update_root_vpn():
        self.root_vpn_config = updated_agent.root_vpn_config
        self.root_vpn = WireGuardInterface(self.root_vpn_config)
      log.warning(f"[AGENT] Root VPN configuration changed: {self.root_vpn_config.generation_ts} -> {updated_agent.root_vpn_config.generation_ts}")
      updaters.append(_update_root_vpn)

    if updated_agent.deployment.generation_ts != self.deployment.generation_ts:
      def _update_deployment():
        # self.ns.clear()
        self._deployment = updated_agent.deployment
        self.backbone_vpn_configs = list(updated_agent.backbone_vpn_configs)
        self.backbone_vpns = [WireGuardInterface(v) for v in self.backbone_vpn_configs]
        self._regenerate_plots()
      log.warning(f"[AGENT] Backbone Deployment changed: {self.deployment.generation_ts} -> {updated_agent.deployment.generation_ts}")
      updaters.append(_update_deployment)

    if updated_agent.particles_vpn_config.generation_ts != self.particles_vpn_config.generation_ts:
      def _update_particles_vpn():
        self.particles_vpn_config = updated_agent.particles_vpn_config
        self.particles_vpn = (
          WireGuardInterface(self.particles_vpn_config.root_config)
          if self.enable_particles_vpn else None
        )
      log.warning(f"[AGENT] Particles VPN configuration changed: {self.particles_vpn_config.generation_ts} -> {updated_agent.particles_vpn_config.generation_ts}")
      updaters.append(_update_particles_vpn)

    if updaters:
      log.warning(f"[AGENT] stopping services to load new configuration...")
      self._stop()
      log.activity(f"[AGENT] peforming updates...")
      for updater in updaters:
        updater()
      # Save configuration to disk if requested
      if save_to_disk:
        self.save_to_disk()
      log.activity(f"[AGENT] restarting services with new configuration...")
      self._start()
      log.warning(f"[AGENT] new configuration loaded: uvn_id={self.uvn_id.generation_ts}, root_vpn={self.root_vpn_config.generation_ts}, particles_vpn={self.particles_vpn_config.generation_ts}, backbone={self.deployment.generation_ts}")
      return True
    else:
      log.activity(f"[AGENT] no changes in configuration detected")

    return False


  def save_to_disk(self) -> Path:
    config_file = self.root / Registry.AGENT_CONFIG_FILENAME
    serialized = self.serialize(persist=True)
    config = yaml.safe_dump(serialized)
    config_file.write_text("")
    config_file.chmod(0o600)
    config_file.write_text(config)
    log.activity(f"[AGENT] configuration file UPDATED: {config_file}")
    return config_file


  def serialize(self, persist: bool=False) -> dict:
    serialized = {
      "uvn_id": self.uvn_id.serialize(),
      "cell_id": self.cell.id,
      "registry_id": self.registry_id,
      "deployment": self.deployment.serialize(),
      # "ns": self.ns.serialize(orig=persist),
      "peers": self.peers.serialize(),
      "root_vpn_config": self.root_vpn_config.serialize(),
      "particles_vpn_config": self.particles_vpn_config.serialize(),
      "backbone_vpn_configs": [
        v.serialize() for v in self.backbone_vpn_configs
      ],
    }
    if not serialized["cell_id"]:
      del serialized["cell_id"]
    # if not serialized["ns"]:
    #   del serialized["ns"]
    if not serialized["backbone_vpn_configs"]:
      del serialized["backbone_vpn_configs"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict,
      root: Path,
      **init_args) -> "CellAgent":
    return CellAgent(
      root=root,
      uvn_id=UvnId.deserialize(serialized["uvn_id"]),
      cell_id=serialized["cell_id"],
      registry_id=serialized["registry_id"],
      deployment=P2PLinksMap.deserialize(serialized["deployment"]),
      root_vpn_config=WireGuardConfig.deserialize(serialized["root_vpn_config"]),
      particles_vpn_config=CentralizedVpnConfig.deserialize(
        serialized["particles_vpn_config"],
        settings_cls=ParticlesVpnSettings),
      backbone_vpn_configs=[
        WireGuardConfig.deserialize(v)
        for v in serialized.get("backbone_vpn_configs", [])
      ],
      **init_args)


  @staticmethod
  def generate(
      registry: Registry,
      cell: CellId,
      output_dir: Path) -> Path:
    # Check that the uvn has been deployed
    if not registry.deployed:
      raise RuntimeError("uvn not deployed")

    # Generate agent in a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)

    package_extra_files: Sequence[Path] = []

    # # Export all keys to a common directory
    # keys_dir = tmp_dir / "gpg"

    # id_db = IdentityDatabase(registry.root)

    # # Export the cell's private key
    # agent_pubkey, agent_privkey, agent_pass = id_db.export_key(
    #   cell,
    #   with_privkey=True,
    #   with_passphrase=True,
    #   output_dir=keys_dir)
    
    # # Export the UVN's public key
    # uvn_pubkey, _, _ = id_db.export_key(
    #   registry.uvn_id,
    #   output_dir=keys_dir)

    # # Export the public key for all other cells
    # other_keys = []
    # for other in (c for c in registry.uvn_id.cells.values() if c != cell):
    #   other_pubkey, _, _ = id_db.export_key(
    #     other,
    #     output_dir=keys_dir)
    #   other_keys.append(other_pubkey)
    
    # package_extra_files.append(keys_dir)

    # # Store the cell id in a separate file
    # cell_id_file = tmp_dir / "cell.id"
    # cell_id_file.write_text(str(cell.id))
    # package_extra_files.append(cell_id_file)

    # # Store the uvn id in a separate file
    # uvn_id_file = tmp_dir / "uvn.id"
    # uvn_id_file.write_text(yaml.safe_dump(registry.uvn_id.serialize()))
    # package_extra_files.append(uvn_id_file)


    # Write agent config
    cell_agent = CellAgent(
      root=tmp_dir,
      uvn_id=registry.uvn_id,
      cell_id=cell.id,
      registry_id=registry.id,
      deployment=registry.backbone_vpn_config.deployment,
      root_vpn_config=registry.root_vpn_config.peer_configs[cell.id],
      particles_vpn_config=registry.particles_vpn_configs[cell.id],
      backbone_vpn_configs=registry.backbone_vpn_config.peer_configs[cell.id]
        if registry.backbone_vpn_config.peer_configs else [])
    agent_config = cell_agent.save_to_disk()

    # # Always sign with the UVN's root key
    # agent_config_sig = id_db.sign_file(
    #   owner_id=registry.uvn_id,
    #   input_file=agent_config,
    #   output_dir=tmp_dir)

    # # Encrypt signature with agent owner's key
    # agent_config_sig_enc = id_db.encrypt_file(
    #   cell, agent_config_sig, tmp_dir)

    # # Encrypt package with the agent owner's key
    # agent_config_enc = id_db.encrypt_file(
    #   cell, agent_config, tmp_dir)

    # agent_license = tmp_dir / Registry.AGENT_LICENSE
    # shutil.copy2(registry.rti_license, agent_license)

    # Include the RTI license file
    # Include DDS Security artifacts
    for src, dst, optional in [
        (registry.rti_license, None, True),
        (registry.dds_keymat.cert(cell.name), "cert.pem", False),
        (registry.dds_keymat.key(cell.name), "key.pem", False),
        (registry.dds_keymat.governance, "governance.p7s", False),
        (registry.dds_keymat.permissions(cell.name), "permissions.p7s", False),
        (registry.dds_keymat.ca.cert, "ca-cert.pem", False),
        (registry.dds_keymat.perm_ca.cert, "perm-ca-cert.pem", False),
      ]:
      dst = dst or src.name
      tgt = tmp_dir / dst
      if optional and not src.exists():
        continue
      shutil.copy2(src, tgt)
      package_extra_files.append(tgt)

    # Store all files in a single archive
    agent_package = output_dir / f"{cell.name}.uvn-agent"
    agent_package.parent.mkdir(parents=True, exist_ok=True)
    exec_command(
      ["tar", "cJf", agent_package,
        # agent_config_sig_enc.relative_to(tmp_dir),
        # agent_config_enc.relative_to(tmp_dir),
        agent_config.relative_to(tmp_dir),
        *(f.relative_to(tmp_dir) for f in package_extra_files)],
      cwd=tmp_dir)
  
    out_config = output_dir / f"{cell.name}.yaml"
    shutil.copy2(agent_config, out_config)

    log.warning(f"[AGENT] package generated: {agent_package}")

    return agent_package


  @staticmethod
  def extract(
      package: Path,
      root: Path) -> "CellAgent":
    # Extract package to a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)

    # log.debug(f"[AGENT] extracting package contents: {package}")
    log.warning(f"[AGENT] installing agent from package {package} to {root}")

    package = package.resolve()

    log.activity(f"[AGENT] extracting package contents: {tmp_dir}")
    exec_command(["tar", "xvJf", package], cwd=tmp_dir)

    # # Read the cell id
    # uvn_id_file = tmp_dir / "uvn.id"
    # uvn_id = UvnId.deserialize(yaml.safe_load(uvn_id_file.read_text()))
    # cell_id_file = tmp_dir / "cell.id"
    # cell_id = int(cell_id_file.read_text())
    # cell = uvn_id.cells[cell_id]

    # Create output directory
    # log.debug(f"[AGENT] bootstrapping cell {cell} of UVN {uvn_id} to {root}")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    root.chmod(0o755)
    
    # Make agent directory readable only by agent's user (i.e. root)

    # # Generate a GPG database by importing the keys
    # gpg = IdentityDatabase(root)
    # keys_dir = tmp_dir / "gpg"
    
    # # Import the cell's private key
    # cell_pubkey_file = keys_dir / f"{cell.name}.pub"
    # cell_privkey_file = keys_dir / f"{cell.name}.key"
    # cell_pass_file = keys_dir / f"{cell.name}.pass"
    # gpg.import_key(
    #   owner_id=cell,
    #   pubkey=cell_pubkey_file.read_text(),
    #   privkey=cell_privkey_file.read_text(),
    #   passphrase=cell_pass_file.read_text(),
    #   save_passphrase=True)

    # # Import the UVN's public key
    # uvn_key_file = keys_dir / f"{uvn_id.name}.pub"
    # gpg.import_key(uvn_id, pubkey=uvn_key_file.read_text())

    # # Import other cell's public keys
    # for other in (c for c in uvn_id.cells.values() if c != cell):
    #   other_key_file = keys_dir / f"{other.name}.pub"
    #   gpg.import_key(other, pubkey=other_key_file.read_text())

    # # Decrypt and verify agent configuration
    # agent_config_sig_enc = tmp_dir / f"{Registry.AGENT_CONFIG_FILENAME}{GpgDatabase.EXT_SIGNED}{GpgDatabase.EXT_ENCRYPTED}"
    # agent_config_sig = gpg.decrypt_file(
    #   owner_id=cell,
    #   input_file=agent_config_sig_enc,
    #   output_dir=root)
    # agent_config_enc = tmp_dir / f"{Registry.AGENT_CONFIG_FILENAME}{GpgDatabase.EXT_ENCRYPTED}"
    # gpg.decrypt_file(
    #   owner_id=cell,
    #   input_file=agent_config_enc,
    #   signature_file=agent_config_sig,
    #   output_dir=root)

    # # Copy agent configuration to root
    # agent_config_tmp = tmp_dir / Registry.AGENT_CONFIG_FILENAME
    # agent_config = root / Registry.AGENT_CONFIG_FILENAME
    # exec_command(["cp", agent_config_tmp, agent_config])

    # # Copy RTI license
    # agent_license_tmp = tmp_dir / Registry.AGENT_LICENSE
    # agent_license = root / Registry.AGENT_LICENSE
    # exec_command(["cp", agent_license_tmp, agent_license])

    for f, permissions in {
        Registry.AGENT_CONFIG_FILENAME: 0o600,
        "rti_license.dat": 0o600,
        "governance.p7s": 0o600,
        "permissions.p7s": 0o600,
        "key.pem": 0o600,
        "cert.pem": 0o644,
        "ca-cert.pem": 0o644,
        "perm-ca-cert.pem": 0o644,
      }.items():
      src = tmp_dir / f
      dst = root / f
      shutil.copy2(src, dst)
      dst.chmod(permissions)

    # Load the imported agent
    log.activity(f"[AGENT] loading imported agent: {root}")
    agent = CellAgent.load(root)
    log.warning(f"[AGENT] bootstrap completed: {agent.cell}@{agent.uvn_id} [{agent.root}]")

    agent.net.generate_configuration()

    return agent


  @staticmethod
  def load(root: Path, **init_args) -> "CellAgent":
    config_file = root / Registry.AGENT_CONFIG_FILENAME
    serialized = yaml.safe_load(config_file.read_text())
    agent = CellAgent.deserialize(serialized, root=root, **init_args)
    return agent
