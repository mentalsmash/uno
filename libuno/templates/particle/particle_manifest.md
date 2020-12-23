# Particle {{name}}

**Contact:** {{contact}}

{% for c in configs %}
## Cell {{c.cell_name}}@{{c.registry_address}}

**Location:** {{c.cell_location}}

**Admin:** {{c.cell_admin}}

**Endpoint:** {{c.cell_endpoint}}

**Configuration:**

![Particle Configuration for {{c.cell_name}}@{{c.registry_address}}][config_{{c.cell_name}}]

{% endfor %}

{% for c in configs %}
[config_{{c.cell_name}}]: {{c.registry_address}}-{{c.cell_name}}-{{name}}.png "Particle Configuration for {{c.cell_name}}@{{c.registry_address}}"
{% endfor %}
