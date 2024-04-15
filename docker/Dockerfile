# Select the base image
ARG BASE_IMAGE="ubuntu:22.04"
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.source=https://github.com/mentalsmash/uno
LABEL org.opencontainers.image.licenses=Apache-2.0
LABEL org.opencontainers.image.vendor=mentalsmash.org

# Name of non-root user created for testing
ARG TEST_USER="uno"
# Enable TEST mode
ARG TEST=
# Enable DEV mode
ARG DEV=

###############################################################################
# Install system dependencies and perform basic environment setup
###############################################################################
RUN set -xe; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    # Make sure the image has updated packages
    apt-get upgrade -y --no-install-recommends; \
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
      python3-venv \
      qrencode \
      tar \
      xz-utils \
      wireguard \
      wireguard-tools; \
      if [ -n "${TEST}${DEV}" ]; then \
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
    fi; \
    # clean up apt cache
    apt-get clean

ENV LANG en_US.UTF-8

###############################################################################
# Install uno and other Python packages
###############################################################################
# Custom middleware plugin for the image
ARG UNO_MIDDLEWARE=

ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"
ENV UNO_PLUGINS_DIR "/uno/plugins"
ENV UNO_MIDDLEWARE  "${UNO_MIDDLEWARE}"
ENV UNO_VENV /opt/uno/venv

# Copy uno repository
COPY . ${UNO_DIR}

RUN set -xe; \
    # Delete .git directory
    rm -rf ${UNO_DIR}/.git; \
    # Generate new virtual environment
    python3 -m venv ${UNO_VENV}; \
    # Install all Python packages in the virtual environment
    . ${UNO_VENV}/bin/activate; \
    # Make sure pip and setuptools are up to date
    pip3 install -U pip setuptools; \
    # Check if the user passed a Connext wheel in the root of the context.
    # Try to install them iteratively (in sorted order), stop as soon as
    # one installs cleanly.
    for rti_whl in $(find ${UNO_DIR} -mindepth 1 -maxdepth 1 -name "rti.connext*$(uname -m).whl" | sort); do \
      if pip3 install -U ${rti_whl}; then \
        break; \
      fi; \
    done; \
    rm -f ${UNO_DIR}/*.whl; \
    # reinstall uno and the middleware in "editable" mode
    # so that they may be overwritten from the host (for development)
    pip3 install -U $([ -z "${DEV}" ] || printf -- -e ) \
      ${UNO_DIR}; \
    # Install uno middleware
    case "${UNO_MIDDLEWARE}" in \
      # default middleware requires Connext
      '') \
        pip3 install -U rti.connext; \
        ;; \
      *) \
        # Other middleware plugins must be installed
        pip3 install -U $([ -z "${DEV}" ] || printf -- -e ) \
          ${UNO_PLUGINS_DIR}/${UNO_MIDDLEWARE}; \
        ;; \
    esac; \
    # Create ${UVN_DIR}
    mkdir -p ${UVN_DIR}; \
    chmod 700 ${UVN_DIR}


###############################################################################
# Create a non-root user and give it passwordless sudo and SSH login
###############################################################################
RUN set -xe; \
    if [ -n "${TEST}${DEV}" ]; then \
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
      chown -R ${TEST_USER}:${TEST_USER} /home/${TEST_USER}/.ssh; \
    fi

###############################################################################
# Final touches
###############################################################################
# Set default work directory
WORKDIR /uvn

# Hard-code RTI license file
ENV RTI_LICENSE_FILE "/rti_license.dat"

# Add venv/bin to PATH so we don't have to activate it
ENV PATH "${UNO_VENV}/bin:${PATH}"

# Custom entrypoint
ENTRYPOINT [ "/uno/docker/entrypoint.sh" ]
CMD ["agent"]

# Mount point for an external UVN directory.
VOLUME ["${UVN_DIR}"]

# Mount point for an external copy of uno
VOLUME ["${UNO_DIR}"]
