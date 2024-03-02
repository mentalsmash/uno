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
from pathlib import Path
import sys
from uno.uvn.agent_net import UvnNetService
from uno.uvn.cell_agent import CellAgent
from uno.uvn.registry import Registry
from uno.uvn.registry_agent import RegistryAgent
from uno.uvn.log import Logger as log, set_verbosity, level as log_level

def main():
  args = sys.argv[1:]
  config_dir = None
  root = False

  set_verbosity(log_level.activity)

  try:
    agent = CellAgent.load(Path.cwd())
    config_dir = agent.net.config_dir
    log.warning(f"{sys.argv[0]}: running from cell directory ({config_dir})")
  except Exception as e:
    # log.exception(e)
    try:
      registry = Registry.load(Path.cwd())
      agent = RegistryAgent(registry)
      config_dir = agent.net.config_dir
      root = True
      log.warning(f"{sys.argv[0]}: running from registry directory ({config_dir})")
    except Exception as e:
      # log.exception(e)
      log.warning(f"{sys.argv[0]}: running with global configuration")
  UvnNetService.uvn_net(args, config_dir=config_dir, root=root)
