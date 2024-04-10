#!/bin/sh
set -e
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
  chmod 600 /package.uvn-agent &&
    uno install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi
# Perform requested action, or custom command:
case "$1" in
# Start an agent for a cell or the registry
agent)
  exec uno agent -r ${UVN_DIR} $@
  ;;
# Regenerate deployment
redeploy)
  exec uno redeploy -r ${UVN_DIR} $@
  ;;
# Start static network services
up)
  exec uno service up -r ${UVN_DIR} $@
  ;;
# Stop static network services
down)
  exec uno service down -r ${UVN_DIR} $@
  ;;
# Push configuration to cells
sync)
  exec uno sync -r ${UVN_DIR} $@
  ;;
# Validate arguments and skip to bottom for chown
fix-root-permissions)
  shift
  OWNER=$1
  shift
  TARGET_DIRS=$(echo ${UVN_DIR} $@ | sort | uniq)
  echo "returning root files to ${OWNER}: ${TARGET_DIRS}"
    find ${TARGET_DIRS} \( -group 0 -o -user 0 \) -exec \
      chown -v ${OWNER} {} \;
  ;;
# Run custom command
*)
  exec "$@"
  ;;
esac
