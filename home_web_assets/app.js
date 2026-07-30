/* EMS Tools — unified shell front-end.
 *
 * Sidebar lists every tool grouped by category. Click an item →
 * the right pane's iframe loads that tool's existing HTML/CSS/JS.
 * No new window. The iframe_shim.js inside each tool proxies
 * pywebview.api calls to the parent's HomeApi.
 */
"use strict";

const state = {
  nav: [],
  active: null,
  counts: {},
  header: {},
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

window.addEventListener("pywebviewready", async () => {
  // WebView2 focus fix: nudge the app window to the foreground on click so
  // a text field doesn't just blink a caret while the window stays inactive.
  let _focusNudgeAt = 0;
  document.addEventListener("pointerdown", () => {
    const now = Date.now();
    if (now - _focusNudgeAt < 400) return;
    _focusNudgeAt = now;
    try { pywebview?.api?.focus_window?.(); } catch (_) { /* ignore */ }
  }, true);
  $("#refresh-btn").addEventListener("click", reloadEverything);
  $("#legacy-btn").addEventListener("click", () => pywebview.api.open_tk_launcher());
  $("#toast-log-btn").addEventListener("click", () => window.openToastLogDrawer?.());
  await loadShell();
  refreshCounts();
  maybeShowFirstRun();
  maybeCheckUpdate();
  // ── Hybrid live updates ────────────────────────────────────────
  // Sidebar badges auto-refresh every 30 seconds. Pauses when the
  // window is hidden (alt-tabbed away) so we don't burn CPU /
  // Trello quota on a backgrounded app.
  setInterval(() => {
    if (document.visibilityState === "visible") refreshCounts();
  }, 30_000);
  // Clock tick every minute (cheap)
  setInterval(updateClock, 60_000);
  // When the user returns focus to the window, refresh immediately
  // so stale numbers don't sit there until the next interval tick.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshCounts();
  });
});

async function loadShell() {
  state.header = await pywebview.api.header();
  state.nav = await pywebview.api.nav();
  renderSidebar();
  // Reopen the last panel IMMEDIATELY after the sidebar exists — same
  // tick, no further awaits. `last_panel` rode in on header() precisely so
  // there is nothing left to wait for here; any await between the sidebar
  // appearing and this call is a window in which the user could click a
  // tool and then get thrown somewhere else.
  restoreLastPanel();
  renderWelcome();
  updateClock();
  renderDeptSwitch();
}

function restoreLastPanel() {
  if (state.userNavigated) return;          // you clicked first — you win
  const key = state.header?.last_panel;
  if (!key) return;                          // first run, or nothing saved
  const item = findItem(key);
  if (!item) return;                         // panel hidden or gone
  navigate(key, item.src, "", true);
}

// ── Department switcher (multi-account) ────────────────────────────
async function renderDeptSwitch() {
  const host = document.getElementById("dept-switch");
  if (!host) return;
  let st;
  try { st = await pywebview.api.department_state(); } catch (_) { st = null; }
  if (!st?.ok || !st.enabled || !(st.departments || []).length) {
    host.style.display = "none";
    return;
  }
  host.style.display = "flex";
  host.innerHTML = (st.departments || []).map((d) =>
    `<button class="dept-seg ${d.key === st.active ? "active" : ""}"
             data-key="${esc(d.key)}" title="${esc(d.label)}">${esc(d.key)}</button>`
  ).join("");
  host.querySelectorAll(".dept-seg").forEach((b) =>
    b.addEventListener("click", () => switchDept(b.dataset.key, st.active)));
}

async function switchDept(key, active) {
  if (!key || key === active) return;
  const splash = document.getElementById("dept-splash");
  const txt = document.getElementById("dept-splash-txt");
  if (txt) txt.textContent = `Switching to ${key}…`;
  if (splash) splash.classList.remove("hidden");
  // Disable the pills so a double-click can't fire two switches.
  document.querySelectorAll(".dept-seg").forEach((b) => (b.disabled = true));
  const unlock = () => {
    if (splash) splash.classList.add("hidden");
    document.querySelectorAll(".dept-seg").forEach((b) => (b.disabled = false));
  };
  try {
    const r = await pywebview.api.switch_department(key);
    if (!r?.ok) { unlock(); window.toastLog?.(`Switch failed: ${r?.error || "?"}`); return; }
    if (r.unchanged) { unlock(); return; }
    // In-process switch: Python persisted the choice and cleared the
    // workspace-scoped caches; reload the shell so every tool + poller
    // re-reads the now-active department. Sub-Apis read config lazily,
    // so a web reload is enough — no process relaunch.
    if (r.reload) { location.reload(); return; }
    unlock();
  } catch (_) {
    unlock();
  }
}

