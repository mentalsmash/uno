# uno

**uno** is a tool for linking multiple LANs into a single routing domain over the public Internet.

LANs are interconnected by agent nodes which act as gateways to other LANs. The agent nodes
establish redudant VPN links between them to carry out the
[BGP protocol](https://en.wikipedia.org/wiki/Border_Gateway_Protocol) and find routes to every
other LAN.

Beside implementing the routing "backbone", each agent node also exposes a VPN port to allow
authorized mobile peers to access the unified routing domain, and route all their traffic through
the VPN link.

**uno** refers to this unified routing domain as a **unified virtual network** or **UVN** for short.
The **UVN** is composed of **cells** (a.k.a. agent nodes), **particles** (a.k.a. mobile peers), and
at least one **user** (the **UVN**'s **owner**).

The **UVN**'s configuration is defined in a centralized **registry**, which provides **cell agent packages**
to be copied onto each agent host. The packages contain all artifacts required to deploy the
**UVN** services on the host, and instantiate its **cell**.

The **registry** also contains a **particle package** for every **particle**, providing ready-to-use
VPN configurations to connect as that **particle** to any one of the **cells** with an active particle
VPN port.

**uno** supports dynamic reconfiguration of the UVN, which can be updated in the registry and
either pushed to **cells** with a publicly reachable address, or pulled by **cells** deployed
behind a NAT (in this case the registry must be deployed behind a public address). This feature
is optional, and **uno** can still be used to create entirely static deployments.

Dynamic reconfiguration requires the deployment of an **agent** process on each **cell**.
The **agents** will listen for connections from the **registry**, and they will also disseminate
status information between them. Each **agent** provides a status overview through a web inteface,
which can be accessed from anywhere within the **UVN**.

All VPN links are provisioned using [WireGuard](https://www.wireguard.com/), while
the [frrouting](https://frrouting.org/) suite is used to implement BGP routing.

The agents use [RTI Connext DDS](https://www.rti.com) to communicate between them,
and to exchange configuration updates with the registry.

The following diagram shows an example of a **UVN** interconnecting four LANs with
a **cell** in each LAN, and several **particles** connecting to them. All **cells**
in this example are reachable through a public address.

![uvn example](docs/static/uvn.png "UVN Example")

## Installation

**uno** is implemented using Python, and it only supports Linux hosts.
So far, it has only been tested on Ubuntu 22.04, but it should
be possible to run it on other distributions as well, provided that the
right system dependencies have been installed.

There are three officially supported methods of installation:

- From a [Docker image](#docker-images) (recommended).

- From a [Debian package](#debian-packages).

- From this repository using a [Python virtual environment](#python-virtual-environment).

### Docker Images

**uno** can be provisioned on a host using one of the prebuilt Docker images:

| Tag | Version | Base OS |
|-----|---------|------------|
| [`mentalsmash/uno:latest`](https://hub.docker.com/r/mentalsmash/uno/tags?page=&page_size=&ordering=&name=latest) |![latest default image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/29b57b0427def87cc3ef4ab81c956c29/raw/uno-badge-image-default-version-latest.json)|![latest default image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/2d53344e1ccfae961665e08432f18113/raw/uno-badge-image-default-base-latest.json)|
| [`mentalsmash/uno:nightly`](https://hub.docker.com/r/mentalsmash/uno/tags?page=&page_size=&ordering=&name=nightly) |![latest default image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/e7aab205f782cc0c6f394a2fece90509/raw/uno-badge-image-default-version-nightly.json)|![latest default image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/8f31c46dcfd0543b42f356e5b1c6c2c8/raw/uno-badge-image-default-base-nightly.json)|

The docker images allow **uno** to be used without installing any dependency other than [Docker](https://www.docker.com/):

```sh
docker run --rm mentalsmash/uno:latest uno -h
```

The images expect the **registry**/**agent** directory to be mounted in `/uvn`, which allows
you to persist files across runs. The images will also automatically pick up an RTI Connext DDS
license mounted at `/rti_license.dat`.

For example, to initialize a new **UVN** create a file named `uvn.yml`:

```yaml
# An "asymmetric" UVN with two cells, one behind NAT.
# The registry will be deployed within the "public" cell.
address: cell1.example.com
owner: john@example.com
users:
  - email: john@example.com
    name: John Doe
    password: johnspassword
  - email: jane@example.com
    name: Jane Doe
    password: janespassword
cells:
  - name: cell1
    address: cell1.example.com
    allowed_lans: [192.168.1.0/24]
  - name: cell2
    allowed_lans: [192.168.2.0/24]
    owner: jane@example.com
particles:
  - name: john
  - name: jane
    owner: jane@example.com
```

Mount `uvn.yml` on a container and use `uno define uvn` to initialize the **registry** (using the
`define` alias):

```sh
mkdir my-uvn/
chmod 700 my-uvn/

docker run --rm \
  -v $(pwd)/my-uvn:/uvn \
  -v $(pwd)/uvn.yml:/uvn.yml \
  -v $(pwd)/rti_license.dat:/rti_license.dat \
  mentalsmash/uno:latest \
  define my-uvn -s /uvn.yml

# See the generated cell agent and particle packages:
ls -l my-uvn/cells my-uvn/particles
```

The images make it easy to deploy agents by mounting their package as `/package.uvn-agent`:

```sh
mkdir -p my-uvn/cell1
chmod 700 my-uvn/cell1

docker create \
  --init \
  --name my-uvn-cell1 \
  --net host \
  --privileged \
  -v $(pwd)/my-uvn__cell1.uvn-agent:/package.uvn-agent \
  -v $(pwd)/my-uvn:/uvn \
  --restart always \
  --stop-signal SIGINT \
  mentalsmash/uno:latest \
  agent

docker start my-uvn-cell1
```

The images can be passed any arbitrary command, but they also support some special "actions"
which act as aliases to some commonly used `uno` CLI commands

| Action | Description | CLI command |
|--------|-------------|------------------------|
|`agent`|Run the **agent** instance for a **cell** or the **registry** | `uno agent ...` |
|`define`|Initialize a new UVN **registry** | `uno define uvn ...` |
|`down`|Disconnect the host from the **UVN**. Only useful with `--net host`.| `uno service down ...`|
|`redeploy`|Regenerate **UVN** deployment configuration in the **registry** | `uno redeploy ...` |
|`sync`|Enable the **registry**'s **agent** to make sure that all **cells** are at the latest **UVN** configuration.| `uno sync ...`|
|`up`|Connect the host to the **UVN**. Only useful with `--net host`.| `uno service up ...`|

The special action `fix-root-permissions` is available to
make sure that all files generated by a container (which runs as `root`) are owned by the correct user:

```sh
docker run --rm -v $(pwd)/my-uvn mentalsmash/uno:latest fix-root-permissions $(id -u):$(id -g)
```

### Debian Packages

Pregenerated `.deb` packages for `amd64` and `arm64` hosts are available on the [Releases page](https://github.com/mentalsmash/uno/releases).

The packages contain a "bundled" version of **uno** generated with [PyInstaller](https://pyinstaller.org/),
which is tested on Ubuntu 22.04, but should run on other similar distributions too.

After downloading the package, install it with `apt`:

```sh
apt install /path/to/uno_<version>_<arch>.deb

uno -h
```

**uno** will be installed under `/opt/uno`, and it will be automatically available in the `PATH`
via a symlink in `/usr/bin/`.

### Python Virtual Environment

**uno** can be installed manually from this repository, using a Python Virtual Environment.

When using this installation method, all of **uno**'s system dependencies must be already
provisioned on the system. On Debian-like systems, this can be achieved by installing
the following packages:

```sh
sudo apt install --no-install-recommends \
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
  wireguard-tools
```

After installing the system dependencies, clone **uno** and install
it in fresh virtual environment. It is recommended to install **uno**
with root credentials to prevent other users from being able to
modify its installation.

```sh
mkdir -p /opt/uno

cd /opt/uno

git clone https://github.com/mentalsmash/uno -b <tag> src

python3 -m venv -m venv

. ./venv/bin/activate

pip3 install ./src

# You can skip this step if you are creating a static deployment 
pip3 install rti.connext
```

The executable `/opt/uno/venv/bin/uno` can be used directly without
first activating the virtual environment. You can add the `/opt/uno/venv/bin/`
directory to `PATH` for quicker access (or just link the executable to
a directory already in your `PATH`, e.g. `/usr/local/bin`).

## Step-by-Step UVN Setup

1. Create a new UVN registry.

   At a minimum, you must specify a name for the UVN, and the identity of the UVN's
   administrator.

   The UVN registry must be initialized in an empty (or non-existent) directory,
   and it is created using command `uno define uvn`:

   ```sh
   # initialize the UVN registry
   mkdir my-uvn

   # WARNING: Protect access to this directory because it contains secrets.
   chmod 700 my-uvn
   
   cd my-uvn

   # Create the uvn and the root user
   RTI_LICENSE_FILE=/path/to/rti_license.dat \
     uno define uvn my-uvn \
       -o "John Doe <john@example.com>" \
       -p userpassword
   ```

2. Define one or more UVN "cells".

   Each cell represents an agent that will be
   deployed to an host to attach one or more LANs to the UVN.

   Every cell must be assigned a unique name, and it will be assigned
   a numerical id in order of registration (starting with 1).

   A cell may be assigned a public address which will be used by
   other nodes to establish VPN connection.

   If a cell doesn't have a public address, uno will assume the agent
   is deployed behind a NAT, and it will configure it to connect
   to other cells that are publicly reachable. Privately deployed
   cells will not be available for particle connections.

   In order to be deployed, a UVN requires at least one public cell.

   Every cell must be configured with list of local networks they
   will be attaching to the UVN. This allows uno to validate the UVN's
   configuration by checking that no conflicts will be present in
   the unified routing domain.

   The list will also be used by each
   agent to filter their active network interface, and only announce
   relevant ones to the routing domain.

   An agent will fail to start if it can't detect the expected networks.

   If an agent's cell has an empty list of networks, the agent will operate
   in "roaming" mode, and only act as an additional router for the UVN.

   Cells are added with command `uno define cell`:

   ```sh
   # Define a cell owned by the root user
   uno define cell lan-a \
     -a lan-a.my-organization.org \
     -N 192.168.1.0/24

   # Define a cell owned by another user
   uno define user jane@example.com \
     -n "Jane Doe"
     -p userpassword

   uno define cell lan-b \
     -a lan-b.my-organization.org \
     -o jane@example.com \
     -N 192.168.2.0/24

   # ...

   ```

3. Optionally, define one or more UVN "particles".

   Each particle represents a mobile user that is authorized to connect to the UVN
   through any of the publicly reachable cells with an active Particle VPN port.

   uno will generate a set of WireGuard configurations for every particle,
   one for every cell the particle can connect to.

   The configurations can be easily imported into mobile WireGuard clients using QR codes.

   Once connected, all traffic will be forwarded through the VPN link, allowing the
   particle to access all of the UVN's hosts, but also to reach the public Internet's through the
   cell's local gateway.

   Particle are registered using command `uno define particle`:

   ```sh
   uno define particle john

   uno define particle jane -o jane@example.com
   ```

4. Generate a deployment configuration for the UVN.

   A deployment configuration defines the "backbone" links that the UVN agents will
   be establish between each other to carry out the routing protocol.

   These links are generated using one of the available strategies:

   - *crossed*: default strategy. Public cells are ordered in a "circular buffer", and they are
     assigned up to 3 backbone links between them: the cells before them, the cell after them, and
     the cell across them (this last one is skipped for the last cell, if odd numbered).
     Private cells are evenly divided between each public cell (which are assigned an additional
     backbone link for every private cell). Each private cell has a single backbone link to its
     assigned public cell.

   - *circular*: similar to *crossed*, but it only assigns 2 links to public cells (the previous
     and the following).

   - *full-mesh*: allocate a full mesh of backbone connection between all cells. Every cell will be
     connected to every other cell with a public address.

   - *static*: specify a static configuration. The configuration is specified as a dictionary mapping
     each cell to its peers.
  
   - *random*: experimental strategy which tries to build a fully routed, redudant graph between cells
     by randomly exploring it. The algorithm will allocate up to "# of cells" links for every
     public cell, and up to 2 backbone links for every private cell. The algorithm is quite naive, and
     it may fail to generate a valid graph.

   The deployment configuration is generated (or updated) automatically whenever any relevant
   configuration setting is changed. It can also be updated explicitly using command `uno redeploy`.

5. Generate agent bundles and deploy them to each agent's target host.

   A `*.uvn-agent` file will be created for every cell agent under directory `<registry-root>/cells/`.

   These bundles must be securely copied to the hosts where each agent is to be deployed.

   Once copied, the bundles can be extracted using command `uno cell install`, which
   will initialize the agent's root directory.

   After extracting the agent's directory, the agent may be installed as a service
   using command `uno cell service enable`.

   For example:

   ```sh
   # Copy agent bundle to target host.
   scp cells/lan-a.uvn-agent lan-a-agent-host:~/

   # Log into the target host.
   ssh lan-a-agent-host

   # Install the agent package
   sudo uno install lan-a.uvn-agent -r /opt/uvn

   # WARNING: Protect access to this directory because it contains secrets.
   sudo chmod 700 /opt/uvn

   # Delete the package
   rm lan-a.uvn-agent

   # Install the agent as a systemd unit, enabled it at boot, and start it
   sudo uno service install -r /opt/uvn -a -b -s

   # Check the agent service logs
   journalctl -xeu uvn-agent

   # Check the agent's HTML status page
   firefox https://lan-a-agent-host

   # Delete systemd unit
   sudo uno service remove -r /opt/uvn
   ```

6. Configure port forwarding to the agents of every public cell.

   UVN agents use the following UDP ports:

   - `63447`: used by private cells to connect to the registry (e.g. to pull new configurations).
   - `63448`: used by the registry to connect to public cells (e.g. to push new configurations).
   - `63449`: used by cells to allow particle connections.
   - `63550` - `63550 + N`: ports used to establish backbone links between cells. The exact number
     depends on the deployment strategy used.

7. Configure static routes on the LAN's router to designate the agent's host
   as the gateway for other remote LANs.

