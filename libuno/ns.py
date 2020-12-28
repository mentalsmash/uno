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
import ipaddress
import threading
import shutil

import libuno.log
from libuno import ip
from libuno import data as StaticData
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.tmplt import TemplateRepresentation, render
from libuno.identity import UvnIdentityDatabase
from libuno.cfg import UvnDefaults
from libuno.exec import exec_command
from libuno.helpers import ListenerDescriptor, MonitorThread

logger = libuno.log.logger("uvn.ns")


def dnsmasq_stop():
    exec_command(["service", "dnsmasq", "stop"],
        root=True,
        fail_msg="failed to stop dnsmasq")

def dnsmasq_start():
    exec_command(["service", "dnsmasq", "start"],
        root=True,
        fail_msg="failed to start dnsmasq")

def dnsmasq_reload():
    exec_command(["service", "dnsmasq", "force-reload"],
        root=True,
        fail_msg="failed to reload dnsmasq")

def systemd_resolved_running():
    res = exec_command(["killall", "-0", "systemd-resolved"],
        root=True,
        noexcept=True,
        quiet=True,
        fail_msg="failed to check systemd-resolved status")
    return res.returncode == 0

def systemd_resolved_disable():
    if systemd_resolved_running():
        exec_command(["systemctl", "disable", "--now", "systemd-resolved"],
            root=True,
            fail_msg="failed to disable systemd-resolved")
        return True
    return False

def systemd_resolved_enable():
    exec_command(["systemctl", "enable", "--now", "systemd-resolved"],
        root=True,
        fail_msg="failed to re-enable systemd-resolved")


class DnsmasqMonitor(MonitorThread):
    def __init__(self, ns):
        self._ns = ns
        MonitorThread.__init__(self, "dnsmasq-monitor")

    def _do_monitor(self):
        try:
            dnsmasq_reload()
        except Exception as e:
            logger.exception(e)
            logger.error("failed to reload dnsmasq")


class UvnNameserverListener:
    def on_nameserver_record_updated(self, server, record, created=False):
        pass

    def on_nameserver_record_removed(self, server, record):
        pass
    
    def on_nameserver_cell_purged(self, server, cell_name, records):
        pass

