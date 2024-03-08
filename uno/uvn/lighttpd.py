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
import time
from typing import TYPE_CHECKING, Iterable
import subprocess

from .render import Templates
from .exec import exec_command
from .keys_dds import CertificateSubject

from .log import Logger as log

class Lighttpd:
  def __init__(self,
      root: Path,
      doc_root: Path,
      log_dir: Path,
      cert_subject: CertificateSubject,
      port: int=443,
      secret: str|None=None,
      auth_realm: str|None=None,
      conf_template: str="httpd/lighttpd.conf",
      protected_paths: Iterable[str]|None=None,
      uwsgi: int=0):
    self.root = root
    self.port = port
    self.doc_root = doc_root
    self.log_dir = log_dir
    self.secret = secret
    self.auth_realm = auth_realm
    self.cert_subject = cert_subject
    self.conf_template = conf_template
    self.protected_paths = list(protected_paths or [])
    self.uwsgi = uwsgi
    self._lighttpd_pid = None
    self._lighttpd_conf = self.root / "lighttpd.conf"
    self._lighttpd_pem =  self.root / "lighttpd.pem"

  def _assert_ssl_cert(self, regenerate: bool=True) -> None:
    log.debug(f"[HTTPD] creating server SSL certificate")
    if self._lighttpd_pem.is_file():
      if not regenerate:
        return
      self._lighttpd_pem.unlink()

    pem_subject = str(self.cert_subject)
    exec_command([
      "openssl",
        "req",
        "-x509",
        "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:secp384r1",
        "-keyout", self._lighttpd_pem,
        "-out",  self._lighttpd_pem,
        "-days", "365",
        "-nodes",
        "-subj", pem_subject,
    ])
    self._lighttpd_pem.chmod(0o600)
    log.debug(f"[HTTPD] SSL certificate: {self._lighttpd_pem}")


  def start(self) -> None:
    if self._lighttpd_pid is not None:
      raise RuntimeError("httpd already started")

    lighttpd_started = False
    try:
      self._lighttpd_pid = self._lighttpd_conf.parent / "lighttpd.pid"

      self._assert_ssl_cert()

      htdigest = self._lighttpd_conf.parent / "lighttpd.auth"
      if self.secret is None:
        htdigest.write_text("")
      else:
        with htdigest.open("wt") as output:
          output.write(self.secret + "\n")
      htdigest.chmod(0o600)

      self._lighttpd_conf.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
      Templates.generate(self._lighttpd_conf, self.conf_template, {
        "root": self.doc_root,
        "port": self.port,
        "pid_file": self._lighttpd_pid,
        "pem_file": self._lighttpd_pem,
        "log_dir": self.log_dir,
        "htdigest": htdigest,
        "auth_realm": self.auth_realm,
        "protected_paths": self.protected_paths,
        "uwsgi": self.uwsgi,
      })

      # Delete pid file if it exists
      if self._lighttpd_pid.is_file():
        self._lighttpd_pid.unlink()

      # Make sure that required directories exist
      self.root.mkdir(parents=True, exist_ok=True)
      self._lighttpd_pid.parent.mkdir(parents=True, exist_ok=True)
      
      # Start lighttpd
      import os
      self._lighttpd = subprocess.Popen(
        ["lighttpd", "-D", "-f", self._lighttpd_conf],
        preexec_fn=os.setpgrp)
      lighttpd_started = True

      # Wait for lighttpd to come online and
      max_wait = 5
      pid = None
      for i in range(max_wait):
        log.debug("[HTTPD] waiting for lighttpd to come online...")
        if self._lighttpd_pid.is_file():
          try:
            pid = int(self._lighttpd_pid.read_text())
            break
          except:
            continue
        time.sleep(1)
      if pid is None:
        raise RuntimeError("failed to detect lighttpd process")
      log.debug(f"[HTTPD] lighttpd started: pid={pid}")
      log.warning(f"[HTTPD] listening on 0.0.0.0:{self.port}")
    except Exception as e:
      self._lighttpd_pid = None
      self._lighttpd = None
      log.error("failed to start lighttpd")
      # log.exception(e)
      if lighttpd_started:
        # lighttpd was started by we couldn't detect its pid
        log.error("[HTTPD] lighttpd process was started but possibly not stopped. Please check your system.")
      raise e


  def stop(self) -> None:
    if self._lighttpd_pid is None:
      # Not started
      return

    lighttpd_stopped = False
    try:
      if self._lighttpd_pid.is_file():
        pid = int(self._lighttpd_pid.read_text())
        log.debug(f"[HTTPD] stopping lighttpd: pid={pid}")
        exec_command(["kill", "-s", "SIGTERM", str(pid)],
          fail_msg="failed to signal lighttpd process")
      # TODO(asorbini) check that lighttpd actually stopped
      lighttpd_stopped = True
      log.activity(f"[HTTPD] stopped")
    except Exception as e:
      log.error(f"[HTTPD] error while stopping:")
      if lighttpd_stopped:
        log.error(f"[HTTPD] failed to stop lighttpd. Please check your system.")
      raise
    finally:
      self._lighttpd_pid = None
      self._lighttpd = None

