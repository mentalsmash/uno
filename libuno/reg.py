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
import string
import ipaddress
import os
import pathlib
import time
import traceback
import shutil
import glob

from libuno import wg
from libuno import ip
from libuno.wg import WireGuardKeyPair
from libuno.cell import CellKeyMaterial, CellIdentity, Cell
from libuno.particle import Particle
from libuno.helpers import Timestamp, ListLastElementDescriptor, ValuesRange
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.tmplt import TemplateRepresentation, render
from libuno.cfg import UvnDefaults, UvnPaths, WireGuardConfig
from libuno.deploy import UvnDeployment, UvnDeploymentSummary
from libuno.psk import PresharedKeys
from libuno.cell_cfg import CellDeployment
from libuno.strategy import DeploymentStrategy
from libuno.identity import UvnIdentityDatabase, UvnCellRecord, PackagedDescriptor, DisabledIfPackaged
from libuno.exception import UvnException, UnknownCellException, UnknownParticleException
from libuno.install import UvnCellInstaller
from libuno.ns import UvnNameserver
from libuno.router_port import RegistryRouterPorts
from libuno.backbone import deploy as deploy_backbone

import libuno.log
logger = libuno.log.logger("uvn.registry")

class UvnRegistryDescriptor:
    def _get(self, obj, attr):
        if (not hasattr(obj, "identity_db") or
            not isinstance(obj.identity_db, UvnIdentityDatabase)):
            raise TypeError("invalid target for UvnRegistryDescriptor")
        return getattr(obj.identity_db.registry_id, attr)

class UvnRegistryAddressDescriptor(UvnRegistryDescriptor):
    def __get__(self, obj, objtype=None):
        return self._get(obj, "address")

class UvnRegistryAdminDescriptor(UvnRegistryDescriptor):
    def __get__(self, obj, objtype=None):
        return self._get(obj, "admin")

class UvnRegistryAdminNameDescriptor(UvnRegistryDescriptor):
    def __get__(self, obj, objtype=None):
        return self._get(obj, "admin_name")

class UvnRegistryKeyDescriptor(UvnRegistryDescriptor):
    def __get__(self, obj, objtype=None):
        return self._get(obj, "key")

class UvnRegistryBasedirDescriptor(UvnRegistryDescriptor):
    def __get__(self, obj, objtype=None):
        return self._get(obj, "basedir")

class UvnRegistryBootstrappedDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.packaged:
            return obj.deployment_id != UvnDefaults["registry"]["deployment_bootstrap"]
        else:
            return obj.latest_deployment is not None

class UvnRegistryCellDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.pkg_cell:
            return obj.cell(obj.pkg_cell)
        else:
            return None

class UvnRegistryCellConfigDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.packaged:
            return obj.get_cell_deployment_config(
                        obj.deployment_id,
                        obj.deployed_cell.id.name,
                        default=None)
        else:
            return None

class UvnRegistryDeployedCellsDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.latest_deployment:
            return obj.latest_deployment.deployed_cells
        else:
            return []

class UvnRegistryCellRecordConfigDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.packaged:
            return obj.identity_db.get_cell_record(
                        obj.deployed_cell.id.name)
        else:
            return None

class UvnRegistryBackboneIpRangeDescriptor:
    def __get__(self, obj, objtype=None):
        ip_start = ipaddress.ip_address("0.0.0.0")
        ip_end = ip_start
        if obj.latest_deployment:
            ip_start = obj.latest_deployment.address_range[0]
            ip_end = obj.latest_deployment.address_range[1]
        return ValuesRange(ip_start, ip_end, 2)

class UvnRegistryBackboneIpSubnetDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.latest_deployment:
            return obj.latest_deployment.backbone_subnet()
        return None

class UvnRegistryRouterIpSubnetDescriptor:
    def __get__(self, obj, objtype=None):
        if obj.router_ports:
            return ip.ipv4_range_subnet(
                # obj.router_ports[0].addr_local,
                ipaddress.ip_address(
                    UvnDefaults["registry"]["vpn"]["router"]["base_ip"]),
                obj.router_ports[-1].addr_remote)
        return None

