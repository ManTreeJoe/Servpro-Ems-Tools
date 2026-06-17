"""persistence.py caches state.json in memory keyed by file mtime to avoid
re-reading on every UI interaction. These tests pin the cache behavior so a
future refactor can't silently regress it (every checkbox click would go
back to hitting disk twice)."""
import json
import os

import pytest

import persistence


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    """Point persistence at a temp state.json and reset its cache before
    every test so leakage between tests can't mask a stale cache."""
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


def test_cache_returns_same_object_on_repeat_read(tmp_path):
    persistence._save({"foo": 1})
    a = persistence._load()
    b = persistence._load()
    # Same object — we did not re-read the disk.
    assert a is b


def test_cache_invalidates_when_file_mtime_changes(tmp_path):
    persistence._save({"foo": 1})
    a = persistence._load()
    # Simulate an external writer (different process) updating state.json.
    # Touch with a future mtime so getmtime sees a change.
    with open(persistence._STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"foo": 2}, f)
    new_mtime = os.path.getmtime(persistence._STATE_PATH) + 5
    os.utime(persistence._STATE_PATH, (new_mtime, new_mtime))
    b = persistence._load()
    assert b.get("foo") == 2
    assert a is not b


def test_save_updates_cache_without_re_read():
    persistence.set_value("favorite_color", "green")
    # Read should serve from cache after _save populated it.
    assert persistence.get("favorite_color") == "green"


def test_missing_file_returns_empty_dict_no_crash(tmp_path):
    # File never existed — _load should still return {} cleanly.
    assert persistence._load() == {}


def test_mutations_to_loaded_dict_persist_after_save():
    """Existing accessor pattern is `state = _load(); state[k] = v; _save(state)`.
    Make sure that pattern still works against the cached dict."""
    state = persistence._load()
    state["bucket"] = {"a": 1}
    persistence._save(state)
    assert persistence._load()["bucket"] == {"a": 1}
