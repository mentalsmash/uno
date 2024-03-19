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
from typing import Iterable, Callable, TYPE_CHECKING, Generator
from collections.abc import Mapping
import ipaddress
import json
import yaml
from functools import cached_property

from .deployment import P2PLinksMap
from .uvn_settings import UvnSettings
from .user import User
from .cell import Cell
from .particle import Particle

from ..core.log import Logger as log

from .versioned import Versioned
from .database_object import OwnableDatabaseObject, DatabaseObjectOwner

if TYPE_CHECKING:
  from .database import Database

class ClashingNetworksError(Exception):
  def __init__(self, clashes: Mapping[ipaddress.IPv4Network, set[tuple[object, ipaddress.IPv4Network]]], *args: object) -> None:
    clash_str = repr({
      str(n): [
        (str(o), str(n))
        for o, n in matches
      ]
        for n, matches in clashes.items()
    })
    super().__init__(f"clashing networks detected: {clash_str}", *args)


class Uvn(Versioned, OwnableDatabaseObject, DatabaseObjectOwner):
  PROPERTIES = [
    "name",
    "address",
    "settings",
  ]
  RO_PROPERTIES = [
    "name",
  ]
  REQ_PROPERTIES = RO_PROPERTIES
  STR_PROPERTIES = [
    "name",
  ]
  SERIALIZED_PROPERTIES = [
    "cells",
    "excluded_cells",
    "particles",
    "excluded_particles",
    "owner",
  ]
  PROPERTY_GROUPS = {
    "cell_properties": [
      "all_cells",
      "cells",
      "excluded_cells",
      "private_cells",
    ],
    "particle_properties": [
      "all_particles",
      "particles",
      "excluded_particles",
    ]
  }
  DB_TABLE_PROPERTIES = PROPERTIES
  DB_TABLE = "uvns"
  DB_OWNER = User
  DB_OWNER_TABLE = "uvns_credentials"

  def INITIAL_SETTINGS(self) -> UvnSettings:
    return self.deserialize_child(UvnSettings)

  @classmethod
  def detect_network_clashes(cls,
      records: Iterable[object],
      get_networks: Callable[[object],Iterable[ipaddress.IPv4Network]],
      checked_networks: Iterable[ipaddress.IPv4Network]|None=None
      ) -> Mapping[ipaddress.IPv4Network, set[tuple[object, ipaddress.IPv4Network]]]:
    checked_networks = set(checked_networks or [])
    by_subnet = {
      n: set()
        for n in checked_networks
    }
    explored = set()
    # subnets = set(checked_networks)
    for record in records:
      for net in get_networks(record):
        subnet_cells = by_subnet[net] = by_subnet.get(net, set())
        subnet_cells.add((record, net))
        for subnet in checked_networks or explored:
          if subnet.overlaps(net) or net.overlaps(subnet):
            by_subnet[subnet].add((record, net))
        explored.add(net)
    return {
      n: matches
      for n, matches in by_subnet.items()
        if (not checked_networks or n in checked_networks)
          and len(matches) > 0
    }


  @cached_property
  def owner(self) -> User | None:
    return self.db.owner(self)


  @cached_property
  def all_cells(self) -> Mapping[int, Cell]:
    return {
      **self.cells,
      **self.excluded_cells,
    }


  @cached_property
  def cells(self) -> Mapping[int, Cell]:
    return {
      cell.id: cell
        for cell in self.db.load(Cell,
          where="uvn_id = ? AND excluded = ?",
          params=(self.id, False))
    }


  @cached_property
  def excluded_cells(self) -> Mapping[int, Cell]:
    return {
      cell.id: cell
        for cell in self.db.load(Cell,
          where="uvn_id = ? AND excluded = ?",
          params=(self.id, True))
    }


  @property
  def private_cells(self) -> Mapping[int, Cell]:
    return {
      cell.id: cell
        for cell in self.db.load(Cell,
          where="uvn_id = ? AND address IS NULL",
          params=(self.id,))
    }


  @cached_property
  def all_particles(self) -> Mapping[int, Particle]:
    return {
      **self.particles,
      **self.excluded_particles,
    }


  @cached_property
  def particles(self) -> Mapping[int, Particle]:
    return {
      particle.id: particle
        for particle in self.db.load(Particle,
          where="uvn_id = ? AND excluded = ?",
          params=(self.id, False))
    }


  @cached_property
  def excluded_particles(self) -> Mapping[int, Particle]:
    return {
      particle.id: particle
        for particle in self.db.load(Particle,
          where="uvn_id = ? AND excluded = ?",
          params=(self.id, True))
    }


  @property
  def supports_reconfiguration(self) -> bool:
    # The uvn can be dynamically reconfigured if all cells have a public address,
    # or if the registry has a master address
    return len(self.private_cells) == 0 or bool(self.address)


  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.settings
    for c in self.all_cells.values():
      yield c
    for p in self.all_particles.values():
      yield p


  def prepare_settings(self, val: str | dict | UvnSettings) -> UvnSettings:
    return self.deserialize_child(UvnSettings, val)


  def validate_cell(self, cell: Cell) -> None:
    # Check that the cell's networks don't clash with any other cell's
    if cell.allowed_lans:
      clashes = Uvn.detect_network_clashes(
        records=(c for c in self.cells.values() if c != cell),
        get_networks=lambda c: c.allowed_lans,
        checked_networks=cell.allowed_lans)  
      if clashes:
        raise ClashingNetworksError(clashes)


  def validate_particle(self, particle: Particle) -> None:
    pass


  def log_deployment(self,
      deployment: P2PLinksMap,
      logger: Callable[[Cell, int, str, Cell, int, str, str], None]|None=None) -> None:
    logged = []
    def _log_deployment(
        peer_a: Cell,
        peer_a_port_i: int,
        peer_a_endpoint: str,
        peer_b: Cell,
        peer_b_port_i: int,
        peer_b_endpoint: str,
        arrow: str) -> None:
      if not logged or logged[-1] != peer_a:
        log.info(f"[BACKBONE] {peer_a} →")
        logged.append(peer_a)
      log.info(f"[BACKBONE]   [{peer_a_port_i}] {peer_a_endpoint} {arrow} {peer_b}[{peer_b_port_i}] {peer_b_endpoint}")

    if logger is None:
      logger = _log_deployment

    for peer_a_id, peer_a_cfg in sorted(deployment.peers.items(), key=lambda t: t[0]):
      peer_a = self.cells[peer_a_id]
      for peer_b_id, (peer_a_port_i, peer_a_addr, peer_b_addr, link_subnet) in sorted(
          peer_a_cfg["peers"].items(), key=lambda t: t[1][0]):
        peer_b = self.cells[peer_b_id]
        peer_b_port_i = deployment.peers[peer_b_id]["peers"][peer_a_id][0]
        if not peer_a.address:
          peer_a_endpoint = "private LAN"
        else:
          peer_a_endpoint = f"{peer_a.address}:{self.settings.backbone_vpn.port + peer_a_port_i}"
        if not peer_b.address:
          peer_b_endpoint = "private LAN"
          arrow = "←  "
        else:
          peer_b_endpoint = f"{peer_b.address}:{self.settings.backbone_vpn.port + peer_b_port_i}"
          if peer_a.address:
            arrow = "← →"
          else:
            arrow = "  →"
        logger(peer_a, peer_a_port_i, peer_a_endpoint, peer_b, peer_b_port_i, peer_b_endpoint, arrow)

