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
from pathlib import Path
import time
import shutil
from typing import TYPE_CHECKING, Iterable
import subprocess

from .data import www as www_data
from importlib.resources import as_file, files

import yaml

from .render import Templates
from .time import Timestamp
from .exec import exec_command
from .peer import UvnPeersList
from .uvn_id import CellId
from .deployment import P2PLinksMap
from .wg import WireGuardInterface
from .ip import LanDescriptor
from .peer_test import UvnPeersTester
from .router import Router
from .lighttpd import Lighttpd
from .keys_dds import CertificateSubject

if TYPE_CHECKING:
  from .cell_agent import CellAgent

from .log import Logger as log


class UvnHttpd:
  def __init__(self, agent: "CellAgent"):
    self.agent = agent
    self.min_update_delay = self.agent.uvn_id.settings.timing_profile.status_min_delay
    self.root = self.agent.root / "www"
    self.doc_root = self.root / "root"
    self._last_update_ts = None
    self._dirty = True
    self._lighttpd = Lighttpd(
      root=self.root,
      doc_root=self.doc_root,
      log_dir=self.agent.log_dir,
      cert_subject=CertificateSubject(org=self.agent.uvn_id.name, cn=self.agent.cell.name),
      secret=self.agent.uvn_id.master_secret,
      auth_realm=self.agent.uvn_id.name,
      protected_paths=["^/particles"])


  def update(self) -> None:
    if (not self._dirty and self._last_update_ts
      and Timestamp.now().subtract(self._last_update_ts) < self.min_update_delay):
      return
    self._last_update_ts = Timestamp.now()
    UvnHttpd.index_html(
      www_root=self.root,
      peers=self.agent.peers,
      deployment=self.agent.deployment,
      ts_start=self.agent.ts_start,
      backbone_vpns=self.agent.backbone_vpns,
      cell=self.agent.cell,
      enable_particles_vpn=self.agent.enable_particles_vpn,
      generation_ts=self._last_update_ts,
      lans=self.agent.lans,
      particles_dir=self.agent.particles_dir,
      peers_tester=self.agent.peers_tester,
      root_vpn=self.agent.root_vpn,
      router=self.agent.router,
      style_css=self.style_css,
      uvn_status_plot=self.agent.uvn_status_plot,
      uvn_backbone_plot=self.agent.uvn_backbone_plot,
      vpn_stats=self.agent.vpn_stats)
    self._dirty = False


  def request_update(self) -> None:
    self._dirty = True


  @property
  def style_css(self) -> str:
    with as_file(files(www_data).joinpath("style.css")) as tmp_f:
      return tmp_f.read_text()


  @staticmethod
  def index_html(
      www_root: Path,
      peers: UvnPeersList,
      deployment: P2PLinksMap,
      ts_start: Timestamp,
      backbone_vpns: Iterable[WireGuardInterface]|None=None,
      cell: CellId|None=None,
      enable_particles_vpn: bool=False,
      generation_ts: Timestamp|None=None,
      lans: Iterable[LanDescriptor]|None=None,
      particles_dir: Path|None=None,
      particles_vpn: WireGuardInterface|None=None,
      peers_tester: UvnPeersTester|None=None,
      root_vpn: WireGuardInterface|None=None,
      router: Router|None=None,
      style_css: str|None=None,
      uvn_status_plot: Path|None=None,
      uvn_backbone_plot: Path|None=None,
      vpn_stats: dict|None=None) -> None:
    log.debug("[WWW] regenerating agent status...")

    # Copy particle configurations if they exist
    if particles_dir and particles_dir.is_dir():
      particles_dir_www = www_root / "particles"
      if particles_dir_www.is_dir():
        shutil.rmtree(particles_dir_www)
      shutil.copytree(particles_dir, particles_dir_www)

    if router:
      router.ospf_summary()
      router.ospf_lsa()
      router.ospf_routes()
      ospf_dir = www_root / "ospf"
      ospf_summary = ospf_dir / f"{router.ospf_summary_f.name}.txt"
      ospf_lsa = ospf_dir / f"{router.ospf_lsa_f.name}.txt"
      ospf_routes = ospf_dir / f"{router.ospf_routes_f.name}.txt"
      if ospf_dir.is_dir():
        shutil.rmtree(ospf_dir)
      ospf_dir.mkdir(exist_ok=True)
      shutil.copy2(router.ospf_summary_f, ospf_summary)
      shutil.copy2(router.ospf_lsa_f, ospf_lsa)
      shutil.copy2(router.ospf_routes_f, ospf_routes)

    index_html = www_root / "index.html"

    online_peers = sum(1 for c in peers.online_cells)
    offline_peers = sum(1 for c in peers.cells) - online_peers

    Templates.generate(index_html, "www/index.html", {
      "cell": cell,
      "css_style": style_css or "",
      "deployment": deployment,
      "enable_particles_vpn": enable_particles_vpn,
      "backbone_plot": uvn_status_plot.relative_to(www_root)
        if uvn_status_plot and uvn_status_plot.exists() else None,
      "backbone_plot_basic": uvn_backbone_plot.relative_to(www_root)
        if uvn_backbone_plot and uvn_backbone_plot.exists() else None,
      "backbone_vpns": list(backbone_vpns or []),
      "generation_ts": (generation_ts or Timestamp.now()).format(),
      "lans": list(lans or []),
      "particles_vpn": particles_vpn,
      "peers": peers,
      "peers_offline": offline_peers,
      "peers_online": online_peers,
      "peers_tester": peers_tester,
      "registry_id": peers.registry_id or "",
      "root_vpn": root_vpn,
      "router": router,
      "ospf_summary": ospf_summary.relative_to(www_root),
      "ospf_lsa": ospf_lsa.relative_to(www_root),
      "ospf_routes": ospf_routes.relative_to(www_root),
      "ts_start": ts_start.format() if ts_start else None,
      "uvn_id": peers.uvn_id,
      "uvn_settings": yaml.safe_dump(peers.uvn_id.settings.serialize()),
      "vpn_stats": vpn_stats or {
        "interfaces": {},
        "traffic": {
          "rx": 0,
          "tx": 0,
        },
      },
    })

    log.debug("[WWW] agent status updated")


  def start(self) -> None:
    self.root.mkdir(exist_ok=True, parents=True)
    self.doc_root.mkdir(exist_ok=True, parents=True)
    self._lighttpd.start()


  def stop(self) -> None:
    self._lighttpd.stop()

