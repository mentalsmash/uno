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
import sys
import subprocess
import pathlib
import tempfile

import libuno.ip as ip
from libuno.cfg import UvnDefaults
from libuno.uvn.cmd import UvnCommand, UvnSubcommand
from libuno.exec import exec_command
from libuno.rs import RoutingServiceProcess
from libuno.agent.quagga import Vtysh

import libuno.log

logger = libuno.log.logger("uvn.cmd.view")

def pager(data):
    try:
        # args stolen fron git source, see `man less`
        pager = subprocess.Popen(['less', '-F', '-R', '-S', '-X', '-K'],
                    stdin=subprocess.PIPE, stdout=sys.stdout)
        pager.communicate(data.encode("utf-8"))
        pager.stdin.close()
        pager.wait()
    except KeyboardInterrupt:
        # let less handle this, -K will exit cleanly
        pass

class UvnCommandView(UvnCommand):
    def __init__(self, uvn, name="view", alias=["v"]):
        UvnCommand.__init__(self, uvn,
            name=name,
            alias=alias,
            help_short="Display UVN Agent configuration files and logs.",
            help_long="""Display UVN Agent configuration files and logs..""",
            subcommands=[
                UvnSubcommandViewRoutingService,
                UvnSubcommandViewKernel,
                UvnSubcommandViewZebra,
                UvnSubcommandViewOspfd,
                UvnSubcommandViewNameserver,
                UvnSubcommandViewAgent])

    def define_args(self, parser):
        self._define_common_args(parser)
    
    def _define_args_sub(self, parser, with_log=True, with_config=True, with_oneline=False):
        self._define_common_args(parser)
        parser.add_argument("-R", "--raw",
            action="store_true",
            default=False,
            help=f"Dump content to stdout without any paging.")
        if with_log:
            parser.add_argument("-l", "--logs",
                action="store_true",
                default=False,
                help=f"Display log file.")
        if with_config:
            parser.add_argument("-c", "--config",
                action="store_true",
                default=False,
                help=f"Display configuration file.")
        if with_oneline:
            parser.add_argument("-o", "--oneline",
                action="store_true",
                default=False,
                help=f"Display more compact and easier to parse results.")
        parser.add_argument("--rundir",
                default=UvnDefaults["registry"]["agent"]["basedir"],
                help=f"Base agent directory.")
    

    def display_file(self, registry, type, file_path):
        file_path = pathlib.Path(file_path)
        if not file_path.exists():
            logger.error("[not found] {}: {}", type, file_path)
            sys.exit(1)
        logger.activity("[display][{}] {}: {}",
            f"{registry.pkg_cell}@{registry.address}"
                if registry.pkg_cell
                else f"{registry.address}",
            type, file_path)
        with file_path.open("r") as input:
            data = input.read()
            if not self.uvn.args.raw:
                data = """-------------------------------------------
 {}
-------------------------------------------
{}""".format(type, data)
                pager(data)
            else:
                print(data)
    
    def display_data(self, registry, type, data):
        with tempfile.NamedTemporaryFile(mode='r+') as tmpfile:
            tmpfile.write(data)
            tmpfile.flush()
            self.display_file(registry, type, tmpfile.name)

