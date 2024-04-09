# uno

**uno** is a tool to link multiple LANs into a single routing domain over the public Internet.

LANs are interconnected by local agents deployed within them to act as gateways to
other LANs.

Agents use secure VPN links to establish a routing "backbone" where they
carry out the [BGP protocol](https://en.wikipedia.org/wiki/Border_Gateway_Protocol)
to find routes to every other remote LAN.

VPN links are provisioned using [WireGuard](https://www.wireguard.com/), while
the [frrouting](https://frrouting.org/) suite is used to implement IP routing.

The configuration of each agent is automatically generated from a global manifest,
which defines all parameters of **uno**'s *unified virtual network* (UVN).

The following diagram shows an example of a UVN interconnecting four LANs with
an agent in each LAN, and an extra, cloud-deployed, agent to provide redudant
backbone links:

![uvn example](docs/static/uvn.png "UVN Example")

## Project Status

| Release | Nightly |
|:-------:|:-------:|
|[![latest release](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/fb644ccb3cbb57b2636f9eca808b9931/raw/uno-badge-latest-release.json)](https://github.com/mentalsmash/uno/actions/workflows/ci-release.yml)|[![nightly](https://github.com/mentalsmash/uno/actions/workflows/ci-nightly.yml/badge.svg?branch=master)](https://github.com/mentalsmash/uno/actions/workflows/ci-nightly.yml)|

| Docker Image | Version | Base Image |
|:------------:|:-------:|:----------:|
| [mentalsmash/uno:latest](https://hub.docker.com/repository/docker/mentalsmash/uno/tags?page=&page_size=&ordering=last_updated&name=latest) |![latest default image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/29b57b0427def87cc3ef4ab81c956c29/raw/uno-badge-image-default-version-latest.json)|![latest default image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/2d53344e1ccfae961665e08432f18113/raw/uno-badge-image-default-base-latest.json)|
| [mentalsmash/uno:latest-static](https://hub.docker.com/repository/docker/mentalsmash/uno/tags?page=&page_size=&ordering=last_updated&name=latest) |![latest static image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/d73e338805c7d2c348a2d7149a66f66c/raw/uno-badge-image-static-version-latest-static.json)|![latest static image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/373e55438055b1222c9937797c949f9b/raw/uno-badge-image-static-base-latest-static.json)|
| [mentalsmash/uno:nightly](https://hub.docker.com/repository/docker/mentalsmash/uno/tags?page=&page_size=&name=nightly&ordering=last_updated) |![latest default image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/e7aab205f782cc0c6f394a2fece90509/raw/uno-badge-image-default-version-nightly.json)|![latest default image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/8f31c46dcfd0543b42f356e5b1c6c2c8/raw/uno-badge-image-default-base-nightly.json)|
| [mentalsmash/uno:nightly-static](https://hub.docker.com/repository/docker/mentalsmash/uno/tags?page=&page_size=&name=nightly&ordering=last_updated) |![latest static image version](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/b310f08c34f051846877aeb59b0be311/raw/uno-badge-image-static-version-nightly.json)|![latest static image base image](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/asorbini/b0e38a84eb8679d5212e162fbb616773/raw/uno-badge-image-static-base-nightly.json)|

## Installation

### Host Installation

**uno** is implemented using Python, and it only supports Linux hosts.
So far, it has only been tested on Ubuntu 22.04, but it should
be possible to run it on other distributions as well, provided that the
right system dependencies have been installed.

On Debian-like systems, **uno**'s system dependencies can be installed with the following packages:

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
  python3-dev \
  python3-pip \
  python3-venv \
  qrencode \
  tar \
  xz-utils \
  wireguard \
  wireguard-tools
```

After installing the system dependencies, you can install **uno** from
this git repository and [one of the available middlewares](#middleware-setup):

```sh
git clone https://github.com/mentalsmash/uno

# Alternatively, you can install uno as a regular user if you plan
# on using the host only to manage the UVN's registry,
# A virtual environment installation is recommended in this case.
python3 -m venv -m uno-venv
. ./uno-venv/bin/activate
pip install ./uno
```

## Middleware Setup

`uno` supports different "middleware backends" to implement communication between agents.

Select and install one of the available plugins:

- "native" middleware: this middleware is included with `uno`, and it does not support deployment of agents.

- [uno-middleware-connext](https://github.com/mentalsmash/uno-middleware-connext): implementation based on [RTI Connext DDS](https://www.rti.com/products/connext-dds-professional).

  ```sh
  git clone https://github.com/mentalsmash/uno-middleware-connext

  . ./uno-venv/bin/activate
  pip install ./uno-middleware-connext
  ```

## UVN Setup

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
   UNO_MIDDLEWARE=uno_middleware_connext \
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