@TemplateRepresentation("dnsmasq-db","dns/nameserver_db.conf")
@TemplateRepresentation("dnsmasq-hosts","dns/nameserver_hosts.conf")
@TemplateRepresentation("dnsmasq-conf","dns/nameserver.conf")
@TemplateRepresentation("resolv-conf","dns/resolv.conf")
class UvnNameserver:
    listener = ListenerDescriptor(UvnNameserverListener)

    @staticmethod
    def load(identity_db):
        args = UvnIdentityDatabase.get_load_args(identity_db=identity_db)
        db_file = args["basedir"] / UvnDefaults["nameserver"]["persist_file"]
        return yml_obj(UvnNameserver,
                    db_file,
                    from_file=True,
                    identity_db=identity_db,
                    **args)

    def __init__(self, identity_db, db=None, noupstream=False):
        self.identity_db = identity_db
        if db is None:
            self.db = {}
        else:
            self.db = db
            for record in self.db.values():
                logger.debug("[loaded] dns record [{}]: {} {} {}",
                    record.server,
                    record.address,
                    record.hostname,
                    record.tags)
        self._db_init = db
        self.dirty = False
        self.loaded = db is not None
        self.dnsmasq_enabled = False
        self.dnsmaq_monitor = DnsmasqMonitor(self)
        self.except_interfaces = []
        self.upstream_servers = []
        self.noupstream = noupstream
        self.localhost_only = False
        self._basedir = None
        self._systemdresolved_disabled = False

    def _generate_dnsmasq_config(self,
            db_only=False,
            upstream_servers=UvnDefaults["nameserver"]["upstream_servers"],
            localhost_only=False,
            except_interfaces=[],
            noupstream=False):
        db_dir = self._basedir / UvnDefaults["nameserver"]["db_dir"]
        hosts_dir = self._basedir / UvnDefaults["nameserver"]["hosts_dir"]
        hosts_file = hosts_dir / UvnDefaults["nameserver"]["hosts_file"]
        db_file = db_dir / UvnDefaults["nameserver"]["db_file"]
        conf_file = UvnDefaults["nameserver"]["conf_file"]

        logger.trace("[dnsmasq][generating] configuration: conf_file={}, hosts_file={}",
                conf_file, hosts_file)
        db_dir.mkdir(parents=True, exist_ok=True)
        # render(self, "dnsmasq-db", to_file=db_file)
        render(self, "dnsmasq-hosts", to_file=hosts_file, export_all=True)
        if not db_only:
            render(self, "dnsmasq-conf", to_file=conf_file, context={
                "except_interfaces": except_interfaces,
                "upstream_servers": upstream_servers if not noupstream else [],
                "hosts_dir": hosts_dir,
                "hosts_file": hosts_file,
                "db_dir": db_dir,
                "db_file": db_file,
                "local_only": localhost_only,
                "noupstream": noupstream
            })
            resolv_conf = pathlib.Path("/etc/resolv.conf")
            resolv_conf_bkp = pathlib.Path("/etc/resolv.conf.uno.bkp")
            if not resolv_conf_bkp.exists():
                shutil.copy2(str(resolv_conf), str(resolv_conf_bkp))
            else:
                logger.warning("not overwritten: {}", resolv_conf_bkp)
            render(self, "resolv-conf", to_file=resolv_conf, context={
                "noupstream": noupstream
            })
        self.except_interfaces = list(except_interfaces)
        self.upstream_servers = list(upstream_servers)
        self.noupstream = noupstream
        self.localhost_only = localhost_only

    def started(self):
        return self.dnsmasq_enabled

    def start(self, basedir, *args, **kwargs):
        if self.dnsmasq_enabled:
            logger.warning("dnsmasq already enabled")
            return
        dnsmasq_stop()
        self._basedir = pathlib.Path(basedir)
        kwargs["noupstream"] = self.noupstream
        self._generate_dnsmasq_config(*args, **kwargs)
        self._systemdresolved_disabled = systemd_resolved_disable()
        dnsmasq_start()
        self.dnsmaq_monitor.start()
        self.dnsmasq_enabled = True
        logger.trace("[dnsmasq] enabled")

    def stop(self):
        self.dnsmaq_monitor.stop()
        dnsmasq_stop()
        self.dnsmasq_enabled = False
        self.except_interfaces = []
        self.upstream_servers = []
        self.noupstream = False
        self.localhost_only = False
        resolv_conf = pathlib.Path("/etc/resolv.conf")
        resolv_conf_bkp = pathlib.Path("/etc/resolv.conf.uno.bkp")
        if resolv_conf_bkp.exists():
            shutil.copy2(str(resolv_conf_bkp), str(resolv_conf))
        else:
            logger.warning("not restored: {}", resolv_conf)
        if self._systemdresolved_disabled:
            systemd_resolved_enable()
        logger.trace("[dnsmasq] disabled")
    
    def reload(self):
        if self.dnsmasq_enabled:
            logger.trace("[dnsmasq] reloading")
            self._generate_dnsmasq_config(db_only=True,
                    upstream_servers=self.upstream_servers,
                    noupstream=self.noupstream,
                    except_interfaces=self.except_interfaces,
                    localhost_only=self.localhost_only)
            db_dir = pathlib.Path(UvnDefaults["nameserver"]["db_dir"])
            db_file = db_dir / UvnDefaults["nameserver"]["db_file"]
            render(self, "dnsmasq-db", to_file=db_file)
            # dnsmasq_reload()
            self.dnsmaq_monitor.trigger()

    def export(self, force=False):
        def exportable(obj):
            return not obj.loaded or obj.dirty or force
        if exportable(self):
            outfile = self.identity_db.registry_id.basedir / UvnDefaults["nameserver"]["persist_file"]
            logger.debug("exporting nameserver to {}", outfile)
            db_args = self.identity_db.get_export_args()
            yml(self, to_file=outfile, **db_args)
            self.dirty = False
            self.loaded = True

    def assert_record(self, hostname, server, address, tags):
        address = ipaddress.ip_address(address)
        logger.trace("asserting record: {}/{}/{} {}", hostname, server, address, tags)
        record = self.db.get(hostname)
        updated = False
        if record is not None:
            changed=[]
            if record.address != address:
                record.address = address
                updated = True
                changed.append("address")
            current_tags = record.tags
            record.tags = set(list(tags))
            changed_tags = record.tags ^ current_tags
            if len(changed_tags) > 0:
                # updated = True
                changed.append("tags")
            updated = len(changed) > 0
            if updated:
                logger.activity("[updated]{} dns record [{}]: {} {} {}",
                    changed,
                    record.server,
                    record.address,
                    record.hostname,
                    record.tags)
                self.listener.on_nameserver_record_updated(self, record)
            else:
                logger.debug("[not updated] dns record [{}]: {} {} {}",
                    record.server,
                    record.address,
                    record.hostname,
                    record.tags)
        else:
            record = UvnNameserver.Record(hostname, server, address, tags)
            self.db[hostname] = record
            logger.activity("[asserted] dns record [{}]: {} {}",
                    record.server,
                    record.address,
                    record.hostname)
            self.listener.on_nameserver_record_updated(self, record, created=True)
            updated = True
        if updated:
            self.dirty = True
            self.reload()
        
        return record, updated
    
    def remove_record(self, hostname):
        record = self.db.get(hostname)
        if record is not None:
            logger.activity("[deleted] dns record [{}]: {} {}",
                    record.server,
                    record.address,
                    record.hostname)
            del self.db[hostname]
            self.listener.on_nameserver_record_removed(self, record)
    
    def resolve(self, hostname):
        record = self.db.get(hostname)
        if record is not None:
            return record.address
        return None
    
    def purge_cell(self, cell_name):
        cell_records = list(filter(lambda r: r[1].server == cell_name, self.db.items()))
        for r_key, r in cell_records:
            self.remove_record(r.hostname)
        logger.activity("[purged][{}] {} records", cell_name, len(cell_records))
        self.listener.on_nameserver_cell_purged(self, cell_name, cell_records)
    
    def lookup_subnet_records(self, subnet, mask):
        subnet = ipaddress.ip_network(subnet).supernet(new_prefix=mask)
        return filter(lambda e: e.address in subnet, self.db.values())
    
    def lookup_cell_records(self, cell_name):
        return filter(lambda e: e.server == cell_name, self.db.values())
    
    def nslookup(self, address):
        address = ipaddress.ip_address(address)
        record = next(filter(lambda r: r.address == address, self.db.values()))
        logger.activity("[nslookup] {}: {}", address, record.hostname)
        return record.hostname
    
    def clear(self):
        self.db = self._db_init
        self.reload()
    
    def exported(self):
        return filter(lambda i: "uvn" not in i[1].tags, self.db.items())

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            export_all = kwargs.get("export_all", False)
            if export_all:
                exported = py_repr.db.items()
            else:
                exported = py_repr.exported()
            return {
                "db": {k: repr_yml(v, **kwargs) for k, v in exported}
            }
    
        def repr_py(self, yml_repr, **kwargs):
            return UvnNameserver(
                        identity_db=kwargs["identity_db"],
                        db={k: repr_py(UvnNameserver.Record, v, **kwargs)
                                for k, v in yml_repr["db"].items()})
        
        def _file_format_out(self, yml_str, **kwargs):
            return UvnIdentityDatabase.sign_data(
                    "nameserver database", yml_str, **kwargs)

        def _file_format_in(self, yml_str, **kwargs):
            return UvnIdentityDatabase.verify_data(
                    "nameserver databse", yml_str, **kwargs)
    
    class Record:
        def __init__(self, hostname, server, address, tags=None):
            self.hostname = hostname
            self.server = server
            self.address = ipaddress.ip_address(address)
            if tags is None:
                tags = []
            self.tags = set(tags)

        class _YamlSerializer(YamlSerializer):
            def repr_yml(self, py_repr, **kwargs):
                return {
                    "hostname": py_repr.hostname,
                    "server": py_repr.server,
                    "address": str(py_repr.address),
                    "tags": list(py_repr.tags)
                }
        
            def repr_py(self, yml_repr, **kwargs):
                return UvnNameserver.Record(
                            hostname=yml_repr["hostname"],
                            server=yml_repr["server"],
                            address=yml_repr["address"],
                            tags=yml_repr["tags"])
