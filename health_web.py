"""Data & Sync Health panel — actionable status, no customer data."""
from __future__ import annotations

import os

import paths

INDEX_HTML = os.path.join(paths.RESOURCE_DIR, "health_web_assets", "index.html")


class Api:
    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    def status(self, force=False):
        import web_health
        return web_health.state(force=bool(force))

    def run_backup(self):
        import data_backup
        with data_backup._RUN_LOCK:
            busy = data_backup._IN_PROGRESS
            if not busy:
                data_backup._IN_PROGRESS = True
        if busy:
            return {"ok": False, "pending": True, "report": {},
                    "backup": data_backup.health()}
        try:
            report = data_backup.run_once(force=True)
            with data_backup._RUN_LOCK:
                data_backup._LAST_REPORT = dict(report)
        finally:
            with data_backup._RUN_LOCK:
                data_backup._IN_PROGRESS = False
        verified = data_backup.health()
        acceptable = {"copied", "recent", "skipped: local backend"}
        return {"ok": bool(verified.get("ok") and "_error" not in report
                            and all(v in acceptable for v in report.values())),
                "report": report, "backup": verified}
