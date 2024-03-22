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
from typing import TYPE_CHECKING, Iterable
from pathlib import Path
from functools import cached_property

from .lighttpd import Lighttpd
from ..core.time import Timestamp
from ..core.htdigest import htdigest_generate
from ..registry.certificate_subject import CertificateSubject
# from .html import index_html
from . import html as views
from .agent_service import AgentService

if TYPE_CHECKING:
  from .agent import Agent


class UvnHttpd(AgentService):
  CLASS = "www"

  @classmethod
  def check_enabled(cls, agent: "Agent") -> bool:
    return agent.config.enable_httpd


  def __init__(self, **properties):
    super().__init__(**properties)
    self.doc_root = self.root / "public"
    self._last_update_ts = None
    self._dirty = True
    self._lighttpd = None
  

  @property
  def listen_port(self) -> int:
    return self.agent.local_object.settings.httpd_port


  @property
  def min_update_delay(self) -> int:
    return self.agent.uvn.settings.timing_profile.status_min_delay


  @cached_property
  def doc_root(self) -> Path:
    doc_root = self.root / "public"
    self.mkdir(doc_root)
    return doc_root


  def spin_once(self) -> None:
    if (not self._dirty and self._last_update_ts
      and int(Timestamp.now().subtract(self._last_update_ts).total_seconds()) < self.min_update_delay):
      return
    views.index_html(self.agent, self.doc_root)
    self._last_update_ts = Timestamp.now()
    self._dirty = False


  def request_update(self) -> None:
    self._dirty = True


  def start(self, bind_addresses: Iterable[str]|None=None) -> None:
    assert(self._lighttpd is None)

    self.root.mkdir(exist_ok=True, parents=True)
    self.doc_root.mkdir(exist_ok=True, parents=True)
    
    # secret_line = htdigest_generate(user=self.agent.uvn.owner, realm=self.agent.uvn.name, password_hash=self.agent.uvn.master_secret)
    secret_line = ""

    self._lighttpd = Lighttpd(
      root=self.root,
      port=self.listen_port,
      doc_root=self.doc_root,
      log_dir=self.agent.log_dir,
      cert_subject=CertificateSubject(org=self.agent.uvn.name, cn=self.agent.local_object.name),
      secret=secret_line,
      auth_realm=self.agent.uvn.name,
      protected_paths=["^/particles"],
      bind_addresses=bind_addresses)
    self._lighttpd.start()


  def stop(self) -> None:
    self._lighttpd.stop()
    self._lighttpd = None

