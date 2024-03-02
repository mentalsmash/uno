#!/bin/sh -ex

# Check if a custom init script was mounted/specified
if [ -n "${INIT}" ]; then
  ${INIT}
fi

# Check if a init configuration was provided, and
# use it to initialize a new uvn
if [ -f /uvn.yaml ]; then
  uno import uvn ${VERBOSE} -C /uvn.yaml -r ${UVN_DIR}
  # uno redeploy ${VERBOSE} -r ${UVN_DIR}
  exit
# Check if we have a package, and if so, bootstrap it
elif [ -f /package.uvn-agent ]; then
  chmod 600 /package.uvn-agent
  uno cell install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi


# Read action from environment, one of:
# - deploy: generate a new deployment
# - sync: push current configuration to agents
# - sh|<none>: start a shell
case "$@" in
deploy)
  uno redeploy ${VERBOSE} -r ${UVN_DIR} \
    $([ -z "${STRATEGY}" ] || printf -- "-S ${STRATEGY}" )
  exit
  ;;
sync)
  uno sync ${VERBOSE} -r ${UVN_DIR}
  exit
  ;;
net)
  # Use static configuration to start the agent
  cd ${UVN_DIR}
  uvn-net start
  bash
  uvn-net stop
  exit
  ;;
"__default__")
  # start the agent
  # Start the agent process
  exec uno agent ${VERBOSE} -r ${UVN_DIR}
  ;;
*)
  exec "$@"
  ;;
esac
