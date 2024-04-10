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
from typing import TYPE_CHECKING, Generator
from pathlib import Path
import ipaddress
from functools import cached_property
import subprocess
import contextlib
import time
import os
import shutil

from uno.core.time import Timer
from uno.core.exec import exec_command
from uno.core.log import Logger
from uno.registry.cell import Cell
from uno.registry.particle import Particle
from uno.registry.package import Packager
from uno.agent.agent import Agent

from .host_role import HostRole

if TYPE_CHECKING:
  from .experiment import Experiment
  from .network import Network


def _read_networks_file(logger, file: Path) -> set[ipaddress.IPv4Network]:
  if not file.exists():
    logger.warning("filed doesn't exist: {}", file)
    return set()
  def _parse(line):
    try:
      return ipaddress.ip_network(line)
    except:
      logger.error("{} invalid line: '{}'", file, line)
      return None
  return {
    net
    for line in file.read_text().split("\n") if bool(line)
      for net in [_parse(line)]
        if net is not None
  }


class Host:
  def __init__(self,
      experiment: "Experiment",
      hostname: str,
      container_name: str,
      networks: dict["Network", tuple[str, ipaddress.IPv4Address]],
      default_network: "Network",
      role: HostRole,
      upstream_network: "Network|None"=None,
      cell_package: Path|None=None,
      particle_package: Path|None=None,
      image: str|None=None,
      port_forward: "dict[tuple[Network, int], Host]|None"=None):
    self.experiment = experiment
    self.hostname = hostname
    self.container_name = container_name
    self.networks = dict(networks)
    self.default_network = default_network
    assert(self.default_network in self.networks)
    self.upstream_network = upstream_network
    assert(self.upstream_network is None or upstream_network in self.networks)
    self.role = role
    self.cell_package = cell_package.resolve() if cell_package else None
    assert(self.role != HostRole.CELL or self.cell_package is not None)
    self.particle_package = particle_package.resolve() if particle_package else None
    assert(self.role != HostRole.PARTICLE or self.particle_package is not None)
    self.image = image or self.experiment.config["image"]
    self.port_forward = dict(port_forward or {})
    self.log = Logger.sublogger(self.container_name)



  def __str__(self) -> str:
    return f"{self.role.name.lower().capitalize()}({self.container_name})"


  def __repr__(self) -> str:
    return str(self)


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Host):
      return False
    return self.container_name == other.container_name


  def __hash__(self) -> int:
    return hash(self.container_name)


  @property
  def default_address(self) -> ipaddress.IPv4Address:
    return self.networks[self.default_network]


  @property
  def default_nic(self) -> str:
    return self.find_network_interface(self.default_network)


  def find_network_interface(self, network: "Network") -> str:
    return next(nic for nic, addr in self.interfaces.items() if addr in network.subnet)


  @cached_property
  def interfaces(self) -> dict[str, ipaddress.IPv4Address]:
    result = exec_command(["ip -o a s | grep -E ': eth[0-9]+    inet ' | awk '{print $2 \" \" $4;}'"],
      shell=True,
      capture_output=True).stdout
    if not result:
      return {}
    return {
      nic: ipaddress.ip_address(addr.split("/")[0])
      for line in filter(len, result.decode().split("\n"))
        for nic, addr in [line.split(" ")]
    }


  @cached_property
  def adjacent_networks(self) -> "list[Network]":
    return [net for net in self.networks if net != self.default_network]


  @property
  def nameserver_entries(self) -> Generator[tuple[str, ipaddress.IPv4Address], None, None]:
    for net, addr in self.networks.items():
      if net != self.default_network:
        domain = f"{self.default_network.name}.{net.name}"
      else:
        domain = net.name
      yield (f"{self.hostname}.{domain}", addr)


  @cached_property
  def experiment_uvn_dir(self) -> Path:
    return self.experiment.test_dir / self.container_name


  @cached_property
  def test_dir(self) -> Path:
    return self.experiment_uvn_dir / "test"


  def test_file(self, name: str, create: bool=False) -> tuple[Path, Path]:
    self.test_dir.mkdir(exist_ok=True, parents=True)
    output = self.test_dir / name
    if create and output.exists():
      output.unlink()
    return [
      output,
      self.experiment.RunnerExperimentDir / self.test_dir.relative_to(self.experiment.test_dir) / output.name
    ]


  @cached_property
  def container_uvn_dir(self) -> Path:
    return Path("/uvn")


  @cached_property
  def cell(self) -> Cell | None:
    if self.cell_package is None:
      return None
    # Parse cell_package.name
    return Packager.parse_cell_archive_file(self.cell_package, self.experiment.registry.uvn)


  @cached_property
  def particle(self) -> Particle | None:
    if self.particle_package is None:
      return None
    # Parse particle_package.name
    return Packager.parse_particle_archive_file(self.particle_package, self.experiment.registry.uvn)


  @cached_property
  def cell_addresses(self) -> list[ipaddress.IPv4Address]:
    if self.cell is None:
      return []
    addresses = []
    # Add the agents LAN interfaces included in the cell's configuration
    for lan in self.cell.allowed_lans:
      net = next((n for n in self.networks.keys() if n.subnet == lan), None)
      if net is None:
        continue
      addresses.append(self.networks[net])
    # Add the backbone vpn interfaces
    addresses.extend(
      self.experiment.registry.deployment.get_interfaces(self.cell.id))
    return addresses


  @property
  def cell_reachable_networks(self) -> set[ipaddress.IPv4Network]:
    return _read_networks_file(self.log, self.experiment_uvn_dir / "log" / Agent.REACHABLE_NETWORKS_TABLE_FILENAME)


  @property
  def cell_unreachable_networks(self) -> set[ipaddress.IPv4Network]:
    return _read_networks_file(self.log, self.experiment_uvn_dir / "log" / Agent.UNREACHABLE_NETWORKS_TABLE_FILENAME)


  @property
  def cell_known_networks(self) -> set[ipaddress.IPv4Network]:
    return _read_networks_file(self.log, self.experiment_uvn_dir / "log" / Agent.KNOWN_NETWORKS_TABLE_FILENAME)


  @property
  def cell_local_networks(self) -> set[ipaddress.IPv4Network]:
    return _read_networks_file(self.log, self.experiment_uvn_dir / "log" / Agent.LOCAL_NETWORKS_TABLE_FILENAME)


  @property
  def cell_fully_routed(self) -> bool:
    expected_lans = {
      l for c in self.experiment.registry.uvn.cells.values()
        for l in c.allowed_lans
    }
    return expected_lans == self.cell_reachable_networks


  def particle_file(self, cell: Cell, ext: str=".conf") -> tuple[Path, Path]:
    artifacts_dir, artifacts_dir_c = self.test_file(f"{self.particle.uvn.name}__{self.particle.name}")
    basename = Packager.particle_cell_file(self.particle, cell)
    return (artifacts_dir / f"{basename}{ext}", artifacts_dir_c / f"{basename}{ext}")


  @contextlib.contextmanager
  def particle_wg_up(self, cell: Cell) -> Generator[Cell, None, None]:
    conf, conf_c = self.particle_file(cell)
    up_conf_c = conf_c.parent / "uwg-v0.conf"
    self.exec("cp", conf_c, up_conf_c)
    self.exec("wg-quick", "up", up_conf_c)
    try:
      yield cell
    finally:
      self.exec("wg-quick", "down", up_conf_c)


  @property
  def locally_routed_networks(self) -> "set[Network]":
    def _lookup_net(netaddr: str) -> "Network|None":
      try:
        subnet = ipaddress.ip_network(netaddr)
      except:
        return None
      return next((n for n in self.experiment.networks if n.subnet == subnet), None)
    return {
      net
      # Read output of `ip route` and detect lines for networks defined in the experiment
      for line in self.exec("ip", "route", capture_output=True).stdout.decode().split("\n")
        # ignore empty lines
        if line
          # Parse the first token
          for net in [_lookup_net(line.split(" ")[0])]
            if net
    }


  @property
  def local_router_ready(self) -> bool:
    # self.log.warning("local networks: {}", self.locally_routed_networks)
    # self.log.warning("  uvn networks: {}", self.experiment.uvn_networks)
    return (self.locally_routed_networks & self.experiment.uvn_networks) == self.experiment.uvn_networks


  def create(self) -> None:
    # # The uno package must have been imported from a cloned repository on the host
    assert((self.experiment.UnoDir / ".git").is_dir())
    assert(not self.experiment.InsideTestRunner)
    # Make sure the host doesn't exist, then create it
    self.delete(ignore_errors=True)

    self.test_dir.mkdir(exist_ok=True, parents=True)

    if self.role == HostRole.REGISTRY:
      # Make a copy of the registry's uvn directory
      if self.experiment_uvn_dir.is_dir():
        shutil.rmtree(self.experiment_uvn_dir)
      shutil.copytree(self.experiment.registry.root, self.experiment_uvn_dir)

    interactive = self.experiment.config.get("interactive", False)

    verbose_flag = self.log.verbose_flag

    exec_command([
      "docker", "create",
        *(["-ti"] if interactive else []),
        "--init",
        "--name", self.container_name,
        "--hostname", self.hostname,
        "--net", self.default_network.name,
        "--ip", str(self.default_address),
        "--privileged",
        "-w", "/uvn",
        "-v", f"{self.experiment.root}:/experiment",
        "-v", f"{self.experiment.test_dir}:{self.experiment.RunnerExperimentDir}",
        *(["-v", f"{self.experiment_uvn_dir}:/uvn"] if self.role in (HostRole.REGISTRY, HostRole.CELL) else []),
        *(["-v", f"{self.cell_package}:/package.uvn-agent"] if self.role == HostRole.CELL else []),
        *([
          "-v", f"{self.experiment.UnoDir}:/uno",
          "-e", f"UNO_MIDDLEWARE={self.experiment.registry.middleware.plugin}",
        ] if self.experiment.Dev else []),
        "-e", "UNO_TEST_RUNNER=y",
        *(["-e", f"VERBOSITY={self.experiment.Verbosity}"] if self.experiment.Verbosity else []),
        self.image,
        "/uno/uno/test/integration/runner.py",
          "host",
          self.experiment.test_case.name,
          self.container_name,
          *([verbose_flag] if verbose_flag else []),
    ])
    for adj_net in self.adjacent_networks:
      adj_net_addr = self.networks[adj_net]
      exec_command([
        "docker", "network", "connect",
          "--ip", str(adj_net_addr), adj_net.name, self.container_name
      ])


  def start(self, wait: bool=False) -> subprocess.Popen:
    self.log.warning("starting container")
    result = subprocess.Popen(["docker", "start", self.container_name])
    if wait:
      self.wait_ready()
      self.log.activity("started")
    return result


  def stop(self) -> subprocess.Popen:
    self.log.debug("stopping container")
    return subprocess.Popen(["docker", "stop", "-s", "SIGINT", "-t", str(self.experiment.config["container_stop_timeout"]), self.container_name])


  def wait_stop(self, stop_process: subprocess.Popen, timeout: int=30) -> None:
    rc = stop_process.wait(timeout)
    assert rc == 0, f"failed to stop docker container: {self.container_name}"


  def delete(self, ignore_errors: bool=False) -> None:
    exec_command(["docker", "rm", "-f", self.container_name,], noexcept=ignore_errors)


  def install_default_route(self, dev: str, route: ipaddress.IPv4Address) -> None:
    exec_command(["ip", "route", "delete", "default"])
    exec_command(["ip", "route", "add", "default", "via", str(route), "dev", dev])


  def write_hosts(self) -> None:
    hosts = Path("/etc/hosts")
    with hosts.open("at") as output:
      for host, addr in self.experiment.nameserver_entries:
        output.write(f"{addr}    {host}" + "\n")


  @cached_property
  def status_file(self) -> Path:
    return self.experiment.test_dir / f"{self.container_name}.status" 


  @contextlib.contextmanager
  def _container_ready(self) -> Generator["Host", None, None]:
    self.status_file.write_text("READY")
    try:
      yield self
    finally:
      try:
        self.status_file.write_text("")
        self.status_file.unlink()
      except Exception as e:
        self.log.error("failed to delete status file: {}", self.status_file)
        self.log.exception(e)


  @property
  def ready(self) -> bool:
    if not self.status_file.exists():
      return False
    return self.status_file.read_text() == "READY"


  def wait_ready(self, timeout: int=60) -> None:
    self.log.activity("waiting for container to be up")
    Timer(timeout, .5, lambda: self.ready, self.log,
      f"waiting for container {self.container_name} to be up",
      f"container {self.container_name} not ready yet...",
      f"container {self.container_name} ready",
      f"container {self.container_name} failed to activate").wait()


