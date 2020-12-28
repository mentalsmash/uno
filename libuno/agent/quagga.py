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
import pathlib
import itertools
import ipaddress
from sh import touch, chown
import threading
import time

from libuno.tmplt import TemplateRepresentation, render
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.cfg import UvnDefaults, WireGuardConfig
from libuno.exec import exec_command
import libuno.ip as ip


import libuno.log
logger = libuno.log.logger("uvn.quagga")

class QuaggaThread(threading.Thread):
    def __init__(self, daemon, config, pid, socket, user, group):
        threading.Thread.__init__(self)
        self._daemon = daemon
        self._config = config
        self._pid = pid
        self._socket = socket
        self._user = user
        self._group = group
        self._sem_started = threading.BoundedSemaphore()
        self._sem_started.acquire()
    
    def start(self):
        threading.Thread.start(self)
        self._sem_started.acquire()
    
    def pid(self):
        with self._pid.open("r") as input:
            return input.read().rstrip()
    
    def kill(self):
        exec_command(["kill", self.pid()],
            fail_msg="failed to signal ospfd for exit")

    def run(self):
        logger.activity("[{}] starting up...", self._daemon)
        try:
            self._sem_started.release()
            exec_command(["killall", "-9", self._daemon],
                fail_msg=f"failed to kill {self._daemon}",
                quiet=True,
                noexcept=True)
            exec_command([self._daemon,
                    "-f", self._config,
                    "-i", self._pid,
                    "-z", self._socket],
                    fail_msg=f"failed to run {self._daemon}")
        except Exception as e:
            logger.exception(e)
            logger.error("error in {} thread", self._daemon)
            raise e
        finally:
            logger.activity("[{}] stopped", self._daemon)

class QuaggaHelper:
    def __init__(self, basedir):
        self._basedir = pathlib.Path(basedir)
        self._started = False
        self._zebra = None
        self._ospfd = None

    def start(self, cfg, *args, **kwargs):
        return self._quagga_start(cfg)
    
    def stop(self, *args, **kwargs):
        return self._quagga_stop()

    def _quagga_stop(self):
        try:
            # Lookup daemon PIDs from files, and kill them if found
            if self._ospfd and self._ospfd.is_alive():
                self._ospfd.kill()
                self._ospfd.join()
            else:
                logger.debug("ospfd not running (no pid)")
            self._ospfd = None

            if self._zebra and self._zebra.is_alive():
                self._zebra.kill()
                self._zebra.join()
            else:
                logger.debug("zebra not running (no pid)")
            self._zebra = None

        except Exception as e:
            logger.exception(e)
            logger.error("failed to stop quagga daemons")
            raise e

    def _quagga_start(self, cfg):
        # Make sure services are stopped
        self._quagga_stop()

        try:
            pid_zebra = self._basedir / UvnDefaults["router"]["zebra"]["pid"]
            pid_ospfd = self._basedir / UvnDefaults["router"]["ospfd"]["pid"]
            conf_zebra = self._basedir / UvnDefaults["router"]["zebra"]["conf"]
            conf_ospfd = self._basedir / UvnDefaults["router"]["ospfd"]["conf"]

            # Generate configuration files
            render(cfg, "ospfd.conf", to_file=conf_ospfd, context={
                "basedir": self._basedir
            })
            render(cfg, "zebra.conf", to_file=conf_zebra, context={
                "basedir": self._basedir
            })

            # Create log directories
            ospfd_log = self._basedir / UvnDefaults["router"]["ospfd"]["log"]
            ospfd_log.parent.mkdir(exist_ok=True, parents=True)
            zebra_log = self._basedir / UvnDefaults["router"]["zebra"]["log"]
            zebra_log.parent.mkdir(exist_ok=True, parents=True)
            # Create directory for socket file
            zebra_socket = self._basedir / UvnDefaults["router"]["zebra"]["socket"]
            zebra_socket.parent.mkdir(exist_ok=True, parents=True)

            # Create directory for vty sockets
            vty_dir = pathlib.Path(UvnDefaults["router"]["vty"]["dir"])
            vty_dir.mkdir(exist_ok=True, parents=True)

            # Create config file for vtysh
            vtysh_conf = pathlib.Path(UvnDefaults["router"]["vty"]["conf"])
            render(cfg, "vtysh.conf", to_file=vtysh_conf)

            q_user = UvnDefaults["router"]["user"]
            q_group = UvnDefaults["router"]["group"]

            # Change permissions of file and directories accessed by daemons
            chown(f"{q_user}:{q_group}", zebra_socket.parent, vty_dir)
            for f in [ospfd_log,
                      zebra_log,
                      pid_ospfd,
                      pid_zebra]:
                touch(str(f))
                chown(f"{q_user}:{q_group}", str(f))

            self._zebra = QuaggaThread("zebra",
                            conf_zebra, pid_zebra, zebra_socket, q_user, q_group)
            self._ospfd = QuaggaThread("ospfd",
                            conf_ospfd, pid_ospfd, zebra_socket, q_user, q_group)
            self._zebra.start()
            # Wait a few seconds for zebra to start and create its socket
            time.sleep(UvnDefaults["router"]["start_wait"])
            self._ospfd.start()
            time.sleep(UvnDefaults["router"]["start_wait"])
            
            self._started = True
        except Exception as e:
            logger.exception(e)
            logger.error("failed to start quagga daemons")
            # Try to reset state to stopped
            self.stop()
            raise e
        
        return self._zebra, self._ospfd


