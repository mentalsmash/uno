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
import pathlib

import libuno.log
logger = libuno.log.logger("uvn.qr")

from libuno.exec import exec_command

def _encode_file_png(file_in, file_out):
    file_out = pathlib.Path(file_out)
    file_out.parent.mkdir(parents=True, exist_ok=True)
    exec_command(
        ["sh", "-c", " ".join(["qrencode", "-t", "png", "-o", str(file_out), "<", str(file_in)])],
        fail_msg="failed to encode PNG qr code")

def _encode_file_utf8(file_in, file_out=None):
    result = exec_command(
        ["qrencode", "-t", "ansiutf8", str(file_in)],
        fail_msg="failed to encode utf8 qr code",
        output=file_out)
    return result.stdout.decode("utf-8")

def encode_file(file_in, file_out=None, format="png"):
    if format == "png":
        return _encode_file_png(file_in, file_out)
    elif format == "utf8":
        return _encode_file_utf8(file_in, file_out)
    else:
        raise ValueError(format)
