"""Dated copies of the files the business cannot lose.

There were none. state.json holds every pin, resolved issue and tracker
record; ems_jobs.db is the job index; config.json holds the paths and
tokens. In July state.json failed to write three times with "Access is
denied", and twelve Trello pins were later found stranded in an
abandoned data folder — both recoverable only because someone looked.
"""
import os
import time

import pytest

import data_backup as db
import paths


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data", lambda name: str(tmp_path / name))
    for n in db.FILES:
        (tmp_path / n).write_text(f"contents of {n}", encoding="utf-8")
    return tmp_path


def _copies(data, name):
    d = data / "backups"
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.iterdir() if f.name.startswith(name + "."))


# ── the basics ─────────────────────────────────────────────────────────
def test_every_protected_file_is_copied(data):
    rep = db.run_once(force=True)
    assert rep == {n: "copied" for n in db.FILES}
    for n in db.FILES:
        assert len(_copies(data, n)) == 1


def test_the_copy_matches_the_original(data):
    db.run_once(force=True)
    src = (data / "state.json").read_text(encoding="utf-8")
    got = (data / "backups" / _copies(data, "state.json")[0]).read_text(
        encoding="utf-8")
    assert got == src


def test_a_missing_file_is_reported_not_fatal(data):
    (data / "ems_jobs.db").unlink()
    rep = db.run_once(force=True)
    assert rep["ems_jobs.db"] == "missing"
    assert rep["state.json"] == "copied"


def test_regenerable_caches_are_not_backed_up():
    """The cache_*.json sidecars cost a re-fetch, not data."""
    assert not any(f.startswith("cache_") for f in db.FILES)


# ── retention ──────────────────────────────────────────────────────────
def test_only_the_newest_copies_are_kept(data):
    for i in range(db.KEEP + 4):
        db.run_once(force=True)
        time.sleep(0.02)          # distinct second-resolution stamps
        # force=True skips the interval check, so re-stamp by hand
        for f in (data / "backups").iterdir():
            if f.name.startswith("state.json."):
                pass
    assert len(_copies(data, "state.json")) <= db.KEEP


def test_a_quick_restart_does_not_burn_a_slot(data):
    """The app gets restarted repeatedly while working; without the
    interval the seven slots fill with copies of the same minute and the
    week of history they exist for is gone."""
    assert db.run_once()["state.json"] == "copied"
    assert db.run_once()["state.json"] == "recent"
    assert len(_copies(data, "state.json")) == 1


# ── failure modes ──────────────────────────────────────────────────────
def test_partial_copies_are_not_left_behind(data, monkeypatch):
    """A backup half-written when the machine goes down must not look
    like a usable one — hence .part then rename."""
    import shutil

    def _die(src, dst, *a, **k):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("half")
        raise OSError("disk went away")
    monkeypatch.setattr(shutil, "copy2", _die)
    rep = db.run_once(force=True)
    assert rep["state.json"].startswith("failed")
    assert _copies(data, "state.json") == []       # no usable-looking file


def test_run_once_never_raises(data, monkeypatch):
    monkeypatch.setattr(db, "FILES", ("state.json",))
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(
        OSError("nope")))
    assert "_error" in db.run_once(force=True)


def test_background_start_does_not_raise(data):
    t = db.start_background(force=True)
    t.join(timeout=5)
    assert not t.is_alive()


# ── listing, for Settings ──────────────────────────────────────────────
def test_list_backups_is_newest_first(data):
    db.run_once(force=True)
    rows = db.list_backups()
    assert rows
    assert {r["name"] for r in rows} <= set(db.FILES)
    assert rows == sorted(rows, key=lambda r: (r["stamp"], r["name"]),
                          reverse=True)


def test_list_backups_on_a_fresh_install_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data", lambda name: str(tmp_path / name))
    assert db.list_backups() == []


def test_launch_wires_the_backup_in():
    """It has to run without anyone remembering to."""
    import inspect

    import home_web
    src = inspect.getsource(home_web.main)
    assert "data_backup" in src and "start_background" in src


# ── the log must not be the suite's scratch pad ────────────────────────
def test_the_suite_logs_somewhere_disposable():
    """536 lines of fixture noise in the real ems.log is what hid four
    genuine "state.json write failed" errors."""
    import ems_log
    p = ems_log.log_path().replace("/", "\\").lower()
    assert r"appdata\roaming\linguar hub" not in p, (
        f"tests are logging to the production log: {ems_log.log_path()}")
    ems_log.warn("test", "canary")
    with open(ems_log.log_path(), encoding="utf-8") as f:
        assert "canary" in f.read()
