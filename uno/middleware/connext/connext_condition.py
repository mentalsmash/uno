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
