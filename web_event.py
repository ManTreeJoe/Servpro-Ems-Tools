"""Shared web-event helpers — dispatch CustomEvents from Python so
they fire BOTH in the home shell's window AND inside the embedded
tool iframe's contentWindow.

Why both: the home_web shell loads each tool's HTML inside an
iframe. The tool's event listeners (e.g. `audit:done`) live on the
iframe's window object — NOT the parent shell's. If the backend
simply calls `window.evaluate_js(...)` on the shell window, the
event fires there and the listener inside the iframe never hears
it. The UI gets stuck (loading icon spins forever, etc.).

This helper rewrites the same dispatch line to fire on the
embedded iframe's contentWindow too, wrapped in a try/catch so a
failure in one context doesn't block the other.

Single-window tools (when the panel is launched standalone, not
inside the shell) just hit the first branch — the second branch
no-ops because there's no `#content-frame` element.
"""
from __future__ import annotations


def dispatch(window, dispatch_js: str) -> None:
    """Run `dispatch_js` (a `window.dispatchEvent(new CustomEvent(...))`
    snippet) on both the home shell window AND the active tool
    iframe's contentWindow. Swallows all errors — event dispatch is
    fire-and-forget UI plumbing, not a critical path."""
    if window is None or not dispatch_js:
        return
    iframe_js = dispatch_js.replace(
        "window.dispatchEvent(",
        "__ems_iframe_win__.dispatchEvent(")
    wrapped = (
        "(function(){"
        "try{" + dispatch_js + "}catch(e){}"
        "try{"
        "var __f=document.getElementById('content-frame');"
        "if(__f && __f.contentWindow){"
        "var __ems_iframe_win__=__f.contentWindow;"
        + iframe_js +
        "}"
        "}catch(e){}"
        "})();"
    )
    try:
        window.evaluate_js(wrapped)
    except Exception:
        pass


def event(window, name: str, detail: dict) -> None:
    """Convenience wrapper — builds the dispatch JS from an event
    name + detail dict. Caller doesn't need to hand-format the JSON.
    """
    import json
    payload = json.dumps(detail or {}, default=str)
    dispatch(window,
             "window.dispatchEvent(new CustomEvent('"
             + name + "', {detail: " + payload + "}));")


# Throttle state — keyed by event name. Each call to throttled_event
# remembers the timestamp of the last dispatch on that channel and
# drops events that arrive faster than `min_interval` apart. The
# `final` flag forces a dispatch regardless of cadence (so the user
# always sees 100% / "done" at the end of a progress stream).
_THROTTLE_STATE: dict[str, float] = {}

def throttled_event(window, name: str, detail: dict,
                    min_interval: float = 0.25,
                    final: bool = False) -> bool:
    """Fire a CustomEvent rate-limited to one dispatch per
    `min_interval` seconds per event name. Returns True if dispatched.

    Pywebview's evaluate_js is synchronous and marshals from a worker
    thread back to the WebView UI thread. Per-item progress callbacks
    that fire hundreds of times per scan (trello_hygiene per-card,
    spreadsheet reconcile per-row, etc.) will serialize the UI thread
    behind those round-trips and freeze the panel. Caller passes
    final=True on the last emission so the receiver lands on the
    correct final state.
    """
    import time as _time
    now = _time.monotonic()
    last = _THROTTLE_STATE.get(name, 0.0)
    if not final and (now - last) < min_interval:
        return False
    _THROTTLE_STATE[name] = now
    event(window, name, detail)
    return True
