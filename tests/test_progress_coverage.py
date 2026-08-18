"""Every tool that makes you wait says so.

Two layers, because the panels are not alike:

  * Panels with a real progress STREAM bind the bar to it, so you get a
    position — disputes, pipeline, hygiene, wc_audit, plus the audit /
    SP / import streams already wired.
  * Everything else gets a generic "this is taking a while" bar from the
    iframe shim, which is the one place every panel's API call passes
    through. That covers APA, Job Notes, KPI and Settings without
    guessing which of their calls are slow.

The generic bar is deliberately modest: it waits 400ms so fast calls
don't flash it, and it refuses to arm while a real stream is already
showing a position — an indeterminate stripe replacing "62%" is a
downgrade, not a feature.
"""
import io
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    return io.open(os.path.join(_ROOT, *p), encoding="utf-8").read()


def _panels():
    return sorted(d for d in os.listdir(_ROOT) if d.endswith("_web_assets"))


def _can_draw(html):
    """progress_bar draws into a status bar, falling back to #status."""
    return ("statusbar" in html) or ('id="status"' in html)


# ── coverage ─────────────────────────────────────────────────────────
def test_every_panel_that_can_show_a_bar_loads_it():
    """A panel with somewhere to draw and no bar is a panel that makes
    you wait in silence."""
    missing = []
    for d in _panels():
        html = _read(d, "index.html")
        if _can_draw(html) and "progress_bar.js" not in html:
            missing.append(d)
    assert not missing, f"can draw a bar but never loads it: {missing}"


def test_the_shim_looks_up_the_bar_lazily():
    """Script order between progress_bar.js and iframe_shim.js differs
    across panels — audit loads the shim first, disputes loads the bar
    first — and it must not matter. `_track` reads window.Progress on
    every CALL rather than capturing it at load, so a panel that happens
    to load them the other way round still gets a bar.

    (This started life as a test that the bar must load first. It was
    asserting an invented rule: the code never needed the order, and
    reordering three working files to satisfy the test would have been
    churn dressed up as a fix.)"""
    js = _read("web_shared", "iframe_shim.js")
    body = js[js.index("function _track"):]
    body = body[:body.index(chr(10) + "    }")]
    assert "const P = window.Progress;" in body, "must read it per call"
    head = js[:js.index("function _track")]
    assert "window.Progress" not in head, "must not capture it at load"


@pytest.mark.parametrize("panel,progress,done", [
    ("disputes", "disputes:sync-progress", "disputes:sync-done"),
    ("pipeline", "pipeline:sync-progress", "pipeline:sync-done"),
    ("hygiene", "hygiene:scan-progress", "hygiene:scan-done"),
])
def test_streaming_panels_bind_their_stream(panel, progress, done):
    js = _read(f"{panel}_web_assets", "app.js")
    assert f'Progress.bind("{progress}", "{done}")' in js


def test_wc_audit_binds_its_inline_script():
    """It has no app.js — the panel's JS lives in the page."""
    html = _read("wc_audit_web_assets", "index.html")
    assert 'Progress.bind("wc:classify-progress", "wc:classify-done")' in html


def test_resources_drives_the_bar_from_its_poll():
    """It polls instead of emitting events, so it sets the bar directly
    — same bar, same meaning."""
    js = _read("resources_web_assets", "app.js")
    assert "Progress.set(d.done, d.total)" in js
    assert "Progress.done()" in js and "Progress.fail()" in js


# ── the generic bar, and its manners ─────────────────────────────────
def test_the_shim_tracks_slow_calls():
    js = _read("web_shared", "iframe_shim.js")
    assert "_track(" in js and "window.Progress" in js


def test_the_generic_bar_waits_before_showing():
    """A bar that flashes on every fast call is noise, and noise is what
    makes people stop reading it."""
    js = _read("web_shared", "iframe_shim.js")
    body = js[js.index("function _track"):]
    body = body[:body.index("\n    }")]
    assert "SLOW_MS = 1200" in _read("web_shared", "iframe_shim.js")


def test_the_generic_bar_never_stomps_a_real_stream():
    """An indeterminate stripe replacing "62%" is a downgrade."""
    js = _read("web_shared", "iframe_shim.js")
    body = js[js.index("function _track"):]
    body = body[:body.index("\n    }")]
    assert "P.active()" in body
    assert "P.indeterminate()" in body, "and only clears the bar it armed"


def test_the_generic_bar_refcounts():
    """Ten overlapping calls are one bar, not ten fighting over it."""
    js = _read("web_shared", "iframe_shim.js")
    assert "_slow += 1" in js and "_slow - 1" in js


def test_a_rejected_call_still_clears_the_bar():
    """Otherwise one failed call leaves the bar running forever."""
    js = _read("web_shared", "iframe_shim.js")
    assert "p.then(settle, settle)" in js


def test_tracking_returns_the_original_promise():
    """Returning the .then() chain instead would swallow rejections that
    callers handle themselves."""
    js = _read("web_shared", "iframe_shim.js")
    body = js[js.index("function _track"):]
    body = body[:body.index("\n    }")]
    assert body.rstrip().endswith("return p;")


def test_the_bar_exposes_the_state_the_shim_asks_for():
    js = _read("web_shared", "progress_bar.js")
    assert "active: function" in js and "indeterminate: function" in js


def _bulk_verbs():
    """Read the shim's own verb list so the test and the code cannot
    drift apart."""
    import re
    js = _read("web_shared", "iframe_shim.js")
    i = js.index("const BULK_VERBS = [")
    block = js[i:js.index("]", i)]
    verbs = re.findall(r'"([^"]+)"', block)
    assert verbs, "could not read the verb list from the shim"
    return verbs


def _is_bulk(name):
    return any(str(name).startswith(v) for v in _bulk_verbs())


def test_only_bulk_verbs_get_a_bar():
    """The first version was a timing heuristic — "anything slower than
    400ms" — and it caught ticking a checklist item, a ~600ms Trello
    write. That is an ACTION, not a load: the checkbox and the status
    line already say it is happening, and a bar on every tick trains
    people to stop reading the bar, which costs you the real ones too.

    Default is silence now. An unlisted slow method gets no bar, which
    is exactly where it started."""
    js = _read("web_shared", "iframe_shim.js")
    body = js[js.index("function _track"):]
    body = body[:body.index(chr(10) + "    }")]
    assert "isBulk(name)" in body, "an allowlist, not a timing guess"


@pytest.mark.parametrize("name", [
    "toggle_checklist_item", "add_checklist_item", "delete_checklist_item",
    "post_comment", "set_folder_path", "pin_trello", "reaudit_one",
    "get_card_comments", "search", "open_file", "last_audit",
    "companycam_pin", "copy_path", "save_job_settings",
])
def test_ordinary_actions_stay_silent(name):
    """These are the ones that made it feel random."""
    assert not _is_bulk(name), f"{name} must not raise a loading bar"


@pytest.mark.parametrize("name", [
    "sync_from_trello", "scan_workspace", "rebuild", "classify_rows",
    "import_zip", "pull_photos", "generate_snapshot", "run_audit_day",
    "reconcile_with_trello", "backfill_carriers", "export_pdf",
])
def test_real_loads_still_get_one(name):
    assert _is_bulk(name), f"{name} is a load and should show a bar"
