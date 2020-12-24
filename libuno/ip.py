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
import netifaces
import ipaddress
import socket
from itertools import chain
from functools import partial
# flatten = lambda t: [item for sublist in t for item in sublist]

from libuno.exec import exec_command, decode_output
import libuno.log

logger = libuno.log.logger("uvn.ip")

def list_local_nics(interfaces=[], skip=[], include_loopback=False):
    """
    Return a list generator of all NICs detected to have an IPv4 address.
    The list contains tuple of the form (nic, ip_addresses)
    """
    def _filter_loopback(addr):
        return (include_loopback
                or not ipv4_nic_network(
                        addr["addr"],
                        addr["netmask"]).is_loopback)

    def _intf_addresses(intf):
        addrs = netifaces.ifaddresses(intf)
        addrs = addrs.get(netifaces.AF_INET, [])
        return list(filter(_filter_loopback, addrs))

    ninterfaces = filter(lambda intf: (
                        intf not in skip
                        and (not interfaces or intf in interfaces)),
                    netifaces.interfaces())

    return list(filter(lambda r: len(r[1]) > 0,
        map(lambda intf: (intf, _intf_addresses(intf)), ninterfaces)))

def list_local_networks(*args, **kwargs):
    """
    Return a list generator of all IPv4 networks associated with local nics.
    The list contains dict() elements describing each network
    """

    def _addr_to_net(nic, addr):
        subnet = ipv4_nic_network(addr["addr"], addr["netmask"])
        net = {
            "nic": nic,
            "address": ipaddress.IPv4Address(addr["addr"]),
            "subnet": subnet,
            "mask": ipv4_netmask_to_cidr(subnet.netmask)
        }
        # if "broadcast" in addr:
        #     net["broadcast"] = ipaddress.IPv4Address(addr["broadcast"])
        # if "peer" in addr:
        #     net["peer"] = ipaddress.IPv4Address(addr["peer"]) 
        return net
    return chain.from_iterable(
        map(lambda nic_r: map(partial(_addr_to_net, nic_r[0]), nic_r[1]),
                list_local_nics(*args, **kwargs)))

def ipv4_nic_network(nic_addr, nic_netmask=None, nic_cidr=0):
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
    logger.debug("enabling source NAT on {} for {}", nic, src_network)
    exec_command(
        ["iptables", "-I", "INPUT", "1", "-i", str(nic), "-j", "ACCEPT"],
        root=True)
    exec_command([
        "iptables", "-t", "nat", "-I", "POSTROUTING", "1",
        "-s", str(src_network), "-o", str(nic), "-j", "MASQUERADE"],
        root=True)
    logger.activity("[enabled] source NAT on {} for {} from {}",
        nic, src_network, src_nic)


def ipv4_disable_source_nat(nic, src_network):
    logger.debug("disabling source NAT on {} for {}", nic, src_network)
    exec_command(
        ["iptables", "-D", "INPUT", "-i", str(nic), "-j", "ACCEPT"],
        root=True)
    exec_command([
        "iptables", "-t", "nat", "-D", "POSTROUTING",
        "-s", str(src_network), "-o", str(nic), "-j", "MASQUERADE"],
        root=True)
    logger.activity("[disabled] source NAT on {} for {} ",
        nic, src_network)


def ipv4_enable_output_nat(nic):
    exec_command([
        "iptables", "-t", "nat", "-A", "POSTROUTING", "-o", str(nic), "-j", "MASQUERADE"],
        root=True)


def ipv4_disable_output_nat(nic, ignore_errors=False):
    exec_command([
        "iptables", "-t", "nat", "-D", "POSTROUTING", "-o", str(nic), "-j", "MASQUERADE"],
        root=True,
        noexcept=ignore_errors,
        quiet=ignore_errors)


def ipv4_enable_forward(nic):
    exec_command(
        ["iptables", "-A", "FORWARD", "-i", str(nic), "-j", "ACCEPT"],
        root=True)
    exec_command(
        ["iptables", "-A", "FORWARD", "-o", str(nic), "-j", "ACCEPT"],
        root=True)
    exec_command(
        ["iptables", "-A", "INPUT", "-i", str(nic), "-j", "ACCEPT"],
        root=True)


def ipv4_disable_forward(nic, ignore_errors=False):
    exec_command(
        ["iptables", "-D", "FORWARD", "-i", str(nic), "-j", "ACCEPT"],
        root=True,
        noexcept=ignore_errors,
        quiet=ignore_errors)
    exec_command(
        ["iptables", "-D", "FORWARD", "-o", str(nic), "-j", "ACCEPT"],
        root=True,
        noexcept=ignore_errors,
        quiet=ignore_errors)
    exec_command(
        ["iptables", "-D", "INPUT", "-i", str(nic), "-j", "ACCEPT"],
        root=True,
        noexcept=ignore_errors,
        quiet=ignore_errors)

def ipv4_enable_forwarding():
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

def ipv4_list_routes(oneline=False, resolve=True, split=True):
    if not oneline:
        cmd = ["ip", "route"]
    else:
        cmd = ["ip", "-o", "route"]
    result = exec_command(cmd, fail_msg="failed to list routes")
    results = result.stdout.decode("utf-8")
    if split:
        results = frozenset(results.split("\n")[:-1])
    return results

def ipv4_resolve_address(ip, ns=None, cache=True, resolv_cache={}):
    try:
        i_ip = ipaddress.ip_address(ip)
    except:
        logger.debug(f"not an ip: {ip}")
        return item
    if cache:
        hostname = resolv_cache.get(i_ip)
        if hostname:
            logger.debug(f"found cached: {ip} -> {hostname}")
            return hostname
    if ns:
        try:
            hostname = ns.nslookup(i_ip)
            if cache:
                resolv_cache[i_ip] = hostname
            logger.debug(f"ns resolved: {ip} -> {hostname}")
            return hostname
        except StopIteration as e:
            pass
    try:
        hostname = ipv4_nslookup(i_ip)
        logger.activity("[nslookup] {}: {}", i_ip, hostname)
        if cache:
            resolv_cache[i_ip] = hostname
        logger.debug(f"DNS resolved: {ip} -> {hostname}")
        return hostname
    except:
        logger.debug(f"unresolved: {ip}")
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

def ipv4_default_gateway():
    result = exec_command(["ip", "route"],
        fail_msg="failed to get kernel routes")
    
    for line in decode_output(result.stdout):
        if not line.startswith("default via "):
            continue
        l_split = list(filter(len, line.split()))
        try:
            gw = ipaddress.ip_address(l_split[2])
        except Exception as e:
            logger.debug("failed to parse as gateway address: {}", l_split[2])
            continue
        return gw
    
    raise RuntimeError("failed to determine default gateway")
