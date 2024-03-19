from pathlib import Path
from typing import Iterable
from enum import Enum
import os

from ..core.log import Logger as log

class UvnTopic(Enum):
  UVN_ID = "uno/uvn"
  CELL_ID = "uno/cell"
  BACKBONE = "uno/config"

def locate_rti_license(search_path: Iterable[Path] | None = None) -> Path | None:
  searched = set()
  def _search_dir(root: Path):
    root = root.resolve()
    if root in searched:
      return None
    rti_license = root / "rti_license.dat"
    log.debug(f"[RTI-LICENSE] checking candidate: {rti_license}")
    if rti_license.is_file():
      log.debug(f"[RTI-LICENSE] found in {root}")
      return rti_license
    searched.add(root)
    return None

  for root in search_path:
    rti_license = _search_dir(root)
    if rti_license:
      return rti_license

  # Check if there is already a license in the specified directory
  rti_license_env = os.getenv("RTI_LICENSE_FILE")
  if rti_license_env:
    rti_license = Path(rti_license_env)
    if rti_license.is_file():
      log.warning(f"[RTI-LICENSE] detected RTI_LICENSE_FILE = {rti_license}")
      return rti_license

  default_path = [Path.cwd()]
  connext_home_env = os.getenv("CONNEXTDDS_DIR", os.getenv("NDDSHOME"))
  if connext_home_env:
    default_path.add(connext_home_env)
  for root in default_path:
    rti_license = _search_dir(root)
    if rti_license:
      return rti_license

  return None

