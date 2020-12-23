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
import datetime
import pathlib
import ipaddress
import types

# A class to store default configuration parameters
class UvnConfig(types.SimpleNamespace):
    @staticmethod
    def _to_sns_args(config):
        if not isinstance(config, dict):
            raise TypeError(config)
        def _process(v):
            if isinstance(v, dict):
                sub_args = UvnConfig._to_sns_args(v)
                return types.SimpleNamespace(**sub_args)
            else:
                return v
        return {k: _process(v) for k, v in config.items()}

    def __init__(self, config):
        types.SimpleNamespace.__init__(self, **UvnConfig._to_sns_args(config))

UvnDefaults = {
    "registry": {
        "ports": [
            63550
        ],
        "admin": "admin",
        "admin_name": "John Doe",
        "uno_dir": ".uvn",
        "persist_file": "registry.yml",
        "deployment_bootstrap": "bootstrap",
        "deployment_default": "latest",
        "deployment_file": "deployment.yml",
        "deployment_report": "deployment.md",
        "deployment_graph": "deployment_backbone.png",
        "deployment_file_fmt": "{}.yml",
        "bootstrap_dir": "bootstrap",
        "deployment_dir": "deployments",
        "particles_dir": "particles",
        "deployment_dir_fmt": "deployment-{}",
        "deployment_packages": "package",
        "cell_cfg_fmt": "backbone.{}.yml",
        "cell_id_fmt": "id.{}.yml",
        "cells_dir": "cells",
        "cell_file": "cell.yml",
        "installers_dir": "installers",
        "vpn": {
            "registry": {
                "base_ip": "10.255.128.0",
                "netmask": 22,
                "interface": "uwg-v{}"
            },
            "backbone": {
                "base_ip": "172.16.0.0",
                "netmask": 22,
                "interface": "uwg-b{}"
            },
            "backbone2": {
                "base_ip": "10.255.192.0",
                "netmask": 31,
                "interface": "uwg-b{}"
            },
            "router": {
                "ports": {
                    "range": (33000, 35000),
                    "reserved": []
                },
                "base_ip": "10.255.0.0",
                "netmask": 31,
                "interface": "uwg-r{}",
                "allowed_ips": [
                    "224.0.0.5/32",
                    "224.0.0.6/32"
                ]
            },
            "particles": {
                "base_ip": "10.254.0.0",
                "netmask": 16,
                "interface": "uwg-p{}",
                "port": 63449,
                "particle_cfg_fmt": "{}-{}-{}.conf",
                "particle_qr_fmt": "{}-{}-{}.png"
            }
        },
        "config": {
            "dir": "registry",
            "vpn": "vpn.conf"
        },
        "agent": {
            "basedir": "/var/run/uvn",
            "log_file": "uvnd.log",
            "pid": "uvnd.pid",
            "assert": {
                "cell": (60, 120),
                "registry": (20, 60),
            },
            "stat": {
                "period_min": 10,
                "period_max": 30,
                "file": "proc",
            },
            "id": {
                "cell": "{}.{}@{}",
                "registry": "registry.{}@{}",
                "cell_brief": "{}@{}",
                "registry_brief": "registry@{}"
            }
        }
    },
    "identity_db" : {
        "secret_len": 32,
        "path" : "keys",
        "key_length": 4096,
        "key_algo": "RSA",
        "key_encoding": "utf-8",
        "key_server": "keys.gnupg.net",
        "persist_file": "identity.yml",
        "secret_file": ".uvn-auth",
        "key_file": ".uvn-key",
        "secret_env": "AUTH",
        "cell_secret_file_fmt": ".uvn-auth-{}",
        "cell_secret_env_fmt": "AUTH_{}",
        "cell_key_file_fmt": ".uvn-key-{}",
        "ext_signature": ".asc",
        "ext_encrypted": ".pgp",
        "ext_pubkey": ".pub.asc",
        "ext_privkey": ".key.asc"
    },
    "cell": {
        "activity_timeout": datetime.timedelta(minutes=15),
        "peer_ports": [
            63450,
            63451,
            63452
        ],
        "pkg": {
            "ext": ".uvnpkg",
            "ext_clear": ".zip",
            "clear_format": "zip",
            "export_name": "uvn-cell",
            "bootstrap_dir": "uvn-cell",
            "root_key_file": "uvn-root",
            "key_file": "uvn-cell",
            "secret_file": ".uvn-auth",
            "installer": {
                "manifest": "uvn.yml",
                "filename_fmt": "uvn-{}-{}-{}"
            }
        },
        "location": "unknown",
        "config": {
            "vpn": "registry_vpn.conf",
            "backbone": "backbone_vpn_{}.conf"
        }
    },
    "particle": {
        "manifest": "particle.md"
    },
    "port": {
        "udp_port_min": 1025,
        "udp_port_max": 65535
    },
    "docker": {
        "volumes": {
            "uvn": "/opt/uvn"
        },
        "env" : {
            "oauth_token": "OAUTH_TOKEN"
        },
        "arg" : {
            "oauth_token": "OAUTH_TOKEN",
            "basedir": "BASEDIR"
        },
        "socket": "unix://var/run/docker.sock",
        "image_name_fmt":{
            "root": "uvn-{}",
            "cell": "uvn-{}-{}"
        },
        "base_image": "uvn-runner",
        "context": {
            "tar": "uvn-runner-context.tar",
            "repo_dir": "uno",
            "repo_branch": "master",
            "repo_proto": "https",
            "repo_url_base": "github.com/mentalsmash/uno.git",
            "repo_url_fmt": "{}://{}:x-oauth-basic@{}",
            "uvn_dir": "uvn",
            "connextdds_wheel_fmt": "rti-0.0.1-cp{}-cp{}{}-linux_{}.whl"
        }
    },
    "ping": {
        "period_ok": 300,
        "period_wait": (60, 100),
        "count": 1,
        "max_failed": 10
    },
    "dds": {
        "home": "ndds",
        "domain_id": 46,
        "process_events": True,
        "profile_file": "uno.xml",
        "dir": "dds",
        "participant": {
            "root_agent": "UnoParticipants::RootAgent",
            "cell_agent": "UnoParticipants::CellAgent"
        },
        "types": {
            "uvn_info":     "uno::UvnInfo",
            "cell_info":    "uno::CellInfo",
            "dns_db":       "uno::NameserverDatabase",
            "dns_rec":      "uno::DnsRecord",
            "deployment":   "uno::UvnDeployment",
            "cell_site":    "uno::CellSiteSummary",
            "cell_peer":    "uno::CellPeerSummary",
            "ip_address":   "uno::IpAddress"
        },
        "reader": {
            "uvn_info":     "Subscriber::UvnInfoReader",
            "cell_info":    "Subscriber::CellInfoReader",
            "dns":          "Subscriber::NameserverReader",
            "deployment":   "MetadataSubscriber::UvnDeploymentReader"
        },
        "writer": {
            "uvn_info":     "Publisher::UvnInfoWriter",
            "cell_info":    "Publisher::CellInfoWriter",
            "dns":          "Publisher::NameserverWriter",
            "deployment":   "MetadataPublisher::UvnDeploymentWriter"
        },
        "rs": {
            "verbosity": 5,
            "config_file": "rtiroutingservice.xml",
            "log_file": "rtiroutingservice.log",
            "config": {
                "peer": "cell",
                "root": "root"
            },
            "orig_info": True
        },
        "connext": {
            "arch": {
                "x86_64": "x64Linux4gcc7.3.0",
                "armv7": "armv7Linuxgcc7.3.0",
                "armv7l": "armv7Linuxgcc7.3.0"
            },
            "bin_arch": {
                "x64Linux4gcc7.3.0": "x64Linux2.6gcc4.4.5",
            },
            "py": {
                "git": "https://github.com/rticommunity/connextdds-py.git"
            }
        }
    },
    "nameserver": {
        "persist_file": "nameserver.yml",
        "db_file": "uvn-db.conf",
        "hosts_file": "uvn-hosts",
        "run_dir": "dnsmasq",
        "hosts_dir": "hosts",
        "db_dir": "db",
        "conf_file": "/etc/dnsmasq.conf",
        "upstream_servers": [
            ipaddress.ip_address("1.1.1.1"),
            ipaddress.ip_address("1.0.0.1")
        ],
        "vpn": {
            "registry_host_fmt": "registry.{}",
            "cell_host_fmt": "{}.vpn.{}"
        },
        "backbone": {
            "enable": True,
            "cell_host_fmt": "{}.{}.backbone.{}",
            "peer_host_fmt": "{}.{}.backbone.{}",
            "multipeer_host_fmt": "p{}.b{}.{}.backbone.{}"
        },
        "router": {
            "cell_host_fmt": "local.{}.router.{}",
            "registry_host_fmt": "{}.router.{}"
        }
    },
    "router": {
        "use_quagga": True,
        "user": "quagga",
        "group": "quagga",
        "vty": {
            "dir": "/run/quagga",
            "conf": "/etc/quagga/vtysh.conf"
        },
        "timeout": {
            "alive": 180,
            "hello": 45,
            "resend": 15
        },
        "start_wait": 2,
        "run_dir": "quagga",
        "ospfd": {
            "pid": "ospfd.pid",
            "conf": "ospfd.conf",
            "log": "ospfd.log",
            "log_level": "debugging",
            "area": "0.0.0.1",
            "root_router_id": "0.0.0.1",
            "md5key": "foobar"
        },
        "zebra": {
            "pid": "zebra.pid",
            "conf": "zebra.conf",
            "socket": "zebra.sock",
            "log": "zebra.log",
            # One of: emergencies, alerts, critical, errors, warnings,
            # notifications, informational, debugging
            "log_level": "debugging",
        },
        "monitor": {
            "poll_period": 30
        }
    }
}

