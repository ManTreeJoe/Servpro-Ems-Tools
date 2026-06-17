"""Multi-unit / multi-card pin tests.

Covers:
  - persistence.set_run_day_units / get_run_day_units round-trip
  - legacy single-string day-pin promoted to a list on read
  - _expand_multi_pinned_jobs replicates a row when N≥2 units pinned
  - audit's composed folder lookup respects the expansion map
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


# ── persistence list variants ────────────────────────────────────────────

def test_set_run_day_units_round_trip():
    persistence.set_run_day_units(
        "05-14-2026", "Avila Apartments",
        [r"X:\IE_Public\2026 Jobs\Avila Apartments 2026\Unit 527 2-19-26",
         r"X:\IE_Public\2026 Jobs\Avila Apartments 2026\Unit 1416 5-9-26"])
    paths = persistence.get_run_day_units("05-14-2026", "Avila Apartments")
    assert len(paths) == 2
    assert paths[0].endswith("Unit 527 2-19-26")


def test_set_run_day_units_dedupes_while_preserving_order():
    persistence.set_run_day_units(
        "05-14-2026", "Avila Apartments",
        ["A", "B", "A", "C", "B"])
    assert persistence.get_run_day_units(
        "05-14-2026", "Avila Apartments") == ["A", "B", "C"]


def test_set_run_day_units_empty_clears_pin():
    persistence.set_run_day_units(
        "05-14-2026", "Avila Apartments", ["/some/path"])
    persistence.set_run_day_units("05-14-2026", "Avila Apartments", [])
    assert persistence.get_run_day_units(
        "05-14-2026", "Avila Apartments") == []


def test_get_run_day_unit_returns_first_for_back_compat():
    """The legacy single-path API should still resolve cleanly when
    the underlying store has a multi-pin list."""
    persistence.set_run_day_units(
        "05-14-2026", "Avila", ["/path/A", "/path/B"])
    assert persistence.get_run_day_unit("05-14-2026", "Avila") == "/path/A"


def test_set_run_day_unit_replaces_whole_pin_list():
    """Single-path setter clobbers any existing multi-pin list (it's a
    backward-compat shim, not an add-to-list operation)."""
    persistence.set_run_day_units(
        "05-14-2026", "Avila", ["/path/A", "/path/B"])
    persistence.set_run_day_unit("05-14-2026", "Avila", "/path/C")
    assert persistence.get_run_day_units(
        "05-14-2026", "Avila") == ["/path/C"]


def test_legacy_string_value_is_promoted_to_list_on_read():
    """A pre-multi-pin install wrote bare strings into the state dict.
    Verify the read path transparently promotes those to a single-item
    list so callers never see the old shape."""
    # Simulate by injecting a legacy entry directly into state.
    state = persistence._load()
    state.setdefault("run_day_units", {}).setdefault(
        "05-14-2026", {})["avila"] = "/legacy/path"
    persistence._save(state)
    assert persistence.get_run_day_units(
        "05-14-2026", "Avila") == ["/legacy/path"]


# ── audit row expansion ─────────────────────────────────────────────────

def test_expand_multi_pinned_jobs_replicates_row():
    import run_audit_gui
    persistence.set_run_day_units(
        "05-14-2026", "Avila Apartments",
        [r"X:\IE_Public\2026 Jobs\Avila Apartments 2026\Unit 527 2-19-26",
         r"X:\IE_Public\2026 Jobs\Avila Apartments 2026\Unit 1416 5-9-26"])
    jobs = [{"client": "Avila Apartments", "section": "work", "raw": "..."}]
    expanded, lookup = run_audit_gui._expand_multi_pinned_jobs(
        jobs, "05-14-2026")
    assert len(expanded) == 2
    names = [j["client"] for j in expanded]
    assert names[0].startswith("Avila Apartments — Unit 527")
    assert names[1].startswith("Avila Apartments — Unit 1416")
    # Lookup map keys are the augmented names; values are the resolved paths
    assert lookup[names[0]].endswith("Unit 527 2-19-26")
    assert lookup[names[1]].endswith("Unit 1416 5-9-26")


def test_expand_multi_pinned_jobs_no_op_when_single_or_zero_pins():
    import run_audit_gui
    persistence.set_run_day_units(
        "05-14-2026", "Single Pin Client", ["/just/one"])
    jobs = [
        {"client": "Single Pin Client", "section": "work"},
        {"client": "No Pin Client",     "section": "work"},
    ]
    expanded, lookup = run_audit_gui._expand_multi_pinned_jobs(
        jobs, "05-14-2026")
    assert len(expanded) == 2
    assert all(j["client"] in ("Single Pin Client", "No Pin Client")
                for j in expanded)
    assert lookup == {}


def test_composed_lookup_prefers_expand_map():
    """The expansion map should win over both `base` and persisted
    day-pins, since each expanded child resolves to its own unit."""
    import run_audit_gui
    expand_map = {"Avila Apartments — Unit 527": "/expanded/527/path"}
    persistence.set_run_day_units(
        "05-14-2026", "Avila Apartments — Unit 527",
        ["/persisted/wrong/path"])
    lookup = run_audit_gui._composed_folder_lookup(
        "05-14-2026", expand_map=expand_map)
    assert lookup("Avila Apartments — Unit 527") == "/expanded/527/path"
