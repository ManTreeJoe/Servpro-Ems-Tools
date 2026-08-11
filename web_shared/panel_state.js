/*
 * web_shared/panel_state.js — remember where you were in each panel.
 *
 * Panels live in iframes and are torn down when you navigate away, so
 * every tab, filter, search box and scroll position resets on the way
 * back in. HomeApi has had `get_ui_state(panel)` / `set_ui_state(panel,
 * patch)` for a while — a per-panel merge-patch store persisted in
 * state.json — but only the audit panel ever used it, and only for its
 * active tab. This is the shared front end so a panel opts in with two
 * lines instead of hand-rolling it.
 *
 * Usage:
 *
 *     await PanelState.init("hygiene");                  // once, on boot
 *     state.active = PanelState.get("active", "all");    // restore
 *     PanelState.set({ active: state.active });          // remember
 *     PanelState.bindScroll(document.querySelector("#rows"));
 *
 * WRITES ARE DEBOUNCED. set_ui_state lands in state.json, and a save
 * there costs ~23ms — cheap once, ruinous on a scroll handler. Patches
 * coalesce and flush on a timer, on tab-hide and on pagehide, so
 * navigating away still persists the last change.
 *
 * Reads are served from memory after init, so `get` is synchronous and
 * usable directly in a render path.
 */
(function () {
  "use strict";

  const FLUSH_MS = 500;

  let _panel = "";
  let _cache = {};          // last known full state for this panel
  let _pending = null;      // merged patch awaiting flush
  let _timer = null;
  let _ready = false;

  function _api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  async function init(panel) {
    _panel = String(panel || "").trim();
    _cache = {};
    _ready = false;
    if (!_panel) return _cache;
    try {
      const api = _api();
      if (api && api.get_ui_state) {
        const st = await api.get_ui_state(_panel);
        if (st && typeof st === "object") _cache = st;
      }
    } catch (_) {
      // No store (standalone window, or an older host) — the panel still
      // works, it just opens at its defaults. Never fatal.
    }
    _ready = true;
    return _cache;
  }

  function get(key, fallback) {
    if (!_ready && !Object.keys(_cache).length) return fallback;
    const v = _cache[key];
    return v === undefined || v === null ? fallback : v;
  }

  function all() { return Object.assign({}, _cache); }

  function set(patch) {
    if (!_panel || !patch || typeof patch !== "object") return;
    Object.assign(_cache, patch);
    _pending = Object.assign(_pending || {}, patch);
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(flush, FLUSH_MS);
  }

  function flush() {
    if (_timer) { clearTimeout(_timer); _timer = null; }
    if (!_panel || !_pending) return;
    const patch = _pending;
    _pending = null;
    try {
      const api = _api();
      if (api && api.set_ui_state) api.set_ui_state(_panel, patch);
    } catch (_) { /* losing a restore never breaks the panel */ }
  }

  // Scroll position of a list, remembered under one key. Restored on the
  // next frame because the rows are usually rendered in the same tick and
  // scrollTop cannot be set past a height that doesn't exist yet.
  function bindScroll(el, key) {
    if (!el) return;
    key = key || "scroll";
    el.addEventListener("scroll", () => {
      set({ [key]: Math.round(el.scrollTop) });
    }, { passive: true });
  }

  function restoreScroll(el, key) {
    if (!el) return;
    const top = Number(get(key || "scroll", 0)) || 0;
    if (!top) return;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => { el.scrollTop = top; });
    });
  }

  // Navigating away tears the iframe down mid-debounce, so force the
  // pending patch out. visibilitychange fires on panel switch inside the
  // launcher; pagehide covers a real unload.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);
  window.addEventListener("beforeunload", flush);

  window.PanelState = {
    init, get, set, all, flush, bindScroll, restoreScroll,
    get panel() { return _panel; },
  };
})();
