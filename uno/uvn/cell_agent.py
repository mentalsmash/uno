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
from typing import Mapping, Sequence, Tuple, Optional
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
from .dds import DdsParticipantConfig, UvnTopic
from .registry import Registry
from .peer import UvnPeersList, UvnPeer
from .exec import exec_command
from .vpn_config import P2PLinksMap, CentralizedVpnConfig
from .peer_test import UvnPeersTester
from .time import Timestamp
from .www import UvnHttpd
from .particle import write_particle_configuration
from .graph import cell_agent_status_plot
from .render import Templates
from .dds_data import cell_agent_status
from .agent_net import AgentNetworking
from .router import Router
from .agent import Agent
from .id_db import IdentityDatabase
from .keys_dds import DdsKeysBackend
from .keys import KeyId
from .log import Logger as log


class CellAgent(Agent):
  PARTICIPANT_PROFILE = "UnoParticipants::CellAgent"
  TOPICS = {
    "writers": [
      UvnTopic.CELL_ID,
    ],

    "readers": {
      UvnTopic.CELL_ID: {},
      UvnTopic.UVN_ID: {},
      UvnTopic.BACKBONE: {},
    }
  }

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
      registry_id=self.registry_id,
      local_peer_id=cell_id)
    self._peers.listeners.append(self)

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
    self._uvn_status_plot_dirty = True

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
  def services(self) -> list[Tuple["Agent.Service", dict]]:
    return [
      *super().services,
      (self.peers_tester, {}),
      *([(self.www, {
        "addresses": [
          "localhost",
          *(vpn.config.intf.address for vpn in self.vpn_interfaces),
          *(l.nic.address for l in self.lans),
        ],
      })] if self.enable_www else []),
    ]


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


  @property
  def uvn_status_plot(self) -> Path:
    status_plot = self.www.root / "uvn-status.png"
    if not status_plot.is_file() or self._uvn_status_plot_dirty:
      cell_agent_status_plot(self, status_plot, seed=self.create_ts)
      self._uvn_status_plot_dirty = False
      log.debug(f"[AGENT] status plot generated: {status_plot}")
    return status_plot


  @property
  def dds_xml_config(self) -> Tuple[str, str, dict]:
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
    return (self.participant_xml_config, CellAgent.PARTICIPANT_PROFILE, CellAgent.TOPICS)


  @property
  def user_conditions(self) -> list[dds.GuardCondition]:
    return [
      *super().user_conditions,
      self.routes_monitor.updated_condition,
      self.peers_tester.result_available_condition,
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


  def _on_started(self, boot: bool=False) -> None:
    # Write particle configuration to disk
    self._write_particle_configurations()
    self._write_cell_info()


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

    self.www.update()

    super()._on_spin(
      ts_start=ts_start,
      ts_now=ts_now,
      spin_len=spin_len)
  


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
    if topic == UvnTopic.BACKBONE:
      if sample["registry_id"] == self.registry_id:
        log.debug(f"[AGENT] ignoring current configuration: {self.registry_id}")
        return
      try:
        # Cache received data to file and trigger handling
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
    else:
      super()._on_reader_data(
        topic=topic,
        reader=reader,
        info=info,
        sample=sample)


  def _on_user_condition(self, condition: dds.GuardCondition):
    if condition == self.peers_tester.result_available_condition:#
      pass
    else:
      super()._on_user_condition(condition)


  def _write_cell_info(self) -> None:
    sample = cell_agent_status(
      participant=self.dp,
      uvn_id=self.uvn_id,
      cell_id=self.cell.id,
      registry_id=self.registry_id,
      lans=self.lans,
      reachable_networks=self.peers.local.reachable_networks,
      unreachable_networks=self.peers.local.reachable_networks)
    self.dp.writers[UvnTopic.CELL_ID].write(sample)
    log.activity(f"[AGENT] published cell info: {self.cell}")


  def on_event_online_cells(self,
      new_cells: set[UvnPeer],
      gone_cells: set[UvnPeer]) -> None:
    super().on_event_online_cells(new_cells, gone_cells)
    self._uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_all_cells_connected(self) -> None:
    super().on_event_all_cells_connected()


  def on_event_registry_connected(self) -> None:
    super().on_event_registry_connected()
    self._uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_routed_networks(self, new_routed, gone_routed) -> None:
    super().on_event_routed_networks(new_routed, gone_routed)
    self.peers_tester.trigger()
    self._uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_consistent_config_cells(self, new_consistent, gone_consistent) -> None:
    super().on_event_consistent_config_cells(new_consistent, gone_consistent)


  def on_event_consistent_config_uvn(self) -> None:
    super().on_event_consistent_config_uvn()


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    super().on_event_local_reachable_networks(new_reachable, gone_reachable)
    self._write_cell_info()
    self._uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_reachable_networks(self, new_reachable, gone_reachable) -> None:
    super().on_event_reachable_networks(new_reachable, gone_reachable)
    self._uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_fully_routed_uvn(self) -> None:
    super().on_event_fully_routed_uvn()


  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    super().on_event_local_routes(new_routes, gone_routes)
    self.peers_tester.trigger()
    self.www.request_update()


  def find_backbone_peer_by_address(self, addr: str | ipaddress.IPv4Address) -> Optional[UvnPeer]:
    addr = ipaddress.ip_address(addr)
    for bbone in self.backbone_vpn_configs:
      if bbone.peers[0].address == addr:
        return self.peers[bbone.peers[0].id]
      elif bbone.intf.address == addr:
        return self.peers.local
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
        self.peers.registry_id = updated_agent.registry_id
      updaters.append(_update_registry_id)

    if updated_agent.uvn_id.generation_ts != self.uvn_id.generation_ts:
      if updated_agent.cell.id != self.cell.id:
        raise RuntimeError("cell id cannot be changed", self.cell.id, updated_agent.cell.id)

      def _update_uvn_id():
        self._uvn_id = updated_agent.uvn_id
        self._cell = self.uvn_id.cells[self.cell.id]
        self.id_db.uvn_id = self.uvn_id
        self.peers.uvn_id = self.uvn_id
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
        self._deployment = updated_agent.deployment
        self.backbone_vpn_configs = list(updated_agent.backbone_vpn_configs)
        self.backbone_vpns = [WireGuardInterface(v) for v in self.backbone_vpn_configs]
        self._uvn_backbone_plot_dirty = True
        self._uvn_status_plot_dirty = True
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

