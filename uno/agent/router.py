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
from typing import Iterable
    

from .render import Templates
from ..core.wg import WireGuardInterface
from ..core.exec import exec_command
from ..registry.cell import Cell
from .agent_service import AgentService


class Router(AgentService):
  USER = ["frr", "frr"]
  
  FRR_CONF = "/etc/frr/frr.conf"

  STATIC_SERVICE = "router"

  # def __init__(self, **properties) -> None:
  #   self.__init__(**properties)
  #   self._watchfrr = None
  #   self._watchfrr_thread = None
  #   self._watchfrr_thread_active = False
  #   self._watchfrr_thread_started = threading.Semaphore(0)
  #   self._watchfrr_thread_exit = threading.Semaphore(0)


  def check_runnable(self) -> bool:
    return isinstance(self.agent.owner, Cell)


  @property
  def frr_config(self) -> tuple[str, dict]:
    def _frr_serialize_vpn(vpn: WireGuardInterface) -> dict:
      return {
        "name": vpn.config.intf.name,
        "address": vpn.config.intf.address,
        "address_peer": vpn.config.peers[0].address,
        "mask": vpn.config.intf.netmask,
        "neighbor": self.agent.uvn.settings.root_vpn.base_ip + vpn.config.peers[0].id,
        "bgp_as": vpn.config.peers[0].id,
        "subnet": vpn.config.intf.subnet,
      }
    #########################################################################
    # FRR configuration for cell agent
    #########################################################################
    static_routes = []
    ctx = {
      "bgp_as": self.agent.owner.id,
      "timing": self.agent.uvn.settings.timing_profile,
      "message_digest_key": f"{self.agent.uvn.name}-{self.agent.deployment.generation_ts}",
      "hostname": self.agent.owner.address,
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


  def _start(self) -> None:
    # Generate and install frr.conf
    Templates.generate(self.FRR_CONF, *self.frr_config)
    # Make sure the required frr daemons are enabled
    exec_command(["sed", "-i", "-r", r"s/^(zebra|bgpd)=no$/\1=yes/g", "/etc/frr/daemons"])
    # (Re)start frr
    # if Systemd.available:
    exec_command(["service", "frr", "restart"])

    # self._watchfrr = subprocess.Popen([
    #     "bash", "-c", "source /usr/lib/frr/frrcommon.sh; /usr/lib/frr/watchfrr $(daemon_list)"
    #   ],
    #   stdin=subprocess.DEVNULL,
    #   stdout=subprocess.PIPE,
    #   stderr=subprocess.DEVNULL,
    #   preexec_fn=os.setpgrp,
    #   text=True)
    # self._watchfrr_thread = threading.Thread(target=self._watchfrr_thread_run)
    # self._watchfrr_thread_active = True
    # self._watchfrr_thread.start()
    # self._watchfrr_thread_started.acquire()


  def _watchfrr_thread_run(self):
    self.log.activity("starting FRR daemons...")
    self._watchfrr_thread_started.release()
    while self._watchfrr_thread_active:
      try:
        self.log.debug("waiting for exit signal...")
        self._watchfrr_thread_exit.acquire()
      except Exception as e:
        self.log.error("error in router thread")
        self.log.exception(e)
    self.log.activity("stopped")



  def _stop(self, assert_stopped: bool) -> None:
    exec_command(["service", "frr", "stop"])
    # if self._watchfrr is not None:
    #   self._watchfrr_thread_active = False
    #   self._watchfrr.send_signal(signal.SIGINT)
    #   if self._watchfrr_thread is not None:
    #     self._watchfrr_thread.join()
    #     self._watchfrr_thread = None
    #   self._watchfrr = None


  def vtysh(self, cmd: Iterable[str|Path], output_file: Path|None=None) -> str|None:
    cmd = ["vtysh", "-E", "-c", *cmd]
    result = exec_command(cmd,
      fail_msg="failed to perform vtysh command",
      capture_output=not output_file,
      output_file=output_file)
    if not output_file:
      return result.stdout.decode("utf-8")


  def _generate_ospf_neighbors(self, output: Path) -> None:
    self.vtysh(["show ip ospf neighbor"], output_file=output)


  def _generate_ospf_routes(self, output: Path) -> None:
    self.vtysh(["show ip ospf route"], output_file=output)


  def _generate_ospf_interfaces(self, output: Path) -> str:
    self.vtysh(["show ip ospf interface"], output_file=output)


  def _generate_ospf_borders(self, output: Path) -> None:
    self.vtysh(["show ip ospf border-routers"], output_file=output)


  def _generate_ospf_lsa(self, output: Path) -> None:
    with output.open("wt") as output:
      output.write(self.vtysh(["show ip ospf database self-originate"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database summary"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database asbr-summary"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf database router"]))
      output.write("\n")


  def _generate_ospf_summary(self, output: Path) -> str:
    with output.open("wt") as output:
      output.write(self.vtysh(["show ip ospf database self-originate"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf border-routers"]))
      output.write("\n")
      output.write(self.vtysh(["show ip ospf neighbor"]))
      output.write("\n")


  @property
  def ospf_neighbors(self) -> Path:
    output = self.log_dir / "ospf.neighbors"
    self._generate_ospf_neighbors(output)
    return output


  @property
  def ospf_routes(self) -> Path:
    output = self.log_dir / "ospf.routes"
    self._generate_ospf_neighbors(output)
    return output


  @property
  def ospf_interfaces(self) -> Path:
    output = self.log_dir / "ospf.interfaces"
    self._generate_ospf_neighbors(output)
    return output


  @property
  def ospf_borders(self) -> Path:
    output = self.log_dir / "ospf.borders"
    self._generate_ospf_neighbors(output)
    return output


  @property
  def ospf_lsa(self) -> Path:
    output = self.log_dir / "ospf.lsa"
    self._generate_ospf_neighbors(output)
    return output


  @property
  def ospf_summary(self) -> Path:
    output = self.log_dir / "ospf.summary"
    self._generate_ospf_neighbors(output)
    return output

