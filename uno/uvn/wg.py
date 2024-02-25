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
import subprocess
import ipaddress
from tempfile import NamedTemporaryFile
from pathlib import Path
from typing import Tuple, Iterable, Optional, Mapping, Union, Sequence

import jinja2


from .exec import exec_command
from .time import Timestamp
from .render import Templates, humanbytes
from .log import Logger as log
from .ip import ip_nic_is_up, ip_nic_exists

class WireGuardError(Exception):
  def __init__(self, msg):
    self.msg = msg


def genpeermaterial() -> Tuple[str, str, str]:
  privkey, pubkey = genkeypair()
  pskey = genkeypreshared()
  return (privkey, pubkey, pskey)


def genkeypair() -> Tuple[str, str]:
  privkey = genkeyprivate()
  pubkey = genkeypublic(privkey)
  return (privkey, pubkey)


def genkeyprivate() -> str:
  prc_result = subprocess.run(
    ["wg", "genkey"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)
  if prc_result.returncode != 0:
    raise WireGuardError(
      f"failed to generate private key: {prc_result.stderr.decode('utf-8')}")
  privkey = prc_result.stdout.decode("utf-8").strip()
  if not privkey:
    raise WireGuardError("invalid empty private key generated")
  return privkey


def genkeypublic(private_key) -> str:
  prc_result = subprocess.run(
    ["wg", "pubkey"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    input=private_key.encode("utf-8"))
  if prc_result.returncode != 0:
    raise WireGuardError(
      f"failed to generate public key: {prc_result.stderr.decode('utf-8')}")
  pubkey = prc_result.stdout.decode("utf-8").strip()
  if not pubkey:
    raise WireGuardError("invalid empty public key generated")
  return pubkey


def genkeypreshared() -> str:
  prc_result = subprocess.run(
    ["wg", "genpsk"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)
  if prc_result.returncode != 0:
    raise WireGuardError(
      f"failed to generate preshared key: {prc_result.stderr.decode('utf-8')}")
  psk = prc_result.stdout.decode("utf-8").strip()
  if not psk:
    raise WireGuardError("invalid empty preshared key generated")
  return psk


class WireGuardKeyPair:
  def __init__(self, privkey, pubkey):
    self.privkey = privkey
    self.pubkey = pubkey
    if not self.pubkey:
      raise ValueError("invalid empty public key", self.pubkey)


  def serialize(self) -> dict:
    serialized = {
      "privkey": self.privkey,
      "pubkey": self.pubkey
    }
    if not self.privkey:
      del serialized["privkey"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardKeyPair":
    return WireGuardKeyPair(
      privkey=serialized.get("privkey"),
      pubkey=serialized["pubkey"])


  @staticmethod
  def generate():
    privkey, pubkey = genkeypair()
    return WireGuardKeyPair(privkey=privkey, pubkey=pubkey)


class WireGuardInterfaceConfig:
  def __init__(self,
      name: str,
      privkey: str,
      address: ipaddress.IPv4Address,
      netmask: int,
      port: Optional[int]=None,
      endpoint: Optional[str]=None) -> None:
    self.name = name
    self.privkey = privkey
    self.address = address
    self.netmask = netmask
    self.port = port
    self.endpoint = endpoint


  def serialize(self) -> dict:
    serialized = {
      "name": self.name,
      "privkey": self.privkey,
      "address": str(self.address),
      "netmask": self.netmask,
      "port": self.port,
      "endpoint": self.endpoint,
    }

    if self.port is None:
      del serialized["port"]

    if self.endpoint is None:
      del serialized["endpoint"]

    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardInterfaceConfig":
    return WireGuardInterfaceConfig(
      name=serialized["name"],
      privkey=serialized["privkey"],
      address=ipaddress.ip_address(serialized["address"]),
      netmask=serialized["netmask"],
      port=serialized.get("port"),
      endpoint=serialized.get("endpoint"))


class WireGuardInterfacePeerConfig:
  def __init__(self,
      id: int,
      pubkey: str,
      psk: str,
      address: Union[str, int],
      allowed: Optional[str]=None,
      endpoint: Optional[str]=None,
      keepalive: Optional[int]=None) -> None:
    self.id = id
    self.pubkey = pubkey
    self.psk = psk
    self.address = ipaddress.ip_address(address)
    self.allowed = allowed
    self.endpoint = endpoint
    self.keepalive = keepalive


  def serialize(self) -> dict:
    serialized = {
      "id": self.id,
      "pubkey": self.pubkey,
      "psk": str(self.psk),
      "address": str(self.address),
      "allowed": self.allowed,
      "endpoint": self.endpoint,
      "keepalive": self.keepalive,
    }
    if self.endpoint is None:
      del serialized["endpoint"]
    if self.allowed is None:
      del serialized["allowed"]
    if not self.keepalive:
      del serialized["keepalive"]

    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardInterfacePeerConfig":
    return WireGuardInterfacePeerConfig(
      id=serialized["id"],
      pubkey=serialized["pubkey"],
      psk=serialized["psk"],
      address=serialized["address"],
      allowed=serialized.get("allowed"),
      endpoint=serialized.get("endpoint"),
      keepalive=serialized.get("keepalive"))


class WireGuardConfig:
  def __init__(self,
      intf: WireGuardInterfaceConfig,
      peers: Sequence[WireGuardInterfacePeerConfig],
      generation_ts: Optional[str]=None) -> None:
    self.intf = intf
    self.peers = list(peers)
    self.generation_ts = generation_ts or Timestamp.now().format()


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, WireGuardConfig):
      return False
    return self.generation_ts == other.generation_ts


  def serialize(self) -> dict:
    serialized = {
      "intf": self.intf.serialize(),
      "peers": [p.serialize() for p in self.peers],
      "generation_ts": self.generation_ts,
    }
    if len(self.peers) == 0:
      del serialized["peers"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardConfig":
    return WireGuardConfig(
      intf=WireGuardInterfaceConfig.deserialize(serialized["intf"]),
      peers=[
        WireGuardInterfacePeerConfig.deserialize(p)
          for p in serialized.get("peers", [])
      ],
      generation_ts=serialized["generation_ts"])


class WireGuardInterface:
  WG_CONFIG = Templates.compile("""\
[Interface]
{% if intf.port %}
ListenPort = {{intf.port}}
{% endif %}
PrivateKey = {{intf.privkey}}

{% for peer in peers %}
[Peer]
{% if peer.endpoint %}
Endpoint = {{peer.endpoint}}
{% endif %}
PublicKey = {{peer.pubkey}}
PresharedKey = {{peer.psk}}
{% if peer.allowed -%}
AllowedIPs = {{peer.allowed}}
{% endif %}
{% if peer.keepalive -%}
PersistentKeepalive = {{peer.keepalive}}
{% endif %}
{% endfor %}
""")

  def __init__(self, config: WireGuardConfig):
    self.config = config
    self.created = False
    self.up = False


  def __str__(self) -> str:
    return self.config.intf.name


  def start(self) -> None:
    self.create()
    self.bring_up()
    import time
    time.sleep(1)


  def stop(self) -> None:
    self.tear_down()
    self.delete()
    import time
    time.sleep(1)


  def create(self):
    if self.created:
      # Already created
      return
    # Check if interface already exists with "ip link show..."
    result = exec_command(
      ["ip", "link", "show", self.config.intf.name],
      root=True,
      noexcept=True)
    # Delete interface if it already exists
    if result.returncode == 0:
      try:
        exec_command(
          ["ip", "link", "delete", "dev", self.config.intf.name],
          root=True)
      except:
        raise WireGuardError(f"failed to delete wireguard interface: {self.config.intf.name}")
    # Create interface
    try:
      exec_command([
        "ip", "link", "add", "dev", self.config.intf.name, "type", "wireguard"],
        root=True)
    except:
      raise WireGuardError(f"failed to create wiregaurd interface: {self.config.intf.name}")
    # Mark interface as up
    self.created = True


  def delete(self):
    if not self.created:
      # Not created yet
      return
    # Remove interface with "ip link delete dev..."
    try:
      exec_command(
        ["ip", "link", "delete", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to delete wireguard interface: {self.config.intf.name}")
    # Mark interface as up
    self.created = False


  def bring_up(self):
    if self.up:
      # Already up
      return
    try:
      # Generate a temporary file with wg configuration
      tmp_file_h = NamedTemporaryFile(
        prefix=f"{self.config.intf.name}-",
        suffix="-wgconf")
      wg_config = Path(tmp_file_h.name)
      wg_config.write_text(
        Templates.render(self.WG_CONFIG, self.config.serialize()))
    except:
      raise WireGuardError(f"failed to generate configuration for wireguard interface: {self.config.intf.name}")
    # Disable and reset interface
    try:
      exec_command(
        ["ip", "link", "set", "down", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to disable wireguard interface: {self.config.intf.name}")
    try:
      exec_command(
        ["ip", "address", "flush", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to reset wireguard interface: {self.config.intf.name}")
    # Configure interface with the expected address
    try:
      exec_command(
        ["ip", "address", "add", "dev", self.config.intf.name,
          f"{self.config.intf.address}/{self.config.intf.netmask}"],
        root=True)
    except:
      raise WireGuardError(f"failed to configure address on wireguard interface: {self.config.intf.name}, {self.config.intf.address}/{self.config.intf.netmask}")
    # Set wireguard configuration with "wg setconf..."
    try:
      exec_command(
        ["wg", "setconf", self.config.intf.name, wg_config],
        root=True)
    except:
      raise WireGuardError(f"failed to set wireguard configuration on interface: {self.config.intf.name}")
    # Activate interface with "ip link set up dev..."
    try:
      exec_command(
        ["ip", "link", "set", "up", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to enable wireguard interface: {self.config.intf.name}")
    # # Allow configured IP addresses
    # for p in self._list_peers():
    #   for a in self.allowed_ips:
    #     self._allow_ip_for_peer(p, a)
    # Mark interface as up
    self.up = True


  def tear_down(self):
    if not self.up:
      # Already down
      return
    # Disable interface with "ip link set down dev..."
    try:
      exec_command(
        ["ip", "link", "set", "down", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to disable wireguard interface: {self.config.intf.name}")
    try:
      exec_command(
        ["ip", "address", "flush", "dev", self.config.intf.name],
        root=True)
    except:
      raise WireGuardError(f"failed to reset wireguard interface: {self.config.intf.name}")
    # Mark interface as down
    self.up = False


  def _list_peers(self) -> Iterable[str]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "peers"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list wireguard peers: {self.config.intf.name}")
    result_lines = result.stdout.decode("utf-8").strip().splitlines()
    # result_lines = set(result_lines)
    return result_lines


  def _list_handshakes(self) -> Mapping[str, int]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "latest-handshakes"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list interfacec handshakes: {self.config.intf.name}")
    handshakes = {}
    for line in result.stdout.decode("utf-8").strip().splitlines():
      l_split = list(filter(len, line.split()))
      handshakes[l_split[0]] = Timestamp.unix(l_split[1])
    return handshakes


  def _list_transfer(self) -> Mapping[str, Mapping[str, int]]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "transfer"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list interface transfer amounts: {self.config.intf.name}")
    transfers = {}
    for line in result.stdout.decode("utf-8").strip().splitlines():
      l_split = list(filter(len, line.split()))
      transfers[l_split[0]] = {
        "recv": int(l_split[1]),
        "send": int(l_split[2])
      }
    return transfers


  def _list_endpoints(self) -> Mapping[str, Mapping[str, int]]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "endpoints"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list endpoints for interface: {self.config.intf.name}")
    endpoints = {}
    for line in result.stdout.decode("utf-8").strip().splitlines():
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
    return endpoints


  def _list_allowed_ips(self) -> Mapping[str, Iterable[Union[ipaddress.IPv4Network, ipaddress.IPv6Address]]]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "allowed-ips"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list peers for interface: {self.config.intf.name}")
    allowed_ips = {}
    for line in result.stdout.decode("utf-8").strip().splitlines():
      l_split = list(filter(len, line.split()))
      ips = set(map(ipaddress.ip_network,
        filter(lambda s: s != "(none)",
          filter(len, l_split[1:]))))
      allowed_ips[l_split[0]] = ips
    return allowed_ips


  def _list_allowed_ips_peer(self, peer: WireGuardInterfacePeerConfig) -> Iterable[str]:
    ips = self._list_allowed_ips()
    return ips.get(peer.pubkey, set())


  def _update_allowed_ips(self,
      peer: WireGuardInterfacePeerConfig,
      allowed_ips: Iterable[ipaddress.IPv4Address]) -> None:
    # sort ips for tidyness in `wg show`'s output
    allowed_ips_str = sorted(map(str,allowed_ips))
    try:
      exec_command(
        ["wg", "set", self.config.intf.name,
            "peer", peer.pubkey, "allowed-ips", ",".join(allowed_ips_str)],
        root=True)
    except:
      raise WireGuardError(f"failed to set allowed peers on interface: {self.config.intf.name}")
    # allowed_ips_set = self._list_allowed_ips_peer(peer)
    # if allowed_ips ^ allowed_ips_set:
    #   # TODO(asorbini) do something with the knowledge that the
    #   # list of allowed peers contains unexpected addresses
    #   pass


  def get_peer_allowed_ips(self, peer_i: int) -> Sequence[Union[ipaddress.IPv4Address, ipaddress.IPv4Network]]:
    peer = self.config.peers[peer_i]
    allowed_ips = set()
    for allowed_ip in self._list_allowed_ips_peer(peer):
      try:
        allowed_ips.add(ipaddress.ip_network(allowed_ip))
      except:
        allowed_ips.add(ipaddress.ip_address(allowed_ip))
    return allowed_ips


  def allow_ips_for_peer(self, peer_i: int, addresses: Sequence[ipaddress.IPv4Address]) -> None:
    # addr = ipaddress.ip_network(addr)
    peer = self.config.peers[peer_i]
    allowed_ips_nic = set(self._list_allowed_ips_peer(peer))
    not_yet_allowed = set(map(str, addresses)) - allowed_ips_nic
    if len(not_yet_allowed) > 0:
      allowed_ips = {*allowed_ips_nic, *not_yet_allowed}
      self._update_allowed_ips(peer, allowed_ips)
    # allowed_ips_nic = self._list_allowed_ips_peer(peer)
    # if addr not in allowed_ips_nic:
    #   raise WireGuardError(f"failed to allow address on interface: {self.config.intf.name}, {addr}")


  def disallow_ips_for_peer(self, peer_i: int, addresses: Sequence[ipaddress.IPv4Address]) -> None:
    peer = self.config.peers[peer_i]
    allowed_ips_nic = set(self._list_allowed_ips_peer(peer))
    # addr = ipaddress.ip_network(addr)
    allowed = allowed_ips_nic - set(map(str, addresses))
    if allowed != allowed_ips_nic:
      self._update_allowed_ips(peer, allowed)
    # allowed_ips_nic = self._list_allowed_ips_peer(peer)
    # if addr in allowed_ips_nic:
    #   raise WireGuardError(f"failed to disallow address on interface: {self.config.intf.name}, {addr}")


  def peers(self) -> Sequence[str]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "peers"],
        root=True,
        capture_output=True)
    except:
      raise WireGuardError(f"failed to list interface peers: {self.config.intf.name}")
    return list(filter(lambda v: len(v) > 0, result.stdout.decode("utf-8").split("\n")))


  def stat(self) -> dict:
    peers = self._list_peers()
    handshakes = self._list_handshakes()
    transfers = self._list_transfer()
    endpoints = self._list_endpoints()
    allowed_ips = self._list_allowed_ips()
    peers = {p : {
      "last_handshake": str(handshakes[p]),
      "transfer": {
        "recv": transfers[p]["recv"],
        # humanbytes(transfers[p]["recv"]),
        "send": transfers[p]["send"],
        # humanbytes(transfers[p]["send"])
      },
      "endpoint": {
        "address": str(endpoints[p]["address"]),
        "port": endpoints[p]["port"]
      },
      "allowed_ips": ", ".join(map(str, allowed_ips[p]))
    } for p in peers}
    return {
      "peers": peers,
      "up": ip_nic_is_up(self.config.intf.name),
      "created": ip_nic_exists(self.config.intf.name),
      "address": f"{self.config.intf.address}/{self.config.intf.netmask}"
    }