<div class="table-responsive" markdown="1">
| | Local Endpoint | In | Out | | Remote Endpoint |
|-|----------------|:--:|:---:|-|-----------------|
{%- for peer in peers %}
|{{peer.port_i}}|{% if cell.private %}Private LAN{% else %}`{{address}}:{{peer.port}}`{% endif %}|
{%- if "l" in peer.direction %}`←`{% endif %}|
{%- if "r" in peer.direction %}`→`{% endif %}|{{peer.peer_port_i}}|
{%- if peer.cell.private %}Private LAN{% else %}`{{peer.cell.address}}:{{peer.peer_port}}`{% endif %} {^ .table .table-sm .table-striped }
{%- endfor %}
</div>
