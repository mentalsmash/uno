#!/bin/sh -e
VENV_DIR="${1:-venv}"
pkg_dir=$(cd $(dirname $0)/.. && pwd)
(
  set -x
  rm -rf ${VENV_DIR}
  python3 -m venv ${VENV_DIR}
)
. ${VENV_DIR}/bin/activate
(
  set -x
  pip3 install --upgrade pip setuptools wheel
  pip3 install -e ${pkg_dir}
)
