
# Hello UVN

* [Introduction](#introduction)
* [Create a new UVN configuration](#create-a-new-uvn-configuration)
* [Manipulating the UVN registry](#manipulating-the-uvn-registry)
  * [Configuration File Validation](#configuration-file-validation)
* [Attaching cells to the UVN](#attaching-cells-to-the-uvn)
* [Deploying the UVN](#deploying-the-uvn)
  * [Bootstrap deployment](#bootstrap-deployment)
  * [Backbone deployment](#backbone-deployment)
* [Attaching particles to the UVN](#attaching-particles-to-the-uvn)
* [Starting the UVN agents](#starting-the-uvn-agents)

## Introduction

**uno** provides the `uvn` command line tool to configure a *UVN* and its
*cells*, and for instantiating *agents* to deploy it.

This page describes the main steps involved in the configuration and
deployment of a *UVN*.

For a quick test of this process, run [test/simple_validation.sh](https://github.com/mentalsmash/uno/blob/master/test/simple_validation.sh):

```sh
# Generate a test UVN and spawn the registry agent
uno/test/simple_validation.sh
# Delete generated files
rm -r test-uvn.localhost test-uvn.localhost-cells
```

If you prefer a more complex, but poignant example, take a look at
[test/local_deploy/experiment_local.sh](https://github.com/mentalsmash/uno/blob/master/test/local_deploy/experiment_local.sh)
which should enable you to simulate an arbitrary number of networks (composed
of a router, cell, a "regular host" hosts) interconnected by a *UVN* administered
by a "cloud deployed" *registry* node.

The test requires Docker on the host system.

```sh
# Build Docker containers for 5 test networks, define a UVN configuration to
# link them, then start a tmux session to monitor output and provide input to
# each one.
NETS=4 VERBOSE=y uno/test/local_deploy/experiment_local.sh
```

## Create a new UVN configuration

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

## Manipulating the UVN registry

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
(cd test-uvn.localhost && uvn info -vv)
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

### Configuration File Validation

`uvn` signs all configuration files with the *registry*'s private key.

The signature is stored inline within each file, and it is automatically
verified upon loading.

This means that you will not be able to manually modify the YAML files, unless
you also manually regenerate this signature.

## Attaching cells to the UVN

In order to attach private networks to the *UVN*, one must first define *cell*
configurations for every *agent* that will be deployed within a LAN.

Each *cell* contains an *agent*, and it must choose a unique name which will
identify them within the *UVN*. A public domain name or IP address must also be
provided so that other *agents* may connect to the *cell*.

When registered in the *UVN*, each *cell* is assigned a unique, 32-bit identifier
that can also be used to refer to *cell* in place of its name (e.g. in various
formulas that generate cell-specific values, like a *cell*'s "control" VPN IP address).

*Cells* can be defined using the `uvn attach cell` command:

```sh
(cd test-uvn.localhost && uvn attach cell --name cell1)
```

This command will define a new *cell* called `cell1` whose address is
`cell1.test-uvn.localhost`. You can specify an arbitrary address with option
`--address ADDRESS`.

By default, **uno** requires *cells* to enable forwarding to their *agents* of
UDP ports `63450`, `63451`, and `63452`.

These will be used to establish the routing links that make up the *UVN*'s
*backbone*. Custom values can be specified using option `--peer-ports PORTS`.
The `PORTS` value must be a valid YAML/JSON array, e.g. `"[ 1, 2, 3 ]"`

Additionally, a *cell* *agent* should also be able to receive connection on port
`63449`, to enable *particle* connections.

When a *cell* is attached to the *UVN*, a new record will be created inside
`registry.yml`, and a new "bootstrap" package will be generated for the *cell*.

This is a `.zip` archive that a *UVN* administrator must send confidentially
to the *cell*'s administrator.

The package contains a unique, randomly generated, GPG key pair for the *cell*,
and a stripped version of `registry.yml`, with all secrets removed. A file
`cell.yml` contains the *cell*'s own configuration, extracted from the root
*agent*'s `registry.yml`, and including all relevant secrets for the *cell*.

These include key material for the *cell*'s "control" and "failover routing"
VPN connections it must establish with the *registry* node.

The archive can be extracted and its contents validated using the `uvn install`
command on the host where the *cell*'s *agent* will be deployed.

For example, the previous `uvn attach` command will generate file
`text-uvn.localhost/installers/uvn-test-uvn.localhost-bootstrap-cell1.zip`.

Once copied to `cell1`'s host, the package can be extracted into a
custom directory `cell1.test-uvn.localhost/` with command:

```sh
uvn install uvn-test-uvn.localhost-bootstrap-cell1.zip cell1.test-uvn.localhost
```

In addition to previously mentioned files (`registry.yml`, `cell.yml`), the
generated *cell* directory will also contain the *cell*'s own GPG key database,
initialized with the *cell*'s key pair, the *registry*'s public key, and
the public keys of all *cell* already attached to the *UVN*.

Similarly to when the root *agent*'s copy of the *UVN* is manipulated, `uvn`
will require users to specify the secret for the *cell*'s private key before
allowing any command to be performed inside the *cell*'s *UVN* directory.

Instead of variable `AUTH` and file `./.uvn-auth`, `uvn` will look for the *cell*'s
secret in variable `AUTH-<cell-name>`, and file `./.uvn-auth-<cell-name>`.

Since *cell* keys are currently automatically generated by the *registry*,
"bootstrap" packages (and the directories generated from them) will store the
key secret in a file named `.uvn-auth-<cell-name>`, and allow *cell* commands
to be executed after `cd`'ing to the installed directory.

## Deploying the UVN

### Bootstrap deployment

A *UVN* can be deployed immediately after attaching its *cells*, by
starting the root *agent* on the latest version of `registry.yml`, and by
starting *agents* for each *cell* using their initial bootstrap packages.

*Cell* *agents* will establish two connections with the *registry*:

* A "control" VPN link that will be used exclusively to exchange DDS traffic
  between the *registry* and the *cells*.

* A (fallback) "routing" VPN link which *agents* can use to route data to remote
  *cells* via the *registry* in case no *backbone* link is available.

In both cases, *cell* *agents* will act as VPN clients, connecting to the
*registry*'s listening endpoints.

The "control" VPN link is always established over port 63550, and the root
*agent* listens for connections on a single WireGuard interface (`uwg-v0`) with
IP address `10.255.128.1`.

*Cell* *agents* also connect via a single WireGuard interface (`uwg-v0`), and use
an IP address in subnet `10.255.128.0/22` based on their unique registration id.
The first *cell* to have been registered will be `10.255.128.2`, the second
`10.255.128.3`, and so on.

No traffic coming from other IP subnetworks can be routed over the "control" link.
*Agents* must use their "routing" link to route packets via the *registry* node.

The *registry* creates a "routing" WireGuard interface for each *cell* (`uwg-r[1-N]`,
when N is the total number of cells). Each interface is assigned the highest of the two
IP addresses in a `/31` subnet picked from the larger `10.255.0.0/22` network, and
starting from base address `10.255.0.2`.

The *registry*'s "routing" interface for the first cell (`uwg-r1`) will have
address `10.255.0.3` from subnet `10.255.0.2/31`. The cell's local interface
(`uwg-r0`) will use `10.255.0.2`.
The second cell's pair of "routing" interfaces (`uwg-r2` on the *registry*, `uwg-r0` on
the *cell*) will use subnet `10.255.0.4/31`, the third's `10.255.0.6/31`, and so on.

The "all encompassing" `10.255.0.0/R` network will be computed after all links
have been allocated, so that netmask size `R` accounts for all allocated addresses.

In the case of "routing" links, the *registry* assigns a random listening UDP port
to each *cell* at registration time, in the range 33000-35000. You might think this is
a completely arbitrary and unnecessary choice, and you wouldn't be wrong. The *registry*
could assign ports sequentially, using a scheme similar to the one used to assign IP
addresses. While this is true now, in the future, **uno** might introduce a handshake
protocol between *cells* and *registry* to negotiate ports and services required by
each *cell*. The assignment of a random port (even if only done once at registration)
can be considered a sort of foreshadowing of that potential scenario.

When *agents* and *registry* are deployed with this "bootstrap" configuration, the
*UVN* will not reach a state of "full routing" between all attached networks.

*Agents* will be able to communicate with each other over the *registry*'s "control"
VPN, and even establish routing paths between attached networks via the *registry*'s
"routing" links, but they will ignore any contact attempt made by *cells* attached to
the *UVN* after them since their are not part of their local copy of *registry.yml*.

For all *cells* to start communicating, the *registry* must push updated packages
to the *cells* which contain a *deployment configuration* that they will use to
activate the *UVN*'s backbone.

### Backbone deployment

A *UVN*'s *deployment configuration* consists of all the configuration parameters
that a *cell* *agent* needs to create its "backbone" VPN links with other *agents*.

These include the list of "peer" *cells* associated to each one of a *cell*'s backbone
ports, the local and remote IP addresses, key material to establish the encrypted
VPN link, and the *cell*'s *deployment id*.

This is a 32-bit identifier similar to a *cell*'s registration id, which uniquely
identifies the *cell* within a certain deployment configuration.

The number of backbone ports opened by each *cell*, and which *cells* will actually be
selected as "peers" for each port, will be determined by the *deployment strategy*
used by the *registry*.

A *deployment strategy* takes the current sent of registered cell, assigns unique
deployment ids to them, and returns a mapping of each *cell* to its peers.

At the moment, **uno** includes two deployment strategies: `default` and `circular`.

The `default` strategy assigns up to 3 peers to each *cell*. Deployment ids are
assigned by sorting the set of registered *cells* in random order. The *UVN* must
contain at lest two *cells* for the deployment to succeed.

Based on the total number of *cells* in the *UVN*, and deployment id `n`, the
`default` strategy will assign peers according to the following logic:

| No. of cells (N) | Deployment Id (n) | len(peers(n)) | peers(n)      |
|------------------|-------------------|---------------|---------------|
| `N == 1`         |  N/A              | N/A           | N/A           |
| `N == 2`         | `n`               | `1`           | `(n+1) % 2`   |
| `N == 3`         | `n`               | `2`           | `(n+1) % 3`, `(n-1) % 3` |
| `N > 3`          | `n <= N//2, n < (N-1)`| `3`       | `(n+1) % N`, `(n-1) % N`, `(n + N//2) % N`|
|                  | `n > N//2, n < (N-1)`| `3`        | `(n+1) % N`, `(n-1) % N`, `(n - N//2) % N`|
| `N > 3, N % 2 == 0`|`n == (N-1)`      | `3`          | `(n+1) % N`, `(n-1) % N`, `(n - N//2) % N`|
| `N > 3, N % 2 == 1`|`n == (N-1)`      | `2`          | `(n+1) % N`, `(n-1) % N`|

The rules can be summarized as:

* If there are only 2 *cells* in the *UVN*, each one gets a single backbone port to the other.
* If there are 3 *cells*, each *cell* creates two links to both of the other two *cells*.
* If there are 4 or more *cells*, all *cells* will get 3 peers, with the exception
  of the one with the highest deployment id, which might get only 2 peers, if the
  total number of *cells* is odd.

In the case of 4 or more *cells*, each *cell* is peered with the one following
it, the one preceding it, and the one "opposite" to it in the ordered deployment
set.

The `circular` strategy assigns peers according to the following logic:

| No. of cells (N) | Deployment Id (n) | len(peers(n)) | peers(n)      |
|------------------|-------------------|---------------|---------------|
| `N == 1`         |  N/A              | N/A           | N/A           |
| `N == 2`         | `n`               | `1`           | `(n+1) % 2`   |
| `N >= 3`         | `n`               | `2`           | `(n+1) % N`, `(n-1) % N` |

Each cell is peered with the one following and the one preceding it in the ordered
deployment set.

Once peers have been assigned to each *cell*, `uvn` will start assigning IP
addresses to each pair of peers, picking them from subnet `10.255.196.0/22`
with an algorithm similar to the one used for "routing" ports.

Each backbone link will be assigned an address in a `/31` subnetwork: the
first cell's first link will have address `10.255.196.2`, its peer `10.255.196.3`.
The second link of the first cell will use addresses `10.255.196.4/31`, the
third `10.255.196.6/31`. The second cell's first link will use `10.255.196.8/31`,
its second `10.255.196.10/31`, and so on.

Similartly to "routing" links, a final, "all encompassing", IP network
`10.255.196.4/B` will be computed after all links have been configured, so that
`B` accounts for all the allocated addresses.

A *deployment configuration* must be generated by the *registry* node, by issuing the
`uvn deploy` command:

```sh
(cd test-uvn.localhost && uvn d -d)
```

The `-d` option will cause `uvn` to drop old deployment configurations, which
can be discarded after a new one has been generated.

After the command completes, a new set of *cell* installers will be generated
in the *UVN* directory, in the `installers/` directory. Contrary to the "bootstrap"
installerrs generated by `uvn attach cell`, these installers will be marked with the *deployment configuration*'s unique identifier (a timestamp of the time of generation).

These installers can be used in place of the "bootstrap" ones,
They will overwrite previous configuration files coming from the *registry*,
updating them to the most recent, authoritative version. The packages can be
installed on top of the previous *cell* configuration using `uvn install`.

If the *UVN* is deployed and the *agents* are active and connected to the
*registry*, every new deployment will be automatically pushed by the *registry*
to each *cell* via DDS.

Along with the *cell* installers, `uvn` will also generate a human-readable
"deployment manifest" to summarize the *deployment configuration*, and display
a graph of the resulting backbone network.

## Attaching particles to the UVN

In addition to *cells* and the hosts in their attached LANs, a *UVN* also includes
another type of nodes, called *particles*.

These are nodes external to any of the LANs, which connect to the *UVN* via a
single WireGuard link with one of the *cells*, over which the node routes
all of its traffics.

A smartphone connecting to the *UVN* from a mobile network is an example of a
*particle*.

A *particle* is created with the `uvn attach particle` command, by specifying a
name for the particle, and an optional email contact, e.g.:

```sh
(cd test-uvn.localhost && uvn a p my-mobile)
```

The root *agent* disseminates information about registered *particles* to every
*cell* so that they may enable their *particle ports*, and it creates multiple
configuration packages, one for every *particle*.

These configuration packages should be copied securely to each *particle* node.
Each package contains multiple WireGuard configurations, which allow
a specific *particle* to connect to the *particle port* of one of the available
*cells*.

A *particle port* is a WireGuard interface created by a *cell* *agent* which
allows any registered *particle* to connect.

The *cell* *agent* has always address `10.254.0.1/16` on this interface, while
*particles* have a "stable" address, independent of the *cell* to which they are connected.

Each *particle*'s address is derived by adding the *particle*'s unique
registration id (a numerical id assigned at registration) to the *cell*
*agent*'s address. For example, the first *particle* registered on the *UVN*
will always have `10.254.0.2/16`, the second one `10.254.0.3/16`, and so on.

Contrary to all IP subnets contained in the *UVN*, the `10.254.0.0/16` subnet
cannot be accessed directly by other hosts in the *UVN*. This means that
a *particle* can access any host within the *UNV*, but other hosts will not
be able to access the *particle* over its *particle port* address.

A *particle* might be able to access other *particles* connected to the same *cell*.

A *particle* should only enable one *particle port* connection at a time, since
every WireGuard connection will install the "catch all" route `0.0.0.0/0` to
redirect all traffic over the VPN link.

The configuration will also set the *cell* *agent* as the default DNS server.
This allows *particles* to access **uno**'s nameserver functionalities, but
it also requires that the *cell agent* be spawned with the nameserver enabled.

## Starting the UVN agents

All *agents* can be started by running the `uvn agent` command inside a
*UVN* directory:

```sh
(cd test-uvn.localhost && uvn A)
```

`uvn` will automatically detect whether the directory contains the *registry*
copy of the *UVN* configuration, or a *cell* package, and initialize the
system accordingly.

The boot up sequence of an *agent* is the same in both cases:

1. Enable IPv4 forwarding in the kernel.

2. Start all VPN links ("control", "router", and "backbone").

3. Start the OSPF routing daemon.

4. Optionally, start a local DNS server and set it as the system's default
   name resolver.

5. Create the DDS DomainParticipant that will be used to communicate with
   other *agents*.

6. Start a connection tester, to periodically verify connectivity to known
   hosts in remote networks.

7. Start a monitoring process to provide runtime access to the *agent*'s
   internal state.

Once the *agent* has been initialized, the data it will exchange over DDS
depends on the type of *agent*.

The root *agent* informs *cell* *agents* about the summary "routing" and
"backbone" networks, which include addresses allocated for these classes of
links. *Cell* *agents* will use this information to enable communication
from these networks over all their "routing" and "backbone" links.

At the same time, *cell* *agents* will also inspect their host's IPV4 interfaces,
and publish summary information about the IP networks they are attached to over DDS.

This information includes the local IP endpoint on which the *agent* can
be reached from a certain network.

When this information is detected by other *agents*, the endpoints are added
to the DDS peer configuration, to have the DomainParticipant perform
discovery (and evenutally communication) over these private addresses.

The advertised networks are also asserted among the allowed IP addreses for
every "routing" and "backbone" interface.

This allows the OSPF router spawned by the *agent* to properly redirect or
accept packets from these networks over its available WireGuard interfaces.
