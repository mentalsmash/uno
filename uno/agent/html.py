from typing import Iterable, TYPE_CHECKING
from pathlib import Path
import shutil
import yaml

from ..registry.deployment import P2PLinksMap
from ..registry.cell import Cell
from ..registry.lan_descriptor import LanDescriptor
from ..core.time import Timestamp
from ..core.wg import WireGuardInterface
from ..core.log import Logger as log
from .peer import UvnPeersList
from .tester import UvnPeersTester
from .router import Router
from .render import Templates

if TYPE_CHECKING:
  from .cell_agent import CellAgent

def index_html(agent: "CellAgent", docroot: Path) -> None:
    _index_html(
      www_root=docroot,
      generation_ts=Timestamp.now().format(),
      peers=agent.peers,
      deployment=agent.deployment,
      ts_start=agent.ts_start,
      backbone_vpns=agent.backbone_vpns,
      cell=agent.cell,
      lans=agent.lans,
      particles_dir=agent.particles_dir,
      particles_vpn=agent.particles_vpn,
      peers_tester=agent.peers_tester,
      root_vpn=agent.root_vpn,
      router=agent.router,
      uvn_status_plot=agent.uvn_status_plot,
      uvn_backbone_plot=agent.uvn_backbone_plot,
      vpn_stats=agent.vpn_stats)


def _index_html(
    www_root: Path,
    peers: UvnPeersList,
    deployment: P2PLinksMap,
    ts_start: Timestamp,
    backbone_vpns: Iterable[WireGuardInterface]|None=None,
    cell: Cell|None=None,
    generation_ts: Timestamp|None=None,
    lans: Iterable[LanDescriptor]|None=None,
    particles_dir: Path|None=None,
    particles_vpn: WireGuardInterface|None=None,
    peers_tester: UvnPeersTester|None=None,
    root_vpn: WireGuardInterface|None=None,
    router: Router|None=None,
    uvn_status_plot: Path|None=None,
    uvn_backbone_plot: Path|None=None,
    vpn_stats: dict|None=None) -> None:
  log.debug("[WWW] regenerating agent status...")

  # Copy particle configurations if they exist
  if particles_dir and particles_dir.is_dir():
    particles_dir_www = www_root / "particles"
    if particles_dir_www.is_dir():
      shutil.rmtree(particles_dir_www)
    shutil.copytree(particles_dir, particles_dir_www)

  if router:
    router.ospf_summary()
    router.ospf_lsa()
    router.ospf_routes()
    ospf_dir = www_root / "ospf"
    ospf_summary = ospf_dir / f"{router.ospf_summary_f.name}.txt"
    ospf_lsa = ospf_dir / f"{router.ospf_lsa_f.name}.txt"
    ospf_routes = ospf_dir / f"{router.ospf_routes_f.name}.txt"
    if ospf_dir.is_dir():
      shutil.rmtree(ospf_dir)
    ospf_dir.mkdir(exist_ok=True)
    shutil.copy2(router.ospf_summary_f, ospf_summary)
    shutil.copy2(router.ospf_lsa_f, ospf_lsa)
    shutil.copy2(router.ospf_routes_f, ospf_routes)

  if uvn_status_plot and uvn_status_plot.is_file():
    www_status_plot = www_root / uvn_status_plot.name
    shutil.copy2(uvn_status_plot, www_status_plot)
    www_status_plot = www_status_plot.relative_to(www_root)
  else:
    www_status_plot = None
  
  if uvn_backbone_plot and uvn_backbone_plot.is_file():
    www_backbone_plot = www_root / uvn_backbone_plot.name
    shutil.copy2(uvn_backbone_plot, www_backbone_plot)
    www_backbone_plot = www_backbone_plot.relative_to(www_root)
  else:
    www_backbone_plot = None

  index_html = www_root / "index.html"

  online_peers = sum(1 for c in peers.online_cells)
  offline_peers = sum(1 for c in peers.cells) - online_peers

  Templates.generate(index_html, "www/index.html", {
    "cell": cell,
    "deployment": deployment,
    "backbone_plot": www_status_plot,
    "backbone_plot_basic": www_backbone_plot,
    "backbone_vpns": list(backbone_vpns or []),
    "generation_ts": (generation_ts or Timestamp.now()).format(),
    "lans": list(lans or []),
    "particles_vpn": particles_vpn,
    "peers": peers,
    "peers_offline": offline_peers,
    "peers_online": online_peers,
    "peers_tester": peers_tester,
    "registry_id": peers.registry_id or "",
    "root_vpn": root_vpn,
    "router": router,
    "ospf_summary": ospf_summary.relative_to(www_root),
    "ospf_lsa": ospf_lsa.relative_to(www_root),
    "ospf_routes": ospf_routes.relative_to(www_root),
    "ts_start": ts_start.format() if ts_start else None,
    "uvn_id": peers.uvn_id,
    "uvn_settings": yaml.safe_dump(peers.uvn_id.settings.serialize()),
    "vpn_stats": vpn_stats or {
      "interfaces": {},
      "traffic": {
        "rx": 0,
        "tx": 0,
      },
    },
  })

  log.debug("[WWW] agent status updated")
