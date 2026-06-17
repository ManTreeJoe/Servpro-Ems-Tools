"""Unit tests for sp_sync_state — OneDrive cloud-only detection.

Mocks `os.stat` to return synthetic `st_file_attributes` values so the
tests run on any OS regardless of OneDrive presence."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sp_sync_state as ss


class _FakeStat:
    """Stand-in for os.stat_result that exposes only the attribute
    field sp_sync_state inspects."""
    def __init__(self, file_attributes):
        self.st_file_attributes = file_attributes


# ── is_cloud_only ───────────────────────────────────────────────────────

def test_is_cloud_only_false_for_recall_on_data_access_alone(monkeypatch):
    """RECALL_ON_DATA_ACCESS (0x400000) is set on EVERY Files-On-Demand
    managed file — including files already downloaded to disk. By
    itself it must NOT count as cloud-only, otherwise the chip
    becomes permanent for any pulled file."""
    monkeypatch.setattr(
        ss.os, "stat",
        lambda p, **kw: _FakeStat(0x00400000))
    assert ss.is_cloud_only("/x/photo.jpg") is False


def test_is_cloud_only_true_for_offline_attribute(monkeypatch):
    monkeypatch.setattr(ss.os, "stat",
                        lambda p, **kw: _FakeStat(0x00001000))
    assert ss.is_cloud_only("/x/photo.jpg") is True


def test_is_cloud_only_true_for_recall_on_open(monkeypatch):
    """RECALL_ON_OPEN (0x40000) is the legacy-sync-client marker for
    a truly-not-on-disk file. Still counts as cloud-only."""
    monkeypatch.setattr(ss.os, "stat",
                        lambda p, **kw: _FakeStat(0x00040000))
    assert ss.is_cloud_only("/x/photo.jpg") is True


def test_is_cloud_only_false_for_regular_file(monkeypatch):
    # Just FILE_ATTRIBUTE_ARCHIVE (0x20) — normal locally-synced file.
    monkeypatch.setattr(ss.os, "stat",
                        lambda p, **kw: _FakeStat(0x20))
    assert ss.is_cloud_only("/x/photo.jpg") is False


def test_is_cloud_only_false_on_stat_error(monkeypatch):
    def _raise(_p, **kw):
        raise OSError("nope")
    monkeypatch.setattr(ss.os, "stat", _raise)
    assert ss.is_cloud_only("/x/photo.jpg") is False


def test_is_cloud_only_false_on_blank_path():
    assert ss.is_cloud_only("") is False


# ── count_cloud_only ────────────────────────────────────────────────────

def _make_tree(tmp_path):
    """Real on-disk tree the walker can iterate. Sync state is faked
    by patching is_cloud_only."""
    (tmp_path / "EMS").mkdir()
    (tmp_path / "EMS" / "PICS").mkdir()
    (tmp_path / "EMS" / "PICS" / "Initial").mkdir()
    (tmp_path / "EMS" / "PICS" / "Initial" / "1.jpg").write_bytes(b"x")
    (tmp_path / "EMS" / "PICS" / "Initial" / "2.jpg").write_bytes(b"x")
    (tmp_path / "EMS" / "PICS" / "Initial" / "3.jpg").write_bytes(b"x")
    # Hidden / dotfile should be skipped
    (tmp_path / "EMS" / "PICS" / "Initial" / ".DS_Store").write_bytes(b"x")
    # Contents/ subtree must be skipped per default skip list
    (tmp_path / "Contents").mkdir()
    (tmp_path / "Contents" / "inventory.xlsx").write_bytes(b"x")
    return tmp_path


def test_count_cloud_only_returns_zero_for_synced_tree(tmp_path,
                                                         monkeypatch):
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: False)
    r = ss.count_cloud_only(str(root))
    assert r["scanned"] is True
    assert r["unsynced"] == 0
    # 3 .jpgs (dotfile skipped + Contents subtree pruned)
    assert r["total"] == 3
    assert r["samples"] == []


def test_count_cloud_only_counts_placeholders(tmp_path, monkeypatch):
    root = _make_tree(tmp_path)
    cloud_paths = {
        str(root / "EMS" / "PICS" / "Initial" / "1.jpg"),
        str(root / "EMS" / "PICS" / "Initial" / "3.jpg"),
    }
    monkeypatch.setattr(ss, "is_cloud_only",
                         lambda p: p in cloud_paths)
    r = ss.count_cloud_only(str(root))
    assert r["unsynced"] == 2
    assert r["total"] == 3
    assert set(r["samples"]) == {"1.jpg", "3.jpg"}


def test_count_cloud_only_skips_contents_folder(tmp_path, monkeypatch):
    """Contents/ holds inventory work — never part of the audit's
    photo/form universe (mirrors `feedback_ems_vs_contents_scope`).
    `count_cloud_only` should respect that even if the user pointed
    at the property root."""
    root = _make_tree(tmp_path)
    # Mark every file as cloud-only so any inventory.xlsx leak shows up
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    r = ss.count_cloud_only(str(root))
    # 3 .jpgs only — inventory.xlsx in Contents/ should be excluded
    assert r["total"] == 3
    assert r["unsynced"] == 3
    assert "inventory.xlsx" not in r["samples"]


def test_count_cloud_only_respects_max_depth(tmp_path, monkeypatch):
    """A photo 5 levels deep won't surface when max_depth=2."""
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "deep.jpg").write_bytes(b"x")
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    shallow = ss.count_cloud_only(str(tmp_path), max_depth=2)
    deeper = ss.count_cloud_only(str(tmp_path), max_depth=10)
    assert shallow["total"] == 0
    assert deeper["total"] == 1


