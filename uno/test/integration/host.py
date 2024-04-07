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

from .host_role import HostRole

if TYPE_CHECKING:
  from .experiment import Experiment
  from .network import Network

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
    assert(self.role != HostRole.AGENT or self.cell_package is not None)
    self.image = image or "uno:latest"
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
  def container_uvn_dir(self) -> Path:
    return Path("/uvn")


  def create(self) -> None:
    assert(not self.experiment.inside_test_runner)

    # Make sure the host doesn't exist, then create it
    self.delete(ignore_errors=True)
    import uno
    uno_dir = Path(uno.__file__).parent.parent
    # The uno package must have been imported from a cloned repository
    assert((uno_dir / ".git").is_dir())

    if self.role == HostRole.REGISTRY:
      # Make a copy of the registry's uvn directory
      if self.experiment_uvn_dir.is_dir():
        shutil.rmtree(self.experiment_uvn_dir)
      shutil.copytree(self.experiment.registry.root, self.experiment_uvn_dir)

    plugin_base_dir = Path(self.experiment.registry.middleware.module.__file__).parent
    try:
      # If the plugin directory is in the base uno repository, we don't need to mount it
      plugin_base_dir.relative_to(uno_dir)
      plugin_base_dir = None
    except ValueError:
      # Determine the base directory to add to PYTHONPATH
      plugin_parent_depth = len(self.experiment.registry.middleware.plugin.split("."))
      for i in range(plugin_parent_depth):
        plugin_base_dir = plugin_base_dir.parent

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
        "-v", f"{self.experiment.test_dir}:/experiment-tmp",
        "-v", f"{uno_dir.resolve()}:/uno",
        "-e", f"UNO_MIDDLEWARE={self.experiment.registry.middleware.plugin}",
        *(["-v", f"{plugin_base_dir}:/uno-middleware"] if plugin_base_dir else []),
        "-v", f"{self.experiment.registry.root}:/experiment-uvn",
        *(["-v", f"{self.experiment_uvn_dir}:/uvn"] if self.role in (HostRole.REGISTRY, HostRole.AGENT) else []),
        *(["-v", f"{self.cell_package}:/package.uvn-agent"] if self.role == HostRole.AGENT else []),
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


  def start(self, wait: bool=True) -> None:
    self.log.debug("starting container")
    exec_command(["docker", "start", self.container_name])
    if wait:
      self.wait_ready()
    self.log.activity("started")


  def stop(self) -> None:
    self.log.debug("stopping container")
    exec_command(["docker", "stop", "-s", "SIGINT", "-t", str(self.experiment.container_wait), self.container_name])
    self.log.activity("stopped")


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


  def wait_ready(self) -> None:
    self.log.activity("waiting for container to be up")
    Timer(30, 1, lambda: self.ready, self.log,
      "waiting for container to be up",
      "container not ready yet...",
      "container ready",
      "container failed to activate").wait()


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


  def _init_agent(self) -> None:
    self._init_common()
    self.install_default_route(
      dev=self.default_nic, route=self.default_network.router_address)


  def _init_registry(self) -> None:
    self._init_common()
    self.install_default_route(
      dev=self.default_nic, route=self.default_network.router_address)


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
    if self.experiment.inside_test_runner:
      cmd = args
      assert(user is None)
    else:
      cmd = self._docker_exec_cmd(*args, user=user)
    return exec_command(cmd, **exec_args)


  def popen(self, *args, user: str|None=None, **popen_args) -> subprocess.Popen:
    # Stop signals from propagating to the child process by default
    popen_args.setdefault("preexec_fn", os.setpgrp)
    if self.experiment.inside_test_runner:
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
      return self.exec(*uno_cmd, user=user, **exec_args)


  @contextlib.contextmanager
  def _uno_service_up(self) -> Generator["Host", None, None]:
    self.uno("service", "up")
    try:
      yield self
    finally:
      self.uno("service", "down")
    

  def _run_host(self) -> None:
    self._run_forever()


  def _run_agent(self) -> None:
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


  def ping_test(self, other_host: "Host") -> None:
    self.log.activity("performing PING test: {}", other_host)
    self.exec("ping", "-c", "3", str(other_host.default_address))
    self.log.info("PING OK: {}", other_host)


  @contextlib.contextmanager
  def iperf_server(self) -> Generator[subprocess.Popen, None, None]:
    self.log.activity("starting iperf3 server")
    server = self.popen("iperf3", "-s", "-B", str(self.default_address),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE)
    if server.poll():
      raise RuntimeError("failed to start iperf3 server", self)
    time.sleep(1)
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
    time.sleep(1)
    try:
      yield server
    finally:
      import signal
      server.send_signal(signal.SIGINT)
      server.wait(timeout=5)
      self.exec("killall", "sshd")
      self.log.activity("stopped SSH server")


  def ssh_test(self, server: "Host") -> None:
    with server.ssh_server() as ssh_server:
      # Connect via SSH and run a "dummy" test (e.g. verify that the hostname is what we expect)
      # We mostly want to make sure we can establish an SSH connection through the UVN
      self.log.activity("performing SSH test: {}", server)
      self.exec("sh", "-c", f"ssh-keyscan -p 22 -H {server.default_address} >> ~/.ssh/known_hosts",
        user="uno")
      result = self.exec("sh", "-c", f"ssh uno@{server.default_address} 'echo THIS_IS_A_TEST_ON $(hostname)' | grep 'THIS_IS_A_TEST_ON {server.hostname}'",
        user="uno", capture_output=True)
      assert(result.stdout.decode().strip() == f"THIS_IS_A_TEST_ON {server.hostname}")
      self.log.info("SSH test completed: {}", server)


  @contextlib.contextmanager
  def uno_agent(self) -> Generator[subprocess.Popen, None, None]:
    agent = self.uno("agent", popen=True)
    if agent.poll():
      raise RuntimeError("failed to start uno agent", self)
    time.sleep(1)
    try:
      yield agent
    finally:
      self.uno_agent_stop(agent)


  def uno_agent_stop(self, agent: subprocess.Popen) -> None:
    if agent.poll():
      self.log.warning("uno agent already stopped")
      return
    self.exec("sh", "-exc", """\
[ -f /run/uno/uno-agent.pid ] || exit
unopid=$(cat /run/uno/uno-agent.pid)
kill -s INT $unopid
while kill -0 $unopid
  do sleep 1
done
""")
    # stdout, stderr = agent.communicate()
    self.log.activity("stopped uno agent")

