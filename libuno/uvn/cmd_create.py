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

logger = libuno.log.logger("uvn.cmd.create")

class UvnCommandCreate(UvnCommand):
    
    def __init__(self, uvn, name="create", alias=["c"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Initialize a new UVN",
            help_long="""Initialize a new UVN root directory.""")

    def define_args(self, parser):
        uvn_opts = parser.add_argument_group("UVN Selection")

        g_cmd = uvn_opts.add_mutually_exclusive_group(required=False)

        g_cmd.add_argument("-A", "--address",
            help="Public address (and default domain) of the new UVN")
        
        g_cmd.add_argument("-f", "--file",
            help="A file containing the UVN's configuration")

        cfg_opts = parser.add_argument_group("UVN Configuration")
        
        cfg_opts.add_argument("-a", "--admin",
            help="Administrator of the UVN")
        
        cfg_opts.add_argument("-an", "--admin-name",
            help="Full name of the UVN's administrator")
        
        cfg_opts.add_argument("-c", "--cells",
            help="Initialize cells from configuration file")
        
        cfg_opts.add_argument("-p", "--particles",
            help="Initialize particles from configuration file")
        
        cfg_opts.add_argument("-n", "--nameserver",
            help="Initialize nameserver entries from configuration file")
        
        cfg_opts.add_argument("-d", "--deploy",
            action="store_true",
            default=False,
            help="Generate a new deployment")
    
        cfg_opts.add_argument("-ds", "--deployment-strategy",
            help="Deployment strategy to use")
        
        extra_opts = parser.add_argument_group("Additional Option")

        extra_opts.add_argument("-P","--print",
            action="store_true",
            default=False,
            help="Print information about the generated UVN")
        
        parser.add_argument("directory",
            help="Directory where to generate the new UVN")
        
        self._define_common_args(parser, with_basedir=False)
    
    def exec(self):
        dir_uvn = self.uvn.paths.basedir

        uvn_address = self.uvn.args.address
        uvn_file = self.uvn.args.file

        from_address = True
        if uvn_address is None:
            if uvn_file is None:
                uvn_address = self.uvn.paths.basedir.name
                if not uvn_address:
                    self.uvn.parser.error("no address nor uvn file specified")
            else:
                from_address = False
    
        if not from_address:
            logger.debug("initializing UVN from file {}", uvn_file)
            registry_dict = libuno.yml.yml_obj(dict, uvn_file, from_file=True)
            registry_dict["config"]["basedir"] = dir_uvn
            if self.uvn.args.admin is not None:
                registry_dict["config"]["admin"] = self.uvn.args.admin
            if self.uvn.args.admin_name is not None:
                registry_dict["config"]["admin_name"] = self.uvn.args.admin_name
            if self.uvn.args.deploy:
                registry_dict["deploy"] = self.uvn.args.deploy
            if self.uvn.args.deployment_strategy is not None:
                registry_dict["deployment_strategy"] = self.uvn.args.deployment_strategy
        else:
            registry_dict = {
                "config": {
                    "basedir": dir_uvn,
                    "address": uvn_address,
                    "admin": self.uvn.args.admin,
                    "admin_name": self.uvn.args.admin_name
                },
                "cells": libuno.yml.yml_obj(
                            list,
                            self._args.cells,
                            from_file=True) if self.uvn.args.cells else [],
                "particles": libuno.yml.yml_obj(
                            list,
                            self._args.particles,
                            from_file=True) if self.uvn.args.particles else [],
                "nameserver": libuno.yml.yml_obj(
                            dict,
                            self._args.nameserver,
                            from_file=True) if self.uvn.args.nameserver else {},
                "deploy": self.uvn.args.deploy,
                "deployment_strategy": self.uvn.args.deployment_strategy
            }

        registry = self.uvn.registry_create(dir_uvn, **registry_dict)

        self.uvn.registry_save(registry)
        
        if self.uvn.args.print:
            self.uvn.registry_info(registry)
