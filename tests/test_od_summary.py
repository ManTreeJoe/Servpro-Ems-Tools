"""What is in the folder, without opening the folder.

Bounded on purpose: the audit already spends most of its 11 seconds
waiting on the share, and a full recursive walk per selected job would
put that cost straight back.
"""
import os

import audit_web


def _api():
    return audit_web.Api.__new__(audit_web.Api)


def _job(tmp_path):
    root = tmp_path / "Doe, Jane"
    (root / "EMS" / "PICS" / "Initial").mkdir(parents=True)
    (root / "EMS" / "DOCS").mkdir(parents=True)
    (root / "CONTENTS" / "PICS").mkdir(parents=True)
    for i in range(3):
        (root / "EMS" / "PICS" / "Initial" / f"p{i}.jpg").write_bytes(b"x")
    (root / "EMS" / "DOCS" / "auth.pdf").write_bytes(b"x")
    (root / "loose.txt").write_bytes(b"x")
    return str(root)


def test_it_reports_the_groups_and_their_counts(tmp_path):
    r = _api().od_summary(_job(tmp_path))
    assert r["ok"] is True
    names = {g["name"]: g for g in r["groups"]}
    assert set(names) == {"EMS", "CONTENTS"}
    subs = {s["name"]: s["files"] for s in names["EMS"]["subs"]}
    assert subs == {"PICS": 0, "DOCS": 1}


def test_loose_files_at_the_top_are_counted(tmp_path):
    assert _api().od_summary(_job(tmp_path))["files"] == 1


def test_empty_subfolders_are_still_listed(tmp_path):
    """"PICS (0)" IS the answer to "are the photos in yet?" — omitting it
    would read as though nothing were missing."""
    r = _api().od_summary(_job(tmp_path))
    ems = next(g for g in r["groups"] if g["name"] == "EMS")
    assert any(s["name"] == "PICS" and s["files"] == 0 for s in ems["subs"])


def test_it_stops_at_two_levels(tmp_path):
    """Third-level files are not counted — that is the bound that keeps
    this off the critical path."""
    root = _job(tmp_path)
    r = _api().od_summary(root)
    ems = next(g for g in r["groups"] if g["name"] == "EMS")
    pics = next(s for s in ems["subs"] if s["name"] == "PICS")
    assert pics["files"] == 0          # the 3 jpgs live one level deeper


def test_desktop_ini_is_not_a_file(tmp_path):
    root = _job(tmp_path)
    with open(os.path.join(root, "desktop.ini"), "w") as fh:
        fh.write("x")
    assert _api().od_summary(root)["files"] == 1


def test_a_missing_folder_is_an_error_not_a_crash():
    r = _api().od_summary(r"X:\nope\not\here")
    assert r["ok"] is False and r["groups"] == []


def test_a_blank_path_is_refused():
    assert _api().od_summary("")["ok"] is False


def test_the_directory_is_not_left_open(tmp_path):
    """A bare scandir loop holds the handle and Windows then refuses to
    rename the folder — the rule the codebase already has for scandir."""
    root = _job(tmp_path)
    _api().od_summary(root)
    os.rename(root, root + " renamed")


def test_it_is_capped(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    for i in range(60):
        (root / f"d{i:02d}").mkdir()
    assert len(_api().od_summary(str(root), max_dirs=10)["groups"]) <= 10
