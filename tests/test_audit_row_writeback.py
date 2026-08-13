"""A re-audited row must land in the list the job actually came from.

The complaint was "it takes a full reload of the tool to clear forms —
normally this would be done upon import". The import DID re-audit, and
the backend answered correctly; the browser threw the answer away.

A job pulled up through Search lives in `state.oneoffHits`, not
`state.rows` — and Search is the default landing tab. Every one of the
sixteen re-audit call sites spliced into `state.rows` only, so the
findIndex missed, the fresh row was discarded, and `renderDetail()` ->
`findRowByKey()` (which reads `oneoffHits` FIRST) kept repainting the
stale `form_issues`. Reloading the tool cleared `oneoffHits`, which is
why a reload "fixed" it.

`findRowByKey` was already the rule for READS. These tests hold the same
line for WRITES, since the failure is invisible in any single-file
review — each site looks perfectly reasonable on its own.
"""
import io
import os
import re

import pytest


_ASSETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "audit_web_assets")
_APP_JS = os.path.join(_ASSETS, "app.js")


@pytest.fixture(scope="module")
def app_js():
    return io.open(_APP_JS, encoding="utf-8").read()


def test_no_row_is_spliced_into_state_rows_by_client_name(app_js):
    """The exact pattern that caused the bug, in all sixteen places."""
    bad = re.findall(r"state\.rows\.findIndex\(\(x\) => x\.client", app_js)
    assert not bad, (
        f"{len(bad)} re-audit site(s) still splice into state.rows by client "
        "name — a job found via Search lives in state.oneoffHits and its "
        "fresh row will be silently dropped. Use applyRow().")


def test_no_direct_assignment_into_state_rows(app_js):
    """Catches the same mistake written a different way."""
    assert not re.findall(r"state\.rows\[\s*ix\s*\]\s*=", app_js), (
        "assign rows through applyRow() so one-off hits stay in sync")


def test_apply_row_updates_both_lists(app_js):
    body = _fn_body(app_js, "applyRow")
    assert "state.oneoffHits" in body and "state.rows" in body, (
        "applyRow must write through to BOTH lists — the one-off list is "
        "the one the detail pane reads first")


def test_apply_row_matches_on_row_key_not_client(app_js):
    """Multi-unit rows share a client name.

    "Avila Apartments::1413" and "::1416" are two rows with one client, so
    matching on client alone overwrote the first unit with another unit's
    audit — a wrong answer, not just a stale one.
    """
    body = _fn_body(app_js, "applyRow")
    assert "rowKey(x) === key" in body, (
        "match on rowKey; client name is ambiguous for multi-unit jobs")
    key_at = body.index("rowKey(x) === key")
    client_at = body.find("x.client === row.client")
    assert client_at == -1 or client_at > key_at, (
        "the client-name match is a FALLBACK — rowKey has to be tried first")


def test_every_reaudit_result_goes_through_apply_row(app_js):
    """Sixteen sites, one helper. A new one must not reinvent the splice."""
    calls = len(re.findall(r"pywebview\.api\.reaudit_one\(", app_js))
    applies = len(re.findall(r"\bapplyRow\(", app_js)) - 1   # minus the def
    assert calls == 16, f"expected 16 reaudit_one call sites, found {calls}"
    assert applies >= calls, (
        f"{calls} re-audits but only {applies} applyRow() calls — some site "
        "is handling its own writeback again")


def test_the_import_paths_repaint_unconditionally(app_js):
    """The Incoming-downloads path used to skip the repaint on a miss.

    `if (ix >= 0) { state.rows[ix] = re.row; renderAll(); }` — when the
    row wasn't in state.rows it drew nothing at all, so an import from
    that panel left even the status text stale.
    """
    assert "if (ix >= 0) { state.rows[ix]" not in app_js


def _fn_body(src, name):
    start = src.index(f"function {name}(")
    depth, i, opened = 0, src.index("{", start), False
    while i < len(src):
        if src[i] == "{":
            depth += 1
            opened = True
        elif src[i] == "}":
            depth -= 1
            if opened and depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError(f"could not find the body of {name}()")
