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
curl -sSL https://uno.mentalsmash.org/install | sh
```

If you have a pre-built wheel file for `connextdds-py` (e.g. if installing on
a Raspberry Pi), place it in the directory where you are running the
script, and it will be automatically detected and installed.

If a wheel file is not available, the script will try to clone and 
build `connextdds-py` from source. [RTI Connext DDS](https://github.com/mentalsmash/uno/wiki/Installation#rti-connext-dds) 6.x must
be installed on the system, and available via `NDDSHOME` for this to succeed.

Consult the [Installation](https://github.com/mentalsmash/uno/wiki/Installation)
section of the wiki for more information on each installation step performed
by the script.

## Documentation

Visit the [wiki](https://github.com/mentalsmash/uno/wiki) for more information
about **uno**.

You might want to start from [Hello UVN](https://github.com/mentalsmash/uno/wiki/Hello-UVN), which gives an overview of **uno**'s
features, and the structure of a *UVN*.
