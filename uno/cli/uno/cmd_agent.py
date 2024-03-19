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
from typing import Callable
import argparse

from uno.agent.agent import Agent
from uno.agent.cell_agent import CellAgent
from uno.agent.registry_agent import RegistryAgent


def agent_action(action: Callable[[argparse.Namespace, Agent], None]) -> Callable[[argparse.Namespace], None]:
  def _wrapped(args: argparse.Namespace) -> None:
    try:
      agent = CellAgent.load(args.root)
    except:
      agent = RegistryAgent.load(args.root)
    action(args, agent)
  return _wrapped;


@agent_action
def agent_sync(args: argparse.Namespace, agent: Agent) -> None:
  agent.spin_until_consistent()


@agent_action
def agent_install(args: argparse.Namespace, agent: Agent) -> None:
  pass


@agent_action
def agent_update(args: argparse.Namespace, agent: Agent) -> None:
  pass


@agent_action
def agent_run(args: argparse.Namespace, agent: Agent) -> None:
  pass


@agent_action
def agent_service_install(args: argparse.Namespace, agent: Agent) -> None:
  pass


@agent_action
def agent_service_remove(args: argparse.Namespace, agent: Agent) -> None:
  pass


