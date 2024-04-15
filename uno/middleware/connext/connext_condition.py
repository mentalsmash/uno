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
import rti.connextdds as dds

from uno.middleware import Condition


class ConnextCondition(Condition):
  def __init__(self, condition: dds.Condition | None = None) -> None:
    self._condition = condition or dds.GuardCondition()

  @property
  def trigger_value(self) -> bool:
    return self._condition.trigger_value

  @trigger_value.setter
  def trigger_value(self, val: bool) -> None:
    self._condition.trigger_value = val
