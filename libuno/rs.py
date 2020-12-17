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
import pathlib
import threading

from libuno.cfg import UvnDefaults
from libuno.connext import NddshomeInfoDescriptor
from libuno.exec import exec_command
from libuno.tmplt import render

import libuno.log
logger = libuno.log.logger("uvn.rs")

class RoutingServiceProcess(threading.Thread):
    connext = NddshomeInfoDescriptor()

    def __init__(self, cfg_name=None, cfg=None,
            basedir=UvnDefaults["registry"]["agent"]["basedir"],
            cfg_dir=UvnDefaults["dds"]["dir"],
            cfg_file=UvnDefaults["dds"]["rs"]["config_file"],
            log_file=UvnDefaults["dds"]["rs"]["log_file"],
            verbosity=UvnDefaults["dds"]["rs"]["verbosity"],
            keep=True):
        threading.Thread.__init__(self)
        self._basedir = pathlib.Path(basedir)
        self._bin = self.connext.service.routing_service
        self._cfg_dir = self._basedir / cfg_dir
        self.cfg_file = self._cfg_dir / cfg_file
        self.cfg_name = cfg_name
        self._cfg = cfg
        self.log_file = self._cfg_dir / log_file
        self._verbosity = verbosity
        self._keep = keep

    def start(self, cfg_name=None, cfg=None):
        # Generate configuration
        if not cfg_name:
            if not self.cfg_name:
                raise ValueError("no configuration name specified")
            cfg_name = self.cfg_name
        if not cfg:
            if not self._cfg:
                raise RuntimeError("no configuration object specified")
            cfg = self._cfg
        render(cfg, "rs-config", to_file=self.cfg_file)
        self.cfg_name = cfg_name
        self._cfg = cfg
        threading.Thread.start(self)

    def stop(self):
        logger.activity("signaling routing service to exit")
        exec_command(["killall", "-SIGTERM", "rtiroutingservice"],
            fail_msg="failed to signal routing service",
            noexcept=True)
        self.join()

    def run(self):
        # try:
        logger.debug("starting routing service")
        result = exec_command(
            [self._bin,
                "-verbosity", str(self._verbosity),
                "-cfgFile", str(self.cfg_file),
                "-cfgName", self.cfg_name],
                # "|", "tee", "-a", str(self.log_file)],
            # shell=True,
            output=self.log_file,
            fail_msg=f"failed to run routing service. see {self.log_file} for more info",
            noexcept=True)
        logger.activity("routing service exited")
        # finally:
        #     if not self._keep and self.cfg_file.exists():
        #         self.cfg_file.unlink()

