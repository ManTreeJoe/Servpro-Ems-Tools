"""Big regenerable caches live outside state.json.

Three keys were 85% of a 6.6 MB state.json. `_save()` deepcopies the whole
state and re-encodes it with indent=2 on every mutation anywhere in the
app, so ticking one checkbox rewrote 5.9 MB and a 13-job audit burned
~3.4s of CPU on eight of those writes before touching the network.

What these pin: the split works, the one-time migration out of state.json
cannot lose data, and a state write no longer drags the caches with it.
"""
import json
import os

import pytest


@pytest.fixture
def per(tmp_path, monkeypatch):
    """persistence pointed at a scratch data dir, module state reset."""
    import paths
    import persistence as p
    monkeypatch.setattr(paths, "data", lambda name: str(tmp_path / name))
    monkeypatch.setattr(p, "_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(p, "_CACHE", None)
    monkeypatch.setattr(p, "_CACHE_MTIME", None)
    monkeypatch.setattr(p, "_SIDECAR_CACHE", {})
    return p


def _state_on_disk(per):
    """state.json as written. Missing counts as empty — a sidecar-only
    write shouldn't create the file at all, which is the point."""
    if not os.path.exists(per._STATE_PATH):
        return {}
    with open(per._STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── routing ────────────────────────────────────────────────────────────
def test_sidecar_value_never_lands_in_state(per):
    per.set_value("xa_email_bodies", {"m1": "hello"})
    per.set_value("some_normal_key", 1)
    assert per.get("xa_email_bodies") == {"m1": "hello"}
    assert "xa_email_bodies" not in _state_on_disk(per)
    assert _state_on_disk(per)["some_normal_key"] == 1


def test_sidecar_has_its_own_file(per, tmp_path):
    per.set_value("dispute_email_seen", ["a", "b"])
    assert (tmp_path / "cache_dispute_email_seen.json").is_file()
    assert per.get("dispute_email_seen") == ["a", "b"]


def test_normal_keys_are_unaffected(per):
    per.set_value("folder_paths", {"smith": "x:/smith"})
    assert per.get("folder_paths") == {"smith": "x:/smith"}
    assert _state_on_disk(per)["folder_paths"] == {"smith": "x:/smith"}


def test_missing_sidecar_returns_the_default(per):
    assert per.get("xa_email_bodies") is None
    assert per.get("xa_email_bodies", {}) == {}
    assert per.get("dispute_email_seen", []) == []


def test_survives_a_corrupt_cache_file(per, tmp_path):
    """A cache is regenerable — a truncated file must degrade to empty,
    never take the app down on startup."""
    (tmp_path / "cache_xa_email_bodies.json").write_text("{not json",
                                                        encoding="utf-8")
    assert per.get("xa_email_bodies", {}) == {}


# ── migration out of state.json ────────────────────────────────────────
def test_legacy_value_is_adopted_and_then_removed(per, tmp_path):
    per.set_value("other", "keep me")
    state = per._load()
    state["xa_email_bodies"] = {"m1": "body"}
    per._save(state)
    assert "xa_email_bodies" in _state_on_disk(per)

    assert per.get("xa_email_bodies") == {"m1": "body"}      # adopted
    assert (tmp_path / "cache_xa_email_bodies.json").is_file()
    on_disk = _state_on_disk(per)
    assert "xa_email_bodies" not in on_disk                  # and dropped
    assert on_disk["other"] == "keep me"                     # nothing else lost


def test_migration_writes_the_sidecar_before_dropping_the_key(per, monkeypatch):
    """If the sidecar write fails, the value must still be in state.json —
    losing a 3 MB cache to a failed write would be silent."""
    state = per._load()
    state["xa_email_bodies"] = {"m1": "body"}
    per._save(state)

    def _boom(key, value):
        raise OSError("disk full")
    monkeypatch.setattr(per, "_sidecar_save", _boom)
    with pytest.raises(OSError):
        per.get("xa_email_bodies")
    assert _state_on_disk(per)["xa_email_bodies"] == {"m1": "body"}


def test_migration_is_idempotent(per):
    state = per._load()
    state["hygiene_scan_cache"] = {"ts": "2026-08-11T00:00:00", "hygiene": []}
    per._save(state)
    first = per.get("hygiene_scan_cache")
    second = per.get("hygiene_scan_cache")
    assert first == second
    assert "hygiene_scan_cache" not in _state_on_disk(per)


def test_empty_legacy_value_is_just_dropped(per, tmp_path):
    state = per._load()
    state["dispute_email_seen"] = []
    per._save(state)
    assert per.get("dispute_email_seen", []) == []
    # An empty list is worth nothing — no need to write a file for it.
    assert not (tmp_path / "cache_dispute_email_seen.json").exists()


# ── the actual point: state.json stops carrying the weight ─────────────
def test_state_stays_small_when_a_cache_is_huge(per):
    per.set_value("xa_email_bodies", {f"m{i}": "x" * 500 for i in range(400)})
    per.set_value("resolved_issues", {"a": True})
    assert os.path.getsize(per._STATE_PATH) < 5_000
    assert per.get("xa_email_bodies")["m0"] == "x" * 500


def test_writing_state_does_not_rewrite_the_cache(per, tmp_path):
    per.set_value("xa_email_bodies", {"m1": "body"})
    cache_file = tmp_path / "cache_xa_email_bodies.json"
    before = cache_file.stat().st_mtime_ns
    for i in range(5):
        per.set_value("resolved_issues", {"n": i})
    assert cache_file.stat().st_mtime_ns == before


# ── the hygiene accessors go through the same door ─────────────────────
def test_hygiene_scan_cache_roundtrip(per, tmp_path):
    per.set_hygiene_scan_cache(["h1"], ["c1"], ipr=["i1"])
    got, age = per.get_hygiene_scan_cache(max_age_minutes=60)
    assert got["hygiene"] == ["h1"] and got["closeout"] == ["c1"]
    assert got["ipr"] == ["i1"]
    assert age >= 0
    assert (tmp_path / "cache_hygiene_scan.json").is_file()
    assert "hygiene_scan_cache" not in _state_on_disk(per)


def test_hygiene_scan_cache_clear(per):
    per.set_hygiene_scan_cache(["h1"], [])
    per.clear_hygiene_scan_cache()
    assert per.get_hygiene_scan_cache(max_age_minutes=60) is None


def test_stale_hygiene_cache_is_ignored(per):
    per.set_hygiene_scan_cache(["h1"], [])
    assert per.get_hygiene_scan_cache(max_age_minutes=0) is None


def test_loading_state_does_not_recreate_the_key(per):
    """The schema defaulter used to put hygiene_scan_cache back into
    state.json on every load, which would undo the split."""
    per.set_value("anything", 1)
    per._CACHE = None
    per._CACHE_MTIME = None
    per._load()
    per.set_value("anything", 2)
    assert "hygiene_scan_cache" not in _state_on_disk(per)
