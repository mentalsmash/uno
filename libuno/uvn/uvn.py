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
import argparse
import pathlib
import sys
import daemon
import lockfile

import libuno
from libuno.cfg import UvnDefaults
from libuno.identity import UvnIdentityDatabase
from libuno.reg import UvnRegistry, UvnPaths
from libuno.identity import UvnIdentityDatabase
from libuno.exception import UvnException

from .cmd_builtin import (UvnCommandAgent,
                          UvnCommandAttach,
                          UvnCommandCreate,
                          UvnCommandDeploy,
                          UvnCommandDrop,
                          UvnCommandGraph,
                          UvnCommandInfo,
                          UvnCommandInstall,
                          UvnCommandNameserver,
                          UvnCommandRunner,
                          commands as _builtin_commands)
from .cmd import create_all as cmd_create_all
from .uvn_fn import UvnFn

from libuno import log
logger = log.logger("uvn")

_builtin_mappings = {
    UvnCommandAgent: ("agent", ["A"]),
    UvnCommandAttach: ("attach", ["a"]),
    UvnCommandCreate: ("create", ["c"]),
    UvnCommandDeploy: ("deploy", ["d"]),
    UvnCommandDrop: ("drop", ["D"]),
    UvnCommandGraph: ("graph", ["G"]),
    UvnCommandInfo: ("info", ["i"]),
    UvnCommandInstall: ("install", ["I"]),
    UvnCommandNameserver: ("nameserver", ["ns"]),
    UvnCommandRunner: ("runner", ["R"])
}

