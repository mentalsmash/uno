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

from .wg import WireGuardInterface
from .ip import (
  ipv4_enable_forward,
  ipv4_enable_output_nat,
  ipv4_disable_forward,
  ipv4_disable_output_nat,
  ipv4_enable_kernel_forwarding,
  NicDescriptor,
  LanDescriptor,
)
from .exec import exec_command
from .router import Router
from .render import Templates
from .log import Logger as log


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
    from .data import service as service_data
    from importlib.resources import as_file, files
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
      self.global_uvn_id,
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
  def global_uvn_id(self) -> Path:
    if self._root:
      return Path("/etc/uno/registry")
    else:
      return Path("/etc/uno/cell")
  

  @property
  def global_uvn_dir(self) -> Path|None:
    if not self.global_uvn_id.exists():
      return None
    return Path(self.global_uvn_id.read_text().strip())


  @staticmethod
  def uvn_net(args, root: bool=False, forced: bool=False, config_dir: Path | None=None) -> None:
    import subprocess
    from .data import service
    from importlib.resources import as_file, files
    import os
    custom_env = {}
    if config_dir:
      custom_env["UVN_NET_CONF_DIR"] = str(config_dir)
    if forced:
      custom_env["FORCED_CLEANUP"] = "true"
    env = {**os.environ, **custom_env} if custom_env else None
    with as_file(files(service).joinpath("uvn-net")) as uvn_net:
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
    log.warning(f"[SERVICE] {self} starting from {self.global_uvn_id if not config_dir else config_dir}")
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
    if not self.global_uvn_id.parent.is_dir():
      self.global_uvn_id.parent.mkdir(mode=0o755, parents=True)
      # self.global_uvn_id.parent.chmod(0o700)
    self.global_uvn_id.write_text(str(config_dir))
    log.warning(f"[SERVICE] {self} configured: {self.global_uvn_id} → {config_dir}")
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
    if self._root:
      return Path("/run/uno/uvn-agent-root.pid")
    else:
      return Path("/run/uno/uvn-agent.pid")
    

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
    import os

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
    import os
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


