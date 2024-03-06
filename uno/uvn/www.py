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
    self._generate_index_html()
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
    

  def _generate_index_html(self) -> None:
    log.debug("[WWW] regenerating agent status...")

    index_html = self.root / "index.html"
    Templates.generate(index_html, "www/index.html", {
      "agent": self.agent,
      "cell": self.agent.cell,
      "uvn_id": self.agent.uvn_id,
      "uvn_settings": yaml.safe_dump(self.agent.uvn_id.settings.serialize()),
      "deployment": self.agent.deployment,
      "backbone_plot": self.agent.uvn_status_plot.relative_to(self.root),
      "backbone_plot_basic": self.agent.uvn_backbone_plot.relative_to(self.root)
        if self.agent.uvn_backbone_plot.is_file() else None,
      "generation_ts": self._last_update_ts.format(),
      "css_style": self.style_css,
      "vpn_stats": self.agent.vpn_stats,
      "peers_reachable": self.agent.reachable_sites,
      "peers_unreachable": self.agent.unreachable_sites,
      "fully_routed": self.agent.fully_routed,
      "clashing_sites": self.agent.peers.clashing_routed_sites,
      "peers_offline": self.agent.peers.offline_peers_count,
      "peers_online": self.agent.peers.online_peers_count,
    })

    # Copy particle configurations if they exist
    if self.agent.particles_dir.is_dir():
      particles_dir_www = self.root / "particles"
      if particles_dir_www.is_dir():
        shutil.rmtree(particles_dir_www)
      shutil.copytree(self.agent.particles_dir, particles_dir_www)

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

      self._lighttpd_conf.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      Templates.generate(self._lighttpd_conf, "httpd/lighttpd.conf", {
        "root": self.root,
        "port": self.port,
        "addresses": addresses,
        "pid_file": self._lighttpd_pid,
        "pem_file": self._lighttpd_pem,
        "log_dir": self.agent.log_dir,
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

