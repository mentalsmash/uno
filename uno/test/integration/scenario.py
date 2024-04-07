from typing import TYPE_CHECKING
from pathlib import Path
import tempfile
from functools import cached_property
import os
import ipaddress

from uno.registry.registry import Registry
from uno.middleware import Middleware
from uno.core.log import Logger
from uno.core.exec import exec_command

from .experiment import Experiment

class Scenario:
  def __init__(self, test_case: Path, config: dict | None = None) -> None:
    self.test_case = test_case
    self.config = dict(config or {})
    for k, v in self.default_config.items():
      self.config.setdefault(k, v)
    self.config.setdefault("networks", self.make_networks())
    self.registry_tmp = tempfile.TemporaryDirectory()
    # Check if we should refresh the uno docker image
    if os.environ.get("BUILD_IMAGE", False):
      Experiment.build_uno_image(self.config["image"])
    # Automatically set RTI_LICENSE_FILE if there is an rti_license.dat
    # in the root of the uno diir
    default_license = Experiment.uno_dir / "rti_license.dat"
    if default_license.exists():
      os.environ["RTI_LICENSE_FILE"] = str(default_license)



  @property
  def default_config(self) -> dict:
    return {
      "interactive": False,
      "image": "mentalsmash/uno:dev-local",
      "uvn_fully_routed_timeout": 60,
    }


  def make_networks(self) -> list[ipaddress.IPv4Network]:
    return []


  @cached_property
  def registry_root(self) -> Path:
    return Path(self.registry_tmp.name)


  @cached_property
  def registry(self) -> Registry:
    # Detect directory mounted inside containers
    experiment_uvn = Path("/experiment-uvn")
    if experiment_uvn.is_dir():
      return Registry.open(experiment_uvn, readonly=True)
    else:
      self._define_uvn()
      return Registry.open(self.registry_root, readonly=True)


  @cached_property
  def experiment(self) -> Experiment:
    from .integration import IntegrationTest
    test_dir = os.environ.get("TEST_DIR", None)
    if test_dir is not None:
      test_dir = Path(test_dir)
    experiment = IntegrationTest.define_experiment(
      test_case=self.test_case,
      config=self.config,
      registry=self.registry,
      test_dir=test_dir)
    self._define_experiment(experiment)
    return experiment


  def _define_uvn(self) -> None:
    raise NotImplementedError()


  def _define_experiment(self) -> None:
    raise NotImplementedError()


  def uno(self, *args, **exec_args):
    # define_uvn = len(args) > 2 and args[0] == "define" and args[1] == "uvn"
    verbose_flag = Logger.verbose_flag
    uno_middleware_plugin, uno_middleware_plugin_module = Middleware.load_module()
    plugin_base_dir = Middleware.plugin_base_directory(
      uno_dir=Experiment.uno_dir,
      plugin=uno_middleware_plugin,
      plugin_module=uno_middleware_plugin_module)
    rti_license = os.environ.get("RTI_LICENSE_FILE")
    if rti_license:
      rti_license = Path(rti_license).resolve()
    # The command may create files with root permissions.
    # These files will be returned to the host user when
    # Experiment.restore_registry_permissions() is called
    # during tear down.
    try:
      return exec_command([
        "docker", "run", "--rm",
          "-v", f"{self.registry_root}:/experiment-uvn",
          "-v", f"{self.registry_root}:/uvn",
          "-v", f"{Experiment.uno_dir}:/uno",
          *(["-v", f"{plugin_base_dir}:/uno-middleware"] if plugin_base_dir else []),
          "-e", f"UNO_MIDDLEWARE={uno_middleware_plugin}",
          *([
            "-v", f"{rti_license}:/rti_license.dat",
            "-e", "RTI_LICENSE_FILE=/rti_license.dat",
          ] if rti_license else []),
          "-w", "/uvn",
          self.config["image"],
          "uno", *args,
            *([verbose_flag] if verbose_flag else []),
      ], **exec_args)
    finally:
      Experiment.restore_registry_permissions(
          registry_root=self.registry_root,
          image=self.config["image"])
    # return result