class AgentNetworking:
  def __init__(self,
      config_dir: Path,
      root: bool=False,
      allowed_lans: Iterable[LanDescriptor]|None=None,
      vpn_interfaces: Iterable[WireGuardInterface]|None=None,
      router: Router|None=None) -> None:
    self.config_dir = config_dir.resolve()
    self._root = root
    self._allowed_lans = set(allowed_lans or [])
    self._vpn_interfaces = set(vpn_interfaces or [])
    self._router = router
    self._router_started = None
    self._lans_nat = []
    self._vpn_started = []
    self._vpn_nat = []
    self._uvn_net_enabled = False
    self._boot = True
    self.configure(
      allowed_lans=allowed_lans,
      vpn_interfaces=vpn_interfaces,
      router=router)


  @property
  def uvn_net_conf(self) -> Path:
    return self.config_dir / "uvn-net.conf"


  @property
  def started(self) -> bool:
    return (
      self._router_started
      or self._lans_nat
      or self._vpn_nat
      or self._vpn_started
      or self._uvn_net_enabled
    )


  @property
  def uvn_agent(self) -> UvnAgentService:
    if self._root:
      return UvnAgentService.Root
    else:
      return UvnAgentService.Cell


  def generate_configuration(self) -> None:
    # Generate updated uvn-net static configuration if we might use it
    prev_id = self.uvn_agent.uvn_net.compute_id(self.config_dir)
    # import tempfile
    # tmp_dir_h = tempfile.TemporaryDirectory()
    # tmp_dir = Path(tmp_dir_h.name)

    self.uvn_agent.uvn_net.generate_configuration(
      output_dir=self.config_dir,
      lans=self._allowed_lans,
      vpn_interfaces=self._vpn_interfaces,
      router=self._router)

    new_id = self.uvn_agent.uvn_net.compute_id(self.config_dir)
    if prev_id != new_id:
      log.activity(f"[NET] uvn-net configuration changed:")
      log.activity(f"[NET] prev id: {prev_id}")
      log.activity(f"[NET] current id: {new_id}")
      # shutil.copytree(tmp_dir, f"{self.config_dir}.2")
      # raise RuntimeError("wtf")
    
    # shutil.copytree(tmp_dir, self.config_dir)

  


  def configure(self,
      allowed_lans: Iterable[LanDescriptor]|None=None,
      vpn_interfaces: Iterable[WireGuardInterface]|None=None,
      router: Router|None=None) -> None:
    self._allowed_lans = set(allowed_lans or [])
    self._vpn_interfaces = set(vpn_interfaces or [])
    self._router = router
  

  def start(self) -> None:
    assert(not self.started)

    boot = self._boot
    self._boot = False

    # Check that no other agent is running
    other_agent_pid = self.uvn_agent.external_pid
    if other_agent_pid is not None:
      raise RuntimeError(f"agent already active in another process", other_agent_pid, self.uvn_agent.pid_file)

    # Check if the uvn-net service is running, i.e. the
    # network layer might have been already initialized
    uvn_net_enabled = self.uvn_agent.uvn_net.enabled()
    if uvn_net_enabled:
      if boot:
        # At "boot", i.e. the first time the services are started, we want uvn-net to
        # have the same configuration, otherwise we refuse to start the agent and
        # expect the user to disable the service or update it to the latest
        # configuration before starting the agent.
        if not self.uvn_agent.uvn_net.is_compatible(self.config_dir):
            log.error(f"[NET] {self.uvn_agent.uvn_net} started with a different configuration: {self.uvn_agent.uvn_net.current_id}")
            log.error(f"[NET] stop it before running this agent")
            raise RuntimeError("cannot start network services")
        else:
          log.warning(f"[NET] {self.uvn_agent.uvn_net} detected, skipping network initialization")
          self._uvn_net_enabled = True
          return
      else:
        # When the services are started again at runtime, the uvn-net configuration might
        # have changed, but we assume we started from a compatible configuration so instead
        # we replace the installed configuration with the agent's
        self.uvn_agent.uvn_net.replace_configuration(self.config_dir)
        self._uvn_net_enabled = True
        return


    try:
      # Make sure kernel forwarding is enabled
      ipv4_enable_kernel_forwarding()
      for vpn in self._vpn_interfaces:
        vpn.start()
        self._vpn_started.append(vpn)
        self._enable_vpn_nat(vpn)
      for lan in self._allowed_lans:
        self._enable_lan_nat(lan)
      if self._router:
        self._router.start()
        self._router_started = self._router
    except Exception as e:
      log.error("[NET] failed to configure network services")
      # log.exception(e)
      errors = [e]
      try:
        self.uvn_agent.delete_pid()
      except Exception as e:
        log.error(f"[NET] failed to reset {self.uvn_agent} status")
        # log.exception(e)
        errors.append(e)
      try:
        self.stop()
      except Exception as e:
        log.error("[NET] failed to cleanup state during partial initialization")
        # log.exception(e)
        errors.append(e)
      raise RuntimeError("failed to start network services", errors)


  def stop(self, assert_stopped: bool=False) -> None:
    # Always perform all clean up operations.
    # If self._uvn_net_enabled this functions should do nothing
    # unless some targets are passed as arguments
    vpns_nat = self._vpn_interfaces if assert_stopped else list(self._vpn_nat)
    vpns_up = self._vpn_interfaces if assert_stopped else list(self._vpn_started)
    lans_nat = self._allowed_lans if assert_stopped else list(self._lans_nat)
    router = self._router if assert_stopped else self._router_started
    errors = []

    for vpn in vpns_nat:
      try:
        self._disable_vpn_nat(vpn)
      except Exception as e:
        log.error(f"[NET] failed to disable NAT on VPN interface: {vpn}")
        # log.exception(e)
        errors.append((vpn, e))
      if vpn in self._vpn_nat:
        self._vpn_nat.remove(vpn)

    for vpn in vpns_up:
      try:
        vpn.stop()
      except Exception as e:
        log.error(f"[NET] failed to delete VPN interface: {vpn}")
        # log.exception(e)
        errors.append((vpn, e))
      if vpn in self._vpn_started:
        self._vpn_started.remove(vpn)

    for lan in lans_nat:
      try:
        self._disable_lan_nat(lan)
      except Exception as e:
        log.error(f"[NET] failed to disable NAT on LAN interface: {lan}")
        # log.exception(e)
        errors.append((lan, e))
      if lan in self._lans_nat:
        self._lans_nat.remove(lan)

    if router:
      try:
        router.stop()
      except Exception as e:
        log.error(f"[NET] failed to stop router: {router}")
        # log.exception(e)
        errors.append((router, e))
      if router == self._router_started:
        self._router_started = None
    
    uvn_net_enabled = self.uvn_agent.uvn_net.enabled()
    if assert_stopped and uvn_net_enabled:
      self.uvn_agent.uvn_net.uvn_net_stop(forced=True)
    elif self._uvn_net_enabled:
      if not self.uvn_agent.uvn_net.enabled():
        log.error(f"[NET] {self.uvn_agent.uvn_net} not running anymore")
      else:
        log.warning(f"[NET] {self.uvn_agent.uvn_net} will remain active")
    self._uvn_net_enabled = False

    try:
      self.uvn_agent.delete_pid()
    except Exception as e:
      log.error(f"[NET] failed to reset service state")
      # log.exception(e)
      errors.append(e)

    if errors:
      if not assert_stopped:
        raise RuntimeError("errors encountered while stopping network services", errors)
      else:
        log.error("[NET] cleanup performed with some errors:")
        for tgt, err in errors:
          log.error(f"[NET] - {tgt}: {err}")
          # log.error(f"[NET]   ")
  

  def _enable_lan_nat(self, lan: NicDescriptor) -> None:
    ipv4_enable_output_nat(lan.nic.name)
    self._lans_nat.append(lan)
    log.debug(f"NAT ENABLED for LAN: {lan}")


  def _disable_lan_nat(self, lan: LanDescriptor, ignore_errors: bool=False) -> None:
    ipv4_disable_output_nat(lan.nic.name, ignore_errors=ignore_errors)
    if lan in self._lans_nat:
      self._lans_nat.remove(lan)
    log.debug(f"NAT DISABLED for LAN: {lan}")


  def _enable_vpn_nat(self, vpn: WireGuardInterface) -> None:
    ipv4_enable_forward(vpn.config.intf.name)
    ipv4_enable_output_nat(vpn.config.intf.name)
    # # For "tunnel" interfaces we must enable ipv6 too
    # if vpn.config.tunnel_root:
    #   ipv4_enable_forward(vpn.config.intf.name, v6=True)
    #   ipv4_enable_output_nat(vpn.config.intf.name, v6=True)
    self._vpn_nat.append(vpn)
    log.debug(f"NAT ENABLED for VPN interface: {vpn}")


  def _disable_vpn_nat(self, vpn: WireGuardInterface, ignore_errors: bool=False) -> None:
    ipv4_disable_forward(vpn.config.intf.name, ignore_errors=ignore_errors)
    ipv4_disable_output_nat(vpn.config.intf.name, ignore_errors=ignore_errors)
    # # For "tunnel" interfaces we must enable ipv6 too
    # if vpn.config.tunnel_root:
    #   ipv4_disable_forward(vpn.config.intf.name, v6=True, ignore_errors=ignore_errors)
    #   ipv4_disable_output_nat(vpn.config.intf.name, v6=True, ignore_errors=ignore_errors)
    if vpn in self._vpn_nat:
      self._vpn_nat.remove(vpn)
    log.debug(f"NAT DISABLED for VPN: {vpn}")

