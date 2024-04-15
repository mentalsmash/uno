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
from typing import Callable
import argparse

from uno.agent.agent import Agent, AgentReload
from uno.agent.systemd import Systemd


def agent_action(
  action: Callable[[argparse.Namespace, Agent], None],
) -> Callable[[argparse.Namespace], None]:
  def _wrapped(args: argparse.Namespace) -> None:
    agent = Agent.open(args.root, enable_systemd=getattr(args, "systemd", False))
    while True:
      try:
        action(args, agent)
        break
      except AgentReload as e:
        agent = agent.reload(agent=e.agent)

  return _wrapped


def agent_install(args: argparse.Namespace) -> None:
  Agent.install_package(args.package, args.root)


def agent_install_cloud(args: argparse.Namespace) -> None:
  storage_config = args.config_cloud_storage(args) or {}
  provider_config = args.config_registry(args)["cloud_provider"]
  Agent.install_package_from_cloud(
    uvn=args.uvn,
    cell=args.cell,
    root=args.root,
    provider_class=provider_config["class"],
    provider_args=provider_config["args"],
    storage_args=storage_config,
  )


@agent_action
def agent_sync(args: argparse.Namespace, agent: Agent) -> None:
  agent.spin_until_consistent(max_spin_time=args.max_wait_time, config_only=args.consistent_config)


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
  # tgt_svc = agent.static if args.agent else agent.router.static
  tgt_svc = agent.static
  if args.boot:
    Systemd.enable_service(tgt_svc)
  if args.start:
    Systemd.start_service(tgt_svc)


@agent_action
def agent_service_remove(args: argparse.Namespace, agent: Agent) -> None:
  for svc in agent.static_services:
    Systemd.remove_service(svc)


@agent_action
def agent_service_up(args: argparse.Namespace, agent: Agent) -> None:
  agent.start_static_services(args.service)


@agent_action
def agent_service_down(args: argparse.Namespace, agent: Agent) -> None:
  agent.stop_static_services(args.service)


@agent_action
def agent_service_status(args: argparse.Namespace, agent: Agent) -> None:
  from tabulate import tabulate

  table = []
  for svc in agent.static_services:
    current_marker = svc.current_marker
    table.append(
      [
        # Name
        svc.name,
        # Active
        svc.active,
        # Consistent
        current_marker is None or current_marker == agent.registry_id,
      ]
    )

  print(
    tabulate(
      table, headers=["Name", "Active", "Consistent"], tablefmt="rounded_outline", showindex=True
    )
  )
