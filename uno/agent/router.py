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
from typing import TYPE_CHECKING, Iterable, Tuple

from .render import Templates
from ..core.wg import WireGuardInterface
from ..core.exec import exec_command
from ..core.log import Logger as log

if TYPE_CHECKING:
  from .cell_agent import CellAgent


class Router:
  FRR_CONF = "/etc/frr/frr.conf"
  ROUTER_USER = "frr"
  ROUTER_GROUP = "frr"

  def __init__(self, agent: "CellAgent") -> None:
    self.agent = agent


  @property
  def log_dir(self) -> Path:
    log_dir = self.agent.log_dir / "frr"
    if not log_dir.is_dir():
      log_dir.mkdir(parents=True)
      exec_command([
        "chown", f"{Router.ROUTER_USER}:{Router.ROUTER_GROUP}", log_dir
      ])
    return log_dir


  @property
  def frr_config(self) -> Tuple[str, dict]:
    def _frr_serialize_vpn(vpn: WireGuardInterface) -> dict:
      return {
        "name": vpn.config.intf.name,
        "address": vpn.config.intf.address,
        "address_peer": vpn.config.peers[0].address,
        "mask": vpn.config.intf.netmask,
        "neighbor": self.agent.uvn_id.settings.root_vpn.base_ip + vpn.config.peers[0].id,
        "bgp_as": vpn.config.peers[0].id,
        "subnet": vpn.config.intf.subnet,
      }
    #########################################################################
    # FRR configuration for cell agent
    #########################################################################
    static_routes = []
    ctx = {
      "bgp_as": self.agent.cell.id,
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
          "subnet": lan.nic.subnet,
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
    return ("router/frr.bgp.conf", ctx)


  def start(self) -> None:
    log.debug(f"[ROUTER] starting frrouting...")
    
    # Make sure log directory exists and is writable
    # TODO(asorbini) fix these ugly permissions
    # self.log_dir.mkdir(parents=True, exist_ok=True)
    # self.log_dir.chmod(0o777)

    # Generate and install frr.conf
    Templates.generate(self.FRR_CONF, *self.frr_config)
    
    # Make sure the required frr daemons are enabled
    exec_command(["sed", "-i", "-r", r"s/^(zebra|ospfd|bgpd)=no$/\1=yes/g", "/etc/frr/daemons"])

    # (Re)start frr
    exec_command(["service", "frr", "restart"])

    log.activity(f"[ROUTER] started")


  def update_state(self) -> None:
    self.ospf_neighbors()
    self.ospf_routes()
    self.ospf_interfaces()
    self.ospf_borders()
    self.ospf_lsa()
    self.ospf_summary()


  def stop(self) -> None:
    log.debug(f"[ROUTER] stopping frrouting...")
    exec_command(["service", "frr", "stop"])
    log.activity(f"[ROUTER] stopped")



  def ospf_neighbors(self) -> None:
    self.vtysh(["show ip ospf neighbor"], output_file=self.ospf_neighbors_f)


  def ospf_routes(self) -> None:
    self.vtysh(["show ip ospf route"], output_file=self.ospf_routes_f)


  def ospf_interfaces(self) -> str:
    self.vtysh(["show ip ospf interface"], output_file=self.ospf_interfaces_f)


  def ospf_borders(self) -> None:
    self.vtysh(["show ip ospf border-routers"], output_file=self.ospf_borders_f)


  def ospf_lsa(self) -> None:
    with self.ospf_lsa_f.open("wt") as output:
      output.write(self.vtysh(["show ip ospf database self-originate"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database summary"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database asbr-summary"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database router"]))
      output.write("\n")


  def ospf_summary(self) -> str:
    with self.ospf_summary_f.open("wt") as output:
      output.write(self.vtysh(["show ip ospf database self-originate"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf border-routers"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf neighbor"]))
      output.write("\n")


  @property
  def ospf_neighbors_f(self) -> Path:
    return self.log_dir / "ospf.neighbors"


  @property
  def ospf_routes_f(self) -> Path:
    return self.log_dir / "ospf.routes"


  @property
  def ospf_interfaces_f(self) -> Path:
    return self.log_dir / "ospf.interfaces"


  @property
  def ospf_borders_f(self) -> Path:
    return self.log_dir / "ospf.borders"


  @property
  def ospf_lsa_f(self) -> Path:
    return self.log_dir / "ospf.lsa"


  @property
  def ospf_summary_f(self) -> Path:
    return self.log_dir / "ospf.summary"


  def vtysh(self, cmd: Iterable[str|Path], output_file: Path|None=None) -> str|None:
    cmd = ["vtysh", "-E", "-c", *cmd]
    result = exec_command(cmd,
      fail_msg="failed to perform vtysh command",
      capture_output=not output_file,
      output_file=output_file)
    if not output_file:
      return result.stdout.decode("utf-8")
