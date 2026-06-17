"""Markdown rendering inside the Job Notes editor.

The editor stores notes as plain markdown but visually styles common
markers in place — headers get bigger/bolder, **bold** and *italic*
spans get the right font weight, `code` gets a mono background, and the
markers themselves are elided so the pane reads like Notion / GitHub
preview rather than raw text.

Pinning behavior here so future regex tweaks don't silently drop the
elision (which would be the most-noticed regression — punctuation
suddenly showing back up in every note)."""
import pytest

import job_notes_gui


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(job_notes_gui, "AUDIT_BASE", str(tmp_path / "ie"))
    notes_root = tmp_path / "notes"
    notes_root.mkdir()
    monkeypatch.setattr(job_notes_gui, "_NOTES_ROOT", str(notes_root))
    monkeypatch.setattr(job_notes_gui.persistence,
                        "get_folder_path", lambda _name: None)
    a = job_notes_gui.JobNotesApp(tk_root)
    a._textarea.config(state="normal")
    yield a
    try:
        a.destroy()
    except Exception:
        pass


def _set_text(app, text):
    app._textarea.delete("1.0", "end")
    app._textarea.insert("1.0", text)
    app._apply_md_styles()


def test_h1_styles_full_line(app):
    _set_text(app, "# Demo today")
    # md_h1 covers the whole line
    ranges = app._textarea.tag_ranges("md_h1")
    assert len(ranges) == 2  # one (start, end) pair
    # md_h2 / md_h3 should NOT also tag this line
    assert app._textarea.tag_ranges("md_h2") == ()
    assert app._textarea.tag_ranges("md_h3") == ()


def test_h2_distinct_from_h1(app):
    _set_text(app, "## Subsection")
    assert app._textarea.tag_ranges("md_h2") != ()
    assert app._textarea.tag_ranges("md_h1") == ()


def test_h3_distinct_from_h2(app):
    _set_text(app, "### Tertiary")
    assert app._textarea.tag_ranges("md_h3") != ()
    assert app._textarea.tag_ranges("md_h2") == ()


def test_header_marker_is_elided(app):
    """The `# ` part of `# Title` gets the md_marker tag (elide=True),
    so the user sees just 'Title'."""
    _set_text(app, "# Title here")
    # md_marker covers exactly the "# " (two chars: # + space)
    ranges = app._textarea.tag_ranges("md_marker")
    assert len(ranges) == 2
    # The covered text is "# "
    start, end = ranges
    covered = app._textarea.get(start, end)
    assert covered == "# "


def test_h2_marker_is_two_hashes_plus_space(app):
    _set_text(app, "## Subhead")
    ranges = app._textarea.tag_ranges("md_marker")
    start, end = ranges
    assert app._textarea.get(start, end) == "## "


def test_bold_styles_inner_content(app):
    _set_text(app, "this is **bold** text")
    # md_bold covers exactly "bold" (4 chars)
    bold_ranges = app._textarea.tag_ranges("md_bold")
    assert len(bold_ranges) == 2
    assert app._textarea.get(*bold_ranges) == "bold"


def test_bold_markers_elided(app):
    """Two `**` markers per bold span; both get md_marker."""
    _set_text(app, "this is **bold** text")
    marker_ranges = app._textarea.tag_ranges("md_marker")
    # Two pairs (open + close marker), so 4 indices.
    assert len(marker_ranges) == 4
    # Each marker covers "**" (2 chars)
    open_text = app._textarea.get(marker_ranges[0], marker_ranges[1])
    close_text = app._textarea.get(marker_ranges[2], marker_ranges[3])
    assert open_text == "**"
    assert close_text == "**"


def test_italic_does_not_match_inside_bold(app):
    """`**bold**` should produce md_bold, NOT two md_italic spans for
    the inner asterisks. The italic regex's negative look-around is the
    safety net here."""
    _set_text(app, "**bold**")
    assert app._textarea.tag_ranges("md_bold") != ()
    assert app._textarea.tag_ranges("md_italic") == ()


def test_italic_matches_single_asterisks(app):
    _set_text(app, "*italic* word")
    italic_ranges = app._textarea.tag_ranges("md_italic")
    assert len(italic_ranges) == 2
    assert app._textarea.get(*italic_ranges) == "italic"


def test_code_styles_and_elides_backticks(app):
    _set_text(app, "run `pytest` now")
    code_ranges = app._textarea.tag_ranges("md_code")
    assert len(code_ranges) == 2
    assert app._textarea.get(*code_ranges) == "pytest"
    # Both backticks elided (2 marker pairs)
    marker_ranges = app._textarea.tag_ranges("md_marker")
    assert len(marker_ranges) == 4


def test_bullet_line_gets_indent_tag(app):
    _set_text(app, "- first\n- second")
    bullet_ranges = app._textarea.tag_ranges("md_bullet")
    # Two bullet lines → two (start, end) pairs → 4 indices
    assert len(bullet_ranges) == 4


def test_star_bullet_also_recognized(app):
    """GitHub markdown allows `* ` as a bullet too; we accept both."""
    _set_text(app, "* one\n* two")
    bullet_ranges = app._textarea.tag_ranges("md_bullet")
    assert len(bullet_ranges) == 4


def test_apply_md_styles_clears_stale_tags(app):
    """When the buffer changes, old marker tags must come off — otherwise
    deleted markdown leaves dangling formatted regions."""
    _set_text(app, "# Old header")
    assert app._textarea.tag_ranges("md_h1") != ()
    _set_text(app, "plain text")
    assert app._textarea.tag_ranges("md_h1") == ()
    assert app._textarea.tag_ranges("md_marker") == ()


def test_empty_buffer_doesnt_crash(app):
    """Tagging an empty buffer must not raise."""
    _set_text(app, "")
    # No tags expected
    for t in ("md_h1", "md_h2", "md_h3", "md_bold",
              "md_italic", "md_code", "md_bullet", "md_marker"):
        assert app._textarea.tag_ranges(t) == ()


def test_multiple_styles_in_one_buffer(app):
    """Mix of header + bold + bullet — each gets its own tag without
    stepping on the others."""
    _set_text(app,
              "# Today\n"
              "- demo with **Vince**\n"
              "- mold prep `4/30`")
    assert app._textarea.tag_ranges("md_h1") != ()
    assert app._textarea.tag_ranges("md_bullet") != ()
    assert app._textarea.tag_ranges("md_bold") != ()
    assert app._textarea.tag_ranges("md_code") != ()


def test_italic_does_not_match_bullet_dash(app):
    """`- foo` is a bullet, not italic — italic needs a closing `*`
    on the same line, which this lacks."""
    _set_text(app, "- just a bullet item")
    assert app._textarea.tag_ranges("md_italic") == ()
    assert app._textarea.tag_ranges("md_bullet") != ()
