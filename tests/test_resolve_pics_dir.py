"""resolve_pics_dir picks PICS or Photos depending on what exists.

Older jobs use "Photos" instead of "PICS"; the audit pipeline must find
photos either way so the missing-photos check doesn't false-positive.
"""
import os
from audit_logic import resolve_pics_dir


def test_prefers_pics_when_both_exist(tmp_path):
    (tmp_path / "PICS").mkdir()
    (tmp_path / "Photos").mkdir()
    assert resolve_pics_dir(str(tmp_path)) == os.path.join(str(tmp_path), "PICS")


def test_falls_back_to_photos(tmp_path):
    (tmp_path / "Photos").mkdir()
    assert resolve_pics_dir(str(tmp_path)) == os.path.join(str(tmp_path), "Photos")


def test_returns_pics_when_neither_exists(tmp_path):
    # Caller's missing-photos message stays consistent ("PICS missing", not
    # "Photos missing") for jobs that have no photo folder at all.
    assert resolve_pics_dir(str(tmp_path)) == os.path.join(str(tmp_path), "PICS")


def test_pics_only(tmp_path):
    (tmp_path / "PICS").mkdir()
    assert resolve_pics_dir(str(tmp_path)) == os.path.join(str(tmp_path), "PICS")


def test_empty_base_returns_empty():
    assert resolve_pics_dir("") == ""


def test_none_base_returns_empty():
    assert resolve_pics_dir(None) == ""
