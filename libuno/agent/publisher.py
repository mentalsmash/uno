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
from functools import partial
import rti.connextdds as dds

from libuno.cfg import UvnDefaults
from libuno.exception import UvnException
import libuno.ip as ip

import libuno.log
logger = libuno.log.logger("uvn.agent.write")


############################################################################
# Writer Helpers
############################################################################
def uvn_info(agent):
    uvn_info = dds.DynamicData(agent.participant.types["uvn_info"])
    uvn_info["id.address"] = agent.registry.address
    uvn_info["cells"] = agent.summarize_peers()
    uvn_info["cell_sites"] = agent.summarize_peer_sites()
    if agent.registry.latest_deployment:
        uvn_info["deployment_id"] = agent.registry.latest_deployment.id
        uvn_info["backbone_subnet.address.value"] = ip.ipv4_to_bytes(
            agent.registry.backbone_subnet.network_address)
        uvn_info["backbone_subnet.mask"] = ip.ipv4_netmask_to_cidr(
            agent.registry.backbone_subnet.netmask)
    else:
        uvn_info["deployment_id"] = UvnDefaults["registry"]["deployment_bootstrap"]
    if agent.registry.router_subnet:
        uvn_info["router_subnet.address.value"] = ip.ipv4_to_bytes(
            agent.registry.router_subnet.network_address)
        # uvn_info["router_subnet.mask"] = ip.ipv4_netmask_to_cidr(
        #     agent.registry.router_subnet.netmask)
        uvn_info["router_subnet.mask"] = agent.registry.router_subnet.prefixlen
    if agent.registry.backbone_subnet:
        uvn_info["backbone_subnet.address.value"] = ip.ipv4_to_bytes(
            agent.registry.backbone_subnet.network_address)
        uvn_info["backbone_subnet.mask"] = ip.ipv4_netmask_to_cidr(
            agent.registry.backbone_subnet.netmask)

    logger.debug("publishing uvn info:\n{}", uvn_info)
    agent.participant.writer("uvn_info").write(uvn_info)

def cell_info(agent, cell, cell_cfg):
    cell_info = dds.DynamicData(agent.participant.types["cell_info"])
    cell_info["id.name"] = cell.id.name
    cell_info["id.uvn.address"] = agent.registry.address
    cell_info["pid"] = os.getpid()
    cell_info["status"] = agent._status.value()
    cell_info["peers"] = agent.summarize_peers()
    sites = agent.summarize_cell_sites()
    sites.extend(agent.summarize_peer_sites())
    cell_info["routed_sites"] = sites
    if agent.registry.deployment_id is not None:
        cell_info["deployment_id"] = agent.registry.deployment_id
    if agent._ts_created:
        cell_info["ts_created"] = int(agent._ts_created.millis())
    if agent._ts_loaded:
        cell_info["ts_loaded"] = int(agent._ts_loaded.millis())
    if agent._ts_started:
        cell_info["ts_started"] = int(agent._ts_started.millis())
    logger.debug("publishing cell info:\n{}", cell_info)
    agent.participant.writer("cell_info").write(cell_info)

def deployment(agent, deployment_id, cell_name, installer):
    installer = pathlib.Path(installer)
    with installer.open("rb") as input:
        cell_pkg = dds.DynamicData(agent.participant.types["deployment"])
        cell_pkg["cell.name"] = cell_name
        cell_pkg["cell.uvn.address"] = agent.registry.address
        cell_pkg["id"] = deployment_id
        cell_pkg["package"] = input.read()
        logger.info("pushing installer {} to cell {} [size: {} KB]",
            installer.name, cell_name, len(list(cell_pkg["package"])) / 1024.0)
        agent.participant.writer("deployment").write(cell_pkg)

def deployments(agent):
    latest_deployment = agent.registry.latest_deployment
    if latest_deployment is None:
        logger.warning("no deployment generated")
        return
    logger.activity("publishing latest deployment: {}", latest_deployment.id)
    installers = agent.registry._list_deployment_installers(deployment=latest_deployment)
    installers = {str(pathlib.Path(i).stem).split("-")[-1]: i for i in installers}
    missing_cells = [c for c in agent.registry.cells.keys() if c not in installers]
    if missing_cells:
        raise UvnException(f"missing deployment installers: {missing_cells}")
    return list(map(
            (lambda i: deployment(agent, latest_deployment.id, *i)),
            installers.items()))

def dns_entries(agent):
    dns_db = dds.DynamicData(agent.participant.types["dns_db"])
    dns_db["cell.name"] = (agent.registry.deployed_cell.id.name
                                if agent.registry.deployed_cell
                                else agent.registry.address)
    dns_db["cell.uvn.address"] = agent.registry.address
    # This fails 1 out of 9 times for yet to identify reasons
    # dns_db["entries"] = agent.summarize_nameserver_entries()
    # This seems to be always working
    for i, e in enumerate(agent._get_published_nameserver_entries()):
        dns_rec = e["record"]
        with dns_db.loan_value("entries") as entries:
            with entries.data.loan_value(i) as d:
                d.data[f"hostname"] = dns_rec.hostname
                d.data[f"address.value"] = ip.ipv4_to_bytes(dns_rec.address)
                d.data[f"tags"] = dns_rec.tags
    agent.participant.writer("dns").write(dns_db)
    logger.info("[dns] pushed {} records", len(dns_db["entries"]))
    return dns_db

methods = [
    uvn_info,
    cell_info,
    deployment,
    deployments,
    dns_entries
]