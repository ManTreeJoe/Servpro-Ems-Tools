"""Workflow Automations panel API."""
from __future__ import annotations

import os
import paths
import workflow_automations as workflows

INDEX_HTML = os.path.join(paths.RESOURCE_DIR, "automations_web_assets", "index.html")


class Api:
    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    def inventory(self):
        return workflows.inventory()

    def recent_runs(self, limit=50):
        return workflows.recent_runs(limit)

