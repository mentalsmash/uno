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
import os
import rti.connextdds as dds
from pathlib import Path

from typing import Sequence, Mapping, Tuple, Union, Optional, Iterable, TYPE_CHECKING

from enum import Enum

from .render import Templates
from .log import Logger as log

class UvnTopic(Enum):
  UVN_ID = "uno/uvn"
  CELL_ID = "uno/cell"
  BACKBONE = "uno/config"


class DdsParticipantConfig:
  PARTICIPANT_PROFILE = "UnoParticipants::UvnAgent"

  def __init__(self,
      participant_xml_config: Path,
      writers: Iterable[UvnTopic] | None = None,
      readers: Mapping[UvnTopic, dict] | None = None,
      user_conditions: Iterable[dds.GuardCondition] | None = None) -> None:
    self.participant_xml_config = participant_xml_config
    self.writers = list(writers or [])
    self.readers = dict(readers or {})
    self.user_conditions = list(user_conditions or [])


def locate_rti_license(search_path: Iterable[Path] | None = None) -> Optional[Path]:
  searched = set()
  def _search_dir(root: Path):
    root = root.resolve()
    if root in searched:
      return None
    rti_license = root / "rti_license.dat"
    log.debug(f"[RTI-LICENSE] checking candidate: {rti_license}")
    if rti_license.is_file():
      log.debug(f"[RTI-LICENSE] found in {root}")
      return rti_license
    searched.add(root)
    return None

  for root in search_path:
    rti_license = _search_dir(root)
    if rti_license:
      return rti_license

  # Check if there is already a license in the specified directory
  rti_license_env = os.getenv("RTI_LICENSE_FILE")
  if rti_license_env:
    rti_license = Path(rti_license_env)
    if rti_license.is_file():
      log.warning(f"[RTI-LICENSE] detected RTI_LICENSE_FILE = {rti_license}")
      return rti_license

  default_path = [Path.cwd()]
  connext_home_env = os.getenv("CONNEXTDDS_DIR", os.getenv("NDDSHOME"))
  if connext_home_env:
    default_path.add(connext_home_env)
  for root in default_path:
    rti_license = _search_dir(root)
    if rti_license:
      return rti_license

  return None


