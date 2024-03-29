from pathlib import Path
from typing import TYPE_CHECKING, Iterable
import tempfile
import shutil

from ..core.exec import exec_command
from ..core.render import Templates
from ..core.wg import WireGuardConfig
from ..core.qr import encode_qr_from_file
from ..core.time import Timestamp
from .cell import Cell
from .particle import Particle
from .database import Database
from .versioned import Versioned

if TYPE_CHECKING:
  from .registry import Registry

class Packager(Versioned):
  @classmethod
  def mkarchive(cls,
        archive: Path,
        base_dir: Path,
        files: Iterable[Path]|None=None,
        format: str="tar"):
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)    
    try:
      if format == "tar":
        exec_command(
          ["tar", "cJf", archive,
            *(f.relative_to(base_dir) for f in files)],
          cwd=base_dir)
      elif format == "zip":
        archive_dir = archive.with_suffix("")
        shutil.make_archive(archive_dir, format=format, root_dir=base_dir, base_dir=archive_dir.name)
      archive.chmod(0o600)
    except Exception as e:
      cls.log.error("failed to create archive: {}", archive)
      cls.log.exception(e)
      try:
        exec_command(["rm", "-f", archive])
      except Exception as i:
        cls.log.error("failed to delete incomplete archive: {}", archive)
        cls.log.exception(i)
      raise


  @classmethod
  def generate_cell_agent_package(cls,
      registry: "Registry",
      cell: Cell,
      output_dir: Path) -> None:
    # Check that the uvn has been deployed
    assert(registry.deployed)
    assert(cell.object_id is not None)
    agent_package = output_dir / f"{cell.uvn.name}__{cell.name}.uvn-agent"
    cls.log.activity("generate cell agent package: {}", agent_package)

    # Generate package in a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)
    package_files: list[Path] = []
    
    # Export DDS keys from identity db
    id_dir = tmp_dir / "id"
    exported_keymat = registry.id_db.export_keys(
      output_dir=id_dir,
      target=cell)
    for f in exported_keymat:
      package_files.append(id_dir / f)

    # Generate an "identity file" so we know who owns the agent
    id_file = tmp_dir / "id.yaml"
    id_file.write_text(registry.yaml_dump({
      "owner": cell.object_id,
      "config_id": registry.config_id,
    }))
    package_files.append(id_file)

    # Copy additional files (some possibly optional)
    for src, dst, optional in [
        (registry.rti_license, None, False),
      ]:
      dst = dst or src.name
      tgt = tmp_dir / dst
      if optional and not src.exists():
        continue
      exec_command(["cp", "-v", src, tgt])
      package_files.append(tgt)

    
    # Generate agent's database
    db = Database(tmp_dir, create=True)
    db.initialize()
    registry.export_cell_database(db, cell)
    package_files.append(db.db_file)


    # Store all files in a single archive
    cls.mkarchive(agent_package, base_dir=tmp_dir, files=package_files)

    cls.log.info("cell agent package generated: {}", agent_package)

    return agent_package


  @classmethod
  def extract_cell_agent_package(cls, package: Path, agent_dir: Path) -> None:
    # Extract package to a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)

    package = package.resolve()

    cls.log.debug("extracting agent package contents: {}", tmp_dir)
    exec_command(["tar", "xvJf", package], cwd=tmp_dir)

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = agent_dir.resolve()
    agent_dir.chmod(0o755)

    for f, permissions in {
        "rti_license.dat": 0o600,
        "id.yaml": 0o644,
        Database.DB_NAME: 0o600,
        ("id", ".id-import"): 0o700,
      }.items():
      if isinstance(f, tuple):
        in_f = f[0]
        out_f = f[1]
      else:
        in_f = f
        out_f = f
      src = tmp_dir / in_f
      dst = agent_dir / out_f
      # shutil.copy2(src, dst)
      exec_command(["cp", "-rv", src, dst])
      dst.chmod(permissions)

    cls.log.info("agent package extracted: {}", package)


  @classmethod
  def generate_particle_package(cls,
      registry: "Registry",
      particle: Particle,
      output_dir: Path) -> None:
    cls.log.activity("generate particle package: {}", particle)
    # Generate package in a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name) / f"{registry.uvn.name}__{particle.name}"
    tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    

    for cell_id, cell_particles_vpn_config in registry.vpn_config.particles_vpns.items():
      cell = registry.uvn.cells[cell_id]
      cls.log.activity("export particle configuration: {}, {}", particle, cell)
      particle_vpn_config = cell_particles_vpn_config.peer_config(particle.id)
      cls.write_particle_configuration(
        particle=particle,
        cell=cell,
        particle_vpn_config=particle_vpn_config,
        output_dir=tmp_dir)

    # Render an index.html
    index_html = tmp_dir / "index.html"
    Templates.generate(index_html, "particles/index.html", {
      "uvn": registry.uvn,
      "particle": particle,
      "generation_ts": Timestamp.now().format(),
    })

    particle_archive = output_dir / f"{tmp_dir.name}.zip"
    cls.mkarchive(particle_archive, base_dir=tmp_dir.parent, format="zip")

    cls.log.info("particle package generated: {}", particle_archive)

    return particle_archive


  @classmethod
  def write_particle_configuration(cls,
      particle: Particle,
      cell: Cell,
      particle_vpn_config: WireGuardConfig,
      output_dir: Path,
      output_filename: str|None=None) -> set[Path]:
    if output_filename is None:
      output_filename = f"{particle.uvn.name}__{particle.name}__{cell.name}"
    particle_cfg_file = output_dir / f"{output_filename}.conf"
    particle_qr_file = output_dir / f"{output_filename}.png"
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    Templates.generate(particle_cfg_file, *particle_vpn_config.template_args, mode=0o600)
    encode_qr_from_file(particle_cfg_file, particle_qr_file, mode=0o600)
    return {particle_cfg_file, particle_qr_file}

