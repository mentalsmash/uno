ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

COPY ./debian-dist/* /tmp/debian-dist/

ARG PACKAGE_NAME=uno
ARG PACKAGE_VERSION=*
ARG PACKAGE_ARCH=
ARG PACKAGE_DEB=
RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    package=${PACKAGE_DEB:-$(find /tmp/debian-dist \
      -name "${PACKAGE_NAME}_${PACKAGE_VERSION}_${PACKAGE_ARCH:-$(dpkg --print-architecture)}.deb" | \
        head -1)}; \
    test -f "${package}"; \
    apt install -y ${package}; \
    apt-get clean; \
    rm -rf /tmp/debian-dist

ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"
ENV UNO_VENV /opt/uno/venv

RUN mkdir -p ${UVN_DIR}; \
    chmod 700 ${UVN_DIR}

ENV RTI_LICENSE_FILE "/rti_license.dat"

VOLUME [ "${UVN_DIR}", "${UNO_DIR}" ]

WORKDIR ${UVN_DIR}

COPY ./docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT [ "/entrypoint.sh" ]
CMD ["agent"]

ARG TEST_FLAVOR=default
COPY ./build/pyinstaller-${TEST_FLAVOR}-runner/runner /opt/runner
ENV PATH="/opt/runner:${PATH}"
