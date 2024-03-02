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
import ipaddress

from typing import Optional, Mapping, Union, Iterable, Sequence

from .exec import exec_command
from .render import Templates
from .monitor_thread import MonitorThread

from .log import Logger as log

def dnsmasq_stop():
  exec_command(["service", "dnsmasq", "stop"],
    fail_msg="failed to stop dnsmasq")

def dnsmasq_start():
  exec_command(["service", "dnsmasq", "start"],
    fail_msg="failed to start dnsmasq")

def dnsmasq_reload():
  exec_command(["service", "dnsmasq", "force-reload"],
    fail_msg="failed to reload dnsmasq")

def systemd_resolved_running():
  res = exec_command(["killall", "-0", "systemd-resolved"],
    noexcept=True,
    fail_msg="failed to check systemd-resolved status")
  return res.returncode == 0

def systemd_resolved_disable():
  if systemd_resolved_running():
    exec_command(["systemctl", "disable", "--now", "systemd-resolved"],
      fail_msg="failed to disable systemd-resolved")
    return True
  return False

def systemd_resolved_enable():
  exec_command(["systemctl", "enable", "--now", "systemd-resolved"],
    fail_msg="failed to re-enable systemd-resolved")


def resolv_conf_install(text: str) -> None:
  from tempfile import NamedTemporaryFile
  resolv_conf = Path("/etc/resolv.conf")
  resolv_conf_bkp = Path("/etc/resolv.conf.uno.bkp")
  if not resolv_conf_bkp.exists():
    exec_command(["cp", resolv_conf, resolv_conf_bkp])
    log.activity(f"[DNS] BACKUP created: {resolv_conf} -> {resolv_conf_bkp}")
  else:
    log.warning(f"[DNS] BACKUP not overwritten: {resolv_conf_bkp}")
  tmp_file_h = NamedTemporaryFile()
  tmp_file = Path(tmp_file_h.name)
  with tmp_file.open("w") as output:
    output.write(text)
    output.write("\n")
    # output.write(resolv_conf.read_text())
    # output.write("\n")
  exec_command(["cp", tmp_file, resolv_conf])


def resolv_conf_restore() -> None:
  resolv_conf = Path("//etc/resolv.conf")
  resolv_conf_bkp = Path("/etc/resolv.conf.uno.bkp")
  if not resolv_conf_bkp.is_file():
    log.error(f"[DNS] BACKUP file not restored: {resolv_conf_bkp}")
    return
  exec_command(["cp", resolv_conf_bkp, resolv_conf])
  exec_command(["rm", resolv_conf_bkp])
  log.activity(f"[DNS] BACKUP restored: {resolv_conf_bkp} -> {resolv_conf}")


