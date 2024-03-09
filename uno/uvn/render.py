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
from typing import Generator, Union, TYPE_CHECKING, Optional, Tuple
from datetime import timedelta
from pathlib import Path

import jinja2

from .time import Timestamp
from .ip import LanDescriptor
import ipaddress

if TYPE_CHECKING:
  from .peer import UvnPeer, UvnPeersList
  from .tester import UvnPeersTester
  from .wg import WireGuardInterface


def humanbytes(B):
  'Return the given bytes as a human friendly KB, MB, GB, or TB string'
  B = float(B)
  KB = float(1024)
  MB = float(KB ** 2) # 1,048,576
  GB = float(KB ** 3) # 1,073,741,824
  TB = float(KB ** 4) # 1,099,511,627,776
  if B < KB:
    return '{0} {1}'.format(B,'B')
  elif KB <= B < MB:
    return '{0:.2f} KB'.format(B/KB)
  elif MB <= B < GB:
    return '{0:.2f} MB'.format(B/MB)
  elif GB <= B < TB:
    return '{0:.2f} GB'.format(B/GB)
  elif TB <= B:
    return '{0:.2f} TB'.format(B/TB)


def _filter_time_since(ts: str | Timestamp) -> str:
  if not ts:
    return "N/A"
  if isinstance(ts, str):
    ts = Timestamp.parse(ts)
  diff = Timestamp.now().subtract(ts)
  mm, ss = divmod(diff.seconds, 60)
  hh, mm = divmod(mm, 60)
  result = []
  if diff.days:
    result.append(f"{diff.days}d")
  if hh:
    result.append(f"{hh}h")
  if mm:
    result.append(f"{mm}m")
  if ss or not result:
    result.append(f"{ss}s")
  result.append("ago")
  return " ".join(result)


def _filter_format_ts(ts: str | Timestamp) -> str:
  if not ts:
    return "N/A"
  if isinstance(ts, str):
    ts = Timestamp.parse(ts)
  return ts.format("%b %m %Y, %I:%M%p")


def _filter_find_lan_status_by_peer(peer_id: int, peers_tester: "UvnPeersTester") -> list[Tuple[LanDescriptor, bool]]:
  return peers_tester.find_status_by_peer(peer_id)


def _filter_ip_default_route(addr: str):
  from .ip import ipv4_get_route
  try:
    route = ipv4_get_route(ipaddress.ip_address(addr))
    return str(route)
  except Exception as e:
    from .log import Logger as log
    log.error(f"failed to get route to address: {addr}")
    log.exception(e)
    return None


def _filter_find_backbone_peer_by_address(addr: str, peers: "UvnPeersList", backbone_vpns: "list[WireGuardInterface]") -> Optional["UvnPeer"]:
  if not addr:
    return None
  addr = ipaddress.ip_address(addr)
  for bbone in backbone_vpns:
    if bbone.config.peers[0].address == addr:
      return peers[bbone.config.peers[0].id]
    elif bbone.config.intf.address == addr:
      return peers.local
  return None


def _filter_yaml(val: object) -> str:
  import yaml
  serializer = getattr(val, "serialize", None)
  if serializer:
    val = serializer()
  return yaml.safe_dump(val)


def _filter_format_hash(val: str) -> str:
  if len(val) <= 11:
    return val
  return val[:4] + "..." + val[-4:]


class _Templates:
  def __init__(self):
    self._env = jinja2.Environment(
      loader=jinja2.PackageLoader("uno.uvn", package_path="templates"),
      autoescape=jinja2.select_autoescape(['html', 'xml']))

    self._env.filters["time_since"] = _filter_time_since
    self._env.filters["format_ts"] = _filter_format_ts
    self._env.filters["find_lan_status_by_peer"] = _filter_find_lan_status_by_peer
    self._env.filters["ip_default_route"] = _filter_ip_default_route
    self._env.filters["find_backbone_peer_by_address"] = _filter_find_backbone_peer_by_address
    self._env.filters["humanbytes"] = humanbytes
    self._env.filters["yaml"] = _filter_yaml
    self._env.filters["format_hash"] = _filter_format_hash


  def template(self, name: str) -> jinja2.Template:
    return self._env.get_template(name)


  def compile(self, template: str) -> jinja2.Template:
    return jinja2.Template(template)


  def render_lines(self, template: Union[str, jinja2.Template], ctx: dict) -> Generator[str, None, None]:
    if not isinstance(template, jinja2.Template):
      template = self.template(template)
    return template.generate(ctx)


  def render(self, template: Union[str, jinja2.Template], ctx: dict) -> str:
    if not isinstance(template, jinja2.Template):
      template = self.template(template)
    return template.render(ctx)


  def generate(self, output: Path, template: str|jinja2.Template, ctx: dict, mode: int=0o644) -> None:
    import tempfile
    from .exec import exec_command
    tmp_f_h = tempfile.NamedTemporaryFile()
    tmp_f = Path(tmp_f_h.name)
    tmp_f.chmod(mode=mode)
    with tmp_f.open("wt") as output_stream:
      for line in self.render_lines(template, ctx):
        output_stream.write(line)
    exec_command(["cp", "-a", tmp_f, output])


Templates = _Templates()