class UvnPaths:

    def __init__(self, basedir=None):
        if (basedir is None):
            basedir = UvnDefaults["registry"]["uno_dir"]
        
        self.basedir = pathlib.Path(basedir).resolve()

    def dir_deployment(
            self,
            deployment_id,
            deployment_dir=UvnDefaults["registry"]["deployment_dir"],
            deployment_dir_fmt=UvnDefaults["registry"]["deployment_dir_fmt"],
            basedir=None):
        if basedir is None:
            basedir = self.basedir
        return pathlib.Path(basedir) / deployment_dir / deployment_id

    def dir_cell_pkg(
            self,
            cell_name,
            deployment_id=UvnDefaults["registry"]["deployment_default"]):
        return self.dir_deployment(deployment_id) / cell_name
    
    def dir_cell_bootstrap(self, cell_name=None):
        basedir = self.basedir / UvnDefaults["registry"]["bootstrap_dir"]
        if cell_name:
            return basedir / cell_name
        return basedir
    
    def dir_particles(self, particle_name=None):
        basedir = self.basedir / UvnDefaults["registry"]["particles_dir"]
        if particle_name:
            return basedir / particle_name
        return basedir
    
    def dir_config(self, basedir=None):
        if basedir is None:
            basedir = self.basedir
        return pathlib.Path(basedir) / UvnDefaults["registry"]["config"]["dir"]
    

