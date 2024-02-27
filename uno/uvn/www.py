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
from functools import partial
import os
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
import shutil
import json
from typing import TYPE_CHECKING, Iterable
import threading
import subprocess

from .data import www as www_data
from importlib.resources import as_file, files

import yaml

from .render import Templates
from .time import Timestamp
from .exec import exec_command

if TYPE_CHECKING:
  from .agent import CellAgent
from .log import Logger as log

from http.server import SimpleHTTPRequestHandler, HTTPServer

class UvnHttpd:
  LIGHTTPD_CONF_TEMPLATE = """\
server.modules = ("mod_openssl", "mod_auth", "mod_authn_file")
server.port = 443
server.pid-file = "{{pid_file}}"
server.document-root = "{{root}}"
server.errorlog = "{{log_dir}}/lighttpd.error.log"
accesslog.filename = "{{log_dir}}/lighttpd.access.log"
ssl.engine = "enable"
ssl.pemfile = "{{pem_file}}"
index-file.names = ( "index.html" )
mimetype.assign = (
  ".html" => "text/html", 
  ".txt" => "text/plain",
  ".jpg" => "image/jpeg",
  ".png" => "image/png" 
)
"""

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
    self._lighttpd_pem.chmod(0o400)
    log.debug(f"[WWW] SSL certificate: {self._lighttpd_pem}")
    

  def _generate_index_html(self) -> None:
    log.debug("[WWW] regenerating agent status...")

    index_html = self.root / "index.html"

    index_html.write_text(Templates.render("www/index.html", {
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
    }))
    
    # Copy particle configurations if they exist
    if self.agent.particle_configurations_dir.is_dir():
      particles_dir_www = self.root / "particles"
      if particles_dir_www.is_dir():
        shutil.rmtree(particles_dir_www)
      shutil.copytree(self.agent.particle_configurations_dir, particles_dir_www)

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

      conf_tmplt = Templates.compile(self.LIGHTTPD_CONF_TEMPLATE)
      conf = Templates.render(conf_tmplt, {
        "root": self.root,
        "port": self.port,
        "addresses": addresses,
        "pid_file": self._lighttpd_pid,
        "pem_file": self._lighttpd_pem,
        "log_dir": self.agent.log_dir,
        # "fakeroot": Path(self._fakeroot.name),
      })
      self._lighttpd_conf.parent.mkdir(parents=True, exist_ok=True)
      self._lighttpd_conf.write_text(conf)

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
      log.activity(f"[WWW] listening on port 443")
    except Exception as e:
      self._lighttpd_pid = None
      self._lighttpd = None
      log.error("failed to start lighttpd")
      log.exception(e)
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
    except Exception as e:
      log.error(f"[WWW] error while stopping:")
      log.exception(e)
      if lighttpd_stopped:
        log.error(f"[WWW] failed to stop lighttpd. Please check your system.")
    finally:
      self._lighttpd_pid = None
      self._lighttpd = None
      self._fakeroot = None
      log.activity(f"[WWW] stopped")



  # def start(self, addresses: Iterable[str]) -> None:
  #   assert(not self._http_servers)

  #   port = 8080

  #   def _http_thread(server, address):
  #     try:
  #       log.warning(f"[HTTPD] now serving {address}:{port}")
  #       with server:
  #         server.serve_forever()
  #     except Exception as e:
  #       log.error(f"[HTTPD] error in thread serving {address}:{port}")
  #       log.exception(e)
  #       raise e

  #   self._http_servers = {
  #     a: HTTPServer((str(a), port),
  #       partial(SimpleHTTPRequestHandler,
  #         directory=self.root))
  #       for a in addresses
  #   }

  #   self._http_threads = {
  #     a: threading.Thread(
  #       target=_http_thread,
  #       args=[self._http_servers[a], a])
  #     for a in addresses
  #   }
  #   for t in self._http_threads:
  #     t.start()


  # def stop(self) -> None:
  #   if self._http_servers:
  #     for s in self._http_servers.values():
  #       s.shutdown()
  #     for t in self._http_threads.values():
  #       t.join()
  #     self._http_servers = {}
  #     self._http_threads = {}
