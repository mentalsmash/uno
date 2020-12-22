###############################################################################
# (C) Copyright 2020 Andrea Sorbini
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
class UvnException(Exception):
    
    def __init__(self, msg):
        self.msg = msg

class UnknownCellException(UvnException):

    def __init__(self, name):
        self.name = name
        UvnException.__init__(self, f"unknown cell: {name}")

class UnknownParticleException(UvnException):
    
    def __init__(self, name):
        self.name = name
        UvnException.__init__(self, f"unknown particle: {name}")
