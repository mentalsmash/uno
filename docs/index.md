## Welcome to uno

**uno** is a tool for interconnecting private LANs into a single **unified virtual network**, or *UVN*, which support fully routed, site-to-site communications over the Internet
via dynamically managed VPN links.

**uno** provides the `uvn` script to configure, deploy, and administer a *UVN*, using [WireGuard](https://www.wireguard.com/), [Quagga](https://www.nongnu.org/quagga/), and [RTI Connext DDS](https://www.rti.com/products/connext-dds-professional).

## Install uno

**uno** should work on any Debian-based target.

So far, it has been successfully tested on Ubuntu 18.04/20.04 (`x86_64`), and
Raspbian Buster (`armv7l`)

To install a local copy of the `uvn` script, use **uno**'s installation helper script:

```sh
curl -sSL https://uno.mentalsmash.org/install | sh
```

## Learn More

Visit the [GitHub repository](https://github.com/mentalsmash/uno/), and consult the documentation available in the [wiki](https://github.com/mentalsmash/uno/wiki).

## Contribute

**uno** is licensed under the [GNU Affero General Public License v3](https://tldrlegal.com/license/gnu-affero-general-public-license-v3-(agpl-3.0)). [Forks](https://github.com/mentalsmash/uno/fork) and [PRs](https://github.com/mentalsmash/uno/pulls) are welcome!
