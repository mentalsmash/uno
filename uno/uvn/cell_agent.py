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
import shutil
from pathlib import Path
from typing import Mapping, Sequence, Iterable, Optional
import ipaddress
import yaml
import tempfile

from .uvn_id import UvnId, CellId, ParticlesVpnSettings
from .wg import WireGuardConfig, WireGuardInterface
from .ip import (
  list_local_networks,
  ipv4_from_bytes,
  ipv4_get_route,
  LanDescriptor,
  NicDescriptor,
)
from .ns import NameserverRecord
from .dds import DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList, UvnPeer
from .exec import exec_command
from .vpn_config import P2PLinksMap, CentralizedVpnConfig
from .peer_test import UvnPeersTester, UvnPeerLanStatus
from .time import Timestamp
from .www import UvnHttpd
from .particle import write_particle_configuration
from .graph import cell_agent_status_plot
from .render import Templates
from .dds_data import dns_database, cell_agent_status
from .agent_net import AgentNetworking
from .router import Router
from .agent import Agent
from .id_db import IdentityDatabase
from .keys_dds import DdsKeysBackend
from .keys import KeyId
from .log import Logger as log


class CellAgent(Agent):
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

    self._cell = self.uvn_id.cells[cell_id]

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

    id_db_backend = DdsKeysBackend(
      root=self.root / "id",
      org=self.uvn_id.name,
      generation_ts=self.uvn_id.generation_ts,
      init_ts=self.uvn_id.init_ts)

    self._id_db = IdentityDatabase(
      backend=id_db_backend,
      local_id=self.cell,
      uvn_id=self.uvn_id)

    # Store configuration upon receiving it, so we can reload it
    # once we're done processing received data
    self._reload_config = None
    self._reload_package_h = None

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
  def cell(self) -> CellId:
    return self._cell


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
  def id_db(self) -> IdentityDatabase:
    return self._id_db


  @property
  def root_vpn_id(self) -> str:
    return self.root_vpn.config.generation_ts if self.root_vpn else None


  @property
  def backbone_vpn_ids(self) -> list[str]:
    return [nic.config.generation_ts for nic in self.backbone_vpns]


  @property
  def particles_vpn_id(self) -> Optional[str]:
    return self.particles_vpn_config.generation_ts


  @property
  def backbone_peers(self) -> list[int]:
    return [p.id for nic in self.backbone_vpns for p in nic.config.peers]


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
      bool(self.uvn_id.particles)
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

    key_id = KeyId.from_uvn_id(self.cell)
    Templates.generate(self.participant_xml_config, "dds/uno.xml", {
      "deployment_id": self.deployment.generation_ts,
      "uvn": self.uvn_id,
      "cell": self.cell,
      "initial_peers": initial_peers,
      "timing": self.uvn_id.settings.timing_profile,
      "license_file": self.rti_license.read_text(),
      "ca_cert": self.id_db.backend.ca.cert,
      "perm_ca_cert": self.id_db.backend.perm_ca.cert,
      "cert": self.id_db.backend.cert(key_id),
      "key": self.id_db.backend.key(key_id),
      "governance": self.id_db.backend.governance,
      "permissions": self.id_db.backend.permissions(key_id),
      "enable_dds_security": False,
    })

    return DdsParticipantConfig(
      participant_xml_config=self.participant_xml_config,
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
      errors.append(e)
    try:
      self.peers_tester.stop()
    except Exception as e:
      log.error(f"[AGENT] failed to stop peers tester")
      errors.append(e)
    try:
      self.fully_routed = False
    except Exception as e:
      log.error(f"[AGENT] failed to reset fully-routed state")
      errors.append(e)
    try:
      self.unreachable_sites = []
    except Exception as e:
      log.error(f"[AGENT] failed to reset unreachable sites")
      errors.append(e)
    try:
      self.reachable_sites = []
    except Exception as e:
      log.error(f"[AGENT] failed to reset reachable sites")
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
    if self._reload_config or self._reload_package_h:
      new_config = self._reload_config
      new_package_h = self._reload_package_h
      self._reload_config = None
      self._reload_package_h = None
      # Parse/save/load new configuration
      self.reload(package=new_package_h, config=new_config, save_to_disk=True)

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


  def _on_agent_config_received(self, package: object|None=None, config: str|None=None) -> None:
    if self._reload_package_h or self._reload_config:
      log.warning(f"[AGENT] discarding previously scheduled reload")
    if package:
      self._reload_package_h = package
      self._reload_config = None
      log.warning(f"[AGENT] package received from registry")
    else:
      self._reload_package_h = None
      self._reload_config = config
      log.warning(f"[AGENT] configuration received from registry")


  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    if topic == UvnTopic.DNS:
      self._on_dns_data(info.instance_handle, sample)
    elif topic == UvnTopic.BACKBONE:

      try:
        tmp_h = tempfile.NamedTemporaryFile()
        tmp = Path(tmp_h.name)
        if len(sample["package"]) > 0:
          with tmp.open("wb") as output:
            output.write(sample["package"])
          self._on_agent_config_received(package=tmp_h)
        elif len(sample["config"]) > 0:
          tmp.write_text(sample["config"])
          self._on_agent_config_received(config=tmp_h)
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
    log.activity(f"[AGENT] published cell info: {self.cell}")


  def _write_dns(self) -> None:
    sample = dns_database(
      participant=self.dp,
      uvn_id=self.uvn_id,
      ns=self.ns,
      server_name=self.cell.name)
    self.dp.writers[UvnTopic.DNS].write(sample)
    log.activity(f"[AGENT] published DNS info: {self.cell}")


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


  def reload(self, package: object|None=None, config: object|None=None, save_to_disk: bool=False) -> bool:
    try:
      tmp_dir_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_dir_h.name)

      if package:
        log.activity("[AGENT] extracting received package")
        package_h = package
        package = Path(package_h.name)
        updated_agent = CellAgent.extract(package, tmp_dir)
      elif config is not None:
        log.activity("[AGENT] parsing received configuration")
        key = self.root / "key.pem"
        config_h = config
        config = Path(config_h.name)
        config_file = tmp_dir / Registry.AGENT_CONFIG_FILENAME

        key = self.id_db.backend[self.cell]
        self.id_db.backend.decrypt_file(key, config, config_file)
        # shutil.copy2(self.ca.cert, tmp_dir / self.ca.cert.name)
        shutil.copytree(self.id_db.backend.root, tmp_dir / self.id_db.backend.root.relative_to(self.root))
        updated_agent = CellAgent.load(tmp_dir)
      else:
        raise ValueError("invalid arguments")
    except Exception as e:
      log.error(f"[AGENT] failed to parse received configuration")
      log.exception(e)
      return False

    updaters = []

    if updated_agent.registry_id != self.registry_id:
      def _update_registry_id():
        self._registry_id = updated_agent.registry_id
      updaters.append(_update_registry_id)

    if updated_agent.uvn_id.generation_ts != self.uvn_id.generation_ts:
      if updated_agent.cell.id != self.cell.id:
        raise RuntimeError("cell id cannot be changed", self.cell.id, updated_agent.cell.id)

      def _update_uvn_id():
        self._uvn_id = updated_agent.uvn_id
        self._cell = self.uvn_id.cells[self.cell.id]
        self.id_db.uvn_id = self.uvn_id
        self.peers.uvn_id = self.uvn_id
        # self.ns = Nameserver(self.root, db=self.uvn_id.hosts)
        # self.ns.assert_records(self.ns_records())
      log.warning(f"[AGENT] UVN configuration changed: {self.uvn_id.generation_ts} → {updated_agent.uvn_id.generation_ts}")
      updaters.append(_update_uvn_id)
    
    if updated_agent.root_vpn_config.generation_ts != self.root_vpn_config.generation_ts:
      def _update_root_vpn():
        self.root_vpn_config = updated_agent.root_vpn_config
        self.root_vpn = WireGuardInterface(self.root_vpn_config)
      log.warning(f"[AGENT] Root VPN configuration changed: {self.root_vpn_config.generation_ts} → {updated_agent.root_vpn_config.generation_ts}")
      updaters.append(_update_root_vpn)

    if updated_agent.deployment.generation_ts != self.deployment.generation_ts:
      def _update_deployment():
        # self.ns.clear()
        self._deployment = updated_agent.deployment
        self.backbone_vpn_configs = list(updated_agent.backbone_vpn_configs)
        self.backbone_vpns = [WireGuardInterface(v) for v in self.backbone_vpn_configs]
        self._regenerate_plots()
      log.warning(f"[AGENT] Backbone Deployment changed: {self.deployment.generation_ts} → {updated_agent.deployment.generation_ts}")
      updaters.append(_update_deployment)

    if updated_agent.particles_vpn_config.generation_ts != self.particles_vpn_config.generation_ts:
      def _update_particles_vpn():
        self.particles_vpn_config = updated_agent.particles_vpn_config
        self.particles_vpn = (
          WireGuardInterface(self.particles_vpn_config.root_config)
          if self.enable_particles_vpn else None
        )
      log.warning(f"[AGENT] Particles VPN configuration changed: {self.particles_vpn_config.generation_ts} → {updated_agent.particles_vpn_config.generation_ts}")
      updaters.append(_update_particles_vpn)

    if updaters:
      log.warning(f"[AGENT] stopping services to load new configuration...")
      self._stop()
      log.warning(f"[AGENT] peforming updates...")
      for updater in updaters:
        updater()
      # Save configuration to disk if requested
      if save_to_disk:
        self.save_to_disk()
        if package:
          extracted_files = list(tmp_dir.glob("*"))
          exec_command(["cp", "-rv", *extracted_files, self.root])
      log.activity(f"[AGENT] restarting services with new configuration...")
      self._start()
      log.warning(f"[AGENT] new configuration loaded: uvn_id={self.uvn_id.generation_ts}, root_vpn={self.root_vpn_config.generation_ts}, particles_vpn={self.particles_vpn_config.generation_ts}, backbone={self.deployment.generation_ts}")
      return True
    else:
      log.warning(f"[AGENT] no changes in configuration detected")

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

    id_dir = tmp_dir / "id"
    exported_keymat = registry.id_db.export_keys(
      output_dir=id_dir,
      target=cell)
    for f in exported_keymat:
      package_extra_files.append(id_dir / f)

    for src, dst, optional in [
        (registry.rti_license, None, False),
      ]:
      dst = dst or src.name
      tgt = tmp_dir / dst
      if optional and not src.exists():
        continue
      shutil.copy2(src, tgt)
      package_extra_files.append(tgt)

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

    # Store all files in a single archive
    agent_package = output_dir / f"{cell.name}.uvn-agent"
    agent_package.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    exec_command(
      ["tar", "cJf", agent_package,
        agent_config.relative_to(tmp_dir),
        *(f.relative_to(tmp_dir) for f in package_extra_files)],
      cwd=tmp_dir)
    agent_package.chmod(0o600)

    log.warning(f"[AGENT] package generated: {agent_package}")

    return agent_package


  @staticmethod
  def extract(
      package: Path,
      root: Path) -> "CellAgent":
    # Extract package to a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)

    log.warning(f"[AGENT] installing agent from package {package} to {root}")

    package = package.resolve()

    log.activity(f"[AGENT] extracting package contents: {tmp_dir}")
    exec_command(["tar", "xvJf", package], cwd=tmp_dir)

    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    root.chmod(0o755)

    for f, permissions in {
        Registry.AGENT_CONFIG_FILENAME: 0o600,
        "rti_license.dat": 0o600,
      }.items():
      src = tmp_dir / f
      dst = root / f
      shutil.copy2(src, dst)
      dst.chmod(permissions)

    # Load the imported agent
    log.activity(f"[AGENT] loading imported agent: {root}")
    agent = CellAgent.load(root)
    id_db_dir = tmp_dir / "id"
    package_files = [
      f.relative_to(id_db_dir)
        for f in id_db_dir.glob("**/*")
    ]
    agent.id_db.import_keys(id_db_dir, package_files)
    log.warning(f"[AGENT] bootstrap completed: {agent.cell}@{agent.uvn_id} [{agent.root}]")

    agent.net.generate_configuration()

    return agent


  @staticmethod
  def load(root: Path, **init_args) -> "CellAgent":
    config_file = root / Registry.AGENT_CONFIG_FILENAME
    serialized = yaml.safe_load(config_file.read_text())
    agent = CellAgent.deserialize(serialized, root=root, **init_args)
    return agent

