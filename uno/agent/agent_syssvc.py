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
from typing import Iterable, Optional
from pathlib import Path
import shutil
from importlib.resources import as_file, files
import subprocess
import os

from ..core.wg import WireGuardInterface
from ..data import service as service_data
from ..registry.lan_descriptor import LanDescriptor
from ..core.exec import exec_command
from ..core.log import Logger as log
from .render import Templates
from .router import Router


def _sha256sum(input: Path) -> str:
  result = exec_command(["sha256sum", input], capture_output=True).stdout
  stdout = (result.decode("utf-8") if result else "").strip()
  if not stdout:
    raise RuntimeError("failed to get sha256 checksum", input)
  cksum = stdout.split(" ")[0]
  if len(cksum) != 64:
    raise RuntimeError("invalid checksum generated", input, cksum)
  return cksum


class UvnService:
  @property
  def service_description(self) -> Path:
    return Path(f"/etc/systemd/system/{self}")


  def __str__(self) -> str:
    raise NotImplementedError()


  def extra_files(self) -> Iterable[Path]:
    return []


  def enabled(self) -> bool:
    raise NotImplementedError()


  def stop(self) -> None:
    raise NotImplementedError()


  def install(self, reload: bool=False) -> None:
    existed = self.service_description.exists()
    if existed:
      self.remove()
    # for output, svc_file in CellAgent.SYSTEMD_SERVICES.items():
    with as_file(files(service_data).joinpath(self.service_description.name)) as input:
      exec_command(["cp", "--no-preserve=mode,ownership", "-v", input, self.service_description])
      self.service_description.chmod(0o644)
    if reload and existed:
      exec_command(["systemctl", "daemon-reload"])
    log.warning(f"[SERVICE] service definition installed: {self.service_description}")
    

  def remove(self) -> None:
    if self.enabled():
      self.stop()
    existed = self.service_description.exists()
    if existed:
      self.disable_boot()
    exec_command(["rm", "-vf", self.service_description, *self.extra_files()])
    if existed:
      exec_command(["systemctl", "daemon-reload"])
      log.warning(f"[SERVICE] service definition removed: {self.service_description}")


  def enable_boot(self) -> None:
    log.activity(f"[SERVICE] enabling at boot: {self}")
    exec_command(["systemctl", "enable", self.service_description.stem])
    log.warning(f"[SERVICE] enabled at boot: {self}")


  def disable_boot(self) -> None:
    log.activity(f"[SERVICE] removing from boot: {self}")
    exec_command(["systemctl", "disable", self.service_description.stem])
    log.warning(f"[SERVICE] removed from boot: {self}")


  def start(self) -> None:
    log.activity(f"[SERVICE] starting {self}")
    exec_command(["systemctl", "start", self.service_description.stem])
    log.warning(f"[SERVICE] started: {self}")


  def restart(self) -> None:
    log.activity(f"[SERVICE] restarting {self}")
    exec_command(["systemctl", "restart", self.service_description.stem])
    log.warning(f"[SERVICE] restarted: {self}")


  def stop(self) -> None:
    log.activity(f"[SERVICE] stopping {self}")
    exec_command(["systemctl", "stop", self.service_description.stem])
    log.warning(f"[SERVICE] stopped {self}")


