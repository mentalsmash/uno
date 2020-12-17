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
from libuno.uvn.cmd import UvnCommand, UvnSubcommand

import libuno.install
import libuno.log

logger = libuno.log.logger("uvn.cmd.ns")

class UvnCommandNameserver(UvnCommand):
    
    def __init__(self, uvn, name="nameserver", alias=["ns"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Manage UVN name server",
            help_long="""Manage UVN name server.""",
            subcommands=[
                UvnSubcommandNameserverAssert,
                UvnSubcommandNameserverRemove])


class UvnSubcommandNameserverAssert(UvnSubcommand):
    
    def __init__(self, parent, name="assert", alias=["a"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Add or update an entry in the name server.",
            help_long="""Add or update an entry in the name server.""")

    def define_args(self, parser):
        parser.add_argument("cell",
            help="Cell to which the host belongs")
        parser.add_argument("hostname",
            help="Hostname for the new entry")
        parser.add_argument("address",
            help="IP address for the new entry")
        parser.add_argument("-t","--tag",
            action='append',
            help="Specify additional tags for the record.")
        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        tags = []
        if self.uvn.args.tag is not None:
            tags.extend(self.uvn.args.tag)
        registry.nameserver.assert_record(
            hostname=self.uvn.args.hostname,
            server=self.uvn.args.cell,
            address=self.uvn.args.address,
            tags=tags)
        self.uvn.registry_save(registry)


class UvnSubcommandNameserverRemove(UvnSubcommand):
    
    def __init__(self, parent, name="remove", alias=["r"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Remove an existing entry from the name server.",
            help_long="""Remove an existing entry from the name server.""")

    def define_args(self, parser):
        parser.add_argument("hostname",
            help="Hostname for the entry to remove")
        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        registry.nameserver.remove_record(self.uvn.args.hostname)
        self.uvn.registry_save(registry)
