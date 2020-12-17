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

logger = libuno.log.logger("uvn.cmd.deploy")

class UvnCommandDeploy(UvnCommand):
    
    def __init__(self, uvn, name="deploy", alias=["d"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Generate deployment configuration for a UVN",
            help_long="""Generate deployment configuration which to be
                      distributed to the cells of a UVN.""")

    def define_args(self, parser):
        deploy_opts = parser.add_argument_group("Deployment Options")

        deploy_opts.add_argument("-d","--drop-old",
            action="store_true",
            help="Drop older deployments.")

        strategies = list(libuno.deploy.DeploymentStrategy.strategy_names() )
        deploy_opts.add_argument("-s","--strategy",
            choices=strategies,
            default=strategies[0],
            help="Deployment strategy to use")
        
        self._define_common_args(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        strategy = getattr(self.uvn.args, "strategy", None)
        deployment = self.uvn.registry_deploy(registry, strategy)
        self.uvn.registry_save(registry)
        # Generate backbone graph
        self.uvn.registry_graph(
            registry,
            deployment_id=deployment.id,
            output="{}/{}".format(
                self.uvn.paths.dir_deployment(deployment.id),
                UvnDefaults["registry"]["deployment_graph"]))
