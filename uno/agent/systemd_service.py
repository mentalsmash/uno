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
from functools import cached_property

from ..registry.versioned import Versioned

from .render import Templates

class SystemdService(Versioned):
  STATIC_SERVICES_MARKER_DIR = Path("/run/uno/services")

  PROPERTIES = [
    "name",
  ]

  REQ_PROPERTIES = [
    "name",
  ]

  RO_PROPERTIES = [
    "name",
  ]

  STR_PROPERTIES = [
    "name",
    "parent",
  ]

  EQ_PROPERTIES = [
    "name",
    "parent",
  ]


  @cached_property
  def service_file_name(self) -> str:
    return f"{self.name}.service"


  @cached_property
  def service_file(self) -> Path:
    return self.root / self.service_file_name


  @cached_property
  def marker_file(self) -> Path:
    return self.STATIC_SERVICES_MARKER_DIR / self.service_file_name


  @cached_property
  def root(self) -> Path:
    raise NotImplementedError()


  @property
  def template_context(self) -> dict:
    raise NotImplementedError()


  @property
  def config_id(self) -> str:
    raise NotImplementedError()


  @property
  def template_id(self) -> str:
    return f"service/{self.service_file.name}"


  @property
  def active(self) -> bool:
    return self.current_marker is not None


  @property
  def current_marker(self) -> str | None:
    if self.marker_file.exists():
      return self.marker_file.read_text()
    else:
      return None


  def check_marker_compatible(self) -> None:
    current_marker = self.current_marker
    compatible = current_marker is None or current_marker == self.config_id
    if not compatible:
      self.log.error("service already started as a systemd unit with different configuration")
      self.log.error("- systemd config: {}", self.current_marker)
      self.log.error("- current config: {}", self.config_id)
      raise RuntimeError("stop systemd unit", self)


  def generate_service_file(self) -> None:
    self.service_file.parent.mkdir(exist_ok=True, parents=True)
    Templates.generate(self.service_file, self.template_id, self.template_context, mode=0o644)


  def write_marker(self) -> None:
    self.marker_file.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    self.marker_file.write_text(self.config_id)
    self.log.activity("created marker: {}", self.marker_file)


  def delete_marker(self) -> None:
    if self.marker_file.exists():
      self.marker_file.unlink()

