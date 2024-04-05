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
from ..registry.topic import UvnTopic
from .condition import Condition
from .handle import Handle


class ParticipantEventsListener:
  def on_remote_writers_status(self, topic: UvnTopic, online_writers: list[Handle]) -> None:
    pass


  def on_instance_offline(self, topic: UvnTopic, instance: Handle) -> None:
    pass


  def on_data(self,
      topic: UvnTopic,
      data: dict,
      instance: Handle | None = None,
      writer: Handle | None = None) -> None:
    pass


  def on_condition_active(self, condition: Condition) -> None:
    pass

