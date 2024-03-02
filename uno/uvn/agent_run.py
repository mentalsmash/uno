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
import rti.connextdds as dds
from typing import Sequence, Optional, Callable
import ipaddress

from .ip import (
  ipv4_from_bytes,
  NicDescriptor,
  LanDescriptor,
)
from .dds import DdsParticipant, UvnTopic
from .peer import UvnPeersList, UvnPeerStatus, UvnPeer
from .time import Timestamp

from .log import Logger as log


def _on_writer_status_active(
    peers: UvnPeersList,
    topic: UvnTopic,
    writer: dds.DataWriter) -> None:
  # Read and reset status flags
  # We don't do anything with writer events for now
  status_mask = writer.status_changes
  pub_matched = writer.publication_matched_status
  liv_lost = writer.liveliness_lost_status
  qos_error = writer.offered_incompatible_qos_status



def _on_reader_status_active(
    peers: UvnPeersList,
    topic: UvnTopic,
    reader: dds.DataReader) -> None:
  # Read and reset status flags
  status_mask = reader.status_changes
  sub_matched = reader.subscription_matched_status
  liv_changed = reader.liveliness_changed_status
  qos_error = reader.requested_incompatible_qos_status

  if (topic in (UvnTopic.CELL_ID, UvnTopic.UVN_ID)
      and (dds.StatusMask.LIVELINESS_CHANGED in status_mask
      or dds.StatusMask.SUBSCRIPTION_MATCHED in status_mask)):
    # Check go through the list of matched writers and assert
    # their associated peer statuses
    matched_writers = reader.matched_publications
    matched_peers = []
    if topic == UvnTopic.CELL_ID:
      matched_peers = [p for p in peers if p.ih_dw and p.ih_dw in matched_writers]
    elif topic == UvnTopic.UVN_ID:
      root_peer = peers[0]
      matched_peers = [root_peer] if root_peer.ih_dw and root_peer.ih_dw in matched_writers else []
    
    # Mark peers that we already discovered in the past as active again
    # They had transitioned because of a received sample, but the sample
    # might not be sent again. Don't transition peers we've never seen.
    if matched_peers:
      log.activity(f"[AGENT] marking {len(matched_peers)} peers on matched publications: {list(map(str, matched_peers))}")
      peers.update_all(
        peers=matched_peers,
        query=lambda p: p.status == UvnPeerStatus.OFFLINE,
        status=UvnPeerStatus.ONLINE)
  


def _on_cell_info_data(
    peers: UvnPeersList,
    info: dds.SampleInfo,
    sample: dds.DynamicData) -> UvnPeer|None:
  peer_uvn = sample["id.uvn.name"]
  if peer_uvn != peers.uvn_id.name:
    log.debug(f"[AGENT] IGNORING update from foreign agent:"
              f" uvn={sample['id.uvn.name']}", f"cell={sample['id.name']}")
    return None

  peer_cell_name = sample["id.name"]
  peer_cell = next((c for c in peers.uvn_id.cells.values() if c.name == peer_cell_name), None)
  if peer_cell is None:
    # Ignore sample from unknown cell
    log.warning(f"[AGENT] IGNORING update from unknown agent:"
                f" uvn={sample['id.uvn.name']}", f"cell={sample['id.name']}")
    return None

  def _site_to_descriptor(site):
    subnet_addr = ipv4_from_bytes(site["subnet.address.value"])
    subnet_mask = site["subnet.mask"]
    subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
    endpoint = ipv4_from_bytes(site["endpoint.value"])
    gw = ipv4_from_bytes(site["gw.value"])
    nic = site["nic"]
    return LanDescriptor(
      nic=NicDescriptor(
        name=nic,
        address=endpoint,
        subnet=subnet,
        netmask=subnet_mask),
      gw=gw)
  peer_routed_sites = [_site_to_descriptor(s) for s in sample["routed_sites"]]
  peer_reachable_sites = [_site_to_descriptor(s) for s in sample["reachable_sites"]]
  backbone_peers = [p["n"] for p in sample["peers"]]

  log.activity(f"[AGENT] cell info UPDATE: {peer_cell}")
  peer = peers[peer_cell.id]
  updated = peers.update_peer(peer,
    deployment_id=sample["deployment_id"],
    registry_id=sample["registry_id"],
    root_vpn_id=sample["root_vpn_id"],
    particles_vpn_id=sample["particles_vpn_id"],
    backbone_vpn_ids=sample["backbone_vpn_ids"],
    status=UvnPeerStatus.ONLINE,
    routed_sites=peer_routed_sites,
    reachable_sites=peer_reachable_sites,
    backbone_peers=backbone_peers,
    ih=info.instance_handle,
    ih_dw=info.publication_handle)
  return peer if updated else None


