#!/bin/sh -e
if [ $# -ne 3 ]; then
  printf -- "ERROR: invalid arguments\n" >&2
  printf -- "Usage: %s <repo> <pr-number> (true|false)\n" "$(basename $0)" >&2
  exit 1
fi

REPO="${1}"
PR_NO="${2}"
MERGED="${3:=false}"
UNO_DIR=$(cd $(dirname $0)/.. && pwd)

if [ -n "${NOOP}" ]; then
  OPT_NOOP="-e NOOP=y"
fi

: "${GH_TOKEN:?GH_TOKEN is required but missing}
: "${ADMIN_IMAGE:=mentalsmash/uno-ci-admin:latest}

log_msg()
{
  local lvl="${1}"
  shift
  printf -- "${lvl}: $@\n" >&2
}

RC=0
case "${MERGED}" in
  false)
    PR_STATE=unmerged
    log_msg INFO "deleting all runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    rc=0
    docker run --rm \
      -v ${UNO_DIR}:/uno \
      -e GH_TOKEN=${GH_TOKEN} \
      ${OPT_NOOP} \
      ${ADMIN_IMAGE} \
      /uno/scripts/cleanup_workflows.sh ${REPO} \
        "'PR #${REPO_NO} [" || rc=0
    if [ "${rc}" -ne 0 ]; then
      log_msg ERROR "failed to delete all runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      RC=${rc}
    else
      log_msg INFO "deleted all runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    fi
    ;;
  true)
    PR_STATE=merged
    log_msg INFO "listing good 'basic validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    BASIC_VALIDATION_ALL=$(
      docker run --rm \
        -v ${UNO_DIR}:/uno \
        -e GH_TOKEN=${GH_TOKEN} \
        -e NOOP=y \
        ${ADMIN_IMAGE} \
        /uno/scripts/cleanup_workflows.sh ${REPO} \
          "^GOOD PR #${PR_NO} [changed]"
    )
    log_msg INFO "$(echo "${BASIC_VALIDATION_ALL}" | grep -v '^$' | wc -l) good 'basic validation' runs detected for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    log_msg INFO "----------------------------------------------------------------"
    echo "${BASIC_VALIDATION_ALL}" | grep -v '^$' >&2
    log_msg INFO "----------------------------------------------------------------"
    BASIC_VALIDATION_RUN="$(echo "${BASIC_VALIDATION_ALL}" | grep -v '^$' | tail -1)"
    if [ -z "${BASIC_VALIDATION_RUN}" ]; then
      log_msg ERROR "no good 'basic validation' run detected for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      exit 1
    else
      BASIC_VALIDATION_DELETE="$(echo "${BASIC_VALIDATION_ALL}" | grep -v '^$' | head -n -1)"
      log_msg INFO "- $(echo "${BASIC_VALIDATION_DELETE}" | wc -l) extra runs will be deleted"
    fi

    log_msg INFO "listing good 'full validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    FULL_VALIDATION_ALL=$(
      docker run --rm \
        -v ${UNO_DIR}:/uno \
        -e GH_TOKEN=${GH_TOKEN} \
        -e NOOP=y \
        ${ADMIN_IMAGE} \
        sh -c "/uno/scripts/cleanup_workflows.sh ${REPO} '^GOOD PR #${PR_NO} [reviewed, approved]'"
    )
    log_msg INFO "$(echo "${FULL_VALIDATION_ALL}" | grep -v '^$' | wc -l) good 'full validation' runs detected for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    log_msg INFO "----------------------------------------------------------------"
    echo "${FULL_VALIDATION_ALL}" | grep -v '^$' >&2
    log_msg INFO "----------------------------------------------------------------"
    FULL_VALIDATION_RUN="$(echo "${FULL_VALIDATION_ALL}" | grep -v '^$' | tail -1)"
    if [ -z "${FULL_VALIDATION_RUN}" ]; then
      log_msg ERROR "no good 'full validation' run detected for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      exit 1
    else
      FULL_VALIDATION_DELETE="$(echo "${FULL_VALIDATION_ALL}" | grep -v '^$'  | head -n -1)"
      log_msg INFO "- $(echo "${FULL_VALIDATION_DELETE}" | wc -l) extra runs will be deleted"
    fi

    log_msg INFO "BASIC VALIDATION run: '${BASIC_VALIDATION_RUN}'"
    log_msg INFO "FULL  VALIDATION run: '${FULL_VALIDATION_RUN}'"

    log_msg INFO "deleting failed runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    rc=0
    docker run --rm \
      -v ${UNO_DIR}:/uno \
      -e GH_TOKEN=${GH_TOKEN} \
      ${OPT_NOOP} \
      ${ADMIN_IMAGE} \
      /uno/scripts/cleanup_workflows.sh ${REPO} \
        "^FAIL | ^cancelled 'PR #${PR_NO} [" || rc=$?
    if [ "${rc}" -ne 0 ]; then
      log_msg WARNING "failed to delete failed runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      RC=${rc}
    else
      log_msg INFO "DELETED failed runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
    fi

    if [ -n "${BASIC_VALIDATION_DELETE}" ]; then
      log_msg INFO "deleting extra 'basic validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      echo "${BASIC_VALIDATION_DELETE}" > .delete_runs.log
      rc=0
      docker run --rm \
        -v $(pwd)/.delete_runs.log:/delete_runs.log \
        -v ${UNO_DIR}:/uno \
        -e GH_TOKEN=${GH_TOKEN} \
        ${OPT_NOOP} \
        ${ADMIN_IMAGE} \
        sh -c "cat /delete_runs.log | head -n -1 | RAW=y /uno/scripts/cleanup_workflows.sh ${REPO}" || rc=$?
      rm .delete_runs.log
      if [ "${rc}" -ne 0 ]; then
        log_msg WARNING "failed to delete extra 'basic validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
        RC=${rc}
      else
        log_msg INFO "DELETED extra 'basic validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      fi
    fi

    if [ -n "${FULL_VALIDATION_DELETE}" ]; then
      log_msg INFO "deleting extra 'full validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      echo "${FULL_VALIDATION_DELETE}" > .delete_runs.log
      rc=0
      docker run --rm \
        -v $(pwd)/.delete_runs.log:/delete_runs.log \
        -v ${UNO_DIR}:/uno \ \
        -e GH_TOKEN=${GH_TOKEN} \
        ${OPT_NOOP} \
        ${ADMIN_IMAGE} \
        sh -c "cat /delete_runs.log | head -n -1 | RAW=y /uno/scripts/cleanup_workflows.sh ${REPO}"
      rm .delete_runs.log
      if [ "${rc}" -ne 0 ]; then
        log_msg WARNING "failed to delete extra 'full validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
        RC=${rc}
      else
        log_msg INFO "DELETED extra 'full validation' runs for ${PR_STATE} PR #${PR_NO} of ${REPO}"
      fi
    fi
    ;;
  *)
    printf -- "ERROR: invalid MERGED value: '%s' (expected either 'true' or 'false')\n" "${MERGED}" >&2
    exit 1
    ;;
esac

if [ "${RC}" -ne 0 ]; then
  log_msg ERROR "errors encountered while processing ${PR_STATE} PR #${PR_NO} of ${REPO}"
else
  log_msg INFO "finished processing ${PR_STATE} PR #${PR_NO} of ${REPO}"
fi

exit ${RC}
