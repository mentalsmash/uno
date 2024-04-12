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

from ..core.exec import exec_command
from ..core.wg import WireGuardInterface
from .agent_service import AgentService, StopAgentServiceError


class UvnNet(AgentService):
  STATIC_SERVICE = "net"

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self._iptables_rules = {}

  def _take_over_static(self) -> None:
    self._start(noop=True)

  def _detect_docker_iptables(self) -> bool:
    return exec_command(["iptables", "-n", "-L" "DOCKER-USER"], noexcept=True).returncode == 0

  def _start(self, noop: bool = False) -> None:
    if not noop:
      exec_command(
        ["echo 1 > /proc/sys/net/ipv4/ip_forward"],
        shell=True,
        fail_msg="failed to enable ipv4 forwarding",
      )

    # Since we won't disable kernel forwarding,
    # permanently install a DROP rule for the FORWARD chain
    self._iptables_install("forward_drop", ["-P", "FORWARD", "DROP"], noop=noop, irremovable=True)

    self._iptables_install(
      "tcp_pmtu",
      [
        "-A",
        "FORWARD",
        "-p",
        "tcp",
        "--tcp-flags",
        "SYN,RST",
        "SYN",
        "-j",
        "TCPMSS",
        "--clamp-mss-to-pmtu",
      ],
      noop=noop,
    )

    for lan in self.agent.lans:
      self._iptables_forward(lan.nic.name, noop=noop)

    for vpn in self.agent.vpn_interfaces:
      from .render import Templates

      wg_config = self.root / f"{vpn.config.intf.name}.conf"
      Templates.generate(wg_config, *vpn.config.template_args)

      vpn.start(noop=noop)

      self._iptables_forward(vpn.config.intf.name, noop=noop)
      if vpn.config.masquerade:
        self._vpn_masquerade(vpn, noop=noop)

  def _stop(self, assert_stopped: bool) -> None:
    errors = []
    for vpn in self.agent.vpn_interfaces:
      try:
        vpn.stop(assert_stopped=assert_stopped)
      except Exception:
        if not assert_stopped:
          raise
        self.log.warning("failed to stop VPN interface: {}", vpn)
        # self.log.exception(e)
        # errors.append(e)
    if assert_stopped and not self._iptables_rules:
      self._start(noop=True)
    for rule_id, rules in list(self._iptables_rules.items()):
      for rule in reversed(rules or []):
        try:
          if rule[0] == "-P":
            assert len(rule) == 3
            del_rule = [*rule[:2], "ACCEPT"]
          else:
            tkn_map = {
              "-I": "-D",
              "-A": "-D",
              "-N": "-X",
            }
            del_rule = [tkn_map.get(tkn, tkn) for tkn in rule]
          exec_command(["iptables", *del_rule])
        except Exception as e:
          if not assert_stopped:
            raise
          self.log.error("failed to delete iptables rule {}: {}", rule_id, " ".join(map(str, rule)))
          self.log.exception(e)
          errors.append(e)
    if errors:
      raise StopAgentServiceError(errors)

  def _iptables_forward(self, nic: str, noop: bool = False) -> None:
    # If docker is enabled we must make install extra rules
    # to prevent its iptables rules from stopping traffic
    docker_installed = self._detect_docker_iptables()

    # Add a dedicated chain to the FORWARD chain
    chain = f"FORWARD_{nic}"

    self._iptables_install(
      nic,
      [
        "-N",
        chain,
      ],
      noop=noop,
    )
    self._iptables_install(
      nic,
      [
        "-A",
        "FORWARD",
        "-j",
        chain,
      ],
      noop=noop,
    )

    # Accept related or established traffic
    self._iptables_install(
      nic,
      [
        "-A",
        chain,
        "-o",
        nic,
        "-m",
        "conntrack",
        "--ctstate",
        "RELATED,ESTABLISHED",
        "-j",
        "ACCEPT",
      ],
      noop=noop,
    )

    # Accept traffic from any valid known subnet
    for subnet in sorted(
      (
        *([self.agent.uvn.settings.root_vpn.subnet] if self.agent.root_vpn else []),
        *([self.agent.uvn.settings.particles_vpn.subnet] if self.agent.particles_vpn else []),
        *([self.agent.uvn.settings.backbone_vpn.subnet] if self.agent.backbone_vpns else []),
        *([lan for cell in self.agent.uvn.cells.values() for lan in cell.allowed_lans]),
      )
    ):
      self._iptables_install(
        nic,
        [
          "-A",
          chain,
          "-s",
          str(subnet),
          "-i",
          nic,
          "-j",
          "ACCEPT",
        ],
        noop=noop,
      )

    if docker_installed:
      for other_nic in sorted(
        (
          *([self.agent.root_vpn.config.intf.name] if self.agent.root_vpn else []),
          *([self.agent.particles_vpn.config.intf.name] if self.agent.particles_vpn else []),
          *(vpn.config.intf.name for vpn in self.agent.backbone_vpns),
          *(lan.nic.name for lan in self.agent.lans),
        )
      ):
        self._iptables_install(
          nic,
          [
            "-I",
            "DOCKER-USER",
            "-i",
            nic,
            "-o",
            other_nic,
            "-j",
            "ACCEPT",
          ],
          noop=noop,
        )

    # Drop everything else coming through the interface
    self._iptables_install(
      nic,
      [
        "-A",
        chain,
        "-i",
        nic,
        "-j",
        "DROP",
      ],
      noop=noop,
    )

    # Return to FORWARD chain
    self._iptables_install(
      nic,
      [
        "-A",
        chain,
        "-j",
        "RETURN",
      ],
      noop=noop,
    )

  def _vpn_masquerade(self, vpn: WireGuardInterface, noop: bool = False) -> None:
    self._iptables_install(
      vpn.config.intf.name,
      [
        "-t",
        "nat",
        "-A",
        "POSTROUTING",
        "-o",
        str(vpn.config.intf.subnet),
        "-j",
        "MASQUERADE",
      ],
      noop=noop,
    )
    for nic in (
      *(l.nic.name for l in sorted(self.agent.lans, key=lambda l: l.nic.name)),
      *(
        v.config.intf.name
        for v in sorted(self.agent.vpn_interfaces, key=lambda l: l.config.intf.name)
        if v != vpn
      ),
    ):
      self._iptables_install(
        vpn.config.intf.name,
        [
          "-t",
          "nat",
          "-A",
          "POSTROUTING",
          "-s",
          str(vpn.config.intf.subnet),
          "-o",
          nic,
          "-j",
          "MASQUERADE",
        ],
        noop=noop,
      )
    if not noop:
      self.log.debug("NAT ENABLED for VPN interface: {}", vpn)

  def _iptables_install(
    self, rule_id: str, rule: list[str], noop: bool = False, irremovable: bool = False
  ):
    if not noop:
      exec_command(["iptables", *rule])
    if irremovable:
      return
    rules = self._iptables_rules[rule_id] = self._iptables_rules.get(rule_id, [])
    rules.append(rule)