class UvnSubcommandViewRoutingService(UvnSubcommand):
    def __init__(self, parent, name="routingservice", alias=["rs", "r"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display data from RTI Routing Service.",
            help_long="""Display data from RTI Routing Service.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser)
    
    def exec(self):
        self.rs = RoutingServiceProcess(basedir=self.uvn.args.rundir)
        registry = self.uvn.registry_load()
        if self.uvn.args.config:
            return self._config(registry)
        else:
            self._logs(registry)
    
    def _logs(self, registry):
        self.parent.display_file(registry, "routing service logs",
            self.rs.log_file)
    
    def _config(self, registry):
        self.parent.display_file(registry, "routing service logs",
            self.rs.cfg_file)

class UvnSubcommandViewKernel(UvnSubcommand):
    def __init__(self, parent, name="kernel", alias=["k"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display data from Linux kernel.",
            help_long="""Display data from Linux kernel.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser, with_oneline=True)
        parser.add_argument("-r", "--routes",
            action="store_true",
            default=False,
            help=f"Display kernel routing table.")
        parser.add_argument("-n", "--noresolve",
            action="store_true",
            default=False,
            help=f"Don't try to resolve ip addresses.")

    def exec(self):
        registry = self.uvn.registry_load()
        return self._routes(registry)

    def _routes(self, registry):
        routes = ip.ipv4_list_routes(oneline=self.uvn.args.oneline, split=False)
        if not self.uvn.args.noresolve:
            routes = ip.ipv4_resolve_text(routes, ns=registry.nameserver)
        self.parent.display_data(registry, "kernel routing table", routes)

class UvnSubcommandViewZebra(UvnSubcommand):
    def __init__(self, parent, name="zebra", alias=["z"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display data from zebra.",
            help_long="""Display data from zebra.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser)
    
    def exec(self):
        registry = self.uvn.registry_load()
        if self.uvn.args.config:
            return self._config(registry)
        else:
            self._logs(registry)
    
    def _logs(self, registry):
        basedir = pathlib.Path(self.uvn.args.rundir) / UvnDefaults["router"]["run_dir"]
        log_file = basedir / UvnDefaults["router"]["zebra"]["log"]
        self.parent.display_file(registry, "zebra logs", log_file)
    
    def _config(self, registry):
        basedir = pathlib.Path(self.uvn.args.rundir) / UvnDefaults["router"]["run_dir"]
        conf_file = basedir / UvnDefaults["router"]["zebra"]["conf"]
        self.parent.display_file(registry, "zebra configuration", conf_file)

class UvnSubcommandViewOspfd(UvnSubcommand):
    def __init__(self, parent, name="ospfd", alias=["o"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display data from ospfd.",
            help_long="""Display data from ospfd.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser)
        parser.add_argument("-n", "--neighbors",
            action="store_true",
            default=False,
            help="Display OSPF neighbors.")
        parser.add_argument("-r", "--routes",
            action="store_true",
            default=False,
            help="Display OSPF routing table.")
        parser.add_argument("-i", "--interfaces",
            action="store_true",
            default=False,
            help="Display OSPF information about network interfaces.")
        parser.add_argument("-b", "--borders",
            action="store_true",
            default=False,
            help=f"Display OSPF ABR/ASBR routers.")
        parser.add_argument("-L", "--lsa",
            action="store_true",
            default=False,
            help=f"Display LSAs generated by OSPF.")
        parser.add_argument("-s", "--summary",
            action="store_true",
            default=False,
            help=f"Display summary information about the OSPF router.")
        
    
    def exec(self):
        registry = self.uvn.registry_load()
        if self.uvn.args.neighbors:
            self._vtysh(registry, "ospf.info.neighbors")
        elif self.uvn.args.routes:
            self._vtysh(registry, "ospf.info.routes")
        elif self.uvn.args.interfaces:
            self._vtysh(registry, "ospf.info.interfaces")
        elif self.uvn.args.borders:
            self._vtysh(registry, "ospf.info.borders")
        elif self.uvn.args.lsa:
            self._vtysh(registry, "ospf.info.lsa")
        elif self.uvn.args.config:
            return self._config(registry)
        elif self.uvn.args.logs:
            self._logs(registry)
        else:
            self._vtysh(registry, "ospf.info.summary")

    def _logs(self, registry):
        basedir = pathlib.Path(self.uvn.args.rundir) / UvnDefaults["router"]["run_dir"]
        log_file = basedir / UvnDefaults["router"]["ospfd"]["log"]
        self.parent.display_file(registry, "ospfd logs", log_file)
    
    def _config(self, registry):
        basedir = pathlib.Path(self.uvn.args.rundir) / UvnDefaults["router"]["run_dir"]
        conf_file = basedir / UvnDefaults["router"]["ospfd"]["conf"]
        self.parent.display_file(registry, "ospfd configuration", conf_file)
    
    def _vtysh(self, registry, cmd):
        output = Vtysh.exec(cmd)
        self.parent.display_data(registry, cmd, output)

class UvnSubcommandViewNameserver(UvnSubcommand):
    def __init__(self, parent, name="nameserver", alias=["dns", "n", "names"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display data from dnsmasq.",
            help_long="""Display data from dnsmasq.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser, with_log=False)
        parser.add_argument("-db", "--database",
            action="store_true",
            default=False,
            help=f"Display nameserver records.")
    
    def exec(self):
        basedir = pathlib.Path(self.uvn.args.rundir)
        self._run_dir = basedir / UvnDefaults["nameserver"]["run_dir"]
        registry = self.uvn.registry_load()
        if self.uvn.args.config:
            return self._config(registry)
        else:
            self._db(registry)
    
    def _db(self, registry):
        db_file = self._run_dir / UvnDefaults["nameserver"]["hosts_dir"] / UvnDefaults["nameserver"]["hosts_file"]
        self.parent.display_file(registry, "nameserver database", db_file)
    
    def _config(self, registry):
        conf_file = pathlib.Path(UvnDefaults["nameserver"]["conf_file"] )
        self.parent.display_file(registry, "nameserver configuration", conf_file)

class UvnSubcommandViewAgent(UvnSubcommand):
    def __init__(self, parent, name="agent", alias=["a"]):
        UvnSubcommand.__init__(self, parent,
            name=name,
            alias=alias,
            help_short="Display summary information about uvnd.",
            help_long="""Display summary information about uvnd.""")

    def define_args(self, parser):
        self.parent._define_args_sub(parser, with_config=False)
        parser.add_argument("-n", "--noresolve",
            action="store_true",
            default=False,
            help=f"Don't try to resolve ip addresses.")
        
        parser.add_argument("-P", "--proc-file",
            default=UvnDefaults["registry"]["agent"]["stat"]["file"],
            help=f"File containing statistics generated by UVN Agent")
    
    def exec(self):
        registry = self.uvn.registry_load()
        basedir = pathlib.Path(self.uvn.args.rundir)

        if self.uvn.args.logs:
            log_file = basedir / UvnDefaults["registry"]["agent"]["log_file"]
            self.parent.display_file(registry, "uvnd logs", log_file)
        else:
            proc_file = basedir / self.uvn.args.proc_file
            with proc_file.open("r") as input:
                stats = input.read()
                if not self.uvn.args.noresolve:
                    stats = ip.ipv4_resolve_text(stats, ns=registry.nameserver)
                self.parent.display_data(registry, "agent statistics", stats)

        # self.parent.display_file(registry, "/proc/agent", proc_file)

