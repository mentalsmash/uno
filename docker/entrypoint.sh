#!/bin/sh -e
# Load Python virtual environment
. ${UNO_VENV}/bin/activate

# Add /uno-middleware to PYTHONPATH if present
if [ -d /uno-middleware ]; then
  export PYTHONPATH="/uno-middleware$([ -z "${PYTHONPATH}" ] || printf -- ":")${PYTHONPATH}"
fi

# Check if a custom init script was mounted/specified
if [ -n "${INIT_ENV}" ]; then
  . ${INIT_ENV}
fi
if [ -n "${INIT}" ]; then
  ${INIT}
fi

# Check if we have a package, and if so, bootstrap it
if [ -f /package.uvn-agent ]; then
  chmod 600 /package.uvn-agent
  uno install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi

# Read action from environment, one of:
# - deploy: generate a new deployment
# - sync: push current configuration to agents
# - net: start network services only
# - <none>|agent: start a cell agent
# - anything else: exec custom command (quotes not preserved)
case "$@" in
deploy)
  uno redeploy ${VERBOSE} -r ${UVN_DIR} \
    $([ -z "${STRATEGY}" ] || printf -- "-S ${STRATEGY}" )
  ;;
sync)
  uno sync ${VERBOSE} -r ${UVN_DIR}
  ;;
net)
  # Use static configuration to start the agent
  cd ${UVN_DIR}
  uno service up router ${VERBOSE}
  bash
  uno service stop router ${VERBOSE}
  ;;
"__default__"|agent)
  # start the agent
  # Start the agent process
  exec uno agent ${VERBOSE} -r ${UVN_DIR}
  ;;
*)
  exec "$@"
  ;;
esac
