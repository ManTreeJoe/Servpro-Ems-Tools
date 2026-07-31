"""The EMS Tools -> Linguar Hub data-directory migration.

This runs exactly once on each machine, against ~90 MB of irreplaceable
state (config.json, the job index, APA drafts, every backup). It gets one
chance, so the failure modes are what's tested here rather than the happy
path alone.

Each test builds a throwaway %APPDATA% and re-imports paths against it.
"""
import importlib
import json
import os
import shutil

import pytest


@pytest.fixture(autouse=True)
def _restore_paths():
    """Reloading `paths` rebinds DATA_DIR process-wide, and the module is
    imported by nearly everything. Without this, whichever test ran last
    would leave every later test in the session writing into a tmp dir that
    pytest has already deleted."""
    real_appdata = os.environ.get("APPDATA")
    yield
    if real_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = real_appdata
    import paths
    importlib.reload(paths)


def _fresh_paths(appdata, monkeypatch):
    monkeypatch.setenv("APPDATA", str(appdata))
    import paths
    return importlib.reload(paths)


@pytest.fixture
def legacy(tmp_path):
    """An %APPDATA% holding a populated pre-rebrand folder."""
    old = tmp_path / "EMS Automation"
    (old / "apa_drafts").mkdir(parents=True)
    (old / "config.json").write_text('{"audit_base": "X:/IE_Public"}',
                                      encoding="utf-8")
    (old / "ems_jobs.db").write_bytes(b"sqlite-ish")
    (old / "apa_drafts" / "draft.docx").write_bytes(b"draft")
    return tmp_path


def test_migrates_everything_including_subfolders(legacy, monkeypatch):
    p = _fresh_paths(legacy, monkeypatch)
    assert os.path.basename(p.DATA_DIR) == "Linguar Hub"
    assert json.load(open(p.data("config.json")))["audit_base"] == "X:/IE_Public"
    assert open(p.data("ems_jobs.db"), "rb").read() == b"sqlite-ish"
    # A whitelist would have silently dropped these. Copy the whole tree.
    assert os.path.isfile(os.path.join(p.DATA_DIR, "apa_drafts", "draft.docx"))


def test_legacy_folder_is_left_intact(legacy, monkeypatch):
    """It is the only way back if the rebrand broke something."""
    p = _fresh_paths(legacy, monkeypatch)
    assert os.path.isfile(os.path.join(p.LEGACY_DATA_DIR, "config.json"))


def test_second_run_does_not_reclobber(legacy, monkeypatch):
    p = _fresh_paths(legacy, monkeypatch)
    with open(p.data("config.json"), "w", encoding="utf-8") as f:
        json.dump({"audit_base": "EDITED SINCE"}, f)
    p = _fresh_paths(legacy, monkeypatch)
    assert json.load(open(p.data("config.json")))["audit_base"] == "EDITED SINCE"


def test_failed_copy_falls_back_to_legacy(legacy, monkeypatch):
    """Starting up empty would look exactly like every job vanished. Running
    on the old data is strictly better than that."""
    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(shutil, "copytree", boom)
    p = _fresh_paths(legacy, monkeypatch)
    assert os.path.basename(p.DATA_DIR) == "EMS Automation"
    assert json.load(open(p.data("config.json")))["audit_base"] == "X:/IE_Public"


def test_failed_copy_leaves_no_half_built_dir(legacy, monkeypatch):
    """A half-populated Linguar Hub folder is the dangerous outcome: the
    next launch sees state there, skips the migration, and silently runs on
    a partial copy. Staging + rename is what prevents it."""
    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(shutil, "copytree", boom)
    p = _fresh_paths(legacy, monkeypatch)
    assert not os.path.exists(os.path.join(p.APPDATA, "Linguar Hub"))
    assert not os.path.exists(os.path.join(p.APPDATA, "Linguar Hub.migrating"))


def test_stale_staging_dir_is_cleared(legacy, monkeypatch):
    """A machine that lost power mid-migration has one of these. It must not
    be mistaken for, or merged into, the real copy."""
    stale = legacy / "Linguar Hub.migrating"
    stale.mkdir()
    (stale / "junk.txt").write_text("partial", encoding="utf-8")
    p = _fresh_paths(legacy, monkeypatch)
    assert not os.path.exists(str(stale))
    assert not os.path.exists(os.path.join(p.DATA_DIR, "junk.txt"))


def test_fresh_install_just_creates_the_new_dir(tmp_path, monkeypatch):
    p = _fresh_paths(tmp_path, monkeypatch)
    assert os.path.basename(p.DATA_DIR) == "Linguar Hub"
    assert os.path.isdir(p.DATA_DIR)


def test_empty_legacy_dir_is_not_treated_as_state(tmp_path, monkeypatch):
    """An empty shell from an aborted run must not win over the new dir."""
    (tmp_path / "EMS Automation").mkdir()
    p = _fresh_paths(tmp_path, monkeypatch)
    assert os.path.basename(p.DATA_DIR) == "Linguar Hub"
