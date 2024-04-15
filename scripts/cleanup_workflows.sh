#!/usr/bin/env bash
# From: https://raw.githubusercontent.com/qmacro/dotfiles/230c6df494f239e9d1762794943847816e1b7c32/scripts/dwr
# Delete workflow runs - dwr

# Given an "owner/repo" name, such as "qmacro/thinking-aloud",
# retrieve the workflow runs for that repo and present them in a
# list. Selected runs will be deleted. Uses the GitHub API.

# Requires gh (GitHub CLI) and jq (JSON processor)

# First version

# (asorbini) Modified to take an optional filter argument to run in noninteractive mode

REPO="${1}"
FILTER="${2}"

set -o errexit
set -o pipefail

declare repo=${1:?No owner/repo specified}

jqscript() {

    cat <<EOF
      def symbol:
        sub(""; "")? // "NULL" |
        sub("skipped"; "SKIP") |
        sub("success"; "GOOD") |
        sub("failure"; "FAIL");

      def tz:
        gsub("[TZ]"; " ");


      .workflow_runs[]
        | [
            (.conclusion | symbol),
            (.created_at | tz),
            .id,
            .event,
            .name
          ]
        | @tsv
EOF

}

selectruns() {

  gh api --paginate "/repos/$repo/actions/runs" \
    | jq -r -f <(jqscript) \
    | fzf --multi $([ -z "${FILTER}" ] || printf -- "--filter '%s'" "${FILTER}")

}

deleterun() {

  local run id result
  run=${REPO}
  id="$(cut -f 3 <<< "$run")"
  gh api -X DELETE "/repos/$repo/actions/runs/$id"
  [[ $? = 0 ]] && result="OK!" || result="BAD"
  printf "%s\t%s\n" "$result" "$run"

}

deleteruns() {

  local id
  while read -r run; do
    deleterun "$run"
    sleep 0.25
  done

}

main() {

  selectruns | deleteruns

}

main

