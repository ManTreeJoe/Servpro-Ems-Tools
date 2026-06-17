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
  $("#refresh-btn").addEventListener("click", reloadEverything);
  $("#legacy-btn").addEventListener("click", () => pywebview.api.open_tk_launcher());
  $("#toast-log-btn").addEventListener("click", () => window.openToastLogDrawer?.());
  await loadShell();
  refreshCounts();
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
  renderWelcome();
  updateClock();
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

function renderNavItem(it) {
  const isActive = state.active && state.active.key === it.key;
  return `<div class="sb-item ${isActive ? "active" : ""}"
              data-key="${esc(it.key)}" data-src="${esc(it.src)}"
              data-icon="${esc(it.icon)}" data-name="${esc(it.name)}">
    <span class="sb-icon">${esc(it.icon)}</span>
    <span class="sb-name">${esc(it.name)}</span>
    <span class="sb-badge loading" id="badge-${esc(it.key)}">…</span>
  </div>`;
}

function navigate(key, src, focus) {
  const item = findItem(key);
  if (!item) return;
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
}

function findItem(key) {
  for (const g of state.nav) {
    for (const it of g.items) if (it.key === key) return it;
  }
  return null;
}

function renderWelcome() {
  $("#welcome-greet").innerHTML =
    `${esc(state.header.greeting)}, <strong>Nathan</strong>.`;
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
