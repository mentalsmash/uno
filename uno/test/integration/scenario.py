from typing import TYPE_CHECKING
from pathlib import Path
import tempfile
from functools import cached_property
import os

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
    
    self.registry_tmp = tempfile.TemporaryDirectory()


  @property
  def default_config(self) -> dict:
    return {
      "interactive": False,
    }


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


