# Setup Checklist

Use the checklists in this page to help you in the process of setting up, and
deploying your own *UVN*.

- [UVN Configuration](#uvn-configuration)
- [Cell Configuration](#cell-configuration)
- [Particle Configuration](#particle-configuration)
- [Agent Host Configuration](#agent-host-configuration)

## UVN Configuration

| Task | Outcome | Example Outcome |
|------|---------|---------|
|[Register a DNS domain name for your organization](#register-a-dns-domain-name-for-your-organization)| A valid DNS domain name is now under your control.| Domain name `example.org` |
|[Allocate a subdomain to your UVN](#allocate-a-subdomain-to-your-uvn)| A subdomain of your organization is dedicated exclusively to UVN addresses.| Subdomain `uvn.example.org` |
|[Create a new YAML configuration for your UVN](#create-a-new-yaml-configuration-for-your-uvn)|A YAML file contaning your *UVN*'s configuration that can be passed to `uvn create` has be created, and checked in into a version control system,.| YAML file `uvn.example.org.yml`|
|[Configure your registry node](#configure-your-registry-node)|A host has been configured to run the *root agent*, including pointing the *UVN*'s *registry address* to it, and forwarding it the required UDP ports.|A dedicated [VPS](https://en.wikipedia.org/wiki/Virtual_private_server) reachable from `uvn.example.org`|
|[Generate and deploy the UVN](#generate-and-deploy-the-uvn)|All required files have been copied to the *registry node*, and the *root agent* is ready to run.|A directory `uvn.example.org/` with all required files on host `uvn.example.org`|
|[Start the root agent](#start-the-root-agent)|A *root agent* process running on the *registry node*|An process running `uvn agent` inside directory `uvn.example.org/` on host `uvn.example.org`|

### Register a DNS domain name for your organization

- It is much easier to set up domain names for all the nodes in your *UVN*
if you have access to your own domain name.
- Any domain registrar will do, as long as they allow you to create unlimited
subdomains (i.e. they allow you to transfer the domain to your own DNS
servers, or they provide you with an interface to manage arbitrary DNS
entries for your domain).
- Example registrars:
  - [Godaddy](https://www.godaddy.com)
  - [Google Domains](https://domains.google/)

### Allocate a subdomain to your UVN

- The subdomain will be used by **uno** as the *UVN*'s *registry address*, a
  unique identifier for the *UVN*, and the address used by *cell agents* to
  contact the *root agent*.
- The subdomain should be fully delegated to the DNS servers in the *UVN*
  (i.e. you shouldn't have any children of this domain served by your
   organization's DNS servers).
- *Agents* in the *UVN* will automatically define subdomains and addresses to
  identify all the dynamic endpoints they create.

### Create a new YAML configuration for your UVN

- Take advantage of **uno**'s support for YAML input whenever you can.
  - YAML files are far easier to read than scripts, and a lot less error prone.
  - They are simple text files, and they can can be version-controlled.
  - Most `uvn` commands accept YAML files/data as input.
- For example, You can create a new *UVN* by passing a YAML file describing the
  *UVN* to `uvn create -f <file>`.
- The file specifies global parameters for the *UVN*, but it can also include
  configurations for *cells*, *particles*, and *nameserver* entries.
- The file allows the whole *UVN* to be configured by a single call to `uvn create`,
  instead of requiring multiple calls to `uvn attach` and `uvn ns`.
- E.g.:

```yaml
# Configure the UVN's global parameters
config:
    address: uvn.example.org
    admin: john@example.org
    admin_name: John Doe

# Attach some cells
cells:
  - name: jane-home
    admin_name: Jane Doe
    admin: jane@example.org
    location: Jane's House, Somewhere, Earth
    address: jane.example.org
  - name: john-home
    admin_name: John Doe
    admin: john@example.org
    location: John's House, Somewhere Else, Earth
    address: john.example.org
  - name: jj-lair
    admin_name: John Jr. Doe
    admin: jj@example.org
    location: Jane's Guest House, Somewhere Nearby, Earth
    address: jj.example.org

# Register some particles for mobile devices
particles:
  - name: jane-phone
    contact: jane@example.org
  - name: john-phone
    contact: john@example.org
  - name: jj-phone
    contact: jj@example.org
  - name: jj-tablet
    contact: jj@example.org

# Define some nameserver entries for useful known hosts
nameserver:
  jane-home:
    - hostname: gw.jane
      address: 192.168.1.1
  john-home:
    - hostname: gw.john
      address: 192.168.2.1
    - hostname: nas
      address: 192.168.2.2
  jj-lair:
    - hostname: gw.jj
      address: 192.168.3.1
    - hostname: workstation
      address: 192.168.3.10
      # Add "windows" tag so host won't be tested with ping
      tag: ["windows"]
    - hostname: server
      address: 192.168.3.15
```

- See [Cell Configuration](#cell-configuration), and [Particle Configuration](#particle-configuration) for more information on *cells*, *particles*, and
*nameserver* entries.

### Configure your registry node

- Every *UVN* must have a *registry node* to host the *root agent*.
- The *registry node* must be reachable via the *UVN*'s *registry address*.
- The following UDP ports must be forwarded to the *registry node*:
  - `63550` (registry vpn port)
  - `33000`-`35000` (router ports)
- The *registry node* must be reachable by all *cell agents* at any time, and
  it is thus best suited for a "deployment in the cloud".
- See [Agent Host Configuration](#agent-host-configuration) for a checklist
  that applies to all hosts running an *agent*.

### Generate and deploy the UVN

- Assuming you have YAML file `uvn.example.org.yml`, containing the
  configuration for *UVN* `uvn.example.org`, you should store all of the *UVN*
  configuration files in a directory named `uvn.example.org/`, which you
  can create with:

  ```sh
  uvn create -f uvn.example.org.yml uvn.example.org
  ```

- Assuming you have `ssh` access to the *registry node*, you can copy the
  generated *UVN* directory with `rsync`
  (making sure to exclude some uncopiable file that might exist inside it):

  ```sh
  rsync -rav --exclude="S.gpg-agent" uvn.example.org uvn.example.org:~/
  ```

- **The *UVN* directory contains secret files. It is critical that access to the remote copy of the directory is protected at all time, or the security of the *UVN*, and all of its *cells*, will be compromised.**

- The need for hosting these files on the *registry node* will be removed from
  future versions of **uno**.

### Start the root agent

- Like all *agents*, the *root agent* must be run as root.

- If you [installed the shell helpers](#install-unos-shell-helpers), use `uvnd_start` to spawn
  the process in a `screen` session called `"uvnd"`, otherwise, `cd` to the
  *UVN* directory, and start the *agent*:

  ```sh
  (cd uvn.example.org/ && sudo uvn agent)
  ```

- The embedded DNS server is not required for the *root agent*.

  - Since the *registry node* might be deployed within a third-party cloud hosting
    environment, you might want to avoid starting the *agent*'s embedded DNS server,
    to avoid overwriting the *registry node*'s `/etc/resolv.conf`, and possibly
    losing some functionality offered by your hosting provider.

- The *root agent* must be available to bootstrap every *cell agent* into the
  *UVN*.
  - The *root agent* instructs each *cell agent* on which networks it
    should enable for routing on its VPN links.

## Cell Configuration

|Task|Outcome|Example Outcome|
|----|-------|---------------|
|[Allocate a subdomain to your cell](#allocate-a-subdomain-to-your-cell)| | |
|[Configure your cell using a YAML file](#configure-your-cell-using-a-yaml-file)| | |
|[Configure your cell node](#configure-your-cell-node)| | |
|[Generate and deploy the cell](#generate-and-deploy-the-cell)| | |
|[Pick a free IP subnetwork for every attached LAN](#pick-a-free-ip-subnetwork-for-every-attached-lan)| | |
|[Configure addresses and routing in attached LANs](#configure-addresses-and-routing-in-attached-lans)| | |
|[Start the cell agent](#start-the-cell-agent)| | |

### Allocate a subdomain to your cell

### Configure your cell using a YAML file

### Configure your cell node

### Generate and deploy the cell

### Pick a free IP subnetwork for every attached LAN

### Configure addresses and routing in attached LANs

### Start the cell agent

## Particle Configuration

### Use particle package to connect to the UVN

### Import particle configuration using a QR code

## Agent Host Configuration

### Select the target environment

### Designate a user to run uno

### Install uno and its dependencies

### Install uno's shell helpers

### Configure host for dynamic DNS
