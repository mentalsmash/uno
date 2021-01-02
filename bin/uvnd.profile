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

uvnd()
{
    (cd ${UVN_DIR} && uvn $@)
}

uvnds()
{
    (cd ${UVN_DIR} && sudo uvn $@)
}

uvnd_start()
{
    screen -r ${UVND_SESSION} 1>/dev/null 2>&1 ||
    (
        set -e
        (
            set -x
            screen -S ${UVND_SESSION} -d -m 
            screen -S ${UVND_SESSION} -p 0 -X stuff \
                "export UVN_DIR=${UVN_DIR}^M. ${UVND_PROFILE}^Muvnds A -v $@^M"
        )
        max_t=${UVND_TIMEOUT}
        max_i=0

        while [ -z "$(uvnd_pid)" -a ${max_i} -lt ${max_t} ]; do
            echo "waiting for uvnd to start..."
            sleep 2
            max_i=$(expr ${max_i} + 2)
        done
        if [ -z "$(uvnd_pid)" ]; then
            echo "ERROR: failed to spawn uvn agent" >&2
        else
            echo "uvn agent started: $(uvnd_pid)"
        fi
    )
}

uvnd_attach()
{
    (
        set -x
        screen -r ${UVND_SESSION}
    )
}

uvnd_stop()
{
    ! screen -list | grep -q ${UVND_SESSION} ||
    (
        set -e
        (
            set -x
            screen -S ${UVND_SESSION} -X at '#' stuff ^C
            screen -S ${UVND_SESSION} -X at '#' stuff "exit^M"
        )
        max_t=${UVND_TIMEOUT}
        max_i=0
        while screen -list | grep -q ${UVND_SESSION} && [ ${max_i} -lt ${max_t} ]; do
            echo "waiting for screen session <${UVND_SESSION}> to terminate..."
            sleep 2
            max_i=$(expr ${max_i} + 2)
        done
        if screen -list | grep -q ${UVND_SESSION}; then
            echo "ERROR: failed to stop uvn agent" >&2
        else
            echo "uvn agent stopped"
        fi
    )
}

uvnd_restart()
{
    uvnd_stop
    uvnd_start "$@"
}

uvnd_cell()
{
    uvnd_start "-n $@"
}

uvnd_pid()
{
    ps aux | grep "uvn A" | grep python3 | awk '{print $2;}'
}

uvnd_kill()
{
    local pid=$(uvnd_pid) \
          signal="${1}"

    if [ -z "${pid}" ]; then
        echo "uvnd doesn't seem to be running" >&2
        return 1
    fi

    if [ -n "${signal}" ]; then
        signal=-${signal}
    fi

    sudo kill ${signal} ${pid}
}

uvnd_deploy()
{
    uvnd_kill SIGUSR2
}

uvnd_reload()
{
    uvnd_kill SIGUSR1
}

uvnd_exit()
{
    uvnd_kill SIGINT
}

uvnd_status()
{
    if uvnd_kill 0 2>/dev/null 1>&2; then
        echo "uvnd status: started ($(uvnd_pid))"
    else
        echo "uvnd status: stopped"
    fi
}

uno_update()
{
    curl -sSL https://uno.mentalsmash.org/install | NONINTERACTIVE=y sh
    . ${UVND_PROFILE}
}

uvn_status()
{
    echo -n "  "; uvnd_status
    echo "  Default UVN_DIR: ${UVN_DIR}"
}

uvnd_help()
{
    echo
    echo "uno shell helper ----------------------"
    echo
    echo -n "  "; uvnd_status
    echo "  Default UVN_DIR: ${UVN_DIR}"
    echo "  Default screen session: ${UVND_SESSION}"
    echo "  Helper script: ${UVND_PROFILE}"
    echo
    echo "available uno commands ----------------"
    echo
    echo "  uvnd:           run \`uvn\` in \${UVN_DIR} as ${USER}"
    echo "  uvnds:          run \`uvn\` in \${UVN_DIR} as root"
    echo
    (
    echo "  uvnd_start:     start uvn agent in a screen session"
    echo "  uvnd_stop:      signal uvn agent for termination, and wait for it's screen session to exit."
    echo "  uvnd_restart:   stop and restart uvn agent's session"
    echo "  uvnd_cell:      same as uvnd_start, but also enables the nameserver"
    echo "  uvnd_pid:       print PID of active uvn agent"
    echo "  uvnd_kill:      send a signal to uvn agent"
    echo "  uvnd_deploy:    signal uvn agent to generate a new deployment"
    echo "  uvnd_reload:    signal uvn agent to reload configuration from filesystem"
    echo "  uvnd_exit:      signal uvn agent to exit"
    echo "  uvnd_status:    check if uvn agent is running"
    echo "  uvnd_help:      print this help"
    echo "  uvnd_attach:    attach to the uvn agent's screen session"
    ) | sort
    echo
    echo "  uno_update:     update the uno installation using the installer in NONINTERACTIVE mode."
    echo
}

UVND_TIMEOUT=${UVND_TIMEOUT:-60}
UVND_SESSION=${UVND_SESSION:-uvnd}
UVND_PROFILE=$(which uvnd.profile)

if [ ! -x "${UVND_PROFILE}" ]; then
    echo "WARNING: uvnd.profile not found in PATH."
    echo "WARNING: \`uvnd_start\`, and \`uvnd_stop\` will not work as expected."
    UVND_INVALID=y
fi

if [ ! -d "${UVN_DIR}" ]; then
    echo "WARNING: invalid UVN_DIR '${UVN_DIR}'" >&2
    echo "WARNING: uvn helper aliases will not be available."
    UVND_INVALID=y
fi

if [ -n "${UVND_INVALID}" ]; then
    echo "ERROR: failed to load uvn configuration"
fi
