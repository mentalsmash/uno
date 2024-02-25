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
from functools import partial
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import json
from typing import TYPE_CHECKING
import threading

from .data import www as www_data
from importlib.resources import as_file, files

import yaml

from .render import Templates
from .time import Timestamp

if TYPE_CHECKING:
  from .agent import CellAgent
from .log import Logger as log

from http.server import SimpleHTTPRequestHandler, HTTPServer

class UvnHttpd:
  def __init__(self, agent: "CellAgent"):
    self.agent = agent
    self.min_update_delay = self.agent.uvn_id.settings.timing_profile.status_min_delay
    self.root = self.agent.root / "www"
    self._http_server = None
    self._http_thread = None
    self._started = False
    self._last_update_ts = None
    self._serve_files = False
    self._dirty = True


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
      "backbone_plot_basic": self.agent.uvn_backbone_plot.relative_to(self.root),
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
    # Copy particle configurations
    particles_dir = self.agent.root / "particles"
    particles_dir_www = self.root / "particles"
    if particles_dir_www.is_dir():
      shutil.rmtree(particles_dir_www)
    shutil.copytree(particles_dir, particles_dir_www)

    log.activity("[WWW] agent status updated")
  
  

  def start(self) -> None:
    if self._started:
      return

    self.update()
    def _http_thread(server, root):
      try:
        with server:
          server.serve_forever()
      except Exception as e:
        log.error(f"[HTTPD] error in thread:")
        log.exception(e)
        raise e

    if self._serve_files:
      self._http_server = HTTPServer(("", 8080),
        partial(SimpleHTTPRequestHandler, directory=self.root))
      self._http_thread = threading.Thread(target=_http_thread, args=[self._http_server, self.root])
      self._http_thread.start()

    self._started = True


  def stop(self) -> None:
    if not self._started:
      return
    if self._serve_files:
      self._http_server.shutdown()
      self._http_thread.join()
    self._started = False
