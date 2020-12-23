#!/bin/sh

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
	set -x
        screen -S ${UVND_SESSION} -d -m 
        screen -S ${UVND_SESSION} -p 0 -X stuff \
            "export UVN_DIR=${UVN_DIR}^M. ${UVND_PROFILE_SH}^Muvnds A -v $@^M"
        screen -r ${UVND_SESSION}
    )
}

uvnd_stop()
{
    ! screen -list | grep -q ${UVND_SESSION} ||
    (
        set -e
	set -x
        screen -S ${UVND_SESSION} -X at '#' stuff ^C
	screen -S ${UVND_SESSION} -X at '#' stuff "exit^M"
	set +x
        while screen -list | grep -q ${UVND_SESSION}; do
            echo "waiting for screen session <${UVND_SESSION}> to terminate..."
            sleep 2
        done
    )
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
        return
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

uvnd_started()
{
    if uvnd_kill 0; then
        echo "uvnd status: started ($(uvnd_pid))"
    else
        echo "uvnd status: stopped"
    fi
}

uno_update()
{
    curl -sSL https://uno.mentalsmash.org/install | NONINTERACTIVE=y sh
    . ${UVND_PROFILE_SH}
}

uvnd_help()
{
    echo "uvnd shell helper (${UVND_PROFILE_SH})"
    echo
    echo "Status --------------------------------------------"
    uvnd_started
    echo "Default UVN_DIR: ${UVN_DIR}"
    echo "Default screen session: ${UVND_SESSION}"
    echo
    echo "Available commands ---------------------------------"
    echo
    echo "  uvnd:           run \`uvn\` in \${UVN_DIR} as ${USER}"
    echo "  uvnds:          run \`uvn\` in \${UVN_DIR} as root"
    echo
    (
    echo "  uvnd_start:     start uvn agent in a screen session"
    echo "  uvnd_stop:      terminate uvn agent's session, and wait for it to exit."
    echo "  uvnd_pid:       print PID of active uvn agent"
    echo "  uvnd_kill:      send a signal to uvn agent"
    echo "  uvnd_deploy:    signal uvn agent to generate a new deployment"
    echo "  uvnd_reload:    signal uvn agent to reload configuration from filesystem"
    echo "  uvnd_exit:      signal uvn agent to exit"
    echo "  uvnd_started:   check if uvn agent is running"
    echo "  uvnd_help:      print this help"
    ) | sort
    echo
    echo "  uno_update:     update the uno installation using the installer in NONINTERACTIVE mode."
    echo
}

UVND_SESSION=${UVND_SESSION:-uvnd}
UVND_PROFILE_SH=$(which uvnd.profile.sh)

if [ ! -x "${UVND_PROFILE_SH}" ]; then
    echo "WARNING: uvnd.profile.sh not found in PATH."
    echo "WARNING: \`uvnd_start\`, and \`uvnd_stop\` will not work as expected."
    UVND_INVALID=y
fi

if [ ! -d "${UVN_DIR}" ]; then
    echo "WARNING: invalid UVN_DIR '${UVN_DIR}'" >&2
    echo "WARNING: uvn helper aliases will not be available."
    UVND_INVALID=y
fi

if [ -z "${UVND_INVALID}" ]; then
    uvnd_help
fi
