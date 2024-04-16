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
        "fix-file-ownership",
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
