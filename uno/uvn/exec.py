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
import os
import subprocess
from pathlib import Path
from typing import Optional, Sequence, Union

from .log import Logger as log, level as log_level, verbosity


DEBUG = bool(os.environ.get("DEBUG", False))

def exec_command(
    cmd_args: Sequence[Union[str, Path]],
    fail_msg: Optional[str] = None,
    root: bool = False,
    shell: bool = False,
    cwd: Optional[Path] = None,
    noexcept: bool = False,
    output_file: Optional[Path] = None,
    capture_output: bool=False):
  if root and os.geteuid() != 0:
    cmd_args = ["sudo", *cmd_args]

  run_args = {"shell": shell,}
  if cwd is not None:
    run_args["cwd"] = cwd

  if DEBUG:
    log.debug(f"[exec] {' '.join(map(str, cmd_args))}")

  if output_file is not None:
    output_file.parent.mkdir(exist_ok=True, parents=True)
    with output_file.open("w") as outfile:
      result = subprocess.run(cmd_args,
        stdout=outfile,
        stderr=outfile,
        **run_args)
  else:
    import sys
    result = subprocess.run(cmd_args,
      stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL if verbosity() != log_level.debug else sys.stdout,
      stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL if verbosity() != log_level.debug else sys.stderr,
      **run_args)
  
  # log.debug(f"[exec] result = {result.returncode}")

  if not noexcept and result.returncode != 0:
    cmd = ' '.join(map(str, cmd_args))
    # stdout = result.stdout.decode("utf-8") if result.stdout else "",
    # stderr = result.stderr.decode("utf-8") if result.stderr else ""
    # log.error(f"command failed: {cmd}")
    # log.error("-"*20)
    # log.error("stdout:")
    # log.error("-"*20)
    # log.error(stdout)
    # log.error("-"*20)
    # log.error("stderr:")
    # log.error("-"*20)
    # log.error(stderr)
    raise RuntimeError(
      "failed to execute command" if fail_msg is None else fail_msg,
      cmd)

  return result
