/* Linguar Hub — shared toast log.
 *
 * Wraps every panel's `setStatus(msg, kind)` so each toast also
 * lands in a session-wide log accessible from the launcher's 🛎
 * button. The log is stored in localStorage so it survives panel
 * navigation. Warnings and errors use a shared, non-modal notice.
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
  if (window._oneLossFeedbackLoaded) return;
  window._oneLossFeedbackLoaded = true;

  const STORAGE_KEY = "ems_toast_log";
  const MAX_ENTRIES = 50;
  const visibleNotices = new Map();

  function noticeStyle() {
    if (document.getElementById('oneloss-notice-style')) return;
    const style = document.createElement('style');
    style.id = 'oneloss-notice-style';
    style.textContent = `
      #oneloss-notices{position:fixed;right:18px;bottom:20px;z-index:2147483000;
        width:min(410px,calc(100vw - 24px));max-height:70vh;overflow:auto;
        display:grid;gap:10px;pointer-events:none;font:14px/1.5 var(--font-body,Segoe UI,sans-serif)}
      .ol-notice{pointer-events:auto;background:var(--surface,#17201b);color:var(--text,#edf3ef);
        border:1px solid var(--border-strong,#50665a);border-left:4px solid #efb762;
        border-radius:9px;padding:14px 16px;box-shadow:0 8px 30px #0005;overflow-wrap:anywhere}
      .ol-notice[data-kind=error]{border-left-color:#e59b88}
      .ol-notice header{display:flex;gap:12px;align-items:start;background:none;padding:0;border:0}
      .ol-notice strong{flex:1;font-size:15px}.ol-notice p{margin:7px 0;color:inherit}
      .ol-notice .ol-context{font-size:12px;color:var(--text-muted,#a9b9b0);margin:0 0 5px}
      .ol-notice button,.ol-notice summary{font:inherit;color:inherit;cursor:pointer}
      .ol-notice button{background:var(--surface-2,#202b25);border:1px solid var(--border-strong,#50665a);
        border-radius:5px;padding:6px 10px;min-height:34px}
      .ol-notice header button{padding:0 8px;background:transparent}
      .ol-notice button:focus-visible,.ol-notice summary:focus-visible{outline:2px solid var(--text,#edf3ef);outline-offset:3px}
      .ol-notice pre{white-space:pre-wrap;max-height:160px;overflow:auto;font:12px/1.5 monospace;margin:8px 0}
      .ol-notice .ol-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
      .ol-notice details{margin-top:8px;font-size:12px}
      @media(max-width:480px){#oneloss-notices{right:12px;bottom:12px;max-height:55vh}}
    `;
    document.head.appendChild(style);
  }

  function cleanDetail(value) {
    return String(value || '').slice(0, 6000)
      .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, 'Bearer [redacted]')
      .replace(/((?:access_token|refresh_token|apikey|api_key|token|password)["']?\s*[:=]\s*["']?)[^\s"'&,}]+/gi, '$1[redacted]');
  }

  function present(entry) {
    if (!['error','warn'].includes(entry.kind)) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', () => present(entry), {once:true});
      return;
    }
    noticeStyle();
    let host = document.getElementById('oneloss-notices');
    if (!host) {
      host = document.createElement('section'); host.id = 'oneloss-notices';
      host.setAttribute('aria-label','Notifications'); document.body.appendChild(host);
    }
    const key = JSON.stringify([entry.panel, entry.kind, entry.msg, entry.details]);
    const previous = visibleNotices.get(key);
    if (previous) {
      previous.count++;
      previous.context.textContent = `${entry.panel} · repeated ${previous.count} times`;
      return;
    }
    const box = document.createElement('article');
    box.className = 'ol-notice'; box.dataset.kind = entry.kind;
    const context = document.createElement('div'); context.className = 'ol-context'; context.textContent = entry.panel;
    const head = document.createElement('header');
    const title = document.createElement('strong');
    const close = document.createElement('button'); close.textContent = '×'; close.setAttribute('aria-label','Dismiss notification');
    const body = document.createElement('p');
    const technical = /HTTP\s*\d|Traceback|SupabaseError|WinError|statement timeout|TimeoutError|42501|57014/.test(entry.msg);
    title.textContent = entry.title || (entry.kind === 'warn' ? 'Needs attention' : 'Action needs attention');
    body.textContent = entry.msg;
    if (technical && !entry.title) {
      if (/403|42501|permission|row.level security/i.test(entry.msg)) {
        title.textContent = 'Permission needed';
        body.textContent = 'This request was refused. Ask an administrator to check your access.';
      } else if (/timeout|timed out|unreachable|WinError|HTTP\s*5\d\d/i.test(entry.msg)) {
        title.textContent = 'Connection needs attention';
        body.textContent = 'The request could not be confirmed. Check the item’s status before trying again.';
      } else {
        body.textContent = 'This action encountered a problem. Open Details for the error information.';
      }
    }
    // Announce text, not every button; do not steal keyboard focus.
    const announcement = document.createElement('div');
    announcement.setAttribute('role', entry.kind === 'error' ? 'alert' : 'status');
    announcement.append(body);
    head.append(title, close); box.append(context, head, announcement);
    if (entry.savedState) {
      const saved = document.createElement('p'); saved.textContent = entry.savedState; box.append(saved);
    }
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = 'Details';
    const pre = document.createElement('pre'); pre.textContent = cleanDetail(entry.details || entry.msg);
    details.append(summary, pre); box.append(details);
    const actions = document.createElement('div'); actions.className = 'ol-actions';
    const copy = document.createElement('button'); copy.textContent = 'Copy details';
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(`${entry.panel}\n${entry.ts}\n${pre.textContent}`); copy.textContent = 'Copied'; }
      catch (_) { copy.textContent = 'Copy unavailable'; details.open = true; }
    };
    actions.append(copy);
    if (typeof entry.retry === 'function') {
      const retry = document.createElement('button'); retry.textContent = 'Retry';
      retry.onclick = async () => {
        retry.disabled = true;
        try {
          const result = await entry.retry();
          if (result === false || result?.ok === false) throw new Error(result?.error || 'Retry was not completed');
          close.click();
        } catch (error) { pre.textContent = cleanDetail(error?.message || error); details.open = true; retry.disabled = false; }
      };
      actions.append(retry);
    }
    box.append(actions);
    close.onclick = () => { visibleNotices.delete(key); box.remove(); };
    visibleNotices.set(key, {box, context, count:1});
    host.append(box);
    while (visibleNotices.size > 3) {
      const first = visibleNotices.keys().next().value;
      visibleNotices.get(first).box.remove(); visibleNotices.delete(first);
    }
  }

  function notify(options) {
    const entry = {ts:new Date().toISOString(),panel:panelName(),kind:'error',...options};
    entry.kind = ({warning:'warn', danger:'error', bad:'error'})[entry.kind] || entry.kind;
    entry.msg = cleanDetail(entry.msg || entry.message || 'Unexpected error');
    entry.details = cleanDetail(entry.details || entry.msg);
    try {
      if (window.parent !== window && window.parent.OneLossNotice) {
        return window.parent.OneLossNotice.show(entry);
      }
    } catch (_) {}
    push({...entry, retry:undefined});
    present(entry);
  }
  window.OneLossNotice = {show:notify};
  if (typeof window.toastLog !== 'function') window.toastLog = (msg, kind='error') => notify({msg,kind});

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
        notify(entry);
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
      z-index:2147483001;background:var(--bg);border-left:1px solid var(--border);
      box-shadow:-6px 0 20px rgba(0,0,0,.5);display:flex;flex-direction:column;`;
    w.innerHTML = `
      <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;">
        <span style="font-size:14px;font-weight:600;">Notifications</span>
        <span class="muted" style="font-size:11px;">${log.length}/50 entries</span>
        <span style="flex:1;"></span>
        <button class="btn" id="tl-clear" style="font-size:11px;padding:3px 10px;">✕ Clear</button>
        <button class="btn" id="tl-close" style="font-size:11px;padding:3px 10px;">Close</button>
      </header>
      <div id="tl-list" style="flex:1;overflow-y:auto;padding:10px 18px;display:flex;flex-direction:column;gap:6px;">
        ${log.length ? log.map(rowHtml).join("") : `<div class="muted" style="padding:30px 0;text-align:center;">No notifications yet.</div>`}
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
          el.style.background = "var(--green-soft)";
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
      const trusted = Array.from(document.querySelectorAll('iframe')).some(frame => frame.contentWindow === ev.source);
      if (trusted && d.type === "toast-log-push" && d.entry) notify(d.entry);
    });
  }
})();
