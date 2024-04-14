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
from typing import Generator, Callable
from pathlib import Path
from functools import cached_property

import markdown
import jinja2

from .time import Timestamp
import ipaddress

from .log import Logger

log = Logger.sublogger("render")


def humanbytes(B):
  "Return the given bytes as a human friendly KB, MB, GB, or TB string"
  B = float(B)
  KB = float(1024)
  MB = float(KB**2)  # 1,048,576
  GB = float(KB**3)  # 1,073,741,824
  TB = float(KB**4)  # 1,099,511,627,776
  if B < KB:
    return "{0} {1}".format(B, "B")
  elif KB <= B < MB:
    return "{0:.2f} KB".format(B / KB)
  elif MB <= B < GB:
    return "{0:.2f} MB".format(B / MB)
  elif GB <= B < TB:
    return "{0:.2f} GB".format(B / GB)
  elif TB <= B:
    return "{0:.2f} TB".format(B / TB)


def _filter_time_since(ts: str | Timestamp) -> str:
  if not ts or (isinstance(ts, str) and ts.startswith("19700101-000000-000000")):
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


def _filter_ip_default_route(addr: str):
  from .ip import ipv4_get_route

  try:
    route = ipv4_get_route(ipaddress.ip_address(addr))
    return str(route)
  except Exception as e:
    log.error(f"failed to get route to address: {addr}")
    log.exception(e)
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


def _filter_pluralize(number: int, singular: str = "", plural: str = "s"):
  if number == 1:
    return singular
  else:
    return plural


OutputProcessor = Callable[[str], str]


class _Templates:
  def __init__(self):
    self._env = jinja2.Environment(
      # loader=jinja2.PackageLoader("uno", package_path="templates"),
      loader=jinja2.FileSystemLoader(Path(__file__).parent.parent / "templates"),
      autoescape=jinja2.select_autoescape(["html", "xml"]),
      extensions=["jinja2.ext.i18n"],
    )
    self._env.filters["time_since"] = _filter_time_since
    self._env.filters["format_ts"] = _filter_format_ts
    self._env.filters["ip_default_route"] = _filter_ip_default_route
    self._env.filters["humanbytes"] = humanbytes
    self._env.filters["yaml"] = _filter_yaml
    self._env.filters["format_hash"] = _filter_format_hash
    self._env.filters["pluralize"] = _filter_pluralize

  def registry_filters(self, **filters) -> None:
    self._env.filters.update(filters)

  def template(self, name: str) -> jinja2.Template:
    return self._env.get_template(name)

  def compile(self, template: str) -> jinja2.Template:
    return jinja2.Template(template)

  def render_lines(self, template: str | jinja2.Template, ctx: dict) -> Generator[str, None, None]:
    if not isinstance(template, jinja2.Template):
      template = self.template(template)
    return template.generate(ctx)

  def render(
    self,
    template: str | jinja2.Template,
    ctx: dict,
    processors: list[OutputProcessor] | None = None,
  ) -> str:
    if not isinstance(template, jinja2.Template):
      template = self.template(template)
    rendered = template.render(ctx)
    for processor in processors or []:
      rendered = processor(rendered)
    return rendered

  def generate(
    self,
    output: Path,
    template: str | jinja2.Template,
    ctx: dict,
    mode: int = 0o644,
    processors: list[OutputProcessor] | None = None,
  ) -> None:
    import tempfile
    from .exec import exec_command

    tmp_f_h = tempfile.NamedTemporaryFile()
    tmp_f = Path(tmp_f_h.name)
    tmp_f.chmod(mode=mode)
    if processors is None:
      # generate file line by line
      with tmp_f.open("wt") as output_stream:
        for line in self.render_lines(template, ctx):
          output_stream.write(line)
    else:
      # Render file with processors
      rendered = self.render(template, ctx, processors=processors)
      with tmp_f.open("wt") as output_stream:
        output_stream.write(rendered)
    exec_command(["cp", "-av", tmp_f, output])

  def markdown_to_html(self, md_text: str) -> str:
    return markdown.markdown(
      md_text,
      extensions=[
        "tables",
        "toc",
        "sane_lists",
        "md_in_html",
        "pymdownx.superfences",
        "uno.core.pm_attr_list",
        # "pymdownx.highlight",
        # "fenced_code",
        # "codehilite",
      ],
    )

  @cached_property
  def pygments_css(self) -> str:
    from pygments.formatters import HtmlFormatter

    return HtmlFormatter().get_style_defs(".highlight")


Templates = _Templates()