@TemplateRepresentation("www","www/registry/index.html")
class UvnRegistry:

    address = UvnRegistryAddressDescriptor()
    admin = UvnRegistryAdminDescriptor()
    admin_name = UvnRegistryAdminNameDescriptor()
    key = UvnRegistryKeyDescriptor()
    basedir = UvnRegistryBasedirDescriptor()
    latest_deployment = ListLastElementDescriptor("deployments")
    bootstrapped = UvnRegistryBootstrappedDescriptor()
    packaged = PackagedDescriptor()
    deployment_cells = UvnRegistryDeployedCellsDescriptor()
    deployed_cell = UvnRegistryCellDescriptor()
    deployed_cell_config = UvnRegistryCellConfigDescriptor()
    deployed_cell_record = UvnRegistryCellRecordConfigDescriptor()
    backbone_ips = UvnRegistryBackboneIpRangeDescriptor()
    backbone_subnet = UvnRegistryBackboneIpSubnetDescriptor()
    router_subnet = UvnRegistryRouterIpSubnetDescriptor()

    def __init__(self,
                 identity_db,
                 ports=UvnDefaults["registry"]["ports"],
                 cells=None,
                 particles=None,
                 keymat=None,
                 deployments=None,
                 loaded=False,
                 pkg_cell=None,
                 deployment_id=None,
                 vpn_config=None,
                 nameserver=None,
                 router_ports=None):
        self.identity_db = identity_db
        self.ports = list(ports)
        self.paths = UvnPaths(identity_db.registry_id.basedir)
        if deployments is None:
            self.deployments = []
        else:
            self.deployments = deployments
        if cells is None:
            self.cells = {}
        else:
            self.cells = cells
        if particles is None:
            self.particles = {}
        else:
            self.particles = particles
        if keymat is None:
            self.keymat = WireGuardKeyPair.generate()
        else:
            self.keymat = keymat
        self.loaded = loaded
        self.dirty = False
        self.pkg_cell = pkg_cell
        self.deployment_id = deployment_id
        self.vpn_config = vpn_config
        if nameserver is not None:
            self.nameserver = nameserver
        else:
            self.nameserver = UvnNameserver(self.identity_db)
        if router_ports is not None:
            self.router_ports = router_ports
        else:
            self.router_ports = RegistryRouterPorts()
    
    def particle(self, name, noexcept=False):
        particle = self.particle.get(name)
        if not particle and not noexcept:
            raise UnknownParticleException(name)
        return particle
    
    def cell(self, name, noexcept=False):
        cell = self.cells.get(name)
        if not cell and not noexcept:
            raise UnknownCellException(name)
        return cell
    
    def cell_by_n(self, n, noexcept=False):
        try:
            return next(filter(lambda c: c.id.n == n, self.cells.values()))
        except StopIteration as e:
            if noexcept:
                return None
            raise e
 
    @DisabledIfPackaged
    def register_cell(self,
                      name,
                      address=None,
                      admin=None,
                      admin_name=None,
                      location=None,
                      peer_ports=None,
                      # Catch all other extra arguments, to allow users to
                      # store custom entries in the input YAML file
                      **kwargs):
        if name in self.cells:
            raise UvnException(f"cell name already in use : '{name}'")

        if address is None:
            address = "{}.{}".format(name, self.identity_db.registry_id.address)

        if admin is None:
            admin = self.identity_db.registry_id.admin
        
        if admin_name is None:
            admin_name = UvnDefaults["registry"]["admin_name"]
        
        if location is None:
            location = UvnDefaults["cell"]["location"]
        
        if peer_ports is None:
            peer_ports = list(UvnDefaults["cell"]["peer_ports"])

        self.identity_db.register_cell(
            name=name,
            address=address,
            admin=admin,
            admin_name=admin_name,
            generate=True)

        keymat = CellKeyMaterial()
        cell_id = CellIdentity(
                    name=name,
                    n=len(self.cells) + 1,
                    address=address,
                    keymat=keymat,
                    location=location,
                    admin=admin,
                    admin_name=admin_name)
        cell = Cell(
                cell_id=cell_id,
                psk=wg.genkeypreshared(),
                peer_ports=peer_ports)
        self.cells[cell.id.name] = cell

        logger.debug("registered cell: {} ({})", cell.id.name, cell.id.address)

        self._generate_vpn_config()
        self._generate_router_ports()
        self._generate_particles()
        
        self.dirty = True
        
        return cell
    
    @DisabledIfPackaged
    def register_particle(self, name, contact=None):
        if name in self.particles:
            raise UvnException(f"particle name already in use : '{name}'")
    
        if contact is None:
            contact = "{}@{}".format(name, self.address)
            
        particle = Particle(
            name=name,
            n=len(self.particles) + 1,
            contact=contact)
        
        self.particles[particle.name] = particle

        logger.debug("registered particle: {} ({})",
            particle.name, particle.contact)
        
        self._generate_particles()
        
        self.dirty = True

        return particle


    @DisabledIfPackaged
    def deploy(self, strategy=None):
        if (strategy is None):
            strategy = DeploymentStrategy.strategies()[0]
        elif (isinstance(strategy, str)):
            strategy = DeploymentStrategy.by_name(strategy)
        
        strategy = strategy()

        (cells,
         psks,
         deployed_cells,
         address_range) = deploy_backbone(self, strategy)

        deploy_time = Timestamp.now()
        deployment = UvnDeployment(
                    strategy=strategy,
                    deploy_time=deploy_time,
                    address_range=address_range,
                    cells = cells,
                    deployed_cells=deployed_cells,
                    psks=psks,
                    registry=self)
        self.deployments.append(deployment)
        self.dirty = True
        return deployment
    
    def export(self,
               cell=None,
               drop_old_deployments=False,
               drop_stale_deployments=False,
               force=False,
               keep=False):
        if drop_old_deployments or drop_stale_deployments:
            self._drop_deployments(
                        keep_last=drop_old_deployments,
                        stale_only=drop_stale_deployments)
            latest_deployment_dir = self.paths.dir_deployment(
                deployment_id=UvnDefaults["registry"]["deployment_default"])
            if latest_deployment_dir.exists():
                latest_deployment_dir.unlink()

        outfile = self.paths.basedir / UvnDefaults["registry"]["persist_file"]

        def exportable(obj):
            return not obj.loaded or obj.dirty or force

        if exportable(self):
            logger.debug("exporting registry to {}", outfile)
            db_args = self.identity_db.get_export_args()
            yml(self, to_file=outfile, owner_cell=cell, **db_args)

            # Export particle packages
            for p in self.particles.values():
                pkg_dir = self.paths.dir_particles(p.name)
                self._export_particle_package(pkg_dir, particle=p, keep=keep)
        else:
            logger.debug("skipping exporting registry to {}", outfile)

        self.nameserver.export(force=force)

        for cell_name, cell in self.cells.items():
            if exportable(cell): # or exportable(self):
                pkg_dir = self.paths.dir_cell_bootstrap(cell.id.name)
                self._export_cell_package(pkg_dir,
                    cell=cell, keep=keep)

        for deployment in self.deployments:
            if exportable(deployment):
                deployment_dir = self.paths.dir_deployment(deployment.id)
                self._export_deployment_manifest(deployment, deployment_dir)
                for cell_cfg in deployment.deployed_cells:
                    pkg_dir = self.paths.dir_cell_pkg(
                                cell_cfg.cell.id.name,
                                deployment.id)
                    self._export_cell_package(pkg_dir,
                        cell_cfg=cell_cfg,
                        deployment=deployment,
                        keep=keep)
        
        if len(self.deployments) > 0 and not self.packaged:
            self._link_latest_deployment()

    def _export_deployment_manifest(self, deployment, deployment_dir):
        deployment_dir.mkdir(parents=True, exist_ok=True)
        deployment_manifest_file = deployment_dir / UvnDefaults["registry"]["deployment_file"]
        db_args = self.identity_db.get_export_args()
        yml(deployment, to_file=deployment_manifest_file, **db_args)
        # Generate a human-readable summary
        report_file = deployment_dir / UvnDefaults["registry"]["deployment_report"]
        deployment_summary = UvnDeploymentSummary(self, deployment)
        render(deployment_summary, "human", to_file=report_file)
        logger.activity("generated deployment summary: {}", report_file)

    def _export_cell_package(self, pkg_dir,
            cell=None, cell_cfg=None, deployment=None, keep=False):
        
        # Check if we are generating a "bootstrap" or a "deployment" package
        bootstrap = cell_cfg is None or deployment is None

        if cell_cfg is not None and deployment is None:
            raise UvnException("no deployment with cell_cfg: {}", cell_cfg.cell.id.name)

        if not bootstrap:
            cell = cell_cfg.cell
            deployment_id = deployment.id
            archive_out_dir = self.paths.dir_deployment(deployment_id) / UvnDefaults["registry"]["deployment_packages"]
        else:
            deployment_id = UvnDefaults["registry"]["deployment_bootstrap"]
            archive_out_dir = self.paths.dir_cell_bootstrap() / UvnDefaults["registry"]["deployment_packages"]

        logger.debug("Generating package for cell {} in {}", cell.id.name, pkg_dir)

        pkg_dir.mkdir(parents=True, exist_ok=True)

        db_args = self.identity_db.get_export_args()
        
        # Serialize cell manifest
        cell_manifest = pkg_dir / UvnDefaults["registry"]["cell_file"]
        yml(cell, to_file=cell_manifest, **db_args)
        
        # Serialize registry manifest
        registry_manifest = pkg_dir / UvnDefaults["registry"]["persist_file"]
        yml(self, to_file=registry_manifest,
            target_cell=cell,
            deployed_cell=cell_cfg,
            deployment_id=deployment_id,
            **db_args)

        # Serialize nameserver database
        ns_db = pkg_dir / UvnDefaults["nameserver"]["persist_file"]
        yml(self.nameserver, to_file=ns_db, **db_args)
        db_export_args = {
            "tgt_cell": cell
        }

        # Serialize identity database
        (db_dir,
        db_manifest,
        cell_secret) = self.identity_db.export_cell(
            self, pkg_dir=pkg_dir, **db_export_args)
        
        if not bootstrap:
            # Serialize deployment
            deployment_manifest = self.paths.dir_deployment(
                deployment_id=deployment.id,
                basedir=pkg_dir) / UvnDefaults["registry"]["deployment_file"]
            yml(deployment,
                to_file=deployment_manifest,
                tgt_cell_cfg=cell_cfg,
                deployment_id=deployment.id,
                **db_args)
        
        # Create package archive
        archive_path = self._zip_cell_pkg(
                        deployment_id=deployment_id,
                        cell_name=cell.id.name,
                        cell_pkg_dir=pkg_dir,
                        archive_out_dir=archive_out_dir)
        
        # Encrypt archive
        encrypt_result = self._encrypt_file_for_cell(cell.id.name, archive_path)

        if not keep:
            # Delete unencrypted archive
            archive_path.unlink()
            # Delete staging directory
            try:
                # For some reason, this call succeeds on x86_64, but fails
                # on RPi with error: "No such file or directory: 'S.gpg-agent.ssh'"
                shutil.rmtree(str(pkg_dir))
            except Exception as e:
                logger.exception(e)
                logger.warning("failed to remove build directory: {}", pkg_dir)
        else:
            logger.warning("[tmp] not deleted: {}", archive_path)
            logger.warning("[tmp] not deleted: {}", pkg_dir)

        cell_record = self.identity_db.get_cell_record(cell.id.name)
        if not cell_record:
            raise UvnException(f"cell record not found in db: {cell.id.address}")
        
        installer = UvnCellInstaller(
                        uvn_admin=self.identity_db.registry_id.admin,
                        uvn_address=self.identity_db.registry_id.address,
                        uvn_deployment=deployment_id,
                        cell_name=cell.id.name,
                        cell_address=cell.id.address,
                        cell_admin=cell.id.admin,
                        uvn_public_key=self.identity_db.registry_id.key.public,
                        cell_public_key=cell_record.key.public,
                        cell_private_key=cell_record.key.private,
                        cell_secret=self.identity_db._secret_cell(
                                        cell.id.name, cell.id.admin),
                        cell_pkg=str(encrypt_result["output"]),
                        cell_sig=str(encrypt_result["signature"]))
        
        basedir = self.paths.basedir / UvnDefaults["registry"]["installers_dir"]
        installer.export(basedir=basedir, keep=keep)

    def _export_particle_package(self, pkg_dir, particle, keep=False):

        logger.debug("Generating package for particle {} in {}", particle.name, pkg_dir)

        # Generate WireGuard configurations for every cell
        particle.render(pkg_dir)

        # Create package archive
        archive_path = self._zip_particle_pkg(
                        particle_name=particle.name,
                        particle_pkg_dir=pkg_dir,
                        archive_out_dir=self.paths.dir_particles())
        
        if not keep:
            # Delete staging directory
            shutil.rmtree(str(pkg_dir))
        else:
            logger.warning("[tmp] not deleted: {}", pkg_dir)

    def _list_deployment_installers(self, deployment, with_dirs=False):
        path_glob = self.paths.basedir / UvnDefaults["registry"]["installers_dir"]
        path_glob = path_glob / "".join([
            UvnDefaults["cell"]["pkg"]["installer"]["filename_fmt"].format(
                self.identity_db.registry_id.address,
                deployment.id,
                "*",
                UvnDefaults["cell"]["pkg"]["clear_format"]),
            UvnDefaults["cell"]["pkg"]["ext_clear"]
        ])
        installers = glob.glob(str(path_glob))
        if with_dirs:
            path_glob = path_glob.with_name(
                UvnDefaults["cell"]["pkg"]["installer"]["filename_fmt"].format(
                    self.identity_db.registry_id.address,
                    deployment.id,
                    "*"))
            installers.extend(
                [i for i in glob.glob(str(path_glob)) if i not in installers])
        return installers

    def _link_latest_deployment(self):
        latest_deployment_dir = self.paths.dir_deployment(
            deployment_id=UvnDefaults["registry"]["deployment_default"])
        deployment = self.latest_deployment
        deployment_dir=self.paths.dir_deployment(deployment.id)
        logger.debug("[ln] {} -> {}", latest_deployment_dir, deployment_dir.name)
        if latest_deployment_dir.is_symlink() or latest_deployment_dir.exists():
            latest_deployment_dir.unlink()
        latest_deployment_dir.symlink_to(deployment_dir.name)
        
        # List installers for this deployment and create symlinks for them
        installers = self._list_deployment_installers(deployment)

        if not installers:
            logger.warning("no installers found for deployment {} in {}",
                deployment.id, path_glob)

        for i in installers:
            i_path = pathlib.Path(i)
            cell_name = str(i_path.stem).split("-")[-1]
            latest_path = self.paths.basedir / UvnDefaults["registry"]["installers_dir"] / "".join([
                UvnDefaults["cell"]["pkg"]["installer"]["filename_fmt"].format(
                    self.identity_db.registry_id.address,
                    UvnDefaults["registry"]["deployment_default"],
                    cell_name),
                UvnDefaults["cell"]["pkg"]["ext_clear"]
            ])
            if latest_path.is_symlink() or latest_path.exists():
                latest_path.unlink()
            logger.debug("[ln] {} -> {}", latest_path, i_path.name)
            latest_path.symlink_to(i_path.name)

    def _zip_cell_pkg(self,
            cell_name,
            cell_pkg_dir,
            deployment_id,
            archive_out_dir,
            archive_ext=UvnDefaults["cell"]["pkg"]["ext"]):
        archive_name = "{}".format(cell_name)
        archive_path = archive_out_dir / archive_name
        archive_path_full = pathlib.Path(str(archive_path) + archive_ext)
        archive_path_zip = pathlib.Path(str(archive_path) + UvnDefaults["cell"]["pkg"]["ext_clear"])
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.make_archive(
            str(archive_path),
            UvnDefaults["cell"]["pkg"]["clear_format"],
            root_dir=cell_pkg_dir)
        archive_path_zip.rename(archive_path_full)
        logger.debug("generated cell archive: {} -> {}",
                        cell_name, archive_path_full)
        return archive_path_full

    def _zip_particle_pkg(self,
            particle_name,
            particle_pkg_dir,
            archive_out_dir):
        archive_name = "uvn-{}-{}".format(self.address, particle_name)
        archive_path = archive_out_dir / archive_name
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.make_archive(
            str(archive_path),
            UvnDefaults["cell"]["pkg"]["clear_format"],
            root_dir=particle_pkg_dir)
        archive_path_full = "{}.{}".format(
            archive_path,
            UvnDefaults["cell"]["pkg"]["clear_format"])
        logger.debug("generated particle archive: {} -> {}",
                        particle_name, archive_path_full)
        return archive_path_full
        
    def _encrypt_file_for_cell(self, cell_name, archive_path):
        # Get cell record
        cell_record = self.identity_db.get_cell_record(cell_name);

        encrypt_result = UvnIdentityDatabase.encrypt_file(
                            "cell package",
                            archive_path,
                            gpg=self.identity_db.gpg,
                            key=cell_record.key.fingerprint,
                            sign_key=self.identity_db.registry_id.key.fingerprint,
                            passphrase=self.identity_db._secret(
                                            required=True,
                                            admin=self.identity_db.registry_id.admin))
        
        logger.debug("Encrypted package for {}: {} [{}]",
                        cell_name,
                        encrypt_result["output"],
                        encrypt_result["signature"])
        
        return encrypt_result
    
    def get_cell_deployment_config(self, deployment_id, cell_name, **kwargs):
        for d in self.deployments:
            if d.id != deployment_id:
                continue
            cell_cfgs = [c for c in d.deployed_cells
                            if c.cell.id.name == cell_name]
            return next(iter(cell_cfgs))
        if "default" in kwargs:
            return kwargs["default"]
        raise StopIteration("cell deployment not found")

    def _load_deployment(self, deployment_id, store=True, deployment_dir=None):
        if (deployment_dir is None):
            deployment_dir=self.paths.dir_deployment(deployment_id)
        deployment_manifest_file = deployment_dir / UvnDefaults["registry"]["deployment_file"]
        db_args = UvnIdentityDatabase.get_load_args(identity_db=self.identity_db)
        deployment = yml_obj(UvnDeployment,
                        deployment_manifest_file,
                        from_file=True,
                        registry=self,
                        **db_args)
        if (deployment.id != deployment_id):
            raise UvnException(f"Invalid deployment loaded: {deployment.id}, expected {deployment_id}")
        if (store):
            self.deployments.append(deployment)
        
        return deployment
    
    @DisabledIfPackaged
    def _drop_deployments(self,
                          stale_only=False,
                          keep_last=False):
        deployments = self.deployments
        if keep_last:
            deployments = deployments[:-1]
        if stale_only:
            deployments = filter(lambda d: d.is_stale(), deployments)
        deployments = list(deployments)

        for d in deployments:
            deployment_dir=self.paths.dir_deployment(d.id)
            shutil.rmtree(str(deployment_dir))
            installers = self._list_deployment_installers(d, with_dirs=True)
            for i in installers:
                i = pathlib.Path(i)
                if i.is_dir():
                    shutil.rmtree(i)
                else:
                    i.unlink()
            self.deployments.remove(d)
        
        self.dirty = True
        return deployments
    
    @DisabledIfPackaged
    def _drop_cells(self):
        self._drop_deployments()
        self.cells = {}
    
    
    def _generate_vpn_config_cell_to_cell(
            self,
            cell_cfg,
            cell_port_i,
            deployed_cells,
            server_connections):
        port = cell_cfg.peers[cell_port_i]
        port_cfg = next(iter([c for c in deployed_cells if c.cell == port.cell]))
        keymat = cell_cfg.cell.id.keymat[cell_port_i]
        peer_keymat = port.cell.id.keymat[port.port_id]

        backbone_connection_cfg = None
        
        def check_candidate(net_i):
            return (net_i not in cell_cfg.allocated_ports.values() and
                    net_i not in port_cfg.allocated_ports.values())

        if cell_cfg.deploy_id in port_cfg.allocated_ports:
            net_cell_n = port_cfg.allocated_ports[cell_cfg.deploy_id]["net"]
            port_backbone_connection_cfg = port_cfg._find_backbone_connection(net_cell_n)
            port.port_id = port_backbone_connection_cfg.port_i
            peer_keymat = port.cell.id.keymat[port.port_id]
        elif check_candidate(cell_cfg.deploy_id):
            net_cell_n = cell_cfg.deploy_id
        elif check_candidate(port.deploy_id):
            net_cell_n = port.deploy_id
        else:
            if cell_cfg.deploy_id < port.deploy_id:
                backbone_connection_cfg = server_connections[cell_cfg.deploy_id]
                net_cell_n = cell_cfg.deploy_id
            else:
                backbone_connection_cfg = server_connections[port.deploy_id]
                net_cell_n = port.deploy_id
                port.port_id = 0
                peer_keymat = port.cell.id.keymat[port.port_id]

        cell_cfg.allocated_ports[port_cfg.deploy_id] = {
            "port_id": cell_port_i,
            "net": net_cell_n
        }
        if cell_cfg.deploy_id not in port_cfg.allocated_ports:
            port_cfg.allocated_ports[cell_cfg.deploy_id] = {
                "port_id": port.port_id,
                "net": net_cell_n
            }
        
        net_local = (net_cell_n == cell_cfg.deploy_id)
        new_connection = backbone_connection_cfg is None

        if net_local and new_connection and cell_port_i > 0:
            backbone_connection_cfg = server_connections[cell_cfg.deploy_id]
            new_connection = False

        peer_addr = WireGuardConfig._ip_addr_cell_to_cell(
                        port.deploy_id + 1, net_cell_n + 1)

        psk = cell_cfg.psks.get_psk(cell_cfg.deploy_id, port.deploy_id)

        if new_connection:
            (net_ip,
             netmask_size,
             hostmask_size) = WireGuardConfig._ip_net_cell_to_cell_addr(net_cell_n + 1)

            cell_addr = WireGuardConfig._ip_addr_cell_to_cell(
                            cell_cfg.deploy_id + 1, net_cell_n + 1)

            backbone_connection_cfg = CellDeployment.BackboneConnection(
                cell_name=cell_cfg.cell.id.name,
                interface=UvnDefaults["registry"]["vpn"]["backbone"]["interface"].format(cell_port_i),
                cell_pubkey=keymat.pubkey,
                cell_privkey=keymat.privkey,
                net_cell_n=net_cell_n,
                port_i=cell_port_i,
                port_local=cell_cfg.cell.peer_ports[cell_port_i],
                addr_local=cell_addr,
                network_local=net_local,
                network=net_ip,
                network_mask=netmask_size)
        
        backbone_connection_cfg.add_peer(
            psk=psk,
            name=port.cell.id.name,
            pubkey=peer_keymat.pubkey,
            addr_remote=str(peer_addr),
            endpoint=":".join(map(str,port.endpoint())),
            peer_i=port.port_id)

        if new_connection:
            return backbone_connection_cfg
        else:
            return None

    def _generate_vpn_config_cell_to_registry(self, cell):
        cell_ip = WireGuardConfig._ip_addr_cell_to_registry(cell.id.n)
        allowed_ips = str(WireGuardConfig._ip_net_cell_to_registry)
        vpn_cfg = Cell.RegistryConnection(
                    # interface=UvnDefaults["registry"]["vpn"]["registry"]["interface"].format(cell.id.n),
                    interface=UvnDefaults["registry"]["vpn"]["registry"]["interface"].format(0),
                    allowed_ips=allowed_ips,
                    cell_ip=cell_ip,
                    registry_pubkey=self.keymat.pubkey,
                    psk=cell.registry_psk,
                    cell_privkey=cell.id.keymat.registry.privkey,
                    registry_endpoint=self.identity_db.registry_id.address,
                    registry_address=WireGuardConfig._ip_addr_registry(),
                    registry_port=self.ports[0])
        return vpn_cfg
    
    def _generate_vpn_config_registry(self):
        peers=[UvnRegistry.RegistryVpnPeer(
                    cell_name=c.id.name,
                    cell_ip=c.registry_vpn.cell_ip,
                    cell_pubkey=c.id.keymat.registry.pubkey,
                    cell_psk=c.registry_psk)
                for c in self.cells.values()]

        vpn_cfg = UvnRegistry.RegistryVpn(
                        interface=UvnDefaults["registry"]["vpn"]["registry"]["interface"].format(0),
                        registry_address=WireGuardConfig._ip_addr_registry(),
                        registry_endpoint=self.identity_db.registry_id.address,
                        registry_port=self.ports[0],
                        registry_pubkey=self.keymat.pubkey,
                        registry_privkey=self.keymat.privkey,
                        peers=peers)
        return vpn_cfg

    def _generate_vpn_config(self):
        for c in filter(lambda c: not c.registry_vpn, self.cells.values()):
            logger.debug("generating VPN configuration for {}", c.id.name)
            c.registry_vpn = self._generate_vpn_config_cell_to_registry(c)
        self.vpn_config = self._generate_vpn_config_registry()

    def _generate_router_ports(self):
        for c in filter(lambda c: not c.router_port, self.cells.values()):
            logger.debug("generating router port for {}", c.id.name)
            c.router_port = self.router_ports.assert_cell(c)
    
    def _generate_particles(self):
        for p in self.particles.values():
            p.clear()
            for c in self.cells.values():
                p.generate_config(self, c)
    
    def _register_particles(self, cell):
        for p in self.particles.values():
            cfg = p.generate_config(self, cell)
            cell.particles_vpn.add_particle(
                name=p.name,
                address=cfg.address,
                pubkey=p.keymat.pubkey,
                psk=cfg.cell_psk)
    
    @staticmethod
    def load(identity_db):
        args = UvnIdentityDatabase.get_load_args(identity_db=identity_db)
        registry_file = args["basedir"] / UvnDefaults["registry"]["persist_file"]
        nameserver = UvnNameserver.load(identity_db=identity_db)
        return yml_obj(UvnRegistry,
                    registry_file,
                    from_file=True,
                    identity_db=identity_db,
                    nameserver=nameserver,
                    **args)
    
    @staticmethod
    def contains_uvn(dir_uvn):
        uvn_file_path = dir_uvn / UvnDefaults["registry"]["persist_file"]
        return uvn_file_path.exists()
    
    def reload(self):
        logger.info("reloading uvn registry from {}", self.paths.basedir)
        identity_db = UvnIdentityDatabase.load(self.paths.basedir)
        return UvnRegistry.load(identity_db)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            target_cell = kwargs.get("target_cell")
            deployed_cell = kwargs.get("deployed_cell")
            if deployed_cell is None:
                deployed_cell = py_repr.pkg_cell
            public_only = (kwargs.get("public_only") or
                deployed_cell is not None or target_cell is not None)
            
            if public_only:
                if deployed_cell is not None:
                    if isinstance(deployed_cell, str):
                        pkg_cell = deployed_cell
                    else:
                        pkg_cell = deployed_cell.cell.id.name
                elif target_cell is not None:
                    pkg_cell = target_cell.id.name
                else:
                    pkg_cell = "<some-unknown-cell>"
            else:
                pkg_cell = None
            
            if deployed_cell is not None:
                deployment_id = kwargs["deployment_id"]
                deployments = [deployment_id]
            elif target_cell is not None:
                deployment_id = kwargs["deployment_id"]
                deployments = []
            else:
                deployment_id = None
                deployments = [d.id for d in py_repr.deployments]
            
            kwargs["public_only"] = public_only
            kwargs["pkg_cell"] = pkg_cell

            yml_repr = dict()
            yml_repr["ports"] = py_repr.ports
            yml_repr["cells"] = [repr_yml(c, **kwargs) 
                                    for c in py_repr.cells.values()]
            yml_repr["particles"] = [repr_yml(p, **kwargs)
                                    for p in py_repr.particles.values()]
            # yml_repr["ns"] = repr_yml(py_repr.nameserver, **kwargs)
            yml_repr["keymat"] = repr_yml(py_repr.keymat, **kwargs)
            if py_repr.vpn_config is not None and not public_only:
                yml_repr["vpn_config"] = repr_yml(py_repr.vpn_config, **kwargs)
            yml_repr["router_ports"] = repr_yml(py_repr.router_ports, **kwargs)
            yml_repr["deployments"] = deployments
            if pkg_cell is not None:
                yml_repr["pkg_cell"] = pkg_cell
            if deployment_id is not None:
                yml_repr["deployment_id"] = deployment_id
                
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            identity_db = kwargs["identity_db"]
            nameserver = kwargs["nameserver"]
            deployments = kwargs.get("deployments")
            cells = {c["id"]["name"]: repr_py(Cell, c, **kwargs)
                        for c in yml_repr["cells"]}
            particles = {p["name"]: repr_py(Particle, p, **kwargs)
                        for p in yml_repr["particles"]}
            keymat = repr_py(WireGuardKeyPair, yml_repr["keymat"], **kwargs)
            
            if "vpn_config" in yml_repr:
                vpn_config = repr_py(UvnRegistry.RegistryVpn,
                                yml_repr["vpn_config"], **kwargs)
            else:
                vpn_config = None
            
            if "router_ports" in yml_repr:
                router_ports = repr_py(RegistryRouterPorts,
                                yml_repr["router_ports"], **kwargs)
            else:
                router_ports = None

            py_repr = UvnRegistry(
                        identity_db=identity_db,
                        cells=cells,
                        particles=particles,
                        keymat=keymat,
                        ports=yml_repr["ports"],
                        loaded=True,
                        pkg_cell=yml_repr.get("pkg_cell", None),
                        deployment_id=yml_repr.get("deployment_id", None),
                        vpn_config=vpn_config,
                        nameserver=nameserver,
                        router_ports=router_ports)

            # Register cells with identity_db
            for c in py_repr.cells.values():
                with_secret = (py_repr.packaged and c.id.name == py_repr.pkg_cell)
                py_repr.identity_db.register_cell(
                    name=c.id.name,
                    address=c.id.address,
                    admin=c.id.admin,
                    admin_name=c.id.admin_name,
                    with_secret=with_secret)
            
            deployment_loaded = False

            if ("deployments" in yml_repr):
                for d in yml_repr["deployments"]:
                    if (deployments is not None and d in deployments):
                        py_repr.deployments.append(deployments[d])
                        continue
                    
                    try:
                        py_repr._load_deployment(deployment_id=d)
                        if d == py_repr.deployment_id:
                            deployment_loaded = True
                    except Exception as e:
                        # traceback.print_exc()
                        logger.exception(e)
                        logger.warning(
                            "failed to load deployment {}: {}", d, e)

            if not py_repr.packaged:
                # Generate particle configurations
                py_repr._generate_particles()
            else:
                if (py_repr.deployment_id != UvnDefaults["registry"]["deployment_bootstrap"] and
                    not deployment_loaded):
                    raise UvnException(f"required deployment not loaded: {py_repr.deployment_id}")
                try:
                    file_path = py_repr.paths.basedir / UvnDefaults["registry"]["cell_file"]
                    db_args = UvnIdentityDatabase.get_load_args(identity_db=identity_db)
                    cell = yml_obj(Cell, file_path, from_file=True,
                                identity_db=identity_db, **db_args)
                    if cell.id.name != py_repr.pkg_cell:
                        raise UvnException(f"invalid UVN package: expected={py_repr.pkg_cell}, found={cell.id.name}")
                    py_repr.cells[cell.id.name] = cell
                    # Generate particle server
                    py_repr._register_particles(py_repr.deployed_cell)
                    # logger.activity("[loaded] UVN package for {} [{}]",
                    #     cell.id.name, py_repr.deployment_id)
                except Exception as e:
                    raise UvnException(f"failed to load UVN package for {py_repr.pkg_cell}: {e}")
            
            logger.activity("[{}]{} loaded UVN: {}",
                py_repr.pkg_cell if py_repr.packaged else "root",
                f"[{py_repr.deployment_id}]" if py_repr.packaged else "",
                py_repr.identity_db.registry_id.address)

            return py_repr
        
        def _file_format_out(self, yml_str, **kwargs):
            return UvnIdentityDatabase.sign_data(
                    "registry manifest", yml_str, **kwargs)

        def _file_format_in(self, yml_str, **kwargs):
            return UvnIdentityDatabase.verify_data(
                    "registry manifest", yml_str, **kwargs)

    class RegistryVpnPeer:

        def __init__(self,
                     cell_name,
                     cell_ip,
                     cell_pubkey,
                     cell_psk):
            self.cell_name = cell_name
            self.cell_ip = cell_ip
            self.cell_pubkey = cell_pubkey
            self.cell_psk = cell_psk

        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                return {
                    "cell_name": py_repr.cell_name,
                    "cell_ip": str(py_repr.cell_ip),
                    "cell_pubkey": py_repr.cell_pubkey,
                    "cell_psk": py_repr.cell_psk
                }
        
            def repr_py(self, yml_repr, **kwargs):
                return UvnRegistry.RegistryVpnPeer(
                            cell_name=yml_repr["cell_name"],
                            cell_ip=ipaddress.ip_address(yml_repr["cell_ip"]),
                            cell_pubkey=yml_repr["cell_pubkey"],
                            cell_psk=yml_repr["cell_psk"])

    
    @TemplateRepresentation("wireguard-cfg", "wg/registry.conf")
    class RegistryVpn:

        def __init__(self,
                     interface,
                     registry_address,
                     registry_endpoint,
                     registry_port,
                     registry_pubkey,
                     registry_privkey,
                     peers):
            self.interface = interface
            self.registry_address = registry_address
            self.registry_endpoint = registry_endpoint
            self.registry_port = registry_port
            self.registry_pubkey = registry_pubkey
            self.registry_privkey = registry_privkey
            self.peers = peers

        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                return {
                    "interface": py_repr.interface,
                    "registry_endpoint": py_repr.registry_endpoint,
                    "registry_address": str(py_repr.registry_address),
                    "registry_port": py_repr.registry_port,
                    "registry_pubkey": py_repr.registry_pubkey,
                    "registry_privkey": py_repr.registry_privkey,
                    "peers": [repr_yml(p, **kwargs) for p in py_repr.peers]
                }
        
            def repr_py(self, yml_repr, **kwargs):
                return UvnRegistry.RegistryVpn(
                            interface=yml_repr["interface"],
                            registry_endpoint=yml_repr["registry_endpoint"],
                            registry_address=ipaddress.ip_address(
                                                yml_repr["registry_address"]),
                            registry_port=yml_repr["registry_port"],
                            registry_pubkey=yml_repr["registry_pubkey"],
                            registry_privkey=yml_repr["registry_privkey"],
                            peers=[repr_py(UvnRegistry.RegistryVpnPeer, p, **kwargs)
                                    for p in yml_repr["peers"]])
