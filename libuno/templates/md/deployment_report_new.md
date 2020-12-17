# UVN {{identity_db.registry_id.address}} [{{deployment.deploy_time}}]

## UVN Backbone Graph

![UVN Backbone Graph][backbone_graph]

## Registry

- **Admin**: `{{identity_db.registry_id.admin_name}} ({{identity_db.registry_id.admin}})`
- **Public Key**: `{{identity_db.registry_id.key}}`
- **Public Endpoint**: `{{registry.vpn_config.registry_endpoint}}:{{registry.vpn_config.registry_port}}`
- **VPN Interface**: `{{registry.vpn_config.interface}}`
- **VPN Address**: `{{registry.vpn_config.registry_address}}`
- **VPN Peers**:
  | Peer | Address | Interface |
  |------|---------|-----------|
{% for peer in registry.vpn_config.peers %}
{%- set here_just_to_consume_space_in_output = False -%}
{% set cell = get_cell_by_name(registry, peer.cell_name) %}  |`{{peer.cell_name}}`|`{{peer.cell_ip}}`|`{{cell.registry_vpn.interface}}`|
{% endfor %}
{% for cell_cfg in sort_deployed_cells(deployment.deployed_cells) %}
{%- set cell = get_cell_by_name(registry, cell_cfg.cell) -%}
{%- set cell_key = get_cell_public_key_by_name(cell_cfg.cell) -%}

## `{{cell_cfg.cell}}`
{% set deploy_id = cell_cfg.deploy_id + 1%}
- **Location**: `{{cell.id.location}}`
- **Admin**: `{{cell.id.admin_name}} ({{cell.id.admin}})`
- **Public Key**: `{{cell_key}}`
- **Address**: `{{cell.id.address}}`
- **Peer Ports**: `[{{cell.peer_ports|join(", ")}}]`
- **Deployment Id**: `{{deploy_id}}`
- **Backbone Connections**:
{% for bbpeer in enumerate(cell_cfg.backbone) %}
{%- set no_spaces_here = False -%}
{% set peer_port = get_peer_port(cell_cfg, bbpeer.0) %}  - **Peer** : `{{bbpeer.1.peer}}`
    - **Interface** : `{{peer_port}}`
    - **Address (local)**: `{{bbpeer.1.addr_local}}`
    - **Address** : `{{bbpeer.1.addr_remote}}`
    - **Endpoint** : `{{bbpeer.1.endpoint}}`
{% if bbpeer.1.peer_2 %}
{%- set no_space_here = False -%}
{% set peer_port = get_peer_port(cell_cfg, bbpeer.1.peer_2_i) %}  - **Peer (2)**: `{{bbpeer.1.peer_2}}`
    - **Interface (2)** : `{{peer_port}}`
    - **Address (2)** : `{{bbpeer.1.peer_2_addr_remote}}`
    - **Endpoint (2)** : `{{bbpeer.1.peer_2_endpoint}}`
{% endif %}
{%- set no_space_here = False -%}
{% endfor %}
{% endfor %}

[backbone_graph]: deployment_backbone.png "UVN Backbone Graph"
