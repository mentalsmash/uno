#!/bin/sh -e
# Load Python virtual environment
. ${UNO_VENV}/bin/activate
# Allow users (a.k.a. tests) to inject environment variables
if [ -n "${INIT_ENV}" ]; then
  . ${INIT_ENV}
fi
# or to perform custom initialization steps
if [ -n "${INIT}" ]; then
  ${INIT}
fi
# Check if we have a package, and if so, bootstrap it
if [ -f /package.uvn-agent ]; then
  chmod 600 /package.uvn-agent
  uno install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi
# Perform requested action, or custom command:
case "$@" in
# Start an agent for a cell or the registry
agent)
  exec uno agent ${VERBOSE} -r ${UVN_DIR}
  ;;
# Regenerate deployment
redeploy)
  uno redeploy ${VERBOSE} -r ${UVN_DIR}
  ;;
# Start static network services
static)
  uno service up ${VERBOSE} -r ${UVN_DIR}
  bash
  uno service down ${VERBOSE} -r ${UVN_DIR}
  ;;
# Push configuration to cells
sync)
  uno sync ${VERBOSE} -r ${UVN_DIR}
  ;;
# Run custom command
*)
  exec "$@"
  ;;
esac
