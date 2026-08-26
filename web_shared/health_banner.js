/* Linguar Hub — health banner + browser-side error reporting.
 *
 * Two jobs, both about the same thing: a failure the user cannot see is
 * a failure they keep working through.
 *
 *   1. A bar at the top of the shell when the shared database is
 *      unreachable, when writes are still queued, or when the signed-in
 *      account has no franchise access. That last one matters most —
 *      RLS returns zero rows, so the app looks EMPTY rather than
 *      forbidden, and "there are no jobs" is a very convincing lie.
 *
 *   2. A window.onerror / unhandledrejection hook in every panel that
 *      posts to ems.log. The window is a WebView with no console anyone
 *      opens, so a panel that threw used to leave no evidence at all
 *      beyond the user saying "it did nothing".
 *
 * The banner renders in the TOP-LEVEL window only. Panels are iframes;
 * rendering per-frame would stack one bar per open panel. Iframes still
 * install the error hook, because that is where the errors happen.
 */
(function () {
  "use strict";

  var IS_TOP = window.parent === window;
  var POLL_MS = 30000;
  var api = null;

  function whenApi(cb) {
    if (window.pywebview && window.pywebview.api) { cb(window.pywebview.api); return; }
    window.addEventListener("pywebviewready", function () {
      cb(window.pywebview && window.pywebview.api);
    });
  }

  // ── error reporting ─────────────────────────────────────────────────
  //
  // Deduped and capped. A render loop that throws every frame would
  // otherwise write ems.log until the disk filled, and burying the first
  // error under ten thousand copies of itself loses the one that matters.
  var seen = Object.create(null);
  var sent = 0;
  var MAX_SENT = 50;

  function panelName() {
    try {
      var parts = location.pathname.split(/[\/\\]/);
      var dir = parts[parts.length - 2] || "";
      return dir.replace(/_web_assets$/, "") || "panel";
    } catch (_) { return "panel"; }
  }

  function report(message, detail) {
    if (sent >= MAX_SENT) return;
    var key = String(message).slice(0, 200);
    if (seen[key]) { seen[key]++; return; }
    seen[key] = 1;
    sent++;
    try {
      if (api && api.log_js_error) api.log_js_error(panelName(), message, detail || "");
    } catch (_) { /* reporting must never throw */ }
  }

  window.addEventListener("error", function (ev) {
    if (!ev) return;
    // A failed <img>/<script> fires here with no .error — real, but not
    // an exception, and it has no stack worth logging.
    if (ev.error) {
      report(String(ev.message || ev.error), String(ev.error.stack || ""));
    } else if (ev.message) {
      report(String(ev.message), (ev.filename || "") + ":" + (ev.lineno || 0));
    }
  });

  window.addEventListener("unhandledrejection", function (ev) {
    var r = ev && ev.reason;
    if (r === undefined) return;
    report("Unhandled promise rejection: " + (r && r.message ? r.message : String(r)),
           String((r && r.stack) || ""));
  });

  // ── the bar ─────────────────────────────────────────────────────────

  function css() {
    if (document.getElementById("health-banner-css")) return;
    var st = document.createElement("style");
    st.id = "health-banner-css";
    st.textContent = [
      "#health-banner{position:sticky;top:0;z-index:9000;display:none;",
      "  font:500 12.5px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;",
      "  padding:7px 12px;border-bottom:1px solid;cursor:pointer;}",
      "#health-banner.on{display:flex;align-items:baseline;gap:8px;}",
      "#health-banner .hb-dot{width:7px;height:7px;border-radius:50%;",
      "  flex:0 0 auto;align-self:center;}",
      "#health-banner .hb-title{font-weight:650;}",
      "#health-banner .hb-detail{opacity:.85;font-weight:400;}",
      "#health-banner .hb-more{margin-left:auto;opacity:.7;font-weight:400;",
      "  white-space:nowrap;}",
      // Amber = still working, degraded. Red = you are being shown
      // nothing and it is not because there is nothing.
      "#health-banner.warn{background:#4A3410;color:#F5D9A8;border-color:#7A5A1E;}",
      "#health-banner.bad{background:#4A1B1B;color:#F6C9C9;border-color:#7E2C2C;}",
      "@media (prefers-color-scheme: light){",
      "  #health-banner.warn{background:#FDF3DC;color:#6B4708;border-color:#E4C177;}",
      "  #health-banner.bad{background:#FCE9E9;color:#8A2020;border-color:#E9A9A9;}}",
    ].join("");
    document.head.appendChild(st);
  }

  // Where the bar can sit WITHOUT breaking the layout it sits in. The
  // shell is a 100vh grid with overflow:hidden, so a bar prepended to
  // <body> pushes the app down and the bottom is clipped off. `.pane` is
  // a flex column whose content is flex:1, so a first child there simply
  // makes room for itself.
  function host() {
    return document.querySelector(".pane") || document.body;
  }

  function el() {
    var n = document.getElementById("health-banner");
    if (n) return n;
    css();
    n = document.createElement("div");
    n.id = "health-banner";
    n.setAttribute("role", "status");
    var h = host();
    h.insertBefore(n, h.firstChild);
    return n;
  }

  var expanded = false;

  function render(st) {
    var box = el();
    var problems = (st && st.problems) || [];
    if (!problems.length) { box.className = ""; box.textContent = ""; return; }

    var worst = problems[problems.length - 1];   // grant issues sort last
    for (var i = 0; i < problems.length; i++) {
      if (problems[i].code === "no_grant" || problems[i].code === "wrong_grant") {
        worst = problems[i];
        break;
      }
    }
    var bad = worst.code === "no_grant" || worst.code === "wrong_grant" ||
              worst.code === "signed_out";
    box.className = "on " + (bad ? "bad" : "warn");
    box.textContent = "";

    var dot = document.createElement("span");
    dot.className = "hb-dot";
    dot.style.background = "currentColor";
    box.appendChild(dot);

    var t = document.createElement("span");
    t.className = "hb-title";
    t.textContent = worst.title || "";
    box.appendChild(t);

    var d = document.createElement("span");
    d.className = "hb-detail";
    d.textContent = expanded
      ? [worst.detail, worst.action, worst.last_error].filter(Boolean).join("  ·  ")
      : (worst.detail || "");
    box.appendChild(d);

    if (problems.length > 1) {
      var m = document.createElement("span");
      m.className = "hb-more";
      m.textContent = "+" + (problems.length - 1) + " more";
      box.appendChild(m);
    }

    box.onclick = function () { expanded = !expanded; render(st); };
  }

  function poll(force) {
    if (!api || !api.health_state) return;
    Promise.resolve(api.health_state(force === true)).then(render).catch(function () {
      // A health check that cannot run says nothing rather than crying
      // wolf — "cannot ask" is not "broken".
    });
  }

  whenApi(function (a) {
    api = a;
    if (!IS_TOP) return;          // iframes: error reporting only
    poll();
    setInterval(poll, POLL_MS);
    // Coming back to the window is exactly when a stale banner is most
    // misleading, in both directions.
    window.addEventListener("focus", poll);
    window.addEventListener("message", function (ev) {
      if (ev && ev.data && ev.data.type === "health-refresh") poll(true);
    });
  });

  window.HealthBanner = { refresh: poll };
})();
