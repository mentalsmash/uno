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
from libuno.cfg import UvnDefaults
import shutil
import pathlib
import sys

################################################################################
# Import importlib.resources (importlib_resources shim)
################################################################################
# try:
#     import importlib.resources as pkg_resources
# except ImportError:
#     # Try backported to PY<37 `importlib_resources`.
#     import importlib_resources as pkg_resources
# Only use importlib_resources for now
import importlib_resources as pkg_resources

################################################################################
# Import modules which contains static files
################################################################################
from . import dockerfiles
from . import sh
from . import dds
from . import www

################################################################################
# Helper Classes
################################################################################
class StaticFile:
    def __init__(self, module, path):
        self.module = module
        self.path = pkg_resources.files(module) / path
        self.rel_path = pathlib.Path(path)
    
    def as_file(self):
        return pkg_resources.as_file(self.path)
    
    def open(self):
        return pkg_resources.open_binary(self.module, str(self.rel_path))
    
    def open_text(self):
        return pkg_resources.open_text(self.module, str(self.rel_path))
    
    def copy_to_dir(self, outdir, with_prefix=True):
        if with_prefix:
            prefix = self.rel_path.parent
        else:
            prefix = ""
        outfile = pathlib.Path(outdir) / prefix / self.rel_path.name
        self.copy_to(outfile)

    def copy_to(self, outfile):
        outfile = pathlib.Path(outfile)
        outfile.parent.mkdir(exist_ok=True, parents=True)
        with outfile.open("b") as output:
            with self.open() as input:
                shutil.copyfileobj(input, output)

################################################################################
# Docker files
################################################################################
def dockerfile(file, binary=True):
    if binary:
        return pkg_resources.open_binary(dockerfiles, file)
    else:
        return pkg_resources.open_text(dockerfiles, file)

################################################################################
# Script files
################################################################################
def script(file, binary=True):
    if binary:
        return pkg_resources.open_binary(sh, file)
    else:
        return pkg_resources.open_text(sh, file)

################################################################################
# connextdds-py wheels
################################################################################
class ConnextDdsWheel:
    def __init__(self, arch, base_name=UvnDefaults["docker"]["context"]["connextdds_wheel_fmt"]):
        py_vers = "{}{}".format(sys.version_info.major, sys.version_info.minor)
        self.name = base_name.format(py_vers, py_vers,
            "m" if (sys.version_info.minor == 6 or sys.version_info.minor == 7)
            else "",
            arch)
        self.path = pkg_resources.files(dds) / self.name
    
    def copy_to(self, dst_path):
        with pkg_resources.as_file(self.path) as whl_path:
            shutil.copyfile(str(whl_path), str(dst_path))
    
def connextdds_wheel(arch):
    return ConnextDdsWheel(arch)

################################################################################
# Connext DDS Configuration Files
################################################################################
class DdsProfileFile:
    def __init__(self, name=UvnDefaults["dds"]["profile_file"]):
        self.name = name
        self.path = pkg_resources.files(dds) / self.name
    
    def as_file(self):
        return pkg_resources.as_file(self.path)
    
    def open(self):
        return pkg_resources.open_text(dds, self.name)

def dds_profile_file():
    return DdsProfileFile()

################################################################################
# WWW data
################################################################################
class WwwStaticFile(StaticFile):
    def __init__(self, path):
        StaticFile.__init__(www, path)

def www_static_files():
    return map(lambda f: WwwStaticFile(f),[
        "css/style.css"
    ])