class DdsParticipant:
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

  def __init__(self) -> None:
    self._qos_provider = None
    self._dp = None
    self._waitset = None
    self._waitset_attached = []
    self.writers = {}
    self._writer_conditions = {}
    self._readers = {}
    self.types = {}
    self._reader_conditions = {}
    self._data_conditions = {}
    self.exit_condition = dds.GuardCondition()
    self._user_conditions = []


  def start(self,config: DdsParticipantConfig) -> None:
    log.debug("[DDS] STARTING...")

    qos_provider = dds.QosProvider(str(config.participant_xml_config))
    self.types = self._register_types(qos_provider)

    self._dp = qos_provider.create_participant_from_config(DdsParticipantConfig.PARTICIPANT_PROFILE)

    self.writers, self._writer_conditions = self._create_writers(self._dp, config.writers)

    self._readers, self._reader_conditions, self._data_conditions = self._create_readers(self._dp, config.readers)

    self._user_conditions = config.user_conditions

    self._waitset = dds.WaitSet()

    for condition in (
        self.exit_condition,
        *self._writer_conditions.values(),
        *self._reader_conditions.values(),
        *self._data_conditions.values(),
        *self._user_conditions):
      self._waitset += condition
      self._waitset_attached.append(condition)
    
    log.activity("[DDS] started")


  def stop(self) -> None:
    log.debug("[DDS] STOP in process...")
    for condition in list(self._waitset_attached):
      if not condition:
        continue
      self._waitset -= condition
      self._waitset_attached.remove(condition)
    self._waitset_attached = []

    if self._dp:
      self._dp.close()

    self._waitset = None
    self.writers = {}
    self._writer_conditions = {}
    self._readers = {}
    self.types = {}
    self._reader_conditions = {}
    self._data_conditions = {}
    self._user_conditions = []
    self._dp = None
    log.activity("[DDS] stopped")


  def wait(self) -> Tuple[bool, Sequence[Tuple[UvnTopic, dds.DataWriter]], Sequence[Tuple[UvnTopic, dds.DataReader]], Sequence[Tuple[UvnTopic, dds.DataReader, dds.QueryCondition]], Sequence[dds.Condition]]:
    # log.debug("[DDS] waiting on waitset...")
    active_conditions = self._waitset.wait(dds.Duration(1))
    # log.debug(f"[DDS] waitset returned {len(active_conditions)} conditions")
    if len(active_conditions) == 0:
      return (False, [], [], [], [])
    assert(len(active_conditions) > 0)
    if self.exit_condition in active_conditions:
      self.exit_condition.trigger_value = False
      return (True, [], [], [], [])

    active_writers = [
      (topic, self.writers[topic])
      for topic, cond in self._writer_conditions.items()
        if cond in active_conditions
    ]
    active_readers = sorted(
      ((topic, self._readers[topic])
      for topic, cond in self._reader_conditions.items()
        if cond in active_conditions),
      key=lambda t: self.READERS_PROCESSING_ORDER[t[0]]
    )
    active_data = [
      (topic, self._readers[topic], self._data_conditions[topic])
      for topic, cond in self._data_conditions.items()
        if cond in active_conditions
    ]
    active_user = [
      cond for cond in self._user_conditions
        if cond in active_conditions
    ]

    return (False, active_writers, active_readers, active_data, active_user)


  def _register_types(self, qos_provider: dds.QosProvider) -> Mapping[str, dds.StructType]:
    return {
      t: qos_provider.type(qos_provider.type_libraries[0], t)
        for t in self.REGISTERED_TYPES
    }

  def _create_writers(self, dp: dds.DomainParticipant, writer_topics: Sequence[UvnTopic]) -> Tuple[Mapping[UvnTopic, dds.DataWriter], Mapping[UvnTopic, dds.StatusCondition]]:
    writers = {}
    conditions = {}
    for topic in writer_topics:
      writer = dds.DynamicData.DataWriter(
        dp.find_datawriter(self.WRITER_NAMES[topic])
      )
      if writer is None:
        raise RuntimeError("failed to lookup writer", topic)
      writers[topic] = writer
      status_condition = dds.StatusCondition(writer)
      status_condition.enabled_statuses = (
        dds.StatusMask.PUBLICATION_MATCHED | 
        dds.StatusMask.LIVELINESS_LOST |
        dds.StatusMask.OFFERED_INCOMPATIBLE_QOS
      )
      conditions[topic] = status_condition

    return (writers, conditions)


  def _create_readers(self,
      dp: dds.DomainParticipant,
      reader_topics: Mapping[UvnTopic, Mapping[str, Union[str, Sequence[str]]]]) -> Tuple[Mapping[UvnTopic, dds.DataReader], Mapping[UvnTopic, dds.StatusCondition], Mapping[UvnTopic, dds.QueryCondition]]:
    readers = {}
    status_conditions = {}
    data_conditions = {}
    data_state = dds.DataState(dds.SampleState.NOT_READ)

    for topic, topic_query in reader_topics.items():
      reader = dds.DynamicData.DataReader(
        dp.find_datareader(self.READER_NAMES[topic])
      )
      if reader is None:
        raise RuntimeError("failed to lookup reader", topic)
      readers[topic] = reader

      status_condition = dds.StatusCondition(reader)
      status_condition.enabled_statuses = (
        dds.StatusMask.SUBSCRIPTION_MATCHED | 
        dds.StatusMask.LIVELINESS_CHANGED |
        dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS
      )
      status_conditions[topic] = status_condition

      if topic_query:
        query = dds.Query(reader, topic_query["query"], topic_query["params"])
        data_condition = dds.QueryCondition(query, data_state)
      else:
        data_condition = dds.ReadCondition(reader, data_state)
      data_conditions[topic] = data_condition

    return (readers, status_conditions, data_conditions)

