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
from ..core.ip import (
  ipv4_enable_forward,
  ipv4_enable_output_nat,
  ipv4_disable_forward,
  ipv4_disable_output_nat,
  ipv4_enable_kernel_forwarding,
  iptables_detect_docker,
  iptables_docker_forward,
  iptables_tcp_pmtu,
)
from ..data import service as service_data
from ..registry.lan_descriptor import LanDescriptor
from ..registry.nic_descriptor import NicDescriptor
from ..core.exec import exec_command
from ..core.log import Logger as log
from .render import Templates
from .router import Router
from .agent_service import AgentService


def _interface_name(intf: LanDescriptor|WireGuardInterface) -> str:
  if isinstance(intf, LanDescriptor):
    return intf.nic.name
  else:
    return intf.config.intf.name


class AgentNetworking(AgentService):
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
    self._iptables_docker_rules = {}
    self._iptables_tcp_pmtu = False
    self._uvn_net_enabled = False
    self._boot = True
    self.configure(
      allowed_lans=allowed_lans,
      vpn_interfaces=vpn_interfaces,
      router=router)


  # @property
  # def uvn_agent(self) -> UvnAgentService:
  #   if self._root:
  #     return UvnAgentService.Root
  #   else:
  #     return UvnAgentService.Cell


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


  # def configure(self,
  #     allowed_lans: Iterable[LanDescriptor]|None=None,
  #     vpn_interfaces: Iterable[WireGuardInterface]|None=None,
  #     router: Router|None=None) -> None:
  #   self._allowed_lans = set(allowed_lans or [])
  #   self._vpn_interfaces = set(vpn_interfaces or [])
  #   self._router = router
  

  def start(self) -> None:
    boot = self._boot
    self._boot = False

    # Check that no other agent is running
    other_agent_pid = self.uvn_agent.external_pid
    if other_agent_pid is not None:
      raise RuntimeError(f"agent already active in another process", other_agent_pid, self.uvn_agent.pid_file)

    if iptables_detect_docker():
      log.warning("docker detected in iptables, the agent might not work correctly on this host.")

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

      iptables_tcp_pmtu(enable=True)
      self._iptables_tcp_pmtu = True

      for vpn in self._vpn_interfaces:
        vpn.start()
        self._vpn_started.append(vpn)
        self._enable_vpn_nat(vpn, self._allowed_lans, (v for v in self._vpn_interfaces if v != vpn))
      # for lan in self._allowed_lans:
      #   self._enable_lan_nat(lan)
      
      self._enable_iptables_docker()

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
    
    # from functools import reduce
    # def _aggregate(res, v):
    #   v, l = v
    #   res[v] = res.get(v, list())
    #   res[v].append(l)
    #   return v
    # vpns_nat = {
    #   v: self._allowed_lans
    #   for v in self._vpn_interfaces
    # } if assert_stopped else reduce(_aggregate, self._vpn_nat, {})
    vpns_up = self._vpn_interfaces if assert_stopped else list(self._vpn_started)
    lans_nat = self._allowed_lans if assert_stopped else list(self._lans_nat)
    router = self._router if assert_stopped else self._router_started
    errors = []

    self._disable_iptables_docker()

    if self._iptables_tcp_pmtu:
      self._iptables_tcp_pmtu = False
      iptables_tcp_pmtu(enable=False)

    for vpn in vpns_up:
      try:
        self._disable_vpn_nat(vpn, self._allowed_lans, (v for v in self._vpn_interfaces if v != vpn))
      except Exception as e:
        log.error(f"[NET] failed to disable NAT on VPN interface: {vpn}")
        log.exception(e)
        errors.append((vpn, e))

    for vpn in vpns_up:
      try:
        vpn.stop()
      except Exception as e:
        log.error(f"[NET] failed to delete VPN interface: {vpn}")
        log.exception(e)
        errors.append((vpn, e))
      if vpn in self._vpn_started:
        self._vpn_started.remove(vpn)

    for lan in lans_nat:
      try:
        self._disable_lan_nat(lan)
      except Exception as e:
        log.error(f"[NET] failed to disable NAT on LAN interface: {lan}")
        log.exception(e)
        errors.append((lan, e))
      if lan in self._lans_nat:
        self._lans_nat.remove(lan)

    if router:
      try:
        router.stop()
      except Exception as e:
        log.error(f"[NET] failed to stop router: {router}")
        log.exception(e)
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
      log.exception(e)
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
    # ipv4_enable_forward(lan.nic.name)
    # ipv4_enable_output_nat(lan.nic.name)
    self._lans_nat.append(lan)
    log.debug(f"NAT ENABLED for LAN: {lan}")


  def _disable_lan_nat(self, lan: LanDescriptor, ignore_errors: bool=False) -> None:
    # ipv4_disable_forward(lan.nic.name, ignore_errors=ignore_errors)
    # ipv4_disable_output_nat(lan.nic.name, ignore_errors=ignore_errors)
    if lan in self._lans_nat:
      self._lans_nat.remove(lan)
    log.debug(f"NAT DISABLED for LAN: {lan}")


  def _enable_vpn_nat(self, vpn: WireGuardInterface, lans: Iterable[LanDescriptor], other_vpns: Iterable[WireGuardInterface]) -> None:
    # if vpn.config.forward:
    #   ipv4_enable_forward(vpn.config.intf.name)
    if vpn.config.masquerade:
      ipv4_enable_output_nat(vpn.config.intf.name)
      for nic in (*(l.nic.name for l in lans), *(v.config.intf.name for v in other_vpns)):
        exec_command([
          "iptables", "-t", "nat", "-A", "POSTROUTING", "-s", str(vpn.config.intf.subnet), "-o", nic, "-j", "MASQUERADE",
        ])
    log.debug(f"NAT ENABLED for VPN interface: {vpn} -> {lans}")


  def _disable_vpn_nat(self, vpn: WireGuardInterface, lans: list[LanDescriptor], other_vpns: Iterable[WireGuardInterface], ignore_errors: bool=False) -> None:
    # if vpn.config.forward:
    #   ipv4_disable_forward(vpn.config.intf.name, ignore_errors=ignore_errors)
    if vpn.config.masquerade:
      ipv4_disable_output_nat(vpn.config.intf.name, ignore_errors=ignore_errors)
    # if vpn in self._vpn_nat:
    #   self._vpn_nat.remove(vpn)
      for nic in (*(l.nic.name for l in lans), *(v.config.intf.name for v in other_vpns)):
        exec_command([
          "iptables", "-t", "nat", "-D", "POSTROUTING", "-s", str(vpn.config.intf.subnet), "-o", nic, "-j", "MASQUERADE",
        ])

    log.debug(f"NAT DISABLED for VPN: {vpn} -> {lans}")


  def _enable_iptables_docker(self) -> None:
    # Check if docker rules are installed on iptables.
    # If they are, assume we must explicitly allow forwarding between
    # interfaces via the DOCKER-USER chain
    # (see https://docs.docker.com/network/packet-filtering-firewalls/#docker-on-a-router)
    self._iptables_docker_rules = {}
    if not iptables_detect_docker() or True:
      return

    # Create explicit forwarding rules between each pair of interfaces
    all_interfaces = set((*self._vpn_nat, *self._lans_nat))
    rules = {}
    for intf_a in all_interfaces:
      for intf_b in all_interfaces:
        intf_b_rules = rules[intf_b] = rules.get(intf_b, set())
        if intf_a == intf_b:
          continue
        iptables_docker_forward(_interface_name(intf_a), _interface_name(intf_b), enable=True)
        intf_b_rules.add(intf_a)
    self._iptables_docker_rules = rules


  def _disable_iptables_docker(self) -> None:
    # Create explicit forwarding rules between each pair of interfaces
    for intf_a, intf_a_rules in list(self._iptables_docker_rules.items()):
      for intf_b in list(intf_a_rules):
        iptables_docker_forward(_interface_name(intf_a), _interface_name(intf_b), enable=False)
        self._iptables_docker_rules[intf_a].remove(intf_b)
      del self._iptables_docker_rules[intf_a]
    self._iptables_docker_rules = {}

