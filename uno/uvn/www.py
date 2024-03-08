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
from typing import TYPE_CHECKING

from .data import www as www_data
from importlib.resources import as_file, files

from .time import Timestamp
from .lighttpd import Lighttpd
from .keys_dds import CertificateSubject

if TYPE_CHECKING:
  from .cell_agent import CellAgent


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
    self.agent.index_html(docroot=self.doc_root)
    self._dirty = False


  def request_update(self) -> None:
    self._dirty = True


  @property
  def style_css(self) -> str:
    with as_file(files(www_data).joinpath("style.css")) as tmp_f:
      return tmp_f.read_text()


  def start(self) -> None:
    self.root.mkdir(exist_ok=True, parents=True)
    self.doc_root.mkdir(exist_ok=True, parents=True)
    self._lighttpd.start()


  def stop(self) -> None:
    self._lighttpd.stop()

