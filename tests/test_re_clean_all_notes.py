"""One-shot migration that re-runs every saved note through the current
Trello cleanup pipeline so older notes pick up later parser fixes (the
trigger case: (edited) suffix recognition added in 2026-04).

Subtle invariant pinned here: relative timestamps in old notes ('2 hours
ago') get resolved against the FILE'S MTIME, not today's clock — otherwise
the migration silently rewrites old timestamps as 'now minus 2 hours'."""
import os
import time
from datetime import datetime

import job_notes_gui


def _write_note(notes_root, year, client, text, mtime=None):
    """Write a note file and optionally backdate it to a specific mtime."""
    os.makedirs(os.path.join(notes_root, year), exist_ok=True)
    path = os.path.join(notes_root, year, f"{client}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_no_notes_dir_returns_zero(tmp_path):
    changed, total = job_notes_gui.re_clean_all_notes(
        notes_root=str(tmp_path / "missing"))
    assert (changed, total) == (0, 0)


def test_empty_notes_dir(tmp_path):
    changed, total = job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    assert (changed, total) == (0, 0)


def test_already_clean_note_unchanged(tmp_path):
    """Note already in cleaned form (no Trello header) → returned as-is."""
    text = "Plain notes\nNo Trello content here.\n"
    _write_note(str(tmp_path), "2026", "Smith John", text)
    changed, total = job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    assert total == 1
    assert changed == 0


def test_raw_trello_paste_with_edited_gets_cleaned(tmp_path):
    """The trigger case: a note that was pasted before (edited) was
    recognized would have stayed in raw Trello form. Re-clean fixes it."""
    raw = (
        "Mark Escobar Apr 27, 2026, 4:03 PM (edited)\n"
        "Edited my reply.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    path = _write_note(str(tmp_path), "2026", "Smith John", raw)
    changed, total = job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    assert (changed, total) == (1, 1)
    with open(path, encoding="utf-8") as f:
        new = f.read()
    # The boilerplate is gone
    assert "Reply" not in new
    assert "Add link as attachment" not in new
    # The edited marker is preserved
    assert "(edited)" in new
    # Header rendered with bullet separator
    assert "Mark Escobar · Apr 27, 2026, 4:03 PM (edited)" in new


def test_relative_time_uses_file_mtime_not_now(tmp_path):
    """Critical: an old note saying '2 hours ago' must resolve relative
    to when it was saved, not today. Backdating the file to 30 days ago
    and re-cleaning should produce a timestamp ~30 days ago, not today."""
    raw = (
        "victoria 2 hours ago\n"
        "Old comment.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    path = _write_note(str(tmp_path), "2026", "Smith John", raw)
    # Backdate to 30 days ago at 10:00 AM.
    thirty_days_ago = time.time() - 30 * 86400
    os.utime(path, (thirty_days_ago, thirty_days_ago))
    job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    with open(path, encoding="utf-8") as f:
        new = f.read()
    # The output should reference a date around 30 days ago, NOT today.
    today = datetime.now()
    today_marker = f"{today.strftime('%b')} {today.day}, {today.year}"
    assert today_marker not in new, (
        f"Migration used today's clock instead of the file mtime — "
        f"output still mentions '{today_marker}'\n\n{new}")


def test_modified_files_are_backed_up(tmp_path):
    """Every overwrite must drop a timestamped .bak so the user can
    revert any individual file."""
    raw = (
        "Mark Escobar Apr 27, 2026, 4:03 PM (edited)\n"
        "Body.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    path = _write_note(str(tmp_path), "2026", "Smith John", raw)
    job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    parent = os.path.dirname(path)
    baks = [f for f in os.listdir(parent)
            if f.startswith("Smith John.md.") and f.endswith(".bak")]
    assert len(baks) == 1
    # Backup contains the ORIGINAL raw text (not the cleaned version)
    with open(os.path.join(parent, baks[0]), encoding="utf-8") as f:
        assert f.read() == raw


def test_unchanged_files_get_no_backup(tmp_path):
    """No backup spam for files that don't actually change."""
    text = "Plain notes\nNothing to clean.\n"
    path = _write_note(str(tmp_path), "2026", "Smith John", text)
    job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    parent = os.path.dirname(path)
    baks = [f for f in os.listdir(parent) if f.endswith(".bak")]
    assert baks == []


def test_progress_callback_fires_per_file(tmp_path):
    """progress_cb gets called once per file with a status string —
    callers can render a progress UI from it."""
    _write_note(str(tmp_path), "2026", "Smith",
        "Mark Escobar Apr 27, 2026, 4:03 PM (edited)\nBody.\n"
        "•\nReply\n•\nAdd link as attachment")
    _write_note(str(tmp_path), "2026", "Doe", "Plain.\n")
    seen = []
    job_notes_gui.re_clean_all_notes(
        notes_root=str(tmp_path),
        progress_cb=lambda y, fn, st: seen.append((y, fn, st)))
    statuses = sorted(s for _, _, s in seen)
    assert statuses == ["unchanged", "updated"]


def test_walks_multiple_year_dirs(tmp_path):
    _write_note(str(tmp_path), "2025", "Old Client",
        "Mark Escobar Apr 27, 2025, 4:03 PM (edited)\nold body\n"
        "•\nReply\n•\nAdd link as attachment")
    _write_note(str(tmp_path), "2026", "New Client",
        "Mark Escobar Apr 27, 2026, 4:03 PM (edited)\nnew body\n"
        "•\nReply\n•\nAdd link as attachment")
    changed, total = job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    assert total == 2
    assert changed == 2


def test_non_md_files_ignored(tmp_path):
    """Backup files (.bak) and stray non-.md files must be skipped so
    repeated migrations don't cascade-rewrite the backups."""
    os.makedirs(os.path.join(str(tmp_path), "2026"), exist_ok=True)
    bak = os.path.join(str(tmp_path), "2026", "Old.md.20260101-120000.bak")
    with open(bak, "w", encoding="utf-8") as f:
        f.write("Old raw content with • Reply chrome")
    junk = os.path.join(str(tmp_path), "2026", "readme.txt")
    with open(junk, "w", encoding="utf-8") as f:
        f.write("not a note")
    changed, total = job_notes_gui.re_clean_all_notes(notes_root=str(tmp_path))
    assert (changed, total) == (0, 0)
