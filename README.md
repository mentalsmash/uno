# uno

**uno** is a tool to link multiple LANs into a single routing domain over the public Internet.

LANs are interconnected by local agents deployed within them to act as gateways to
other LANs.

Agents use secure VPN links to establish a routing "backbone" where they
carry out the [OSPF protocol](https://en.wikipedia.org/wiki/Open_Shortest_Path_First)
to find routes to every other remote LAN.

VPN links are provisioned using [WireGuard](https://www.wireguard.com/), while
the [frrouting](https://frrouting.org/) suite is used to implement IP routing.

The configuration of each agent is automatically generated from a global manifest,
which defines all parameters of **uno**'s *unified virtual network* (UVN).

Agents will automatically discover local LANs by inspecting their active
network interfaces, and they will exchange this information using
[RTI Connext DDS](https://www.rti.com/products/connext-dds-professional).

The following diagram shows an example of a UVN interconnecting four LANs with
an agent in each LAN, and an extra, cloud-deployed, agent to provide redudant
backbone links:

![uvn example](docs/static/uvn.png "UVN Example")

## Installation

### Host Installation

**uno** is implemented using Python, and it only supports Linux hosts.
So far, it has only been tested on Ubuntu 22.04, but it should
be possible to run it on other distributions as well, provided that the
right system dependencies have been installed.

On Debian-like systems, **uno**'s system dependencies can be installed with the following packages:

```sh
sudo apt install \
  sudo \
  psmisc \
  iproute2 \
  iptables \
  python3-pip \
  wireguard-dkms \
  wireguard-tools \
  frr \
  iputils-ping \
  tar \
  qrencode \
  git 
```

After installing the system dependencies, you can install **uno** from
this git repository:

```sh
git clone https://github.com/mentalsmash/uno
pip install ./uno
```

**uno**'s agents use the RTI Connext DDS Python API, which requires a valid RTI license file to be provided separately. [You can request a free evaluation license from the RTI website](https://www.rti.com/free-trial).

In order to deploy an agent, you must copy the license file to the agent's shot, and export its absolute path through variable `RTI_LICENSE_FILE`:

```sh
export RTI_LICENSE_FILE=/path/to/rti_license.dat
```

### Docker Agent

**uno**'s agent can be deployed using a Docker container.
In order to do this, you must first build the image using
the `Dockerfile` included in this repository:

1. Install Docker Engine.

2. Clone this repository and build the container image:

   ```sh
   git clone https://github.com/mentalsmash/uno

   cd uno

   docker build -t uno:latest -f docker/Dockerfile .
   
   ```

3. Deploy agents using the generated image. The containers must be
   created with "privileged" credentials in order to be able to manipulate
   the host's network stack. You will also need to pass a valid
   RTI Connext DDS license file.

   Example invocation:

   ```sh
   docker run --rm --detach \
     -v /path/to/agent-dir:/uvn \
     -v /path/to/rti_license.dat:/rti_license.dat \
     -e CELL_ID=agent-id \
     --privileged \
     --net host \
     uno:latest
   ```

## UVN Setup

1. Create a new UVN registry:

   ```sh
   mkdir my-uvn

   cd my-uvn

   uvn registry init -n my-uvn -o "John Doe <john@example.com>"
   ```

2. Define two or more UVN "cells", one for every agent:

   ```sh
   uvn registry add-cell \
     --name lan-a \
     --address lan-a.my-organization.org \
     --network 192.168.1.0/24

   uvn registry add-cell \
     --name lan-b \
     --address lan-b.my-organization.org \
     --owner "Jane Doe <jane@example.com" \
     --network 192.168.2.0/24

   # ...

   uvn registry add-cell \
     --name cloud \
     --address cloud.my-organization.org
   ```

3. Optionally, define one or more UVN "particles", one for mobile user:

   ```sh
   uvn registry add-particle --name john

   uvn registry add-particle --name jane --owner "Jane Doe <jane@example.com"
   ```

4. Generate a deployment configuration for the UVN:

   ```sh
   uvn registry deploy
   ```

5. Copy each agent's configuration file to the host where it should be deployed using a secure
   method, e.g.:

   ```sh
   scp cells/lan-a.uvn-agent lan-a-agent-host:~/

   scp cells/lan-b.uvn-agent lan-b-agent-host:~/

   scp cells/lan-c.uvn-agent lan-c-agent-host:~/

   scp cells/lan-d.uvn-agent lan-d-agent-host:~/

   scp cells/cloud.uvn-agent cloud-agent-host:~/
   ```

6. You can perform all of the above steps in an automated way using an input configuration file.

   Create `uvn.yaml` with the following contents:

   ```yaml
   name: my-uvn
   owner: john@example.com
   owner_name: John Doe
   cells:
   - name: lan-a
     address: lan-a.my-organization.com
   - name: lan-b
     address: lan-b.my-organization.com
   - name: lan-c
     address: lan-c.my-organization.com
   - name: lan-d
     address: lan-d.my-organization.com
   - name: cloud
     address: cloud.my-organization.com
   particles:
   - name: john
   - name: jane
     owner: jane@example.com
     owner_name: Jane Doe
   ```

   Then use it to initialize the UVN:

   ```sh
   uvn registry init --from-file uvn.yaml -r my-uvn/
   ```

   You can also use a Docker container:

   ```sh
   mkdir my-uvn
   mv uvn.yaml my-uvn/

   docker run --rm \
     -v $(pwd)/my-uvn:/uvn \
     -v $(pwd)/uvn.yaml:/uvn.yaml \
     -e UVN_INIT=y \
     uno:latest
   ```

7. Install the agent on each host, e.g.:

   ```sh
   ssh lan-a.my-organization.org

   mkdir lan-a

   cd lan-a
   
   uvn cell bootstrap ~/lan-a.uvn-agent
   
   rm ~/lan-a.yaml
   ```

8. Configure NAT port forwarding to each agent's host for the following TCP ports:

   - `63550`: WireGuard interface to push configuration updates.
   - `63450-63452`: WireGuard interfaces for backbone links between cells.
   - `63449`: WireGuard interface for particle connections.

   - Enable `ospfd` and `zebra`:

     ```sh
     sed -i -r 's/^(zebra|ospfd)=no$/\1=yes/g' /etc/frr/daemons
     ```

   - Enable IPv4 forwarding, e.g.:

     ```sh
     echo 1 > /proc/sys/net/ipv4/ip_forward
     ```

9. Configure static routes on the LAN's router to designate the agent's host
   as the gateway for other LANs.

10. Start the agent:

    - Directly:

      ```sh
      cd lan-a/

      uvn cell agent
      ```

    - Or using Docker:

      ```sh
      cd lan-a/

      docker run \
        --net host \
        --privileged \
        -v $(pwd):/uvn \
        -v /path/to/rti_license.dat:/rti_license.dat \
        -e CELL_ID=lan-a \
        uno:latest
      ```
