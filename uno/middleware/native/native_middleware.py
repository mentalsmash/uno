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
from uno.middleware import Middleware

from .native_condition import NativeCondition
from .native_participant import NativeParticipant


class NativeMiddleware(Middleware):
  CONDITION = NativeCondition
  PARTICIPANT = NativeParticipant

  @classmethod
  def supports_agent(cls) -> bool:
    return False
