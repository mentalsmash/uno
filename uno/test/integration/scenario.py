from typing import TYPE_CHECKING
from pathlib import Path
import tempfile
from functools import cached_property
import os
import ipaddress

from uno.registry.registry import Registry
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
    verbose_flag = Logger.verbose_flag
    return exec_command([
      "uno", *args,
        "-r", self.registry_root,
        *([verbose_flag] if verbose_flag else []),
    ], **exec_args)


