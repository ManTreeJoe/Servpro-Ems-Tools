/*
 * web_shared/progress_bar.js — the thin bar across the status bar.
 *
 * Long jobs (SP pulls, CompanyCam pulls, WC classify) already stream
 * {done, total, name} to the UI; until now that only became text —
 * "Pulling 12/40 · IMG_4412.jpg". Text tells you it's alive but not how
 * far along it is, and on a slow share the difference between "nearly
 * done" and "barely started" is what decides whether you wait or go do
 * something else.
 *
 * Draws INTO the existing <footer class="statusbar">, pinned to its top
 * edge and absolutely positioned, so showing it never reflows the panel
 * — a bar that pushes the layout around each time it appears is worse
 * than no bar.
 *
 * Usage:
 *
 *     Progress.set(12, 40);          // determinate
 *     Progress.start();              // indeterminate — total unknown
 *     Progress.done();               // fills, then fades out
 *     Progress.fail();               // paints red, then fades out
 *
 * Every call is a no-op when there's no status bar, so a panel that
 * hasn't opted in can call it without guarding.
 */
(function () {
  "use strict";

  var HIDE_MS = 700;          // how long a finished bar lingers
  var _el = null;             // the moving fill
  var _host = null;           // the track
  var _hideTimer = null;

  function injectCss() {
    if (document.getElementById("ems-progress-css")) return;
    var st = document.createElement("style");
    st.id = "ems-progress-css";
    st.textContent = [
      ".ems-prog{position:absolute;left:0;right:0;top:0;height:3px;",
      "overflow:hidden;pointer-events:none;opacity:0;",
      "transition:opacity .25s ease;}",
      ".ems-prog.on{opacity:1;}",
      ".ems-prog > i{display:block;height:100%;width:0%;",
      "background:var(--accent,#4A9EFF);transition:width .18s ease;}",
      ".ems-prog.err > i{background:var(--red,#F85149);}",
      ".ems-prog.ind > i{width:35%;animation:emsProgSlide 1.1s ease-in-out infinite;}",
      "@keyframes emsProgSlide{0%{margin-left:-35%;}100%{margin-left:100%;}}",
      // A bar that never stops moving is a distraction on a machine
      // that's already struggling; hold it still and let the width do
      // the talking.
      "@media (prefers-reduced-motion: reduce){",
      ".ems-prog.ind > i{animation:none;width:100%;opacity:.45;}",
      ".ems-prog > i{transition:none;}}",
    ].join("");
    document.head.appendChild(st);
  }

  function ensure() {
    if (_el && document.body.contains(_el)) return _el;
    // Most panels have a status footer; Quick Import — the one that is
    // nothing BUT imports — has a bare #status div instead, so fall back
    // to it rather than leaving that panel the only one without a bar.
    var bar = document.querySelector("footer.statusbar")
      || document.querySelector(".statusbar")
      || document.getElementById("status");
    if (!bar) return null;
    injectCss();
    // The track is absolutely positioned against the status bar, so the
    // status bar has to be a positioning context. It usually isn't.
    var pos = window.getComputedStyle(bar).position;
    if (pos === "static") bar.style.position = "relative";
    _host = document.createElement("div");
    _host.className = "ems-prog";
    _host.appendChild(document.createElement("i"));
    bar.appendChild(_host);
    _el = _host;
    return _el;
  }

  function clearHide() {
    if (_hideTimer) { clearTimeout(_hideTimer); _hideTimer = null; }
  }

  function show(cls) {
    var el = ensure();
    if (!el) return null;
    clearHide();
    el.classList.remove("err", "ind");
    if (cls) el.classList.add(cls);
    el.classList.add("on");
    return el;
  }

  function fadeOut() {
    clearHide();
    _hideTimer = setTimeout(function () {
      if (!_el) return;
      _el.classList.remove("on");
      // Reset only after it's invisible, so the bar doesn't visibly snap
      // back to zero on its way out.
      setTimeout(function () {
        if (!_el) return;
        _el.classList.remove("err", "ind");
        _el.firstChild.style.width = "0%";
      }, 260);
    }, HIDE_MS);
  }

  var Progress = {
    // Unknown total — a moving stripe, which says "working" without
    // claiming a position it doesn't know.
    start: function () {
      var el = show("ind");
      if (el) el.firstChild.style.width = "";
    },
    set: function (done, total) {
      var d = Number(done) || 0;
      var t = Number(total) || 0;
      if (t <= 0) { Progress.start(); return; }
      var el = show(null);
      if (!el) return;
      var pct = Math.max(0, Math.min(100, (d / t) * 100));
      el.firstChild.style.width = pct + "%";
    },
    done: function () {
      var el = show(null);
      if (!el) return;
      el.firstChild.style.width = "100%";
      fadeOut();
    },
    fail: function () {
      var el = show("err");
      if (!el) return;
      el.firstChild.style.width = "100%";
      fadeOut();
    },
    hide: function () {
      if (!_el) return;
      clearHide();
      _el.classList.remove("on", "err", "ind");
      _el.firstChild.style.width = "0%";
    },
    // Wire a {done,total} progress event and its done event in one line.
    // `okOf` decides success from the done event's detail.
    bind: function (progressEvent, doneEvent, okOf) {
      window.addEventListener(progressEvent, function (ev) {
        var d = (ev && ev.detail) || {};
        Progress.set(d.done, d.total);
      });
      window.addEventListener(doneEvent, function (ev) {
        var d = (ev && ev.detail) || {};
        var ok = okOf ? okOf(d) : (d.ok !== false);
        if (ok) Progress.done(); else Progress.fail();
      });
    },
  };

  window.Progress = Progress;
})();
