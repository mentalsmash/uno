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
from typing import Sequence, Tuple, Mapping, Optional, Union
import netifaces
import ipaddress
import socket
from itertools import chain
from functools import partial

from .exec import exec_command


class NicDescriptor:
    def __init__(self,
        name: str,
        address: Optional[ipaddress.IPv4Address]=None,
        subnet: Optional[ipaddress.IPv4Network]=None,
        netmask: Optional[int]=None) -> None:
        self.name = name
        self.address = ipaddress.ip_address(address) if address else None
        self.subnet = ipaddress.ip_network(subnet) if subnet else None
        self.netmask = netmask


    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NicDescriptor):
            return False
        return (self.name == other.name
            and self.address == other.address
            and self.subnet == other.subnet
            and self.netmask == other.netmask)


    def __hash__(self) -> int:
        return hash(self.name)


    def __str__(self) -> str:
        return f"{self.address}/{self.netmask} ({self.name})"


    def serialize(self) -> dict:
        serialized = {
            "name": self.name,
            "address": None if not self.address else str(self.address),
            "subnet": None if not self.subnet else str(self.subnet),
            "netmask": self.netmask,
        }
        if serialized["netmask"] is None:
            del serialized["netmask"]
        if not serialized["address"]:
            del serialized["address"]
        if not serialized["subnet"]:
            del serialized["subnet"]
        return serialized


    @staticmethod
    def deserialize(serialized: dict) -> "NicDescriptor":
        return NicDescriptor(
            name=serialized["name"],
            address=serialized.get("address"),
            subnet=serialized.get("subnet"),
            netmask=serialized.get("netmask"))


class LanDescriptor:
    def __init__(self,
            nic: NicDescriptor,
            gw: Union[str, int],
            next_hop: Optional[Union[str, int, ipaddress.IPv4Address]]=None) -> None:
        self.nic = nic
        self.gw = ipaddress.ip_address(gw)
        self.next_hop = ipaddress.ip_address(next_hop) if next_hop else None


    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LanDescriptor):
            return False
        return self.nic == other.nic and self.gw == other.gw


    def __hash__(self) -> int:
        return hash((self.nic, self.gw))


    def __str__(self) -> str:
        return str(self.nic.subnet)


    def serialize(self) -> dict:
        serialized = {
            "nic": self.nic.serialize(),
            "gw": str(self.gw),
            **({"next_hop": str(self.next_hop)} if self.next_hop else {}),
        }
        return serialized


    @staticmethod
    def deserialize(serialized: dict) -> "LanDescriptor":
        return LanDescriptor(
            nic=NicDescriptor.deserialize(serialized["nic"]),
            gw=serialized["gw"],
            next_hop=serialized["next_hop"])


def list_local_nics(interfaces=[], skip=[], include_loopback=False) -> Sequence[Tuple[str, Sequence[Mapping[str, str]]]]:
    """
    Return a list generator of all NICs detected to have an IPv4 address.
    The list contains tuple of the form (nic, ip_addresses)
    """
    def _intf_addresses(intf):
        return [
            {
                "addr": a["addr"],
                "netmask": a["netmask"],
            } for a in netifaces.ifaddresses(intf).get(netifaces.AF_INET, [])
            if include_loopback or not ipv4_nic_network(a["addr"], a["netmask"]).is_loopback
        ]

    return [
        (intf, intf_addrs)
        for intf in netifaces.interfaces()
            if intf not in skip and (not interfaces or intf in interfaces)
            for intf_addrs in [_intf_addresses(intf)]
                if len(intf_addrs) > 0
    ]


def list_local_networks(*args, **kwargs) -> Sequence[NicDescriptor]:
    """
    Return a list generator of all IPv4 networks associated with local nics.
    The list contains dict() elements describing each network
    """
    roaming = kwargs.get("roaming")
    return [
        NicDescriptor(
            name=nic,
            address=ipaddress.IPv4Address(nic_addr["addr"]),
            subnet=subnet,
            netmask=ipv4_netmask_to_cidr(subnet.netmask))
        for nic, nic_addrs in list_local_nics(*args, **kwargs)
            for nic_addr in nic_addrs
                for subnet in [
                    ipv4_nic_network(
                        nic_addr["addr"],
                        nic_addr["netmask"] if not roaming else 32)
                ]
    ]