def test_count_cloud_only_not_scanned_for_missing_dir():
    r = ss.count_cloud_only("/definitely/not/a/real/path")
    assert r["scanned"] is False
    assert r["unsynced"] == 0


def test_summarize_empty_when_fully_synced(tmp_path, monkeypatch):
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: False)
    assert ss.summarize(str(root)) == ""


def test_summarize_text_when_unsynced(tmp_path, monkeypatch):
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    text = ss.summarize(str(root))
    assert text.startswith("⚠")
    assert "3 of 3" in text


def test_sample_cap(tmp_path, monkeypatch):
    """The samples list never exceeds _SAMPLE_CAP even when more files
    are cloud-only."""
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(25):
        (folder / f"f{i:02d}.jpg").write_bytes(b"x")
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    r = ss.count_cloud_only(str(folder))
    assert r["unsynced"] == 25
    assert len(r["samples"]) == ss._SAMPLE_CAP


# ── force_pull ──────────────────────────────────────────────────────────

def test_force_pull_reads_one_byte_per_cloud_only_file(tmp_path,
                                                         monkeypatch):
    """Every cloud-only file gets opened and read once. Real files
    on disk are skipped — only flagged ones are pulled."""
    root = _make_tree(tmp_path)
    cloud_paths = {
        str(root / "EMS" / "PICS" / "Initial" / "1.jpg"),
        str(root / "EMS" / "PICS" / "Initial" / "2.jpg"),
    }
    monkeypatch.setattr(ss, "is_cloud_only",
                         lambda p: p in cloud_paths)
    r = ss.force_pull(str(root))
    assert r["attempted"] == 2
    assert r["pulled"] == 2
    assert r["failed"] == 0


def test_force_pull_no_op_when_all_synced(tmp_path, monkeypatch):
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: False)
    r = ss.force_pull(str(root))
    assert r["attempted"] == 0
    assert r["pulled"] == 0


def test_force_pull_counts_failures(tmp_path, monkeypatch):
    """OSErrors during the 1-byte read count toward `failed`, not
    `pulled`. The walk continues — one bad file doesn't stop the rest."""
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    real_open = open

    def fake_open(path, *args, **kwargs):
        # Make the file at path "2.jpg" raise; let everything else
        # actually open via the real builtin.
        if path.endswith("2.jpg"):
            raise OSError("network gone")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr("builtins.open", fake_open)
    r = ss.force_pull(str(root))
    assert r["attempted"] == 3
    assert r["pulled"] == 2
    assert r["failed"] == 1


def test_force_pull_progress_callback(tmp_path, monkeypatch):
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    calls: list[tuple] = []
    ss.force_pull(str(root),
                   progress_cb=lambda done, total, name:
                       calls.append((done, total, name)))
    assert len(calls) == 3
    assert calls[0][1] == 3                  # total reported consistently
    assert calls[-1][0] == 3                 # final done == total


def test_force_pull_respects_skip_names(tmp_path, monkeypatch):
    """Contents/ stays untouched even if every file is marked
    cloud-only — same scope rule as count_cloud_only."""
    root = _make_tree(tmp_path)
    monkeypatch.setattr(ss, "is_cloud_only", lambda p: True)
    r = ss.force_pull(str(root))
    assert r["attempted"] == 3            # 3 .jpgs, not 4
