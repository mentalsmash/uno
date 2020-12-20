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
import os
import sys
import subprocess
import platform

from libuno import data as StaticData
from libuno.cfg import UvnDefaults
from libuno.identity import UvnIdentityDatabase
from libuno.helpers import Timestamp
from libuno.exec import exec_command
from libuno.connext import NddshomeInfoDescriptor
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.tmplt import TemplateRepresentation, render

import libuno.log
logger = libuno.log.logger("uvn.docker")

@TemplateRepresentation("Dockerfile", "docker/Dockerfile")
class Dockerfile:
    def __init__(self, base_image, dev, ndds, rpi_extra):
        self.base_image = base_image
        self.dev = dev
        self.ndds = ndds
        self.rpi_extra = rpi_extra

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return {
                "base_image": py_repr.base_image,
                "dev": py_repr.dev,
                "ndds": py_repr.ndds,
                "rpi_extra": py_repr.rpi_extra
            }
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()


class DockerController:

    connext = NddshomeInfoDescriptor()

    def __init__(self, registry,
            socket=UvnDefaults["docker"]["socket"],
            dev=False):
        self.registry = registry
        self.socket = socket
        self.dev = dev

        logger.debug("connecting to docker: {}", self.socket)
        self.client = docker.DockerClient(base_url=self.socket)
        logger.activity("[connected] socket: {}", self.socket)

        (self.component,
         self.component_type,
         self.image_name,
         self.image_tag,
         self.image_labels,
         self.image_args,
         self.dockerfile,
         self.base_image_name,
         self.base_image_tag,
         self.base_image_labels,
         self.base_image_args,
         self.base_dockerfile,
         self.container_name,
         self.container_labels,
         self.container_volumes,
         self.container_arch) = DockerController._registry_metadata(self.registry, dev)

        # logger.activity("target: {} [{}]", self.component, self.component_type)
        # logger.activity("image: {}", self.image_name)
    
    @staticmethod
    def _registry_metadata(registry, dev=False):
        if registry.packaged:
            pkg_cell = registry.cell(registry.pkg_cell)
            component = pkg_cell.id.name
            component_type = "cell"
            image_tag = registry.deployment_id
            image_name = UvnDefaults["docker"]["image_name_fmt"]["cell"].format(registry.address, component)
            component_labels = {
                "uvn.cell.name": pkg_cell.id.name,
                "uvn.cell.address": pkg_cell.id.address,
                "uvn.cell.admin": pkg_cell.id.admin,
                "uvn.deployment": registry.deployment_id
            }
        else:
            component = registry.address
            component_type = "registry"
            image_tag = Timestamp.now().format()
            image_name = UvnDefaults["docker"]["image_name_fmt"]["root"].format(registry.address)
            component_labels = {
                "uvn.version": image_tag
            }

        image_labels = {
            "uvn.address": registry.address,
            "uvn.admin": registry.admin,
            "uvn.component": component_type
        }
        image_labels.update(component_labels)

        image_args = {}
        
        if dev:
            dockerfile_pfx = "-dev"
        else:
            dockerfile_pfx = ""

        dockerfile = f"{component_type}{dockerfile_pfx}.dockerfile"
        
        base_image_name = UvnDefaults["docker"]["base_image"]
        base_image_tag = libuno.__version__
        base_image_labels = {}
        base_image_args = image_args
        base_dockerfile = f"{base_image_name}{dockerfile_pfx}.dockerfile"

        container_name = image_name
        container_labels = image_labels
        container_volumes = {
            str(registry.paths.basedir) : {
                "bind": UvnDefaults["docker"]["volumes"]["uvn"],
                "mode": "rw"
            }
        }

        (os_system,
         os_node,
         os_release,
         os_version,
         container_arch,
         os_processor) = platform.uname()

        return (
            component,
            component_type,
            image_name,
            image_tag,
            image_labels,
            image_args,
            dockerfile,
            base_image_name,
            base_image_tag,
            base_image_labels,
            base_image_args,
            base_dockerfile,
            container_name,
            container_labels,
            container_volumes,
            container_arch
        )

    def build_runner(self,
            keep=False,
            drop_old=False,
            rebuild=False,
            rebuild_base=False,
            nocache=False,
            image_only=False,
            volumes=None,
            packages=None):
        logger.debug("building runner {} [{}]", self.component, self.component_type)

        # Create a temporary directory where to build the container
        tmp_dir = tempfile.mkdtemp(
            prefix="{}-".format(self.container_name),
            suffix="-context")
        tmp_dir = pathlib.Path(tmp_dir)

        try:
            base_image = DockerController._get_existing_image(
                            self.client, self.base_image_name,
                            delete_existing=rebuild)
            if base_image and (not self.dev or rebuild):
                logger.debug("rebuilding existing image: {}", base_image.tags[0])
            elif base_image and self.dev:
                logger.info("already built: {}", base_image.tags[0])
                return base_image

            # Initialize directory with build context for base image
            base_context_tar, extra_ctx_args = DockerController._initialize_runner_context(
                        tmp_dir=tmp_dir,
                        basedir=self.registry.paths.basedir,
                        dockerfile=self.base_dockerfile,
                        container_arch=self.container_arch,
                        connext_helper=self.connext,
                        keep=keep,
                        copy_uno=True,
                        dev=self.dev)
            
            # Initialize directory with build context
            context_tar = None
            # context_tar = DockerController._initialize_runner_context(
            #             tmp_dir=tmp_dir,
            #             basedir=self.registry.paths.basedir,
            #             dockerfile=self.dockerfile,
            #             keep=keep,
            #             copy_uno=True)

            image_args = dict(self.image_args)
            if packages:
                image_args["APT_EXTRAS"] = " ".join(packages)
            image_args.update(extra_ctx_args)
            
            base_image_args = dict(self.base_image_args)
            if packages:
                base_image_args["APT_EXTRAS"] = " ".join(packages)
            base_image_args.update(extra_ctx_args)
            
            image = DockerController._build_runner_image(
                        client=self.client,
                        component=self.component,
                        component_type=self.component_type,
                        image_name=self.image_name,
                        image_context=context_tar,
                        image_tag=self.image_tag,
                        image_labels=self.image_labels,
                        image_args=image_args,
                        dockerfile=self.dockerfile,
                        base_image_name=self.base_image_name,
                        base_image_tag=self.base_image_tag,
                        base_image_labels=self.base_image_labels,
                        base_image_args=base_image_args,
                        base_image_context=base_context_tar,
                        base_dockerfile=self.base_dockerfile,
                        keep=keep,
                        drop_old=drop_old,
                        rebuild=rebuild,
                        rebuild_base=rebuild_base,
                        nocache=nocache,
                        dev=self.dev)
            
            if not image_only:
                if volumes and len(volumes) > 0:
                    container_volumes = list(self._args.volume)
                    container_volumes.extend(volumes)
                container = DockerController._build_runner_container(
                            client=self.client,
                            container_name=self.container_name,
                            image_name=self.base_image_name,
                            container_labels=self.container_labels,
                            container_volumes=volumes)
            
            logger.debug("runner image: {}", image.attrs)
        finally:
            if not keep:
                shutil.rmtree(str(tmp_dir))
            else:
                logger.warning("[tmp] not deleted: {}", tmp_dir)
        
        # logger.activity("[built] runner {} [{}]", self.component, self.component_type)

    @staticmethod
    def _get_existing_image(client, image_name, delete_existing=False):
        try:
            image = client.images.get(image_name)
            logger.debug("image found: {}", image.tags[0])
            if not delete_existing:
                logger.debug("[exists] {}", image_name)
                return image
            client.images.remove(image.tags[0], force=True)
            logger.activity("deleted existing image: {}", image.tags[0])
            return None
        except docker.errors.ImageNotFound as e:
            # Image doesn't exist
            return None
        except Exception as e:
            logger.exception(e)
            raise e

    @staticmethod
    def _get_existing_container(client, container_name, delete_existing=False):
        try:
            container = client.containers.get(container_name)
            logger.debug("container found: {}", container_name)
            if not delete_existing:
                logger.activity("[exists] {}", container_name)
                return base_image
            container.remove(force=True)
            logger.debug("deleted existing container: {}", container_name)
            return None
        except docker.errors.NotFound as e:
            # Container doesn't exist
            return None
        except Exception as e:
            logger.exception(e)
            raise e
    
    @staticmethod
    def _parse_build_image_logs(build_logs):
        lines = []
        image_hash = None

        for l in build_logs:
            if "stream" in l:
                lines.append(l["stream"])
            if "aux" in l and "ID" in l["aux"]:
                image_hash = l["aux"]["ID"]
        
        if not image_hash:
            raise ValueError("image hash not found")

        return image_hash, lines

    @staticmethod
    def _build_dockerfile(client, image_name, dockerfile, **kwargs):
        logger.activity("[building] image {} from {}", image_name, dockerfile)
        # Open stream for dockerfile
        dockerfile_stream = StaticData.dockerfile(dockerfile)
        (image,
        build_logs) = client.images.build(fileobj=dockerfile_stream, **kwargs)
        image_hash, output = DockerController._parse_build_image_logs(build_logs)
        logger.trace("build log: \n{}", "".join(output))
        logger.activity("[built] {} [{}]", image_name, image_hash)
        return image, image_hash
    
    @staticmethod
    def _build_dockerfile_w_context(client, image_name, context, **kwargs):
        logger.activity("[build] image {} from {}", image_name, context)
        # Open stream for context
        context = pathlib.Path(context)
        with context.open("rb") as context_stream:
            (image,
            build_logs) = client.images.build(
                fileobj=context_stream, custom_context=True, **kwargs)
            image_hash, output = DockerController._parse_build_image_logs(build_logs)
            logger.trace("build log: \n{}", "".join(output))
            logger.activity("[built] {} [{}]", image_name, image_hash)
            return image, image_hash

    @staticmethod
    def _build_runner_image_base(client,
            image_name, image_labels, image_args,
            image_tag=None,
            dockerfile=None,
            image_context=None,
            rebuild=False,
            nocache=False,
            dev=False):
        
        # base_image = DockerController._get_existing_image(
        #                 client, image_name, delete_existing=rebuild)
        # if base_image and (not dev or rebuild):
        #     logger.debug("rebuilding existing image: {}", base_image.tags[0])
        # elif base_image and dev:
        #     logger.info("already built: {}", base_image.tags[0])
        #     return base_image
        
        if image_tag is not None:
            build_tag = "{}:{}".format(image_name, image_tag)
        else:
            build_tag = image_name

        if image_context is not None:
            base_image, image_hash = DockerController._build_dockerfile_w_context(
                                        client,
                                        build_tag,
                                        image_context,
                                        tag=image_name,
                                        buildargs=image_args,
                                        # TODO re-enable labels after refactoring them
                                        # to be generic (and not uvn-specific)
                                        # labels=image_labels,
                                        nocache=nocache)
        elif dockerfile is not None:
            base_image, image_hash = DockerController._build_dockerfile(client,
                                        image_name,
                                        dockerfile,
                                        tag=build_tag,
                                        buildargs=image_args,
                                        # labels=image_labels,
                                        nocache=nocache)
        else:
            raise ValueError("one of image_context or dockerfile must be specified")
    
        return base_image
    
    @staticmethod
    def _clone_uno(tmp_dir, keep=False, dev=True):
        # Clone the "uno" git repository
        repo_dir = tmp_dir / UvnDefaults["docker"]["context"]["repo_dir"]
        repo_dir_clone = repo_dir.with_name("{}.tmp".format(repo_dir.name))

        repo_url = UvnDefaults["docker"]["context"]["repo_url_fmt"].format(
            UvnDefaults["docker"]["context"]["repo_proto"],
            os.environ.get(UvnDefaults["docker"]["env"]["oauth_token"]),
            UvnDefaults["docker"]["context"]["repo_url_base"])
        
        repo_branch = UvnDefaults["docker"]["context"]["repo_branch"]
        
        if not dev:
            logger.debug("clone git repo {} to {}", repo_url, repo_dir_clone)
            exec_command([
                "git", "clone", "-b", repo_branch, repo_url, repo_dir_clone],
                fail_msg="failed to clone git repository: {}".format(repo_url))
        
            # Create an archived copy
            logger.debug("archive git repo to {}", repo_dir)
            repo_tar = repo_dir.with_name("{}.tar".format(repo_dir.name))
            exec_command([
                "git", "archive", repo_branch, "--format", "tar", "-o", repo_tar],
                cwd=repo_dir_clone,
                fail_msg="failed to archive git repository: {}".format(repo_tar))
    
            repo_dir.mkdir(parents=True, exist_ok=True)
            exec_command([
                "tar", "xvf", repo_tar, "-C", repo_dir],
                fail_msg="failed to extract repository: {}".format(repo_dir))
        else:
            # Copy uno from this current copy
            import libuno
            uno_path = pathlib.Path(libuno.__file__).parent.parent
            logger.debug("copying uno from {}", uno_path)
            shutil.copytree(str(uno_path), str(repo_dir),
                ignore=DockerController.filter_uvn_files)
        
        # Delete clone directory and tar file
        if not keep and not dev:
            repo_tar.unlink()
            shutil.rmtree(str(repo_dir_clone))
        return repo_dir
    
    @staticmethod
    def filter_uvn_files(dir_name, dir_content):
        ignored = []
        if "S.gpg-agent" in dir_content:
            ignored.append("S.gpg-agent")
        return ignored

    @staticmethod
    def _clone_uvn(tmp_dir, basedir, keep=False):
        # Copy the uvn root
        uvn_dir = tmp_dir / UvnDefaults["docker"]["context"]["uvn_dir"]
        logger.debug("[copy] {} -> {}", basedir, uvn_dir)
        shutil.copytree(str(basedir), str(uvn_dir), ignore=DockerController.filter_uvn_files)
        return uvn_dir

    @staticmethod
    def _initialize_runner_context(
            tmp_dir,
            basedir,
            dockerfile,
            container_arch,
            connext_helper,
            keep=False,
            copy_uno=False,
            copy_uvn=False,
            build_wheel=False,
            dev=False,
            connext=False):
        logger.activity("[context] initializing: {}", tmp_dir)
        context_data = []
        extra_args = {}

        if copy_uno and not dev:
            repo_dir = DockerController._clone_uno(tmp_dir, keep=keep, dev=dev)
            context_data.append(repo_dir.name)

        if copy_uvn:
            uvn_dir = DockerController._clone_uvn(tmp_dir, basedir,
                keep=keep)
            context_data.append(uvn_dir.name)
        
        # Retrieve a pre-built wheel file to install connextdds-py
        connextdds_wheel = None
        if not build_wheel:
            try:
                connextdds_wheel = StaticData.connextdds_wheel(container_arch)
            except Exception as e:
                logger.warning("no prebuilt connextdds-py wheel found for architecture {}")
        if not connextdds_wheel or build_wheel:
            connextdds_wheel = connext_helper.py.build(container_arch)
        dds_whl_path = tmp_dir / connextdds_wheel.name
        connextdds_wheel.copy_to(dds_whl_path)
        context_data.append(dds_whl_path.name)
        extra_args["CONNEXTDDS_WHEEL"] = connextdds_wheel.name

        if connext:
            # Copy Connext DDS libraries and routing service
            dds_path = tmp_dir / UvnDefaults["dds"]["home"]
            connextdds_arc = UvnDefaults["dds"]["connext"]["arch"][container_arch]
            connext_helper.copy_to(dds_path, archs=[connextdds_arc])
            context_data.append(dds_path.name)
        
        # Instantiate Dockerfile
        dockerfile_path = tmp_dir / "Dockerfile"
        base_image = None
        if container_arch == "x86_64":
            if sys.version_info.minor == 6:
                base_image = "ubuntu:18.04"
            elif sys.version_info.minor == 8:
                base_image = "ubuntu:20.04"
        elif container_arch == "armv7l":
            if sys.version_info.minor == 7:
                base_image = "balenalib/raspberry-pi-debian:latest"
        else:
             raise ValueError(f"unsupported container architecture: {container_arch}")
        if not base_image:
            raise RuntimeError(f"Python 3.{sys.version_info.minor} not supported in {container_arch} uno containers yet")
        dockerfile_tmplt = Dockerfile(
            base_image=base_image,
            dev=dev,
            ndds=False,
            rpi_extra=container_arch == "armv7l")
        render(dockerfile_tmplt,"Dockerfile", to_file=dockerfile_path)
        context_data.append("Dockerfile")
        
        # Instantiate entrypoint script
        entrypoint_path = tmp_dir / "entrypoint.sh"
        with entrypoint_path.open("w") as output:
            entrypoint_stream = StaticData.script("entrypoint.sh", binary=False)
            shutil.copyfileobj(entrypoint_stream, output)
        context_data.append("entrypoint.sh")

        # Create a tar containing the custom build context
        context_tar = tmp_dir / UvnDefaults["docker"]["context"]["tar"]
        cmd_args = ["tar", "cvf", context_tar]
        cmd_args.extend(context_data)
        exec_command(cmd_args,
            cwd=tmp_dir,
            fail_msg="failed to archive build context: {}".format(context_tar))
        
        return context_tar, extra_args


    @staticmethod
    def _build_runner_image(
            client,
            component,
            component_type,
            image_name,
            image_context,
            dockerfile,
            base_image_name,
            base_dockerfile,
            # Build only base image for now
            base_only=True,
            image_tag=None,
            image_labels={},
            image_args={},
            base_image_tag=None,
            base_image_labels={},
            base_image_args={},
            base_image_context=None,
            keep=False,
            drop_old=False,
            rebuild=False,
            rebuild_base=False,
            nocache=False,
            dev=False):

        # Build the runner's base image
        base_image = DockerController._build_runner_image_base(
                        client,
                        image_name=base_image_name,
                        image_tag=base_image_tag,
                        image_labels=base_image_labels,
                        image_args=base_image_args,
                        image_context=base_image_context,
                        dockerfile=base_dockerfile,
                        rebuild=rebuild_base,
                        nocache=nocache,
                        dev=dev)
        
        if base_only or dev:
            logger.debug("building only generic runner")
            return base_image

        # Drop existing images
        if drop_old:
            image_filters = [
                "uvn.component={}".format(component_type)
            ]
            if component_type == "cell":
                image_filters.append("uvn.cell.name={}".format(component))
            else:
                image_filters.append("uvn.address={}".format(component))
            existing_images = client.images.list(filters={"label": image_filters})
            for i in existing_images:
                if image_tag is not None and i.tags[0].endswith(image_tag):
                    continue
                client.images.remove(image=i.tags[0], force=True)
                logger.activity("deleted existing image: {}", i.tags[0])

        if image_tag is not None:
            build_tag = "{}:{}".format(image_name, image_tag)
        else:
            build_tag = image_name
        
        image = DockerController._get_existing_image(
                        client, build_tag, delete_existing=rebuild)
        if image:
            logger.debug("rebuilding existing image: {}", image.tags[0])
        
        # Normalize context to path
        image_context = pathlib.Path(image_context)

        image, image_hash = DockerController._build_dockerfile_w_context(client,
                                build_tag,
                                image_context,
                                tag=build_tag,
                                buildargs=image_args,
                                labels=image_labels,
                                nocache=nocache)

        return image
    
    @staticmethod
    def _build_runner_container(
        client,
        container_name,
        image_name,
        container_labels={},
        container_volumes={}):

        DockerController._get_existing_container(
            client, container_name, delete_existing=True)

        logger.debug("creating container: {} [{}]", container_name, image_name)

        container = client.containers.create(image_name,
                        hostname=container_name,
                        name=container_name,
                        labels=container_labels,
                        privileged=True,
                        volumes=container_volumes)

        # logger.activity("[built] {} [{}]", container_name, image_name)
        
        return container
