#!/bin/sh
set -e

FLAVOR=${1:-default}

: "${CLEAN:=yes}"
[ "${CLEAN}" = yes -o "${CLEAN}" = no ]

: "${DIST_DIR:=$(pwd)/dist/bundle/${FLAVOR}}"
[ -n "${DIST_DIR}" ]

: "${BUILD_DIR:=$(pwd)/build/pyinstaller}"
[ -n "${BUILD_DIR}" ]

: "${SCRIPTS:=\
  ./scripts/bundle/uno
  ./uno/test/integration/runner.py}"
[ -n "${SCRIPTS}" ]

: "${VENV_PYINST:=${BUILD_DIR}/venv-pyinst}"
[ -n "${VENV_PYINST}" ]

: "${VENV_UNO:=${BUILD_DIR}/venv-uno}"
[ -n "${VENV_UNO}" ]

if [ ! -d "${VENV_PYINST}" ]; then
  (
    set -x
    python3 -m venv ${VENV_PYINST}
    . ${VENV_PYINST}/bin/activate
    pip install pyinstaller
    deactivate
  )
fi

if [ "${CLEAN}" = yes -o ! -d "${VENV_UNO}" ]
  (
    set -x
    rm -rf ${VENV_UNO}
    python3 -m venv ${VENV_UNO}
    . ${VENV_UNO}/bin/activate
    pip install .
    [ "${FLAVOR}" != default ] || pip install rti.connext
    pip uninstall --yes pip setuptools
    deactivate
  )
endif

VENV_LIB=$(find ${VENV_UNO}/lib/*/ -mindepth 1 -maxdepth 1 -name site-packages | head -1)
[ -n "${VENV_LIB}" ]

RTI_DIST_INFO=$(find ${VENV_LIB} -name "rti.connext-*.dist-info" -mindepth 1 -maxdepth 1 | head -1)
[ -n "${RTI_DIST_INFO}" ]

(
  set -x
  rm -rf $(BUILD_DIR)

  . ${VENV_PYINST}/bin/activate
  for script in ${SCRIPTS}; do
    pyinstaller \
      --noconfirm \
      --onedir \
      --clean \
      --workpath $(BUILD_DIR) \
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
      ${script}
  done
)
