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
from libuno.cfg import UvnDefaults

import libuno.log

logger = libuno.log.logger("uvn.cmd.graph")

class UvnCommandGraph(UvnCommand):
    
    def __init__(self, uvn, name="graph", alias=["G"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Generate a graph of the UVN layout",
            help_long="""Generate a graph of the UVN layout.""")

    def define_args(self, parser):
        graph_opts = parser.add_argument_group("Graph Options")

        graph_opts.add_argument("-D","--deployment",
            default=UvnDefaults["registry"]["deployment_default"],
            help="Id of the deployment configuration to display.")

        graph_opts.add_argument("-d","--dir",
            default="",
            help="Directory where to generate files")

        graph_opts.add_argument("-o","--output",
            default="",
            help="Save output to the specified file.")
        
        graph_opts.add_argument("-f","--format",
            choices=["png", "dot"],
            default="png",
            help="Format of the generated graph.")

        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        self.uvn.registry_graph(registry,
            output=self.uvn.args.output,
            outdir=self.uvn.args.dir,
            deployment_id=self.uvn.args.deployment)