@TemplateRepresentation("vtysh.conf", "router/vtysh.conf")
@TemplateRepresentation("ospfd.conf", "router/ospfd_root.conf")
@TemplateRepresentation("zebra.conf", "router/zebra_root.conf")
class QuaggaRootHelper():
    def __init__(self, basedir, registry, vpn):
        self.registry = registry
        self.vpn = vpn
        self._static_routes = []
        self._helper = QuaggaHelper(basedir)
    
    def start(self, *args, **kwargs):
        if "static_routes" in kwargs:
            self._static_routes = kwargs["static_routes"]
        return self._helper.start(self, *args, **kwargs)
    
    def stop(self, *args, **kwargs):
        return self._helper.stop(*args, **kwargs)
    
    def _hostname(self):
        return UvnDefaults["nameserver"]["vpn"]["registry_host_fmt"].format(
                    self.registry.address)
    

    def _repr_ctx_ospfd_conf(self):
        return {
            "md5key": UvnDefaults["router"]["ospfd"]["md5key"],
            "router_area": UvnDefaults["router"]["ospfd"]["area"],
            "router_id": str(self.vpn.wg_root.interface_address),
            "timeout": dict(UvnDefaults["router"]["timeout"]),
            "log": UvnDefaults["router"]["ospfd"]["log"],
            "log_level": UvnDefaults["router"]["ospfd"]["log_level"],
            "root": {
                "name": self.vpn.wg_root.interface,
                "address": self.vpn.wg_root.interface_address,
                "mask": self.vpn.wg_root.interface_address_mask
            },
            "router": [
                {
                    "name": wg.interface,
                    "address": wg.interface_address,
                    "mask": wg.interface_address_mask,
                    "area": self.registry.router_ports.interface_area(
                                wg.interface, root=True)
                } for wg in self.vpn.wg_router
            ]
        }
    
    def _repr_ctx_zebra_conf(self):
        return {
            "hostname": self._hostname(),
            "timeout": dict(UvnDefaults["router"]["timeout"]),
            "log": UvnDefaults["router"]["zebra"]["log"],
            "log_level": UvnDefaults["router"]["zebra"]["log_level"],
            "root": {
                "name": self.vpn.wg_root.interface,
                "address": self.vpn.wg_root.interface_address,
                "mask": self.vpn.wg_root.interface_address_mask
            },
            "router": [
                {
                    "name": wg.interface,
                    "address": wg.interface_address,
                    "mask": wg.interface_address_mask
                } for wg in self.vpn.wg_router
            ],
            "static_routes": repr_yml(self._static_routes)
        }
    
    def _repr_ctx_vtysh_conf(self):
        return {
            "hostname": self._hostname()
        }

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            repr = kwargs.get("repr")
            if repr == "ospfd.conf":
                return py_repr._repr_ctx_ospfd_conf()
            elif repr == "zebra.conf":
                return py_repr._repr_ctx_zebra_conf()
            elif repr == "vtysh.conf":
                return py_repr._repr_ctx_vtysh_conf()
            raise NotImplementedError()
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()

