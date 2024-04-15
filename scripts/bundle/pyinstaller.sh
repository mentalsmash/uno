#!/bin/sh
set -ex

FLAVOR=${1:-default}
DIST_DIR=$(pwd)/build/pyinstaller-${FLAVOR}
VENV_PYINST=${DIST_DIR}/venv
VENV_UNO=${DIST_DIR}/venv-uno

if [ ! -d ${VENV_PYINST} ]; then
  python3 -m venv ${VENV_PYINST}
  . ${VENV_PYINST}/bin/activate
  pip install pyinstaller
  deactivate
fi

rm -rf build/uno* build/runner* ${VENV_UNO}
python3 -m venv ${VENV_UNO}
. ${VENV_UNO}/bin/activate
pip install .
case "${FLAVOR}" in
  default)
    pip install rti.connext
    ;;
  *)
    ;;
esac
pip uninstall --yes pip setuptools
deactivate

VENV_LIB=$(find ${VENV_UNO}/lib/*/ -mindepth 1 -maxdepth 1 -name site-packages | head -1)

RTI_DIST_INFO=$(find ${VENV_LIB} -name "rti.connext-*.dist-info" -mindepth 1 -maxdepth 1 | head -1)

. ${VENV_PYINST}/bin/activate
pyinstaller \
  --noconfirm \
  --onedir \
  --clean \
  --distpath ${DIST_DIR} \
  --specpath build/ \
  --add-data $(pwd)/uno:uno \
  --hidden-import rti.connextdds \
  --hidden-import rti.idl_impl \
  --hidden-import rti.idl \
  --hidden-import rti.logging \
  --hidden-import rti.request \
  --hidden-import rti.rpc \
  --hidden-import rti.types \
  --add-data ${VENV_LIB}/rti:rti \
  --add-data ${VENV_LIB}/rti.connext.libs:rti.connext.libs \
  --add-data ${RTI_DIST_INFO}:$(basename ${RTI_DIST_INFO}) \
  -p ${VENV_LIB} \
  ./scripts/bundle/uno

pyinstaller \
  --noconfirm \
  --onedir \
  --clean \
  --distpath ${DIST_DIR}-runner \
  --specpath build/ \
  --add-data "../uno:uno" \
  --hidden-import rti.connextdds \
  --hidden-import rti.idl_impl \
  --hidden-import rti.idl \
  --hidden-import rti.logging \
  --hidden-import rti.request \
  --hidden-import rti.rpc \
  --hidden-import rti.types \
  --add-data ${VENV_LIB}/rti:rti \
  --add-data ${VENV_LIB}/rti.connext.libs:rti.connext.libs \
  --add-data ${RTI_DIST_INFO}:$(basename ${RTI_DIST_INFO}) \
  -p ${VENV_LIB} \
  ./uno/test/integration/runner.py
