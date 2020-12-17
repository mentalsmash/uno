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

from .cmd_agent import UvnCommandAgent
from .cmd_attach import UvnCommandAttach
from .cmd_create import UvnCommandCreate
from .cmd_deploy import UvnCommandDeploy
from .cmd_drop import UvnCommandDrop
from .cmd_graph import UvnCommandGraph
from .cmd_info import UvnCommandInfo
from .cmd_install import UvnCommandInstall
from .cmd_nameserver import UvnCommandNameserver
from .cmd_runner import UvnCommandRunner
from .cmd_view import UvnCommandView

from .cmd import UvnCommand, create_all as cmd_create_all

commands = [
    UvnCommandAgent,
    UvnCommandAttach,
    UvnCommandCreate,
    UvnCommandDeploy,
    UvnCommandDrop,
    UvnCommandGraph,
    UvnCommandInfo,
    UvnCommandInstall,
    UvnCommandNameserver,
    UvnCommandRunner,
    UvnCommandView
]

def create_all(uvn, mappings={}):
    return cmd_create_all(uvn, commands, mappings)
