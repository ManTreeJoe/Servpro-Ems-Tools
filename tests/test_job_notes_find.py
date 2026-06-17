"""Find-in-note bar — search within the loaded client's note text.

Pinning the find behavior here so future edits to the editor pane don't
silently break the highlight, the count, or the ↑/↓ wrap-around (each
of which is easy to regress when refactoring Tk Text tag logic)."""
import pytest

import job_notes_gui


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    """Build a JobNotesApp pointed at a tmp tree (no real X: drive)."""
    monkeypatch.setattr(job_notes_gui, "AUDIT_BASE", str(tmp_path / "ie"))
    notes_root = tmp_path / "notes"
    notes_root.mkdir()
    monkeypatch.setattr(job_notes_gui, "_NOTES_ROOT", str(notes_root))
    monkeypatch.setattr(job_notes_gui.persistence,
                        "get_folder_path", lambda _name: None)
    a = job_notes_gui.JobNotesApp(tk_root)
    # Put text in the editor so we have something to search.
    a._textarea.config(state="normal")
    a._textarea.insert("1.0",
        "Demo on Friday with Vince\n"
        "Mold prep scheduled tomorrow\n"
        "Demo continues Saturday\n"
        "Another demo line for Vince")
    yield a
    try:
        a.destroy()
    except Exception:
        pass


def test_find_bar_hidden_by_default(app):
    """The find bar shouldn't take editor space until the user opens it."""
    assert app._find_bar.winfo_manager() == ""


def test_toggle_shows_and_hides(app):
    app._toggle_find_bar()
    assert app._find_bar.winfo_manager() != ""
    app._toggle_find_bar()
    assert app._find_bar.winfo_manager() == ""


def test_force_true_keeps_open(app):
    """Passing force=True when already open should keep it open, not toggle."""
    app._toggle_find_bar(True)
    assert app._find_bar.winfo_manager() != ""
    app._toggle_find_bar(True)
    assert app._find_bar.winfo_manager() != ""


def test_search_finds_all_matches(app):
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()  # bypass the after() debounce
    # 'demo' appears 3 times (Demo, Demo, demo)
    assert len(app._find_matches) == 3
    assert "of 3" in app._find_count.cget("text")


def test_search_is_case_insensitive(app):
    """'DEMO' should still find 'Demo' lines — users won't type the
    exact case from a Trello dump."""
    app._toggle_find_bar(True)
    app._find_var.set("DEMO")
    app._run_find()
    assert len(app._find_matches) == 3


def test_search_empty_query_clears_highlights(app):
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    assert app._find_matches  # populated
    app._find_var.set("")
    app._run_find()
    assert app._find_matches == []
    assert app._find_count.cget("text") == ""


def test_no_matches_shows_message(app):
    app._toggle_find_bar(True)
    app._find_var.set("xyzzy_no_such_text")
    app._run_find()
    assert app._find_matches == []
    assert "no matches" in app._find_count.cget("text")


def test_step_forward_wraps_around(app):
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    start = app._find_current
    n = len(app._find_matches)
    for _ in range(n):
        app._find_step(+1)
    # After n forward steps from any starting point, we should land back
    # on the same match (wrap-around modulo n).
    assert app._find_current == start


def test_step_backward_wraps_around(app):
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    # Step back from the first match → last match.
    app._find_current = 0
    app._find_step(-1)
    assert app._find_current == len(app._find_matches) - 1


def test_close_clears_tags(app):
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    assert app._find_matches
    app._toggle_find_bar(False)
    # Tags removed, state reset
    assert app._textarea.tag_ranges("find_match") == ()
    assert app._textarea.tag_ranges("find_current") == ()
    assert app._find_matches == []


def test_current_match_highlight_is_a_single_range(app):
    """Only one 'find_current' tag range at a time — stepping should
    move it, not accumulate."""
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    app._find_step(+1)
    ranges = app._textarea.tag_ranges("find_current")
    # Tag ranges come back as pairs (start, end) — exactly one pair.
    assert len(ranges) == 2


def test_load_client_clears_stale_highlights(app, monkeypatch):
    """When a different client loads with the find bar closed, leftover
    highlights from the previous note must be cleared."""
    app._toggle_find_bar(True)
    app._find_var.set("demo")
    app._run_find()
    assert app._textarea.tag_ranges("find_match") != ()
    # Hide the bar (which clears tags), then load a different client to
    # confirm the cleared state survives the load path.
    app._toggle_find_bar(False)
    # Stub load_note so _load_client doesn't try to read disk
    monkeypatch.setattr(job_notes_gui, "load_note", lambda _y, _c: "fresh text")
    app._dirty = False  # skip the unsaved-changes prompt
    app._load_client("2026 EMS Files", "Other Client")
    assert app._textarea.tag_ranges("find_match") == ()