class NameserverRecord:
  def __init__(self,
      hostname: str,
      address: Union[str, int],
      server: Optional[str]=None,
      tags: Optional[Iterable[str]]=None):
    self.hostname = hostname
    self.address = ipaddress.ip_address(address)
    self.server = server
    self.tags = set(tags or [])


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, NameserverRecord):
      return False
    return (
      self.hostname == other.hostname
      and self.address == other.address
    )


  def __hash__(self) -> int:
    return hash((self.hostname, self.address))


  def __str__(self) -> str:
    return f"{self.hostname}={self.address}"


  def serialize(self) -> dict:
    serialized = {
      "hostname": self.hostname,
      "address": str(self.address),
      "server": self.server,
      "tags": [t for t in self.tags]
    }
    if not serialized["tags"]:
      del serialized["tags"]
    if not serialized["server"]:
      del serialized["server"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "NameserverRecord":
    return NameserverRecord(
      hostname=serialized["hostname"],
      address=serialized["address"],
      server=serialized.get("server"),
      tags=serialized.get("tags"))


class NameserverMonitorThread(MonitorThread):
  def __init__(self, ns: "Nameserver"):
    self.ns = ns
    super().__init__("ns-monitor")

  def _do_monitor(self):
    self.ns._reload()


class Nameserver:
  HOSTS_DIRNAME = "dns-hosts"
  HOSTS_FILENAME = "uvn.hosts"
  HOSTS_TEMPLATE_STR = """\
{% for a in addresses %}{{a.address}} {{a.hostname}}
{% endfor %}

"""
  HOSTS_TEMPLATE = Templates.compile(HOSTS_TEMPLATE_STR)

  DNSMASQ_CONF_FILENAME = "dnsmasq.conf"
  DNSMASQ_TEMPLATE_STR = """\
domain-needed
bogus-priv
no-resolv
filterwin2k
hostsdir={{hosts_dir}}

"""
  DNSMASQ_TEMPLATE = Templates.compile(DNSMASQ_TEMPLATE_STR)
  DNSMASQ_INSTALL_LOCATION = Path("/etc/dnsmasq.conf")

  RESOLV_CONF_TEMPLATE_STR = """\
search {{domain}}
nameserver 127.0.0.1
"""
  RESOLV_CONF_TEMPLATE = Templates.compile(RESOLV_CONF_TEMPLATE_STR)


  def __init__(self,
      root: Path,
      db: Optional[Mapping[str, NameserverRecord]]=None) -> None:
    self.root = root.resolve()
    self.db = db or {}
    self._db_orig = dict(db)
    self._dnsmasq_enabled = False
    self._systemdresolved_disabled = False
    self._monitor = None


  @property
  def dirty(self) -> bool:
    return {
      set(self.db.keys()) != set(self._db_orig.keys())
      or set(self.db.values()) != set(self._db_orig.values())
    }


  def _generate_config(self) -> None:
    hosts_file = self.root / self.HOSTS_DIRNAME / self.HOSTS_FILENAME
    hosts_file.parent.mkdir(parents=True, exist_ok=True)
    db = list(self.db.values())
    hosts_file.write_text(
      Templates.render(self.HOSTS_TEMPLATE, {
        "addresses": db
      }))

    dnsmasq_conf_file = self.root / self.DNSMASQ_CONF_FILENAME
    dnsmasq_conf_file.parent.mkdir(parents=True, exist_ok=True)
    dnsmasq_conf_file.write_text(
      Templates.render(self.DNSMASQ_TEMPLATE, {
        "hosts_dir": hosts_file.parent,
      }))
    exec_command(["cp", dnsmasq_conf_file, self.DNSMASQ_INSTALL_LOCATION])
    log.activity(f"[DNS] GENERATED dnsmasq config [{len(db)} records]")


  def serialize(self, orig: bool=False) -> dict:
    db = self.db if not orig else self._db_orig
    serialized = {
      "db": [r.serialize() for r in db.values()],
    }
    if not serialized["db"]:
      del serialized["db"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict, root: Path) -> "Nameserver":
    return Nameserver(
      root=root,
      db={
        record.hostname: record
          for val in serialized.get("db", [])
            for record in [NameserverRecord.deserialize(val)]
      })


  def start(self, resolve_domain: str) -> None:
    if self._dnsmasq_enabled:
      # already started
      return
    if self._monitor is not None:
      self._monitor.stop()
    log.debug(f"[DNS] starting nameserver...")
    self._monitor = NameserverMonitorThread(self)
    self._monitor.start()
    dnsmasq_stop()
    self._generate_config()
    if not self._systemdresolved_disabled:
      self._systemdresolved_disabled = systemd_resolved_disable()
    dnsmasq_start()
    # resolv_conf = Templates.render(self.RESOLV_CONF_TEMPLATE, {
    #   "domain": resolve_domain,
    # })
    # resolv_conf_install(resolv_conf)
    self._dnsmasq_enabled = True
    log.activity("[DNS] nameserver STARTED")


  def stop(self) -> None:
    if self._systemdresolved_disabled:
      systemd_resolved_enable()
      self._systemdresolved_disabled = False
    if self._monitor is not None:
      log.debug("[DNS] stopping dnsmasq monitor...")
      self._monitor.stop()
      self._monitor = None
      log.debug("[DNS] dnsmasq monitor STOPPED")
    dnsmasq_stop()
    # resolv_conf_restore()
    if self._dnsmasq_enabled:
      self._dnsmasq_enabled = False
    log.activity("[DNS] nameserver STOPPED")


  def reload(self) -> None:
    if self._monitor is None:
      raise RuntimeError("nameserver not started")
    self._monitor.trigger()
    log.debug("[DNS] SCHEDULED reload")


  def _reload(self) -> None:
    if not self._dnsmasq_enabled:
      raise RuntimeError("nameserver not started")
    self._generate_config()
    dnsmasq_reload()
    log.activity("[DNS] RELOAD completed")


  def clear(self, restore_initial: bool=False) -> None:
    if restore_initial:
      self.db = {}
    else:
      self.db = dict(self._db_orig)


  def assert_records(self, records: Iterable[NameserverRecord]) -> Sequence[NameserverRecord]:
    records = list(records)
    log.debug(f"[DNS] asserting {len(records)} records...")
    asserted = []
    for record in records:
      if self.assert_record(record):
        asserted.append(record)
    if asserted and self._dnsmasq_enabled:
      log.debug(f"[DNS] reloading service for {len(asserted)} updated records.")
      self.reload()
    log.debug(f"[DNS] {len(asserted)} records updated")
    return asserted


  def assert_record(self, record: NameserverRecord) -> bool:
    existing_record = self.db.get(record.hostname)
    changed = existing_record is not None and existing_record != record
    if existing_record is not None and not changed:
      # record unchanged, nothing to do
      return False
    self.db[record.hostname] = record
    return True


  def purge_server(self, server: str) -> Iterable[NameserverRecord]:
    server_records = {
      r for r in self.db.values() if r.server == server
    }
    for r in server_records:
      del self.db[r.hostname]
    if server_records and self._dnsmasq_enabled:
      self.reload()
    return server_records


  def remove_record(self, hostname: str) -> Optional[NameserverRecord]:
    record = self.db.get(hostname)
    if record is not None:
      del self.db[hostname]
      if self._dnsmasq_enabled:
        self.reload()
    return record


  def resolve(self, hostname: str) -> Optional[ipaddress.IPv4Address]:
    record = self.db.get(hostname)
    if record is None:
      return None
    return record.address


  def nslookup(self, address: Union[str, int, ipaddress.IPv4Address]) -> str:
    address = ipaddress.ip_address(address)
    record = next(r for r in self.db.values() if r.address == address)
    return record.hostname
