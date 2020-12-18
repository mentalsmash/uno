## Welcome to uno

**uno** is a tool for interconnecting private LANs into a **unified virtual network**, or *UVN*, which support fully routed, site-to-site communications between all hosts via dynamically managed VPN links.

**uno** provides the `uvn` Python script to configure, deploy, and administer a *UVN*, using [WireGuard](https://www.wireguard.com/), [Quagga](https://www.nongnu.org/quagga/), and [RTI Connext DDS](https://www.rti.com/products/connext-dds-professional).

## Install uno

**uno** supports any Debian-based `x86_64` or `armv7l` target (e.g. Ubuntu 18.04, Debian/Raspbian Buster).

To install a local copy of the `uvn` script, use **uno**'s `install.sh` script:

```sh
curl -sSL https://raw.githubusercontent.com/mentalsmash/uno/master/bin/install.sh | sh
```

## Learn More

Visit the [GitHub repository](https://github.com/mentalsmash/uno/), and consult the documentation available in the [wiki](https://github.com/mentalsmash/uno/wiki).
