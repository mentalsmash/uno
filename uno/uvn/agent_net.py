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
import time

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

from .log import Logger as log


class AgentNetworking:
  def __init__(self,
      deployment_id: str | None = None,
      static_dir: Path | None=None) -> None:
    self.static_dir = static_dir
    self.deployment_id = deployment_id
    self._lans_nat = []
    self._vpn_started = []
    self._vpn_nat = []


  def started(self) -> bool:
    return len(self._lans_nat) > 0 or len(self._vpn_started) > 0


  def start(self,
      lans: Optional[Iterable[LanDescriptor]]=None,
      vpn_interfaces: Optional[Iterable[WireGuardInterface]]=None) -> None:
    try:
      # Make sure kernel forwarding is enabled
      ipv4_enable_kernel_forwarding()

      for vpn in (vpn_interfaces or []):
        vpn.start()
        self._vpn_started.append(vpn)
        self._enable_vpn_nat(vpn)
      for lan in (lans or []):
        self._enable_lan_nat(lan)
    except Exception as e:
      self.stop()
      raise RuntimeError("failed to configure network interfaces")


  def stop(self,
      lans: Optional[Iterable[LanDescriptor]]=None,
      vpn_interfaces: Optional[Iterable[WireGuardInterface]]=None) -> None:
    try:
      vpns_nat = vpn_interfaces if vpn_interfaces is not None else list(self._vpn_nat)
      vpns_up = vpn_interfaces if vpn_interfaces is not None else list(self._vpn_started)
      lans_nat = lans if lans is not None else list(self._lans_nat)

      for vpn in vpns_nat:
        self._disable_vpn_nat(vpn)
      for vpn in vpns_up:
        vpn.stop()
        if vpn in self._vpn_started:
          self._vpn_started.remove(vpn)
      for lan in lans_nat:
        self._disable_lan_nat(lan)
    except Exception as e:
      raise RuntimeError("failed to start")


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


  @property
  def static_pid_file(self) -> Path:
    return Path("/run/uno/uvn-net.pid")


  @property
  def is_statically_configured(self) -> bool:
    return (
      self.static_pid_file is not None
      and self.static_pid_file.is_file()
    )


  @property
  def compatible_static_configuration(self) -> bool:
    return (
      self.is_statically_configured
      and self.static_pid_file.read_text().strip() == self.deployment_id
    )


  def stop_static_configuration(self) -> None:
    uno_sh = self.static_dir / "uno.sh"
    exec_command(["sh", "-c", f"{uno_sh} stop"], capture_output=True)


  def take_over_configuration(self,
      lans: Optional[Iterable[LanDescriptor]]=None,
      vpn_interfaces: Optional[Iterable[WireGuardInterface]]=None) -> None:
    if not self.is_statically_configured:
      raise RuntimeError("static configuration not detected")

    # exec_command(["kill", str(int(self.static_pid_file.read_text()))])
    self.static_pid_file.unlink()
    # TODO(asorbini) verify that the specified interface have actually been initialized
    self._lans = list(lans)
    self._vpn_nat = list(vpn_interfaces)
    self._vpn_started = list(self._vpn_nat)


  def delegate_configuration(self) -> None:
    if self.static_pid_file is None:
      raise RuntimeError("cannot delegate to static configuration")

    self.static_pid_file.write_text(self.deployment_id)

    # uno_sh = self.static_dir / "uno.sh"
    # exec_command(["sh", "-c", f"{uno_sh} take-over"], capture_output=True)
    # max_wait = 5
    # for i in range(max_wait):
    #   if self.is_statically_configured:
    #     break
    #   log.debug(f"[AGENT] waiting for static configuration to take over")
    #   time.sleep(1)

    if not self.is_statically_configured and not self.compatible_static_configuration:
      raise RuntimeError("failed to delegate networking to static configuration")

    log.warning(f"[AGENT] services delegated to static configuration")
  
  