// Cross-frame message bus — settings panel posts
// {type:"sidebar-reload"} when a panel-visibility toggle changes,
// so the launcher re-renders the sidebar without a full launcher
// reload.
window.addEventListener("message", async (ev) => {
  const d = ev?.data || {};
  if (d.type === "sidebar-reload") {
    state.nav = await pywebview.api.nav();
    renderSidebar();
    refreshCounts();
    renderDeptSwitch();
  } else if (d.type === "ems-navigate" && d.key) {
    // Cross-tool jump from a panel's "Open in…" right-click. Switch the
    // content frame to the target tool, handing it `focus` (a client
    // name) so it filters/selects the job on load.
    const item = findItem(d.key);
    if (item) navigate(d.key, item.src, d.focus || "");
  }
});

function updateClock() {
  // Re-fetch header time from Python (handles tz transitions etc.)
  pywebview.api.header().then((h) => {
    state.header = h;
    $("#time-meta").textContent = `${h.date} · ${h.time}`;
  });
}

function renderSidebar() {
  const nav = $("#sb-nav");
  nav.innerHTML = state.nav.map((g) => `
    <div class="sb-group">${esc(g.label)}</div>
    ${g.items.map(renderNavItem).join("")}
  `).join("");
  $$(".sb-item").forEach((el) =>
    el.addEventListener("click", () => navigate(el.dataset.key, el.dataset.src)));
}

// Update banner — polls the repo's version.txt; shows a bar when newer.
async function maybeCheckUpdate() {
  let r;
  try { r = await pywebview.api.check_update(); } catch (e) { return; }
  if (!r || !r.ok || !r.update_available) return;
  if (document.getElementById("update-bar")) return;
  const bar = document.createElement("div");
  bar.id = "update-bar";
  bar.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:9999;background:var(--accent,#2E8B57);color:#fff;padding:8px 14px;font-size:13px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,.35);";
  bar.innerHTML =
    `<span>⬆️ Update available — <b>v${r.latest}</b> (you have v${r.current})${r.notes ? " · " + r.notes : ""}</span>
     <span style="flex:1;"></span>
     <button id="update-dl" style="background:#fff;color:#2E8B57;border:none;border-radius:5px;padding:5px 12px;font-weight:700;cursor:pointer;">Update now</button>
     <button id="update-x" style="background:transparent;color:#fff;border:1px solid rgba(255,255,255,.5);border-radius:5px;padding:5px 10px;cursor:pointer;">✕</button>`;
  document.body.appendChild(bar);
  const msg = bar.querySelector("span");
  const dl = document.getElementById("update-dl");
  dl.addEventListener("click", async () => {
    dl.disabled = true; dl.style.cursor = "default"; dl.textContent = "Downloading…";
    let res;
    try { res = await pywebview.api.install_update(r.installer || r.url || ""); }
    catch (e) { res = { ok: false, error: String(e) }; }
    if (res && res.ok && res.launched) {
      dl.textContent = "Installer opened ✓";
      if (msg) msg.innerHTML = "⬇️ Installer downloaded — follow the setup prompts. EMS Tools will close and reopen on the new version.";
    } else if (res && res.opened_page) {
      dl.textContent = "Opened page";
      if (msg) msg.innerHTML = "🌐 Opened the download page in your browser — run the setup from there.";
    } else {
      dl.disabled = false; dl.style.cursor = "pointer"; dl.textContent = "Retry";
      if (msg) msg.innerHTML = "⚠️ Update failed: " + ((res && res.error) || "unknown") + " — try again or open the release page.";
      try { pywebview.api.open_url(r.url || ""); } catch (_) {}
    }
  });
  document.getElementById("update-x").addEventListener("click", () => bar.remove());
}

function renderNavItem(it) {
  const isActive = state.active && state.active.key === it.key;
  // A panel whose backend Api failed to import is a dead tab — show ⚠
  // instead of a spinner so it's not silently broken.
  const badge = it.error
    ? `<span class="sb-badge hot" id="badge-${esc(it.key)}" title="This panel failed to load — see ems.log">⚠</span>`
    : `<span class="sb-badge loading" id="badge-${esc(it.key)}">…</span>`;
  return `<div class="sb-item ${isActive ? "active" : ""}${it.error ? " errored" : ""}"
              data-key="${esc(it.key)}" data-src="${esc(it.src)}"
              data-icon="${esc(it.icon)}" data-name="${esc(it.name)}">
    <span class="sb-icon">${esc(it.icon)}</span>
    <span class="sb-name">${esc(it.name)}</span>
    ${badge}
  </div>`;
}

// `isRestore` marks the one navigation the app performs on its own —
// reopening wherever you left off. Anything else is you, and you always
// win: once state.userNavigated is set, the restore is abandoned rather
// than switching the panel out from under you a moment after you clicked.
function navigate(key, src, focus, isRestore) {
  const item = findItem(key);
  if (!item) return;
  if (!isRestore) state.userNavigated = true;
  state.active = item;
  // Update active highlight without re-rendering whole sidebar
  $$(".sb-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.key === key);
  });
  // Hide welcome, show iframe (no crumb header anymore — iframe takes the full pane)
  $("#welcome").classList.add("hidden");
  $("#content-frame").classList.remove("hidden");
  // Deep-link focus (from a cross-tool "Open in…") rides along as a
  // ?focus= query the target panel reads on boot via emsDeepLinkFocus().
  let url = src || item.src;
  if (focus) {
    url += (url.indexOf("?") >= 0 ? "&" : "?") + "focus=" + encodeURIComponent(focus);
  }
  $("#content-frame").src = url;
  // Remember where we are for next launch. Fire-and-forget: a failure here
  // costs a restore, never the navigation the user just asked for. The
  // deep-link `focus` is deliberately NOT stored — reopening tomorrow on a
  // job you were briefly sent to would be worse than reopening the panel.
  if (!isRestore) {
    try { pywebview?.api?.set_last_panel?.(key); } catch (_) { /* ignore */ }
  }
}

