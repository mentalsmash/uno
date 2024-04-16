#!/bin/sh
set -e
# Load Python virtual environment
if [ -f "${UNO_VENV}/bin/activate" ]; then
  . ${UNO_VENV}/bin/activate
fi
# Allow users (a.k.a. tests) to inject environment variables
if [ -n "${INIT_ENV}" ]; then
  . ${INIT_ENV}
fi
# or to perform custom initialization steps
if [ -n "${INIT}" ]; then
  ${INIT}
fi
# Check if we have a package, and if so, bootstrap it
# if the ${UVN_DIR} is empty
if [ -f /package.uvn-agent -a -z "$(find ${UVN_DIR} -mindepth 1 -maxdepth 1)" ]; then
  chmod 600 /package.uvn-agent &&
    uno install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR}
fi
# Perform requested action, or custom command:
case "$1" in
# Define a new UVN registry
define)
  shift
  exec uno define uvn $@
  ;;
# Start an agent for a cell or the registry
agent)
  shift
  exec uno agent -r ${UVN_DIR} $@
  ;;
# Regenerate deployment
redeploy)
  shift
  exec uno redeploy -r ${UVN_DIR} $@
  ;;
# Start static network services
up)
  shift
  exec uno service up -r ${UVN_DIR} $@
  ;;
# Stop static network services
down)
  shift
  exec uno service down -r ${UVN_DIR} $@
  ;;
# Push configuration to cells
sync)
  shift
  exec uno sync -r ${UVN_DIR} $@
  ;;
# Validate arguments and skip to bottom for chown
fix-file-ownership)
  shift
  OWNER=$1
  shift
  TARGET_DIRS=$(echo ${UVN_DIR} $@ | sort | uniq)
  echo "returning root files to ${OWNER}: ${TARGET_DIRS}"
    find ${TARGET_DIRS} \( -group 0 -o -user 0 \) -exec \
      chown $([ -z "${DEBUG}" ] || printf -- -v) ${OWNER} {} \;
  ;;
# Run custom command
*)
  exec "$@"
  ;;
esac
