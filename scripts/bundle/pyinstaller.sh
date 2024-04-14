#!/bin/sh
set -ex

FLAVOR=${1:-default}
DIST_DIR=build/pyinstaller-${FLAVOR}
VENV_PYINST=${DIST_DIR}/venv
VENV_UNO=${DIST_DIR}/venv-uno

if [ ! -d ${VENV_PYINST} ]; then
  python3 -m venv ${VENV_PYINST}
  . ${VENV_PYINST}/bin/activate
  pip install pyinstaller
  deactivate
fi

rm -rf ${VENV_UNO}
python3 -m venv ${VENV_UNO}
. ${VENV_UNO}/bin/activate
pip install .
case "${FLAVOR}" in
  default)
    pip install ./plugins/uno_middleware_connext
    ;;
  *)
    ;;
esac
pip uninstall --yes pip setuptools
deactivate

. ${VENV_PYINST}/bin/activate
pyinstaller \
  --noconfirm \
  --onedir \
  --clean \
  --distpath ${DIST_DIR} \
  -p ${VENV_UNO}/lib/*/site-packages/ \
  ./scripts/bundle/uno