@TemplateRepresentation("vtysh.conf", "router/vtysh.conf")
@TemplateRepresentation("ospfd.conf", "router/ospfd_cell.conf")
@TemplateRepresentation("zebra.conf", "router/zebra_cell.conf")
class QuaggaCellHelper():
    def __init__(self, basedir, registry, vpn, cell, cell_cfg, roaming):
        self.registry = registry
        self.vpn = vpn
        self.cell = cell
        self.cell_cfg = cell_cfg
        self.roaming = roaming
        self._static_routes = []
        self._helper = QuaggaHelper(basedir)

    def start(self, *args, **kwargs):
        if "cell_cfg" in kwargs and self.cell_cfg != kwargs["cell_cfg"]:
            self.cell_cfg = kwargs["cell_cfg"]
        if "static_routes" in kwargs:
            self._static_routes = kwargs["static_routes"]
        return self._helper.start(self, *args, **kwargs)
    
    def stop(self, *args, **kwargs):
        return self._helper.stop(*args, **kwargs)

    def _hostname(self):
        return UvnDefaults["nameserver"]["vpn"]["cell_host_fmt"].format(
                            self.cell.id.name, self.registry.address)

    def _repr_ctx_ospfd_conf(self):
        parent = {
            "md5key": UvnDefaults["router"]["ospfd"]["md5key"],
            "router_area": UvnDefaults["router"]["ospfd"]["area"],
            "router_id": str(self.vpn.wg_root.interface_address),
            "timeout": dict(UvnDefaults["router"]["timeout"]),
            "log": UvnDefaults["router"]["ospfd"]["log"],
            "log_level": UvnDefaults["router"]["ospfd"]["log_level"],
            "root": {
                "name": self.vpn.wg_root.interface,
                "address": self.vpn.wg_root.interface_address,
                "mask": self.vpn.wg_root.interface_address_mask
            },
            "router": [
                {
                    "name": wg.interface,
                    "address": wg.interface_address,
                    "mask": wg.interface_address_mask,
                    "area": self.registry.router_ports.cell_area(self.cell.id.n)
                } for wg in self.vpn.wg_router
            ]
        }
        if not self.roaming:
            parent.update({
                "lans": [{
                    "name": net["nic"],
                    "address": str(net["address"]),
                    "mask": net["mask"],
                    "subnet": str(net["subnet"]),
                    "area": str(net["subnet"].network_address)
                } for net in self.vpn.list_local_networks()]
            })
        if self.cell_cfg:
            parent.update({
                "backbone": [{
                    "name": bbone.interface,
                    "address": str(bbone.addr_local),
                    "mask": UvnDefaults["registry"]["vpn"]["backbone2"]["netmask"],
                    "subnet": str("{}/{}".format(
                                bbone.network.network_address,
                                UvnDefaults["registry"]["vpn"]["backbone2"]["netmask"])),
                    "area": str(bbone.network.network_address),
                    "area_int": int(bbone.network.network_address),
                    "peers": repr_yml(bbone.peers)
                } for bbone_i, bbone in enumerate(self.cell_cfg.backbone)]
            })
        return parent
    
    def _repr_ctx_zebra_conf(self):
        parent = {
            "hostname": self._hostname(),
            "timeout": dict(UvnDefaults["router"]["timeout"]),
            "log": UvnDefaults["router"]["zebra"]["log"],
            "log_level": UvnDefaults["router"]["zebra"]["log_level"],
            "root": {
                "name": self.vpn.wg_root.interface,
                "address": self.vpn.wg_root.interface_address,
                "mask": self.vpn.wg_root.interface_address_mask
            },
            "router": [
                {
                    "name": wg.interface,
                    "address": wg.interface_address,
                    "mask": wg.interface_address_mask
                } for wg in self.vpn.wg_router
            ],
            "static_routes": repr_yml(self._static_routes)
        }
        parent.update({
            "lans": [{
                "name": net["nic"],
                "address": str(net["address"]),
                "mask": net["mask"]
            } for net in self.vpn.list_local_networks()]
        })
        if self.cell_cfg:
            parent.update({
                "backbone": [{
                    "name": bbone.interface,
                    "address": str(bbone.addr_local),
                    "mask": UvnDefaults["registry"]["vpn"]["backbone2"]["netmask"],
                    "subnet": str(bbone.network),
                    "area": str(bbone.network.network_address),
                    "area_int": int(bbone.network.network_address),
                    "peers": repr_yml(bbone.peers)
                } for bbone_i, bbone in enumerate(self.cell_cfg.backbone)]
            })
        return parent
    
    def _repr_ctx_vtysh_conf(self):
        return {
            "hostname": self._hostname()
        }
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            repr = kwargs.get("repr")
            if repr == "ospfd.conf":
                return py_repr._repr_ctx_ospfd_conf()
            elif repr == "zebra.conf":
                return py_repr._repr_ctx_zebra_conf()
            elif repr == "vtysh.conf":
                return py_repr._repr_ctx_vtysh_conf()
            raise NotImplementedError()
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()


class Vtysh:
    commands = {
        "ospf": {
            "info": {
                "neighbors": ["show ip ospf neighbor"],
                "routes": ["show ip ospf route"],
                "interfaces": ["show ip ospf interface"],
                "borders": ["show ip ospf border-routers"],
                "lsa": [
                    "show ip ospf database self-originate",
                    "show ip ospf database summary",
                    "show ip ospf database asbr-summary",
                    "show ip ospf database router"
                ],
                "summary": [
                    "show ip ospf database self-originate",
                    "show ip ospf border-routers",
                    "show ip ospf neighbor"
                ]
            }
        }
    }
    @staticmethod
    def exec(cmd_id):
        cmd_id_p = cmd_id.split(".")
        cmds = Vtysh.commands
        for p in cmd_id_p:
            cmds = cmds[p]

        cmd = ["vtysh", "-E"]
        for c in cmds:
            cmd.extend(["-c", str(c)])
        result = exec_command(cmd,
            fail_msg="failed to perform vtysh command",
            root=True)
        return result.stdout.decode("utf-8")

