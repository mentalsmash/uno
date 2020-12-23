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
import types

from libuno.cfg import UvnDefaults
from libuno.tmplt import TemplateRepresentation, render
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.helpers import PeriodicFunctionThread

import libuno.log
logger = libuno.log.logger("uvn.proc")

class AgentProc(PeriodicFunctionThread):
    def __init__(self, agent,
            file=UvnDefaults["registry"]["agent"]["stat"]["file"]):
        self._agent = agent
        self._file = self._agent._basedir / file
        super(AgentProc, self).__init__(
            self._on_stat,
            period=(UvnDefaults["registry"]["agent"]["stat"]["period_min"],
                    UvnDefaults["registry"]["agent"]["stat"]["period_max"]),
            run_on_start=True,
            wrap_except=True,
            logger=logger)
    
    def _on_stat(self):
        self._file.parent.mkdir(exist_ok=True, parents=True)
        with self._agent._lock:
            stat = self._stat()
            yml(stat, to_file=self._file)
    
    def _stat(self):
        return {
            "vpn": self._stat_vpn(),
            "router": self._stat_router(),
            "peers": self._stat_peers()
        }

    def _stat_vpn(self):
        res = {
            "interfaces": {
                "registry": repr_yml(self._agent.vpn.wg_root),
                "backbone": {wg.interface: repr_yml(wg)
                                for wg in self._agent.vpn.wg_backbone},
                "router": {wg.interface: repr_yml(wg)
                                for wg in self._agent.vpn.wg_router}
            },
            "local_networks": [{k: str(v) for k, v in n.items()}
                                for n in self._agent.vpn._nat_nets]
        }
        if hasattr(self._agent.vpn, "wg_particles"):
            res["interfaces"]["particles"] = {
                self._agent.vpn.wg_particles.interface:
                    repr_yml(self._agent.vpn.wg_particles)}
        return res

    def _stat_router(self):
        return {
            "networks": {n.handle: repr_yml(n) for n in self._agent.router},
            "services": {
                "quagga": self._agent.router._quagga is not None,
                "monitor": self._agent.router._monitor is not None
            }
        }

    def _stat_peers(self):
        return {p.cell.id.name: repr_yml(p) for p in self._agent._peers}
