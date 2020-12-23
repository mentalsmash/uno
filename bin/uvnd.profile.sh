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

uvnd_update()
{
    curl -sSL https://uno.mentalsmash.org/install | NONINTERACTIVE=y sh
    . ${UVND_PROFILE_SH}
}

uvnd_pull()
{
    (cd ${UVN_DIR} && git pull)
    . ${UVND_PROFILE_SH}
}

UVND_SESSION=${UVND_SESSION:-uvnd}
UVND_PROFILE_SH=$(which uvnd.profile.sh)
UVND_PID=${UVND_PID:-/var/run/uvn/uvnd.pid}

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
    echo "Loaded UVN: ${UVN_DIR}"
    echo "Use \`uvnd\`, or \`uvnds\` to run \`uvn\` in ${UVN_DIR}"
    echo "Use \`uvnd_start\`, and \`uvnd_stop\` to start/stop an agent inside screen session <${UVND_SESSION}>"
fi
