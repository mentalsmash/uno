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

from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.tmplt import TemplateRepresentation
from libuno.cfg import UvnDefaults

import libuno.data as StaticData

TopicQueries = {
    "match_cell": {
        "cell_info": "id.uvn.address MATCH {} AND id.name MATCH {}",
        "dns": "cell.uvn.address MATCH {} AND cell.name MATCH {}",
        "deployment": "cell.uvn.address MATCH {} AND cell.name MATCH {}"
    },
    "match_others": {
        "cell_info": "id.uvn.address MATCH {} AND NOT id.name MATCH {}",
        "dns": "cell.uvn.address MATCH {} AND NOT cell.name MATCH {}",
        "deployment": "cell.uvn.address MATCH {} AND NOT cell.name MATCH {}"
    },
    "match_uvn": {
        "uvn_info": "id.address MATCH {}",
        "cell_info": "id.uvn.address MATCH {}",
        "dns": "cell.uvn.address MATCH {}"
    }
}

RouterTypeMappings = {
    "uvn_info": UvnDefaults["dds"]["types"]["uvn_info"],
    "cell_info": UvnDefaults["dds"]["types"]["cell_info"],
    "dns_db": UvnDefaults["dds"]["types"]["dns_db"],
    "deployment": UvnDefaults["dds"]["types"]["deployment"]
}

RoutingServiceTopics = [
    {
        "route": "cell_info",
        "name": "uno/cell/info",
        "type": "cell_info",
        "qos_profile": "UnoQosProfiles::CellInfo"
    },
    {
        "route": "dns",
        "name": "uno/uvn/ns",
        "type": "dns",
        "qos_profile": "UnoQosProfiles::Nameserver"
    }
]

def read_qos_profile():
    xml_cfg = StaticData.dds_profile_file()
    with xml_cfg.open() as input:
        return input.read()

def read_types_and_qos():
    xml_cfg = read_qos_profile()
    types = xml_cfg[xml_cfg.find("<types>"):xml_cfg.find("</types>") + len("</types>")]
    qos = xml_cfg[xml_cfg.find("<qos_library"):xml_cfg.find("</qos_library>") + len("</qos_library>")]
    return {
        "types_lib": types,
        "qos_lib": qos
    }

def serialize_config(py_repr):
    yml_repr = {
        "registry_address": py_repr.registry.address,
        "peers": py_repr.peers,
        "topics": py_repr.topics,
        "queries": py_repr.queries,
        "types": py_repr.types,
        "orig_info": py_repr.with_orig_info
    }
    yml_repr.update(read_types_and_qos())
    return yml_repr

def init_config(self, 
        peers, registry,
        cell=None,
        cell_cfg=None,
        with_orig_info=UvnDefaults["dds"]["rs"]["orig_info"],
        topics=RoutingServiceTopics,
        types=RouterTypeMappings,
        queries=TopicQueries):
    self.peers = peers
    self.registry = registry
    self.with_orig_info = with_orig_info
    self.topics = topics
    self.types = types
    self.queries = queries
    self.cell = cell
    self.cell_cfg = cell_cfg

@TemplateRepresentation("rs-config","dds/rs.xml")
class CellRoutingServiceConfig:
    def __init__(self, *args, **kwargs):
        init_config(self, *args, **kwargs)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = serialize_config(py_repr)
            yml_repr["cell_name"] = py_repr.cell.id.name
            return yml_repr

        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()

@TemplateRepresentation("rs-config","dds/rs-root.xml")
class RootRoutingServiceConfig:
    def __init__(self, *args, **kwargs):
        init_config(self, *args, **kwargs)

    class _YamlSerializer(YamlSerializer):

        def repr_yml(self, py_repr, **kwargs):
            return serialize_config(py_repr)

        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()
