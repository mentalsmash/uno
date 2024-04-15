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
from ..registry.topic import UvnTopic
from .condition import Condition
from .handle import Handle


class ParticipantEventsListener:
  def on_remote_writers_status(self, topic: UvnTopic, online_writers: list[Handle]) -> None:
    pass

  def on_instance_offline(self, topic: UvnTopic, instance: Handle) -> None:
    pass

  def on_data(
    self, topic: UvnTopic, data: dict, instance: Handle | None = None, writer: Handle | None = None
  ) -> None:
    pass

  def on_condition_active(self, condition: Condition) -> None:
    pass
