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
import os
from pathlib import Path
from typing import Callable
from functools import wraps
import tempfile

from uno.core.log import Logger
from uno.registry.registry import Registry

from .experiment import Experiment
from .scenario import Scenario

class IntegrationTest:
  log = Logger.sublogger("test")

  Experiments: list[Experiment] = []

  @classmethod
  def tear_down(cls, assert_stopped: bool=False) -> None:
    for experiment in cls.Experiments:
      experiment.tear_down(assert_stopped=assert_stopped)
    cls.Experiments.clear()


  @classmethod
  def define_experiment(cls,
      test_case: Path,
      name: str | None=None,
      root: Path | None=None,
      config: dict|None=None,
      registry: Registry|None=None,
      registry_tmp: tempfile.TemporaryDirectory|None=None,
      test_dir: Path | None=None) -> Experiment:
    experiment = Experiment(
      test_case=test_case,
      name=name,
      root=root,
      config=config,
      registry=registry,
      registry_tmp=registry_tmp,
      test_dir=test_dir)
    cls.Experiments.append(experiment)
    return experiment


  @classmethod
  def import_test_case(cls, test_case_file: Path) -> Scenario:
    # Load test case as a module
    # (see: https://stackoverflow.com/a/67692)
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(test_case_file.stem, str(test_case_file))
    test_case = importlib.util.module_from_spec(spec)
    sys.modules[test_case_file.stem] = test_case
    spec.loader.exec_module(test_case)
    return test_case.load_scenario()
    # return scenario.experiment
    # experiment: Experiment = test_case.config(args)
    # return experiment


# Make info the minimum default verbosity when this module is loaded
if IntegrationTest.log.level >= Logger.Level.warning:
  IntegrationTest.log.level = Logger.Level.info
