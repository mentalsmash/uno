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
from typing import Sequence, Mapping, Iterable
import rti.connextdds as dds
from pathlib import Path

from .agent_service import AgentService, StopAgentServiceError

from ..core.log import Logger
log = Logger.sublogger("dds")

from ..registry.dds import UvnTopic


class DdsParticipant(AgentService):
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

  def __init__(self, **properties) -> None:
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
    super().__init__(**properties)


  def _start(self) -> None:
    # HACK set NDDSHOME so that the Connext Python API finds the license file
    import os
    os.environ["NDDSHOME"] = str(self.root)

    qos_provider = dds.QosProvider(str(self.agent.participant_xml_config))
    self.types = self._register_types(qos_provider)
    self._dp = qos_provider.create_participant_from_config(self.PARTICIPANT_PROFILE)
    (self.writers,
     self._writer_conditions) = self._create_writers(self._dp, self.agent.dds_topics["writers"])
    (self._readers,
     self._reader_conditions,
     self._data_conditions) = self._create_readers(self._dp, self.agent.dds_topics["readers"])
    self._user_conditions = [
      *(svc.updated_condition for svc in self.agent.services),
      # self.agent.peers_tester.result_available_condition,
    ]
    self._waitset = dds.WaitSet()
    for condition in (
        self.exit_condition,
        *self._writer_conditions.values(),
        *self._reader_conditions.values(),
        *self._data_conditions.values(),
        *self._user_conditions):
      self._waitset += condition
      self._waitset_attached.append(condition)

  def _stop(self, assert_stopped: bool) -> None:
    errors = []
    for condition in list(self._waitset_attached):
      if not condition:
        continue
      try:
        self._waitset -= condition
        self._waitset_attached.remove(condition)
      except Exception as e:
        if not assert_stopped:
          raise
        self.log.error("failed to detach DDS condition: {}", condition)
        self.log.exception(e)
        errors.append(e)
    self._waitset_attached = []
    if self._dp:
      try:
        self._dp.close()
      except Exception as e:
        if not assert_stopped:
          raise
        self.log.error("failed to stop DDS participan: {}", self._dp)
        self.log.exception(e)
        errors.append(e)
    self._waitset = None
    self.writers = {}
    self._writer_conditions = {}
    self._readers = {}
    self.types = {}
    self._reader_conditions = {}
    self._data_conditions = {}
    self._user_conditions = []
    self._dp = None
    if errors:
      raise StopAgentServiceError(errors)


  def wait(self) -> tuple[bool, Sequence[tuple[UvnTopic, dds.DataWriter]], Sequence[tuple[UvnTopic, dds.DataReader]], Sequence[tuple[UvnTopic, dds.DataReader, dds.QueryCondition]], Sequence[dds.Condition]]:
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
    active_user = []
    for cond in self._user_conditions:
      if cond not in active_conditions:
        continue
      cond.trigger_value = False
      active_user.append(cond)

    return (False, active_writers, active_readers, active_data, active_user)


  def _register_types(self, qos_provider: dds.QosProvider) -> Mapping[str, dds.StructType]:
    return {
      t: qos_provider.type(qos_provider.type_libraries[0], t)
        for t in self.REGISTERED_TYPES
    }

  def _create_writers(self, dp: dds.DomainParticipant, writer_topics: Sequence[UvnTopic]) -> tuple[Mapping[UvnTopic, dds.DataWriter], Mapping[UvnTopic, dds.StatusCondition]]:
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
      reader_topics: Mapping[UvnTopic, Mapping[str, str| Sequence[str]]]) -> tuple[Mapping[UvnTopic, dds.DataReader], Mapping[UvnTopic, dds.StatusCondition], Mapping[UvnTopic, dds.QueryCondition]]:
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

