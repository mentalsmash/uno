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
from typing import Iterable, Mapping, Sequence


from .exec import exec_command
from .time import Timestamp
from .render import Templates
from .ip import ip_nic_is_up, ip_nic_exists
from .log import Logger
log = Logger.sublogger("wg")


def _check_handshake_online(handshake: Timestamp, validity_period: int=150) -> bool:
  handshake_age = Timestamp.now().subtract(handshake)
  return handshake_age.total_seconds() <= validity_period


class WireGuardError(Exception):
  def __init__(self, msg):
    self.msg = msg


def genpeermaterial() -> tuple[str, str, str]:
  privkey, pubkey = genkeypair()
  pskey = genkeypreshared()
  return (privkey, pubkey, pskey)


def genkeypair() -> tuple[str, str]:
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


class WireGuardInterfaceConfig:
  def __init__(self,
      name: str,
      privkey: str,
      address: ipaddress.IPv4Address,
      netmask: int,
      port: int|None=None,
      endpoint: str|None=None,
      mtu: int|None=None) -> None:
    self.name = name
    self.privkey = privkey
    self.address = address
    self.netmask = netmask
    self.subnet = ipaddress.ip_network(f"{self.address}/{self.netmask}", strict=False)
    self.port = port
    self.endpoint = endpoint
    self.mtu = mtu


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, WireGuardInterfaceConfig):
      return False
    return self.name == other.name


  def __hash__(self) -> int:
    return hash(self.name)


  def serialize(self, public: bool=False) -> dict:
    serialized = {
      "name": self.name,
      "privkey": self.privkey if not public else None,
      "address": str(self.address),
      "netmask": self.netmask,
      "port": self.port,
      "endpoint": self.endpoint,
      "mtu": self.mtu,
    }

    if self.port is None:
      del serialized["port"]

    if self.endpoint is None:
      del serialized["endpoint"]

    if self.mtu is None:
      del serialized["mtu"]

    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardInterfaceConfig":
    return WireGuardInterfaceConfig(
      name=serialized["name"],
      privkey=serialized["privkey"],
      address=ipaddress.ip_address(serialized["address"]),
      netmask=serialized["netmask"],
      port=serialized.get("port"),
      endpoint=serialized.get("endpoint"),
      mtu=serialized.get("mtu"))


class WireGuardInterfacePeerConfig:
  def __init__(self,
      id: int,
      pubkey: str,
      psk: str,
      address: str | int,
      allowed: str | None=None,
      endpoint: str | None=None,
      keepalive: int | None=None) -> None:
    self.id = id
    self.pubkey = pubkey
    self.psk = psk
    self.address = ipaddress.ip_address(address)
    self.allowed = sorted(allowed or [])
    self.endpoint = endpoint
    self.keepalive = keepalive


  def serialize(self, public: bool=False) -> dict:
    serialized = {
      "id": self.id,
      "pubkey": self.pubkey,
      "psk": str(self.psk) if not public else None,
      "address": str(self.address),
      "allowed": list(self.allowed),
      "endpoint": self.endpoint,
      "keepalive": self.keepalive,
    }
    if self.endpoint is None:
      del serialized["endpoint"]
    if not self.allowed:
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
      tunnel: bool=False,
      tunnel_root: bool=False,
      masquerade: bool=False,
      forward: bool=False,
      generation_ts: str | None=None) -> None:
    self.intf = intf
    self.peers = list(peers)
    self.tunnel = tunnel
    self.tunnel_root = tunnel_root
    self.masquerade = masquerade
    self.forward = forward
    self.generation_ts = generation_ts or Timestamp.now().format()


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, WireGuardConfig):
      return False
    return self.intf == other.intf


  def __hash__(self) -> int:
    return hash(self.intf)


  @property
  def template_args(self) -> tuple[str, dict]:
    return ("wg/wg.conf", self.serialize())


  def serialize(self, public: bool=False) -> dict:
    serialized = {
      "intf": self.intf.serialize(public=public),
      "peers": [p.serialize(public=public) for p in self.peers],
      "generation_ts": self.generation_ts,
      "tunnel": self.tunnel,
      "tunnel_root": self.tunnel_root,
      "masquerade": self.masquerade,
      "forward": self.forward,
    }
    if len(self.peers) == 0:
      del serialized["peers"]
    if not self.tunnel:
      del serialized["tunnel"]
    if not self.tunnel_root:
      del serialized["tunnel_root"]
    if not self.masquerade:
      del serialized["masquerade"]
    if not self.forward:
      del serialized["forward"]
    return serialized


  @staticmethod
  def deserialize(serialized: dict) -> "WireGuardConfig":
    return WireGuardConfig(
      intf=WireGuardInterfaceConfig.deserialize(serialized["intf"]),
      peers=[
        WireGuardInterfacePeerConfig.deserialize(p)
          for p in serialized.get("peers", [])
      ],
      tunnel=serialized.get("tunnel", False),
      tunnel_root=serialized.get("tunnel_root", False),
      generation_ts=serialized["generation_ts"],
      masquerade=serialized.get("masquerade"),
      forward=serialized.get("forward"))