class UvnNetService(UvnService):
  def __init__(self, root: bool=False) -> None:
    self._root = root


  def __str__(self) -> str:
    if self._root:
      return "uvn-net-registry.service"
    else:
      return "uvn-net-cell.service"


  def extra_files(self) -> Iterable[Path]:
    return [
      self.marker,
      self.config_file,
      self.global_uvn_dir_marker,
    ]


  @property
  def config_file(self) -> Path:
    if self._root:
      return Path("/run/uno/uvn-net/uvn-net-root.conf")
    else:
      return Path("/run/uno/uvn-net/uvn-net.conf")


  @property
  def marker(self) -> Path:
    return Path(f"{self.config_file}.id")


  @property
  def global_uvn_dir_marker(self) -> Path:
    if self._root:
      return Path("/etc/uno/registry")
    else:
      return Path("/etc/uno/cell")
  

  @property
  def global_uvn_dir(self) -> Path|None:
    if not self.global_uvn_dir_marker.exists():
      return None
    return Path(self.global_uvn_dir_marker.read_text().strip())


  @staticmethod
  def uvn_net(args, root: bool=False, forced: bool=False, config_dir: Path | None=None) -> None:
    custom_env = {}
    if config_dir:
      custom_env["UVN_NET_CONF_DIR"] = str(config_dir)
    if forced:
      custom_env["FORCED_CLEANUP"] = "true"
    env = {**os.environ, **custom_env} if custom_env else None
    with as_file(files(service_data).joinpath("uvn-net")) as uvn_net:
      cmd = ["sh", uvn_net, *(["root"] if root else []), *args]
      log.activity(f"[UVN-NET] command: {' '.join(map(str, cmd))}")
      if custom_env:
        log.activity(f"[UVN-NET] env: {custom_env}")
      subprocess.run(cmd, check=True, env=env)


  def enabled(self) -> bool:
    return self.marker.is_file()


  @property
  def current_id(self) -> Optional[str]:
    return self.compute_id(self.marker.parent)


  def compute_id(self, config_dir: Path) -> Optional[str]:
    conf_marker = config_dir / self.marker.name
    if not conf_marker.exists():
      return None
    conf_id = conf_marker.read_text().strip()
    log.debug(f"[SERVICE] {self} marker {conf_marker} = {conf_id}")
    return conf_id


  def is_compatible(self, config_dir: Path) -> bool:
    return not self.enabled() or self.current_id == self.compute_id(config_dir)


  def uvn_net_start(self, config_dir: Path|None=None) -> None:
    log.warning(f"[SERVICE] {self} starting from {self.global_uvn_dir_marker if not config_dir else config_dir}")
    self.uvn_net(
      ["start"],
      root=self._root,
      config_dir=config_dir)
    log.warning(f"[SERVICE] {self} started")


  def uvn_net_stop(self, forced: bool=False) -> None:
    self.uvn_net(["stop"], root=self._root, forced=forced)
    log.warning(f"[SERVICE] {self} stopped")


  def configure(self, config_dir: Path) -> None:
    was_started = self.enabled()
    if was_started:
      self.uvn_net_stop()
    if not self.global_uvn_dir_marker.parent.is_dir():
      self.global_uvn_dir_marker.parent.mkdir(mode=0o755, parents=True)
      # self.global_uvn_dir_marker.parent.chmod(0o700)
    self.global_uvn_dir_marker.write_text(str(config_dir))
    log.warning(f"[SERVICE] {self} configured: {self.global_uvn_dir_marker} → {config_dir}")
    if was_started:
      self.uvn_net_start()


  def generate_configuration(
      self,
      output_dir: Path,
      lans: Iterable[LanDescriptor],
      vpn_interfaces: Iterable[WireGuardInterface],
      router: Router | None=None) -> None:
    log.activity(f"[SERVICE] generating static configuration: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    generated = []

    output = output_dir / self.config_file.name
    Templates.generate(output, "static_config/uvn-net.conf", {
      "vpn_interfaces": vpn_interfaces,
      "lans": lans,
      "router_enabled": "enabled" if router else "",
      # "generation_ts": Timestamp.now().format(),
    }, mode=0o600)
    generated.append(output)

    wg_dir = output_dir / "wg"
    if wg_dir.is_dir():
      shutil.rmtree(wg_dir)
    wg_dir.mkdir(parents=True, exist_ok=False)
    wg_dir.chmod(0o700)
    for vpn in vpn_interfaces:
      wg_config = wg_dir / f"{vpn.config.intf.name}.conf"
      Templates.generate(wg_config, *vpn.config.template_args, mode=0o600)
      generated.append(wg_config)

    output = output_dir / "wg-ip.config"
    Templates.generate(output, "static_config/wg-ip.config", {
      "vpn_interfaces": vpn_interfaces,
    })

    if router:
      output = output_dir / "frr.conf"
      Templates.generate(output, *router.frr_config)
      generated.append(output)
    
    conf_digest = output_dir / f"{self.config_file.name}.digest"
    exec_command([
      "sha256sum", *sorted((g.relative_to(output_dir) for g in generated), key=lambda v: str(v))
    ], cwd=output_dir, output_file=conf_digest)
    conf_digest.chmod(0o644)
    
    output = output_dir / self.marker.name
    conf_id = _sha256sum(conf_digest)
    output.write_text(conf_id)
    output.chmod(0o644)

    log.activity(f"[SERVICE] {self} configuration generated: {output_dir} [{conf_id}]")


  def replace_configuration(self, config_dir: Path) -> None:
    # Chek that the configuration has all the required files
    config_files = [config_dir / self.marker.name, config_dir / self.config_file.name]
    missing = [f for f in config_files if not f.exists()]
    if missing:
      raise RuntimeError("invalid configuration to install: missing files", config_dir, missing)

    conf_id = self.compute_id(config_dir)
    if conf_id is None:
      raise RuntimeError("refusing to install invalid configuration")
    current_id = self.current_id

    if current_id == conf_id:
      log.debug(f"[SERVICE] {self} configuration unchanged: {conf_id}")
      return

    if self.enabled():
      self.uvn_net_stop()
      self.uvn_net_start(config_dir)
      return

    marker_dir = self.marker.parent
    marker_dir.mkdir(parents=True, exist_ok=True)
    exec_command(["cp", "-v", *config_files, marker_dir])


UvnNetService.Cell = UvnNetService()
UvnNetService.Root = UvnNetService(root=True)


class UvnAgentService(UvnService):
  def __init__(self, root: bool=False) -> None:
    self._root = root


  def __str__(self) -> str:
    if self._root:
      return "uvn-registry.service"
    else:
      return "uvn-cell.service"


  def install(self, reload: bool=False) -> None:
    super().install(reload=reload)
    self.uvn_net.install(reload=reload)


  def remove(self) -> None:
    super().remove()
    self.uvn_net.remove()


  def extra_files(self) -> Iterable[Path]:
    return [
      self.pid_file,
    ]


  def enabled(self) -> bool:
    return self.external_pid is not None


  # def stop(self) -> None:
  #   agent_pid = self.external_pid
  #   if agent_pid is None:
  #     return
  #   import os
  #   import signal
  #   log.debug(f"[SERVICE] signaling and waiting for agent process to exit: {agent_pid}")
  #   os.kill(agent_pid, signal.SIGINT)
  #   # os.waitpid(agent_pid, 0)
  #   exec_command(["sh", "-c", f"wait {agent_pid}"])
  #   log.warning(f"[SERVICE] agent process stopped: {agent_pid}")


  @property
  def uvn_net(self) -> UvnNetService:
    if self._root:
      return UvnNetService.Root
    else:
      return UvnNetService.Cell


  @property
  def pid_file(self) -> Path:
    # home = Path(os.environ.get("HOME", "/run/uno/"))
    home = Path("/run/uno")
    if self._root:
      # return Path("/run/uno/uvn-agent-root.pid")
      return home / "uvn-agent-root.pid"
    else:
      # return Path("/run/uno/uvn-agent.pid")
      return home / "uvn-agent.pid"
    

  @property
  def pid(self) -> Optional[int]:
    if not self.pid_file.exists():
      return None
    try:
      agent_pid = int(self.pid_file.read_text().strip())
      return agent_pid
    except Exception as e:
      log.error(f"failed to read agent PID: {self.pid_file}")
      log.exception(e)
      return None


  @property
  def external_pid(self) -> Optional[int]:
    agent_pid = self.pid
    if agent_pid is None:
      return None

    if agent_pid == os.getpid():
      log.debug(f"[SERVICE] current process is the designated system agent")
      return None

    log.debug(f"[SERVICE] possible external agent process detected: {agent_pid}")
    try:
      os.kill(agent_pid, 0)
      log.warning(f"[SERVICE] external agent process detected: {agent_pid}")
      return agent_pid
    except OSError:
      log.debug(f"[SERVICE] process {agent_pid} doesn't exist")
      if self.pid_file.is_file():
        old_pid = self.pid_file.read_text().strip()
        log.warning(f"[SERVICE] clearing stale agent PID file: {self.pid_file} [{old_pid}]")
        self.delete_pid()
      return None


  def write_pid(self) -> None:
    self.pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid = str(os.getpid())
    self.pid_file.write_text(pid)
    log.activity(f"[SERVICE] PID file [{pid}]: {self.pid_file}")


  def delete_pid(self) -> None:
    try:
      self.pid_file.unlink()
    except Exception as e:
      if self.pid_file.is_file():
        raise e


UvnAgentService.Root = UvnAgentService(root=True)
UvnAgentService.Cell = UvnAgentService()
