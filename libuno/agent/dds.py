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
import threading
import itertools
from collections import namedtuple
import rti.connextdds as dds

from libuno.cfg import UvnDefaults
from libuno.exception import UvnException
from libuno.helpers import notify_if_present, ListenerDescriptor
from libuno.rs import RoutingServiceProcess

import libuno.log
logger = libuno.log.logger("uvn.agent.dds")


def format_qos_count(cur, change):
    sign = ""
    change_str = ""
    if change > 0:
        sign = "+"
    if change != 0:
        change_str = f" ({sign}{change})"
    return f"{cur}{change_str}"

class UvnParticipantListener:
    def on_participant_started(self, participant):
        logger.warning("on_participant_started: no listener")

    def on_participant_stopped(self, participant):
        logger.warning("on_participant_stopped: no listener")
    
    def on_participant_error(self, participant):
        logger.warning("on_participant_error: no listener")

    def on_writer_active(self, participant, writer_name, writer):
        status_mask = writer.status_changes
        pub_matched = writer.publication_matched_status
        liv_lost = writer.liveliness_lost_status
        qos_error = writer.offered_incompatible_qos_status
        if dds.StatusMask.publication_matched() in status_mask:
            logger.activity("[writer][{}]: publication matched {}",
                writer_name,
                format_qos_count(
                    pub_matched.current_count,
                    pub_matched.current_count_change))
            notify_if_present(self, f"_on_writer_matched_{writer_name}",
                participant, writer, pub_matched)
        if dds.StatusMask.liveliness_lost() in status_mask:
            logger.warning("[writer][{}]: liveliness lost {}",
                writer_name,
                format_qos_count(
                    liv_lost.total_count,
                    liv_lost.total_count_change))
            notify_if_present(self, f"_on_writer_liveliness_{writer_name}",
                participant, writer, liv_lost)
        if dds.StatusMask.requested_incompatible_qos() in status_mask:
            logger.error("[writer][{}]: incompatible qos detected",
                writer_name)
            notify_if_present(self, f"_on_writer_incompatible_qos_{writer_name}",
                participant, writer, qos_error)

    def on_reader_active(self, participant, reader_name, reader):
        status_mask = reader.status_changes
        sub_matched = reader.subscription_matched_status
        liv_changed = reader.liveliness_changed_status
        qos_error = reader.requested_incompatible_qos_status
        if dds.StatusMask.subscription_matched() in status_mask:
            logger.activity("[reader][{}]: subscription matched {}",
                reader_name,
                format_qos_count(
                    sub_matched.current_count,
                    sub_matched.current_count_change))
            notify_if_present(self, f"_on_reader_matched_{reader_name}",
                participant, reader, sub_matched)
        if dds.StatusMask.liveliness_changed() in status_mask:
            logger.activity("[reader][{}]: liveliness changed {}",
                reader_name,
                format_qos_count(
                    liv_changed.alive_count,
                    liv_changed.alive_count_change))
            notify_if_present(self, f"_on_reader_liveliness_{reader_name}",
                participant, reader, liv_changed)
        if dds.StatusMask.requested_incompatible_qos() in status_mask:
            logger.error("[reader][{}]: incompatible qos detected",
                reader_name)
            notify_if_present(self, f"_on_reader_incompatible_qos_{reader_name}",
                participant, reader, qos_error)

    def on_reader_data(self, participant, reader_name, reader, reader_condition):
        notify_if_present(self, f"_on_reader_data_{reader_name}",
            participant, reader, reader_condition)


