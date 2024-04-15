###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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
