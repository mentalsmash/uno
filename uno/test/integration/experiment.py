###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from typing import Generator
from pathlib import Path
import ipaddress
import tempfile
import os
from functools import cached_property
import contextlib
import subprocess
from typing import Protocol
import pprint
import yaml

from uno.core.exec import exec_command
from uno.core.log import Logger
from uno.core.time import Timer
from uno.registry.registry import Registry
from uno.middleware import Middleware

from .network import Network
from .host import Host
from .host_role import HostRole

import uno

_UnoDir = Path(uno.__file__).resolve().parent.parent

# Make "info" the minimum default verbosity when this module is loaded
# if Logger.Level.warning >= Logger.level:
#   Logger.level = Logger.Level.info


class TestFunction(Protocol):
  def __call__(self, experiment: "Experiment", *args, **kwargs) -> None: ...


class TestFixture(Protocol):
  def __call__(
    self, experiment: "Experiment", *args, **kwargs
  ) -> Generator[object, None, None]: ...


class ExperimentLoader(Protocol):
  def __call__(self, **experiment_args) -> "Experiment": ...


_RtiLicenseFile = os.environ.get("RTI_LICENSE_FILE")
if _RtiLicenseFile:
  _RtiLicenseFile = Path(_RtiLicenseFile).resolve()

_ExternalTestDir = os.environ.get("TEST_DIR")
if _ExternalTestDir:
  _ExternalTestDir = Path(_ExternalTestDir).resolve()

# Don't resolve this path, because it might be "runner",
# passed by the Makefile
_RunnerScript = Path(os.environ.get("TEST_RUNNER", "/uno/uno/test/integration/runner.py"))


