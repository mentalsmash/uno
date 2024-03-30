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
from typing import Generator

from ..core.exec import exec_command
from ..core.wg import WireGuardInterface
from .agent_service import AgentService, StopAgentServiceError, AgentStaticService


class UvnNet(AgentService):
  STATIC_SERVICE = "net"

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self._iptables_rules = {}


  def _start_static(self) -> None:
    self._start()


  def _start(self) -> None:
    exec_command(["echo", "1", ">", "/proc/sys/net/ipv4/ip_forward"],
      shell=True,
      fail_msg="failed to enable ipv4 forwarding")

    self._iptables_install("tcp_pmtu", [
      "-A", "FORWARD",
      "-p", "tcp",
      "--tcp-flags", "SYN,RST", "SYN",
      "-j", "TCPMSS",
      "--clamp-mss-to-pmtu"
    ])

    for vpn in self.agent.vpn_interfaces:
      vpn.start()
      if vpn.config.masquerade:
        self._vpn_masquerade(vpn)


  def _stop(self, assert_stopped: bool) -> None:
    errors = []
    for vpn in self.agent.vpn_interfaces:
      try:
        vpn.stop(assert_stopped=assert_stopped)
      except Exception as e:
        if not assert_stopped:
          raise
        self.log.warning("failed to stop VPN interface: {}", vpn)
        # self.log.exception(e)
        # errors.append(e)
    for rule_id, rules in list(self._iptables_rules.items()):
      for rule in reversed(rules or []):
        try:
          del_rule = [tkn if tkn != "-A" else "-D" for tkn in rule]
          exec_command(["iptables", *del_rule])
        except Exception as e:
          if not assert_stopped:
            raise
          self.log.error(
            "failed to delete iptables rule {}: {}", rule_id, ' '.join(map(str, rule)))
          self.log.exception(e)
          errors.append(e)
    if errors:
      raise StopAgentServiceError(errors)


  def _vpn_masquerade(self, vpn: WireGuardInterface) -> None:
    self._iptables_install(vpn.config.intf.name, [
      "-t", "nat",
      "-A", "POSTROUTING",
      "-o", str(vpn.config.intf.subnet),
      "-j", "MASQUERADE",
    ])
    for nic in (
        *(l.nic.name for l in sorted(self.agent.lans, key=lambda l: l.nic.name)),
        *(v.config.intf.name for v in sorted(self.agent.vpn_interfaces, key=lambda l: l.config.intf.name) if v != vpn)):
      self._iptables_install(vpn.config.intf.name, [
        "-t", "nat",
        "-A", "POSTROUTING",
        "-s", str(vpn.config.intf.subnet),
        "-o", nic,
        "-j", "MASQUERADE",
      ])
    self.log.debug("NAT ENABLED for VPN interface: {}", vpn)


  def _iptables_install(self, rule_id: str, rule: list[str]):
    exec_command(["iptables", *rule])
    rules = self._iptables_rules[rule_id] = self._iptables_rules.get(rule_id, [])
    rules.append(rule)

