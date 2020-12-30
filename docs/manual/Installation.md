# Installation

* [Installation steps](#installation-steps)
* [System Dependencies](#system-dependencies)
* [RTI Connext DDS](#rti-connext-dds)
* [Docker](#docker)

## Installation steps

1. Install the required [system dependencies](#system-dependencies).

2. Install [RTI Connext DDS and connextdds-py](#rti-connext-dds).

3. Optionally, install [Docker](#docker).

4. Clone this repository:

   ```sh
   git clone https://github.com/mentalsmash/uno.git
   ```

5. Install **uno** and the `uvn` command with `pip`:

   ```sh
   pip3 install -e uno/
   sudo pip3 install -e uno/
   ```
 
   Only **uno**'s agents must be run as root (and that will hopefully change eventually),
   so you must only install **uno** for root if you plan on running an agent on the host.

   You can omit the `-e` option if you don't plan on making changes to the
   source code, and don't need them to be automatically propagated to your
   environment. If you don't specify `-e`, you will need to reinstall **uno**
   every time you update the repository's clone.

## System Dependencies

**uno** supports any modern Linux system with access to Python 3.6+,
WireGuard and a few other dependecies, but it has only been tested on
Ubuntu 18.04+ so far.

The following system dependencies must be available:

- Python 3.6+ (with `pip`)
- GnuPG.
- WireGuard's kernel module, and the `wg` command line tools.
- Quagga's `zebra` and `ospfd` daemons.
- The `ip` command from iproute2.
- `dnsmasq` for DNS provisioning.
- `ping`, `traceroute`, and `dig` for testing the *UVN*.
- `qrencode` to generate configuration QR codes.

All required dependencies can be installed on Ubuntu with:

```sh
apt install -y iproute2 \
               python3-pip \
               gpg \
               gnupg2 \
               wireguard-dkms \
               wireguard-tools \
               dnsmasq \
               quagga \
               iputils-ping \
               inetutils-traceroute \
               dnsutils \
               qrencode \
               tmux \
               screen
```

Optionally, you may install Docker to take advantage of uno's support for containerized deployments. Please refer to [Docker's documentation](https://docs.docker.com/engine/install/) on how to install Docker Engine on your system.

### Raspberry Pi Dependencies

On Raspbian, the following system dependencies must also be installed manually:

```sh
apt install -y libatlas-base-dev \
               libopenjp2-7 \
               libtiff5 \
               libxcb1
```

WireGuard must also be installed manually, by first adding the Debian apt repository (as root):

```sh
apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 \
                --recv-keys 04EE7237B7D453EC 648ACFD622F3D138
echo 'deb http://deb.debian.org/debian/ unstable main' > /etc/apt/sources.list.d/debian-unstable.list
printf 'Package: *\nPin: release a=unstable\nPin-Priority: 90\n' > /etc/apt/preferences.d/limit-debian-unstable
apt-get update 
apt-get install -y wireguard raspberrypi-kernel-headers
```

### Python Dependencies

All Python dependencies required by **uno** will be automatically installed by `pip`.

If you prefer to provising them manually, you can run the following command:

```sh
pip3 install pyyaml \
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
```

## RTI Connext DDS

**uno** relies on RTI Connext DDS 6 to exchange data between *agents*.

RTI Connext DDS and the [connextdds-py](https://github.com/rticommunity/connextdds-py) 
module must be manually installed on the target system before running the `uvn` command.

You can [request a free version of RTI Connext DDS from RTI](https://www.rti.com/free-trial).

With the downloaded packages at hand, follow [RTI's documentation to install them](https://community.rti.com/static/documentation/connext-dds/6.0.1/doc/manuals/connext_dds/getting_started/cpp98/before.html#installing-connext-dds), and configure `NDDSHOME` to point to the installation directory.

Once Connext is available on the sytem, clone and install [connextdds-py](https://github.com/rticommunity/connextdds-py). E.g. on a system using target `x64Linux4gcc7.3.0`:

```sh
pip install -U wheel \
               setuptools \
               cmake \
               patchelf-wrapper
git clone https://github.com/rticommunity/connextdds-py
cd connextdds-py
python configure.py x64Linux4gcc7.3.0
python install .
```

### RTI Connext DDS for Raspberry Pi

Since `connextdds-py` fails to build natively on Raspberry Pi 3 because of memory
exhaustion, a docker container provided by [rticonnextdds-docker-crosscompile](https://github.com/asorbini/rticonnextdds-docker-crosscompile)
can be used to cross-compile a wheel archive using Qemu.

Once you have generated `rti-0.0.1-cp37-cp37m-linux_armv7l.whl`, copy it to
your Raspberry Pi, and install it with `pip`:

```sh
scp rti-0.0.1-cp37-cp37m-linux_armv7l.whl pi@myrpi:~/
ssh pi@myrpi
pip3 install rti-0.0.1-cp37-cp37m-linux_armv7.whl
```

Or, using the simplified installer script, you can install the
wheel automatically if found in the current directory:

```sh
scp rti-0.0.1-cp37-cp37m-linux_armv7l.whl pi@myrpi:~/
ssh pi@myrpi
curl -sSL https://uno.mentalsmash.org/install | sh
```

## Docker

**uno** supports deploying *agents* inside a Docker container, and the `uvn`
command can be used to build a local image for this purpose.

Follow the [instructions on Docker's website](https://docs.docker.com/engine/install/)
for more information on how to install Docker

If a package is not available for your distro (e.g. if you are using Raspbian),
you can use the shell installation script:

```sh
curl -sSL https://get.docker.com | sh
```
