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
      ) \
    && apt-get clean

RUN adduser --shell /bin/bash uno

# Copy uno
COPY . /uno-dev

ARG VERSION=master
ARG DEV=

ADD https://api.github.com/repos/mentalsmash/uno/commits?sha=${VERSION}
RUN set -e; \
    if [ -n "${DEV}" ]; then \
      wheel=$(find /uno/ -mindepth 1 -maxdepth 1 -name "rti.connext*.whl" | head -1); \
      if [ -e "${wheel}" ]; then \
        pip3 install ${wheel}; \
      fi; \
      cp -r /uno-dev /uno; \
      pip3 install -e /uno; \
    else \
      rm -rf /uno-dev; \
      git clone https://github.com/mentalsmash/uno -b ${VERSION} /uno; \
    fi

# Custom entrypoint
ENTRYPOINT [ "/uno/docker/entrypoint.sh" ]
CMD ["__default__"]

# Define volumes
ENV UVN_DIR "/uvn"
ENV UNO_DIR "/uno"

VOLUME [ "${UVN_DIR}" , "${UNO_DIR}"]

WORKDIR /uvn
