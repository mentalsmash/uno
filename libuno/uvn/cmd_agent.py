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
from daemon import pidfile as daemon_pidfile
# import lockfile
import pathlib
import signal

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
        parser.add_argument("-i","--interface",
            action="append",
            default=[],
            help="Select local network interfaces to attach. Otherwise use any interface with an IPv4 address. Repeat for multiple interfaces.")
        self._define_common_args(parser)
    
    def exec(self):
        if self.uvn.daemon:
            self._exec_daemon()
        else:
            self._exec()

    def _create_agent(self, daemon=False):
        dir_uvn = self.uvn.paths.basedir
        logger.debug("creating UVN agent from {}", dir_uvn)
        agent = UvnAgent.load(
                    registry_dir=dir_uvn,
                    keep=self.uvn.args.keep,
                    roaming=self.uvn.args.roaming,
                    daemon=daemon,
                    interfaces=self.uvn.args.interface)
        logger.activity("created UVN agent: {}", agent.registry.address)
        return agent

    def _exec(self):
        agent = self._create_agent()
        agent.start(nameserver=self.uvn.args.nameserver)
        agent.main(daemon=False)
        
    def _exec_daemon(self):
        agent_basedir = pathlib.Path(UvnDefaults["registry"]["agent"]["basedir"])
        pidfile = agent_basedir / UvnDefaults["registry"]["agent"]["pid"]
        logfile = agent_basedir / UvnDefaults["registry"]["agent"]["log_file"]

        logger.activity("starting uvn daemon: basedir={}, pid={}, log={}",
            self.uvn.paths.basedir, pidfile, logfile)

        # Disable colored output since we'll be logging to a file
        libuno.log.set_color(False)
        
        logfile.parent.mkdir(exist_ok=True, parents=True)

        agent = None

        def _process_deploy(sig, frame):
            if agent:
                agent._request_deploy()
        
        def _process_reload(sig, frame):
            if agent:
                agent._request_reload()
        
        def _process_exit(sig, frame):
            if agent:
                agent._request_exit()

        with logfile.open("ab", 0) as logout:
            daemon_ctx = daemon.DaemonContext(
                working_directory=self.uvn.paths.basedir,
                umask=0o002,
                pidfile=daemon_pidfile.TimeoutPIDLockFile(str(pidfile)),
                stdout=logout,
                stderr=logout,
                signal_map={
                        signal.SIGTERM: _process_exit,
                        signal.SIGHUP: _process_exit,
                        signal.SIGINT: _process_exit,
                        signal.SIGUSR1: _process_reload,
                        signal.SIGUSR2: _process_deploy,
                    },
                # gid=... ,
                # uid=... ,
                )

            try:
                with daemon_ctx:
                    agent = self._create_agent()
                    agent.start(nameserver=self.uvn.args.nameserver)
                    agent.main(daemon=True)
            except Exception as e:
                logger.error("failed to run uvnd or uvnd already running: {}", e)