#   @property
#   def agent_alive(self) -> bool:
#     result = self.exec("sh", "-c", """\
# [ -f /run/uno/uno-agent.pid ] || exit
# kill -0 $(cat /run/uno/uno-agent.pid) && echo OK
# """, capture_output=True, shell=True).stdout
#     if not result:
#       return False
#     result = result.decode().strip()
#     return result == "OK"
#     # return result and result.decode().strip() == "OK"


  def init(self) -> None:
    # Dispatch to role-specific implementation
    initializer = getattr(self, f"_init_{self.role.name.lower()}")
    initializer()


  def _init_common(self) -> None:
    self.write_hosts()


  def _init_host(self) -> None:
    self._init_common()
    self.install_default_route(
      dev=self.default_nic, route=self.default_network.router_address)


  def _init_router(self) -> None:
    # Kernel forwarding is expected to be already enabled on the host, because Docker needs it.
    assert(int(exec_command(["cat", "/proc/sys/net/ipv4/ip_forward"], capture_output=True).stdout.decode().strip()) == 1)

    self._init_common()

    # Set default forward policy to DROP
    exec_command(["iptables", "-P", "FORWARD", "DROP"])

    # Route all traffic locally
    exec_command(["iptables", "-A", "FORWARD", "-i", self.default_nic, "-o", self.default_nic, "-j", "ACCEPT"])

    # Install default route to upstream network or just delete default route
    if self.upstream_network:
      dev = self.find_network_interface(self.upstream_network)
      self.install_default_route(
        dev=dev, route=self.upstream_network.router_address)
    else:
      exec_command(["ip", "route", "delete", "default"])

    # Configure NAT and enable forwarding between default network and adjacent networks
    def _enable_fwd(nic_in: str, nic_out: str):
      exec_command([
        "iptables", "-A", "FORWARD", "-i", nic_in, "-o", nic_out,
          "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT",
      ])
      exec_command([
        "iptables", "-A", "FORWARD", "-i", nic_in, "-o", nic_out, "-j", "ACCEPT"
      ])

    for adj_net in self.adjacent_networks:
      adj_net_dev = self.find_network_interface(adj_net)
      exec_command([
        "iptables", "-t", "nat", "-A", "POSTROUTING", "-o", adj_net_dev, "-j", "MASQUERADE",
      ])
      _enable_fwd(adj_net_dev, self.default_nic)
      _enable_fwd(self.default_nic, adj_net_dev)

    # Forward ports if configured
    if self.port_forward:
      upstream_dev = self.find_network_interface(self.upstream_network)
      for (dest_net, port), host in self.port_forward.items():
        # adj_net_dev = self.find_network_interface(adj_net)
        host_addr = host.networks[dest_net]
        exec_command([
          "iptables", "-t", "nat", "-A", "PREROUTING", "-i", upstream_dev, "-p", "udp", "--dport", str(port),
            "-j", "DNAT", "--to-destination", f"{host_addr}:{port}"
        ])


    # Add static routes for UVN networks via the router's default network's public agent
    # Add also a static route for the backbone vpn and root vpn addresses
    if self.default_network.public_agent:
      agent_addr = self.default_network.public_agent.networks[self.default_network]
      other_cell_networks = [
        lan
        for cell in self.experiment.registry.uvn.cells.values()
          for lan in cell.allowed_lans
            if lan != self.default_network.subnet
      ]
      for other_net in (
          *other_cell_networks,
          self.experiment.registry.uvn.settings.root_vpn.subnet,
          self.experiment.registry.uvn.settings.backbone_vpn.subnet):
        exec_command([
          "ip", "route", "add", str(other_net), "via", str(agent_addr)
        ])


  def _init_cell(self) -> None:
    self._init_common()
    self.install_default_route(
      dev=self.default_nic, route=self.default_network.router_address)


  def _init_registry(self) -> None:
    self._init_common()
    self.install_default_route(
      dev=self.default_nic, route=self.default_network.router_address)


  def _init_particle(self) -> None:
    self._init_common()
    # Extract particle package
    exec_command([
      "unzip", "-o", self.particle_package
    ], cwd=self.test_dir)


  def run(self) -> None:
    # Dispatch to role-specific implementation
    runner = getattr(self, f"_run_{self.role.name.lower()}")
    runner()


  def _run_forever(self) -> None:
    with self._container_ready():
      try:
        while True:
          time.sleep(1)
      except KeyboardInterrupt:
        self.log.error("SIGINT detected")


  def _docker_exec_cmd(self, *args,
      user: str|None=None,
      interactive: bool=False,
      terminal: bool=False) -> list[str|Path]:
    return [
      "docker", "exec",
        *(["-u", user] if user else []),
        *(["-i"] if interactive else []),
        *(["-t"] if terminal else []),
        self.container_name, *args
    ]


  def exec(self, *args, user: str|None=None, **exec_args):
    if self.experiment.InsideTestRunner:
      cmd = args
      assert(user is None)
    else:
      cmd = self._docker_exec_cmd(*args, user=user)
    return exec_command(cmd, **exec_args)


  def popen(self, *args, user: str|None=None, capture_output: bool=False, **popen_args) -> subprocess.Popen:
    # Stop signals from propagating to the child process by default
    popen_args.setdefault("preexec_fn", os.setpgrp)
    if capture_output:
      popen_args.update({
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
      })
    if self.experiment.InsideTestRunner:
      cmd = args
      assert(user is None)
    else:
      cmd = self._docker_exec_cmd(*args, user=user)
    return subprocess.Popen(cmd, **popen_args)


  def uno(self, *args, user: str|None=None, popen: bool=False, **exec_args):
    verbose_flag = self.log.verbose_flag
    uno_cmd = ["uno", *args, "-r", self.container_uvn_dir, *([verbose_flag] if verbose_flag else [])]
    if popen:
      return self.popen(*uno_cmd, user=user, **exec_args)
    else:
      exec_args.setdefault("capture_output", True)
      return self.exec(*uno_cmd, user=user, debug=True, **exec_args)


  @contextlib.contextmanager
  def _uno_service_up(self) -> Generator["Host", None, None]:
    self.uno("service", "up")
    try:
      yield self
    finally:
      self.uno("service", "down")
    

  def _run_host(self) -> None:
    self._run_forever()


  def _run_cell(self) -> None:
    self.uno("install", "/package.uvn-agent", "-r", "/uvn")
    with self._uno_service_up():
      self._run_forever()


  def _run_registry(self) -> None:
    # Load services so that the router process gets
    # inherited by "init"
    with self._uno_service_up():
      self._run_forever()


  def _run_router(self) -> None:
    self._run_forever()


  def _run_particle(self) -> None:
    self._run_forever()


  # def ping_test_start(self, other_host: "Host", address: ipaddress.IPv4Address) -> subprocess.Popen:
  #   self.log.activity("performing PING test with {}: {}", other_host, address)
  #   return self.popen("ping", "-c", "3", str(address))


  # def ping_test_check(self, other_host: "Host", address: ipaddress.IPv4Address, ping_test: subprocess.Popen) -> None:
  #   rc = ping_test.wait()
  #   assert rc == 0, f"PING FAILED: {self} -> {other_host}@{address}"
  #   self.log.info("PING {} OK: {}", other_host, address)
    
      

  @contextlib.contextmanager
  def iperf_server(self) -> Generator[subprocess.Popen, None, None]:
    self.log.activity("starting iperf3 server")
    server = self.popen("iperf3", "-s", "-B", str(self.default_address),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE)
    if server.poll():
      raise RuntimeError("failed to start iperf3 server", self)
    time.sleep(.5)
    try:
      yield server
    finally:
      self.iperf_server_stop(server)


  def iperf_server_stop(self, server: subprocess.Popen) -> str | None:
    if server.poll():
      self.log.debug("iperf3 server already stopped")
      return
    self.exec("sh", "-c", "kill -s INT $(ps aux | grep iperf3 | grep -v grep | awk '{print $2;}')")
    stdout, stderr = server.communicate()
    self.log.activity("stopped iperf3 server")
    if not stdout:
      return None
    stdout = stdout.decode()
    for line in stdout.split("\n"):
      if not line.endswith("receiver"):
        continue
      return "]".join(line[:-len("receiver")].split("]")[1:]).strip()
    raise RuntimeError("failed to detect iperf3 server's result", self, stdout)


  def iperf_test(self, server: "Host", tcp: bool=True) -> None:
    with server.iperf_server() as iperf_server:
      self.log.activity("performing iperf3 {} test: {}",
        "TCP" if tcp else "UDP", server)
      test_len_exp = 5
      timer = Timer()
      timer.start()
      self.exec("iperf3",
        "-B", str(self.default_address),
        "-c", str(server.default_address),
        # Select UDP if needed
        *(["-u"] if not tcp else []),
        # Force ipv4
        "-4", 
        # Run for 10 seconds for TCP, 10 for UDP
        "-t", str(test_len_exp))
      test_len = timer.stop()
      self.log.info("iperf3 {} test completed in {} seconds: {}",
        "TCP" if tcp else "UDP", test_len.total_seconds(), server)
      result = server.iperf_server_stop(iperf_server)
      assert(result is not None)
      self.log.info("iperf3 server result: {}", result)


  @contextlib.contextmanager
  def ssh_server(self) -> Generator[subprocess.Popen, None, None]:
    self.log.activity("starting SSH server")
    self.exec("mkdir", "-p", "/run/sshd")
    server = self.popen("/usr/sbin/sshd", "-D")
    if server.poll():
      raise RuntimeError("failed to start SSH server", self)
    time.sleep(.5)
    try:
      yield server
    finally:
      import signal
      server.send_signal(signal.SIGINT)
      server.wait(timeout=30)
      # self.exec("killall", "sshd")
      self.log.activity("stopped SSH server")



  @contextlib.contextmanager
  def uno_agent(self, wait_exit: bool=False, start_timeout: bool=60, stop_timeout: bool=60, graceful: bool=True) -> Generator[subprocess.Popen, None, None]:
    agent = self.uno("agent", popen=True)
    if agent.poll():
      raise RuntimeError("failed to start uno agent", self)
    self.uno_agent_wait_ready(timeout=start_timeout)
    try:
      yield agent
    finally:
      self.uno_agent_request_stop()
      if wait_exit:
        self.uno_agent_wait_exit(timeout=stop_timeout, graceful=graceful)


  def uno_agent_pid(self) -> int | None:
    result = self.exec("sh", "-ec", """\
[ ! -f /run/uno/uno-agent.pid ] || cat /run/uno/uno-agent.pid
""", capture_output=True).stdout
    if not result:
      return None
    pid = result.decode().strip()
    if not pid:
      return None
    try:
      return int(pid)
    except Exception as e:
      self.log.warning("failed to parse agent pid: '{}'", pid)
      return None


  def uno_agent_running(self) -> bool:
    result = self.exec("sh", "-ec",
      "[ -f /run/uno/uno-agent.pid ] && kill -0 $(cat /run/uno/uno-agent.pid)",
      noexcept=True)
    return result.returncode == 0


  def uno_agent_wait_ready(self, timeout: float=60) -> None:
    timer = Timer(timeout, .5, lambda: self.uno_agent_running(), self.log,
      "waiting for cell agent to start",
      "cell agent not ready yet",
      "cell agent started",
      f"cell agent {self} failed to start")
    timer.wait()


  def uno_agent_request_stop(self) -> None:
    self.exec("sh", "-exc",
      "[ ! -f /run/uno/uno-agent.pid ] || kill -s INT $(cat /run/uno/uno-agent.pid)")


  def uno_agent_wait_exit(self, timeout: float=60, graceful: bool=True) -> None:
    timer = Timer(timeout, 1, lambda: not self.uno_agent_running(), self.log,
      "waiting for cell agent to exit",
      "cell agent still running",
      "cell agent stopped",
      "cell agent failed to stop gracefully")
    try:
      timer.wait()
    except Timer.TimeoutError:
      if graceful:
        raise
      self.log.warning("failed to stop agent process gracefully, sending SIGKILL")
      self.exec("sh", "-exc", "kill -9 $(cat /run/uno/uno-agent.pid)")


  def agent_httpd_test(self, agent_host: "Host") -> None:
    def _test_url(address: ipaddress.IPv4Address):
      output, output_c = self.test_file(f"{agent_host.container_name}-{address}-index.html", create=True)
      agent_url = f"https://{address}"
      self.log.activity("test HTTP GET {} -> {}", agent_url, output.name)
      # assert(agent_host.agent_alive)
      self.exec("curl",
        "-v",
        "--output", output_c,
        # Since the agent uses a self-signed certificate, disable certificate verification
        "--insecure",
        # TODO(asorbini) use the central CA to sign the certificate, then pass the
        # CA's certificate.
        # "--cacert", ca_cert
        agent_url)
      assert(output.exists())
      assert(output.stat().st_size > 0)
      with output.open("rt") as input:
        first_line = input.readline().strip()
        assert(first_line == "<!doctype html>")
      # <!doctype html>
      # assert(agent_host.agent_alive)
      self.log.info("HTTP GET {} -> {}", agent_url, output.name)
      return output

    # Agent should be accessible on it's "default address",
    # if it's not roaming, and on its backbone interfaces
    self.log.activity("performing HTTPD test on {} addresses for {}: {}",
      len(agent_host.cell_addresses), agent_host, agent_host.cell_addresses)
    assert(len(agent_host.cell_addresses) > 0)
    # import hashlib
    # def _hash(f: Path) -> str:
    #   h = hashlib.sha256()
    #   h.update(f.read_bytes())
    #   return h.hexdigest()
    downloaded = []
    for addr in agent_host.cell_addresses:
      downloaded.append(_test_url(addr))
    # We can't compare the downloaded files, because the agent might
    # have updated the HTML in between calls
    # if len(downloaded) > 1:
    #   prev = downloaded[0]
    #   for other in downloaded[1:]:
    #     assert(prev.stat().st_size == other.stat().st_size)
    #     assert(_hash(prev) == _hash(other))
    #     prev = other
    self.log.info("{} HTTP interfaces OK: {}", len(agent_host.cell_addresses), agent_host)

