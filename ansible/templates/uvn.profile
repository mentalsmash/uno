export UVN_DIR={{uvn_dir}}
echo UVN_DIR := ${UVN_DIR}

UVND_PROFILE=$(which uvnd.profile)
if [ -f "${UVND_PROFILE}" ]; then
    . ${UVND_PROFILE}
else
    echo ERROR: uvnd.profile not found in PATH >&2
fi
