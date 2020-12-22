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

import libuno.log

logger = libuno.log.logger("uvn.cmd.attach")

class UvnCommandAttach(UvnCommand):
    
    def __init__(self, uvn, name="attach", alias=["a"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Attach a cell or particle to the UVN",
            help_long="""Attach a cell or particle to the UVN.""",
            subcommands=[
                UvnSubcommandAttachCell,
                UvnSubcommandAttachParticle])

    def define_args(self, parser):
        self._define_common_args(parser)


class UvnSubcommandAttachCell(UvnSubcommand):
    
    def __init__(self, parent, name="cell", alias=["c"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Attach a cell to the UVN",
            help_long="""Generate a new cell configuration and attach it to
                      an existing UVN.""")

    def define_args(self, parser):
        self.parent._define_common_args(parser)

        tgt_opts = parser.add_argument_group(
                        "Cell Selection",
                        "One of these arguments must be specified")

        g_cmd = tgt_opts.add_mutually_exclusive_group(required=True)

        g_cmd.add_argument("-n","--name",
            help="Name of the cell")
        
        g_cmd.add_argument("-f","--file",
            help="A file containing the cell's configuration")
        
        cfg_opts = parser.add_argument_group("Cell Configuration")

        cfg_opts.add_argument("--address",
            help="Public address of the cell")
        
        cfg_opts.add_argument("--admin",
            help="Administrator of the cell")

        cfg_opts.add_argument("--admin-name",
            help="Full name of the cell's administrator")
        
        cfg_opts.add_argument("--location",
            help="Physical location of the cell")
        
        cfg_opts.add_argument("--peer-ports",
            help="Port numbers used accept connections from other cells")
        
        extra_opts = parser.add_argument_group("Additional Options")
        
        extra_opts.add_argument("-d","--drop-stale",
            action="store_true",
            help="Drop existing deployment configurations.")

    def exec(self):
        registry = self.uvn.registry_load()
        cell_file = self.uvn.args.file
        cell_name = self.uvn.args.name

        if not cell_name:
            if not cell_file:
                self.uvn.error("no cell name nor file specified")
            logger.activity("adding cells from file {} to UVN {}",
                    cell_file, registry.address)
            cells = libuno.yml.yml_obj(list, cell_file, from_file=True)
            for c in cells:
                self.uvn.registry_add(registry, **c)
        else:
            cell_ports = self.uvn.args.peer_ports
            if (cell_ports):
                cell_ports = libuno.yml.yml_obj(list, cell_ports)

            self.uvn.registry_add(
                registry,
                name=cell_name,
                address=self.uvn.args.address,
                admin=self.uvn.args.admin,
                admin_name=self.uvn.args.admin_name,
                location=self.uvn.args.location,
                peer_ports=self.uvn.args.peer_ports)

        self.uvn.registry_save(registry)


class UvnSubcommandAttachParticle(UvnSubcommand):
    
    def __init__(self, parent, name="particle", alias=["p"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Attach a particle to the UVN",
            help_long="""Generate a new particle configuration and attach it to
                      an existing UVN.""")

    def define_args(self, parser):
        self.parent._define_common_args(parser)
        
        cfg_opts = parser.add_argument_group("Particle Configuration")

        cfg_opts.add_argument("name",
            help="Name of the particle")

        cfg_opts.add_argument("--contact",
            default=None,
            help="A contact e-mail for the particle")

    def exec(self):
        registry = self.uvn.registry_load()
        particle = registry.register_particle(
            name=self.uvn.args.name,
            contact=self.uvn.args.contact)
        logger.activity("added particle {} ({}) to UVN {}",
            particle.name, particle.contact, registry.address)
        self.uvn.registry_save(registry)
