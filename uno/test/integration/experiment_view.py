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
from .experiment import Experiment

from uno.core.log import Logger

_Registered = {}


class ExperimentView:
  Id: str = None
  Live: bool = False

  def __init__(self, experiment: Experiment) -> None:
    self.experiment = experiment
    self.log = Logger.sublogger(self.experiment.name)

  def display(self) -> None:
    raise NotImplementedError()

  def __init_subclass__(cls) -> None:
    if cls.Id is not None:
      _Registered[cls.Id.lower()] = cls

  @classmethod
  def load(cls, id: str, experiment: Experiment) -> "ExperimentView":
    return _Registered[id.lower()](experiment)