class Uvn(UvnFn):
    @staticmethod
    def print_version():
        print("libuno.version: {}".format(libuno.__version__))
    
    @staticmethod
    def define_parser(commands, daemon=False):
        parser = argparse.ArgumentParser(
                    prog="uvn",
                    allow_abbrev=False,
                    description="Interconnect LANs over the Internet.",
                    add_help=True)
        
        parser.set_defaults(
            directory=".",
            verbose=False,
            quiet=False)
        
        # Add global arguments
        parser.add_argument("--version",
            action="store_true",
            default=False,
            help="Print versioning information and exit.")

        subparsers = {}
        ssubparsers = {}
        scmdparsers_out = {}

        cmdparsers = parser.add_subparsers(
                        title="Uvn commands",
                        dest="cmd")

        for cmd in commands:
            # Check if the command can be used by daemon version
            # If it can't, don't install it
            if daemon and not cmd.daemon_friendly:
                logger.debug("invalid command for uvn daemon: {}", cmd.name)
                continue
            parser_cmd = cmdparsers.add_parser(cmd.name,
                            help=cmd.help_short,
                            aliases=cmd.alias,
                            description=cmd.help_long,
                            add_help=True)
            parser_cmd.set_defaults(cmd=cmd.name)
            cmd.define_args(parser_cmd)
            subparsers[cmd.name] = parser_cmd
            if len(cmd.subcommands) > 0:
                cmd_subparsers = {}
                ssubparsers[cmd.name] = cmd_subparsers
                scmdparser = parser_cmd.add_subparsers(
                        title="Subcommands for {}".format(cmd.name),
                        dest="scmd")
                scmdparsers_out[cmd] = scmdparser
                for scmd in cmd.subcommands:
                    if daemon and not scmd.daemon_friendly:
                        logger.debug("invalid subcommand for uvn daemon: {} {}",
                            cmd_name, scmd_name)
                        continue
                    parser_scmd = scmdparser.add_parser(scmd.name,
                            help=scmd.help_short,
                            aliases=scmd.alias,
                            description=scmd.help_long,
                            add_help=True)
                    parser_scmd.set_defaults(scmd=scmd.name)
                    scmd.define_args(parser_scmd)
                    cmd_subparsers[scmd] = parser_scmd

        return (parser, subparsers, ssubparsers, scmdparsers_out)

    def run(self):
        if self.args.cmd is None:
            self.parser.error("no command specified.")

        cmd = next(filter(
            lambda c: c.name == self.args.cmd, self.commands),None)
        if cmd is None:
            self.parser.error("unknown command: {}".format(self.args.cmd))

        if len(cmd.subcommands) > 0:
            if not self.args.scmd:
                self.parser.error("no subcommand specified for `{}`".format(cmd.name))
            cmd = next(filter(
                lambda c: c.name == self.args.scmd, cmd.subcommands), None)

        try:
            cmd.exec()
        except Exception as e:
            logger.exception(e)
            exit(1)

    def error(self, *args, rc=1):
        if len(args) > 0:
            logger.error(*args)
        exit(rc)
    
    def _handle_global_args(self):
        if self.args.version:
            Uvn.print_version()
            exit(0)
        # Handle common global options
        if self.args.verbose is not None:
            if self.args.verbose > 2:
                log.set_verbosity(log.level.trace)
            elif self.args.verbose > 1:
                log.set_verbosity(log.level.debug)
            elif self.args.verbose > 0:
                log.set_verbosity(log.level.activity)
        elif self.args.quiet:
            log.set_verbosity(log.level.quiet)

    def __init__(self,
            commands=[],
            command_mappings={},
            builtin_mappings=_builtin_mappings,
            nobuiltin=False,
            args=None,
            daemon=False,
            cli=False):

        self.daemon = daemon
        self.cli = cli

        if (self.daemon and self.cli) or (not self.daemon and not self.cli):
            raise ValueError(self.daemon, self.cli)

        commands = list(commands)   
        command_mappings = dict(command_mappings)
        if not nobuiltin:
            commands.extend(_builtin_commands)
            command_mappings.update(builtin_mappings)
        
        self.commands = cmd_create_all(self, commands, command_mappings)
        
        if len(self.commands) == 0:
            raise UvnException("no uvn command enabled")

        (self.parser,
         self._subparsers,
         self._ssubparsers,
         self._scmdparsers) = Uvn.define_parser(self.commands, daemon=daemon)
        
        if not args:
            # If uvn was spawned from cli, use sys.argv as default arguments
            if cli:
                args = sys.argv[1:]
            else:
                args = []

        if self.daemon:
            # Daemon always runs the "agent" command
            parser_args = ["A"]
            parser_args.extend(args)
        else:
            parser_args = args
        
        self.args = self.parser.parse_args(args=parser_args)
        
        # Handle global options (must be applied before commands)
        self._handle_global_args()
        
        # Load paths object based on selected target directory
        self.paths = UvnPaths(basedir=self.args.directory)

    ############################################################################
    # Helper functions
    ############################################################################
    def registry_save(self, registry):
        return UvnFn._registry_save(
            basedir=self.paths.basedir,
            registry=registry,
            drop_old=(hasattr(self.args, "drop_old") and self.args.drop_old),
            drop_stale=(hasattr(self.args, "drop_stale") and self.args.drop_stale),
            keep=self.args.keep)

    def registry_create(self, dir_uvn, **registry_dict):
        return UvnFn._registry_create(dir_uvn, **registry_dict)
    
    def registry_load(self):
        try:
            return UvnFn._registry_load(self.paths.basedir)
        except Exception as e:
            if self.args.verbose:
                logger.exception(e)
            logger.error("failed to load UVN registry.")
            logger.warning("Are you sure {} contains a UVN configuration?", self.paths.basedir)
            self.error()

    def registry_add(self, registry, **cell_dict):
        return UvnFn._registry_add(registry, **cell_dict)

    def registry_info(self, registry):
        return UvnFn._registry_info(registry)

    def registry_deploy(self, registry, strategy=None):
        return UvnFn._registry_deploy(registry, strategy)
    
    def registry_drop(self, registry):
        return UvnFn._registry_drop(registry,
                    drop_deployment=self.args.deployment,
                    drop_cell=self.args.cell,
                    drop_all=self.args.all,
                    keep_last=getattr(self._args, "keep_last", False),
                    stale_only=getattr(self._args, "invalid_only", False))

    def registry_graph(self,
            registry,
            deployment_id=UvnDefaults["registry"]["deployment_default"],
            output="",
            outdir=""):
        return UvnFn._registry_graph(registry,
                    deployment_id=deployment_id,
                    output=output,
                    outdir=outdir)
