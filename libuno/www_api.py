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
import cherrypy

from libuno.reg import UvnRegistry
from libuno.tmplt import render
from libuno.yml import yml, json

logger = libuno.log.logger("uvn.www.api")

class DataFormat:
    JSON = "json"
    YAML = "yaml"
    values = [ JSON, YAML ]
    default = JSON

    @staticmethod
    def mime(t):
        if t == DataFormat.JSON:
            return "application/json"
        elif t == DataFormat.YAML:
            return "application/x-yaml"
        else:
            return "text/plain"

    @staticmethod
    def format(t, obj):
        if t == DataFormat.JSON:
            return json(obj, public_only=True)
        elif t == DataFormat.YAML:
            return yml(obj, public_only=True)
        else:
            return str(obj)

@cherrypy.config(**{
    'tools.encode.text_only': False
})
class UvnRegistryApi:

    def __init__(self, registry_dir, data_format=DataFormat.JSON):
        self.registry_dir = registry_dir
        self.data_format = data_format
        self.cfg = {
            "tools.response_headers.on": True,
            "tools.response_headers.headers": [
                ("Content-Type", DataFormat.mime(data_format))
            ]
        }

    @cherrypy.expose
    def index(self):
        registry = UvnRegistry.load(basedir=self.registry_dir)
        response = DataFormat.format(self.data_format, registry)
        cherrypy.response.headers['Content-Type'] = DataFormat.mime(self.data_format)
        return response
    
    @cherrypy.expose
    def cells(self, cell_name=None):
        registry = UvnRegistry.load(basedir=self.registry_dir)
        
        if cell_name is None:
            response_obj = registry.cells
        else:
            cell = next((c for c in registry.cells.values()
                            if c.id.name == cell_name), None)
            response_obj = cell

        response = DataFormat.format(self.data_format, response_obj)
        cherrypy.response.headers['Content-Type'] = DataFormat.mime(self.data_format)

        return response
    
    @cherrypy.expose
    def deployments(self, deployment_id=None):
        registry = UvnRegistry.load(basedir=self.registry_dir)
        
        if deployment_id is None:
            response_obj = registry.deployments
        else:
            deployment = next((d for d in registry.deployments
                                if d.id == deployment_id), None)
            response_obj = deployment

        response = DataFormat.format(self.data_format, response_obj)
        cherrypy.response.headers['Content-Type'] = DataFormat.mime(self.data_format)

        return response
