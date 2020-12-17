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

logger = libuno.log.logger("uvn.cmd.drop")

class UvnCommandDrop(UvnCommand):
    
    def __init__(self, uvn, name="drop", alias=["D"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Drop elements from the UVN",
            help_long="""Delete existing deployments, cells, or particles from the UVN.""")

    def define_args(self, parser):
        tgt_opts = parser.add_argument_group("Drop Target Selection")

        g_tgt = tgt_opts.add_mutually_exclusive_group(required=True)

        g_tgt.add_argument("--deployment", action="store_true",
                            help="Drop deployments")
        g_tgt.add_argument("--cell", action="store_true",
                            help="Drop cells")
        g_tgt.add_argument("--particle", action="store_true",
                            help="Drop particles")

        g_tgt_select = tgt_opts.add_mutually_exclusive_group(required=True)

        g_tgt_select.add_argument("--all",
            action="store_true",
            help="Drop all existing elements.")

        g_tgt_select.add_argument("-t","--target",
            help="Drop only the specified element.")
        
        drop_opts = parser.add_argument_group("Drop Options")

        drop_opts.add_argument("-l","--keep-last",
            action="store_true",
            default=False,
            help="Keep the last element added to the set.")
        
        drop_opts.add_argument("-i","--invalid",
            action="store_true",
            default=False,
            help="Remove elements that have become invalid (e.g. stale deployments).")
        
        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        self.uvn.registry_drop(registry)
        self.uvn.registry_save(registry)
