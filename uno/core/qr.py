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
import pathlib


from .exec import exec_command


def _encode_file_png(file_in, mode, file_out):
  file_out = pathlib.Path(file_out)
  file_out.parent.mkdir(parents=True, exist_ok=True)
  exec_command(
    ["sh", "-c", " ".join(["qrencode", "-t", "png", "-o", str(file_out), "<", str(file_in)])],
    fail_msg="failed to encode PNG qr code",
  )
  file_out.chmod(mode)


def _encode_file_utf8(file_in, mode, file_out=None):
  result = exec_command(
    ["qrencode", "-t", "ansiutf8", str(file_in)],
    fail_msg="failed to encode utf8 qr code",
    output=file_out,
  )
  if file_out:
    file_out.chmod(mode)
  return result.stdout.decode("utf-8")


def encode_qr_from_file(file_in, file_out=None, format="png", mode: int = 0o644):
  if format == "png":
    return _encode_file_png(file_in, mode, file_out)
  elif format == "utf8":
    return _encode_file_utf8(file_in, mode, file_out)
  else:
    raise ValueError(format)
