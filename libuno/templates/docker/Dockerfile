FROM {{base_image}}

# Run apt via the non-interactive front-end
ENV DEBIAN_FRONTEND="noninteractive"

# Update apt database and install apt-utils (for debconf)
RUN apt-get -y update
RUN apt-get install -y apt-utils

# Install psmisc to have killall
RUN apt-get install psmisc
# Install iproute2 to provision `ip` command
RUN apt-get install -y iproute2
# Install python3-pip to provision `pip` command (and possibly `python`)
RUN apt-get install -y python3-pip
# Install gpg to handle keys and identities
RUN apt-get install -y gpg \
                       gnupg2
# Install wireguard to implement the uvn connections
{% if rpi_extra %}
# Add debian repository then install wireguard
RUN apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 \
                --recv-keys 04EE7237B7D453EC 648ACFD622F3D138 && \
    sh -c "echo 'deb http://deb.debian.org/debian/ unstable main' > /etc/apt/sources.list.d/debian-unstable.list" && \
    sh -c "printf 'Package: *\nPin: release a=unstable\nPin-Priority: 90\n' > /etc/apt/preferences.d/limit-debian-unstable" && \
    apt-get update && \
    apt-get install -y wireguard raspberrypi-kernel-headers
{% else %}
RUN apt-get install -y wireguard-dkms \
                       wireguard-tools
{% endif %}
# Install rng-tools to provision `rngd` and speed up key generation
RUN apt-get install -y rng-tools
# Install vim to have a decent text editor, and less for a decent pager
RUN apt-get install -y vim \
                       less
# Install some system services used by uvn
RUN apt-get install -y dnsmasq \
                       lighttpd
# Install quagga for the ospfd routing daemon
RUN apt-get install -y quagga
# Install qrencode to generate QR codes for particles
RUN apt-get install -y qrencode
# Enable zebra and ospfd in /etc/quagga/daemons
# RUN sed -r 's/(zebra|ospfd)=no/\1=yes/g' /etc/quagga/daemons
# Install useful networking utilities (and other external packages)
ARG APT_EXTRAS
RUN apt-get install -y iputils-ping \
                       iputils-tracepath \
                       dnsutils \
                       inetutils-traceroute \
                       ${APT_EXTRAS}

{% if rpi_extra %}
# Install additional apt dependencies for Raspberry Pi
RUN apt-get install libatlas-base-dev \
                    libopenjp2-7 \
                    libtiff5 \
                    libxcb1
{% endif %}

# Manually install Cython to fix build on Raspberry Pi
RUN pip3 install cython

# Copy pre-built wheel file for connextdds-py and install it
ARG CONNEXTDDS_WHEEL
COPY ${CONNEXTDDS_WHEEL} /opt/
ARG CONNEXTDDS_WHEEL
RUN pip3 install /opt/${CONNEXTDDS_WHEEL}

{% if ndds %}
# Copy Connext DDS
COPY ndds /opt/ndds
{% endif %}

# Install uno's Python dependencies explicitly.
# They would be installed with uno, but doing it in a
# separate stage allows Docker to cache the result and
# speed up the build time when the repository changes
RUN pip3 install pyyaml \
                 Jinja2 \
                 python-gnupg \
                 termcolor \
                 docker \
                 netifaces \
                 importlib-resources \
                 cherrypy \
                 networkx \
                 matplotlib \
                 python-daemon \
                 lockfile \
                 sh


{% if dev %}
# Define a volume to mount a development version of uno.
# The package will be installer by entrypoint.sh on start
RUN sh -c 'echo "export DEV=y" >> /root/bashrc'
VOLUME [ "/opt/uno" ]
{% else %}
# Copy uno repository from build context, and install it with `pip`.
# Use /opt/uno to match default non-containerized deployment
COPY uno /opt/uno
RUN pip3 install /opt/uno
{% endif %}

# Define a volume to pass the uvn configuration to the container
# Use /opt/uvn to match default non-containerized deployment
VOLUME [ "/opt/uvn" ]

# Define a custom entrypoint script which will run the default
# command or the one specified to the container.
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh
ENTRYPOINT [ "/entrypoint.sh" ]
CMD ["__default__"]
