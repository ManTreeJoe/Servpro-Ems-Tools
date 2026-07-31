/* Linguar Hub — shared toast log.
 *
 * Wraps every panel's `setStatus(msg, kind)` so each toast also
 * lands in a session-wide log accessible from the launcher's 🛎
 * button. The log is stored in localStorage so it survives panel
 * navigation but resets on launcher restart.
 *
 * Each panel's app.js typically already defines a local
 * setStatus(). This shim wraps the FIRST-defined function once
 * (window._toastLogShim flag prevents double-wrapping) and pushes
 * the (timestamp, panel, msg, kind) tuple onto the log.
 *
 * The launcher renders the drawer; iframes just push entries.
 * The cross-iframe message bus carries entries up to the parent.
 */
(function () {
  "use strict";

  const STORAGE_KEY = "ems_toast_log";
  const MAX_ENTRIES = 50;

  function panelName() {
    try {
      const parts = location.pathname.split(/[\/\\]/);
      const dir = parts[parts.length - 2] || "";
      return dir.replace(/_web_assets$/, "") || "home";
    } catch (_) { return "home"; }
  }

  // Append to the log (called by the wrapped setStatus + by the
  // parent's message receiver). Newest entries at the END.
  function push(entry) {
    try {
      let log = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      if (!Array.isArray(log)) log = [];
      log.push(entry);
      if (log.length > MAX_ENTRIES) log = log.slice(-MAX_ENTRIES);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(log));
    } catch (_) {}
  }

  function readLog() {
    try {
      const log = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(log) ? log : [];
    } catch (_) { return []; }
  }

  function clearLog() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  // Wrap any panel's existing setStatus so calls also feed the log.
  // Re-wraps if the panel defined setStatus AFTER this script loaded
  // (re-checks on a short interval until the function appears).
  function wrapSetStatus() {
    if (window._toastLogShim) return;
    if (typeof window.setStatus !== "function") return;
    const orig = window.setStatus;
    window.setStatus = function (msg, kind = "") {
      if (msg) {
        const entry = {
          ts:     new Date().toISOString(),
          panel:  panelName(),
          msg:    String(msg),
          kind:   String(kind || ""),
        };
        push(entry);
        // Forward up to the launcher shell so the drawer stays live
        try {
          window.parent?.postMessage({ type: "toast-log-push", entry }, "*");
        } catch (_) {}
      }
      return orig.apply(this, arguments);
    };
    window._toastLogShim = true;
  }

  // Poll for setStatus until the panel's app.js has defined it.
  // Bails after ~10 seconds of no detection (panels without
  // setStatus just don't contribute to the log — no error).
  let tries = 0;
  const wrapTimer = setInterval(() => {
    tries += 1;
    if (typeof window.setStatus === "function") {
      wrapSetStatus();
      clearInterval(wrapTimer);
      return;
    }
    if (tries > 100) clearInterval(wrapTimer);
  }, 100);

  // ── Parent / launcher shell entry points ────────────────────────
  // The launcher uses these to render the drawer + clear button.
  window._toastLog = {
    read:  readLog,
    clear: clearLog,
    push,
  };

  // Launcher's drawer renderer — reads localStorage + builds a
  // simple list. The launcher's app.js wires this to a 🛎 button.
  window.openToastLogDrawer = function () {
    document.getElementById("toast-log-drawer")?.remove();
    const log = readLog().slice().reverse();  // newest first
    const w = document.createElement("div");
    w.id = "toast-log-drawer";
    w.style.cssText = `position:fixed;top:0;right:0;bottom:0;width:min(420px,90vw);
      z-index:200;background:var(--bg);border-left:1px solid var(--border);
      box-shadow:-6px 0 20px rgba(0,0,0,.5);display:flex;flex-direction:column;`;
    w.innerHTML = `
      <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;">
        <span style="font-size:14px;font-weight:600;">🛎 Toast log</span>
        <span class="muted" style="font-size:11px;">${log.length}/50 entries</span>
        <span style="flex:1;"></span>
        <button class="btn" id="tl-clear" style="font-size:11px;padding:3px 10px;">✕ Clear</button>
        <button class="btn" id="tl-close" style="font-size:11px;padding:3px 10px;">Close</button>
      </header>
      <div id="tl-list" style="flex:1;overflow-y:auto;padding:10px 18px;display:flex;flex-direction:column;gap:6px;">
        ${log.length ? log.map(rowHtml).join("") : `<div class="muted" style="padding:30px 0;text-align:center;">No toasts yet — actions will appear here as you work.</div>`}
      </div>`;
    document.body.appendChild(w);
    document.getElementById("tl-close").addEventListener("click", () => w.remove());
    document.getElementById("tl-clear").addEventListener("click", () => {
      clearLog();
      document.getElementById("tl-list").innerHTML =
        `<div class="muted" style="padding:30px 0;text-align:center;">Cleared.</div>`;
    });
    // Click row to copy its message
    document.querySelectorAll(".tl-row").forEach((el) =>
      el.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(el.dataset.msg);
          el.style.background = "rgba(46,139,87,.18)";
          setTimeout(() => { el.style.background = "var(--surface)"; }, 400);
        } catch (_) {}
      }));
  };

  function rowHtml(e) {
    const time = (e.ts || "").slice(11, 19);
    const kindColor = e.kind === "error" ? "var(--red)"
                    : e.kind === "warn"  ? "var(--amber)"
                    : e.kind === "ok"    ? "var(--green)"
                    : "var(--text-muted)";
    return `<div class="tl-row" data-msg="${esc(e.msg)}"
              style="padding:8px 10px;background:var(--surface);
                     border:1px solid var(--border);border-radius:6px;
                     cursor:pointer;font-size:12px;">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:3px;">
        <span style="font-family:monospace;font-size:10px;color:var(--text-muted);">${esc(time)}</span>
        <span style="padding:1px 6px;background:var(--surface-2);border-radius:3px;font-size:9px;text-transform:uppercase;letter-spacing:.04em;color:${kindColor};">${esc(e.panel)}${e.kind ? " · " + esc(e.kind) : ""}</span>
      </div>
      <div style="word-break:break-word;line-height:1.4;">${esc(e.msg)}</div>
    </div>`;
  }
  function esc(s) {
    return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  // ── Launcher: receive entries posted from child iframes ─────────
  // Only the launcher (top window) has this listener; iframes ignore
  // their own posts to themselves.
  if (window.parent === window) {
    window.addEventListener("message", (ev) => {
      const d = ev?.data || {};
      if (d.type === "toast-log-push" && d.entry) push(d.entry);
    });
  }
})();
