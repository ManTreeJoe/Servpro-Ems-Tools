"""Privacy and coverage guardrails for application-wide usage tracking."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACKER = "../web_shared/usage_track.js?v=20260825a"

ACTIVE_ASSETS = (
    "home_web_assets", "health_web_assets", "exceptions_web_assets", "audit_web_assets", "run_doc_editor_web_assets",
    "photo_folders_web_assets", "apa_web_assets", "pipeline_web_assets",
    "notifications_web_assets", "hygiene_web_assets", "disputes_web_assets",
    "wc_audit_web_assets", "spreadsheet_web_assets", "job_notes_web_assets",
    "multi_unit_web_assets", "cheat_sheet_web_assets", "resources_web_assets",
    "settings_web_assets", "snapshot_web_assets", "quickimport_web_assets",
)


def test_every_active_web_surface_loads_the_shared_tracker():
    missing = []
    for folder in ACTIVE_ASSETS:
        html = (ROOT / folder / "index.html").read_text(encoding="utf-8")
        if TRACKER not in html:
            missing.append(folder)
    assert missing == []


def test_tracker_never_uses_visible_control_text_as_an_event_label():
    js = (ROOT / "web_shared" / "usage_track.js").read_text(encoding="utf-8")
    label_fn = js[js.index("function labelFor"):js.index("document.addEventListener(\"click\"")]
    for forbidden in ("textContent", "innerText", "title", "aria-label"):
        assert forbidden not in label_fn
    for stable in ("data-track", "data-action", "data-tab", "data-filter"):
        assert stable in label_fn


def test_home_api_exposes_one_shared_tracking_sink():
    source = (ROOT / "home_web.py").read_text(encoding="utf-8")
    assert "def track_events(self, events: list)" in source
    assert "usage_tracker as _ut" in source
