# uno

**uno** is a tool for interconnecting private LANs into a
**unified virtual network**, or *UVN*, that supports fully routed,
site-to-site communications via dynamically managed encrypted links.

The *UVN* is composed of multiple *cells*, each one containing one or
more private networks, and managed by an *agent*.

*Agents* connect to a common *registry* node, which administers the *UVN*,
and provisions each *agent* with the latest *deployment configuration*. This
specifies the encrypted links that each *agent* will establish with other *cells*
in order to form the *UVN*'s routing *backbone*.

*Agents* use [RTI Connext DDS](https://www.rti.com/products/connext-dds-professional)
to exchange information about their local networks and their operational status,
over encrypted [WireGuard](https://www.wireguard.com/) links that connect them 
to each other, and to the registry node.

Once information about remote sites is available, and the VPN links have been
properly configured, the [Quagga](https://www.nongnu.org/quagga/) routing suite
is used to implement the OSPF protocol between all nodes, and to enable complete
routing paths between all attached networks.

*Agents* should be run in a dedicated host deployed within each LAN, and
configured as the default gateway for other networks in the *UVN*, in order to
allow transparent routing between all hosts.

An *agent* can also act as a DNS server for hosts in their attached LANs. The
server will automatically include entries for the dynamic VPN endpoints in
the *UVN*, in addition to any custom entry added to the *UVN*'s
configuration.

## Installation

The easiest way to install UNO is via the simplified installation script:

```sh
curl -sSL https://raw.githubusercontent.com/asorbini/uno/master/bin/install.sh?token=AAKLA5IHD5KHZMYXYH2ALMC74UJQ2 | sh
```

If you have a pre-built wheel file for `connextdds-py` (e.g. if installing on
a Raspberry Pi), place the file in the directory where you are running the
installation script, and the script will automatically detect it and offer to
use it.

If a wheel file is not available, the script will build `connextdds-py` from source
after cloning its repository.
[RTI Connext DDS](#rti-connext-dds) must be already installed
with the correct libraries for the target, and available via `NDDSHOME`.

If you prefer an alternative installation method, follow the steps described in
the next section to perform the installation manually.

### Installation steps

1. Install the required [system dependencies](#system-dependencies).

2. Install [RTI Connext DDS and connextdds-py](#rti-connext-dds).

3. Optionally, install [Docker](#docker).

4. Clone this repository:

   ```sh
   git clone https://github.com/asorbini/uno.git
   ```

5. Install **uno** and the `uvn` command with `pip`:

   ```sh
   pip install -e /path/to/uno
   ```

   You can omit the `-e` option if you don't plan on making changes to the
   source code, and don't need them to be automatically propagated to your
   environment.

### System Dependencies

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
               dnsutils
```

### RTI Connext DDS

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

#### Raspberry Pi Installation

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

### Docker

**uno** supports deploying *agents* inside a Docker container, and the `uvn`
command can be used to build a local image for this purpose.

Follow the [instructions on Docker's website](https://docs.docker.com/engine/install/)
for more information on how to install Docker

If a package is not available for your distro (e.g. if you are using Raspbian),
you can use the shell installation script:

```sh
curl -sSL https://get.docker.com | sh
```

## Hello UVN

**uno** provides the `uvn` command line tool for configuring a *UVN* and its
*cells*, and for instantiating *agents* to deploy it.

### Create a new *UVN* configuration

A *UVN* must be associated with a unique domain name, e.g. `myuvn.foo.bar`.
The domain identifies the *UVN*, and it specifies the address that *agents* will
use to connect to the *registry*.

A *UVN*'s configuration consists of a few files YAML files and a database
of PGP keys. These should be stored in a dedicated directory with appropriate
permissions that prevent unauthorized access to the *UVN*'s secrets.

These files must be stored on the *registry* node, which is responsible for
generating new deployment configurations, and must be able to access
confidential information in order to configure the *UVN*'s encrypted links.

A new *UVN* configuration can be generated with `uvn create`, e.g.:

```sh
uvn create myuvn.foo.bar
```

This will create a new directory `myuvn.foo.bar/`, initialized with an empty
UVN configuration (since it still has no *cells* attached to it).

...
