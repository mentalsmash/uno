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
  |Cell | Interface | Address         | Endpoint        | Peer | Address         | Endpoint         |
  |-----|-----------|-----------------|-----------------|------|-----------------|------------------|
{% for bbpeer in enumerate(cell_cfg.backbone) %}  |`{{cell.id.name}}`|`{{bbpeer.1.interface}}`|`{{bbpeer.1.addr_local}}`|{%- if bbpeer.1.network_local -%}`{{cell.id.address}}:{{bbpeer.1.port_local}}`{%- endif -%}|`{{bbpeer.1.peers[0].name}}`|`{{bbpeer.1.peers[0].addr_remote}}`|{%- if not bbpeer.1.network_local -%}`{{bbpeer.1.peers[0].endpoint}}`{%- endif -%}|
{% for p in bbpeer.1.peers[1:] %}  |||||`{{p.name}}`|`{{p.addr_remote}}`|{%- if not bbpeer.1.network_local -%}`{{p.endpoint}}`{%- endif -%}|
{% endfor %}{% endfor %}
{% endfor %}

[backbone_graph]: deployment_backbone.png "UVN Backbone Graph"
