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
from typing import TYPE_CHECKING, Iterable
import tempfile

from .wg import WireGuardInterface
from .render import Templates
from .exec import exec_command

from .log import Logger as log

if TYPE_CHECKING:
  from .agent import CellAgent

class Vtysh:
    commands = {
        "ospf": {
            "info": {
                "neighbors": ["show ip ospf neighbor"],
                "routes": ["show ip ospf route"],
                "interfaces": ["show ip ospf interface"],
                "borders": ["show ip ospf border-routers"],
                "lsa": [
                    "show ip ospf database self-originate",
                    "show ip ospf database summary",
                    "show ip ospf database asbr-summary",
                    "show ip ospf database router"
                ],
                "summary": [
                    "show ip ospf database self-originate",
                    "show ip ospf border-routers",
                    "show ip ospf neighbor"
                ]
            }
        }
    }



class Router:
  FRR_CONF = "/etc/frr/frr.conf"

  def __init__(self, agent: "CellAgent") -> None:
    self.agent = agent
    self.log_dir = self.agent.root / "router-log"

  @property
  def frr_config(self) -> str:
    def _frr_serialize_vpn(vpn: WireGuardInterface) -> dict:
      return {
        "name": vpn.config.intf.name,
        "address": vpn.config.intf.address,
        "mask": vpn.config.intf.netmask,
      }
    #########################################################################
    # FRR configuration for cell agent
    #########################################################################
    static_routes = []
    ctx = {
      "timing": self.agent.uvn_id.settings.timing_profile,
      "message_digest_key": f"{self.agent.uvn_id.name}-{self.agent.deployment.generation_ts}",
      "hostname": self.agent.cell.address,
      "root": _frr_serialize_vpn(self.agent.root_vpn),
      "backbone": [
        _frr_serialize_vpn(v) for v in self.agent.backbone_vpns
      ],
      "lans": [
        {
          "name": lan.nic.name,
          "address": lan.nic.address,
          "mask": lan.nic.netmask,
          "area": lan.nic.subnet.network_address,
          "gw": lan.gw,
        } for lan in self.agent.lans
      ],
      "static_routes": [
        {
          "subnet": r["subnet"],
          "route_gw": r["route_gw"],
        } for r in static_routes
      ],
      "router_id": str(self.agent.root_vpn.config.intf.address),
      "log_dir": self.log_dir,
    }
    return Templates.render("router/frr.conf", ctx)


  def start(self) -> None:
    log.debug(f"[ROUTER] starting frrouting...")
    
    # Make sure log directory exists and is writable
    # TODO(asorbini) fix these ugly permissions
    self.log_dir.mkdir(parents=True, exist_ok=True)
    self.log_dir.chmod(0o777)

    # Generate and install frr.conf
    tmp_file_h = tempfile.NamedTemporaryFile()
    tmp_file = Path(tmp_file_h.name)
    tmp_file.write_text(self.frr_config)
    exec_command(["cp", tmp_file, self.FRR_CONF], root=True)
    
    # Make sure the required frr daemons are enabled
    exec_command(["sed", "-i", "-r", r"s/^(zebra|ospfd)=no$/\1=yes/g", "/etc/frr/daemons"], root=True)

    # (Re)start frr
    exec_command(["service", "frr", "restart"], root=True)

    log.activity(f"[ROUTER] started")


  def stop(self) -> None:
    log.debug(f"[ROUTER] stopping frrouting...")
    exec_command(["service", "frr", "stop"], root=True)
    log.activity(f"[ROUTER] stopped")


  @property
  def ospf_neighbors(self) -> str:
    return self.vtysh(["show ip ospf neighbor"])


  @property
  def ospf_routes(self) -> str:
    return self.vtysh(["show ip ospf route"])


  @property
  def ospf_interfaces(self) -> str:
    return self.vtysh(["show ip ospf interface"])


  @property
  def ospf_borders(self) -> str:
    return self.vtysh(["show ip ospf border-routers"])

  @property
  def ospf_lsa(self) -> str:
    return "\n".join([
      self.vtysh(["show ip ospf database self-originate"]),
      self.vtysh(["show ip ospf database summary"]),
      self.vtysh(["show ip ospf database asbr-summary"]),
      self.vtysh(["show ip ospf database router"]),
    ])


  @property
  def ospf_summary(self) -> str:
    return "\n".join([
      self.vtysh(["show ip ospf database self-originate"]),
      self.vtysh(["show ip ospf border-routers"]),
      self.vtysh(["show ip ospf neighbor"]),
    ])


  def vtysh(self, cmd: Iterable[str|Path]):
    cmd = ["vtysh", "-E", "-c", *cmd]
    result = exec_command(cmd,
      fail_msg="failed to perform vtysh command",
      root=True,
      capture_output=True)
    return result.stdout.decode("utf-8")
