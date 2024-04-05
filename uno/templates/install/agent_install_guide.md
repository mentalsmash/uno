# Installation guide for {{cell.name}}@{{uvn.name}}

<div class="p-3 pb-1" markdown="1">

[TOC]

</div>

## Overview

By following this guide you will deploy a `uno` agent for cell `{{cell.name}}`, 
{%- if allowed_lans %} and connect {{allowed_lans|length}} network{{allowed_lans|length|pluralize}} to
{%- else %} to act as an extra relay for
{%- endif %} UVN `{{uvn.name}}`{% if not allowed_lans %}.
{%- else %}:
{%- for lan in allowed_lans %}

- `{{lan}}`
{%- endfor %}
{%- endif %}

{% if address %}The agent will be reachable from public address `{{address}}`.
{%- else %}The agent will be deployed behind NAT, without a public address.
{%- endif %}

{% if not peers %}The agent will not connect to any backbone peers.
{%- else %}The agent will connect to {{peers|length}} backbone peer{{peers|length|pluralize}}:

{% with peers=peers %}
{%- include "install/_deployment_table.md" with context %}
{%- endwith %}
{%- endif %}

{% if cell.enable_particles_vpn %}The agent will accept particle connections on endpoint `{{address}}:{{uvn.settings.particles_vpn.port}}`.
{%- elif address %}The agent will not accept particle connections.
{%- endif %}

{% if uvn.settings.enable_root_vpn -%}UVN `{{uvn.name}}` supports dynamic reconfiguration of agents.
{%- if address %} The agent will listen for new configurations pushed by the registry on endpoint `{{address}}:{{uvn.settings.root_vpn.peer_port}}`.
{%- else %} The agent will pull new configurations from the registry by connecting to endpoint `{{uvn.address}}:{{uvn.settings.root_vpn.port}}`.
{%- endif %}
{%- else %}UVN `{{uvn.name}}` does not support dynamic reconfiguration of agents.
{%- endif %}

After connecting to UVN `{{uvn.name}}`, cell `{{cell.name}}`{% if allowed_lans %} and other hosts in its attached networks{% endif %} will
gain access to the following remote networks:

| Cell | Network |
|------|---------|
{%- for cell, lan in remote_lans %}
|`{{cell.name}}`|`{{lan}}` { ^ .table .table-sm .table-striped } |
{%- endfor %}

<div class="alert alert-warning" markdown="1">

**WARNING**: For the remainder of this document:

- Replace `{{deployment_host}}` with the hostname of the machine where the agent is to be deployed.

- Replace `{{deployment_user}}` with the name of the non-`root` user used to access `{{deployment_host}}`.

</div>
{%- if allowed_lans %}

## Attached Networks Setup

{%- if allowed_lans | length > 1 %}

Repeat these steps for every one of the {{allowed_lans|length}} networks that will be attached by cell `{{cell.name}}` to UVN `{{uvn.name}}`:
{%- for lan in allowed_lans %}

