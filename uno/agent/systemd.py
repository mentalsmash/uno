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

from ..core.exec import exec_command, shell_which
from ..core.log import Logger
log = Logger.sublogger("systemd")

from .systemd_service import SystemdService

class _Systemd:
  SERVICE_INSTALL_PATH = Path("/etc/systemd/system")

  def __init__(self) -> None:
    self._systemctl = shell_which("systemctl")


  @cached_property
  def available(self) -> bool:
    result = exec_command([
      "ps aux | grep /sbin/init | grep -v grep"
    ], shell=True, capture_output=True).stdout
    return result and len(result.decode().strip()) > 0


  def _exec(self, *command, required: bool=True, **exec_args) -> None:
    if self._systemctl is None:
      if required:
        raise RuntimeError("systemctl not available on the system")
      else:
        log.warning("systemctl not found, cannot perform: systemctl {}", ' '.join(map(str, command)))
        return
    return exec_command(["systemctl", *command], **exec_args)


  def install_service(self, svc: SystemdService) -> Path:
    self.remove_service(svc)
    svc.generate_service_file()
    install_svc_file = self.SERVICE_INSTALL_PATH / svc.service_file.name
    install_svc_file.symlink_to(svc.service_file)
    self._reload_configuration()
    log.info("installed service: {}", install_svc_file)


  def remove_service(self, svc: SystemdService) -> None:
      install_svc_file = self.SERVICE_INSTALL_PATH / svc.service_file.name
      if install_svc_file.exists():
        self.stop_service(svc)
        self.disable_service(svc)
        if install_svc_file.exists():
          install_svc_file.unlink()
        log.info("deleted service: {}", install_svc_file)


  def _reload_configuration(self) -> None:
    self._exec("daemon-reload", required=False)


  def enable_service(self, svc: SystemdService) -> None:
    self._exec("enable", svc.service_file.stem)
    log.info("enabled at boot: {}", svc)


  def disable_service(self, svc: SystemdService) -> None:
    self._exec("disable", svc.service_file.stem, required=False)
    log.info("disabled from boot: {}", svc)


  def start_service(self, svc: SystemdService) -> None:
    self._exec("start", svc.service_file.stem)
    log.info("started: {}", svc)


  def stop_service(self, svc: SystemdService) -> None:
    self._exec("stop", svc.service_file.stem, required=False)
    log.info("stopped: {}", svc)
  

Systemd = _Systemd()

