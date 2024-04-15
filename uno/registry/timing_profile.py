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
from enum import Enum


class TimingProfile(Enum):
  DEFAULT = 0
  FAST = 1

  @staticmethod
  def parse(val: str) -> "TimingProfile":
    return TimingProfile[val.upper().replace("-", "_")]

  @property
  def participant_liveliness_lease_duration(self) -> int:
    if self == TimingProfile.FAST:
      return 5
    else:
      return 60

  @property
  def participant_liveliness_assert_period(self) -> int:
    if self == TimingProfile.FAST:
      return 2
    else:
      return 20

  @property
  def participant_liveliness_detection_period(self) -> int:
    if self == TimingProfile.FAST:
      return 6
    else:
      return 30

  @property
  def initial_participant_announcements(self) -> int:
    if self == TimingProfile.FAST:
      return 60
    else:
      return 60

  @property
  def initial_participant_announcement_period(self) -> tuple[int, int]:
    if self == TimingProfile.FAST:
      return (1, 5)
    else:
      return (3, 15)

  @property
  def ospf_dead_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 5
    else:
      return 60

  @property
  def ospf_hello_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 1
    else:
      return 15

  @property
  def ospf_retransmit_interval(self) -> int:
    if self == TimingProfile.FAST:
      return 2
    else:
      return 5

  @property
  def tester_max_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 30
    else:
      return 3600  # 1h

  @property
  def max_service_trigger_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 30
    else:
      return 3600  # 1h

  @property
  def status_min_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 10
    else:
      return 30
