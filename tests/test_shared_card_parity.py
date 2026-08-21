"""web_shared/audit_detail.js is ONE card rendered by Audit AND Snapshot.

Anything it calls has to exist on BOTH windows, or the button is dead on
one of them — and dead quietly: the iframe shim logs a warning to a
console nobody has open and returns null, so the click just does
nothing.

This has now bitten three times (job settings, CompanyCam, and the
📁 OD contents / 📖 Job tracker viewers, which called od_contents,
job_work_log and save_job_work_log — none of them proxied in Snapshot).
Checking it by hand against ~50 calls is not a thing anyone will keep
doing, so the check lives here.
"""
import os
import re

import pytest

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CARD = os.path.join(_SCRIPTS, "web_shared", "audit_detail.js")


def _card_js(strip_comments=False):
    with open(_CARD, encoding="utf-8") as f:
        js = f.read()
    if strip_comments:
        # The file's header documents the ctx shape and NAMES the modal
        # keys, so scanning raw text reports documentation as usage —
        # `openPin` is listed there but the card calls the shared
        # openPinModal directly.
        js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        js = re.sub(r"^\s*//.*$", "", js, flags=re.M)
    return js


def _api_calls():
    return sorted(set(re.findall(r"pywebview\.api\.([A-Za-z_]\w*)",
                                 _card_js(strip_comments=True))))


# Methods reached through the shim's fallback to the parent HomeApi
# rather than the panel's own Api (see iframe_shim.js: it tries
# "<ns>_name" first, then bare "name" on HomeApi).
_HOST_API = {"get_ui_state", "set_ui_state", "get_last_panel",
             "set_last_panel", "focus_window"}


def test_the_card_actually_calls_something():
    """Guard the guard: a regex that silently matches nothing would make
    every assertion below vacuously pass."""
    calls = _api_calls()
    assert len(calls) > 30, f"only found {len(calls)} api calls — regex broken?"


@pytest.mark.parametrize("panel", ["audit_web", "snapshot_web"])
def test_every_api_call_exists_on_this_panel(panel):
    import importlib
    api = importlib.import_module(panel).Api
    missing = [c for c in _api_calls()
               if c not in _HOST_API and not hasattr(api, c)]
    assert not missing, (
        f"{panel}.Api is missing {missing} — the shared card calls these, "
        f"so those buttons are dead in that panel. Add a proxy.")


def test_the_two_panels_agree():
    """Neither should be able to drift ahead of the other."""
    import audit_web
    import snapshot_web
    calls = [c for c in _api_calls() if c not in _HOST_API]
    only_audit = [c for c in calls if hasattr(audit_web.Api, c)
                  and not hasattr(snapshot_web.Api, c)]
    only_snap = [c for c in calls if hasattr(snapshot_web.Api, c)
                 and not hasattr(audit_web.Api, c)]
    assert not only_audit, f"audit-only: {only_audit}"
    assert not only_snap, f"snapshot-only: {only_snap}"


# ── ctx modals: the other way a button dies ────────────────────────────
def _modal_keys():
    js = _card_js(strip_comments=True)
    return sorted(set(re.findall(r"\bM\.([A-Za-z_]\w*)", js)
                      + re.findall(r"ctx\.modals\.([A-Za-z_]\w*)", js)))


def test_every_modal_the_card_uses_has_a_fallback_or_both_renderers():
    """A `M.x` with no fallback and no injection in one renderer is a
    dead button there. Either both panels inject it, or the card has to
    handle its absence."""
    js = _card_js(strip_comments=True)
    gaps = []
    for key in _modal_keys():
        # Any of these is a safe call: an `if` guard in either spelling
        # (`M.x` or the longhand `ctx.modals.x`), or a `|| default`.
        safe = (
            re.search(rf"if \(M\.{key}\)", js)
            or re.search(rf"ctx\.modals && ctx\.modals\.{key}", js)
            or re.search(rf"if \(ctx\.modals\.{key}\)", js)
            or re.search(rf"M\.{key}\s*\|\|", js)
        )
        if not safe:
            gaps.append(key)
    assert not gaps, f"unguarded modal hooks: {gaps}"


def test_shared_viewers_are_defined_in_the_shared_card():
    """OD contents and the job tracker used to live only in the Audit
    panel while the shared card offered buttons for them, so they were
    dead in Snapshot. They are defaults here now."""
    js = _card_js()
    assert "function defaultOdContents(" in js
    assert "function defaultWorkLog(" in js
    assert "defaultOdContents(ctx" in js
    assert "defaultWorkLog(ctx" in js


def test_attachments_modal_is_called_with_an_object():
    """openTrelloAttachmentsModal destructures {cardId, client, onAfter}.
    Positional args silently open the modal with no card."""
    js = _card_js()
    for m in re.findall(r"openTrelloAttachmentsModal\(([^)]*)\)", js):
        assert "cardId" in m, f"positional call: openTrelloAttachmentsModal({m})"


# ── existing is not enough: it has to accept the same ARGUMENTS ────────
#
# toggle_checklist_item grew `item_name` and `client` when ticks started
# posting and deleting Trello comments. Audit got the new signature;
# Snapshot's proxy kept the old three-parameter one. The method still
# EXISTED, so this file passed — and every tick in Snapshot raised
# TypeError and reported "Trello update failed".

def _params(fn):
    import inspect
    try:
        return list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None


@pytest.mark.parametrize("panel_name", ["snapshot_web", "quickimport_web"])
def test_proxies_accept_everything_the_real_method_does(panel_name):
    import importlib

    import audit_web
    panel = importlib.import_module(panel_name)

    bad = []
    for name in dir(panel.Api):
        if name.startswith("_"):
            continue
        real = getattr(audit_web.Api, name, None)
        proxy = getattr(panel.Api, name, None)
        if not (callable(real) and callable(proxy)):
            continue
        pr, pp = _params(real), _params(proxy)
        if pr is None or pp is None:
            continue
        # *a / **k forwards everything — that is the drift-proof form.
        if any(x.kind in (x.VAR_POSITIONAL, x.VAR_KEYWORD) for x in pp):
            continue
        n_real = len([x for x in pr if x.name != "self"])
        n_proxy = len([x for x in pp if x.name != "self"])
        if n_proxy < n_real:
            bad.append(f"{panel_name}.{name}: audit takes {n_real} arg(s), "
                       f"the proxy takes {n_proxy}")
    assert not bad, (
        "a proxy cannot forward what the shared card sends:\n  "
        + "\n  ".join(bad)
        + "\n\nUse `def name(self, *a, **k): return self._aw().name(*a, **k)` "
          "so it cannot drift again.")