function findItem(key) {
  for (const g of state.nav) {
    for (const it of g.items) if (it.key === key) return it;
  }
  return null;
}

// ── First-run welcome modal ──────────────────────────────────────
// Shown once on a fresh machine to point the user at Settings (Trello
// key/token + folder paths). Dismissing either way drops the
// `.configured` marker server-side so it never reappears.
async function maybeShowFirstRun() {
  let info;
  try { info = await pywebview.api.first_run(); } catch { return; }
  if (!info || !info.show) return;
  const overlay = $("#fr-overlay");
  if (!overlay) return;
  const close = () => {
    overlay.classList.add("hidden");
    pywebview.api.dismiss_first_run().catch(() => {});
  };
  $("#fr-later").onclick = close;
  $("#fr-settings").onclick = () => {
    close();
    const item = findItem("settings");
    if (item) navigate("settings", item.src);
  };
  overlay.classList.remove("hidden");
}

function renderWelcome() {
  $("#welcome-greet").innerHTML =
    `${esc(state.header.greeting)}.`;
  // Quick-pick tiles — first item of each group
  const quick = [];
  for (const g of state.nav) {
    if (g.items.length) quick.push(g.items[0]);
  }
  $("#welcome-quick").innerHTML = quick.slice(0, 4).map((it) => `
    <div class="welcome-tile" data-key="${esc(it.key)}" data-src="${esc(it.src)}">
      <div class="wt-icon">${esc(it.icon)}</div>
      <div class="wt-name">${esc(it.name)}</div>
      <div class="wt-meta">Click to open</div>
    </div>`).join("");
  $$(".welcome-tile").forEach((el) =>
    el.addEventListener("click", () => navigate(el.dataset.key, el.dataset.src)));
}

// Sidebar refresh button does THREE things now:
//   1. Reload the current tool's iframe (forces it to re-fetch data)
//   2. Refresh sidebar badge counts
//   3. Spin the ↻ icon for visible feedback so the user knows the
//      click registered (previously: silent no-op feel — the counts
//      may already be up-to-date so nothing visible changed)
async function reloadEverything() {
  const btn = document.getElementById("refresh-btn");
  if (btn) btn.classList.add("spinning");
  try {
    // Re-load the active iframe — this is the part the user actually
    // wants when they hit "reload": refresh the tool they're staring
    // at. The simple `.src = .src` re-assignment forces a navigation
    // even when the URL hasn't changed.
    const frame = document.getElementById("content-frame");
    if (frame && frame.src && frame.src !== "about:blank") {
      // Cache-bust query string so iframe_shim + tool JS re-run
      const url = new URL(frame.src);
      url.searchParams.set("_r", String(Date.now()));
      frame.src = url.toString();
    }
    await refreshCounts();
  } finally {
    setTimeout(() => btn?.classList.remove("spinning"), 600);
  }
}

async function refreshCounts() {
  // Mark all badges loading
  $$(".sb-badge").forEach((b) => { b.textContent = "…"; b.className = "sb-badge loading"; });
  const counts = await pywebview.api.counts();
  state.counts = counts || {};
  for (const [key, val] of Object.entries(state.counts)) {
    const b = document.getElementById(`badge-${key}`);
    if (!b) continue;
    if (val === null || val === undefined) {
      b.textContent = "—"; b.className = "sb-badge";
      continue;
    }
    b.textContent = val;
    b.className = "sb-badge " + kind(key, val);
  }
  // Clear the loading spinner on any panel counts() didn't return a value
  // for — otherwise those badges (notifications, kpi, wc_audit, spreadsheet,
  // multi_unit, cheat_sheet, settings, photo_folders) spin "…" forever.
  $$(".sb-badge").forEach((b) => {
    const key = (b.id || "").replace(/^badge-/, "");
    // Leave the ⚠ dead-panel marker alone; only clear stale spinners.
    if (b.textContent === "⚠") return;
    if (!(key in state.counts)) {
      b.textContent = "";
      b.className = "sb-badge";
    }
  });
}

function kind(key, v) {
  if (typeof v !== "number") return "";
  if (v === 0) return "";
  if (key === "audit") return v > 5 ? "warn" : "ok";
  if (key === "hygiene") return v >= 50 ? "hot" : v >= 20 ? "warn" : "";
  if (key === "snapshot") return v >= 10 ? "warn" : "ok";
  if (key === "disputes") return v >= 50 ? "warn" : "";
  return "";
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
