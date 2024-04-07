ARG BASE_IMAGE="ubuntu:jammy"
FROM ${BASE_IMAGE}

ARG EXTRAS

# Update apt database and install apt-utils (for debconf)
# Install psmisc to have killall
# Install iproute2 to provision `ip` command
# Install iptables to control kernel routing
# Install python3-pip to provision `pip` command (and possibly `python`)
# Install gnupg2 to handle keys and identities
# Install wireguard to implement the uvn connections
# Install rng-tools to provision `rngd` and speed up key generation
# Install vim to have a decent text editor, and less for a decent pager
# Install frr for the ospfd routing daemon
# Install qrencode to generate QR codes for particles
# Install some system services used by uvn
# Install useful networking utilities (and other external packages)
RUN export DEBIAN_FRONTEND="noninteractive" \
    && apt-get update \
    && apt-get install -y \
      python3-venv \
      python3-pip \
      psmisc \
      iproute2 \
      iptables \
      gnupg2 \
      wireguard-dkms \
      wireguard-tools \
      frr \
      qrencode \
      iputils-ping \
      lighttpd \
      openssl \
      git \
      $([ -z "${EXTRAS}" ] || \
        echo \
          rng-tools \
          vim \
          less \
          iputils-tracepath \
          dnsutils \
          inetutils-traceroute \
          netcat \
          iperf \
          iperf3 \
          tcpdump \
          curl \
          elinks \
          net-tools \
          build-essential \
          cargo \
          sqlite3 \
      ) \
    && apt-get clean

# Copy uno
COPY . /uno-dev

# Install everything in a virtual environment
# Add venv/bin directory to the top of PATH
# so we don't have to activate it
ENV UNO_VENV /opt/uno/venv
RUN python3 -m venv ${UNO_VENV}
ENV PATH "${UNO_VENV}/bin:${PATH}"

# Check if the user passed a Connext wheel in the context
RUN set -e; \
    rti_wheel=$(find /uno-dev/ -mindepth 1 -maxdepth 1 -name "rti.connext*.whl" | head -1); \
    if [ -f "${rti_wheel}" ]; then \
      pip3 install ${rti_wheel}; \
    fi

# Allow the user to install the local clone, otherwise
# Clone the selected version from the remote repository
ARG UNO_VERSION=master
ARG UNO_URL=https://github.com/mentalsmash/uno
ARG LOCAL=
RUN set -e; \
    if [ -n "${LOCAL}" ]; then \
      cp -r /uno-dev /uno; \
      pip3 install pytest; \
    else \
      git clone ${UNO_URL} -b ${UNO_VERSION} /uno; \
    fi; \
    pip3 install -e /uno

# Install some plugins.
ARG PLUGINS=uno-middleware-connext@https://github.com/mentalsmash/uno-middleware-connext.git|master

RUN set -e; \
    mkdir -p /uno-plugins; \
    for plugin in ${PLUGINS}; do \
      plugin_name=$(echo ${plugin} | cut -d@ -f1); \
      plugin_url=$(echo ${plugin} | cut -d@ -f2- | cut "-d|" -f1); \
      plugin_branch=$(echo ${plugin} | cut -d@ -f2- | cut "-d|" -f2); \
      plugin_dir=/uno-plugins/${plugin_name}; \
      git clone ${plugin_url} -b ${plugin_branch} ${plugin_dir}; \
      pip3 install -e ${plugin_dir}; \
    done

# Make sure locale is en_US.UTF-8
RUN apt-get update \
    && set -e \
    && if [ "$(. /etc/os-release && echo $ID)" = ubuntu ]; then \
      apt-get install -y --no-install-recommends \
          locales  \
      && apt-get clean \
      && locale-gen en_US en_US.UTF-8 \
      && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8; \
    else \
      apt-get install -y --no-install-recommends \
          locales \
          locales-all \
      && apt-get clean \
      && update-locale LC_ALL=en_US.utf8 LANG=en_US.utf8; \
    fi

ENV LANG en_US.UTF-8

# Create a non-root user
# For DEV mode, also install openssh-server, openssh-client, and (passwordless) sudo.
# Also configure uno-dev/docker/dev/test_key.ed25519.key as an authorized key
# and install it as the user's private key
ARG USER="uno"
ARG DEV=
RUN set -xe; \
    if [ -n "${DEV}" ]; then \
      apt-get update; \
      apt-get install -y --no-install-recommends sudo openssh-server openssh-client; \
      apt-get clean; \
    fi; \
    adduser ${USER} --shell /bin/bash; \
    if [ -n "${DEV}" ]; then \
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
    fi

# Clean-up uno repository
RUN rm -rf /uno-dev

# Make sure IPv4 forwarding is disabled in the image by default
RUN sysctl -w net.ipv4.ip_forward=0

# Custom entrypoint
ENTRYPOINT [ "/uno/docker/entrypoint.sh" ]
CMD ["__default__"]

# Define volumes
# ARG UNO_MIDDLEWARE=uno_middleware_connext

# ENV UNO_MIDDLEWARE  "${UNO_MIDDLEWARE}"
ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"

VOLUME [ "${UVN_DIR}" , "${UNO_DIR}"]

WORKDIR /uvn
