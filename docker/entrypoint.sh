#!/bin/sh -ex

# Run a custom init script if specified
if [ -n "${RC_LOCAL}" ]; then
  printf "Running custom rc.local script: %s\n" "${RC_LOCAL}"
  ${RC_LOCAL}
fi

if [ "$@" = "__default__" ]; then
  cd ${UVN_DIR}
  if [ -n "${CELL_ID}" ]; then
    uvn cell agent ${UVN_EXTRA_ARGS}
  else
    if [ -n "${UVN_INIT}" ]; then
      uvn registry init --from-file ${UVN_INIT_CONFIG} ${UVN_EXTRA_ARGS}

      uvn registry generate-agents ${UVN_EXTRA_ARGS}
    else
      uvn registry agent ${UVN_EXTRA_ARGS}
    fi
  fi
else
  exec "$@"
fi
