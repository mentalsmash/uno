#!/bin/sh -ex

# Check if a custom init script was mounted/specified
if [ -n "${INIT}" ]; then
  ${INIT}
fi

# Check if the user specified a custom command
if [ "$@" != "__default__" ]; then
  exec "$@"
  exit
fi

# Check if the container was started in registry mode
if [ -z "${CELL}" ]; then
  # Check if a init configuration was provided, and
  # use it to initialize a new uvn
  if [ -f /uvn.yaml ]; then
    uno import uvn ${VERBOSE} -C /uvn.yaml -r ${UVN_DIR}
    # uno redeploy ${VERBOSE} -r ${UVN_DIR}
    exit
  fi

  # Read action from environment, one of:
  # - deploy: generate a new deployment
  # - sync: push current configuration to agents
  # - sh|<none>: start a shell
  case "${ACTION}" in
  deploy)
    uno redeploy ${VERBOSE} -r ${UVN_DIR} \
      $([ -z "${STRATEGY}" ] || printf -- "-S ${STRATEGY}" )
    ;;
  sync)
    uno sync ${VERBOSE} -r ${UVN_DIR}
    ;;
  sh|"")
    # Start a shell
    cd ${UVN_DIR}
    exec bash
    ;;
  *)
    printf -- "unknown action: '${ACTION}'\n" >&2
    exit 1
    ;;
  esac
  exit
fi

# Check if we have a package, and if so, bootstrap it
if [ -f /package.uvn-agent ]; then
  uno cell install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi

if [ -n "${STATIC}" ]; then
  # Use static configuration to start the agent
  ${UVN_DIR}/static/uno.sh start
  cd ${UVN_DIR}
  exec bash
  exit
fi

# Start the cell agent process
exec uno cell agent ${VERBOSE} -W -r ${UVN_DIR}
