###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from pathlib import Path
from functools import cached_property

from ..core.exec import exec_command, shell_which
from ..core.log import Logger
from .systemd_service import SystemdService

log = Logger.sublogger("systemd")


class _Systemd:
  SERVICE_INSTALL_PATH = Path("/etc/systemd/system")

  def __init__(self) -> None:
    self._systemctl = shell_which("systemctl")

  @cached_property
  def available(self) -> bool:
    result = exec_command(
      ["ps aux | grep /sbin/init | grep -v grep"], shell=True, capture_output=True
    ).stdout
    return result and len(result.decode().strip()) > 0

  def _exec(self, *command, required: bool = True, **exec_args) -> None:
    if self._systemctl is None:
      if required:
        raise RuntimeError("systemctl not available on the system")
      else:
        log.warning(
          "systemctl not found, cannot perform: systemctl {}", " ".join(map(str, command))
        )
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
