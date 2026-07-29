"""Local, privacy-safe usage analytics — 'which tools/buttons do I use,
and how do I move through the app', so the UI can be tuned to the real
workflow.

Logs UI ACTIONS only — tool opened, button clicked (its label/id),
panel viewed — with a timestamp. It deliberately does NOT record job
names, client data, search text or file contents, so the log stays a
clean picture of *how the app is used*, not *what was worked on*. Single
user, single machine, stored next to the job DB in %APPDATA%.

Public API:
    record_event(tool, action, label="")   # one event
    record(events)                          # bulk: [{tool,action,label,ts?}]
    report(days=30)                         # aggregated dict for the UI
    reset()                                 # wipe the log
"""
from __future__ import annotations
import os
import sqlite3
import threading
import datetime as _dt
from contextlib import contextmanager

try:
    import paths as _paths
    DB_PATH = _paths.data("usage.db")
except Exception:
    DB_PATH = os.path.join(os.path.expanduser("~"), "ems_usage.db")

_LOCK = threading.Lock()
_INITED = False


def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure():
    global _INITED
    if _INITED:
        return
    with _LOCK, _connect() as c:
        c.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS events (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     TEXT NOT NULL,
                day    TEXT NOT NULL,
                tool   TEXT NOT NULL,
                action TEXT NOT NULL,
                label  TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS ix_events_day  ON events(day);
            CREATE INDEX IF NOT EXISTS ix_events_tool ON events(tool);
        """)
        c.commit()
    _INITED = True


def _clean(s, cap=80) -> str:
    s = " ".join(str(s or "").split())          # collapse whitespace
    return s[:cap]


def record(events) -> dict:
    """Bulk-insert UI events. Each: {tool, action, label?, ts?}. Missing
    ts defaults to now. Silently no-ops on a bad/empty batch so tracking
    never breaks the caller."""
    if not events:
        return {"ok": True, "written": 0}
    try:
        _ensure()
        rows = []
        for e in events:
            if not isinstance(e, dict):
                continue
            tool = _clean(e.get("tool"), 40)
            action = _clean(e.get("action"), 40)
            if not tool or not action:
                continue
            ts = _clean(e.get("ts"), 32) or _now_iso()
            day = ts[:10]
            rows.append((ts, day, tool, action, _clean(e.get("label"))))
        if not rows:
            return {"ok": True, "written": 0}
        with _LOCK, _connect() as c:
            c.executemany(
                "INSERT INTO events (ts, day, tool, action, label) "
                "VALUES (?, ?, ?, ?, ?)", rows)
            c.commit()
        return {"ok": True, "written": len(rows)}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "written": 0}


def record_event(tool: str, action: str, label: str = "") -> dict:
    return record([{"tool": tool, "action": action, "label": label}])


def report(days: int = 30) -> dict:
    """Aggregated usage over the last `days`. Returns top tools, top
    buttons, per-day counts, and span — enough to see where the time goes
    and what to streamline."""
    try:
        _ensure()
        since = (_dt.date.today() - _dt.timedelta(days=max(1, days) - 1)
                 ).isoformat()
        with _LOCK, _connect() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM events WHERE day >= ?",
                (since,)).fetchone()[0]
            tools = [dict(r) for r in c.execute(
                "SELECT tool, COUNT(*) AS count FROM events "
                "WHERE day >= ? GROUP BY tool ORDER BY count DESC LIMIT 30",
                (since,)).fetchall()]
            buttons = [dict(r) for r in c.execute(
                "SELECT tool, label, action, COUNT(*) AS count FROM events "
                "WHERE day >= ? AND action='click' AND label != '' "
                "GROUP BY tool, label ORDER BY count DESC LIMIT 40",
                (since,)).fetchall()]
            per_day = [dict(r) for r in c.execute(
                "SELECT day, COUNT(*) AS count FROM events "
                "WHERE day >= ? GROUP BY day ORDER BY day",
                (since,)).fetchall()]
            span = c.execute(
                "SELECT MIN(ts) AS first, MAX(ts) AS last, "
                "COUNT(DISTINCT day) AS active_days FROM events").fetchone()
        return {"ok": True, "days": days, "total": total,
                "tools": tools, "buttons": buttons, "per_day": per_day,
                "first": span["first"] or "", "last": span["last"] or "",
                "active_days": span["active_days"] or 0}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def reset() -> dict:
    try:
        _ensure()
        with _LOCK, _connect() as c:
            c.execute("DELETE FROM events")
            c.commit()
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
