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
"""Helper module to configure and control WireGuard"""

import subprocess
import ipaddress
import string
import tempfile
import pathlib
import os
import types

from libuno.yml import YamlSerializer
from libuno.exec import exec_command, decode_output
from libuno.helpers import Timestamp, humanbytes

class WireGuardError(Exception):
    
    def __init__(self, msg):
        self.msg = msg

def genpeermaterial():
    keypair = genkeypair()
    pskey = genkeypreshared()
    return (keypair[0], keypair[1], pskey)

def genkeypair():
    privkey = genkeyprivate()
    pubkey = genkeypublic(privkey)
    return (privkey, pubkey)

def genkeyprivate():
    prc_result = subprocess.run(
        ["wg", "genkey"],
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE)
    if prc_result.returncode != 0:
        raise WireGuardError(
            msg="".join([
                "Failed to generate private key: ", prc_result.stderr()]))
    privkey = prc_result.stdout.decode("utf-8")
    if (len(privkey) == 0):
        raise WireGuardError(
            msg="".join([
                "Invalid private key generated: ", privkey]))
    elif (privkey[-1] == "\n"):
        privkey = privkey[:-1]
    return privkey

def genkeypublic(private_key):
    prc_result = subprocess.run(
        ["wg", "pubkey"],
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
        input = private_key.encode("utf-8"))
    if prc_result.returncode != 0:
        raise WireGuardError(
            msg="".join([
                "Failed to generate public key: ", prc_result.stderr()]))
    pubkey = prc_result.stdout.decode("utf-8")
    if (len(pubkey) == 0):
        raise WireGuardError(
            msg="".join([
                "Invalid public key generated: ", pubkey]))
    elif (pubkey[-1] == "\n"):
        pubkey = pubkey[:-1]
    return pubkey

def genkeypreshared():
    prc_result = subprocess.run(
        ["wg", "genpsk"],
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE)
    if prc_result.returncode != 0:
        raise WireGuardError(
            msg="".join([
                "Failed to generate preshared key: ", prc_result.stderr()]))
    psk = prc_result.stdout.decode("utf-8")
    if (len(psk) == 0):
        raise WireGuardError(
            msg="".join([
                "Invalid preshared key generated: ", psk]))
    elif (psk[-1] == "\n"):
        psk = psk[:-1]
    return psk


class WireGuardKeyPair:

    def __init__(self, privkey, pubkey):
        self.privkey = privkey
        self.pubkey = pubkey
    
    @staticmethod
    def generate():
        mat = genkeypair()
        return WireGuardKeyPair(privkey = mat[0], pubkey = mat[1])
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            if (kwargs.get("public_only")):
                privkey = ""
            else:
                privkey = py_repr.privkey
            
            yml_repr = dict()
            yml_repr["pubkey"] = py_repr.pubkey
            yml_repr["privkey"] = privkey
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = WireGuardKeyPair(
                            pubkey=yml_repr["pubkey"],
                            privkey=yml_repr["privkey"])
            return py_repr

import subprocess

import libuno.log

logger = libuno.log.logger("uno.wg")

