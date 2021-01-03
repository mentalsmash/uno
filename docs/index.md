## Welcome to uno

**uno** is a tool for interconnecting private LANs into a single **unified virtual network**, or *UVN*, which supports fully routed, site-to-site communication over the Internet
via dynamically managed VPN links.

**uno** provides the `uvn` script to configure, deploy, and administer a *UVN*, using [WireGuard](https://www.wireguard.com/), [Quagga](https://www.nongnu.org/quagga/), and [RTI Connext DDS](https://www.rti.com/products/connext-dds-professional).

## Install uno

**uno** is written in Python, and it should work on any Debian-based Linux target.

So far, it has been successfully tested on Ubuntu 18.04/20.04 (`x86_64`), and
Raspbian Buster (`armv7l`).

### From source

To install a development copy (or on platforms without binary packages
available), use **uno**'s installer script:

```sh
curl -sSL https://uno.mentalsmash.org/install | sh
```

### Binary packages

On some supported distributions, you can install **uno** using the experimental
Debian packages from mentalsmash.org's repository.

Packages are available for Ubuntu `focal` (20.04), and Debian `buster` (10).

```sh
# Add mentalsmash.org's key to your trusted repositories
curl http://packages.mentalsmash.org/apt/mentalsmash-archive-keyring.gpg | apt-key add -

# Download the preconfigured sources.list for Ubuntu
sudo curl -o /etc/apt/sources.list.d/mentalsmash.org.list \
             http://packages.mentalsmash.org/apt/ubuntu/sources.list

# Download the preconfigured sources.list for Debian
sudo curl -o /etc/apt/sources.list.d/mentalsmash.org.list \
             http://packages.mentalsmash.org/apt/debian/sources.list

# Update apt database
sudo apt update

# Install uno
sudo apt install uno
```

## Learn More

Visit the [GitHub repository](https://github.com/mentalsmash/uno/), and consult the documentation available in the [wiki](https://github.com/mentalsmash/uno/wiki).

## Contribute

**uno** is licensed under the [GNU Affero General Public License v3](https://tldrlegal.com/license/gnu-affero-general-public-license-v3-(agpl-3.0)). [Forks](https://github.com/mentalsmash/uno/fork) and [PRs](https://github.com/mentalsmash/uno/pulls) are welcome!
