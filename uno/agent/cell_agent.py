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

from ..registry.uvn import Uvn
from ..registry.database import Database
from ..core.wg import WireGuardConfig, WireGuardInterface
from .peer import UvnPeersList, UvnPeer, VpnInterfaceStatus
from .tester import UvnPeersTester
from .dds_data import cell_agent_status
from .render import Templates
from .agent import Agent
from ..core.log import Logger as log
from ..core.exec import exec_command
from ..core.time import Timestamp
from ..registry.key_id import KeyId
from ..registry.dds import UvnTopic
from ..registry.lan_descriptor import LanDescriptor
from ..registry.registry import Registry
from ..registry.vpn_config import P2pLinksMap, CentralizedVpnConfig


class CellAgent(Agent):
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
      uvn: Uvn,
      cell_id: int,
      registry_id: str,
      deployment: P2pLinksMap,
      backbone_vpn_configs: Sequence[WireGuardConfig]|None=None,
      particles_vpn_config: CentralizedVpnConfig|None=None,
      root_vpn_config: WireGuardConfig|None=None) -> None:
    
    self._uvn = uvn
    self._deployment = deployment
    self._registry_id = registry_id

    self._cell = self.uvn.cells[cell_id]

    self.root_vpn = (
      WireGuardInterface(root_vpn_config)
      if root_vpn_config else None
    )

    self.backbone_vpns = [WireGuardInterface(v) for v in backbone_vpn_configs or []]

    self.particles_vpn_config = particles_vpn_config
    self.particles_vpn = (
      WireGuardInterface(self.particles_vpn_config.root_config)
      if self.particles_vpn_config else None
    )
    self._root: Path = root.resolve()

    self._peers = UvnPeersList(
      uvn=self.uvn,
      registry_id=self.registry_id,
      local_peer_id=cell_id)
    self._peers.listeners.append(self)

    self.peers_tester = UvnPeersTester(self,
      max_test_delay=self.uvn.settings.timing_profile.tester_max_delay)


    # Only enable HTTP server if requested
    self.enable_www = False

    super().__init__()

    self._finish_import_package()


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
      vpn.config.intf.address
        for vpn in self.backbone_vpns
    }
    initial_peers = [
      *backbone_peers,
      *([self.root_vpn.config.peers[0].address] if self.root_vpn else []),
    ]
    initial_peers = [f"[0]@{p}" for p in initial_peers]

    key_id = KeyId.from_uvn(self.cell)
    Templates.generate(self.participant_xml_config, "dds/uno.xml", {
      "uvn": self.uvn,
      "cell": self.cell,
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
    return (self.participant_xml_config, CellAgent.TOPICS)


  def _on_started(self, boot: bool=False) -> None:
    # Write particle configuration to disk
    self._write_particle_configurations()
    self._write_cell_info()


  def _parse_received_configuration(self) -> None:
    pass


  def _on_spin(self,
      ts_start: Timestamp,
      ts_now: Timestamp,
      spin_len: float) -> None:
    super()._on_spin(
      ts_start=ts_start,
      ts_now=ts_now,
      spin_len=spin_len)

    self.www.spin_once()


  def _on_agent_config_received(self, package: bytes, config: str) -> None:
    try:
      use_package = False

      # Cache received data to file and trigger handling
      tmp_file_h = tempfile.NamedTemporaryFile()
      tmp_file = Path(tmp_file_h.name)
      if len(package) > 0:
        with tmp_file.open("wb") as output:
          output.write(package)
        use_package = True
      elif len(config) > 0:
        tmp_file.write_text(config)
      else:
        # nothing to reload
        log.debug(f"[AGENT] found nothing to reload")
        return

      tmp_dir_h = tempfile.TemporaryDirectory()
      tmp_dir = Path(tmp_dir_h.name)

      if use_package:
        log.activity(f"[AGENT] extracting received package: {tmp_file}")
        CellAgent.extract(tmp_file, tmp_dir, config_only=True)
        config_file = tmp_dir / Registry.AGENT_CONFIG_FILENAME
        load_agent = lambda: CellAgent.extract(package, tmp_dir)
      else:
        log.activity(f"[AGENT] parsing received configuration: {tmp_file}")
        key = self.root / "key.pem"
        key = self.id_db.backend[self.cell]
        config_file = tmp_dir / Registry.AGENT_CONFIG_FILENAME
        self.id_db.backend.decrypt_file(key, tmp_file, config_file)
        def _generate_agent_root():
          shutil.copytree(self.id_db.backend.root, tmp_dir / self.id_db.backend.root.relative_to(self.root))
          return CellAgent.load(tmp_dir)
        load_agent = _generate_agent_root

      # TODO(asorbini) preserve and copy the new agent's additional files

      # Read registry_id from received config and ignore it if invalid
      # or equal to the  current one
      agent_config = yaml.safe_load(config_file.read_text()) or {}
      registry_id = agent_config.get("registry_id")
      if (not isinstance(registry_id, str)
          or not registry_id
          or self.registry_id == registry_id):
        # invalid or same config, ignore it
        log.debug(f"[AGENT] ignoring invalid configuration: {registry_id}")
        return

      # Load an agent instance from the updated configuration
      reload_agent = load_agent()
    except Exception as e:
      log.error(f"[AGENT] failed to parse/load updated configuration")
      log.exception(e)
      return
  
    self.schedule_reload(reload_agent)


  def _on_reader_data(self,
      topic: UvnTopic,
      reader: dds.DataReader,
      info: dds.SampleInfo,
      sample: dds.DynamicData) -> None:
    if topic == UvnTopic.BACKBONE:
      if sample["registry_id"] == self.registry_id:
        log.debug(f"[AGENT] ignoring current configuration: {self.registry_id}")
      else:
        self._on_agent_config_received(
          package=sample["package"],
          config=sample["config"])
    else:
      super()._on_reader_data(
        topic=topic,
        reader=reader,
        info=info,
        sample=sample)


  def _write_cell_info(self) -> None:
    sample = cell_agent_status(
      participant=self.dp,
      uvn=self.uvn,
      cell_id=self.cell.id,
      registry_id=self.registry_id,
      ts_start=self.init_ts,
      lans=self.lans,
      reachable_networks=[n.lan for n in self.peers.local.reachable_networks],
      unreachable_networks=[n.lan for n in self.peers.local.unreachable_networks])
    self.dp.writers[UvnTopic.CELL_ID].write(sample)
    log.activity(f"[AGENT] published cell info: {self.cell}")


  def on_event_online_cells(self,
      new_cells: set[UvnPeer],
      gone_cells: set[UvnPeer]) -> None:
    super().on_event_online_cells(new_cells, gone_cells)
    self.uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_all_cells_connected(self) -> None:
    super().on_event_all_cells_connected()


  def on_event_registry_connected(self) -> None:
    super().on_event_registry_connected()
    self.uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_routed_networks(self, new_routed, gone_routed) -> None:
    super().on_event_routed_networks(new_routed, gone_routed)
    self.peers_tester.trigger()
    self.uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_consistent_config_cells(self, new_consistent, gone_consistent) -> None:
    super().on_event_consistent_config_cells(new_consistent, gone_consistent)


  def on_event_consistent_config_uvn(self) -> None:
    super().on_event_consistent_config_uvn()


  def on_event_local_reachable_networks(self, new_reachable: set[LanDescriptor], gone_reachable: set[LanDescriptor]) -> None:
    super().on_event_local_reachable_networks(new_reachable, gone_reachable)
    self._write_cell_info()
    self.uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_reachable_networks(self, new_reachable, gone_reachable) -> None:
    super().on_event_reachable_networks(new_reachable, gone_reachable)
    self.uvn_status_plot_dirty = True
    self.www.request_update()


  def on_event_fully_routed_uvn(self) -> None:
    super().on_event_fully_routed_uvn()


  def on_event_local_routes(self, new_routes: set[str], gone_routes: set[str]) -> None:
    super().on_event_local_routes(new_routes, gone_routes)
    self.peers_tester.trigger()
    self.www.request_update()


  def on_event_vpn_connections(self, new_online: set[VpnInterfaceStatus], gone_online: set[VpnInterfaceStatus]) -> None:
    super().on_event_vpn_connections(new_online, gone_online)
    self.www.request_update()


  def find_backbone_peer_by_address(self, addr: str | ipaddress.IPv4Address) -> Optional[UvnPeer]:
    addr = ipaddress.ip_address(addr)
    for vpn in self.backbone_vpns:
      if vpn.config.peers[0].address == addr:
        return self.peers[vpn.config.peers[0].id]
      elif vpn.config.intf.address == addr:
        return self.peers.local
    return None


  def _write_particle_configurations(self) -> None:
    if self.particles_dir.is_dir():
      shutil.rmtree(self.particles_dir)
    if not self.particles_vpn_config:
      return
    for particle_id, particle_client_cfg in self.particles_vpn_config.peer_configs.items():
      particle = self.uvn.particles[particle_id]
      write_particle_configuration(particle, self.cell, particle_client_cfg, self.particles_dir)


  def _reload(self, updated_agent: "CellAgent") -> None:
    self._uvn = updated_agent.uvn
    self._cell = self.uvn.cells[self.cell.id]
    self.id_db.uvn = self.uvn
    self.peers.uvn = self.uvn
    self.peers.registry_id = updated_agent.registry_id
    self.root_vpn = (
      WireGuardInterface(updated_agent.root_vpn.config)
      if updated_agent.root_vpn else None
    )
    self._deployment = updated_agent.deployment
    self.backbone_vpns = [WireGuardInterface(v.config) for v in updated_agent.backbone_vpns]
    self.uvn_backbone_plot_dirty = True
    self.uvn_status_plot_dirty = True
    self.particles_vpn_config = updated_agent.particles_vpn_config
    self.particles_vpn = (
      WireGuardInterface(self.particles_vpn_config.root_config)
      if self.particles_vpn_config else None
    )
    self._vpn_stats_update = True
    self._vpn_stats = None
    self._registry_id = updated_agent.registry_id


  # def save_to_disk(self) -> Path:
  #   config_file = self.root / Registry.AGENT_CONFIG_FILENAME
  #   serialized = self.serialize(persist=True)
  #   config = yaml.safe_dump(serialized)
  #   config_file.write_text("")
  #   config_file.chmod(0o600)
  #   config_file.write_text(config)
  #   log.activity(f"[AGENT] configuration file UPDATED: {config_file}")
  #   return config_file


  # def serialize(self, persist: bool=False) -> dict:
  #   serialized = {
  #     "uvn": self.uvn.serialize(),
  #     "cell_id": self.cell.id,
  #     "registry_id": self.registry_id,
  #     "deployment": self.deployment.serialize(),
  #     "root_vpn_config": self.root_vpn.config.serialize() if self.root_vpn else None,
  #     "particles_vpn_config": self.particles_vpn_config.serialize()
  #       if self.particles_vpn_config else None,
  #     "backbone_vpn_configs": [
  #       v.config.serialize() for v in self.backbone_vpns
  #     ],
  #   }
  #   if not serialized["root_vpn_config"]:
  #     del serialized["root_vpn_config"]
  #   if not serialized["particles_vpn_config"]:
  #     del serialized["particles_vpn_config"]
  #   if not serialized["cell_id"]:
  #     del serialized["cell_id"]
  #   # if not serialized["ns"]:
  #   #   del serialized["ns"]
  #   if not serialized["backbone_vpn_configs"]:
  #     del serialized["backbone_vpn_configs"]
  #   return serialized


  # @staticmethod
  # def deserialize(serialized: dict,
  #     root: Path,
  #     **init_args) -> "CellAgent":
  #   particles_vpn_config = serialized.get("particles_vpn_config")
  #   if particles_vpn_config:
  #     particles_vpn_config = CentralizedVpnConfig.deserialize(
  #       particles_vpn_config,
  #       settings_cls=ParticlesVpnSettings)
  #   root_vpn_config = serialized.get("root_vpn_config")
  #   if root_vpn_config:
  #     root_vpn_config = WireGuardConfig.deserialize(root_vpn_config)
  #   return CellAgent(
  #     root=root,
  #     uvn=Uvn.deserialize(serialized["uvn"]),
  #     cell_id=serialized["cell_id"],
  #     registry_id=serialized["registry_id"],
  #     deployment=P2pLinksMap.deserialize(serialized["deployment"]),
  #     root_vpn_config=root_vpn_config,
  #     particles_vpn_config=particles_vpn_config,
  #     backbone_vpn_configs=[
  #       WireGuardConfig.deserialize(v)
  #       for v in serialized.get("backbone_vpn_configs", [])
  #     ],
  #     **init_args)


  def _finish_import_package(self) -> None:
    id_db_dir = self.root / ".id-import"
    if not id_db_dir.is_dir():
      return

    # Load the imported agent
    log.activity("[AGENT] loading imported agent")

    package_files = [
      f.relative_to(id_db_dir)
        for f in id_db_dir.glob("**/*")
    ]
    self.id_db.import_keys(id_db_dir, package_files)
    self.net.generate_configuration()
    exec_command(["rm", "-rf", id_db_dir])

    log.warning("[AGENT] bootstrap completed: {}@{} [{}]", self.cell, self.uvn, self.root)


  @staticmethod
  def open(db: Database) -> "CellAgent":
    return CellAgent(db)
    # config_file = root / Registry.AGENT_CONFIG_FILENAME
    # serialized = yaml.safe_load(config_file.read_text())
    # agent = CellAgent.deserialize(serialized, root=root, **init_args)
    # return agent

