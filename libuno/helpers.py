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
"""A module for different helpers which are generic enough to be reused
across libuno"""

import re
import time
import datetime
import signal
import sys
import collections

from libuno.exception import UvnException
from libuno.yml import YamlSerializer, repr_yml, repr_py

class Timestamp:

    epoch = datetime.datetime.utcfromtimestamp(0)

    default_format = "%Y%m%d-%H%M%S"

    def __init__(self, ts):
        self._ts = ts
    
    def subtract(self, ts):
        self_ts = time.mktime(self._ts)
        if (isinstance(ts, Timestamp)):
            other_ts = time.mktime(ts._ts)
        else:
            other_ts = time.mktime(ts)
        return self_ts - other_ts
    
    def format(self, fmt=None):
        if (fmt is None):
            fmt = Timestamp.default_format
        return time.strftime(fmt, self._ts)
    

    def millis(self):
        ts = datetime.datetime.fromtimestamp(time.mktime(self._ts))
        return (ts - Timestamp.epoch).total_seconds() * 1000.0
    
    def __str__(self):
        return self.format()
    
    @staticmethod
    def parse(val, fmt = None):
        if (fmt is None):
            fmt = Timestamp.default_format
        ts = time.strptime(val, fmt)
        return Timestamp(ts)

    @staticmethod
    def now():
        return Timestamp(time.gmtime())

    @staticmethod
    def unix(t):
        return Timestamp(time.gmtime(int(t)))


    class _YamlSerializer(YamlSerializer):

        def repr_yml(self, py_repr, **kwargs):
            return py_repr.format()
    
        def repr_py(self, yml_repr, **kwargs):
            return Timestamp.parse(yml_repr)

class Duration:

    def __init__(self, tdelta):
        self._tdelta = tdelta
    
    def total_seconds(self):
        return self._tdelta.total_seconds()
    
    class _YamlSerializer(YamlSerializer):
        
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = py_repr.total_seconds()
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = Duration(tdelta = datetime.timedelta(seconds=yml_repr))
            return py_repr

class ActivityMonitor:
    """An object which helps keeping track of the state of another based on its
    "activity"."""

    def __init__(self, activity_timeout, last_activity = None):
        self._last_activity = last_activity
        self._activity_timeout = Duration(tdelta = activity_timeout)
    
    def mark_active(self):
        self._last_activity = Timestamp.now()
    
    def is_active(self):
        if self._last_activity is None:
            return False
        now = Timestamp.now()
        diff = now.subtract(self._last_activity)
        return (diff <= self._activity_timeout.total_seconds())
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            if (py_repr._last_activity is not None):
                yml_repr["last_activity"] = repr_yml(
                                                py_repr._last_activity, **kwargs)
            yml_repr["activity_timeout"] = repr_yml(
                                            py_repr._activity_timeout, **kwargs)
            yml_repr["active"] = py_repr.is_active()
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            last_activity = None
            if ("last_activity" in yml_repr):
                last_activity = repr_py(Timestamp, 
                                    yml_repr["last_activity"], **kwargs)
            activity_timeout = repr_py(Duration, 
                                    yml_repr["activity_timeout"], **kwargs)
            py_repr = ActivityMonitor(
                        activity_timeout = activity_timeout,
                        last_activity = last_activity)
            return py_repr