class Experiment:
  Dev = bool(os.environ.get("DEV", False))
  InsideTestRunner = bool(os.environ.get("UNO_TEST_RUNNER", False))
  TestImage = os.environ.get("TEST_IMAGE", "mentalsmash/uno-test-runner:latest")
  RunnerScript = _RunnerScript
  ExternalTestDir = _ExternalTestDir
  RtiLicenseFile = _RtiLicenseFile
  BuiltImages = set()
  UnoDir = _UnoDir
  # Load the selected uno middleware plugin
  UnoMiddlewareEnv = os.environ.get("UNO_MIDDLEWARE")
  RunnerTestDir = Path("/experiment-tmp")
  RunnerRoot = Path("/experiment")
  RunnerRegistryRoot = Path("/uvn")
  RunnerUnoDir = Path("/uno")

  @classmethod
  def as_fixture(
    cls, loader: ExperimentLoader, **experiment_args
  ) -> Generator["Experiment", None, None]:
    e = loader(**experiment_args)
    if not e:
      yield None
    else:
      with e.begin():
        yield e

  @classmethod
  def define(
    cls,
    test_case: Path,
    name: str | None = None,
    root: Path | None = None,
    config: dict | None = None,
    test_dir: Path | None = None,
    requires_agents: bool = False,
  ) -> "Experiment | None":
    # Make sure the test case file is an absolute path
    test_case = test_case.resolve()
    # Derive the name from the test case file if unspecified
    name = name or test_case.stem.replace("_", "-")
    # Derive root directory from test case file if unspecified
    root = root.resolve() if root else test_case.parent
    # Load test configuration
    config = cls.load_config(config)
    # Check if the user specified a non-temporary test directory
    # Otherwise the experiment will allocate a temporary directory
    test_dir = cls.ExternalTestDir or test_dir
    test_dir_tmp = None
    if test_dir is not None:
      test_dir = Path(test_dir) / name
      Logger.warning("using external test directory: {}", test_dir)
      # Make sure the external directory is empty
      if test_dir.exists():
        contents = list(test_dir.glob("*"))
        if contents:
          Logger.warning("wiping contents of external test directory: {}", test_dir)
          for file in sorted(map(str, contents)):
            Logger.warning("- {}", file)
          exec_command(["rm", "-rf", *(["-v"] if Logger.DEBUG else []), *contents])
      else:
        test_dir.mkdir(parents=True)
    elif cls.InsideTestRunner:
      test_dir = cls.RunnerTestDir
    else:
      test_dir_tmp = tempfile.TemporaryDirectory()
      test_dir = Path(test_dir_tmp.name)
    # Check that we have the expected middleware
    expected_plugin = os.environ.get("EXPECTED_MIDDLEWARE")
    if expected_plugin is not None:
      if (
        not expected_plugin and Middleware.selected().plugin
      ) or expected_plugin != Middleware.selected().plugin:
        raise RuntimeError(
          f"unexpected middleware plugin: found={Middleware.selected().plugin}, expected={expected_plugin}"
        )
    if not Middleware.selected().supports_agent(test_dir) and requires_agents:
      Logger.warning(
        "test case disabled because middleware {} doesn't support agents: {}",
        Middleware.selected().__qualname__,
        name,
      )
      return
    experiment = cls(
      test_case=test_case,
      name=name,
      root=root,
      config=config,
      test_dir=test_dir,
    )
    experiment.__test_dir_tmp = test_dir_tmp
    if not experiment.InsideTestRunner:
      experiment.log_configuration()
    return experiment

  @classmethod
  def import_test_case(cls, test_case_file: Path) -> "Experiment":
    # Load test case as a module
    # (see: https://stackoverflow.com/a/67692)
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(test_case_file.stem, str(test_case_file))
    test_case = importlib.util.module_from_spec(spec)
    sys.modules[test_case_file.stem] = test_case
    spec.loader.exec_module(test_case)
    return test_case.load_experiment()

  @classmethod
  def load_config(cls, user_config: dict | None = None) -> dict:
    config = dict(user_config or {})
    for k, v in cls.default_config().items():
      config.setdefault(k, v)
    cls.default_derived_config(config)
    # config.setdefault("networks", cls.default_networks(config))
    return config

  @classmethod
  def default_config(cls) -> dict:
    return {
      "interactive": False,
      "uvn_fully_routed_timeout": 60,
      "container_start_timeout": 60,
      "container_stop_timeout": 60,
      "test_timeout": 60,
    }

  @classmethod
  def default_derived_config(cls, config: dict) -> None:
    pass

  def __init__(
    self,
    test_case: Path,
    name: str,
    root: Path,
    config: dict,
    test_dir: Path,
  ) -> None:
    self.test_case = test_case
    self.name = name
    self.root = root
    self.test_dir = test_dir
    self.config = config
    self.networks: list[Network] = []
    self.private_networks: list[Network] = []
    self.public_networks: list[Network] = []
    self.transit_networks: list[Network] = []
    self.hosts: list[Host] = []
    self.log = Logger.sublogger(name)
    self.define_networks_and_hosts()

  @property
  def host_hosts(self) -> list[Host]:
    return sorted(
      (h for h in self.hosts if h.role == HostRole.HOST), key=lambda h: h.container_name
    )

  @property
  def router_hosts(self) -> list[Host]:
    return sorted(
      (h for h in self.hosts if h.role == HostRole.ROUTER), key=lambda h: h.container_name
    )

  @property
  def cell_hosts(self) -> list[Host]:
    return sorted(
      (h for h in self.hosts if h.role == HostRole.CELL), key=lambda h: h.container_name
    )

  @property
  def particle_hosts(self) -> list[Host]:
    return sorted(
      (h for h in self.hosts if h.role == HostRole.PARTICLE), key=lambda h: h.container_name
    )

  @property
  def registry_host(self) -> Host:
    return next((h for h in self.hosts if h.role == HostRole.REGISTRY), None)

  def log_configuration(self) -> None:
    self.log.info("experiment configuration: {}", pprint.pformat(self.config))
    self.log.info(
      "{} experiment private networks: {}",
      len(self.private_networks),
      pprint.pformat(self.private_networks),
    )
    self.log.info(
      "{} experiment public networks: {}",
      len(self.public_networks),
      pprint.pformat(self.public_networks),
    )
    self.log.info(
      "{} experiment transit networks: {}",
      len(self.transit_networks),
      pprint.pformat(self.transit_networks),
    )
    self.log.info("{} experiment hosts: {}", len(self.hosts), pprint.pformat(self.hosts))
    for net in self.networks:
      net.log_configuration()
    for host in self.hosts:
      host.log_configuration()

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
  def registry_root(self) -> Path:
    return self.test_dir / "uvn"

  @cached_property
  def registry(self) -> Registry:
    if not self.InsideTestRunner and not Registry.is_uno_directory(self.registry_root):
      self.log.info("initializing UVN")
      self.define_uvn()
      self.log.info("initialized UVN")
    self.log.info("opening UVN registry from {}", self.registry_root)
    registry = Registry.open(self.registry_root, readonly=True)
    self.log.info("opened UVN registry {}: {}", registry.root, registry)
    return registry

  @cached_property
  def uvn_networks(self) -> set[Network]:
    subnets = {n for c in self.registry.uvn.cells.values() for n in c.allowed_lans}
    return {net for net in self.networks if net.subnet in subnets}

  def define_networks_and_hosts(self) -> None:
    pass

  def define_uvn(self) -> None:
    pass

  def define_uvn_from_config(self, name: str, uvn_spec: dict) -> None:
    uvn_spec_f = self.test_dir / "uvn_spec.yaml"
    uvn_spec_f.write_text(yaml.safe_dump(uvn_spec))
    self.uno(
      "define",
      "uvn",
      name,
      "-s",
      self.RunnerTestDir / uvn_spec_f.relative_to(self.test_dir),
    )

  @contextlib.contextmanager
  def begin(self) -> "Generator[Experiment, None, None]":
    try:
      self.create()
      self.start()
      yield self
    finally:
      KEEP_DOCKER = os.environ.get("KEEP_DOCKER", False)
      try:
        self.stop()
      except Exception as e:
        self.log.error("failed to stop containers")
        self.log.exception(e)
      if not KEEP_DOCKER:
        self.tear_down(assert_stopped=True)
      self.log.info("done")

  def create(self) -> None:
    self.log.info("creating {} networks and {} containers", len(self.networks), len(self.hosts))
    if self.registry.deployed:
      self.log.info("UVN {} deployement configuration:", self.registry.uvn.name)
      self.registry.uvn.log_deployment(self.registry.deployment, log_level="info")
    # Make sure no stale container exists
    # (otherwise we will fail to recreate networks)
    self.wipe_containers()
    for net in self.networks:
      self.log.info("creating network: {}", net)
      net.create()
      self.log.info("network created: {}", net)
    for host in self.hosts:
      self.log.info("creating host: {}", host)
      host.create()
      self.log.info("host created: {}", host)
    self.log.info("created {} networks and {} containers", len(self.networks), len(self.hosts))

  def fix_root_permissions(self) -> None:
    dirs = {self.root: self.RunnerRoot, self.test_dir: self.RunnerTestDir}
    exec_command(
      [
        "docker",
        "run",
        "--rm",
        *(tkn for hvol, vol in dirs.items() for tkn in ("-v", f"{hvol}:{vol}")),
        self.TestImage,
        "fix-file-ownership",
        f"{os.getuid()}:{os.getgid()}",
        *dirs.values(),
      ]
    )

  def uno(self, *args, **exec_args):
    verbose_flag = Logger.verbose_flag
    try:
      return exec_command(
        [
          "docker",
          "run",
          "--rm",
          *(["-ti"] if self.config["interactive"] else []),
          "--init",
          "-v",
          f"{self.root}:{self.RunnerRoot}",
          "-v",
          f"{self.test_dir}:{self.RunnerTestDir}",
          "-v",
          f"{self.registry_root}:{self.RunnerRegistryRoot}",
          *(
            [
              "-v",
              f"{self.UnoDir}:{self.RunnerUnoDir}",
            ]
            if self.Dev
            else []
          ),
          *(
            [
              "-e",
              f"UNO_MIDDLEWARE={self.UnoMiddlewareEnv}",
            ]
            if self.UnoMiddlewareEnv
            else []
          ),
          *(
            [
              "-e",
              f"DEBUG={self.log.DEBUG}",
            ]
            if self.log.DEBUG
            else []
          ),
          *(
            [
              "-v",
              f"{self.RtiLicenseFile}:/rti_license.dat",
            ]
            if self.RtiLicenseFile
            else ["-e", "RTI_LICENSE_FILE="]
          ),
          "-e",
          f"VERBOSITY={self.log.level.name}",
          self.TestImage,
          "uno",
          *args,
          *([verbose_flag] if verbose_flag else []),
        ],
        debug=True,
        **exec_args,
      )
    finally:
      self.fix_root_permissions()

  def tear_down(self, assert_stopped: bool = False) -> None:
    self.log.info("tearing down {} networks and {} containers", len(self.networks), len(self.hosts))
    for host in self.hosts:
      self.log.info("tearing down host: {}", host)
      host.delete(ignore_errors=assert_stopped)
      self.log.info("host deleted: {}", host)
    self.hosts.clear()
    for net in self.networks:
      self.log.info("tearing down net: {}", net)
      net.delete(ignore_errors=assert_stopped)
      self.log.info("network deleted: {}", net)
    self.networks.clear()
    self.fix_root_permissions()
    self.log.info("removed all networks and containers", len(self.networks), len(self.hosts))

  @property
  def nameserver_entries(self) -> Generator[tuple[str, ipaddress.IPv4Address], None, None]:
    for net in self.networks:
      for host in net:
        for hostname, addr in host.nameserver_entries:
          yield (hostname, addr)

  @property
  def active_containers(self) -> list[str]:
    result = exec_command(
      ["docker ps -a --format {{.Names}} | grep " f"'^{self.name}-' || true"],
      shell=True,
      capture_output=True,
    ).stdout
    if not result:
      return []
    return list(filter(len, result.decode().split("\n")))

  def wipe_containers(self) -> None:
    existing_containers = self.active_containers
    if not existing_containers:
      return
    self.log.warning(
      "wiping stale {} containers: {}", len(existing_containers), existing_containers
    )
    exec_command(["docker", "rm", "-f", *existing_containers])

  def define_network(
    self,
    subnet: ipaddress.IPv4Network,
    name: str | None = None,
    private_lan: bool = False,
    transit_wan: bool = False,
    masquerade_docker: bool = False,
  ) -> "Network":
    if private_lan:
      net_set = self.private_networks
      name_prefix = "prilan"
    elif transit_wan:
      net_set = self.transit_networks
      name_prefix = "internet"
    else:
      net_set = self.public_networks
      name_prefix = "publan"
    net_i = len(net_set)
    name = f"{name_prefix}{net_i+1}"
    net = Network(
      experiment=self,
      name=name,
      subnet=subnet,
      i=net_i,
      private_lan=private_lan,
      transit_wan=transit_wan,
      masquerade_docker=masquerade_docker,
    )
    self.networks.append(net)
    net_set.append(net)
    return net

  def start(self) -> None:
    self.log.info("starting {} hosts", len(self.hosts))

    # first start routers, to prevent spurious communication before the NATs are properly initialized.
    # This is mostly a problem for wireguard, because all containers share the same kernel and thus
    # the same "wireguard routing table". If a wireguard connection gets through a router before the
    # nat is properly initialized, the kernel table will associate a public key with the wrong peer.
    startups = []
    routers = [r for net in self.networks for r in (h for h in net if h.role == HostRole.ROUTER)]
    for router in routers:
      startups.append(router.start())
    for router in routers:
      router.wait_ready()
    startups.clear()
    other_hosts = [
      h for net in self.networks for h in (h for h in net if h.role != HostRole.ROUTER)
    ]
    # Now start all other hosts
    for host in other_hosts:
      startups.append(host.start())
    for host in other_hosts:
      host.wait_ready()

    self.log.info("started {} hosts", len(self.hosts))

  def stop(self) -> None:
    self.log.info("stopping {} hosts", len(self.hosts))
    stop_processes = []
    for h in (h for n in self.networks for h in n):
      stop_processes.append((h, h.stop()))
    for h, stop_process in stop_processes:
      h.wait_stop(stop_process)
    self.log.info("stopped {} hosts", len(self.hosts))

  def other_hosts(self, host: Host, hosts: list[Host] | None = None) -> list[Host]:
    if hosts is None:
      hosts = self.hosts
    return sorted(
      (h for h in hosts if h.role == HostRole.HOST and h != host), key=lambda h: h.container_name
    )

  @property
  def agent_processes(self) -> Generator[dict[Host, subprocess.Popen], None, None]:
    with contextlib.ExitStack() as stack:
      agents = {}
      for host in self.cell_hosts:
        agents[host] = stack.enter_context(host.uno_agent())
      yield agents

  def wait_for_fully_routed_networks(self) -> None:
    def _check_all_ready() -> bool:
      for cell in self.cell_hosts:
        if not cell.local_router_ready:
          return False
      return True

    timer = Timer(
      self.config["uvn_fully_routed_timeout"],
      0.5,
      _check_all_ready,
      self.log,
      "waiting for UVN to become consistent",
      "UVN not consistent yet",
      "UVN fully routed",
      "UVN failed to reach consistency",
    )
    timer.wait()

  def wait_for_fully_routed_agents(self, agents: dict[Host, subprocess.Popen]) -> None:
    def _check_all_consistent() -> bool:
      for agent in agents:
        if not agent.cell_fully_routed:
          return False
      return True

    timer = Timer(
      self.config["uvn_fully_routed_timeout"],
      0.5,
      _check_all_consistent,
      self.log,
      "waiting for UVN to become consistent",
      "UVN not consistent yet",
      "UVN fully routed",
      "UVN failed to reach consistency",
    )
    timer.wait()