def ipv4_nic_network(nic_addr, nic_netmask=None, nic_cidr=0) -> ipaddress.IPv4Network:
    if nic_netmask is not None:
        mask_size = ipv4_netmask_to_cidr(nic_netmask)
    else:
        mask_size = nic_cidr
    ip = ipaddress.IPv4Address(nic_addr)
    ip_int = int(ip)
    if mask_size < 32:
        ip_int = ip_int - (ip_int & ((1 << 32 - mask_size) - 1))
    ip_net_addr = ipaddress.IPv4Address(ip_int)
    net = ipaddress.IPv4Network("{}/{}".format(ip_net_addr, mask_size))
    return net

def ipv4_netmask_to_cidr(mask):
    ip = ipaddress.IPv4Address(mask)
    bin_ip = bin(int(ip))
    mask_len = bin_ip[2:].rindex("1")
    if mask_len < 0:
        raise ValueError("invalid netmask: {}".format(mask))
    return mask_len + 1

def ipv4_enable_source_nat(nic, src_network):
    exec_command(
        ["iptables", "-I", "INPUT", "1", "-i", str(nic), "-j", "ACCEPT"])
    exec_command([
        "iptables", "-t", "nat", "-I", "POSTROUTING", "1",
            "-s", str(src_network), "-o", str(nic), "-j", "MASQUERADE"])


def ipv4_disable_source_nat(nic, src_network):
    exec_command(
        ["iptables", "-D", "INPUT", "-i", str(nic), "-j", "ACCEPT"])
    exec_command([
        "iptables", "-t", "nat", "-D", "POSTROUTING",
        "-s", str(src_network), "-o", str(nic), "-j", "MASQUERADE"])


def ipv4_enable_output_nat(nic, v6: bool=False):
    iptables = "iptables6" if v6 else "iptables"
    exec_command(
        [iptables, "-t", "nat", "-A", "POSTROUTING", "-o", str(nic), "-j", "MASQUERADE"])


def ipv4_disable_output_nat(nic, v6: bool=False, ignore_errors=False):
    iptables = "iptables6" if v6 else "iptables"
    exec_command(
        [iptables, "-t", "nat", "-D", "POSTROUTING", "-o", str(nic), "-j", "MASQUERADE"],
        noexcept=ignore_errors)


def ipv4_enable_forward(nic, v6: bool=False):
    iptables = "iptables6" if v6 else "iptables"
    exec_command(
        [iptables, "-A", "FORWARD", "-i", str(nic), "-j", "ACCEPT"])
    exec_command(
        [iptables, "-A", "FORWARD", "-o", str(nic), "-j", "ACCEPT"])
    exec_command(
        [iptables, "-A", "INPUT", "-i", str(nic), "-j", "ACCEPT"])


def ipv4_disable_forward(nic, v6: bool=False, ignore_errors=False):
    iptables = "iptables6" if v6 else "iptables"
    exec_command(
        [iptables, "-D", "FORWARD", "-i", str(nic), "-j", "ACCEPT"],
        noexcept=ignore_errors)
    exec_command(
        [iptables, "-D", "FORWARD", "-o", str(nic), "-j", "ACCEPT"],
        noexcept=ignore_errors)
    exec_command(
        [iptables, "-D", "INPUT", "-i", str(nic), "-j", "ACCEPT"],
        noexcept=ignore_errors)

def ipv4_enable_kernel_forwarding():
    exec_command(
        ["echo", "1", ">", "/proc/sys/net/ipv4/ip_forward"],
        shell=True,
        fail_msg="failed to enable ipv4 forwarding")


def ipv4_add_route_to_network(net_addr, net_nic, net_gw):
    exec_command(
        ["ip", "route", "add", str(net_addr),
            "via", str(net_gw), "dev", str(net_nic)],
        fail_msg="failed to add route: {}({}) <--> {}".format(
            str(net_gw), str(net_nic), str(net_addr)))

def ipv4_del_route_to_network(net_addr, net_nic, net_gw):
    exec_command(
        ["ip", "route", "del", str(net_addr),
            "via", str(net_gw), "dev", str(net_nic)],
        fail_msg="failed to remove route: {}({}) <--> {}".format(
            str(net_gw), str(net_nic), str(net_addr)))

def ipv4_from_bytes(ip_bytes):
    return ipaddress.IPv4Address(int.from_bytes(ip_bytes, byteorder="big"))

def ipv4_to_bytes(ip):
    ip = ipaddress.ip_address(ip)
    if not isinstance(ip, ipaddress.IPv4Address):
        raise TypeError("expected IPv4 address")
    return int(ip).to_bytes(4, byteorder="big")

def ipv4_gethostbyname(hostname):
    return socket.gethostbyname(hostname)

def ipv4_nsresolve(hostname):
    from sh import awk, grep, nslookup
    return str(awk(grep(grep(nslookup(hostname),
            "-A","1","^Name:\thost.org8"),
                "^Address"),
                    "{print $2;}")).strip()