class WireGuardConfig:
    _ip_addr_cell_to_registry_base = ipaddress.ip_address(
                UvnDefaults["registry"]["vpn"]["registry"]["base_ip"])
    
    _ip_net_cell_to_registry = ipaddress.ip_network(
        "{}/{}".format(
            UvnDefaults["registry"]["vpn"]["registry"]["base_ip"],
            UvnDefaults["registry"]["vpn"]["registry"]["netmask"]))
    
    _ip_addr_cell_to_cell_base = ipaddress.ip_address(
                UvnDefaults["registry"]["vpn"]["backbone"]["base_ip"])

    @staticmethod
    def _ip_addr_cell_to_registry(n):
        registry_ip = WireGuardConfig._ip_addr_registry()
        cell_ip = registry_ip + n
        return cell_ip

    @staticmethod
    def _ip_addr_registry():
        registry_ip = WireGuardConfig._ip_addr_cell_to_registry_base + 1
        return registry_ip
    
    @staticmethod
    def _ip_net_cell_to_cell_addr(n):
        netmask_size = UvnDefaults["registry"]["vpn"]["backbone"]["netmask"]
        hostmask_size = 32 - netmask_size
        net_prefix = (n + 1) << hostmask_size
        net_ip = WireGuardConfig._ip_addr_cell_to_cell_base + net_prefix
        return (net_ip, netmask_size, hostmask_size)
    
    @staticmethod
    def _ip_net_cell_to_cell(n):
        net_ip, netmask_size, hostmask_size = WireGuardConfig._ip_net_cell_to_cell_addr(n)
        net_str = "{}/{}".format(net_ip, netmask_size)
        net = ipaddress.ip_network(net_str)
        return net
    
    @staticmethod
    def _ip_addr_cell_to_cell(cell_n, net_n=None):
        if (net_n is None):
            net_n = cell_n
        net_ip, netmask_size, hostmask_size = WireGuardConfig._ip_net_cell_to_cell_addr(net_n)
        cell_ip = net_ip + cell_n
        return cell_ip