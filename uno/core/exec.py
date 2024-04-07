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
from typing import Sequence, Union

from .log import Logger

log = Logger.sublogger("exec")

def shell_which(command: str) -> Path | None:
  cmd_path = exec_command([f"which {command} || true"], shell=True, capture_output=True).stdout.decode().strip()
  if not cmd_path:
    return None
  return Path(cmd_path)


def exec_command(
    cmd_args: Sequence[Union[str, Path]],
    fail_msg: str|None = None,
    root: bool = False,
    shell: bool = False,
    cwd: Path|None = None,
    noexcept: bool = False,
    output_file: Path|None = None,
    capture_output: bool=False,
    debug: bool=False):
  if root and os.geteuid() != 0:
    cmd_args = ["sudo", *cmd_args]

  debug = debug or log.DEBUG

  run_args = {"shell": shell,}

  logger = (log.trace if not debug else log.info)
  if cwd is not None:
    run_args["cwd"] = cwd
    logger("cd {}", cwd)

  logger(" ".join(["{}"]*len(cmd_args)), *cmd_args)

  try:
    if output_file is not None:
      output_file.parent.mkdir(exist_ok=True, parents=True)
      with output_file.open("w") as outfile:
        result = subprocess.run(cmd_args,
          stdout=outfile,
          stderr=outfile,
          check=not noexcept,
          **run_args)
    else:
      import sys
      if capture_output:
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE
      elif log.level >= log.Level.tracedbg or debug:
        stdout = sys.stdout
        stderr = sys.stderr
      else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL

      result = subprocess.run(cmd_args,
        stdout=stdout,
        stderr=stderr,
        check=not noexcept,
        **run_args)
  except subprocess.CalledProcessError as e:
    log.command(cmd_args, e.returncode, e.stdout, e.stderr)
    raise

  # if not noexcept and result.returncode != 0:
  #   cmd = ' '.join(map(str, cmd_args))
  #   # stdout = result.stdout.decode("utf-8") if result.stdout else "",
  #   # stderr = result.stderr.decode("utf-8") if result.stderr else ""
  #   # log.error(f"command failed: {cmd}")
  #   # log.error("-"*20)
  #   # log.error("stdout:")
  #   # log.error("-"*20)
  #   # log.error(stdout)
  #   # log.error("-"*20)
  #   # log.error("stderr:")
  #   # log.error("-"*20)
  #   # log.error(stderr)
  #   log.command(cmd_args, result.returncode, result.stdout, result.stderr)
  #   raise RuntimeError(
  #     "failed to execute command" if fail_msg is None else fail_msg,
  #     cmd)

  return result