class WireGuardInterface:
  def __init__(self, config: WireGuardConfig):
    self.config = config
    self.log = log.sublogger(self.config.intf.name)
    self.created = False
    self.up = False


  def __eq__(self, other: object) -> bool:
    if not isinstance(other, WireGuardInterface):
      return False
    return self.config == other.config


  def __hash__(self) -> int:
    return hash(self.config)


  def __str__(self) -> str:
    return self.config.intf.name


  def __repr__(self) -> str:
    return f"{self.__class__.__name__}({self.config.intf.name})"


  def start(self) -> None:
    self.create()
    self.bring_up()
    import time
    time.sleep(1)


  def stop(self, assert_stopped: bool=False) -> None:
    errors = []
    if self.up or assert_stopped:
      self.tear_down(ignore_errors=assert_stopped)
    if self.created or assert_stopped:
      self.delete(ignore_errors=assert_stopped)
    import time
    time.sleep(1)


  def create(self):
    # Check if interface already exists with "ip link show..."
    result = exec_command(
      ["ip", "link", "show", self.config.intf.name],
      noexcept=True)
    # Delete interface if it already exists
    if result.returncode == 0:
      try:
        self.log.debug("making sure interface doesn't exist")
        exec_command(
          ["ip", "link", "delete", "dev", self.config.intf.name])
      except:
        raise WireGuardError(f"failed to delete wireguard interface: {self.config.intf.name}")
    # Create interface
    try:
      self.log.debug("creating WireGuard interface")
      exec_command(
        ["ip", "link", "add", "dev", self.config.intf.name, "type", "wireguard"])
    except:
      raise WireGuardError(f"failed to create wireguard interface: {self.config.intf.name}")
    # Set MTU
    if self.config.intf.mtu:
      try:
        self.log.debug("setting interface MTU")
        exec_command(
          ["ip", "link", "set", "dev", self.config.intf.name, "mtu", str(self.config.intf.mtu)])
      except:
        raise WireGuardError(f"failed to set interface MTU: {self.config.intf.name}, {self.config.intf.mtu}")
    # Mark interface as up
    self.created = True
    self.log.activity("created")


  def delete(self, ignore_errors: bool=False):
    # Remove interface with "ip link delete dev..."
    try:
      self.log.debug("deleting interface")
      exec_command(
        ["ip", "link", "delete", "dev", self.config.intf.name])
    except Exception as e:
      if not ignore_errors:
        raise WireGuardError(f"failed to delete wireguard interface: {self.config.intf.name}")
      else:
        log.warning("failed to delete wireguard interface {}: {}", self.config.intf.name, e)
    # Mark interface as up
    self.created = False
    self.log.activity("deleted")


  def bring_up(self):
    try:
      # Generate a temporary file with wg configuration
      tmp_file_h = NamedTemporaryFile(
        prefix=f"{self.config.intf.name}-",
        suffix="-wgconf")
      wg_config = Path(tmp_file_h.name)
      Templates.generate(wg_config, *self.config.template_args, mode=0o600)
    except:
      raise WireGuardError(f"failed to generate configuration for wireguard interface: {self.config.intf.name}")
    # Disable and reset interface
    try:
      self.log.debug("making sure interface is disabled")
      exec_command(
        ["ip", "link", "set", "down", "dev", self.config.intf.name])
    except:
      raise WireGuardError(f"failed to disable wireguard interface: {self.config.intf.name}")
    try:
      self.log.debug("resetting interface configuration")
      exec_command(
        ["ip", "address", "flush", "dev", self.config.intf.name])
    except:
      raise WireGuardError(f"failed to reset wireguard interface: {self.config.intf.name}")
    # Configure interface with the expected address
    try:
      self.log.debug("creating interface with address {}/{}", self.config.intf.address, self.config.intf.netmask)
      exec_command(
        ["ip", "address", "add", "dev", self.config.intf.name,
          f"{self.config.intf.address}/{self.config.intf.netmask}"])
    except:
      raise WireGuardError(f"failed to configure address on wireguard interface: {self.config.intf.name}, {self.config.intf.address}/{self.config.intf.netmask}")
    # Set wireguard configuration with "wg setconf..."
    try:
      self.log.debug("configuring WireGuard")
      exec_command(
        ["wg", "setconf", self.config.intf.name, wg_config])
    except:
      raise WireGuardError(f"failed to set wireguard configuration on interface: {self.config.intf.name}")
    # Activate interface with "ip link set up dev..."
    try:
      self.log.debug("enabling interface")
      exec_command(
        ["ip", "link", "set", "up", "dev", self.config.intf.name])
    except:
      raise WireGuardError(f"failed to enable wireguard interface: {self.config.intf.name}")
    # # Allow configured IP addresses
    # for p in self._list_peers():
    #   for a in self.allowed_ips:
    #     self._allow_ip_for_peer(p, a)
    # Mark interface as up
    self.up = True
    self.log.activity("up [{}/{}]", self.config.intf.address, self.config.intf.netmask)


  def tear_down(self, ignore_errors: bool=False):
    # Disable interface with "ip link set down dev..."
    try:
      self.log.debug("disabling interface")
      exec_command(
        ["ip", "link", "set", "down", "dev", self.config.intf.name])
    except Exception as e:
      if not ignore_errors:
        raise WireGuardError(f"failed to disable wireguard interface: {self.config.intf.name}")
      else:
        log.warning("failed to disabled wireguard interface {}: {}", self.config.intf.name, e)
    try:
      self.log.debug("resetting interface configuration")
      exec_command(
        ["ip", "address", "flush", "dev", self.config.intf.name])
    except Exception as e:
      if not ignore_errors:
        raise WireGuardError(f"failed to reset wireguard interface: {self.config.intf.name}")
      else:
        log.warning("failed to reset wireguard interface {}: {}", self.config.intf.name, e)
    # Mark interface as down
    self.up = False
    self.log.activity("down")


  def _list_peers(self) -> Iterable[str]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "peers"],
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


  def _list_allowed_ips(self) -> Mapping[str, Iterable[ipaddress.IPv4Network]]:
    try:
      result = exec_command(
        ["wg", "show", self.config.intf.name, "allowed-ips"],
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


  def _list_allowed_ips_peer(self, peer: WireGuardInterfacePeerConfig) -> Iterable[ipaddress.IPv4Network]:
    ips = self._list_allowed_ips()
    return ips.get(peer.pubkey, set())


  def _update_allowed_ips(self,
      peer: WireGuardInterfacePeerConfig,
      allowed_ips: Iterable[ipaddress.IPv4Network]) -> None:
    # sort ips for tidyness in `wg show`'s output
    allowed_ips_str = sorted(map(str,allowed_ips))
    try:
      self.log.debug("setting allowed IPs for peer #{}", peer.id)
      exec_command(
        ["wg", "set", self.config.intf.name,
            "peer", peer.pubkey, "allowed-ips", ",".join(allowed_ips_str)])
      self.log.activity("allowed #{} = [{}]", peer.id, ', '.join(allowed_ips_str))
    except:
      raise WireGuardError(f"failed to set allowed peers on interface: {self.config.intf.name}")
    # allowed_ips_set = self._list_allowed_ips_peer(peer)
    # if allowed_ips ^ allowed_ips_set:
    #   # TODO(asorbini) do something with the knowledge that the
    #   # list of allowed peers contains unexpected addresses
    #   pass

  def allow_ips_for_peer(self, peer_i: int, addresses: Sequence[ipaddress.IPv4Network]) -> None:
    # addr = ipaddress.ip_network(addr)
    peer = self.config.peers[peer_i]
    allowed_ips_nic = set(self._list_allowed_ips_peer(peer))
    not_yet_allowed = set(addresses) - allowed_ips_nic
    if len(not_yet_allowed) > 0:
      allowed_ips = {*allowed_ips_nic, *not_yet_allowed}
      self._update_allowed_ips(peer, allowed_ips)
    # allowed_ips_nic = self._list_allowed_ips_peer(peer)
    # if addr not in allowed_ips_nic:
    #   raise WireGuardError(f"failed to allow address on interface: {self.config.intf.name}, {addr}")


  def disallow_ips_for_peer(self, peer_i: int, addresses: Sequence[ipaddress.IPv4Network]) -> None:
    peer = self.config.peers[peer_i]
    allowed_ips_nic = set(self._list_allowed_ips_peer(peer))
    allowed = allowed_ips_nic - set(addresses)
    if allowed != allowed_ips_nic:
      self._update_allowed_ips(peer, allowed)
    # allowed_ips_nic = self._list_allowed_ips_peer(peer)
    # if addr in allowed_ips_nic:
    #   raise WireGuardError(f"failed to disallow address on interface: {self.config.intf.name}, {addr}")


  # def peers(self) -> Sequence[str]:
  #   try:
  #     result = exec_command(
  #       ["wg", "show", self.config.intf.name, "peers"],
  #       capture_output=True)
  #   except:
  #     raise WireGuardError(f"failed to list interface peers: {self.config.intf.name}")
  #   return list(filter(lambda v: len(v) > 0, result.stdout.decode("utf-8").split("\n")))

  def _map_peer_ids(self, input: Mapping[str, object]) -> Mapping[str, Mapping[int, object]]:
    return{
      "peers": {
        peer.id: v
          for pubkey, v in input.items()
            for peer in [next((p for p in self.config.peers if p.pubkey == pubkey), None)]
              if peer is not None
      },
      "unknown_peers": {
        pubkey: v
          for pubkey, v in input.items()
            for peer in [next((p for p in self.config.peers if p.pubkey == pubkey), None)]
              if peer is None
      },
    }


  def stat(self) -> dict:
    peer_keys = self._list_peers()
    handshakes = self._list_handshakes()
    transfers = self._list_transfer()
    endpoints = self._list_endpoints()
    allowed_ips = self._list_allowed_ips()
    peers = {
      pubkey : {
        "last_handshake": str(handshake),
        "online": _check_handshake_online(handshake),
        "transfer": {
          "recv": transfers[pubkey]["recv"],
          "send": transfers[pubkey]["send"],
        },
        "endpoint": {
          "address": endpoints[pubkey]["address"],
          "port": endpoints[pubkey]["port"]
        },
        "allowed_ips": allowed_ips[pubkey],
      } for pubkey in peer_keys
          for handshake in [handshakes[pubkey]]
    }
    return {
      **self._map_peer_ids(peers),
      "up": ip_nic_is_up(self.config.intf.name),
      "created": ip_nic_exists(self.config.intf.name),
      # TODO(asorbini) read current interface address with "ip a s"
      "address": f"{self.config.intf.address}/{self.config.intf.netmask}"
    }
