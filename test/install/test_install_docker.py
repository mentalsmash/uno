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
from pathlib import Path
import tempfile
import subprocess
import os


def test_install_docker():
  tmp_dir_h = tempfile.TemporaryDirectory()
  uvn_dir = Path(tmp_dir_h.name)
  test_dir = Path(__file__).parent
  force_pull = bool(os.environ.get("FORCE_PULL", False))
  platform = os.environ.get("PLATFORM", "amd64")
  rti_license = os.environ.get("RTI_LICENSE_FILE")
  uno_image = os.environ.get("UNO_IMAGE", "mentalsmash/uno:latest")

  try:
    subprocess.run(
      [
        "docker",
        "run",
        "--rm",
        *(["--pull=always"] if force_pull else []),
        f"--platform=linux/{platform}",
        "-v",
        f"{test_dir.parent.parent}:/uno",
        "-v",
        f"{uvn_dir}:/uvn",
        "-v",
        f"{test_dir}/spec/basic_uvn.yml:/uvn.yaml",
        *(["-v", f"{Path(rti_license).resolve()}:/rti_license.dat"] if rti_license else []),
        uno_image,
        "uno",
        "define",
        "uvn",
        "my-uvn",
        "--spec",
        "/uvn.yaml",
        "-vv",
      ],
      check=True,
    )
    subprocess.run(
      [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{uvn_dir}:/uvn",
        "-v",
        f"{test_dir.parent.parent}:/uno",
        f"--platform=linux/{platform}",
        uno_image,
        "fix-root-permissions",
        f"{os.getuid()}:{os.getgid()}",
        "/uno",
      ],
      check=True,
    )
  finally:
    subprocess.run(
      [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{uvn_dir}:/uvn",
        "-v",
        f"{test_dir.parent.parent}:/uno",
        "ubuntu:latest",
        "chown",
        "-R",
        f"{os.getuid()}:{os.getgid()}",
        "/uvn",
        "/uno",
      ],
      check=True,
    )
