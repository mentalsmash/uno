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
from libuno.uvn.cmd import UvnCommand

import libuno.log

logger = libuno.log.logger("uvn.cmd.info")

class UvnCommandInfo(UvnCommand):
    
    def __init__(self, uvn, name="info", alias=["i"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Display information about a UVN",
            help_long="""Display information about a UVN.""")

    def define_args(self, parser):
        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        self.uvn.registry_info(registry)