def ipv4_nslookup(ip):
    ip = ipaddress.ip_address(ip)
    from sh import awk, cut, nslookup, rev
    # nslookup ${ip} | cut -d= -f2- | awk '{print $1;}' | rev | cut -d. -f2- | rev 
    hostname = str(rev(cut(rev(awk(cut(nslookup(str(ip)),
                "-d=", "-f2-"),
                    "{print $1;}")),
                        "-d.", "-f2-"))).strip()
    if hostname:
        return hostname
    raise StopIteration()

def ipv4_list_routes(oneline=True, resolve=True, split=True) -> set[str]:
    if not oneline:
        cmd = ["ip", "route"]
    else:
        cmd = ["ip", "-o", "route"]
    result = exec_command(cmd, fail_msg="failed to list routes", capture_output=True)
    results = result.stdout.decode("utf-8")
    if split:
        results = frozenset(l for l in results.splitlines() if l)
    return results


def ipv4_resolve_address(ip, ns=None, cache=True, resolv_cache={}):
    try:
        i_ip = ipaddress.ip_address(ip)
    except:
        return item
    if cache:
        hostname = resolv_cache.get(i_ip)
        if hostname:
            return hostname
    if ns:
        try:
            hostname = ns.nslookup(i_ip)
            if cache:
                resolv_cache[i_ip] = hostname
            return hostname
        except StopIteration as e:
            pass
    try:
        hostname = ipv4_nslookup(i_ip)
        if cache:
            resolv_cache[i_ip] = hostname
        return hostname
    except:
        return ip

import re
def ipv4_resolve_text(text, ns=None, cache=True):
    text = str(text)
    valid_ip_addr = r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    ips = set(filter(lambda i: re.match(valid_ip_addr, i), text.split(" ")))
    if not ips:
        # No ip addresses detected
        return text
    # filter out network addresses
    ips = set(map(lambda i: i.strip(), filter(lambda i: i.find("/") < 0, ips)))
    resolved = {}
    for ip in ips:
        hostname = ipv4_resolve_address(ip, ns=ns, cache=cache, resolv_cache=resolved)
        if hostname == ip:
            hostname = "unknown"
        text = re.sub(f"{ip}([^/0-9])", f"\"{hostname}\" <{ip}>\\1", text)
    return text

import math
def ipv4_range_subnet(ip_start, ip_end):
    subnet_hosts = int(ip_end) - int(ip_start)
    if subnet_hosts <= 0:
        raise ValueError(ip_start, ip_end)
    # Find the first power of 2 big enough to
    host_bits = math.ceil(math.log(subnet_hosts, 2))
    subnet_size = 32 - host_bits
    if subnet_size < 0:
        raise ValueError(ip_start, ip_end)
    subnet = ipv4_nic_network(ip_start, nic_cidr=subnet_size)
    return subnet


def ipv4_default_gateway() -> ipaddress.IPv4Address:
    result = exec_command(["ip", "route", "show", "default"],
        fail_msg="failed to get kernel routes",
        capture_output=True)
    for line in result.stdout.decode("utf-8").strip().splitlines():
        if not line.startswith("default via "):
            continue
        l_split = list(filter(len, line.split()))
        try:
            gw = ipaddress.ip_address(l_split[2])
        except Exception as e:
            from .log import Logger as log
            log.error(f"failed to parse gateway ip address: '{l_split[2]}'")
            log.exception(e)
            continue
        return gw
    
    raise RuntimeError("failed to determine default gateway")


def ipv4_get_route(target: ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    target_str = str(target)
    result = exec_command(["ip", "route", "get", target_str],
        fail_msg=f"failed to get routes for {target}",
        capture_output=True)
    for line in result.stdout.decode("utf-8").strip().splitlines():
        if not line.startswith(target_str):
            continue
        l_split = list(filter(len, line.split()))
        try:
            gw = ipaddress.ip_address(l_split[2])
        except Exception as e:
            continue
        return gw
    return ipv4_default_gateway()

def ip_nic_is_up(nic: str) -> bool:
    result = exec_command(["ip", "link", "show", nic, "up"],
        fail_msg=f"failed to check the status of interface {nic}",
        capture_output=True)
    # TODO(asorbini) check that the interface was actually returned
    return bool(result.stdout.decode("utf-8").strip())

def ip_nic_exists(nic: str) -> bool:
    result = exec_command(["ip", "link", "show", nic],
        fail_msg=f"failed to check existence of interface {nic}",
        capture_output=True)
    # TODO(asorbini) check that the interface was actually returned
    return bool(result.stdout.decode("utf-8").strip())

