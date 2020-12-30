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
import random

import libuno.log
from libuno.cfg import UvnDefaults
from libuno.helpers import Timestamp, ListenerDescriptor

from libuno.exec import exec_command

logger = libuno.log.logger("uvn.ping")

class PeerConnectionsListener():

    def on_peer_tester_check_enabled(self, tester, record):
        if "windows" in record["tags"]:
            logger.debug("Windows record not tested: {}", record["name"])
            return False
        if "noping" in record["tags"]:
            logger.debug("unpingable record not tested: {}", record["name"])
            return False
        return True

    def on_peer_connection_available(self, tester, peer, peer_i, peer_max):
        logger.activity("[test] {}/{} OK: {}/{} {}",
            peer_i, peer_max,
            peer["name"], peer["address"], peer["tags"])

    def on_peer_connection_unavailable(self, tester, peer, peer_i, peer_max):
        logger.activity("[test] {}/{} FAILED: {}/{} {}",
            peer_i, peer_max,
            peer["name"], peer["address"], peer["tags"])
    
    def on_peer_test_begin(self, tester, peers):
        pass

    def on_peer_test_result(self,
            tester,
            peers,
            ok,
            unavail_peers,
            gone_peers,
            now_unavail,
            now_avail,
            new_avail,
            new_unavail):
        if gone_peers:
            logger.info("[test][result] {} removed: {}", len(gone_peers), gone_peers)
        
        if now_unavail:
            logger.warning("[test][result] {} now FAILED: {}", len(now_unavail), now_unavail)
        
        if now_avail:
            logger.warning("[test][result] {} now OK: {}", len(now_avail), now_avail)
        
        if new_unavail:
            logger.warning("[test][result] {} {} FAILED: {}",
                len(new_unavail),
                "have" if len(new_unavail) > 1 else "has",
                new_unavail)
        if new_avail:
            logger.info("[test][result] {} {} OK: {}",
                len(new_avail),
                "are" if len(new_avail) > 1 else "is",
                new_avail)
        if ok:
            logger.info("[test][result] {} OK", len(peers))
        else:
            logger.warning("[test][result] {}/{} FAILED: {}",
                len(unavail_peers), len(peers), unavail_peers)

