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

from libuno.reg import UvnRegistry
from libuno.identity import UvnIdentityDatabase
from libuno.cfg import UvnDefaults

import libuno.log
logger = libuno.log.logger("uvn")

class UvnFn:
    @staticmethod
    def _error(*args, rc=1):
        if len(args) > 0:
            logger.error(*args)
        exit(rc)

    @staticmethod
    def _registry_save(basedir, registry,
            drop_old=False, drop_stale=False, keep=False):
        logger.debug("saving UVN {} to {}...", registry.address, basedir)
        registry.export(
            drop_old_deployments=drop_old,
            drop_stale_deployments=drop_stale,
            keep=keep)
        registry.identity_db.export()
        logger.debug("saved UVN {}", registry.address)

    @staticmethod
    def _registry_create(dir_uvn, **registry_dict):
        identity_db_args = registry_dict.get("config")
        dir_uvn = identity_db_args["basedir"]
        logger.debug("initializing UVN {} in {}",
            identity_db_args["address"], dir_uvn)
        
        if (UvnIdentityDatabase.contains_db(dir_uvn) or
            UvnRegistry.contains_uvn(dir_uvn)):
            UvnFn._error("A UVN already exists in {}", dir_uvn)
        
        identity_db = UvnIdentityDatabase(**identity_db_args)
        registry = UvnRegistry(identity_db=identity_db)
        
        for c in registry_dict.get("cells",[]):
            UvnFn._registry_add(registry, **c)

        for p in registry_dict.get("particles",[]):
            name = p["name"]
            contact = p.get("contact")
            p = registry.register_particle(name, contact)
            logger.activity("added particle {} ({}) to UVN {}",
                p.name, p.contact, registry.address)
        
        for cell, names in registry_dict.get("nameserver", {}).items():
            for n in names:
                registry.nameserver.assert_record(
                    hostname=n["hostname"],
                    address=n["address"],
                    server=cell,
                    tags=set(n.get("tags",[])))

        if registry_dict.get("deploy"):
            UvnFn._registry_deploy(registry,
                strategy = registry_dict.get("deployment_strategy"))

        logger.activity("initialized UVN {} in {}", registry.address, dir_uvn)
        return registry

    @staticmethod
    def _registry_load(basedir):
        logger.debug("loading UVN from {}", basedir)
        identity_db = UvnIdentityDatabase.load(basedir)
        registry = UvnRegistry.load(identity_db)
        logger.debug("loaded UVN {}", registry.address)
        return registry

    @staticmethod
    def _registry_add(registry, **cell_dict):
        cell_name = cell_dict.get("name")
        logger.debug("adding cell {} to UVN {}", cell_name, registry.address)
        cell = registry.register_cell(**cell_dict)
        logger.activity("added cell {} ({}) to UVN {}",
            cell.id.name, cell.id.address, registry.address)
        return cell

    @staticmethod
    def _registry_info(registry):
        logger.activity("---")
        logger.activity("{}:", registry.address)
        logger.activity("  admin: {} ({})", registry.admin_name, registry.admin)
        logger.debug("  directory: {}", registry.paths.basedir)
        if registry.packaged:
            logger.activity("  package: {}", registry.pkg_cell)
        logger.debug("  cells_count: {}", len(registry.cells))
        logger.activity("  cells:")
        for c in registry.cells.values():
            if registry.packaged and c.id.name == registry.pkg_cell:
                packaged = " [PACKAGE]"
            else:
                packaged = ""
            logger.activity("    - name: {}{}", c.id.name, packaged)
            logger.debug("      admin: {} ({})", c.id.admin_name, c.id.admin)
            logger.debug("      location: {}", c.id.location)
            logger.debug("      address: {}", c.id.address)
            logger.debug("      peer_ports: {}", c.peer_ports)
        logger.debug("  deployments_count: {}", len(registry.deployments))
        logger.activity("  deployments:")
        for d_el in enumerate(registry.deployments):
            d = d_el[1]
            d_i = d_el[0]
            if (d_i == len(registry.deployments) - 1):
                logger.activity("    - &latest")
                logger.activity("      id: {}", d.id)
            else:
                logger.activity("    - id: {}", d.id)
            logger.debug("      valid: {}", not d.is_stale())
            logger.debug("      cells: {}", len(d.deployed_cells))
            # logger.debug("      directory: {}", registry.dir_deployment(d.id))
            logger.debug("      deployment:")
            for c in d.deployed_cells:
                logger.debug("        {}:", c.cell.id.name)
                for p in c.peers:
                    logger.debug("          - {}", p.cell.id.name)
        logger.activity("...")

    @staticmethod
    def _registry_deploy(registry, strategy=None):
        logger.debug("generating new deployment for UVN {}...", registry.address)
        deployment = registry.deploy(strategy=strategy)
        logger.activity("generated new deployment for UVN {}: {}", registry.address, deployment.id)
        return deployment

    def _registry_drop(self, registry,
            drop_deployment=False,
            drop_cell=False,
            drop_all=False,
            keep_last=False,
            stale_only=False):
        if drop_deployment:
            if drop_all:
                logger.activity("dropping deployments from UVN {}...", registry.address)
                registry._drop_deployments(
                    keep_last=keep_last,
                    stale_only=stale_only)
                return
        elif drop_cell:
            if drop_all:
                logger.activity("dropping all cells from UVN {}...", registry.address)
                registry._drop_cells()
                return
        
        raise NotImplementedError("requested deletion not implemented yet")

    @staticmethod
    def _registry_graph(registry,
            deployment_id=UvnDefaults["registry"]["deployment_default"],
            output="",
            outdir=""):

        logger.debug("generating graph for deployment {} of UVN {}...", deployment_id, registry.address)
        
        if len(registry.deployments) == 0:
            UvnFn._error("no deployments to graph in UVN {}", registry.address)

        if deployment_id == UvnDefaults["registry"]["deployment_default"]:
            deployment = registry.deployments[-1]
        else:
            try:
                deployment= next(filter(lambda d: d.id == deployment_id,
                                        registry.deployments))
            except StopIteration:
                UvnFn._error("unknown deployment for UVN {}: {}", registry.address, deployment_id)

        auto_output = len(output) == 0
        auto_basedir = len(outdir) == 0

        if auto_output:
            if auto_basedir:
                basedir = "."
            else:
                basedir = outdir
            output_name = "{}/{}-{}.png".format(basedir, registry.address, deployment.id)
            outfile = pathlib.Path(output_name).resolve()
        else:
            outfile = pathlib.Path(output).resolve()

        outfile.parent.mkdir(parents=True, exist_ok=True)

        graph = deployment.to_graph(save=True, filename=str(outfile))
        
        logger.activity("deployment graph: {}", outfile)
        
        return (deployment, graph)