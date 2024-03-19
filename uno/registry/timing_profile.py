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
      return 3600 # 1h


  @property
  def status_min_delay(self) -> int:
    if self == TimingProfile.FAST:
      return 10
    else:
      return 30

