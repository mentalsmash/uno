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
from typing import Iterable
import subprocess

from .render import Templates
from ..core.exec import exec_command
from ..core.time import Timer
from ..core.log import Logger
log = Logger.sublogger("lighttpd")
from ..registry.certificate_subject import CertificateSubject


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
      uwsgi: int=0,
      bind_addresses: Iterable[str]|None=None):
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
    self.bind_addresses = list(bind_addresses or [])
    self._lighttpd_pid = None
    self._lighttpd_conf = self.root / "lighttpd.conf"
    self._lighttpd_pem =  self.root / "lighttpd.pem"

  def _assert_ssl_cert(self, regenerate: bool=True) -> None:
    log.debug("creating server SSL certificate")
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
    log.debug("SSL certificate: {}", self._lighttpd_pem)


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
        "bind_addresses": self.bind_addresses,
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
      detected_pid = []
      def _check_online() -> bool:
        if not self._lighttpd_pid.is_file():
          return False
        try:
          detected_pid.append(int(self._lighttpd_pid.read_text()))
          return True
        except:
          return False
      timer = Timer(10, .1, _check_online, log,
        "waiting for lighttpd to come online",
        "lighttpd not ready yet",
        ready_message=None,
        timeout_message="lighttpd failed to come online")
      timer.wait()
      log.info("lighttpd started ({}), listening on {} interfaces: {}",
        detected_pid.pop(),
        len(self.bind_addresses),
        ', '.join(f"{a}:{self.port}" for a in self.bind_addresses))
    except Exception as e:
      self._lighttpd_pid = None
      self._lighttpd = None
      log.error("failed to start lighttpd")
      # log.exception(e)
      if lighttpd_started:
        # lighttpd was started by we couldn't detect its pid
        log.error("lighttpd process was started but possibly not stopped. Please check your system.")
      raise e


  def stop(self) -> None:
    if self._lighttpd_pid is None:
      # Not started
      return

    lighttpd_stopped = False
    try:
      if self._lighttpd_pid.is_file():
        pid = int(self._lighttpd_pid.read_text())
        log.debug("stopping lighttpd: pid={}", pid)
        exec_command(["kill", "-s", "SIGTERM", str(pid)],
          fail_msg="failed to signal lighttpd process")
      # TODO(asorbini) check that lighttpd actually stopped
      lighttpd_stopped = True
      log.activity("stopped")
    except Exception:
      log.error("error while stopping:")
      if lighttpd_stopped:
        log.error("failed to stop lighttpd. Please check your system.")
      raise
    finally:
      self._lighttpd_pid = None
      self._lighttpd = None

