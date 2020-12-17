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
import libuno.log
logger = libuno.log.logger("uvn.cmd")

def create(uvn, cmd_cls, mapping=None):
    if mapping:
        return cmd_cls(uvn, name=mapping[0], alias=mapping[1])
    else:
        return cmd_cls(uvn)

def create_all(uvn, commands, mappings={}):
    def _create(cmd_cls):
        mapping = mappings.get(cmd_cls)
        return create(uvn, cmd_cls, mapping)
    return list(map(_create, commands))

class UvnCommand:
    
    def __init__(self, uvn, name,
            alias=[],
            help_short="",
            help_long="",
            subcommands=[],
            daemon_friendly=False):
        self.uvn = uvn
        self.subcommands = []
        self.name = name
        self.alias = list(alias)
        self.help_short = help_short
        self.help_long = help_long
        self.daemon_friendly = daemon_friendly

        # Create subcommands
        for subcmd_cls in subcommands:
            subcmd = subcmd_cls(parent=self)
            self.subcommands.append(subcmd)

    def _define_common_args(self, parser, with_basedir=True):
        common_opts = parser.add_argument_group("Common Arguments")

        if with_basedir:
            common_opts.add_argument(
                "-C","--directory",
                help="Directory containing a UVN configuration (defaults to current directory).",
                default=".")
        
        g_verb = common_opts.add_mutually_exclusive_group()

        g_verb.add_argument("-q", "--quiet", action="store_true",
                            help="Suppress all output to stdout")
        g_verb.add_argument("-v", "--verbose", action="count",
                            help="Increase output verbosity. Repeat for increased verbosity.")

        common_opts.add_argument("-k","--keep",
            action="store_true",
            default=False,
            help="Do not delete generated files.")

    def define_args(self, parser):
        self._define_common_args(parser)
    
    def exec(self):
        logger.warning("command not implemented: {}", self.name)


class UvnSubcommand(UvnCommand):
    
    def __init__(self, parent, name, alias=[], help_short="", help_long=""):
        self.parent = parent
        UvnCommand.__init__(self,
            uvn=parent.uvn,
            name=name,
            alias=alias,
            help_short=help_short,
            help_long=help_long)

    def exec(self):
        logger.warning("command not implemented: {} {}", self.parent.name, self.name)
