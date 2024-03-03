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
from typing import Optional, Mapping
from pathlib import Path

from .uvn_id import ParticleId, UvnId
from .render import Templates
from .qr import encode_qr_from_file
from .wg import WireGuardInterface, WireGuardConfig
from .vpn_config import CentralizedVpnConfig
from .time import Timestamp

from .log import Logger as log

def write_particle_configuration(
    particle: ParticleId,
    particle_vpn_config: WireGuardConfig,
    output_dir: Path,
    output_filename: Optional[str]=None) -> set[Path]:
  if output_filename is None:
    output_filename = particle.name
  particle_cfg_file = output_dir / f"{output_filename}.wireguard"
  particle_qr_file = output_dir / f"{output_filename}.png"
  output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
  Templates.generate(particle_cfg_file, *particle_vpn_config.template_args, mode=0o600)
  encode_qr_from_file(particle_cfg_file, particle_qr_file, mode=0o600)
  return {particle_cfg_file, particle_qr_file}


def generate_particle_packages(
    uvn_id: UvnId,
    particle_vpn_configs: Mapping[int, CentralizedVpnConfig],
    output_dir: Path) -> set[Path]:
  generated = set()

  if output_dir.is_dir():
    output_dir.unlink()
  output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)

  for particle in uvn_id.particles.values():
    particle_dir = output_dir / particle.name
    particle_dir.mkdir(mode=0o700)

    for cell_id, cell_particles_vpn_config in particle_vpn_configs.items():
      cell = uvn_id.cells[cell_id]
      particle_vpn_config = cell_particles_vpn_config.peer_configs[particle.id]
      write_particle_configuration(
        particle=particle,
        particle_vpn_config=particle_vpn_config,
        output_dir=particle_dir,
        output_filename=cell.name)

    # Render an index.html
    index_html = particle_dir / "index.html"
    index_html.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    Templates.generate(index_html, "particles/index.html", {
      "uvn_id": uvn_id,
      "particle": particle,
      "generation_ts": Timestamp.now().format(),
    })

    import shutil
    shutil.make_archive(particle_dir, format="zip", root_dir=particle_dir.parent, base_dir=particle_dir.name)
    particle_archive = Path(f"{particle_dir}.zip")
    if not particle_archive.is_file():
      raise RuntimeError("failed to create particle package", particle_archive)
    shutil.rmtree(particle_dir)
    particle_archive.chmod(0o600)
    log.warning(f"[PARTICLE] package generated: {particle_archive}")

  return generated

