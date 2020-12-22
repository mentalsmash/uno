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

UVN_ADDRESS=${UVN_ADDRESS:-test-uvn.localhost}
UVN_CELLS="cell1 cell2 cell3"
UVN_PARTICLES="particle1 particle2 particle3"
[ -z "${VERBOSE}" ] || VERBOSE="-vv"
[ -z "${KEEP}" ] || KEEP="-k"

(
    set -e
    set -x

    # Delete test directories, if they exist
    rm -rf ${UVN_ADDRESS} \
           ${UVN_ADDRESS}.cells \
           ${UVN_ADDRESS}.particles

    # Initialize a new UVN
    uvn c ${UVN_ADDRESS} ${VERBOSE}

    # Perform operations from UVN directory to load secrets from file
    cd ${UVN_ADDRESS}

    # Attach three cells
    uvn a c -n cell1 ${VERBOSE}
    uvn a c -n cell2 ${VERBOSE}
    uvn a c -n cell3 ${VERBOSE}

    # Attach some particles
    uvn a p particle1 ${VERBOSE}
    uvn a p particle2 ${VERBOSE}
    uvn a p particle3 ${VERBOSE}

    # Generate a new deployment
    uvn d ${VERBOSE}

    if [ -n "${EXTRA_CELLS}" ]; then
        UVN_CELLS="${UVN_CELLS} cell4 cell5 cell6 cell7"
        # Attach a new cell. This invalidates the existing deployment.
        uvn a c -n cell4 ${VERBOSE}
        uvn a c -n cell5 ${VERBOSE}
        uvn a c -n cell6 ${VERBOSE}
        uvn a c -n cell7 ${VERBOSE}

        # Attach some more particles
        uvn a p particle4 ${VERBOSE}
        uvn a p particle5 ${VERBOSE}
        uvn a p particle6 ${VERBOSE}
        uvn a p particle7 ${VERBOSE}

        # Generate a new deployment and drop the ones that have become stale
        uvn d -d ${VERBOSE}
    fi

    # Exit UVN directory
    cd -

    for cell in ${UVN_CELLS}; do
        # Install cell packages into separate directories
        uvn I ${UVN_ADDRESS}/installers/uvn-${UVN_ADDRESS}-bootstrap-${cell}.zip \
            ${UVN_ADDRESS}.cells/${cell} ${VERBOSE}
        (
            base_dir=$(pwd)
            cd ${UVN_ADDRESS}.cells/${cell}
            uvn I ${base_dir}/${UVN_ADDRESS}/installers/uvn-${UVN_ADDRESS}-latest-${cell}.zip . ${VERBOSE}
        )
    done

    for particle in ${UVN_PARTICLES}; do
        # Check that particle's zip exists and extract zip
        (
            mkdir -p ${UVN_ADDRESS}.particles/${particle}
            cd  ${UVN_ADDRESS}.particles/${particle}
            unzip ../../${UVN_ADDRESS}/particles/uvn-${UVN_ADDRESS}-${particle}.zip
        )
    done

    uvn_bin=$(which uvn)

    cd ${UVN_ADDRESS}
    
    # Test root UVN agent. Enter directory to load secret from file
    [ -n "${NONINTERACTIVE}" ] || sudo ${uvn_bin} A ${VERBOSE} ${KEEP}

    # Build Docker images
    sudo ${uvn_bin} R b -D ${VERBOSE}

    cd -
)
rc=$?
if [ ${rc} -eq 0 ]; then
    printf "OK\n"
else
    printf "FAILED\n"
fi
