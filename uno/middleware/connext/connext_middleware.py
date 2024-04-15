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
import os
from pathlib import Path

from uno.middleware import Middleware
from uno.core.log import Logger

from .connext_condition import ConnextCondition
from .connext_participant import ConnextParticipant

log = Logger.sublogger("connext")


class ConnextMiddleware(Middleware):
  CONDITION = ConnextCondition
  PARTICIPANT = ConnextParticipant

  @classmethod
  def install_cell_agent_package_files(cls, registry_root: Path, package_dir: Path) -> list[Path]:
    result = []
    rti_license = cls.locate_rti_license([registry_root])
    if rti_license:
      cls.install_rti_license(package_dir, rti_license)
      result.append(package_dir / "rti_license.dat")
    return result

  @classmethod
  def configure_extracted_cell_agent_package(cls, extracted_package: Path) -> None:
    rti_license = extracted_package / "rti_license.dat"
    if not rti_license.exists():
      cls.install_rti_license(extracted_package, optional=True)
    if not rti_license.exists():
      log.debug("no RTI license files, agents will not be available unless one is provided")

  @classmethod
  def supports_agent(cls, root: Path) -> bool:
    rti_license = cls.locate_rti_license([root])
    if not rti_license or not rti_license.exists():
      log.debug("an RTI license is required to run agents, but none was found")
      return False
    return True

  @classmethod
  def locate_rti_license(cls, search_path: list[Path] | None = None) -> Path | None:
    searched = set()

    def _search_dir(root: Path):
      root = root.resolve()
      if root in searched:
        return None
      rti_license = root / "rti_license.dat"
      log.activity("checking RTI license candidate: {}", rti_license)
      if rti_license.is_file():
        log.activity("RTI license found in {}", root)
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
      if rti_license.exists():
        log.info("detected RTI_LICENSE_FILE = {}", rti_license)
        return rti_license.resolve()
      else:
        log.warning("invalid RTI_LICENSE_FILE := {}", rti_license_env)

    default_path = [Path.cwd()]
    connext_home_env = os.getenv("CONNEXTDDS_DIR", os.getenv("NDDSHOME"))
    if connext_home_env:
      default_path.add(connext_home_env)
    for root in default_path:
      rti_license = _search_dir(root)
      if rti_license:
        return rti_license

    return None

  @classmethod
  def install_rti_license(
    cls, root: Path, user_license: Path | None = None, optional: bool = False
  ) -> None:
    license = root / "rti_license.dat"
    if not license.exists():
      if user_license is None:
        user_license = cls.locate_rti_license(search_path=[root])
        if not user_license or not user_license.is_file():
          if optional:
            return None
          raise RuntimeError("an RTI license file is required but was not specified")
      license.write_bytes(user_license.read_bytes())
      log.warning("cached RTI license: {} → {}", user_license, license)