- `{{lan}}`
{%- endfor %}
{%- else %}{# if allowed_lans | length > 1 #}

Perform these steps to configure network `{{allowed_lans[0]}}`, and allow cell `{{cell.name}}` to attach it to UVN `{{uvn.name}}`.
{%- endif %}{# if allowed_lans | length > 1 #}
{%- if address and (peers or uvn.settings.enable_root_vpn or cell.enable_particles_vpn) %}

- Assign a fixed IP address to `{{deployment_host}}` (in order to setup up port forwarding).

    It is recommended to accomplish this by adding a "reservation" on the network's DHCP server,
    so that `{{deployment_host}}`'s interface will always receive the same address (based on its MAC address).

- Make sure that `{{deployment_host}}`'s gateway is publicly reachable from address `{{address}}`.

- Configure the gateway to forward the required UDP ports to `{{deployment_host}}` according to the table below.
    {% include "install/_agent_ports_table.md" with context %}

{%- endif %}{# if address and (peers or uvn.settings.enable_root_vpn or cell.enable_particles_vpn) #}
{%- if remote_lans %}

- Configure the network's router with static routes to the {{remote_lans|length}} remote network{{remote_lans|length|pluralize}}
  managed by the other {{other_cells|length}} cell{{other_cells|length|pluralize}} in UVN `{{uvn.name}}`. Designate `{{deployment_host}}`'s interface as the local gateway to each network:
  {%- for peer_cell, lan in remote_lans %}

    - `{{lan}}` (cell `{{peer_cell.name}}`)
  {%- endfor %}
{%- endif %}{# if remote_lans #}
{%- else %}{# if allowed_lans #}

## Agent Network Setup

- Make sure that `{{deployment_host}}` is publicly reachable from address `{{address}}`.

- If the `{{deployment_host}}` is deployed behind a NAT, make sure to forward the following UDP ports to it:
    {% include "install/_agent_ports_table.md" with context %}

{%- endif %}{# if allowed_lans #}

## Agent Host Setup

1. Initialize `{{deployment_host}}` with a supported operating system, e.g. Ubuntu 22.04+.

2. Install and enable SSH on `{{deployment_host}}`.

    For easier administration, it is recommended to enable passwordless login as `root`.

    <div class="alert alert-warning" markdown="1">

    **WARNING**: The rest of this guide will assume you are logging in as `root` on `{{deployment_host}}`
    (unless differently specified). Adjust commands accordingly if that's not the case
    (i.e. use `sudo`, or login as `root` using `su`).

    </div>

    - On `{{deployment_host}}`, install and enable `openssh-server`:

        ```{.sh .p-2 .pb-0}
        sudo apt install -y openssh-server  
        ```

    - On your administration host, generate an SSH key, and enable passwordless login on `{{deployment_host}}`
      (first for a non-`root` user, then for `root`):

        ```{.sh .p-2 .pb-0}
        ssh-keygen -t ed25519

        ssh {{deployment_user}}@{{deployment_host}} "mkdir -p ~/.ssh"

        cat ~/.ssh/id_ed25519.pub | ssh {{deployment_user}}@{{deployment_host}} "cat - >> .ssh/authorized_keys"

        ssh {{deployment_user}}@{{deployment_host}} "sudo mkdir -p /root/.ssh"

        cat ~/.ssh/id_ed25519.pub | ssh {{deployment_user}}@{{deployment_host}} "cat - | sudo tee -a /root/.ssh/authorized_keys"
        ```

    - (Optional) On your administration host, add an entry to `~/.ssh/config` to always login as `root` on `{{deployment_host}}`:

        ```{.sh .p-2 .pb-0}
        Host {{deployment_host}}
          User root
        ```

3. Install `uno` on `{{deployment_host}}`:

    ```{.sh .p-2 .pb-0}
    # Installation steps require root
    ssh {{deployment_host}}

    # Install system dependencies
    apt install -y \
      {%- for dep in uno_dependencies %}
      {{dep}}{% if not loop.last %} \{% endif %}
      {%- endfor %}
  
    # Install uno in a fresh virtual environment
    rm -rf {{venv}}
    python3 -m venv {{venv}}
    . {{venv}}/bin/activate
    pip install git+{{uno_repo_url}}@{{uno_version}}
    {%- if middleware_install %}

    {{middleware_install | indent(4)}}
    {%- endif %}

    # (optional) Add venv/bin/ directory to root's PATH.
    printf -- "export PATH={{venv}}/bin:${PATH}\n" > /etc/profile.d/uno-venv.sh
    . /etc/profile.d/uno-venv.sh
    uno -h

    # (alternatively) Load venv in order to use `uno`, or...
    . {{venv}}/bin/activate
    uno -h

    # (alternatively) Invoke `uno` by its full path
    {{venv}}/bin/uno -h
    ```

4. Copy archive `{{cell_package.name}}` to `{{deployment_host}}` and install it.
   You should have received this file together with this guide.

    ```{.sh .p-2 .pb-0}
    scp {{cell_package.name}} {{deployment_host}}:{{install_base}}

    ssh {{deployment_host}}
   
    cd {{install_base}}

    uno install {{cell_package.name}} -r {{cell.name}}
    ```

5. (Recommended) Run the agent as a `systemd` unit, and configure it to automatically
   start at boot:

    ```{.sh .p-2 .pb-0}
    uno service install -r {{agent_root}} --boot --agent
    ```

    Omit argument `--boot` if you only want to install the `systemd` unit, without
    enabling at boot. You can enable the service at a later time with:

    ```{.sh .p-2 .pb-0}
    systemctl enable uno-agent
    ```

    You can also start the agent immediately by passing argument `--start` to `uno service install`.
    Alternatively, you can start (and stop) it using `systemctl`:

    ```{.sh .p-2 .pb-0}
    systemctl start uno-agent
    ```

    The `systemd` unit can be removed with:

    ```{.sh .p-2 .pb-0}
    uno service remove -r {{agent_root}}
    ```

6. (Alternatively) Start the agent directly in a terminal:

    ```sh
    uno agent -r {{agent_root}}
    ```

<div class="alert alert-primary text-center mt-5 pb-0" markdown="1">
Generate by `uno` on {{generation_ts | format_ts}}
</div>