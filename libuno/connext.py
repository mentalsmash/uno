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
from sh import grep, cut
import sys
import os
import pathlib
import types
import shutil
import fnmatch
import functools
import glob
import tempfile
import multiprocessing

from libuno.cfg import UvnDefaults
from libuno.helpers import CachedOrGeneratedValuedDescriptor
from libuno.exec import exec_command

import libuno.log
logger = libuno.log.logger("uvn.connext")

def _nddshome_env(required=False):
    e_connextdds_dir = os.getenv("CONNEXTDDS_DIR", None)
    e_nddshome = os.getenv("NDDSHOME", None)
    if e_connextdds_dir:
        return pathlib.Path(e_connextdds_dir)
    elif e_nddshome:
        return pathlib.Path(e_nddshome)
    elif required:
        raise ValueError("NDDSHOME not set")

def get_nddshome(required=False):
    nddshome = _nddshome_env(required=required)
    if (not nddshome or not nddshome.exists()) and required:
        raise ValueError(f"required path not found: '{nddshome}'")
    logger.debug("NDDSHOME: {}", nddshome)
    return nddshome

def export_nddshome(path):
    os.environ["CONNEXTDDS_DIR"] = str(path)
    os.environ["NDDSHOME"] = str(path)


def copy_nddshome(nddshome, dst_dir, archs=[]):
    nddshome = pathlib.Path(nddshome)
    dst_dir = pathlib.Path(dst_dir)
    paths = [
        pathlib.Path("bin") / "rtiroutingservice",
        pathlib.Path("include"),
        pathlib.Path("resource") / "scripts",
        pathlib.Path("resource") / "template",
        pathlib.Path("rti_versions.xml")
    ]
    if archs:
        for a in archs:
            bin_a = UvnDefaults["dds"]["connext"]["bin_arch"].get(a, a)
            paths.extend([
                pathlib.Path("lib") / a,
                pathlib.Path("resource") / "app" / "lib" / bin_a,
                pathlib.Path("resource") / "app" / "bin" / bin_a / "rtiroutingservice"])
    else:
        paths.append(pathlib.Path("lib"))
        paths.append(pathlib.Path("resource") / "app" / "lib")
        paths.extend(glob.glob(str(
            pathlib.Path("resource") / "app" / "bin" / "*" / "rtiroutingservice")))
    
    for p in paths:
        p_in = nddshome / p
        p_out = dst_dir / p
        p_out.parent.mkdir(exist_ok=True, parents=True)
        if p_in.is_dir():
            shutil.copytree(str(p_in), str(p_out))
        else:
            shutil.copy2(str(p_in), str(p_out))


def build_connextddspy(nddshome, dst_dir, arch, keep=False):
    # Create a temporary directory for storing build files
    tmp_dir = tempfile.mkdtemp(
            prefix=f"connextdds-py-{nddshome.name}-",
            suffix="-context")
    tmp_dir = pathlib.Path(tmp_dir)
    nddsarch = UvnDefaults["dds"]["connext"]["arch"].get(container_arch)
    if not nddsarch:
        raise ValueError(f"unsupported architecture: {arch}")
    try:
        # Clone connextdds-py repository
        repo_url = UvnDefaults["dds"]["connext"]["py"]["git"]
        repo_dir = tmp_dir / "connextdds-py"
        exec_command([
            "git", "clone", repo_url, repo_dir],
            fail_msg="failed to clone git repository: {}".format(repo_url))
        
        # Run configure.py
        logger.warning("building connextdds-py wheel (this might take some time)")
        cpu_count = multiprocessing.cpu_count()
        exec_command([
            "python", "configure.py", "-j", str(cpu_count), nddsarch],
            cwd=repo_dir,
            fail_msg="failed to clone git repository: {}".format(repo_url))

        # Copy wheel to destination directory:
        py_vers = "{}{}".format(sys.version_info.major, sys.version_info.minor)
        whl_name = self.name = UvnDefaults["docker"]["context"]["connextdds_wheel_fmt"].format(
            py_vers, py_vers, arch)
        whl_path = repo_dir / whl_name
        shutil.copy2(str(whl_path), str(dst_dir))

    except Exception as e:
        logger.exception(e)
        logger.error("failed to build wheel for connextdds-py: {}", arch)
        raise (e)
    finally:
        if not keep:
            shutil.rmtree(str(tmp_dir))
        else:
            logger.warning("[tmp] not deleted: {}", tmp_dir)
    
    return whl_path


class NddshomeInfoDescriptor:
    def __init__(self, init_from_env=True):
        self._info = None
    
    def _init_info(self, nddshome=None):
        if not nddshome:
            nddshome = get_nddshome()
        if not nddshome or not nddshome.exists():
            logger.debug("NDDSHOME not found: '{}'", nddshome)
            return
        rti_versions = pathlib.Path(f"{nddshome}/rti_versions.xml")
        if not rti_versions.exists():
            raise ValueError("required path not found: {}", rti_versions)
        # read installed architectures
        result = cut(cut(grep(grep(
            "-A", "1",
                "RTI Connext DDS Pro Target Package Installed",
                str(rti_versions)),
            "<architecture>"),
            "-d>", "-f2-"),
            "-d<", "-f1")
        targets = frozenset(result.stdout.decode("utf-8").split("\n")[:-1])

        rs_path = pathlib.Path(f"{nddshome}/bin/rtiroutingservice")
        if not rs_path.exists():
            raise ValueError("required path not found: {}", rs_path)

        svc = types.SimpleNamespace(
                routing_service=rs_path)
        
        py = types.SimpleNamespace(
                build=functools.partial(build_connextddspy, nddshome))

        self._info = types.SimpleNamespace(
                    path=nddshome,
                    targets=targets,
                    service=svc,
                    copy_to=functools.partial(copy_nddshome, nddshome),
                    py=py)
        
    def __get__(self, obj, objtype=None):
        if not self._info:
            self._init_info()
        return self._info
    
    def __set__(self, obj, value):
        self._init_info(value)
        export_nddshome(self._info.path)
