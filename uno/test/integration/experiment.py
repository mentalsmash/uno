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
from typing import Generator
from types import ModuleType
from pathlib import Path
import ipaddress
import tempfile
import os
from functools import cached_property

from uno.core.exec import exec_command
from uno.core.log import Logger
from uno.registry.registry import Registry
from uno.middleware import Middleware

from .network import Network
from .host import Host
from .host_role import HostRole

import uno
uno_dir = Path(uno.__file__).parent.parent


class Experiment:
  uno_dir = Path(uno.__file__).parent.parent
  BuiltImages = set()

  def __init__(self,
      test_case: Path,
      name: str | None=None,
      root: Path | None=None,
      config: dict|None=None,
      registry: Registry|None=None,
      registry_tmp: tempfile.TemporaryDirectory|None=None,
      container_wait: int=60,
      test_dir: Path | None=None) -> None:
    self.test_case = test_case.resolve()
    self.name = name or test_case.stem.replace("_", "-")
    self.log = Logger.sublogger(self.name)
    VERBOSITY = os.environ.get("VERBOSITY")
    if VERBOSITY:
      self.log.level = VERBOSITY
    self.root = root.resolve() if root else self.test_case.parent
    self.networks: list[Network] = []
    self.hosts: list[Host] = []
    if test_dir is not None:
      self.test_dir = test_dir.resolve()
    else:
      if self.inside_test_runner:
        self.test_dir = Path("/experiment-tmp")
      else:
        self.test_dir_h = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.test_dir_h.name)
    self.config = dict(config or {})
    self.registry = registry
    self.registry_tmp = registry_tmp
    self.container_wait = container_wait


  def __str__(self) -> str:
    return f"Experiment({self.name})"


  def __repr__(self) -> str:
    return str(self)


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Experiment):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  @cached_property
  def inside_test_runner(self) -> bool:
    return bool(os.environ.get("UNO_TEST_RUNNER", False))


  def create(self) -> None:
    self.log.info("creating {} networks and {} containers", len(self.networks), len(self.hosts))
    if self.registry.deployed:
      self.log.info("UVN {} deployement configuration:", self.registry.uvn.name)
      self.registry.uvn.log_deployment(self.registry.deployment, log_level="info")
    # Make sure no stale container exists
    # (otherwise we will fail to recreate networks)
    self.wipe_containers()
    for net in self.networks:
      self.log.debug("creating network: {}", net)
      net.create()
      self.log.activity("network created: {}", net)
    for host in self.hosts:
      self.log.debug("creating host: {}", host)
      host.create()
      self.log.activity("host created: {}", host)
    self.log.info("created {} networks and {} containers", len(self.networks), len(self.hosts))


  def restore_registry_permissions(self) -> None:
    # Return ownership of registry directory to current user
    if self.registry.root.exists():
      exec_command([
        "docker", "run", "--rm",
          "-v", f"{self.registry.root}:/registry",
          "-v", f"{self.test_dir}:/test-dir",
          self.config["image"],
          "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/registry", "/test-dir"
      ])


  def tear_down(self, assert_stopped: bool=False) -> None:
    self.log.info("tearing down {} networks and {} containers", len(self.networks), len(self.hosts))
    for host in self.hosts:
      self.log.debug("tearing down host: {}", host)
      host.delete(ignore_errors=assert_stopped)
      self.log.activity("host deleted: {}", host)
    self.hosts.clear()
    for net in self.networks:
      self.log.debug("tearing down net: {}", net)
      net.delete(ignore_errors=assert_stopped)
      self.log.activity("network deleted: {}", net)
    self.networks.clear()
    self.restore_registry_permissions()
    self.log.info("removed all networks and containers", len(self.networks), len(self.hosts))


  @property
  def nameserver_entries(self) -> Generator[tuple[str, ipaddress.IPv4Address], None, None]:
    for net in self.networks:
      for host in net:
        for hostname, addr in host.nameserver_entries:
          yield (hostname, addr)


  @property
  def active_containers(self) -> list[str]:
    result = exec_command([
      "docker ps -a --format {{.Names}} | grep " f"'^{self.name}-' || true"
    ], shell=True, capture_output=True).stdout
    if not result:
      return []
    return list(filter(len, result.decode().split("\n")))


  def wipe_containers(self) -> None:
    existing_containers = self.active_containers
    if not existing_containers:
      return
    self.log.warning("wiping stale {} containers: {}", len(existing_containers), existing_containers)
    exec_command(["docker", "rm", "-f", *existing_containers])


  def define_network(self,
      subnet: ipaddress.IPv4Network,
      name: str|None=None,
      masquerade: bool=False) -> "Network":
    if name is None:
      net_i = len(self.networks)
      name = f"{self.name}-net{net_i}"
    net = Network(
      experiment=self,
      name=name,
      subnet=subnet,
      masquerade=masquerade)
    self.networks.append(net)
    return net


  def start(self) -> None:
    self.log.info("starting {} hosts", len(self.hosts))

    # first start routers, to prevent spurious communication before the NATs are properly initialized.
    # This is mostly a problem for wireguard, because all containers share the same kernel and thus
    # the same "wireguard routing table". If a wireguard connection gets through a router before the
    # nat is properly initialized, the kernel table will associate a public key with the wrong peer.
    for net in self.networks:
      for router in (h for h in net if h.role == HostRole.ROUTER):
        router.start()

    # Now start all other hosts
    for net in self.networks:
      for host in (h for h in net if h.role != HostRole.ROUTER):
        host.start()
    
    self.log.info("started {} hosts", len(self.hosts))


  def stop(self) -> None:
    self.log.info("stopping {} hosts", len(self.hosts))
    for net in self.networks:
      for host in net:
        host.stop()
    self.log.info("stopped {} hosts", len(self.hosts))


  @classmethod
  def build_uno_image(cls, tag: str="mentalsmash/uno:dev-local", use_cache: bool=False, dev: bool=True, extras: bool=True, local: bool=True) -> None:
    if tag in cls.BuiltImages:
      Logger.debug("image already built: {}", tag)
      return
    Logger.info("building uno docker image: {}", tag)
    exec_command([
      "docker", "build",
        *(["--no-cache"] if not use_cache else []),
        "-f", f"{cls.uno_dir}/docker/Dockerfile",
        "-t", tag,
        *(["--build-arg", "DEV=y"] if dev else []),
        *(["--build-arg", "EXTRAS=y"] if extras else []),
        *(["--build-arg", "LOCAL=y"] if local else []),
        cls.uno_dir,
    ], debug=True)
    cls.BuiltImages.add(tag)
    Logger.warning("uno docker image updated: {}", tag)
  
