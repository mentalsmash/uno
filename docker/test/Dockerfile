# Select the base image
ARG BASE_IMAGE="mentalsmash/uno:latest"
FROM ${BASE_IMAGE}

# Name of non-root user created for testing
ARG USER="uno"

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
    adduser ${USER} --shell /bin/bash; \
    echo ${USER} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${USER}; \
    chmod 0440 /etc/sudoers.d/${USER}; \
    adduser ${USER} sudo; \
    # Initialize ~/.ssh
    mkdir -p /home/${USER}/.ssh; \
    touch /home/${USER}/.ssh/authorized_keys; \
    # reinstall uno and the middleware in "editable" mode
    if [ -n "${DEV}" ]; then \
      pip3 install -e ${UNO_DIR}; \
      case "${UNO_MIDDLEWARE}" in \
        uno.middleware.native) \
          ;; \
        *) \
          pip3 install -e ${UNO_PLUGINS_DIR}/${UNO_MIDDLEWARE}; \
          ;; \
      esac; \  
    fi; \
    # Copy private and public key
    cp docker/dev/test_key.ed25519.key      /home/${USER}/.ssh/id_ed25519; \
    cp docker/dev/test_key.ed25519.key.pub  /home/${USER}/.ssh/id_ed25519.pub; \
    # Adjust private key's permissions
    chown -R ${USER}:${USER} /home/${USER}/.ssh; \
    chmod 600 /home/${USER}/.ssh/id_ed25519; \
    # Enable key for SSH login
    cat ${key}.pub >> /home/${USER}/.ssh/authorized_keys