def _on_uvn_info_data(
    peers: UvnPeersList,
    info: dds.SampleInfo,
    sample: dds.DynamicData) -> UvnPeer | None:
  peer_uvn = sample["id.name"]
  if peer_uvn != peers.uvn_id.name:
    log.warning(f"[AGENT] IGNORING update for foreign UVN: uvn={sample['id.name']}")
    return None

  log.debug(f"[AGENT] uvn info UPDATE: {peers.uvn_id}")
  peer = peers[0]
  updated = peers.update_peer(peer,
    uvn_id=peers.uvn_id,
    deployment_id=sample["deployment_id"],
    registry_id=sample["registry_id"],
    status=UvnPeerStatus.ONLINE,
    ih=info.instance_handle,
    ih_dw=info.publication_handle)
  return peer if updated else None


def _on_reader_data_available(
    peers: UvnPeersList,
    topic: UvnTopic,
    reader: dds.DataReader,
    condition: dds.QueryCondition | dds.ReadCondition,
    on_reader_data: Optional[Callable[[UvnTopic, dds.DataReader, dds.SampleInfo, dds.DynamicData], Sequence[UvnPeer]]]=None,
    on_reader_offline: Optional[Callable[[UvnTopic, dds.DataReader, dds.SampleInfo], Sequence[UvnPeer]]]=None,
    on_peer_updated: Callable[[UvnPeer], None]|None=None) -> None:
  
  for s in reader.select().condition(condition).read():
    if s.info.valid:
      if topic == UvnTopic.CELL_ID:
        updated_peer = _on_cell_info_data(peers, s.info, s.data)
        if updated_peer and on_peer_updated:
          on_peer_updated(updated_peer)
      elif topic == UvnTopic.UVN_ID:
        updated_peer = _on_uvn_info_data(peers, s.info, s.data)
        if updated_peer and on_peer_updated:
          on_peer_updated(updated_peer)
      elif on_reader_data:
        on_reader_data(topic, reader, s.info, s.data)
    elif (s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_DISPOSED
          or s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_NO_WRITERS):
      if topic in (UvnTopic.CELL_ID, UvnTopic.UVN_ID):
        try:
          peer = peers[s.info.instance_handle]
        except KeyError:
          continue
        log.debug(f"[AGENT] peer writer offline: {peer}")
        updated = peers.update_peer(peer,
          status=UvnPeerStatus.OFFLINE)
        if updated and on_peer_updated:
          on_peer_updated(peer)
      elif on_reader_offline:
        on_reader_offline(topic, reader, s.info)


def spin(
    dp: DdsParticipant,
    peers: UvnPeersList,
    until: Optional[Callable[[], bool]]=None,
    max_spin_time: Optional[int]=None,
    **spin_listeners) -> None:
  on_reader_data = spin_listeners.get("on_reader_data")
  on_reader_offline = spin_listeners.get("on_reader_offline")
  on_user_condition = spin_listeners.get("on_user_condition")
  on_peer_updated = spin_listeners.get("on_peer_updated")
  on_spin = spin_listeners.get("on_spin")


  spin_start = Timestamp.now()
  log.debug(f"starting to spin on {spin_start}")
  while True:
    done, active_writers, active_readers, active_data, extra_conds = dp.wait()
    
    spin_time = Timestamp.now()
    spin_length = spin_time.subtract(spin_start)
    timedout = max_spin_time is not None and spin_length >= max_spin_time
    if timedout:
      log.debug(f"time out after {max_spin_time} sec")
      # If there is an exit condition, throw an error, since we
      # didn't reach it.
      if until:
        raise RuntimeError("timed out", max_spin_time)

    done = done or timedout

    if done:
      log.debug("done spinning")
      break

    for topic, writer in active_writers:
      _on_writer_status_active(peers, topic, writer)


    for topic, reader in active_readers:
      _on_reader_status_active(peers, topic, reader)


    for topic, reader, query_cond in active_data:
      _on_reader_data_available(peers,
        topic=topic,
        reader=reader,
        condition=query_cond,
        on_reader_data=on_reader_data,
        on_reader_offline=on_reader_offline,
        on_peer_updated=on_peer_updated)

    for active_cond in extra_conds:
      active_cond.trigger_value = False
      if on_user_condition:
        on_user_condition(active_cond)

    # Test custom exit condition after event processing
    if until and until():
      log.debug("exit condition reached")
      break

    if on_spin:
      on_spin(
        ts_start=spin_start,
        ts_now=spin_time,
        spin_len=spin_length)
