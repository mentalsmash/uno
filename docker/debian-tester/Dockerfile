ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ARG TEST_USER=uno

RUN set -xe; \
    # Install packages required by integration tests
    export DEBIAN_FRONTEND="noninteractive"; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      unzip \
      sudo \
      openssh-server \
      openssh-client \
      iperf3 \
      curl; \
    apt-get clean; \
    # create a non-root user and give it passwordless sudo
    adduser ${TEST_USER} --shell /bin/bash; \
    echo ${TEST_USER} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${TEST_USER}; \
    chmod 0440 /etc/sudoers.d/${TEST_USER}; \
    adduser ${TEST_USER} sudo; \
    # Initialize ~/.ssh
    mkdir -p /home/${TEST_USER}/.ssh; \
    touch /home/${TEST_USER}/.ssh/authorized_keys; \
    # Generate a private key and configure it as an authorized key
    ssh-keygen -t ed25519 -N '' -C uno@test -f /home/${TEST_USER}/.ssh/id_ed25519; \
    cat /home/${TEST_USER}/.ssh/id_ed25519.pub >> /home/${TEST_USER}/.ssh/authorized_keys; \
    # Adjust permissions
    chown -R ${TEST_USER}:${TEST_USER} /home/${TEST_USER}/.ssh

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
