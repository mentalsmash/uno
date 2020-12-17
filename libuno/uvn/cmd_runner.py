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
from libuno.cfg import UvnDefaults
from libuno.docker import DockerController

import libuno.log

logger = libuno.log.logger("uvn.cmd.runner")

class UvnCommandRunner(UvnCommand):
    
    def __init__(self, uvn, name="runner", alias=["R"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Provision a uvn node with a Docker container",
            help_long="""Provision a uvn node with a Docker container.""",
            subcommands=[UvnSubcommandRunnerBuild])

class UvnSubcommandRunnerBuild(UvnSubcommand):

    def __init__(self, parent, name="build", alias=["b"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Build Docker images and containers to provision a UVN node.",
            help_long="""Build Docker images and containers to provision a UVN node.""")

    def define_args(self, parser):
        parser.add_argument("-s", "--socket",
            default=UvnDefaults["docker"]["socket"],
            help="URL for the Docker daemon socket")

        parser.add_argument("-r", "--rebuild",
            default=False, action="store_true",
            help="Rebuild runner image")
        
        # parser.add_argument("-rb", "--rebuild-base",
        #     default=False, action="store_true",
        #     help="Rebuild base runner image")
        
        parser.add_argument("-d", "--drop-old",
            default=False, action="store_true",
            help="Drop old containers and images")
        
        parser.add_argument("-n", "--nocache",
            default=False, action="store_true",
            help="Do not cache docker build stages")
        
        parser.add_argument("-V", "--volume",
            action="append",
            default=[],
            help="Additional volume to mount, in the form <volume>:<mountpoint>:<mode>. Repeat for multiple volumes.")

        parser.add_argument("-p", "--package",
            action="append",
            default=[],
            help="Additional apt packages to intall in the runner image.")
        
        parser.add_argument("-D","--dev",
            default=False, action="store_true",
            help="Generate image from a local clone of uno.")
        
        # parser.add_argument("-i","--image-only",
        #     default=False, action="store_true",
        #     help="Only build container image, do not create a container")

        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        docker_ctrl = DockerController(
                        registry,
                        socket=self.uvn.args.socket,
                        dev=self.uvn.args.dev)
    
        docker_ctrl.build_runner(
            keep=self.uvn.args.keep,
            drop_old=self.uvn.args.drop_old,
            rebuild=self.uvn.args.rebuild,
            # rebuild_base=self.uvn.args.rebuild_base,
            rebuild_base=False,
            nocache=self.uvn.args.nocache,
            volumes={
                v.split(":")[0]: {
                    "bind":  v.split(":")[1],
                    "mode": v.split(":")[2]
                } for v in self.uvn.args.volume
            },
            packages=self.uvn.args.package,
            # image_only=self.uvn.args.image_only)
            image_only=True)
