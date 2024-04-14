###############################################################################
# (C) Copyright 2020-2024 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################
import yaml
import copy
from pathlib import Path


def yaml_load_inline(val: str | Path) -> dict:
  # Try to interpret the string as a Path
  yml_val = val
  args_file = Path(val)
  if args_file.is_file():
    yml_val = args_file.read_text()
  # Interpret the string as inline YAML
  if not isinstance(yml_val, str):
    raise ValueError("failed to load yaml", val)
  return yaml.safe_load(yml_val)


def apply_defaults(values: dict, defaults: dict) -> dict:
  def _apply_recur(current_values: dict, current_defaults: dict, parent_key: list[str]):
    result = copy.deepcopy(current_values)
    for k, def_v in current_defaults.items():
      current_key = [*parent_key, k]
      if k not in current_values:
        v = def_v
      else:
        v = current_values[k]
        if isinstance(v, dict):
          if not isinstance(def_v, dict):
            raise ValueError("expected a dictionary", ".".join(current_key))
          v = _apply_recur(v, def_v, current_key)
      result[k] = v
    return result

  return _apply_recur(values, defaults, [])
