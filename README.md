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
curl -sSL https://raw.githubusercontent.com/mentalsmash/uno/master/bin/install.sh | sh
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
   git clone https://github.com/mentalsmash/uno.git
   ```

5. Install **uno** and the `uvn` command with `pip`:

   ```sh
   pip install -e uno/
   ```

   You can omit the `-e` option if you don't plan on making changes to the
   source code, and don't need them to be automatically propagated to your
   environment. If you don't specify `-e`, you will need to reinstall **uno**
   every time you update the repository's clone.

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

Or, using the provided `install.sh` script, install wheel automatically along with **uno**:

```sh
scp rti-0.0.1-cp37-cp37m-linux_armv7l.whl pi@myrpi:~/
ssh pi@myrpi sh -c "curl -sSL https://raw.githubusercontent.com/mentalsmash/uno/master/bin/install.sh | sh"
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

This section describes the main steps involved in the configuration and
deployment of a *UVN*.

For a quick test of this process, run [test/simple_validation.sh](test/simple_validation.sh):

```sh
# Generate a test UVN and spawn the registry agent
uno/test/simple_validation.sh
# Delete generated files
rm -r test-uvn.localhost test-uvn.localhost-cells
```

### Create a new UVN configuration

A *UVN* must be associated with a unique domain name, e.g. `test-uvn.localhost`.
The domain identifies the *UVN*, and it specifies the address that *agents* will
use to connect to the *registry*.

A *UVN*'s configuration consists of a few YAML files and a database of PGP/GPG
keys. These should be stored in a dedicated directory with appropriate
permissions that prevent unauthorized access to the *UVN*'s secrets.

During deployment, these configuration files must be stored on the *registry*
node and available to the the registry's *agent* (or "root" *agent*), who is
responsible for generating new deployment configurations, and must be able to access
confidential information in order to configure the *UVN*'s encrypted links.

A new *UVN* configuration can be generated with `uvn create`, e.g.:

```sh
uvn create test-uvn.localhost
```

This command will create a new directory `test-uvn.localhost/`, containing *UVN*
`test-uvn.localhost`. The *UVN* is still empty, since no *cell* has been
attached to it yet.

The new directory will contain a `registry.yml` file, describing the registry's
configuration, and signed with the registry's own private key, and a `keys/`
directory, which stores the registry's GPG key database. The database is
initialized only with the registry's private and public key pair. The private
key is protected by a randomly generated password (see [Manipulating the UVN registry](#manipulating-the-uvn-registry)).

The root *agent* must be configured to listen for connections on the *UVN*'s
own address, and the following ports must be forwarded to it:

| Port | Protocol | Description    |
|------|----------|----------------|
|63550 | UDP      |Port used by the root *agent* to listen for initial connections from cell *agents*|
|33000-35000|UDP  |Ports used by the root *agent* to establish routing links with each cell *agent*|

### Manipulating the UVN registry

All commands that manipulate the *UVN* registry must provide the secret for the
registry's private key, or fail with an authentication error.

`uvn` will load the secret from the environment via variable `AUTH`, or fall
back to file `.uvn-auth` in the current directory, if the variable is not set.

For the moment, `uvn create` will store the registry's random password in
`<uvn-root>/.uvn-auth`. This makes testing easier, since `uvn` can be invoked
simply by first `cd`'ing into the *UVN*'s directory.

File `.uvn-auth` (and other files storing *cell* secrets) should be deleted
from the *UVN* directory before the root *agent* is deployed to a public setting.

Since all commands must load `.uvn-auth`, you can run them in a subshell to avoid
changing your current directory.

For example, you can display summary information about a *UVN* using `uvn info`:

```sh
(cd test-uvn.localhost && uvn i -v)
```

This can get tedious, and you might prefer to move your *UVN* configuration to
some "stable" location (e.g. `/opt/uvn`), and define a shell function to
automatically enter that directory before running `uvn`.

For example, you could add this shell function to your `~/.profile` file:

```sh
uvnd()
{
    local uvn_dir="${UVN_DIR:-/opt/uvn}"
    (cd uvn_dir && uvn $@)
}
```

Using `uvnd` instead of `uvn`, you will then be able to manipulate the *UVN* in
`/opt/uvn` without the need to `cd` to the directory first.

E.g. to display summary information:

```sh
uvnd i -v
```

Arbitrary *UVN* directories can be accessed by setting `UVN_DIR`:

```sh
# Access $(pwd)/test-uvn.localhost/
UVN_DIR=test-uvn.localhost uvnd i -v
```

Setting the value of `UVN_DIR` modifies the default *UVN* directory. Use
absolute paths to be able to issue commands from anywhere in the filesystem.

```sh
# Make $(pwd)/test-uvn.localhost the default UVN directory
export UVN_DIR=$(pwd)/test-uvn.localhost
uvnd i -v
```

### Attach cells to the UVN

In order to attach private networks to the *UVN*, one must first define *cell*
configurations for each *agents* that will be deployed within each LAN.

Each *cell* contains an *agent*, and it must choose a unique name which will
identify them within the *UVN*. A public domain name or IP address must also be
provided so that other *agents* may connect to the *cell*.

*Cells* can be defined using the `uvn attach` command:

```sh
(cd test-uvn.localhost && uvn a -n cell1)
```

This command will define a new *cell* called `cell1` whose address is
`cell1.test-uvn.localhost`. You can specify an arbitrary address with option
`--address ADDRESS`.

By default, **uno** requires *cells* to enable forwarding to their *agents* of
UDP ports 63450, 63451, and 63452.

These will be used to establish the routing links that make up the *UVN*'s
*backbone*. Custom values can be specified using option `--peer-ports PORTS`.
The `PORTS` valus must be a valid YAML/JSON array value, e.g. `"[ 1, 2, 3 ]"`
