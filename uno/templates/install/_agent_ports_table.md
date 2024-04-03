
    <div class="table-responsive" markdown="1">

    |Port|Use|
    |----|---|
    {%- if uvn.settings.enable_root_vpn %}
    |{{uvn.settings.root_vpn.peer_port}}| Root VPN port (push) { ^ .table .table-sm .table-striped } |
    {%- endif -%}
    {%- if cell.enable_particles_vpn %}
    |{{uvn.settings.particles_vpn.port}}| Particles VPN port { ^ .table .table-sm .table-striped } |
    {%- endif -%}
    {%- for peer in peers %}
    |{{peer.port}}| Backbone VPN port (#{{peer.port_i}}) { ^ .table .table-sm .table-striped } |
    {%- endfor -%}
    </div>

    {%- if uvn.settings.enable_root_vpn and (peers|length) > 0 and (peers|length) < (other_cells|length) %}

    <div class="alert alert-warning" markdown="1">
    **WARNING**: Even though the current configuration only uses {{peers|length}} port{{peers|length|pluralize}}
    for backbone VPN connections, UVN `{{uvn.name}}` has {{other_cells|length}} other cell{{other_cells|length|pluralize}},
    and it is possible that future configurations will use additional ports, up to `{{uvn.settings.backbone_vpn.port + (other_cells|length) - 1}}`.
  
    You can forward the UDP port range from `{{uvn.settings.backbone_vpn.port}}` to `{{uvn.settings.backbone_vpn.port + (other_cells|length) - 1}}`
    to prevent having to manually change the port forwarding configuration again in the future (at least until a new cell is
    added to the UVN). Make sure that your [UVN administrator](mailto:{{uvn.owner.email}}) is notified if you decide not to
    forward the whole block, otherwise they may end up pushing an invalid backbone configuration that relies on ports which
    are not actually available.
    </div>
    {%- endif %}