def validate_fqdn(fqdn):
    """Checks that provided string is a valid FQDN.
    
    Adapted from:
    https://stackoverflow.com/questions/2532053/validate-a-hostname-string

    The function ensures that each segment:

        - contains at least one character and a maximum of 63 characters
        - consists only of allowed characters
        - doesn't begin or end with a hyphen.

    It also avoids double negatives (not disallowed).
    """
    if len(fqdn) > 255:
        return False
    allowed = re.compile(r"(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in fqdn.split("."))

def wait_for_sigint(tgt=None, logger=None):
    def exit_handler(sig, frame):
        try:
            if tgt:
                tgt.stop()
            sys.exit(0)
        except Exception as e:
            if logger:
                logger.exception(e)
            sys.exit(1)
    signal.signal(signal.SIGINT, exit_handler)
    if logger:
        logger.activity("send SIGINT (CTRL+C) to exit")
    signal.pause()

def wait_for_signals(sem_wait, sem_exit=None, sem_reload=None, logger=None):
    def handler_exit(sig, frame):
        if logger:
            logger.debug("received SIGINT")
        sem_exit.release()
        sem_wait.release()
    def handler_reload(sig, frame):
        if logger:
            logger.debug("received SIGUSR1")
        sem_reload.release()
        sem_wait.release()
    if sem_exit:
        signal.signal(signal.SIGINT, handler_exit)
        if logger:
            logger.activity("send SIGINT (CTRL+C) to exit")
    if sem_reload:
        signal.signal(signal.SIGUSR1, handler_reload)
    sem_wait.acquire()

def wait_for_signals(sem_wait, signals, logger=None):
    def _install_handler(k, handler):
        s = {
            "SIGINT": signal.SIGINT,
            "SIGUSR1": signal.SIGUSR1,
            "SIGUSR2": signal.SIGUSR2
        }.get(k)
        if not s:
            raise UvnException(f"unsupported signal: {k}")
        def _handler(sig, frame):
            if logger:
                logger.warning("received {}", k)
            handler()
        signal.signal(s, _handler)
        return k

    handlers = [_install_handler(k, handler)
                    for (k, handler) in signals.items()]
    if logger:
        logger.activity("captured signals: {}", handlers)
    sem_wait.acquire()


def dynamic_import(name):
    components = name.split('.')
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod

def pop_with_lock(lock, queue):
    def _next_request():
        with lock:
            if queue:
                # extract newest request and discard others
                req = queue.pop(-1)
                queue.clear()
                return req
            return None
    return _next_request

def process_queue(lock, queue, handler):
    next_req = pop_with_lock(lock, queue)
    req = next_req()
    while req:
        handler(**req)
        req = next_req()

def notify_if_present(obj, cb_name, *args):
    cb = getattr(obj, cb_name, None)
    if cb:
        cb(*args)


class CustomizableValueDescriptor:
    def __init__(self, value_cls, none_resets=True):
        self._value_cls = value_cls
        self._value_default = value_cls()
        self._value = None
        self._value_set = False
        self._value_reset_on_none = none_resets
    
    def __get__(self, obj, objtype=None):
        if self._value_set:
            return self._value
        else:
            return self._value_default
    
    def __set__(self, obj, value):
        if value is not None and not isinstance(value, self._value_cls):
            raise ValueError(value)
        self._value = value
        self._value_set = not self._value_reset_on_none or self._value is not None

class ListenerDescriptor(CustomizableValueDescriptor):
    def __init__(self, listener_cls):
        CustomizableValueDescriptor.__init__(self, value_cls=listener_cls)


class Observable:
    @staticmethod
    def listener_event_map(obsv, listener_map):
        """
        To be used with an observable with a "listener" attribute whose value
        is managed by ListenerDescriptor.

        Return an event_map to be passed to Observable.__init__ whose callbacks
        will invoke a method on the listener object, retrieved "lazily" via the
        ListenerDescriptor.__get__
        """
        if hasattr(obsv, "listener"):
            ValueError(obsv)

        def mkcallback(k, v):
            def _callback(*args, **kwargs):
                return getattr(obsv.listener, v)(*args, **kwargs)
            return _callback

        return {k: mkcallback(k, v) for k, v in listener_map.items()}

    def __init__(self, callbacks, events_prefix=None, events_remap=None):
        self._observable_callbacks = callbacks
        self._observable_events_prefix = events_prefix
        self._observable_events_remap = events_remap

    def _event_remap(self, event):
        return (self._observable_events_remap[event]
                if (self._observable_events_remap
                    and event in self._observable_events_remap)
                else f"{self._observable_events_prefix}_{event}"
                    if self._observable_events_prefix is not None
                    else event)

    def _event_dispatch(self, event, *args, **kwargs):
        event_orig = event
        event = self._event_remap(event)
        callback = self._observable_callbacks.get(event)
        if not callback:
            logger.trace("no event registered for '{}' on {}", event, self)
            return
        if "dispatched_events" not in kwargs:
            # kwargs=dict(kwargs)
            kwargs["dispatched_events"] = [event]
        # Check if instance defines an event-specific dispatch implementation
        # to pass custom arguments to the callback
        dispatch_method = f"_dispatch_event_{event}"
        ok = hasattr(self, dispatch_method)
        if hasattr(self, dispatch_method):
            return getattr(self, dispatch_method)(callback, *args, **kwargs)
        callback(self, *args, **kwargs)
    
    def _event_dispatch_all(self, events, *args, **kwargs):
        for e in events:
            self._event_dispatch(e, *args, dispatched_events=events, **kwargs)


class _ObservableStatusKind:
    UNKNOWN = -1
    CREATED = 0
    ERROR = 1
    STARTED = 2
    STOPPED = 3

    @staticmethod
    def to_str(val):
        if val == _ObservableStatusKind.CREATED:
            return "CREATED"
        elif val == _ObservableStatusKind.ERROR:
            return "ERROR"
        elif val == _ObservableStatusKind.STARTED:
            return "STARTED"
        elif val == _ObservableStatusKind.STOPPED:
            return "STOPPED"
        else:
            return "UNKNOWN"

    @staticmethod
    def from_int(val):
        if val == _ObservableStatusKind.CREATED:
            return ObservableStatus.CREATED
        elif val == _ObservableStatusKind.ERROR:
            return ObservableStatus.ERROR
        elif val == _ObservableStatusKind.STARTED:
            return ObservableStatus.STARTED
        elif val == _ObservableStatusKind.STOPPED:
            return ObservableStatus.STOPPED
        else:
            return ObservableStatus.UNKNOWN
    
    @staticmethod
    def valid(val):
        return val not in [
            _ObservableStatusKind.CREATED,
            _ObservableStatusKind.ERROR,
            _ObservableStatusKind.STARTED,
            _ObservableStatusKind.STOPPED]
    
    def __init__(self, val, validate=False):
        if validate and not _ObservableStatusKind.valid(valid):
            raise ValueError(val)
        self._val = val
    
    def __eq__(self, other):
        if isinstance(other, _ObservableStatusKind):
            return self._val == other._val
        return self._val == other

    def __str__(self):
        return _ObservableStatusKind.to_str(self._val)
    
    def value(self):
        return self._val

_ObservableStatus = collections.namedtuple("ObservableStatus",
    [ "UNKNOWN", "CREATED", "ERROR", "STARTED", "STOPPED",
        "from_int", "to_str", "valid"])

ObservableStatus = _ObservableStatus(
    UNKNOWN = _ObservableStatusKind(_ObservableStatusKind.UNKNOWN),
    CREATED = _ObservableStatusKind(_ObservableStatusKind.CREATED),
    ERROR = _ObservableStatusKind(_ObservableStatusKind.ERROR),
    STARTED = _ObservableStatusKind(_ObservableStatusKind.STARTED),
    STOPPED = _ObservableStatusKind(_ObservableStatusKind.STOPPED),
    from_int = lambda i: _ObservableStatusKind(i),
    to_str = _ObservableStatusKind.to_str,
    valid = _ObservableStatusKind.valid)


class StatefulObjectStatusDescriptor:

    def __get__(self, obj, objtype=None):
        return obj._status
    
    def __set__(self, obj, value):
        if not isinstance(value, _ObservableStatusKind):
            value = ObservableStatus.from_int(value)
        obj.state_set_value(value)

class StatefulObject:
    _status_all_default = {
        "unknown": ObservableStatus.UNKNOWN,
        "created": ObservableStatus.CREATED,
        "error": ObservableStatus.ERROR,
        "started": ObservableStatus.STARTED,
        "stopped": ObservableStatus.STOPPED,
        "reset": ObservableStatus.CREATED
    }

    def __init__(self, statuses=None, initial_status=None):
        if statuses:
            self._status_all = statuses
        else:
            self._status_all = StatefulObservable._status_all_default
        if initial_status:
            self._state_update(initial_status, init=True)
        else:
            self._state_update("created", init=True)

    def _on_state_created(self, *args, **kwargs):
        pass

    def _on_state_started(self, *args, **kwargs):
        pass
    
    def _on_state_stopped(self, *args, **kwargs):
        pass
    
    def _on_state_reset(self, *args, **kwargs):
        pass
    
    def _on_state_error(self, unknown, *args, **kwargs):
        pass
    
    def _state_update(self, state_id, init=False):
        self._status = self._status_all[state_id]

    def _state_set_created(self, *args, **kwargs):
        self._on_state_created(*args, **kwargs)
        self._state_update("created")

    def _state_set_started(self, *args, **kwargs):
        self._on_state_started(*args, **kwargs)
        self._state_update("started")
    
    def _state_set_stopped(self, *args, **kwargs):
        self._on_state_stopped(*args, **kwargs)
        self._state_update("stopped")
    
    def _state_set_reset(self, *args, **kwargs):
        self._on_state_reset(*args, **kwargs)
        self._state_update("reset")
    
    def _state_set_unknown(self, *args, **kwargs):
        self._on_state_error(True, *args, **kwargs)
        self._state_update("unknown")

    def _state_set_error(self, *args, **kwargs):
        self._on_state_error(False, *args, **kwargs)
        self._state_update("error")
    
    def state_created(self, *args, **kwargs):
        self._state_set_created(*args, **kwargs)
    
    def state_started(self, *args, **kwargs):
        self._state_set_started(*args, **kwargs)
    
    def state_stopped(self, *args, **kwargs):
        self._state_set_stopped(*args, **kwargs)
    
    def state_reset(self, *args, **kwargs):
        self._state_set_reset(*args, **kwargs)
    
    def state_error(self, *args, **kwargs):
        self._state_set_error(*args, **kwargs)
    
    def state_unknown(self, *args, **kwargs):
        self._state_set_unknown(*args, **kwargs)
    
    def state_set_value(self, value, *args, **kwargs):
        status, v = next(filter(lambda s: s[1] == value, self._status_all.items()))
        getattr(self, f"state_{status}")(*args, **kwargs)

class StatefulObservable(Observable, StatefulObject):
    def __init__(self, callbacks,
            events_prefix=None, events_remap=None, statuses=None,
            initial_status=None):
        Observable.__init__(self, callbacks,
            events_prefix=events_prefix, events_remap=events_remap)
        StatefulObject.__init__(self, statuses=statuses, initial_status=initial_status)

    def _on_state_started(self, *args, **kwargs):
        self._event_dispatch("state_started", *args, **kwargs)
    
    def _on_state_stopped(self, *args, **kwargs):
        self._event_dispatch("state_stopped", *args, **kwargs)
    
    def _on_state_reset(self, *args, **kwargs):
        self._event_dispatch("state_reset", *args, **kwargs)
    
    def _on_state_error(self, unknown, *args, **kwargs):
        if "unknown":
            self._event_dispatch("state_unknown", *args, **kwargs)
        else:
            self._event_dispatch("state_error", *args, **kwargs)

class ObservableDelegate(Observable):
    def __init__(self, target):
        self._observable_tgt = target
    
    def _event_dispatch(self, event, *args, **kwargs):
        self._observable_tgt._event_dispatch(event, *args, **kwargs)


# TODO Turn this class into a decorator, e.g.
# @AbstractContainer(element=ElementClass)
class AbstractContainer:

    def __init__(self):
        self._content = {}
    
    def __iter__(self):
        return iter(self._content.values())
    
    def clear(self):
        content = list(self._content.keys())
        for k in content:
            self._container_remove(k)
    
    def _container_default_item(self, handle, *args, **kwargs):
        return None

    def _container_create_item(self, handle, *args, **kwargs):
        return None
    
    def _container_update_item(self, handle, item, *args, **kwargs):
        return item, False
    
    def _container_asserted_item(self,
            handle, item, prev_item, new_item, updated,
            *args, **kwargs):
        pass
    
    def _container_snapshot_item(self, handle, item, *args, **kwargs):
        return None

    def _container_get(self, handle):
        return self._content.get(handle)
    
    def _container_removed_item(self, handle, item, *args, **kwargs):
        pass
    
    def _container_remove(self, handle, *args, **kwargs):
        item = self._content[handle]
        del self._content[handle]
        self._container_removed_item(handle, item, *args, **kwargs)

    def _container_assert_item(self, handle, *args, **kwargs):
        item = self._content.get(handle)
        new_item = item is None
        updated = False
        if new_item:
            item_prev = self._container_default_item(handle, *args, **kwargs)
            item = self._container_create_item(handle, *args, **kwargs)
            updated = True
        else:
            item_prev = self._container_snapshot_item(handle, item, *args, **kwargs)
            item, updated = self._container_update_item(handle, item, *args, **kwargs)
        
        if item is not None:
            self._content[handle] = item
            self._container_asserted_item(handle, item, item_prev, new_item, updated, *args, **kwargs)
        elif not new_item:
            del self._content[handle]
            self._container_removed_item(handle, item, *args, **kwargs)
        
        return item, item_prev, new_item, updated

class ContainerListenerDescriptor(ListenerDescriptor):
    def __set__(self, obj, value):
        ListenerDescriptor.__set__(self, obj, value)
        # store listener in every existing peer
        for p in obj:
            p.listener = value

class CachedOrGeneratedValuedDescriptor:
    def __init__(self, gen_fn, validate_fn=None):
        self._cached = None
        self._gen_fn = gen_fn
        self._validate_fn = validate_fn

    def __get__(self, obj, objtype=None):
        if self._cached is not None:
            return self._cached
        else:
            return self._gen_fn()
    
    def __set__(self, obj, value):
        if value is not None:
            self._cached = self._validate_fn(value)
            self.on_value_cached(self._cached)
        else:
            old_val = self._cached
            self._cached = None
            self.on_value_reset(old_val)
    
    def on_value_cached(self, val):
        pass
    
    def on_value_reset(self, old_val):
        pass

import threading
import random

class PeriodicFunctionThread(threading.Thread):
    def __init__(self, fn, period, run_on_start=False, wrap_except=False, logger=None):
        self._sem_exit = threading.Semaphore()
        self._sem_exit.acquire()
        self._lock = threading.RLock()
        self._period = (period, period) if isinstance(period, int) else period
        self._run_on_start = run_on_start
        self._fn = fn
        self._wrap_except = wrap_except
        self._logger = logger
        threading.Thread.__init__(self)

    def start(self):
        self._exit = False
        threading.Thread.start(self)
    
    def stop(self):
        if not self.is_alive():
            return
        self._exit = True
        self._sem_exit.release()
        self.join()

    def run(self):
        try:
            if self._run_on_start:
                self._fn()
            while not self._exit:
                wait_time = random.randint(self._period[0], self._period[1])
                if self._sem_exit.acquire(timeout=wait_time):
                    continue
                self._fn()
        except Exception as e:
            if not self._wrap_except:
                raise (e)
            elif self._logger:
                self._logger.exception(e)
                self._logger.error("error in periodic thread: {}", self)


class ExtraClassMethods:

    class Method:
        def __init__(self, obj, fn):
            self._fn = fn
            self._obj = obj
        
        def __call__(self, *args, **kwargs):
            return self._fn(self._obj, *args, **kwargs)

    def __init__(self, methods=[]):
        self._methods = methods
        self._methods_t = None
        self._name = None
        self._attr = None

    def __get__(self, obj, objtype=None):
        if not hasattr(obj, self._attr):
            # methods_t_fns = [ExtraClassMethods.Method(obj, m)
            #                     for m in self._methods]
            # methods_t = self._methods_t(*methods_t_fns)
            # setattr(obj, self._attr, methods_t)
            setattr(obj, self._attr,
                self._methods_t(*[ExtraClassMethods.Method(obj, m)
                                        for m in self._methods]))
        return getattr(obj, self._attr)

    def __set_name__(self, owner, name):
        self._name = f"{owner.__name__}_{name}"
        self._attr = f"_{name}"
        self._methods_t = collections.namedtuple(f"{self._name}",
                [m.__name__ for m in self. _methods])

class ListLastElementDescriptor:
    def __init__(self, attr):
        self._attr = attr
    def __get__(self, obj, objtype=None):
        l = obj
        for p in self._attr.split("."):
            l = getattr(l, p)
        if l:
            return l[-1]
        else:
            return None

class ValuesRange:
    def __init__(self, start, stop, incr):
        self.start = start
        self.stop = stop
        self.incr = incr
    
    def __iter__(self):
        return ValuesRange.Iterator(self)

    class Iterator:
        def __init__(self, range):
            self._range = range
            self._cur = self._range.start

        def __next__(self):
            if self._cur >= self._range.stop:
                raise StopIteration()
            self._cur = self._cur + self._range.incr
            return self._cur

def humanbytes(B):
    'Return the given bytes as a human friendly KB, MB, GB, or TB string'
    B = float(B)
    KB = float(1024)
    MB = float(KB ** 2) # 1,048,576
    GB = float(KB ** 3) # 1,073,741,824
    TB = float(KB ** 4) # 1,099,511,627,776

    if B < KB:
        return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
    elif KB <= B < MB:
        return '{0:.2f} KB'.format(B/KB)
    elif MB <= B < GB:
        return '{0:.2f} MB'.format(B/MB)
    elif GB <= B < TB:
        return '{0:.2f} GB'.format(B/GB)
    elif TB <= B:
        return '{0:.2f} TB'.format(B/TB)



class MonitorThread(threading.Thread):

    def __init__(self, name, min_wait=0):
        threading.Thread.__init__(self, daemon=True)
        # set thread name
        self.name = name
        self._min_wait = min_wait
        self._queued = False
        self._lock = threading.RLock()
        self._sem_run = threading.Semaphore()
        self._sem_run.acquire()
        self._sem_exit = threading.BoundedSemaphore()
        self._sem_exit.acquire()

    def trigger(self):
        with self._lock:
            if self._queued:
                return
            self._queued = True
        self._sem_run.release()
    
    def _do_monitor(self):
        raise NotImplementedError()

    def run(self):
        complete = False
        while not (complete or self._exit):
            self._sem_run.acquire()

            run = False
            with self._lock:
                run = self._queued
                if run:
                    self._queued = False
            if run:
                self._do_monitor()

            if self._min_wait:
                complete = self._sem_exit.acquire(timeout=self._min_wait)
            else:
                complete = self._sem_exit.acquire(blocking=False)

    def start(self):
        self._exit = False
        threading.Thread.start(self)

    def stop(self):
        if not self.is_alive():
            return
        self._exit = True
        self._sem_exit.release()
        self._sem_run.release()
        self.join()
