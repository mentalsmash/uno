# Select the base image
ARG BASE_IMAGE="mentalsmash/uno:latest"
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.source=https://github.com/mentalsmash/uno
LABEL org.opencontainers.image.licenses=Apache-2.0
LABEL org.opencontainers.image.vendor=mentalsmash.org

# Name of non-root user created for testing
ARG TEST_USER="uno"

# Enable DEV mode
ARG DEV=

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
    # Install extras packages to help with development
    if [ -n "${DEV}" ]; then \
      apt-get install -y --no-install-recommends \
        build-essential \
        cargo \
        dnsutils \
        elinks \
        inetutils-traceroute \
        iperf \
        iputils-tracepath \
        less \
        sqlite3 \
        tcpdump \
        vim; \
    fi; \
    apt-get clean; \
    # create a non-root user and give it passwordless sudo
    adduser ${TEST_USER} --shell /bin/bash; \
    echo ${TEST_USER} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${TEST_USER}; \
    chmod 0440 /etc/sudoers.d/${TEST_USER}; \
    adduser ${TEST_USER} sudo; \
    # reinstall uno in "editable" mode
    if [ -n "${DEV}" ]; then \
      pip3 install -e ${UNO_DIR}; \
    fi; \
    # Initialize ~/.ssh
    mkdir -p /home/${TEST_USER}/.ssh; \
    touch /home/${TEST_USER}/.ssh/authorized_keys; \
    # Generate a private key and configure it as an authorized key
    ssh-keygen -t ed25519 -N '' -C uno@test -f /home/${TEST_USER}/.ssh/id_ed25519; \
    cat /home/${TEST_USER}/.ssh/id_ed25519.pub >> /home/${TEST_USER}/.ssh/authorized_keys; \
    # Adjust permissions
    chown -R ${TEST_USER}:${TEST_USER} /home/${TEST_USER}/.ssh

