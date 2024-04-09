# Select the base image
ARG BASE_IMAGE="ubuntu:22.04"
FROM ${BASE_IMAGE}

# Enable TEST mode
ARG TEST=
# Enable DEV mode
ARG DEV=
###############################################################################
# Install system dependencies and perform basic environment setup
###############################################################################
RUN set -xe; \
    export DEBIAN_FRONTEND="noninteractive"; \
    apt-get update; \
    # - Make sure locale is en_US.UTF-8
    if [ "$(. /etc/os-release && echo $ID)" = ubuntu ]; then \
      apt-get install -y --no-install-recommends \
        locales;  \
      locale-gen en_US en_US.UTF-8; \
      update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8; \
    else \
      apt-get install -y --no-install-recommends \
        locales \
        locales-all; \
      update-locale LC_ALL=en_US.utf8 LANG=en_US.utf8; \
    fi; \
    # - Install uno's dependencies
    #   - psmisc to have killall
    #   - iproute2 to provision `ip` command
    #   - iptables to control kernel routing
    #   - python3-pip to provision `pip` command (and possibly `python`)
    #   - gnupg2 to handle keys and identities
    #   - wireguard to implement the uvn connections
    #   - rng-tools to provision `rngd` and speed up key generation
    #   - vim to have a decent text editor, and less for a decent pager
    #   - frr for the ospfd routing daemon
    #   - qrencode to generate QR codes for particles
    #   - some system services used by uvn
    #   - build-essential (because some PyPI packages might need building, e.g. netifaces)
    apt-get install -y --no-install-recommends \
      frr \
      git \
      gnupg2 \
      iproute2 \
      iptables \
      iputils-ping \
      lighttpd \
      lighttpd-mod-openssl \
      psmisc \
      openssl \
      python3-dev \
      python3-pip \
      python3-venv \
      qrencode \
      wireguard \
      wireguard-tools; \
    # Install packages required by integration tests
    if [ -n "${DEV}" -o -n "${TEST}" ]; then \
      apt-get install -y --no-install-recommends \
        unzip \
        sudo \
        openssh-server \
        openssh-client \
        iperf3; \
    fi; \
    # Install extras packages to help with development
    if [ -n "${DEV}" ]; then \
      apt-get install -y --no-install-recommends \
        vim \
        less \
        iputils-tracepath \
        dnsutils \
        inetutils-traceroute \
        iperf \
        tcpdump \
        elinks \
        cargo \
        sqlite3; \
    fi; \
    # clean up apt cache
    apt-get clean

ENV LANG en_US.UTF-8

###############################################################################
# Install uno and other Python packages
###############################################################################
# Path to the Python venv where everything will be installed.
ENV UNO_VENV /opt/uno/venv

# Copy uno repository
COPY . /uno-dev

# Install uno from the local repository clone, ...
ARG LOCAL=
# Name of non-root user created for TEST, and DEV modes
ARG USER="uno"
# Or to clone a specific version from the remote repository
ARG UNO_VERSION=master
ARG UNO_URL=https://github.com/mentalsmash/uno
# Specify a default middleware for the image
ARG UNO_MIDDLEWARE=uno_middleware_connext

RUN set -xe; \
    # - create a non-root user
    # - install openssh-server, openssh-client, and (passwordless) sudo.
    # - configure uno-dev/docker/dev/test_key.ed25519.key as an authorized key
    #   and install it as the user's private key
    if [ -n "${DEV}" -o -n "${TEST}" ]; then \
      adduser ${USER} --shell /bin/bash; \
      echo ${USER} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${USER}; \
      chmod 0440 /etc/sudoers.d/${USER}; \
      adduser ${USER} sudo; \
      mkdir -p /home/${USER}/.ssh; \
      touch /home/${USER}/.ssh/authorized_keys; \
      key=/uno-dev/docker/dev/test_key.ed25519.key; \
      cat ${key}.pub >> /home/${USER}/.ssh/authorized_keys; \
      cp ${key} /home/${USER}/.ssh/id_ed25519; \
      cp ${key}.pub /home/${USER}/.ssh/id_ed25519.pub; \
      chown -R ${USER}:${USER} /home/${USER}/.ssh; \
      chmod 600 /home/${USER}/.ssh/id_ed25519; \
    fi; \
    # Generate new virtual environment
    python3 -m venv ${UNO_VENV}; \
    . ${UNO_VENV}/bin/activate; \
    # Check if the user passed a Connext wheel in the context
    rti_wheel=$(find /uno-dev/ -mindepth 1 -maxdepth 1 -name "rti.connext*.whl" | head -1); \
    if [ -f "${rti_wheel}" ]; then \
      pip3 install ${rti_wheel}; \
    fi; \
    # Install uno
    if [ -n "${LOCAL}" ]; then \
      cp -r /uno-dev /uno; \
    else \
      git clone ${UNO_URL} -b ${UNO_VERSION} /uno; \
    fi; \
    pip3 install -e /uno; \
    # Install middleware and other plugins
    mkdir -p /uno-plugins; \
    install_plugin() { \
      plugin_dir=/uno-plugins/$1; \
      git clone $2 -b $3 ${plugin_dir}; \
      pip3 install -e ${plugin_dir}; \
    }; \
    case "${UNO_MIDDLEWARE}" in \
      uno_middleware_connext) \
        install_plugin uno_middleware_connext https://github.com/mentalsmash/uno-middleware-connext.git master; \
        ;; \
    esac; \
    # Install packages required by tests
    if [ -n "${DEV}" -o -n "${TEST}" ]; then \
      pip3 install pytest; \
    fi; \
    # Delete uno repository
    rm -rf /uno-dev

# Custom entrypoint
ENTRYPOINT [ "/uno/docker/entrypoint.sh" ]
CMD ["__default__"]

# Define volumes
ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"
VOLUME [ "${UVN_DIR}" , "${UNO_DIR}"]

# Add venv/bin directory to the top of PATH
# so we don't have to activate it
ENV PATH "${UNO_VENV}/bin:${PATH}"

# Set default middleware
ENV UNO_MIDDLEWARE  "${UNO_MIDDLEWARE}"

# Set default work directory
WORKDIR /uvn
