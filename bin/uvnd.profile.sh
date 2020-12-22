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
        screen -S ${UVND_SESSION} -p 0 -X stuff ". $(which uvnd.profile)^Muvnds A -v $@^M"
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

UVND_SESSION=${UVND_SESSION:-uvnd}

if [ -d "${UVN_DIR}" ]; then
    echo "Loaded UVN: ${UVN_DIR}"
    echo "Use \`uvnd\`, or \`uvnds\` to run \`uvn\` in ${UVN_DIR}"
    echo "Use \`uvnd_start\`, and \`uvnd_stop\` to start/stop an agent inside screen session <${UVND_SESSION}>"
else
    echo "WARNING: invalid UVN_DIR '${UVN_DIR}'" >&2
    echo "WARNING: uvn helper aliases will not be available."
fi


