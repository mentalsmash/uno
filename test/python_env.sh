#!/bin/sh
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

set -e
set -x

UNO_DIR=$(realpath $(cd $(dirname "${0}") && pwd)/..)
ENV_DIR="${1}"

python3 -m venv ${ENV_DIR}

export PATH="$(realpath ${ENV_DIR})/bin:${PATH}"

pip install -e ${UNO_DIR}

uvn --version
