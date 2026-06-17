"""
Lightweight rotating logfile for the EMS Automation suite.
Use ems_log.error('source', 'message') anywhere a try/except swallows errors.
File: scripts/ems.log (rotates when over 1 MB)
"""
import os
from datetime import datetime

import paths

_LOG_PATH    = paths.data("ems.log")
_MAX_BYTES   = 512_000  # rotate to ems.log.bak when this big (~512 KB)

def _rotate_if_needed():
    try:
        if os.path.isfile(_LOG_PATH) and os.path.getsize(_LOG_PATH) > _MAX_BYTES:
            bak = _LOG_PATH + ".bak"
            if os.path.isfile(bak):
                os.remove(bak)
            os.replace(_LOG_PATH, bak)
    except OSError:
        pass

def _write(level, source, message):
    _rotate_if_needed()
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {level:5} " \
            f"{source}: {message}\n"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass

def info(source, message):  _write("INFO",  source, message)
def warn(source, message):  _write("WARN",  source, message)
def error(source, message): _write("ERROR", source, message)


def recent_errors(within_hours=24, max_lines=20):
    """Return the most recent ERROR/WARN lines within `within_hours`."""
    if not os.path.isfile(_LOG_PATH):
        return []
    try:
        with open(_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    cutoff = datetime.now().timestamp() - (within_hours * 3600)
    out = []
    for line in lines:
        if " ERROR " not in line and " WARN " not in line:
            continue
        try:
            ts_end = line.index("]")
            ts = line[1:ts_end]
            if datetime.fromisoformat(ts).timestamp() < cutoff:
                continue
            out.append(line.rstrip())
        except (ValueError, IndexError):
            continue
    return out[-max_lines:]


def log_path():
    return _LOG_PATH


def clear():
    """Truncate the active log so the recent-errors count resets to 0.
    Keeps any .bak rotation so the prior log isn't lost."""
    try:
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("")
    except OSError:
        pass
