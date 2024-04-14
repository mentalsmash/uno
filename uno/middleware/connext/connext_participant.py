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
from functools import cached_property
from importlib.resources import files, as_file

import rti.connextdds as dds

from uno.core.ip import ipv4_from_bytes, ipv4_to_bytes, ipv4_netmask_to_cidr
from uno.core.time import Timestamp
from uno.registry.topic import UvnTopic
from uno.core.log import Logger
from uno.registry.uvn import Uvn
from uno.registry.cell import Cell
from uno.registry.lan_descriptor import LanDescriptor
from uno.registry.key_id import KeyId
from uno.core.render import Templates

from uno.middleware import Participant

from .connext_condition import ConnextCondition
from .connext_handle import ConnextHandle

log = Logger.sublogger("connext")


class ConnextParticipant(Participant):
  PARTICIPANT_PROFILE = "UnoParticipants::UvnAgent"

  WRITER_NAMES = {
    UvnTopic.UVN_ID: "Publisher::UvnInfoWriter",
    UvnTopic.CELL_ID: "Publisher::CellInfoWriter",
    UvnTopic.BACKBONE: "Publisher::AgentConfigWriter",
  }

  READER_NAMES = {
    UvnTopic.UVN_ID: "Subscriber::UvnInfoReader",
    UvnTopic.CELL_ID: "Subscriber::CellInfoReader",
    UvnTopic.BACKBONE: "Subscriber::AgentConfigReader",
  }

  READERS_PROCESSING_ORDER = {
    UvnTopic.UVN_ID: 0,
    UvnTopic.CELL_ID: 1,
    UvnTopic.BACKBONE: 2,
  }

  TOPIC_TYPES = {
    UvnTopic.UVN_ID: "uno::UvnInfo",
    UvnTopic.CELL_ID: "uno::CellInfo",
    UvnTopic.BACKBONE: "uno::AgentConfig",
  }

  REGISTERED_TYPES = {
    *TOPIC_TYPES.values(),
    "uno::NetworkInfo",
    "uno::IpAddress",
  }

  def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._qos_provider = None
    self._dp = None
    self._waitset = None
    self._waitset_attached = []
    self._writer_conditions = {}
    self._reader_conditions = {}
    self._types = {}
    self._data_conditions = {}
    self._exit_condition = dds.GuardCondition()
    self._user_conditions = []
    self._readers = {}
    self._writers = {}

  @cached_property
  def rti_license(self) -> Path:
    return self.agent.root / "rti_license.dat"

  def uvn_info(self, uvn: Uvn, registry_id: str) -> None:
    sample = dds.DynamicData(self._types[self.TOPIC_TYPES[UvnTopic.UVN_ID]])
    sample["name"] = uvn.name
    sample["registry_id"] = registry_id
    writer = self._writers[UvnTopic.UVN_ID]
    writer.write(sample)

  def cell_agent_config(self, uvn: Uvn, cell_id: int, registry_id: str, package: Path) -> None:
    sample = dds.DynamicData(self._types[self.TOPIC_TYPES[UvnTopic.BACKBONE]])
    sample["cell.n"] = cell_id
    sample["cell.uvn"] = uvn.name
    sample["registry_id"] = registry_id
    with package.open("rb") as input:
      sample["package"] = input.read()
    writer = self._writers[UvnTopic.BACKBONE]
    writer.write(sample)

  def _lan_descriptor(self, net: LanDescriptor) -> dds.DynamicData:
    sample = dds.DynamicData(self._types["uno::NetworkInfo"])
    sample["nic"] = net.nic.name
    sample["subnet.address.value"] = ipv4_to_bytes(net.nic.subnet.network_address)
    sample["subnet.mask"] = ipv4_netmask_to_cidr(net.nic.subnet.netmask)
    sample["endpoint.value"] = ipv4_to_bytes(net.nic.address)
    sample["gw.value"] = ipv4_to_bytes(net.gw)
    return sample

  def cell_agent_status(
    self,
    uvn: Uvn,
    cell_id: int,
    registry_id: str,
    ts_start: Timestamp | None = None,
    lans: list[LanDescriptor] | None = None,
    known_networks: dict[LanDescriptor, bool] | None = None,
  ) -> None:
    cell = uvn.cells[cell_id]
    sample = dds.DynamicData(self._types[self.TOPIC_TYPES[UvnTopic.CELL_ID]])
    sample["id.n"] = cell.id
    sample["id.uvn"] = uvn.name
    sample["registry_id"] = registry_id
    sample["routed_networks"] = [self._lan_descriptor(lan) for lan in lans or []]
    sample["reachable_networks"] = [
      self._lan_descriptor(lan) for lan, reachable in known_networks.items() if reachable
    ]
    sample["unreachable_networks"] = [
      self._lan_descriptor(lan) for lan, reachable in known_networks.items() if not reachable
    ]
    if ts_start is not None:
      sample["ts_start"] = ts_start.from_epoch()

    writer = self._writers[UvnTopic.CELL_ID]
    writer.write(sample)

  def _parse_data(self, topic: UvnTopic, data: object) -> dict:
    """\
UVN_ID:
{
  uvn: str,
  registry_id: str
}

CELL_ID:
{
  uvn: str,
  cell: int,
  registry_id: str,
  routed_networks: list[LanDescriptor],
  known_networks: dict[LanDescriptor, bool]
  ts_start: str,
}

BACKBONE:
{
  uvn: str,
  cell: int,
  registry_id: str,
  package: bytes
}
"""
    if topic == UvnTopic.UVN_ID:
      return {
        "uvn": data["name"],
        "registry_id": data["registry_id"],
      }
    elif topic == UvnTopic.CELL_ID:

      def _site_to_descriptor(site):
        subnet_addr = ipv4_from_bytes(site["subnet.address.value"])
        subnet_mask = site["subnet.mask"]
        subnet = ipaddress.ip_network(f"{subnet_addr}/{subnet_mask}")
        endpoint = ipv4_from_bytes(site["endpoint.value"])
        gw = ipv4_from_bytes(site["gw.value"])
        nic = site["nic"]
        return {
          "nic": {
            "name": nic,
            "address": endpoint,
            "subnet": subnet,
          },
          "gw": gw,
        }

      def _site_to_lan_status(site, reachable):
        return (
          self.agent.new_child(LanDescriptor, _site_to_descriptor(site), save=False),
          reachable,
        )

      routed_networks = [_site_to_descriptor(s) for s in data["routed_networks"]]
      known_networks = dict(
        (
          *(_site_to_lan_status(s, False) for s in data["unreachable_networks"]),
          *(_site_to_lan_status(s, True) for s in data["reachable_networks"]),
        )
      )

      return {
        "uvn": data["id.uvn"],
        "cell": data["id.n"],
        "registry_id": data["registry_id"],
        "routed_networks": routed_networks,
        "known_networks": known_networks,
        "ts_start": data["ts_start"],
      }
    elif topic == UvnTopic.BACKBONE:
      return {
        "uvn": data["cell.uvn"],
        "cell": data["cell.n"],
        "registry_id": data["registry_id"],
        "package": data["package"],
      }

  @cached_property
  def participant_xml_config(self) -> Path:
    config = self.root / "uno_qos_profiles.xml"
    if isinstance(self.owner, Uvn):
      self._generate_dds_xml_config_uvn(config)
    elif isinstance(self.owner, Cell):
      self._generate_dds_xml_config_cell(config)
    return config

  def _generate_dds_xml_config_uvn(self, output: Path) -> None:
    key_id = KeyId.from_uvn(self.registry.uvn)
    from . import data

    with as_file(files(data).joinpath("uno.xml")) as tmplt_str:
      tmplt = Templates.compile(tmplt_str.read_text())
    Templates.generate(
      output,
      tmplt,
      {
        "uvn": self.registry.uvn,
        "cell": None,
        "initial_peers": [f"[0]@{p}" for p in self.initial_peers],
        "timing": self.registry.uvn.settings.timing_profile,
        "license_file": self.rti_license.read_text(),
        "ca_cert": self.registry.id_db.backend.ca.cert,
        "perm_ca_cert": self.registry.id_db.backend.perm_ca.cert,
        "cert": self.registry.id_db.backend.cert(key_id),
        "key": self.registry.id_db.backend.key(key_id),
        "governance": self.registry.id_db.backend.governance,
        "permissions": self.registry.id_db.backend.permissions(key_id),
        "enable_dds_security": self.registry.uvn.settings.enable_dds_security,
        "domain": self.registry.uvn.settings.dds_domain,
        "domain_tag": self.registry.uvn.name,
        "rti_license": self.registry.rti_license,
      },
    )

  def _generate_dds_xml_config_cell(self, output: Path) -> None:
    key_id = KeyId.from_uvn(self.owner)
    from . import data

    with as_file(files(data).joinpath("uno.xml")) as tmplt_str:
      tmplt = Templates.compile(tmplt_str.read_text())
    Templates.generate(
      output,
      tmplt,
      {
        "uvn": self.registry.uvn,
        "cell": self.owner,
        "initial_peers": [f"[0]@{p}" for p in self.initial_peers],
        "timing": self.registry.uvn.settings.timing_profile,
        "license_file": self.rti_license.read_text(),
        "ca_cert": self.registry.id_db.backend.ca.cert,
        "perm_ca_cert": self.registry.id_db.backend.perm_ca.cert,
        "cert": self.registry.id_db.backend.cert(key_id),
        "key": self.registry.id_db.backend.key(key_id),
        "governance": self.registry.id_db.backend.governance,
        "permissions": self.registry.id_db.backend.permissions(key_id),
        "enable_dds_security": self.registry.uvn.settings.enable_dds_security,
        "domain": self.registry.uvn.settings.dds_domain,
        "domain_tag": self.registry.uvn.name,
        "rti_license": self.rti_license,
      },
    )

  def start(self) -> None:
    # HACK set NDDSHOME so that the Connext Python API finds the license file
    import os

    os.environ["NDDSHOME"] = str(self.root)
    log.activity("NDDSHOME: {}", os.environ["NDDSHOME"])

    qos_provider = dds.QosProvider(str(self.participant_xml_config))

    self._types = {
      t: qos_provider.type(qos_provider.type_libraries[0], t) for t in self.REGISTERED_TYPES
    }
    self._dp = qos_provider.create_participant_from_config(self.PARTICIPANT_PROFILE)

    writers = {}
    writer_conditions = {}
    for topic in self.topics["writers"]:
      writer = dds.DynamicData.DataWriter(self._dp.find_datawriter(self.WRITER_NAMES[topic]))
      if writer is None:
        raise RuntimeError("failed to lookup writer", topic)
      writers[topic] = writer
      status_condition = dds.StatusCondition(writer)
      status_condition.enabled_statuses = (
        dds.StatusMask.PUBLICATION_MATCHED
        | dds.StatusMask.LIVELINESS_LOST
        | dds.StatusMask.OFFERED_INCOMPATIBLE_QOS
      )
      writer_conditions[topic] = status_condition
    self._writers = writers
    self._writer_conditions = writer_conditions

    readers = {}
    reader_conditions = {}
    data_conditions = {}
    data_state = dds.DataState(dds.SampleState.NOT_READ)
    for topic in self.topics["readers"]:
      reader = dds.DynamicData.DataReader(self._dp.find_datareader(self.READER_NAMES[topic]))
      if reader is None:
        raise RuntimeError("failed to lookup reader", topic)
      readers[topic] = reader

      status_condition = dds.StatusCondition(reader)
      status_condition.enabled_statuses = (
        dds.StatusMask.SUBSCRIPTION_MATCHED
        | dds.StatusMask.LIVELINESS_CHANGED
        | dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS
      )
      reader_conditions[topic] = status_condition
      data_conditions[topic] = dds.ReadCondition(reader, data_state)
    self._reader_conditions = reader_conditions
    self._data_conditions = data_conditions
    self._readers = readers
    self._user_conditions = [svc.updated_condition for svc in self.agent.services]
    self._waitset = dds.WaitSet()
    for condition in (
      self._exit_condition,
      *self._writer_conditions.values(),
      *self._reader_conditions.values(),
      *self._data_conditions.values(),
      *(c._condition for c in self._user_conditions),
    ):
      self._waitset += condition
      self._waitset_attached.append(condition)

  def stop(self) -> None:
    for condition in list(self._waitset_attached):
      self._waitset -= condition
      self._waitset_attached.remove(condition)
    self._waitset_attached = []
    if self._dp:
      self._dp.close()
    self._waitset = None
    self._writers = {}
    self._readers = {}
    self._writer_conditions = {}
    self._types = {}
    self._reader_conditions = {}
    self._data_conditions = {}
    self._user_conditions = []
    self._dp = None

  def spin(self) -> bool:
    done, active_writers, active_readers, active_data, active_user = self._wait()
    if done:
      return True

    for topic, writer in active_writers:
      # Read and reset status flags
      # We don't do anything with writer events for now
      status_mask = writer.status_changes
      _ = writer.publication_matched_status
      _ = writer.liveliness_lost_status
      _ = writer.offered_incompatible_qos_status

    for topic, reader in active_readers:
      # Read and reset status flags
      status_mask = reader.status_changes
      _ = reader.subscription_matched_status
      _ = reader.liveliness_changed_status
      _ = reader.requested_incompatible_qos_status

      if (
        dds.StatusMask.LIVELINESS_CHANGED in status_mask
        or dds.StatusMask.SUBSCRIPTION_MATCHED in status_mask
      ):
        online_writers = [ConnextHandle(ih_dw) for ih_dw in reader.matched_publications]
        self.agent.on_remote_writers_status(topic, online_writers)

    for topic, reader, query_cond in active_data:
      for s in reader.select().condition(query_cond).take():
        if s.info.valid:
          data = self._parse_data(topic, s.data)
          self.agent.on_data(
            topic,
            data,
            instance=ConnextHandle(s.info.instance_handle),
            writer=ConnextHandle(s.info.publication_handle),
          )
        elif (
          s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_DISPOSED
          or s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_NO_WRITERS
        ):
          self.agent.on_instance_offline(topic, ConnextHandle(s.info.instance_handle))

    for user_cond in active_user:
      self.agent.on_condition_active(user_cond)

    return False

  def _wait(
    self,
  ) -> tuple[
    bool,
    list[tuple[UvnTopic, dds.DataWriter]],
    list[tuple[UvnTopic, dds.DataReader]],
    list[tuple[UvnTopic, dds.DataReader, dds.ReadCondition]],
    list[ConnextCondition],
  ]:
    active_conditions = self._waitset.wait(dds.Duration(1))
    if len(active_conditions) == 0:
      return (False, [], [], [], [])
    assert len(active_conditions) > 0
    if self._exit_condition in active_conditions:
      self._exit_condition.trigger_value = False
      return (True, [], [], [], [])

    active_writers = [
      (topic, self._writers[topic])
      for topic, cond in self._writer_conditions.items()
      if cond in active_conditions
    ]
    active_readers = sorted(
      (
        (topic, self._readers[topic])
        for topic, cond in self._reader_conditions.items()
        if cond in active_conditions
      ),
      key=lambda t: self.READERS_PROCESSING_ORDER[t[0]],
    )
    active_data = [
      (topic, self._readers[topic], self._data_conditions[topic])
      for topic, cond in self._data_conditions.items()
      if cond in active_conditions
    ]
    active_user = []
    for cond in self._user_conditions:
      if cond._condition not in active_conditions:
        continue
      cond.trigger_value = False
      active_user.append(cond)
    return (False, active_writers, active_readers, active_data, active_user)
