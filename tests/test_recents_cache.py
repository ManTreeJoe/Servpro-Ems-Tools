"""The Search tab's recents survive closing the app.

They accumulate as you pull jobs up, and quitting threw the lot away —
you came back and re-typed the same names. PanelState already persists
per-panel state to state.json on this machine, so the list rides along
with the tab and filter that were already remembered.

The part that needed care is WHAT gets saved. A row carries "3 missing"
and a photo count, and those go stale the moment someone drops a form in
overnight. Restoring them would show yesterday's answer as though it
were today's — the exact failure this panel keeps having — so only the
job's IDENTITY is saved and the numbers are re-audited on the way back.
"""
import io
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def js():
    return io.open(os.path.join(_ROOT, "audit_web_assets", "app.js"),
                   encoding="utf-8").read()


def _fn(js, name):
    body = js[js.index(f"function {name}("):]
    return body[:body.index(chr(10) + "}")]


# ── what gets saved ──────────────────────────────────────────────────
def test_only_identity_is_saved(js):
    """Not the audit numbers. This is the whole point."""
    body = _fn(js, "saveRecents")
    for field in ("client", "display_name", "row_key", "path",
                  "trello_card_id"):
        assert field in body, f"identity field {field} missing"
    for stale in ("total_missing", "form_issues", "photo_issues",
                  "sharepoint_new", "pics_count"):
        assert stale not in body, f"{stale} is audit state and goes stale"


def test_saving_is_capped(js):
    """The list is capped on screen; the saved copy has to match or it
    grows without bound in state.json."""
    assert "ONEOFF_MAX" in _fn(js, "saveRecents")


def test_the_list_persists_when_it_changes(js):
    """Both directions — adding a job and clearing the list."""
    assert js.count("saveRecents();") >= 2
    cleared = js[js.index('$("#clear-oneoff-btn")'):]
    cleared = cleared[:cleared.index("});")]
    assert "saveRecents()" in cleared, "clearing must persist too"


# ── coming back ──────────────────────────────────────────────────────
def test_restore_marks_rows_as_not_yet_checked(js):
    body = _fn(js, "restoreRecents")
    assert "_stale: true" in body


def test_a_restored_row_does_not_look_clean(js):
    """A placeholder count of 0 rendered in the "zero" style reads as a
    clean job. Dressing a placeholder as a result is how a stale answer
    gets acted on."""
    assert 'r._stale ? "miss-num pending"' in js
    assert "not checked yet" in js


def test_the_pending_style_is_not_the_clean_style():
    css = io.open(os.path.join(_ROOT, "audit_web_assets", "app.css"),
                  encoding="utf-8").read()
    assert ".miss-num.pending" in css
    block = css[css.index(".list-end .miss-num.pending"):]
    block = block[:block.index("}")]
    assert "dashed" in block, "must read as provisional, not as a result"


def test_restore_re_audits_each_job(js):
    body = _fn(js, "restoreRecents")
    assert "reaudit_one" in body and "applyRow" in body


def test_restore_is_sequential(js):
    """A burst of parallel audits would hammer the share for a list
    nobody is looking at yet."""
    body = _fn(js, "restoreRecents")
    assert "for (const r of saved)" in body
    assert "Promise.all" not in body


def test_restore_stops_if_the_list_is_cleared(js):
    """Clearing the list mid-restore must not have jobs reappear."""
    body = _fn(js, "restoreRecents")
    assert "break" in body


def test_restore_does_not_block_the_panel(js):
    """It re-audits each job in turn; awaiting it would hold up boot."""
    boot = js[js.index("if (!state.userSwitchedMode) applyModeChrome(landing);"):]
    boot = boot[:boot.index("}")]
    assert "restoreRecents();" in boot
    assert "await restoreRecents" not in boot


def test_restore_runs_after_the_state_is_loaded(js):
    """PanelState.get is served from memory only after init resolves."""
    assert js.index('PanelState.init("audit")') < js.index("restoreRecents();")


# ── the store really round-trips a list ──────────────────────────────
def test_ui_state_round_trips_a_list():
    """PanelState is a merge-patch store; recents is the first ARRAY to
    go through it."""
    import home_web
    import persistence
    api = home_web.HomeApi.__new__(home_web.HomeApi)
    panel = "audit_recents_pytest"
    try:
        api.set_ui_state(panel, {"recents": [{"client": "A"}, {"client": "B"}]})
        got = api.get_ui_state(panel)
        state = got.get("state", got)
        assert [r["client"] for r in state["recents"]] == ["A", "B"]
    finally:
        st = dict(persistence.get("ui_state") or {})
        for k in [k for k in st if panel in k]:
            st.pop(k)
        persistence.set_value("ui_state", st)
