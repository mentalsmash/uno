#!/bin/sh -e
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

EXPERIMENT_TYPE=host

printf "Initializing host %s...\n" "$(hostname)"

# Include common init script
EXPERIMENT_DIR=$(cd $(dirname "${0}") && pwd)
. ${EXPERIMENT_DIR}/common.sh

TEST_NET_GW=${TEST_NET_GW:-${TEST_NET}.254}
printf "Setting default route via %s\n" "${TEST_NET_GW}"
# Delete default route
ip route delete default
# Add default route via network's router
ip route add default via ${TEST_NET_GW} dev eth0

# Dump host configuration for logging
dump_host_config

printf "Host initialized: %s\n" "$(hostname)"
