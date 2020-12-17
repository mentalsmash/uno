###############################################################################
# (C) Copyright 2020 Andrea Sorbini
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

import libuno.log
logger = libuno.log.logger("uvn.exec")

def is_root():
    return os.geteuid() == 0

def decode_output(stdout):
    return filter(len, map(str.strip,
                stdout.decode("utf-8").strip().split("\n")))

def exec_command(
        cmd_args,
        fail_msg=None,
        root=False,
        shell=False,
        cwd=None,
        exception=ValueError,
        noexcept=False,
        quiet=False,
        output=None,
        display=False,
        display_level="info",
        logger=logger):
    if root and not is_root():
        cmd = " ".join(cmd_args)
        cmd_args = ["sudo", "sh", "-c", cmd]

    if cwd is None:
        cwd = os.getcwd()

    if not quiet:
        logger.debug("[exec] {}", " ".join(map(str, cmd_args)))
    def _exec(stdout, stderr):
        return subprocess.run(cmd_args,
                        cwd=str(cwd),
                        shell=shell,
                        stdout=stdout, stderr=stderr)
    if output:
        if not quiet:
            logger.debug("[exec] output file: {}", output)
        output.parent.mkdir(exist_ok=True, parents=True)
        with output.open("w") as outfile:
            result = _exec(outfile, outfile)
    else:
        result = _exec(subprocess.PIPE, subprocess.PIPE)

    if not quiet:
        logger.command(cmd_args, result.returncode,
            result.stdout, result.stderr, display)

    if not noexcept and result.returncode != 0:
        if fail_msg is None:
            emsg = "failed to run as root: {}".format("".join(cmd_args))
        else:
            emsg = fail_msg
        raise exception(fail_msg)

    return result
