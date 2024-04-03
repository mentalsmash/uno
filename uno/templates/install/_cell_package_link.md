{% if cell_package_url -%}
[{{cell_package.name}}](cell_package_url)
{%- else -%}
*{{cell_package.name}}*
{%- endif -%}