class UvnParticipant(threading.Thread):

    listener = ListenerDescriptor(UvnParticipantListener)
    
    def __init__(self, basedir, registry, listener, profile_file, participant_config,
            writers={}, readers={}, types={}, queries={}, dds_peers=[],
            process_events=UvnDefaults["dds"]["process_events"],
            router_cfg=None):
        threading.Thread.__init__(self, daemon=True)
        # set thread name
        self.name = f"{participant_config}"
        self.basedir = basedir
        self.registry = registry
        self.listener = listener
        self._process_events = process_events
        self._participant_config = participant_config
        self._profile_file = str(profile_file)
        self._writers = dict(writers)
        # self._writers.update({
        #     "dns":          UvnDefaults["dds"]["writer"]["dns"]
        # })
        self._readers = dict(readers)
        self._readers.update({
            "cell_info":    UvnDefaults["dds"]["reader"]["cell_info"],
            "dns":          UvnDefaults["dds"]["reader"]["dns"]
        })
        self._types = dict(types)
        self._queries = dict(queries)
        self._dds_peers = set(dds_peers)
        self._types.update({
            "uvn_info": UvnDefaults["dds"]["types"]["uvn_info"],
            "cell_info": UvnDefaults["dds"]["types"]["cell_info"],
            "ip_address": UvnDefaults["dds"]["types"]["ip_address"],
            "deployment": UvnDefaults["dds"]["types"]["deployment"],
            "dns_db": UvnDefaults["dds"]["types"]["dns_db"],
            "dns_rec": UvnDefaults["dds"]["types"]["dns_rec"],
            "cell_site": UvnDefaults["dds"]["types"]["cell_site"],
            "cell_peer": UvnDefaults["dds"]["types"]["cell_peer"]
        })
        qos_provider = self._create_qos_provider(self._profile_file)
        self.participant = self._create_participant(qos_provider, self._participant_config)
        self.types = self._create_types(qos_provider, self._types)
        (self.writers,
         self.readers) = self._create_endpoints(
             self.participant, self._writers, self._readers)
        self.writer_conditions = self._create_writer_conditions(self.writers)
        self.reader_conditions = self._create_reader_conditions(self.readers)
        self.data_conditions = self._create_data_conditions(self.readers)
        self.exit_condition = dds.GuardCondition()
        self.waitset = dds.WaitSet()
        self.waitset += self.exit_condition
        for c in itertools.chain(
                    self.writer_conditions.values(),
                    self.reader_conditions.values(),
                    self.data_conditions.values()):
            self.waitset += c

        logger.activity("DDS types: {}", self._types)
        logger.activity("DDS readers: {}", self._readers)
        logger.activity("DDS writers: {}", self._writers)
        
        # Start routing service if requested
        # if router_cfg:
        #     self._rs = self._create_rs(*router_cfg)
        #     self._rs_cfg = router_cfg
        # else:
        #     self._rs = None
        
        # Keep track of "private" ports from discovered peers.
        # These are the address on which the peer can be reach within
        # (one or more of) its own private LANs attached to the UVN.
        # Each port is added as a peer, and once all cells are active,
        # and have a private port assigned, then routing service will
        # be disabled, to stop receiving recasted message from the
        # registry and other peers.
        # If a cell loses liveliness, then routing service will be
        # reenabled, until a connection can be re-established.
        # The agent keeps track of the livelness of remote peers by
        # monitoring the liveliness of a topic which is not shared
        # across the DDS routing service network.
        self._private_ports = {}

    def _create_qos_provider(self, profile_file):
        profile_file_url = "file://{}".format(profile_file)
        logger.debug("dds profile file: {}", profile_file_url)
        return dds.QosProvider(profile_file_url)
    
    def _create_participant(self, qos_provider, participant_config):
        logger.debug("dds domain participant: {}", participant_config)
        return qos_provider.create_participant_from_config(participant_config)

    @staticmethod
    def _create_entity(participant, ep_type, ep_key, ep_name, load_fn):
        logger.debug("dds {} [{}]: {}", ep_type, ep_key, ep_name)
        ep = load_fn(participant, ep_name)
        if ep is None:
            raise UvnException(f"unknown {ep_type}: {ep_name}")
        return ep

    def _create_writer(self, participant, writer_key, writer_name):
        return UvnParticipant._create_entity(
                    participant, "writer", writer_key, writer_name,
                    dds.DynamicData.DataWriter.find_by_name)

    def _create_reader(self, participant, reader_key, reader_name):
        return UvnParticipant._create_entity(
                    participant, "reader", reader_key, reader_name,
                    dds.DynamicData.DataReader.find_by_name)

    def _create_endpoints(self, participant, writers, readers):
        return (
            {k: self._create_writer(participant, k, w)
                for (k, w) in writers.items()},
            {k: self._create_reader(participant, k, r)
                for (k, r) in readers.items()}
        )
    
    def _create_type(self, qos_provider, type_key, type):
        logger.debug("dds type [{}]: {}", type_key, type)
        return qos_provider.type(qos_provider.type_libraries[0], type)

    def _create_types(self, qos_provider, types):
        return {t_name: self._create_type(qos_provider, t_name, t)
                    for (t_name, t) in types.items()}
    
    def _create_rs(self, cfg_name, cfg):
        return RoutingServiceProcess(cfg_name, cfg, basedir=self.basedir)

    def add_peers(self, peers):
        for p in peers:
            self.participant.add_peer(p)
            logger.activity("dds peer: {}", p)
    
    def _get_reader_default_data_state(self):
        return dds.DataState(dds.SampleState.not_read())

    def _get_reader_query_condition(self, reader_name, reader):
        query_rec = self._queries.get(reader_name, {})
        return (
            query_rec.get("str", None),
            query_rec.get("params", []),
            query_rec.get("data_state", self._get_reader_default_data_state())
        )
    
    def _create_reader_data_condition(self, reader_name, reader):
        query_str, query_args, data_state = self._get_reader_query_condition(reader_name, reader)
        if data_state is None:
            data_state = self._get_reader_default_data_state()
        if query_str is None:
            logger.debug("read condition [{}]: {}", reader_name, data_state)
            return dds.ReadCondition(reader, data_state)
        else:
            logger.debug("query condition [{}]: '{}' {}",
                reader_name, query_str, query_args)
            query = dds.Query(reader, query_str, query_args)
            query_condition = dds.QueryCondition(query, data_state)
            return query_condition
    
    def _create_writer_status_condition(self, writer_name, writer):
        status_condition = dds.StatusCondition(writer)
        status_condition.enabled_statuses = (
            dds.StatusMask.publication_matched() | 
            dds.StatusMask.liveliness_lost() |
            dds.StatusMask.offered_incompatible_qos()
        )
        return status_condition
        
    def _create_reader_status_condition(self, reader_name, reader):
        status_condition = dds.StatusCondition(reader)
        status_condition.enabled_statuses = (
            dds.StatusMask.subscription_matched() | 
            dds.StatusMask.liveliness_changed() |
            dds.StatusMask.requested_incompatible_qos()
        )
        return status_condition

    def _create_writer_conditions(self, writers):
        return {ep_name: self._create_writer_status_condition(ep_name, ep)
                    for ep_name, ep in writers.items()}
    
    def _create_reader_conditions(self, readers):
        return {ep_name: self._create_reader_status_condition(ep_name, ep)
                    for ep_name, ep in readers.items()}
    
    def _create_data_conditions(self, readers):
        return {ep_name: self._create_reader_data_condition(ep_name, ep)
                    for ep_name, ep in readers.items()}
    
    # def restart_rs(self):
    #     if self._rs:
    #         self.start_rs()
    #     else:
    #         logger.warning("[not restarted] routing service not running")

    def writer(self, name):
        return self.writers[name]

    def start(self):
        logger.info("enable DDS with peers: {}", self._dds_peers)
        self.participant.enable()
        self.add_peers(self._dds_peers)
        # if self._rs:
        #     self._rs.start()
        if self._process_events:
            logger.debug("starting participant thread...")
            threading.Thread.start(self)

    def stop(self):
        # if self._rs:
        #     self._rs.stop()
        if self._process_events:
            self.exit_condition.trigger_value = True
            logger.debug("waiting for participant thread to exit...")
            self.join()

    def wait_for_events(self):
        logger.trace("waiting for conditions...")
        active_conditions = self.waitset.wait()
        if self.exit_condition in active_conditions:
            logger.debug("signaled for exit")
        if len(active_conditions) == 0:
            logger.trace("wait timed out")
        return active_conditions
    
    def process_events(self, active_conditions):
        logger.trace("active conditions: {}", len(active_conditions))
        for ep_name, ep_cond in self.writer_conditions.items():
            if ep_cond in active_conditions:
                logger.debug("[writer][{}]: active", ep_name)
                writer = self.writers[ep_name]
                self.listener.on_writer_active(self, ep_name, writer)
        for ep_name, ep_cond in self.reader_conditions.items():
            if ep_cond in active_conditions:
                logger.debug("[reader][{}]: active", ep_name)
                reader = self.readers[ep_name]
                self.listener.on_reader_active(self, ep_name, reader)
        for ep_name, ep_cond in self.data_conditions.items():
            if ep_cond in active_conditions:
                logger.debug("[reader][{}]: data avaiable", ep_name)
                reader = self.readers[ep_name]
                self.listener.on_reader_data(self, ep_name,reader, ep_cond)

    
    # Listen to endpoints via a waitset and dispatch events to subclass
    def spin(self):
        active_conditions = self.wait_for_events()
        self.process_events(active_conditions)

    def run(self):
        logger.debug("participant thread starting...")
        self.listener.on_participant_started(self)
        logger.activity("participant thread started")
        while not self.exit_condition.trigger_value:
            try:
                self.spin()
            except Exception as e:
                logger.exception(e)
                logger.error("error in participant thread")
        logger.debug("participant thread exiting...")
        self.listener.on_participant_stopped(self)
        logger.activity("participant thread exited")

    def add_private_ports(self, cell_name, ports):
        existing_ports = self._private_ports.get(cell_name, set())
        existing_ports.update(ports)
        return self.assert_private_port(cell_name, existing_ports)

    def assert_private_port(self, cell_name, ports):
        existing_ports = self._private_ports.get(cell_name, set())
        if existing_ports == ports:
            # Nothing to do
            logger.warning("[agent][{}] private locators already enabled: {}", cell_name, ports)
            return
        elif existing_ports:
            # Remove the peer, so we won't try to contact it any longer.
            # This call doesn't actually stop communication with the participant
            # if it was already matched. ignore_peer() would do that, but there
            # is no way to reverse it, so we leave that for an explicit dispose()
            # (which means the private port has gone and won't come back again,
            # e.g. the subnetwork/ip address has been permanently changed)
            for p in existing_ports:
                self.participant.remove_peer(str(p))
                if p not in ports:
                    logger.activity("[agent][{}] private locator removed: {}", cell_name, p)
        if ports:
            for p in ports:
                self.participant.add_peer(str(p))
                logger.activity("[agent][{}] private locator enabled: {}", cell_name, p)
            self._private_ports[cell_name] = ports
        elif cell_name in self._private_ports:
            del self._private_ports[cell_name]

    def dispose_private_port(self, cell_name):
        ports = self._private_ports.get(cell_name)
        if ports:
            # Stop communication with the peer's stale locator
            # self.participant.ignore(port)
            del self._private_ports[cell_name]
            logger.warning("[agent][{}] private locators disposed: {}", cell_name, ports)

    # def stop_rs(self):
    #     if self._rs:
    #         self._rs.stop()
    #         self._rs = None
    
    # def start_rs(self):
    #     self.stop_rs()
    #     if self._rs_cfg:
    #         self._rs = self._create_rs(*self._rs_cfg)
    #         self._rs.start()