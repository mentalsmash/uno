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

from uno.agent.agent import Agent, AgentReload
from uno.registry.package import Packager
from uno.agent.systemd import Systemd


def agent_action(action: Callable[[argparse.Namespace, Agent], None]) -> Callable[[argparse.Namespace], None]:
  def _wrapped(args: argparse.Namespace) -> None:
    agent = Agent.open(args.root)
    active_services = agent.active_static_services
    if active_services:
      agent.log.warning("detected active systemd services: {}", [s.name for s in active_services])
    try:
      while True:
        try:
          action(args, agent)
          break
        except AgentReload as e:
          agent = Agent.reload(agent, e.agent)
    finally:
      if active_services:
        agent.log.warning("restoring systemd services: {}", [s.name for s in active_services])
        for svc in active_services:
          if svc.current_marker is not None:
            agent.log.warning("service still active: {}", svc.name)
            continue
          svc.up()
  return _wrapped


def agent_install(args: argparse.Namespace) -> None:
  Packager.extract_cell_agent_package(args.package, args.root)


@agent_action
def agent_sync(args: argparse.Namespace, agent: Agent) -> None:
  agent.spin_until_consistent(
    max_spin_time=args.max_run_time,
    config_only=args.consistent_config)


@agent_action
def agent_update(args: argparse.Namespace, agent: Agent) -> None:
  pass


@agent_action
def agent_run(args: argparse.Namespace, agent: Agent) -> None:
  agent.log.info("starting to spin...")
  agent.spin()
  agent.log.info("stopped")


@agent_action
def agent_service_install(args: argparse.Namespace, agent: Agent) -> None:
  for svc in agent.static_services:
    Systemd.install_service(svc)
  tgt_svc = agent.static if args.agent else agent.router.static
  if args.boot:
    Systemd.enable_service(tgt_svc)
  if args.start:
    Systemd.start_service(tgt_svc)
    

@agent_action
def agent_service_remove(args: argparse.Namespace, agent: Agent) -> None:
  for svc in agent.static_services:
    Systemd.remove_service(svc)


def _get_target_run_level(args: argparse.Namespace, agent: Agent, index: int=-1) -> str:
  if not args.service:
    # target_services = [svc.name for svc in all_services]
    target = agent.static_services[index]
  else:
    target_services = [
      svc.name
      for svc in agent.static_services
        if svc.name in args.service
    ]
    if len(target_services) != len(args.service):
      raise RuntimeError("unknown services", list(set(args.service)- set(target_services)))
    target = target_services[index]
  return target


@agent_action
def agent_service_up(args: argparse.Namespace, agent: Agent) -> None:
  up_to = _get_target_run_level(args, agent)
  for svc in agent.static_services:
    svc.up()
    if svc.name == up_to:
      break


@agent_action
def agent_service_down(args: argparse.Namespace, agent: Agent) -> None:
  down_to = _get_target_run_level(args, agent, index=0)
  for svc in reversed(agent.static_services):
    svc.down()
    if svc.name == down_to:
      break