class PeerConnectionsTester(threading.Thread):
    
    listener = ListenerDescriptor(PeerConnectionsListener)

    def __init__(self, peers, listener=None,
            run_on_start=False,
            check_period_wait=UvnDefaults["ping"]["period_wait"],
            ping_count=UvnDefaults["ping"]["count"],
            max_failed=UvnDefaults["ping"]["max_failed"]):
        threading.Thread.__init__(self, daemon=True)
        # set thread name
        self.name = "connection-tester"
        self.listener = listener
        self._check_period_wait = check_period_wait
        self._ping_len = 3
        self._ping_count = 1
        self._ping_count_max = ping_count
        self._max_failed = max_failed
        self._failed_count = 0
        self._exit = False
        self._peers = []
        self._peer_connection_status = {}
        self._run_peers = None
        self._queued = False
        self._peers_lock = threading.RLock()
        self._sem_test = threading.Semaphore()
        self._sem_test.acquire()
        self._sem_exit = threading.BoundedSemaphore()
        self._sem_exit.acquire()
        self.set_peers(peers)
        self._result_peers = None
        self._result_avail = None
        self._result_unavail = None
        if run_on_start:
            self.perform_test()
    
    def perform_test(self):
        with self._peers_lock:
            if self._queued:
                logger.debug("already queued")
                return
            self._queued = True
        self._sem_test.release()

    @staticmethod
    def _peer_status(peer):
        return {
            "name": peer.get("name", peer["address"]),
            "address": peer["address"],
            "cell": peer.get("cell"),
            "available": False,
            "ts_last_check": 0,
            "tags": set(peer.get("tags",[]))
        }

    def _update_run_peers(self):
        self._run_peers = list(self._peer_connection_status.keys())
    
    def set_peers(self, peers):
        # TODO protect change with a mutex
        with self._peers_lock:
            self._peers = peers
            self._peer_connection_status = {p["name"]: PeerConnectionsTester._peer_status(p)
                                                for p in peers}
            self._update_run_peers()

    def add_peer(self, name, address, tags=None, cell=None):
        with self._peers_lock:
            p_rec = self._peer_connection_status.get(name)
            updated = False
            if p_rec is not None:
                if p_rec["address"] != address:
                    p_rec["address"] = address
                    updated = True
                if p_rec["cell"] != cell:
                    p_rec["cell"] = cell
                    updated = True
                current_tags = p_rec["tags"]
                p_rec["tags"] = set(tags)
                changed_tags = current_tags ^ p_rec["tags"]
                updated = updated or len(changed_tags) > 0
                if updated:
                    logger.debug("updated peer: {}", p_rec["name"])
            else:
                if tags is None:
                    tags = []
                peer = {
                    "name": name,
                    "address": address,
                    "tags": tags,
                    "cell": cell
                }
                p_rec = PeerConnectionsTester._peer_status(peer)
                self._peers.append(peer)
                self._peer_connection_status[name] = p_rec
                logger.debug("added peer: {}", p_rec["name"])
                updated = True
            if updated:
                self._update_run_peers()
                self.perform_test()
        
    def _remove_peer_record(self, p_rec):
        del self._peer_connection_status[p_rec["name"]]
        peer = next(filter(lambda p: p["name"] == p_rec["name"], self._peers))
        self._peers.remove(peer)
        logger.debug("removed peer: {}", p_rec["name"])
        self._update_run_peers()
    
    def remove_peer_by_name(self, name):
        with self._peers_lock:
            p_rec = self._peer_connection_status.get(name)
            if p_rec is not None:
                self._remove_peer_record(p_rec)

    def remove_peer_by_address(self, address):
        with self._peers_lock:
            p_rec = next(filter(lambda p: p["address"] == address,
                        self._peer_connection_status.values()), None)
            if p_rec is not None:
                self._remove_peer_record(p_rec)
    
    def _update_and_notify(self, peer_i, peer_max, name, available, ts_check):
        with self._peers_lock:
            p_rec = self._peer_connection_status.get(name)
            if p_rec is None:
                # peer must have been removed, ignore notification
                return
            was_available = p_rec["available"]
            p_rec["available"] = available
            p_rec["ts_last_check"] = ts_check
            if not was_available and available:
                self.listener.on_peer_connection_available(
                    tester=self, peer=p_rec, peer_i=peer_i, peer_max=peer_max)
            elif was_available and not available:
                self.listener.on_peer_connection_unavailable(
                    tester=self, peer=p_rec, peer_i=peer_i, peer_max=peer_max)
    
    def _test_result(self, peers, unavail_peers):
        ok = len(unavail_peers) == 0
        peers = set(peers)
        avail_peers = peers - unavail_peers

        if self._result_peers is not None:
            # peers that have been removed from tester since last notification
            new_peers = peers - self._result_peers
            gone_peers = self._result_peers - peers
            # peers which were available and aren't now
            now_unavail = self._result_avail & unavail_peers
            now_unavail -= gone_peers
            # peers which have since become available
            now_avail = self._result_unavail & avail_peers
            now_avail -= gone_peers
            # Newly tested unavailable hosts
            new_unavail = unavail_peers & new_peers
            # Newly tested available hosts
            new_avail = avail_peers & new_peers
        else:
            gone_peers = set()
            now_unavail = set()
            now_avail = set()
            new_unavail = unavail_peers
            new_avail = avail_peers

        self._result_peers = peers
        self._result_avail = avail_peers
        self._result_unavail = unavail_peers
        
        self.listener.on_peer_test_result(
            tester=self,
            peers=peers,
            ok=ok,
            unavail_peers=unavail_peers,
            gone_peers=gone_peers,
            now_unavail=now_unavail,
            now_avail=now_avail,
            new_avail=new_avail,
            new_unavail=new_unavail)

    def _ping_test(self, peer_count, peer_i, p_name, p_rec, unavail_peers):
        ts_check = Timestamp.now()
        result = exec_command(
            ["ping", "-w", str(self._ping_len),"-c", str(self._ping_count), str(p_rec["address"])],
            fail_msg="failed to ping peer: {} [{}]".format(p_name, p_rec["address"]),
            # don't throw an exception on error
            noexcept=True,
            # don't print any error message
            quiet=True)
        peer_ok = result.returncode == 0
        if not peer_ok:
            unavail_peers.add(p_name)
        self._update_and_notify(peer_i, peer_count, p_name, peer_ok, ts_check)
    
    def _tracepath_test(self, peer_count, peer_i, p_name, p_rec):
        ts_check = Timestamp.now()
        result = exec_command(
            ["tracepath", "-c", str(self._ping_count), str(p_rec["address"])],
            fail_msg="failed to ping peer: {} [{}]".format(p_name, p_rec["address"]),
            # don't throw an exception on error
            noexcept=True,
            # don't print any error message
            quiet=True)
        peer_ok = result.returncode == 0
        if not peer_ok:
            unavail_peers.add(p_name)
        self._update_and_notify(peer_i, peer_count, p_name, peer_ok, ts_check)

    def _run_test(self, peers, unavail_peers):
        peer_i = 0
        peer_count = len(peers)
        logger.info("[test][start] {} peers", peer_count)
        logger.debug("[test][peers]{}", peers)
        self.listener.on_peer_test_begin(tester=self, peers=peers)
        while not self._exit:
            if peer_i < peer_count:
                p_name = peers[peer_i]
                peer_i += 1
                with self._peers_lock:
                    p_rec = self._peer_connection_status.get(p_name)
                    if not p_rec:
                        logger.debug("ignored removed peer: {}", p_name)
                        continue
            else:
                logger.trace("test complete")
                self._test_result(peers, unavail_peers)
                break
                
            self._ping_test(peer_count, peer_i, p_name, p_rec, unavail_peers)

    def run(self):
        try:
            complete = False
            while not (complete or self._exit):
                logger.debug("waiting for next test request...")
                self._sem_test.acquire()

                peers = []
                unavail_peers = set()
                peer_i = 0
                wait_period = 0

                with self._peers_lock:
                    if self._queued:
                        self._queued = False
                        peers = list(filter(lambda p:
                                    self.listener.on_peer_tester_check_enabled(
                                        self, self._peer_connection_status.get(p)),
                                    self._run_peers))
                        disabled_peers = set(self._run_peers) - set(peers)
                        if disabled_peers:
                            logger.info("[test] skipped: {}", disabled_peers)
                        if not peers:
                            logger.warning("[test] all peers disabled")
                            continue
                if peers:
                    self._run_test(peers, unavail_peers)

                if unavail_peers:
                    if self._failed_count >= self._max_failed:
                        logger.warning("pausing tests after {} failures", self._failed_count)
                    else:
                        self._failed_count += 1
                        # trigger another test but wait a bit before running it
                        self.perform_test()
                        # self._ping_count = self._ping_count_max
                        wait_period = random.randint(
                            self._check_period_wait[0], self._check_period_wait[1])
                        logger.warning("[failed][{}/{}] next check in {}s",
                            self._failed_count, self._max_failed, wait_period)
                else:
                    self._failed_count = 0

                if wait_period:
                    logger.debug("waiting {}s before next test...", wait_period)
                    complete = self._sem_exit.acquire(timeout=wait_period)
                else:
                    complete = self._sem_exit.acquire(blocking=False)
        except Exception as e:
            logger.exception(e)
            logger.error("unexpected error in connections tester")
    
    def start(self):
        self._exit = False
        threading.Thread.start(self)

    def stop(self):
        if not self.is_alive():
            return
        self._exit = True
        self._sem_exit.release()
        self._sem_test.release()
        self.join()