class WireGuardInterface:
    def __init__(self,
                 interface,
                 interface_address,
                 interface_address_mask,
                 config,
                 keep=False,
                 allowed_ips=set()):
        self.interface = interface
        self.interface_address = interface_address
        self.interface_address_mask = interface_address_mask
        self.config = config
        self.created = False
        self.up = False
        self.keep = keep
        self.allowed_ips = set(allowed_ips)
    
    def create(self):
        if self.created:
            logger.warning("wireguard interface already created: {}",
                self.interface)
            return

        logger.debug("creating wireguard interface: {}", self.interface)
        
        # Check if interface already exists with "ip link show..."
        result = exec_command([
            "ip", "link", "show", self.interface],
            root=True,
            noexcept=True,
            quiet=True)
        intf_exists = result.returncode == 0
        
        if intf_exists:
            # Delete interface with "ip link delete dev..."
            logger.debug("deleting existing wireguard interface: {}", self.interface)
            exec_command([
                "ip", "link", "delete", "dev", self.interface],
                root=True,
                fail_msg="failed to delete interface: {}".format(self.interface),
                exception=WireGuardError)

        # Add interface with "ip link add dev..."
        exec_command([
            "ip", "link", "add", "dev", self.interface, "type", "wireguard"],
            root=True,
            fail_msg="failed to add interface: {}".format(self.interface),
            exception=WireGuardError)
        
        logger.debug("created wireguard interface: {}", self.interface)

        # Mark interface as up
        self.created = True

    def delete(self):
        if not self.created:
            logger.warning("wireguard interface not deleted: {}",
                self.interface)
            return

        logger.debug("deleting wireguard interface: {}", self.interface)
        
        # Remove interface with "ip link delete dev..."
        exec_command([
            "ip", "link", "delete", "dev", self.interface],
            root=True,
            fail_msg="failed to add interface: {}".format(self.interface),
            exception=WireGuardError)
        
        logger.debug("deleted wireguard interface: {}", self.interface)

        # Mark interface as up
        self.created = False
    
    def bring_up(self):
        if self.up:
            logger.warning("wireguard interface already active: {}",
                self.interface)
            return

        logger.debug("activating wireguard interface: {} [{}]",
            self.interface, self.interface_address)

        # Disable interface with "ip link set down dev..."
        exec_command([
            "ip", "link", "set", "down", "dev", self.interface],
            root=True,
            fail_msg="failed to disable interface: {}".format(self.interface),
            exception=WireGuardError)
        
        exec_command([
            "ip", "address", "flush", "dev", self.interface],
            root=True,
            fail_msg="failed to reset addresses on interface: {}".format(self.interface),
            exception=WireGuardError)
        
        # Configure interface address with "ip address add dev..."
        exec_command([
            "ip", "address", "add", 
            "dev", self.interface,
            "{}/{}".format(self.interface_address, self.interface_address_mask)],
            root=True,
            fail_msg="failed to configure interface address: {} {}".format(
                        self.interface, self.interface_address),
            exception=WireGuardError)
        
        # Generate a temporary file with wg configuration
        tmp_file_fd, tmp_file_path = tempfile.mkstemp(
            prefix="{}-".format(self.interface),
            suffix="-wgconf")
        tmp_file_path = pathlib.Path(str(tmp_file_path))
        try:
            with tmp_file_path.open("w") as output:
                output.write(self.config)
                output.flush()
            
            # Set wireguard configuration with "wg setconf..."
            exec_command([
                "wg", "setconf", self.interface, str(tmp_file_path)],
                root=True,
                fail_msg="failed to configure wireguard: {}".format(self.interface),
                exception=WireGuardError)
        finally:
            os.close(tmp_file_fd)
            if not self.keep:
                tmp_file_path.unlink()
            else:
                logger.warning("[tmp] not deleted: {}", tmp_file_path)

        # Activate interface with "ip link set up dev..."
        exec_command([
            "ip", "link", "set", "up", "dev", self.interface],
            root=True,
            fail_msg="failed to activate wireguard: {}".format(self.interface),
            exception=WireGuardError)

        # Allow configure IP addresses
        for p in self._list_peers():
            for a in self.allowed_ips:
                self.allow_ips(p, a)

        logger.activity("wireguard interface active: {} [{}]",
            self.interface, self.interface_address)

        # Mark interface as up
        self.up = True

    def tear_down(self):
        if not self.up:
            logger.warning("wireguard interface already disabled: {}",
                self.interface)
            return

        logger.debug("disabling wireguard interface: {}", self.interface)
        
        # Disable interface with "ip link set down dev..."
        exec_command([
            "ip", "link", "set", "down", "dev", self.interface],
            root=True,
            fail_msg="failed to disable interface: {}".format(self.interface),
            exception=WireGuardError)
        
        exec_command([
            "ip", "address", "flush", "dev", self.interface],
            root=True,
            fail_msg="failed to reset addresses on interface: {}".format(self.interface),
            exception=WireGuardError)
        
        logger.activity("wireguard interface disabled: {}", self.interface)

        # Mark interface as down
        self.up = False

    def _list_peers(self):
        result = exec_command(["wg", "show", str(self.interface), "peers"],
            quiet=True,
            root=True,
            fail_msg="failed to get peers for interface: {}".format(self.interface),
            exception=WireGuardError)
        peers = set(decode_output(result.stdout))
        logger.trace("current peers [{}]: {}", self.interface, peers)
        return peers

    def _list_handshakes(self):
        result = exec_command(["wg", "show", str(self.interface), "latest-handshakes"],
            quiet=True,
            root=True,
            fail_msg="failed to get latest handshakes for interface: {}".format(self.interface),
            exception=WireGuardError)
        handshakes = {}
        for line in decode_output(result.stdout):
            l_split = list(filter(len, line.split()))
            handshakes[l_split[0]] = Timestamp.unix(l_split[1])
        logger.trace("current handshakes [{}]: {}", self.interface, handshakes)
        return handshakes
    
    def _list_transfer(self):
        result = exec_command(["wg", "show", str(self.interface), "transfer"],
            quiet=True,
            root=True,
            fail_msg="failed to get transfer stats for interface: {}".format(self.interface),
            exception=WireGuardError)
        transfers = {}
        for line in decode_output(result.stdout):
            l_split = list(filter(len, line.split()))
            transfers[l_split[0]] = {
                "recv": int(l_split[1]),
                "send": int(l_split[2])
            }
        logger.trace("current transfer stats [{}]: {}", self.interface, transfers)
        return transfers
    
    def _list_endpoints(self):
        result = exec_command(["wg", "show", str(self.interface), "endpoints"],
            quiet=True,
            root=True,
            fail_msg="failed to get endpoints for interface: {}".format(self.interface),
            exception=WireGuardError)
        endpoints = {}
        for line in decode_output(result.stdout):
            l_split = list(filter(len, line.split()))
            endp_split = list(filter(len, l_split[1].split(":")))
            try:
                addr = ipaddress.ip_address(endp_split[0])
                port = int(endp_split[1])
            except Exception as e:
                addr = "<unknown>"
                port = "<unknown>"
            endpoints[l_split[0]] = {
                "address": addr,
                "port": port
            }
        logger.trace("current endpoints [{}]: {}", self.interface, endpoints)
        return endpoints
    
    def _list_allowed_ips(self):
        result = exec_command(["wg", "show", str(self.interface), "allowed-ips"],
            quiet=True,
            root=True,
            fail_msg="failed to get endpoints for interface: {}".format(self.interface),
            exception=WireGuardError)
        allowed_ips = {}
        for line in decode_output(result.stdout):
            l_split = list(filter(len, line.split()))
            ips = set(map(ipaddress.ip_network,
                    filter(lambda s: s != "(none)",
                        filter(len, l_split[1:]))))
            allowed_ips[l_split[0]] = ips
        logger.trace("current allowed IPs [{}]: {}", self.interface, allowed_ips)
        return allowed_ips

    def _list_allowed_ips_peer(self, peer):
        ips = self._list_allowed_ips()
        return ips.get(peer, set())
    
    def _update_allowed_ips(self, peer, allowed_ips):
        logger.trace("updating allowed ips for peer {} on {}: {}",
            peer, self.interface, list(map(str, allowed_ips)))
        # sort ips for tidyness in `wg show`'s output
        allowed_ips_str = sorted(map(str,allowed_ips))
        exec_command([
            "wg", "set", self.interface,
                "peer", peer, "allowed-ips", ",".join(allowed_ips_str)],
            root=True,
            fail_msg=f"failed to get set allowed-ips on interface: {self.interface}",
            exception=WireGuardError)
        allowed_ips_set = self._list_allowed_ips_peer(peer)
        if allowed_ips ^ allowed_ips_set:
            logger.warning("[unexpected allowed][{}] {}",
                self.interface, peer)
            logger.warning("[set][{}] {}: {}",
                self.interface, peer, allowed_ips)
            logger.warning("[found][{}] {}: {}",
                self.interface, peer, allowed_ips_set)

    def allow_ips(self, peer, addr):
        addr = ipaddress.ip_network(addr)
        allowed_ips_nic = self._list_allowed_ips_peer(peer)
        # if allowed_ips_nic != self.allowed_ips:
        #     logger.warning("unexpected allowed IPs: expected={}, found={}",
        #         self.allowed_ips, allowed_ips_nic)
        if addr not in self.allowed_ips:
            self.allowed_ips.add(addr)
            self._update_allowed_ips(peer, self.allowed_ips)
        else:
            logger.debug("[already allowed][{}] {}: {}",
                self.interface, peer, addr)
    
    def disallow_ips(self, peer, addr):
        allowed_ips_nic = self._list_allowed_ips_peer(peer)
        # if allowed_ips_nic != self.allowed_ips:
        #     logger.warning("unexpected allowed IPs: expected={}, found={}",
        #         self.allowed_ips, allowed_ips_nic)
        if addr not in self.allowed_ips:
            self.allowed_ips.add(addr)
            self._update_allowed_ips(peer, self.allowed_ips)
        else:
            logger.warning("already disabled for {} on {}: {}",
                peer, self.interface, addr)

    def peers(self):
        result = exec_command(
            ["wg", "show", str(self.interface), "peers"],
            root=True,
            fail_msg="failed to get current peers for interface: {}".format(self.interface),
            exception=WireGuardError)
        peers = list(filter(lambda v: len(v) > 0, result.stdout.decode("utf-8").split("\n")))
        return peers
    
    def stat(self):
        peers = self._list_peers()
        handshakes = self._list_handshakes()
        transfers = self._list_transfer()
        endpoints = self._list_endpoints()
        allowed_ips = self._list_allowed_ips()
        peers = {p : {
            # "pubkey": p,
            "last_handshake": str(handshakes[p]),
            "transfer": {
                "recv": humanbytes(transfers[p]["recv"]),
                "send": humanbytes(transfers[p]["send"])
            },
            "endpoint": {
                "address": str(endpoints[p]["address"]),
                "port": endpoints[p]["port"]
            },
            "allowed_ips": ", ".join(map(str, allowed_ips[p]))
        } for p in peers}
        return {
            "peers": peers,
            "up": self.up,
            "created": self.created,
            # "config": self.config,
            "address": f"{self.interface_address}/{self.interface_address_mask}"
        }

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return py_repr.stat()
    
        def repr_py(self, yml_repr, **kwargs):
            raise NotImplementedError()
