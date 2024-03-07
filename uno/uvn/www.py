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

if TYPE_CHECKING:
  from .cell_agent import CellAgent

from .log import Logger as log


class UvnHttpd:
  def __init__(self, agent: "CellAgent"):
    self.agent = agent
    self.min_update_delay = self.agent.uvn_id.settings.timing_profile.status_min_delay
    self.root = self.agent.root / "www"
    self.doc_root = self.root / "root"
    self.port = 8080
    self._http_servers = {}
    self._http_threads = {}
    self._last_update_ts = None
    self._dirty = True
    self._lighttpd_pid = None
    self._lighttpd_conf = self.agent.root / "lighttpd.conf"
    self._lighttpd_pem =  self.agent.root / "lighttpd.pem"
    self._fakeroot = None


  def update(self) -> None:
    if (not self._dirty and self._last_update_ts
      and Timestamp.now().subtract(self._last_update_ts) < self.min_update_delay):
      return
    self._last_update_ts = Timestamp.now()
    UvnHttpd.index_html(
      www_root=self.root,
      peers=self.agent.peers,
      deployment=self.agent.deployment,
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


  def _assert_ssl_cert(self, regenerate: bool=True) -> None:
    log.debug(f"[WWW] creating server SSL certificate")
    if self._lighttpd_pem.is_file():
      if not regenerate:
        return
      self._lighttpd_pem.unlink()

    country_id = "US"
    state_id = "Denial"
    location_id = "Springfield"
    org_id = self.agent.uvn_id.name
    common_name = self.agent.cell.name
    pem_subject = f"/C={country_id}/ST={state_id}/L={location_id}/O={org_id}/CN={common_name}"
    exec_command([
      "openssl",
        "req",
        "-x509",
        "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:secp384r1",
        "-keyout", self._lighttpd_pem,
        "-out",  self._lighttpd_pem,
        "-days", "365",
        "-nodes",
        "-subj", pem_subject,
    ])
    self._lighttpd_pem.chmod(0o600)
    log.debug(f"[WWW] SSL certificate: {self._lighttpd_pem}")
    

  @staticmethod
  def index_html(
      www_root: Path,
      peers: UvnPeersList,
      deployment: P2PLinksMap,
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


  def start(self, addresses: Iterable[str]) -> None:
    if self._lighttpd_pid is not None:
      raise RuntimeError("httpd already started")

    # Addresses are not used for anything at the moment
    addresses = list(addresses)
    lighttpd_started = False
    try:
      self._lighttpd_pid = self._lighttpd_conf.parent / "lighttpd.pid"

      # self._fakeroot = TemporaryDirectory()
      self._assert_ssl_cert()

      htdigest = self._lighttpd_conf.parent / "lighttpd.auth"
      if self.agent.uvn_id.master_secret is None:
        htdigest.write_text("")
      else:
        with htdigest.open("wt") as output:
          output.write(self.agent.uvn_id.master_secret + "\n")
      htdigest.chmod(0o600)

      self._lighttpd_conf.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      Templates.generate(self._lighttpd_conf, "httpd/lighttpd.conf", {
        "root": self.root,
        "port": self.port,
        "addresses": addresses,
        "pid_file": self._lighttpd_pid,
        "pem_file": self._lighttpd_pem,
        "log_dir": self.agent.log_dir,
        "htdigest": htdigest,
        "auth_realm": self.agent.uvn_id.name,
        # "fakeroot": Path(self._fakeroot.name),
      })

      # Delete pid file if it exists
      if self._lighttpd_pid.is_file():
        self._lighttpd_pid.unlink()

      # Make sure that required directories exist
      self.root.mkdir(parents=True, exist_ok=True)
      self._lighttpd_pid.parent.mkdir(parents=True, exist_ok=True)
      
      # Start lighttpd in daemon mode
      log.debug(f"[WWW] starting lighttpd...")
      # exec_command(["lighttpd", "-D", "-f", self._lighttpd_conf],
      #   fail_msg="failed to start lighttpd")
      self._lighttpd = subprocess.Popen(["lighttpd", "-D", "-f", self._lighttpd_conf])
      lighttpd_started = True

      # Wait for lighttpd to come online and
      max_wait = 5
      pid = None
      for i in range(max_wait):
        log.debug("[WWW] waiting for lighttpd to come online...")
        if self._lighttpd_pid.is_file():
          try:
            pid = int(self._lighttpd_pid.read_text())
            break
          except:
            continue
        time.sleep(1)
      if pid is None:
        raise RuntimeError("failed to detect lighttpd process")
      log.debug(f"[WWW] lighttpd started: pid={pid}")
      log.warning(f"[WWW] listening on 0.0.0.0:443")
    except Exception as e:
      self._lighttpd_pid = None
      self._lighttpd = None
      log.error("failed to start lighttpd")
      # log.exception(e)
      if lighttpd_started:
        # lighttpd was started by we couldn't detect its pid
        log.error("[WWW] lighttpd process was started but possibly not stopped. Please check your system.")
      raise e


  def stop(self) -> None:
    if self._lighttpd_pid is None:
      # Not started
      return

    lighttpd_stopped = False
    try:
      if self._lighttpd_pid.is_file():
        pid = int(self._lighttpd_pid.read_text())
        log.debug(f"[WWW] stopping lighttpd: pid={pid}")
        exec_command(["kill", "-s", "SIGTERM", str(pid)],
          fail_msg="failed to signal lighttpd process")
      # TODO(asorbini) check that lighttpd actually stopped
      lighttpd_stopped = True
      log.activity(f"[WWW] stopped")
    except Exception as e:
      log.error(f"[WWW] error while stopping:")
      if lighttpd_stopped:
        log.error(f"[WWW] failed to stop lighttpd. Please check your system.")
      raise
    finally:
      self._lighttpd_pid = None
      self._lighttpd = None
      self._fakeroot = None

