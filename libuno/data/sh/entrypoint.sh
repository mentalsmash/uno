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

printf "uvn-runner starting up...\n"

# Load a custom init script if specified
if [ -n "${RC_LOCAL}" ]; then
    printf "Running custom rc.local script: %s\n" "${RC_LOCAL}"
    ${RC_LOCAL}
fi

# Add some useful alias to /root/.bashrc
cat - > /root/bashrc.uvn << EOF
alias uvnd_pid="ps aux | grep -E 'uvn agent|uvn A' | grep -v grep | awk '{print \\\$2;}'"
alias uvnd_reload="kill -SIGUSR1 \\\$(uvnd_pid)"
alias uvnd_deploy="kill -SIGUSR2 \\\$(uvnd_pid)"
alias uvnd_stop="kill -SIGINT \\\$(uvnd_pid)"
alias uvnd_kill="kill \\\$(uvnd_pid)"
export NDDSHOME=/opt/ndds
export CONNEXTDDS_DIR="\${NDDSHOME}"
export UVN=/opt/uvn
uvnd()
{
    (cd \${UVN} && uvn \$@)
}
EOF
if [ -z "$(grep bashrc.uvn /root/.bashrc)" ]; then
    printf "%s\n" "source /root/bashrc.uvn" >> /root/.bashrc
fi

# Export NDDSHOME for agent
export NDDSHOME=/opt/ndds

if [ -n "${DEV}" ]; then
    printf "Installing uno's development version...\n"
    # Install uno from a development version mounted via volumed
    # cd /opt/uno
    # python setup.py
    pip3 install -e /opt/uno
else
    printf "Running uno release\n"
fi

# Intercept and run default command
if [ "$@" = "__default__" ]; then
    printf "Starting UVN agent from /opt/uvn\n"
    
    # Start UVN agent
    cd /opt/uvn

    uvn_extra=
    if [ -n "${KEEP}" ]; then
        uvn_extra="${uvn_extra} -k"
    fi
    if [ -n "${VERBOSE}" ]; then
        printf "Enabling verbose output: ${VERBOSE}\n"
        uvn_extra="${uvn_extra} -${VERBOSE}"
    fi
    if [ -n "${ROAMING}" ]; then
        uvn_extra="${uvn_extra} -r"
    fi
    if [ -z "${DISABLE_NAMESERVER}" ]; then
        # Enable nameserver by default
        uvn_extra="${uvn_extra} -n"
    fi

    if [ -n "${DAEMON}" ]; then
        uvnd ${uvn_extra}
        uvn_pid=$(cat /var/run/uvnd.pid)
    else
        uvn agent ${uvn_extra} &
        uvn_pid=$!
    fi

    wait ${uvn_pid}
    uvn_rc=$?

    if [ -n "${failed_rc}" ]; then
        exit ${failed_rc}
    else
        exit ${uvn_rc}
    fi
fi

printf "Runnin custom command: '%s'\n" "$@"

exec "$@"
