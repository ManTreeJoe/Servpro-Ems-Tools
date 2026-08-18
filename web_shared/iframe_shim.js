/* Linguar Hub — iframe shim (v2).
 *
 * Sets up `window.pywebview.api` inside each tool's iframe as a
 * Proxy that auto-prefixes method names with the tool's namespace
 * and forwards calls to the parent window's HomeApi.
 *
 * Timing matters: the tool's app.js listens for `pywebviewready`
 * via `window.addEventListener`. If the event fires before app.js
 * has run, the listener is never called and the tool appears stuck
 * loading. We guard against this by deferring the dispatch until
 * `document.readyState === "complete"` (all scripts loaded).
 */
(function () {
  if (window.parent === window) return;  // standalone — let pywebview do its thing
  const parentWin = window.parent;
  let alreadyFired = false;

  function fireReady() {
    if (alreadyFired) return;
    alreadyFired = true;
    // Microtask delay so the call stack settles + any synchronous
    // listener registration in app.js runs first.
    setTimeout(() => {
      window.dispatchEvent(new Event("pywebviewready"));
    }, 0);
  }

  function dispatchWhenReady() {
    if (document.readyState === "complete") {
      fireReady();
    } else {
      window.addEventListener("load", fireReady);
      // Also try DOMContentLoaded in case the load event is slow
      // due to images/iframes etc. — pywebviewready only needs the
      // DOM + scripts, not all subresources.
      window.addEventListener("DOMContentLoaded", () => {
        // Give scripts a beat to register listeners
        setTimeout(fireReady, 10);
      });
    }
  }

  function tryWire() {
    if (!parentWin.pywebview || !parentWin.pywebview.api) {
      setTimeout(tryWire, 30);
      return;
    }
    const parentApi = parentWin.pywebview.api;
    let ns = "";
    try {
      const parts = location.pathname.split(/[\/\\]/);
      const dir = parts[parts.length - 2] || "";
      ns = dir.replace(/_web_assets$/, "");
    } catch (_) { ns = ""; }
    // ── "This is a big load" ────────────────────────────────────────
    //
    // Every panel's API call comes through this one function, which
    // makes it the only place a loading indicator can be added ONCE and
    // cover panels that never streamed progress — APA, Job Notes, KPI,
    // Settings — instead of guessing which of their calls are slow.
    //
    // It is an ALLOWLIST of bulk verbs, not a timing heuristic, and that
    // is the whole lesson from the first attempt: "anything slower than
    // 400ms" caught ticking a checklist item, which is a ~600ms Trello
    // write. It is an ACTION, not a load — the checkbox and the status
    // line already say it is happening — and a bar flashing on every
    // tick trains people to stop reading the bar, which costs you the
    // real ones too.
    //
    // Default is silence. A slow method that is not listed simply gets
    // no bar, which is where it started; a fast one that IS listed still
    // waits out the delay below.
    const BULK_VERBS = [
      "sync", "scan", "rebuild", "reindex", "build_", "index_", "classify",
      "reconcile", "generate", "export", "import", "pull", "backfill",
      "migrate", "refresh_all", "load_all", "run_audit", "audit_all",
    ];
    function isBulk(name) {
      const n = String(name || "");
      return BULK_VERBS.some(function (v) { return n.indexOf(v) === 0; });
    }
    const SLOW_MS = 1200;       // even a real load gets this long to finish

    let _slow = 0;
    function _track(name, p) {
      const P = window.Progress;
      if (!P || !p || typeof p.then !== "function") return p;
      if (!isBulk(name)) return p;
      let armed = false;
      const t = setTimeout(function () {
        if (P.active && P.active()) return;   // a real stream owns it
        armed = true;
        _slow += 1;
        P.start();
      }, SLOW_MS);
      const settle = function () {
        clearTimeout(t);
        if (!armed) return;
        _slow = Math.max(0, _slow - 1);
        // Only finish what WE started: if a determinate stream took the
        // bar over mid-flight, leave it alone.
        if (_slow === 0 && P.indeterminate && P.indeterminate()) P.done();
      };
      p.then(settle, settle);
      return p;
    }

    const handler = {
      get(_target, prop) {
        if (typeof prop !== "string") return undefined;
        return function (...args) {
          const nsKey = ns + "_" + prop;
          if (typeof parentApi[nsKey] === "function") {
            return _track(prop, parentApi[nsKey](...args));
          }
          if (typeof parentApi[prop] === "function") {
            return _track(prop, parentApi[prop](...args));
          }
          console.warn("[shim] pywebview.api." + prop + " — neither "
            + nsKey + " nor " + prop + " on parent HomeApi");
          return Promise.resolve(null);
        };
      }
    };
    window.pywebview = { api: new Proxy({}, handler) };

    // WebView2 focus fix: clicking into a field can leave the top-level OS
    // window un-activated (the caret blinks but the window isn't focused),
    // so keystrokes feel dead until you click the title bar. Nudge the app
    // to the foreground on interaction — throttled to skip a round-trip on
    // every click, and idempotent on the Python side.
    let _focusNudgeAt = 0;
    document.addEventListener("pointerdown", () => {
      const now = Date.now();
      if (now - _focusNudgeAt < 400) return;
      _focusNudgeAt = now;
      try { if (parentApi.focus_window) parentApi.focus_window(); } catch (_) { /* ignore */ }
    }, true);

    dispatchWhenReady();
  }
  tryWire();
})();
