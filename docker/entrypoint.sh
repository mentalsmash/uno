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
# Disable exit on error so we can make sure to fix permissions on exit
set +e
rc=0
fix_host_permissions()
{
  # Restore permissions if the user provided uid/gid
  # Always restore ${UVN_DIR}
  CHOWN=${CHOWN}:${UVN_DIR}
  if [ -n "${HOST_UID}" -a -n "${HOST_GID}" -a "${CHOWN}" ]; then
    chown -R ${HOST_UID}:${HOST_GID} $(echo ${CHOWN} | tr : ' ' | sort | uniq)
  fi
}
# Check if we have a package, and if so, bootstrap it
if [ -f /package.uvn-agent ]; then
  chmod 600 /package.uvn-agent &&
    uno install ${VERBOSE} /package.uvn-agent -r ${UVN_DIR} || rc=$?
  if [ $rc -ne 0 ]; then
    fix_host_permissions
    exit $rc
  fi
fi
# Perform requested action, or custom command:
case "$@" in
# Start an agent for a cell or the registry
agent)
  exec uno agent ${VERBOSE} -r ${UVN_DIR} || rc=$?
  ;;
# Regenerate deployment
redeploy)
  uno redeploy ${VERBOSE} -r ${UVN_DIR}
  ;;
# Start static network services
static)
  uno service up ${VERBOSE} -r ${UVN_DIR} &&
    bash || rc=?
  if [ $rc -eq 0 ]; then
    rc=0 && uno service down ${VERBOSE} -r ${UVN_DIR} || rc=?
  fi
  ;;
# Push configuration to cells
sync)
  uno sync ${VERBOSE} -r ${UVN_DIR} || rc=$?
  ;;
# Validate arguments and skip to bottom for chown
chown)
  if  [ -z "${HOST_UID}" -o -z "${HOST_GID}" ]; then
    printf -- "ERROR: action 'chown' requires variables HOST_UID and HOST_GID"
    exit 1
  fi
  ;;
# Run custom command
*)
  exec "$@" || rc=$?
  ;;
esac

fix_host_permissions
exit $rc
