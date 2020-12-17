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
import os
import pathlib
import tempfile

import cherrypy

from libuno.reg import UvnRegistry
from libuno.tmplt import render
from libuno.yml import yml, json

import libuno
import libuno.data as StaticData

logger = libuno.log.logger("uvn.www")

class UvnHttpd:
    @staticmethod
    def extract_root():
        outdir = tempfile.mkdtemp(
            prefix="uvn-httpd-{}-".format(libuno.__version__),)
        logger.debug("extracting www root to {}", outdir)
        for f in StaticData.www_static_files():
            logger.debug("extracting {}", f.path)
            f.copy_to_dir(outdir)
        return pathlib.Path(outdir)

    def __init__(self,
            keep=False,
            api=None):
        self.staticdir = UvnHttpd.extract_root()
        self.keep = keep
        
        self.cfg = {
            "/": {
                "tools.staticdir.root": self.staticdir
            },
            "/static": {
                "tools.staticdir.on": True,
                "tools.staticdir.dir": './'
            }
        }

        if api:
            self.api = api
            self.cfg["/api"] = self.api.cfg
    
    def __del__(self):
        if not self.keep:
            shutil.rmtree(str(self.staticdir))
        else:
            logger.warning("[tmp] not deleted: {}", self.staticdir)
    
    def main(self):
        # cherrypy.quickstart(self, '/', self.cfg)
        cherrypy.tree.mount(self, '/', self.cfg)
        cherrypy.engine.start()
        cherrypy.engine.block()
