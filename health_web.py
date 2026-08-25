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
        report = data_backup.run_once(force=True)
        return {"ok": not any(str(v).startswith("failed")
                              for v in report.values()),
                "report": report, "backup": data_backup.health()}
