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
import setuptools

import libuno

with open("README.md", "r") as readme_f:
    readme_contents = readme_f.read()

setuptools.setup(
    name=libuno.__name__,
    version=libuno.__version__,
    author=libuno.__author__,
    author_email=libuno.__email__,
    description=libuno.__doc__,
    license="License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
    long_description=readme_contents,
    long_description_content_type="text/markdown",
    url="https://uno.mentalsmash.org",
    packages=setuptools.find_packages(),
    package_data={
        "libuno": [
            "templates/**/*",
            "data/**/*",
            "www/static/**/*"
    ]},
    scripts=[
        "bin/uvn",
        "bin/uvnd.profile"
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
        "Operating System :: POSIX :: Linux"
    ],
    python_requires='>=3.6, <4',
    install_requires=[
        "pyyaml>=5.1",
        "Jinja2",
        "python-gnupg",
        "termcolor",
        "docker",
        "netifaces",
        "importlib-resources",
        "cherrypy",
        "networkx",
        "matplotlib",
        "python-daemon",
        "lockfile",
        "sh",
        "shyaml"
    ],
    data_files=[
        ('share/man/man1',["docs/man/uvn.1"]),
        ('share/man/man8',["docs/man/uvnd.profile.8"]),
    ],
)
