"""Long jobs show how far along they are, not just that they're alive.

The CompanyCam pull already worked this way — a bar riding the same
stream as the status text. Three other long jobs were emitting progress
and never reaching the bar:

  * the audit run itself — streamed {i, n, client} into a text label only
  * the SharePoint enrichment pass — runs 30-120s AFTER audit:done, the
    longest stretch in the panel, and the only sign it was alive was rows
    quietly changing
  * imports — HEIC conversion streamed {done, total} to a button caption

The text says WHICH job; the bar says how much is left. On a 300-row day
those are different questions, and only one of them decides whether you
wait or go do something else.
"""
import io
import os

import pytest

import audit_web


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


@pytest.fixture(scope="module")
def audit_js():
    return _read("audit_web_assets", "app.js")


@pytest.fixture(scope="module")
def bar_js():
    return _read("web_shared", "progress_bar.js")


# ── every long stream reaches the bar ────────────────────────────────
@pytest.mark.parametrize("progress,done", [
    ("sp:pull-progress", "sp:pull-done"),
    ("audit:progress", "audit:done"),
    ("audit:sp_update", "audit:sp_done"),
    ("import:progress", "import:done"),
])
def test_the_audit_panel_binds_the_bar(audit_js, progress, done):
    assert f'Progress.bind("{progress}", "{done}")' in audit_js


def test_the_snapshot_panel_binds_its_import(audit_js):
    js = _read("snapshot_web_assets", "app.js")
    assert 'Progress.bind("import:progress", "import:done")' in js


# ── the two counting vocabularies ────────────────────────────────────
def test_bind_accepts_both_payload_shapes(bar_js):
    """These streams were written at different times: {done,total} for
    the pulls and imports, {i,n} for the audit. Accepting both is what
    makes wiring a new one a single line rather than a payload change on
    the Python side."""
    body = bar_js[bar_js.index("bind: function"):]
    body = body[:body.index("window.addEventListener(doneEvent")]
    assert "d.done != null" in body and "d.i" in body
    assert "d.total != null" in body and "d.n" in body


def test_an_unknown_total_still_shows_movement(bar_js):
    """Progress.set falls back to the indeterminate stripe rather than
    drawing a 0% bar, which reads as stalled."""
    body = bar_js[bar_js.index("set: function"):]
    body = body[:body.index("done: function")]
    assert "Progress.start()" in body


# ── every stream must be closed ──────────────────────────────────────
def test_the_import_stream_has_a_done_event():
    """A bar bound to a progress event with no done event stops at
    whatever fraction it reached and stays there — which reads as still
    working long after the import finished."""
    src = _read("audit_web.py")
    assert "def _emit_import_done" in src
    assert "'import:done'" in src


def test_a_failed_import_still_closes_the_bar():
    """Especially on failure: a bar frozen at 60% is the worst outcome,
    because it says the work is continuing when it has stopped."""
    src = _read("audit_web.py")
    body = src[src.index("def do_import"):]
    body = body[:body.index("def ", body.index("_emit_import_done(True)"))]
    assert "_emit_import_done(False)" in body


def test_the_sp_pass_reports_its_position():
    """It had no counts at all — the pass emitted per row with no idea
    how many rows there were."""
    src = _read("audit_web.py")
    body = src[src.index("def _spawn_sp_enrichment_pass"):]
    body = body[:body.index("\n    def ", 10)] if "\n    def " in body[10:] else body
    assert "_sp_total" in body and "_sp_i" in body
    assert '"done":' in body and '"total":' in body


def test_the_sp_done_event_says_it_succeeded():
    """bind() paints red unless the done detail says ok — an empty
    detail would have finished every SP pass in the failure colour."""
    src = _read("audit_web.py")
    assert "'audit:sp_done', {detail: {" in src
    i = src.index("'audit:sp_done'")
    assert "ok" in src[i:i + 120]


# ── the counts have to be real ───────────────────────────────────────
def test_sp_total_counts_only_rows_that_emit():
    """Counting rows that are skipped would leave the bar short of 100%
    on every run."""
    src = _read("audit_web.py")
    i = src.index("_sp_total = ")
    line = src[i:src.index("\n", i)]
    assert 'get("client")' in line, "must match the loop's own skip rule"
