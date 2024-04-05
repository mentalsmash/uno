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
  CELL_PACKAGE_EXT = ".uvn-agent"
  PARTICLE_PACKAGE_EXT = ".zip"


  @classmethod
  def cell_archive_file(cls, cell: Cell | None = None, cell_name: str | None = None, uvn_name: str | None = None, basename: bool=False) -> str:
    cell_name = cell_name or cell.name
    uvn_name = uvn_name or cell.uvn.name
    return f"{uvn_name}__{cell_name}{cls.CELL_PACKAGE_EXT if not basename else ''}"


  @classmethod
  def particle_archive_file(cls, particle: Particle, basename: bool=False) -> str:
    return f"{particle.uvn.name}__{particle.name}{cls.PARTICLE_PACKAGE_EXT if not basename else ''}"


  @classmethod
  def particle_cell_file(cls, particle: Particle, cell: Cell | None = None, ext: str=None) -> str:
    return f"{particle.uvn.name}__{particle.name}__{cell.name}{ext if ext is not None else ''}"


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
    archive_package_name = cls.cell_archive_file(cell)
    agent_package = output_dir / archive_package_name
    cls.log.activity("generate cell agent package: {}", agent_package)

    # Generate package in a temporary directory
    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name)
    package_files: list[Path] = []
    
    # Export DDS keys from identity db
    id_dir = tmp_dir / ".id-import"
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

    # Create a participant from the registry to
    # read additional bundled files
    participant = registry.middleware.participant(
      registry=registry,
      owner=cell)
    for src in participant.cell_agent_package_files:
      dst = src.relative_to(participant.root)
      tgt = tmp_dir / dst
      tgt.parent.mkdir(exist_ok=True, parents=True)
      exec_command(["cp", "-v", src, tgt])
      package_files.append(tgt)


    # Generate agent's database in the temporary directory
    db = registry.generate_cell_database(cell, root=tmp_dir)
    package_files.append(db.db_file)

    # Store all files in a single archive
    cls.mkarchive(agent_package, base_dir=tmp_dir, files=package_files)

    cls.log.info("cell agent package generated: {}", agent_package)

    return agent_package


  @classmethod
  def generate_cell_agent_install_guide(cls,
      registry: "Registry",
      cell: Cell,
      output_dir: Path):
    import uno
    assert(registry.deployed)
    assert(cell.object_id is not None)
    # Reuse the same base file name as the cell agent archive
    cell_package = Path(cls.cell_archive_file(cell))
    guide_file_name = cls.cell_archive_file(cell, basename=True)
    guide_file_name = f"{guide_file_name}.html"
    guide_file = output_dir / guide_file_name
    guide_file.parent.mkdir(exist_ok=True, parents=True)
    other_cells = sorted((c for c in cell.uvn.cells.values() if c != cell), key=lambda c: c.id)
    install_base = "/opt/uno"
    html_body = Templates.render("install/agent_install_guide.md", {
      "generation_ts": Timestamp.now(),
      "uvn": registry.uvn,
      "cell": cell,
      "cell_package": cell_package,
      "install_base": install_base,
      "venv": install_base + "/venv",
      "agent_root": install_base + "/" + cell.name,
      "middleware_install": registry.middleware.install_instructions,
      # Cache some frequently used variables for easier reference
      "allowed_lans": list(cell.allowed_lans),
      "address": cell.address,
      "peers": [
        {
          "cell": peer_cell,
          "port": registry.uvn.settings.backbone_vpn.port + i,
          "port_i": i,
          "peer_port": registry.uvn.settings.backbone_vpn.port + peer["peer_port"],
          "peer_port_i": peer["peer_port"],
          "direction":(
            "l" if not cell.private and peer_cell.private else
            "r" if cell.private and not peer_cell.private else
            "lr"
          ),
        }
        for i, peer in enumerate(registry.uvn.deployment_peers(cell, registry.deployment))
          for peer_cell in [peer["cell"]]
      ],
      "other_cells": other_cells,
      "remote_lans": [
        (c, lan)
        for c in other_cells
          for lan in c.allowed_lans
      ],
      "uno_version": uno.__version__,
      "uno_repo_url": "https://github.com/mentalsmash/uno",
      "uno_dependencies": [
        "psmisc",
        "iproute2",
        "iptables",
        "python3-pip",
        "wireguard-dkms",
        "wireguard-tools",
        "frr",
        "iputils-ping",
        "tar",
        "qrencode",
        "lighttpd",
        "openssl",
        "git",
      ],
      "deployment_host": "agent-host",
      "deployment_user": cell.owner.guessed_username,
    }, processors=[
      Templates.markdown_to_html,
    ])
    Templates.generate(guide_file, "install/agent_install_guide.html", {
      "cell": cell,
      "uvn": cell.uvn,
      "body": html_body,
      "pygments_css": Templates.pygments_css,
    })
    cls.log.info("cell agent installation guide generated: {}", guide_file)


  @classmethod
  def extract_cell_agent_package(cls, package: Path, agent_dir: Path, exclude: list[str] | None = None) -> None:
    package = package.resolve()
    cls.log.activity("extracting agent package contents: {}", agent_dir)
    exec_command(["tar", "xvJf", package, *(f"--exclude={e}" for e in (exclude or []))], cwd=agent_dir)
    agent_dir.chmod(0o755)
    cls.log.info("agent package extracted: {} → {}", package, agent_dir)


  @classmethod
  def generate_particle_package(cls,
      registry: "Registry",
      particle: Particle,
      output_dir: Path) -> None:
    cls.log.activity("generate particle package: {}", particle)
    # Generate package in a temporary directory
    particle_archive_name = cls.particle_archive_file(particle)

    tmp_dir_h = tempfile.TemporaryDirectory()
    tmp_dir = Path(tmp_dir_h.name) / Path(particle_archive_name).stem
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

    particle_archive = output_dir / particle_archive_name
    cls.mkarchive(particle_archive, base_dir=tmp_dir.parent, format=Path(particle_archive_name).suffix[1:])

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
      output_filename = cls.particle_cell_file(particle, cell)
    particle_cfg_file = output_dir / f"{output_filename}.conf"
    particle_qr_file = output_dir / f"{output_filename}.png"
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    Templates.generate(particle_cfg_file, *particle_vpn_config.template_args, mode=0o600)
    encode_qr_from_file(particle_cfg_file, particle_qr_file, mode=0o600)
    return {particle_cfg_file, particle_qr_file}

