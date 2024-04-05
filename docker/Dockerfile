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

RUN adduser --shell /bin/bash uno

# Copy uno
COPY . /uno-dev

ARG VERSION=2.1.2
ARG DEV=

RUN set -e; \
    rti_wheel=$(find /uno-dev/ -mindepth 1 -maxdepth 1 -name "rti.connext*.whl" | head -1); \
    if [ -e "${rti_wheel}" ]; then \
      pip3 install ${rti_wheel}; \
    fi; \
    if [ -n "${DEV}" ]; then \
      cp -r /uno-dev /uno; \
    else \
      git clone https://github.com/mentalsmash/uno -b ${VERSION} /uno; \
    fi; \
    pip3 install -e /uno


ARG PLUGINS=uno-middleware-connext@https://github.com/mentalsmash/uno-middleware-connext.git|1.1.0

RUN set -e; \
    if [ -n "${DEV}" -a -d "${DEV}/plugins" ]; then \
      cp ${DEV}/plugins /uno-plugins; \
    else \
      mkdir -p /uno-plugins; \
      for plugin in ${PLUGINS}; do \
        plugin_name=$(echo ${plugin} | cut -d@ -f1); \
        plugin_url=$(echo ${plugin} | cut -d@ -f2- | cut "-d|" -f1); \
        plugin_branch=$(echo ${plugin} | cut -d@ -f2- | cut "-d|" -f2); \
        plugin_dir=/uno-plugins/${plugin_name}; \
        git clone ${plugin_url} -b ${plugin_branch} ${plugin_dir}; \
        pip3 install -e ${plugin_dir}; \
      done; \
    fi

RUN rm -rf /uno-dev

# Custom entrypoint
ENTRYPOINT [ "/uno/docker/entrypoint.sh" ]
CMD ["__default__"]

# Define volumes
ARG UNO_MIDDLEWARE=uno_middleware_connext

ENV UNO_MIDDLEWARE  "${UNO_MIDDLEWARE}"
ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"

VOLUME [ "${UVN_DIR}" , "${UNO_DIR}"]

WORKDIR /uvn
