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
import daemon
import lockfile
from libuno.uvn.cmd import UvnCommand
from libuno.agent import UvnAgent
from libuno.cfg import UvnDefaults

import libuno.log

logger = libuno.log.logger("uvn.cmd.agent")

class UvnCommandAgent(UvnCommand):
    
    def __init__(self, uvn, name="agent", alias=["A"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Start the UVN agent",
            help_long="""Start the UVN agent.""",
            daemon_friendly=True)

    def define_args(self, parser):
        parser.add_argument("-r","--roaming",
            action="store_true",
            default=False,
            help="Enable roaming mode.")
        parser.add_argument("-n","--nameserver",
            action="store_true",
            default=False,
            help="Enable DNS server (requires dnsmasq).")
        self._define_common_args(parser)
    
    def exec(self):
        if self.uvn.daemon:
            self._exec_daemon()
        else:
            self._exec()

    def _exec(self):
        dir_uvn = self.uvn.paths.basedir
        logger.debug("creating UVN agent from {}", dir_uvn)
        agent = UvnAgent.load(
                    registry_dir=dir_uvn,
                    keep=self.uvn.args.keep,
                    roaming=self.uvn.args.roaming)
        logger.activity("created UVN agent: {}", agent.registry.address)
        agent.start(nameserver=self.uvn.args.nameserver)
        agent.main(daemon=self.uvn.daemon)
        
    def _exec_daemon(self):
        context = daemon.DaemonContext(
            working_directory=str(self.uvn.paths.basedir),
            umask=0o077,
            pidfile=lockfile.FileLock(UvnDefaults["registry"]["agent"]["pid"]),
        )

        # context.signal_map = {
        #     signal.SIGTERM: program_cleanup,
        #     signal.SIGHUP: 'terminate',
        #     signal.SIGUSR1: reload_program_config,
        #     }
        # context.gid = ...
        # context.uid = ...

        with context:
            self._exec()

