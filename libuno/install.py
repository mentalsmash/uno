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
import shutil
import tempfile
import docker

import libuno.log

from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.cfg import UvnDefaults
from libuno.identity import UvnIdentityDatabase
from libuno.exception import UvnException
from libuno.exec import exec_command

logger = libuno.log.logger("uvn.install")

class UvnCellInstaller:
    
    def __init__(self,
        uvn_admin,
        uvn_address,
        uvn_deployment,
        cell_name,
        cell_address,
        cell_admin,
        uvn_public_key=None,
        cell_public_key=None,
        cell_private_key=None,
        cell_secret=None,
        cell_pkg=None,
        cell_sig=None):
        self._bootstrap = uvn_deployment == UvnDefaults["registry"]["deployment_bootstrap"]
        self.uvn_admin = uvn_admin
        self.uvn_address = uvn_address
        self.uvn_public_key = uvn_public_key
        self.uvn_deployment = uvn_deployment
        self.cell_name = cell_name
        self.cell_address = cell_address
        self.cell_admin = cell_admin
        self.cell_public_key = cell_public_key
        self.cell_private_key = cell_private_key
        self.cell_secret = cell_secret
        self.cell_pkg = cell_pkg
        self.cell_sig = cell_sig

    def compute_hashes(self):
        pass

    @staticmethod
    def _manifest_file(installer_dir):
        return installer_dir / UvnDefaults["cell"]["pkg"]["installer"]["manifest"]

    @staticmethod
    def _installer_files(installer_dir, bootstrap=False):
        installer_dir = pathlib.Path(installer_dir)
        files = {
            "manifest": UvnCellInstaller._manifest_file(installer_dir),
            "cell_pkg": installer_dir / "".join([
                            UvnDefaults["cell"]["pkg"]["export_name"],
                            UvnDefaults["cell"]["pkg"]["ext"],
                            UvnDefaults["identity_db"]["ext_encrypted"]]),
            "cell_sig": installer_dir / "".join([
                            UvnDefaults["cell"]["pkg"]["export_name"],
                            UvnDefaults["cell"]["pkg"]["ext"],
                            UvnDefaults["identity_db"]["ext_signature"]]),
        }
        if bootstrap:
            files.update({
                "uvn_public_key": installer_dir / "".join([
                                    UvnDefaults["cell"]["pkg"]["root_key_file"],
                                    UvnDefaults["identity_db"]["ext_pubkey"]]),
                "cell_public_key": installer_dir / "".join([
                                    UvnDefaults["cell"]["pkg"]["key_file"],
                                    UvnDefaults["identity_db"]["ext_pubkey"]]),
                "cell_private_key": installer_dir / "".join([
                                    UvnDefaults["cell"]["pkg"]["key_file"],
                                    UvnDefaults["identity_db"]["ext_privkey"]]),
                "cell_secret": installer_dir / UvnDefaults["cell"]["pkg"]["secret_file"]
            })
        return files

    def export(self, basedir, keep=False):
        basedir = pathlib.Path(basedir)

        # Create directory for installer files
        installer_dir = basedir / UvnDefaults["cell"]["pkg"]["installer"]["filename_fmt"].format(
            self.uvn_address, self.uvn_deployment, self.cell_name)
        installer_dir.mkdir(parents=True, exist_ok=True)

        installer_files = UvnCellInstaller._installer_files(
            installer_dir, bootstrap=self._bootstrap)

        # Export installer manifest
        yml(self, to_file=installer_files["manifest"])

        # Copy cell's package
        shutil.copyfile(str(self.cell_pkg), installer_files["cell_pkg"])

        # Copy cell's package signature
        shutil.copyfile(str(self.cell_sig), installer_files["cell_sig"])

        if self._bootstrap:
            # Export uvn's public key
            with installer_files["uvn_public_key"].open("w") as output:
                output.write(self.uvn_public_key)

            # Export cells's public key
            with installer_files["cell_public_key"].open("w") as output:
                output.write(self.cell_public_key)

            # Export cells's private key
            with installer_files["cell_private_key"].open("w") as output:
                output.write(self.cell_private_key)

            # Export cells's secret
            with installer_files["cell_secret"].open("w") as output:
                output.write(self.cell_secret)

        shutil.make_archive(str(installer_dir),
            UvnDefaults["cell"]["pkg"]["clear_format"],
            root_dir=installer_dir)

        if not keep:
            shutil.rmtree(str(installer_dir))
        else:
            logger.warning("[tmp] not deleted: {}", installer_dir)
        
        installer = "".join([str(installer_dir), UvnDefaults["cell"]["pkg"]["ext_clear"]])
        installer = pathlib.Path(installer)
        logger.activity("generated installer: {}", installer.name)
    
    @staticmethod
    def bootstrap(package, install_prefix, keep=False):
        package = pathlib.Path(package)
        install_prefix = pathlib.Path(install_prefix).resolve()

        logger.activity("installing cell package: {}", package.name)
        # Create a temporary directory to extract the installer and bootstrap
        # the gpg database
        tmp_dir = tempfile.mkdtemp(prefix="{}-".format(package.stem))
        tmp_dir = pathlib.Path(tmp_dir)

        try:
            logger.debug("extracting {} to {}", package, tmp_dir)

            shutil.unpack_archive(str(package), extract_dir=str(tmp_dir),
                format=UvnDefaults["cell"]["pkg"]["clear_format"])

            # Load installer manifest
            manifest = UvnCellInstaller._manifest_file(tmp_dir)
            installer = yml_obj(UvnCellInstaller, manifest, from_file=True)
            
            logger.debug("loaded installer for cell {} of UVN {} [{}]",
                installer.cell_name, installer.uvn_address, installer.uvn_deployment)

            installer_files = UvnCellInstaller._installer_files(
                tmp_dir, bootstrap=installer._bootstrap)

            # Check that all files are there as expected
            missing_files = [str(f) for f in installer_files.values()
                                        if not f.exists()]
            if missing_files:
                raise UvnException("missing uvn installer files: [{}]".format(
                    ",".join(missing_files)))

            installer_dir = tmp_dir / UvnDefaults["cell"]["pkg"]["export_name"]

            if installer._bootstrap:
                logger.activity("bootstrap: {} -> {}", package.stem, install_prefix)
                bootstrap_dir = installer_dir
                registry = None
            else:
                # extract deployment package into target cell's dir
                logger.activity("deployment: {} -> {}", package.stem, install_prefix)
                bootstrap_dir = install_prefix
                identity_db = UvnIdentityDatabase.load(basedir=bootstrap_dir)
                from libuno.reg import UvnRegistry
                registry = UvnRegistry.load(identity_db)

            
            # Decrypt cell package and extract it
            UvnIdentityDatabase.bootstrap_cell(
                bootstrap_dir=bootstrap_dir,
                registry=registry,
                uvn_address=installer.uvn_address,
                uvn_admin=installer.uvn_admin,
                cell_name=installer.cell_name,
                cell_admin=installer.cell_admin,
                cell_pkg=installer_files["cell_pkg"],
                cell_sig=installer_files["cell_sig"],
                uvn_public_key=installer_files.get("uvn_public_key"),
                cell_public_key=installer_files.get("cell_public_key"),
                cell_private_key=installer_files.get("cell_private_key"),
                cell_secret=installer_files.get("cell_secret"),
                keep=keep)
            
            if installer._bootstrap:
                shutil.copytree(str(installer_dir), str(install_prefix))

        finally:
            if not keep:
                # Delete temporary directory
                shutil.rmtree(str(tmp_dir))
            else:
                logger.warning("[tmp] not deleted: {}", tmp_dir)

        logger.activity("installed package: {} -> {}", package.name, install_prefix)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["uvn"] = {
                "admin": py_repr.uvn_admin,
                "address": py_repr.uvn_address,
                "deployment": py_repr.uvn_deployment,
            }
            yml_repr["cell"] = {
                "name": py_repr.cell_name,
                "admin": py_repr.cell_admin,
                "address": py_repr.cell_address
            }
            return yml_repr

        def repr_py(self, yml_repr, **kwargs):
            py_repr = UvnCellInstaller(
                        uvn_admin=yml_repr["uvn"]["admin"],
                        uvn_address=yml_repr["uvn"]["address"],
                        uvn_deployment=yml_repr["uvn"]["deployment"],
                        cell_name=yml_repr["cell"]["name"],
                        cell_admin=yml_repr["cell"]["admin"],
                        cell_address=yml_repr["cell"]["address"],
                        uvn_public_key=kwargs.get("uvn_public_key"),
                        cell_public_key=kwargs.get("cell_public_key"),
                        cell_private_key=kwargs.get("cell_private_key"),
                        cell_secret=kwargs.get("cell_secret"),
                        cell_pkg=kwargs.get("cell_pkg"),
                        cell_sig=kwargs.get("cell_sig"))
            return py_repr
