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
  def __init__(self, static_dir: Path) -> None:
    self.static_dir = static_dir
    self._lans_nat = []
    self._vpn_started = []
    self._vpn_nat = []


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
  def static_pid_file(self) -> bool:
    return self.static_dir / "uvn.pid"


  @property
  def is_statically_configured(self) -> bool:
    return self.static_pid_file.is_file()
  

  def take_over_configuration(self,
      lans: Optional[Iterable[LanDescriptor]]=None,
      vpn_interfaces: Optional[Iterable[WireGuardInterface]]=None) -> None:
    exec_command(["kill", str(int(self.static_pid_file.read_text()))])
    self.static_pid_file.unlink()
    # TODO(asorbini) verify that the specified interface have actually been initialized
    self._lans = list(lans)
    self._vpn_nat = list(vpn_interfaces)
    self._vpn_started = list(self._vpn_nat)
