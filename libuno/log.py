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
import traceback
import numbers
import sys
from termcolor import colored
import threading
import pathlib

class LoggerError(Exception):
    def __init__(self, msg):
        self.msg = msg

class _LogLevel:
    def __init__(self, name, lvl):
        self.name = name
        self.lvl = lvl
    
    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        elif issubclass(other, numbers.Number):
            return self.lvl == other
        elif isinstance(other, _LogLevel):
            return self.lvl == other.lvl
        else:
            raise TypeError()

    def __ge__(self, other):
        if isinstance(other, _LogLevel):
            return self.lvl >= other.lvl
        elif isinstance(other, str):
            return self.name >= other
        elif issubclass(other, numbers.Number):
            return self.lvl >= other
        else:
            raise TypeError()
    
    def __str__(self):
        return self.name

from collections import namedtuple

_LogLevels = namedtuple("LogLevels",
    ['trace', 'debug', 'activity', 'info', 'warning', 'error', 'quiet'])

level = _LogLevels(
            _LogLevel('trace', 500),
            _LogLevel('debug', 400),
            _LogLevel('activity', 350),
            _LogLevel('info', 300),
            _LogLevel('warning', 200),
            _LogLevel('error', 100),
            _LogLevel('quiet', 0))

_LOGGER_LEVEL = level.info
_LOGGER_CONTEXT = None
_LOGGERS = {}
_LOGGER_LOCK = threading.RLock()
_LOGGER_FILE = None
_LOGGER_PREFIX = ""
_LOGGER_NOCOLOR = False

def context_enabled(context):
    if _LOGGER_CONTEXT is None:
        return True
    else:
        return _LOGGER_CONTEXT.match(context) is not None

def log_enabled(context, lvl):
    if _LOGGER_LEVEL >= lvl:
        return context_enabled(context)
    return False

def set_verbosity(lvl):
    global _LOGGER_LOCK
    with _LOGGER_LOCK:
        global _LOGGER_LEVEL
        _LOGGER_LEVEL = lvl

def set_context(context):
    global _LOGGER_LOCK
    with _LOGGER_LOCK:
        global _LOGGER_CONTEXT
        _LOGGER_CONTEXT = re.compile(context)

def set_color(enabled=True):
    global _LOGGER_LOCK
    with _LOGGER_LOCK:
        global _LOGGER_NOCOLOR
        _LOGGER_NOCOLOR = not enabled

def color_enabled():
    global _LOGGER_LOCK
    with _LOGGER_LOCK:
        global _LOGGER_NOCOLOR
        return not _LOGGER_NOCOLOR

def logger(context, no_prefix=False):
    global _LOGGER_LOCK
    with _LOGGER_LOCK:
        global _LOGGERS
        return _LOGGERS.get(context, _UvnLogger(context, no_prefix=no_prefix))

def output_file(path):
    global _LOGGER_LOCK
    global _LOGGER_FILE
    with _LOGGER_LOCK:
        if _LOGGER_FILE:
            _LOGGER_FILE.close()
        path = pathlib.Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        _LOGGER_FILE = path.open("w+")

def global_prefix(pfx):
    global _LOGGER_LOCK
    global _LOGGER_PREFIX
    with _LOGGER_LOCK:
        _LOGGER_PREFIX = pfx

def _colorize(lvl, line):
    if lvl >= level.trace:
        return colored(line, "white")
    elif lvl >= level.debug:
        return colored(line, "magenta")
    elif lvl >= level.activity:
        return colored(line, "cyan")
    elif lvl >= level.info:
        return colored(line, "green")
    elif lvl >= level.warning:
        return colored(line, "yellow")
    elif lvl >= level.error:
        return colored(line, "red")
    else:
        return line

def _emit_default(logger, context, lvl, line, **kwargs):
    file = kwargs.get("file", sys.stdout)
    outfile = kwargs.get("outfile", None)
    # serialize writing to output
    global _LOGGER_LOCK
    global _LOGGER_NOCOLOR
    with _LOGGER_LOCK:
        if outfile:
            print(line, file=outfile)
            outfile.flush()
        if not _LOGGER_NOCOLOR:
            line = _colorize(lvl, line)
        print(line, file=file)
        file.flush()

def _format_default(logger, context, lvl, fmt, *args, **kwargs):
    global _LOGGER_LOCK
    global _LOGGER_PREFIX
    with _LOGGER_LOCK:
        glb_prefix = _LOGGER_PREFIX
    fmt_args = []
    if not logger.no_prefix:
        if glb_prefix:
            fmt_args.extend(["[{}]"])
        fmt_args.extend(["[{}]", "[{}]"])
        if not fmt.startswith("["):
            fmt_args.append(" ")
    fmt_args.append(fmt)
    fmt = "".join(fmt_args)

    fmt_args = []
    if not logger.no_prefix:
        if glb_prefix:
            fmt_args.extend([glb_prefix])
        fmt_args.extend([lvl.name[0], context])
    fmt_args.extend(args)
    
    return fmt.format(*fmt_args)

class _UvnLogger:
    global_prefix = None

    def __init__(
        self,
        context,
        no_prefix=False,
        format=_format_default,
        emit=_emit_default):
        if not context:
            raise LoggerError("invalid logger context")
        self.context = context
        self.format = format
        self.emit = emit
        self.no_prefix = no_prefix

    def _log(self, lvl, *args, **kwargs):
        if not log_enabled(self.context, lvl):
            return
        if len(args) == 1:
            line = self.format(self, self.context, lvl, "{}", *args, **kwargs)
        else:
            line = self.format(self, self.context, lvl, args[0], *args[1:], **kwargs)
        
        global _LOGGER_LOCK
        global _LOGGER_FILE
        with _LOGGER_LOCK:
            if _LOGGER_FILE:
                kwargs["outfile"] = _LOGGER_FILE
            self.emit(self, self.context, lvl, line, **kwargs)

    def exception(self, e):
        # if log_enabled(self.context, level.debug):
        traceback.print_exc()
        self.error("[exception] {}", e)
    
    def command(self, cmd_args, rc, stdout=None, stderr=None, display=False):
        if rc != 0:
            self.error("command failed: {}", " ".join(map(str,cmd_args)))
            self.error("  stdout: {}",
                stdout.decode("utf-8") if stdout else "<none>")
            self.error("  stderr: {}",
                stderr.decode("utf-8") if stderr else "<none>")
        else:
            self.trace("  stdout: {}",
                stdout.decode("utf-8") if stdout else "<none>")
            self.trace("  stderr: {}",
                stderr.decode("utf-8") if stderr else "<none>")
        if display and stdout:
            output = stdout.decode("utf-8")
            for line in output.split("\n"):
                self.info(f"{line}")

    def error(self, *args, **kwargs):
        kwargs["file"] = kwargs.get("file", sys.stderr)
        self._log(level.error, *args, **kwargs)

    def warning(self, *args, **kwargs):
        kwargs["file"] = kwargs.get("file", sys.stderr)
        self._log(level.warning, *args, **kwargs)

    def info(self, *args, **kwargs):
        self._log(level.info, *args, **kwargs)
    
    def activity(self, *args, **kwargs):
        self._log(level.activity, *args, **kwargs)

    def debug(self, *args, **kwargs):
        self._log(level.debug, *args, **kwargs)
    
    def trace(self, *args, **kwargs):
        self._log(level.trace, *args, **kwargs)
