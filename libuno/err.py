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
"""Exceptions for libuno"""

class Error(Exception):
    """Base class for exceptions in this module."""
    
    def __init__(self, msg):
        self.msg = msg
    
    def __str__(self):
        return self.msg

class InvalidConfigError(Error):
    """Exception raised when an invalid configuration paramater is detected"""

    def __init__(self, arg, val, expected):
        super().__init__(" : ".join((arg, str(val), expected)))
        self.arg = arg
        self.val = val
        self.expected = expected

class UnexpectedError(Error):
    """Generic exception raised when some unexpected error occurs"""

    def __init__(self, msg):
        super().__init__(msg)
