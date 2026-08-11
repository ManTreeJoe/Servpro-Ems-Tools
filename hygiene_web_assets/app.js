"use strict";
// Hygiene — priority dashboard (rebuild 2026-06-10).
// Count tiles + a single most-urgent-first feed. Backend data contract:
//   api.get_cache()         → {scanned, sections[], display[], stale, age_minutes}
//   api.get_priority_feed() → {items[], total, shown}  (items tagged with
//                              section/display_key/tier — sorted by urgency)
//   api.get_section_items(key, off, lim) → lazy page (used for open-jobs)
// Per-row actions reuse the existing Api methods, dispatched by `section`.

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const api = () => window.pywebview.api;
const esc = (s) => String(s ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

const state = {
  display: [], sectionCount: {}, feed: [], openJobs: [],
  active: "all", search: "", board: "", showOpenJobs: false,
  scanning: false,
  // Per-section "Load more" paging: `extra` holds rows pulled in beyond
  // the bounded priority feed; `sectionOffset` tracks the next page
  // offset per backend section key. Both reset on scan/tile-switch.
  extra: [], sectionOffset: {}, tabsLoaded: false,
};

// ── Per-section row actions. Keyed by the backend section key carried on
// each feed item. Each action: {label, cls, fn(row)->Promise, after}.
// `after: "remove"` optimistically drops the row on success. ────────────
const A = (label, cls, fn) => ({ label, cls, fn, after: "remove" });
const SECTION_ACTIONS = {
  estimates: [
    A("✓ Ack", "go", (r) => api().ack_estimate(r.card_id, r.client, r.body || "")),
    A("✕", "warn", (r) => api().estimate_dismiss(r.request_id || "")),
  ],
  adjuster_pending: [
    A("✓ Post", "go", (r) => api().post_adjuster_inquiry(r.card_id, r.client, r.body || "")),
    A("✕", "warn", (r) => api().adjuster_dismiss(r.message_id || "")),
  ],
  xa_inquiries: [
    A("✓ Add to tracker", "go", (r) => api().approve_xa_inquiry(r.message_id || "")),
    A("✕", "warn", (r) => api().dismiss_xa_inquiry(r.message_id || "")),
  ],
  ipr: [A("✓ Confirm", "go", (r) => api().confirm_ipr(r.card_id, r.client, r.body || ""))],
  xa_apology: [A("✓ Handled", "go", (r) => api().mark_xa_handled(r.card_id))],
  docusketch_needed: [A("📐 Request", "go", (r) => api().mark_docusketch_requested(r.card_id, r.client, r.body || ""))],
  docusketch: [A("✓ Imported", "go", (r) => api().resolve_docusketch_request(r.card_id))],
  docusign: [A("✓ Signed", "go", (r) => api().resolve_docusign_request(r.card_id))],
  docusign_resends: [
    A("✓ Signed", "go", (r) => api().docusign_resend_signed(r.request_id || "")),
    A("📧 Resend", "", (r) => api().docusign_resend_physical(r.request_id || "")),
  ],
  missing_items: [
    A("✓ Resolved", "go", (r) => api().missing_item_resolved(r.request_id || "")),
    A("✕ Ignore", "warn", (r) => api().missing_item_ignored(r.request_id || "")),
  ],
  xa_gaps: [A("✓ Resolved", "go", (r) => api().mark_xa_gap_resolved(r.group_key || ""))],
  closeout: [A("✓ Drafted", "go", (r) => api().closeout_mark_drafted(r.card_id))],
  weekly: [A("✓ Note sent", "go", (r) => api().send_weekly_note(r.card_id, r.client, r.body || ""))],
  handoff: [A("✓ Handoff", "go", (r) => api().mark_handoff_done(r.card_id, r.client, r.body || ""))],
  hygiene: [{ label: "💤 Snooze", cls: "", after: "remove",
    fn: (r) => api().dismiss(r.card_id, r.rule || "hygiene", 24) }],
  wc_audit_due: [{ label: "Open WC Audit", cls: "go", after: "",
    fn: () => api().navigate("wc_audit_web") }],
};

window.addEventListener("pywebviewready", async () => {
  // Restore the view you left: active tile, search text, board filter and
  // the open-jobs toggle. Panels are torn down on navigate, so without
  // this every trip back through Hygiene reset all four.
  await PanelState.init("hygiene");
  state.active        = PanelState.get("active", state.active);
  state.search        = PanelState.get("search", "");
  state.board         = PanelState.get("board", "");
  state.showOpenJobs  = !!PanelState.get("showOpenJobs", false);
  const _sb = $("#search-box"); if (_sb) _sb.value = state.search;
  const _oj = $("#show-open-jobs"); if (_oj) _oj.checked = state.showOpenJobs;

  $("#scan-btn").addEventListener("click", () => runScan(false));
  $("#scan-min-btn").addEventListener("click", () => runScan(true));
  $("#cancel-btn").addEventListener("click", async () => { await api().cancel_scan(); });
  $("#xa-scan-btn").addEventListener("click", runXaScan);
  $("#diag-btn").addEventListener("click", openDiag);
  $("#search-box").addEventListener("input", (e) => {
    state.search = e.target.value; PanelState.set({ search: state.search }); renderFeed();
  });
  $("#board-filter").addEventListener("change", (e) => {
    state.board = e.target.value; PanelState.set({ board: state.board }); renderFeed();
  });
  $("#show-open-jobs").addEventListener("change", onToggleOpenJobs);
  window.addEventListener("hygiene:scan-progress", (ev) => {
    const d = ev.detail || {};
    setScanState(`Scanning ${d.i || 0}/${d.n || "?"} · ${d.label || d.name || "…"}`);
  });
  window.addEventListener("hygiene:scan-done", async (ev) => {
    const d = ev.detail || {};
    state.scanning = false;
    $("#cancel-btn").classList.add("hidden");
    $("#scan-btn").disabled = false;
    if (d.ok === false) { setStatus(`Scan failed: ${d.error || "?"}`, "error"); }
    else setStatus(`✓ Scan complete${d.count != null ? " · " + d.count + " items" : ""}`, "ok");
    await load();
  });
  await loadBoards();
  // loadBoards populates the <select>; only now can the saved value stick.
  const _bf = $("#board-filter");
  if (_bf && state.board) _bf.value = state.board;
  await load();
});

async function loadBoards() {
  try {
    const boards = await api().list_boards() || [];
    const sel = $("#board-filter");
    for (const b of boards) {
      const o = document.createElement("option");
      o.value = b.id || b.board_id || "";
      o.textContent = b.name || b.board_name || o.value;
      sel.appendChild(o);
    }
  } catch { /* boards optional */ }
}

async function load() {
  const c = await api().get_cache();
  state.display = c.display || [];
  state.sectionCount = {};
  for (const s of (c.sections || [])) state.sectionCount[s.key] = s.count || 0;
  // Fresh cache → discard any paged-in extras + offsets.
  state.extra = []; state.sectionOffset = {};
  // Populate the per-tab scan dropdown once (tabs are static).
  if (!state.tabsLoaded && (c.tabs || []).length) {
    const sel = $("#scan-tab");
    for (const t of c.tabs) {
      const o = document.createElement("option");
      o.value = t.key || "";
      o.textContent = "↻ " + (t.label || t.key || "");
      sel.appendChild(o);
    }
    state.tabsLoaded = true;
  }
  // Cache-age + staleness badge.
  const age = c.age_minutes;
  const ageEl = $("#cache-age");
  if (!c.scanned) ageEl.textContent = "never scanned — run a scan";
  else if (age == null) ageEl.textContent = "";
  else {
    const txt = age < 60 ? `${age}m ago` : `${Math.floor(age / 60)}h ago`;
    ageEl.innerHTML = c.very_stale ? `<span class="stale-badge very">⚠ ${txt}</span>`
      : c.stale ? `<span class="stale-badge">${txt}</span>` : `scanned ${txt}`;
  }
  // Priority feed (bounded, urgency-sorted, from the in-memory cache).
  const f = await api().get_priority_feed(null, 200);
  state.feed = f.items || [];
  if (state.showOpenJobs) await fetchOpenJobs(); else state.openJobs = [];
  renderTiles();
  renderFeed();
}

function tileCount(d) {
  return (d.keys || []).reduce((n, k) => n + (state.sectionCount[k] || 0), 0);
}

function renderTiles() {
  const tiles = $("#tiles");
  const total = state.display.reduce((n, d) => n + (d.feed === false ? 0 : tileCount(d)), 0);
  let html = `<div class="tile all ${state.active === "all" ? "active" : ""}" data-key="all">
    <span class="tile-icon">📋</span>
    <span class="tile-meta"><span class="tile-count">${total}</span>
    <span class="tile-label">All action items</span></span></div>`;
  for (const d of state.display) {
    if (d.feed === false) continue;
    const n = tileCount(d);
    html += `<div class="tile tier-${d.tier} ${n === 0 ? "zero" : ""} ${state.active === d.key ? "active" : ""}" data-key="${esc(d.key)}">
      <span class="tile-icon">${d.icon}</span>
      <span class="tile-meta"><span class="tile-count">${n}</span>
      <span class="tile-label">${esc(d.label)}</span></span></div>`;
  }
  tiles.innerHTML = html;
  $$(".tile").forEach((t) => t.addEventListener("click", () => {
    state.active = t.dataset.key;
    PanelState.set({ active: state.active });
    // Switching tiles drops the previous tile's paged-in extras.
    state.extra = []; state.sectionOffset = {};
    renderTiles(); renderFeed();
  }));
}

function feedRows() {
  let rows = state.feed.slice();
  if (state.extra.length) rows = rows.concat(state.extra);
  if (state.showOpenJobs) rows = rows.concat(state.openJobs);
  const q = state.search.trim().toLowerCase();
  return rows.filter((r) => {
    if (state.active !== "all" && r.display_key !== state.active) return false;
    if (state.board && r.board_id !== state.board) return false;
    if (q && ![r.client, r.subtitle, r.display_label, r.board_name]
      .join(" ").toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderFeed() {
  const rows = feedRows();
  const d = state.display.find((x) => x.key === state.active);
  $("#feed-title").textContent = state.active === "all" ? "All action items"
    : `${d ? d.icon + " " + d.label : state.active}`;
  $("#feed-count").textContent = `${rows.length} shown`;
  $("#feed-empty").classList.toggle("hidden", rows.length > 0);
  let html = rows.map(rowHtml).join("");
  // Per-section "Load more" — only on a single-section view whose backend
  // sections still hold cached items we haven't pulled into the feed.
  if (canLoadMore(d)) {
    html += `<div class="load-more-wrap"><button class="load-more" id="load-more-btn">Load more</button></div>`;
  }
  $("#feed").innerHTML = html;
  bindRows(rows);
  $("#load-more-btn")?.addEventListener("click", loadMore);
}

// Count of rows we currently hold (feed + paged extras) for the display
// tile's backend section keys, ignoring search/board filters — so the
// "Load more" affordance reflects what's actually cached, not what's
// momentarily filtered out of view.
function loadedForTile(d) {
  const keys = new Set(d.keys || []);
  return state.feed.concat(state.extra)
    .filter((r) => keys.has(r.section)).length;
}

function canLoadMore(d) {
  if (state.active === "all" || !d || d.feed === false) return false;
  return loadedForTile(d) < tileCount(d);
}

async function loadMore() {
  const d = state.display.find((x) => x.key === state.active);
  if (!d) return;
  const btn = $("#load-more-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
  const seen = new Set(
    state.feed.concat(state.extra, state.openJobs).map(rowKey));
  let added = 0;
  for (const k of (d.keys || [])) {
    const offset = state.sectionOffset[k] || 0;
    let res;
    try { res = await api().get_section_items(k, offset, 50); }
    catch { continue; }
    for (const it of (res.items || [])) {
      const row = { ...it, section: k, display_key: d.key,
        display_label: d.label, display_icon: d.icon, tier: d.tier };
      const key = rowKey(row);
      if (seen.has(key)) continue;
      seen.add(key); state.extra.push(row); added++;
    }
    state.sectionOffset[k] = res.next_offset != null
      ? res.next_offset : offset + (res.items || []).length;
  }
  renderFeed();
  if (!added) setStatus("No more items in this section", "ok");
}

// Stable identity for dedup across the priority feed + paged extras.
function rowKey(r) {
  return r.card_id || r.request_id || r.message_id || r.group_key
    || `${r.section}|${r.client}|${r.subtitle}`;
}

function rowHtml(r, i) {
  const acts = (SECTION_ACTIONS[r.section] || []).map((a, j) =>
    `<button class="act ${a.cls || ""}" data-act="${j}">${esc(a.label)}</button>`).join("");
  const xa = r.card_id ? `<button class="act icon" data-xa="1" title="Open XactAnalysis link">🔗</button>` : "";
  const trello = r.card_url ? `<button class="act icon" data-trello="1" title="Open Trello card"><img src="../web_shared/trello.png" alt="T" style="width:13px;height:13px;vertical-align:middle;" onerror="this.replaceWith(document.createTextNode('↗'))"/></button>` : "";
  const days = (r.days && Number(r.days) > 0) ? `<span class="days">${Number(r.days)}d</span>` : "";
  return `<div class="row tier-${r.tier ?? 2}" data-i="${i}">
    <span class="urg"></span>
    <span class="sec-chip">${r.display_icon || ""} ${esc(r.display_label || r.section || "")}</span>
    <span class="body">
      <div class="client" data-open="1">${esc(r.client || "(no name)")}</div>
      <div class="subtitle">${esc(r.subtitle || "")}</div>
    </span>
    <span class="acts">${days}${acts}${trello}${xa}</span>
  </div>`;
}

function bindRows(rows) {
  $$("#feed .row").forEach((el) => {
    const r = rows[Number(el.dataset.i)];
    if (!r) return;
    el.querySelector('[data-open]')?.addEventListener("click", () => {
      if (r.card_url) api().open_url(r.card_url);
    });
    el.querySelector('[data-trello]')?.addEventListener("click", () => api().open_url(r.card_url));
    el.querySelector('[data-xa]')?.addEventListener("click", async () => {
      const url = await api().open_xa_link(r.card_id);
      if (!url) setStatus("No XA link on this card", "warn");
    });
    el.querySelectorAll('.act[data-act]').forEach((b) =>
      b.addEventListener("click", () => doAction(r, Number(b.dataset.act), el)));
    if (r.card_id && window.attachTrelloHover) window.attachTrelloHover(el, r.card_id);
  });
}

async function doAction(r, idx, el) {
  const a = (SECTION_ACTIONS[r.section] || [])[idx];
  if (!a) return;
  el.style.opacity = ".5";
  let res;
  try { res = await a.fn(r); } catch (ex) { res = { ok: false, error: String(ex) }; }
  if (res && res.ok === false) {
    el.style.opacity = "";
    setStatus(`${a.label} failed: ${res.error || "?"}`, "error");
    return;
  }
  setStatus(`${a.label} · ${r.client || ""}`, "ok");
  if (a.after === "remove") {
    state.feed = state.feed.filter((x) => x !== r);
    state.extra = state.extra.filter((x) => x !== r);
    state.openJobs = state.openJobs.filter((x) => x !== r);
    // Decrement the tile count so the dashboard stays in sync without a rescan.
    if (state.sectionCount[r.section] > 0) state.sectionCount[r.section]--;
    renderTiles(); renderFeed();
  }
}

// ── Open-jobs toggle (demoted from a tile to an opt-in list) ─────────
async function onToggleOpenJobs(e) {
  state.showOpenJobs = e.target.checked;
  PanelState.set({ showOpenJobs: state.showOpenJobs });
  if (state.showOpenJobs && !state.openJobs.length) await fetchOpenJobs();
  renderFeed();
}
async function fetchOpenJobs() {
  try {
    const r = await api().get_section_items("open_jobs", 0, 200);
    state.openJobs = (r.items || []).map((it) => ({
      ...it, section: "open_jobs", display_key: "open_jobs",
      display_label: "Open job", display_icon: "📋", tier: 3,
    }));
  } catch { state.openJobs = []; }
}

// ── Scans ───────────────────────────────────────────────────────────
async function runScan(minimal) {
  if (state.scanning) return;
  state.scanning = true;
  $("#scan-btn").disabled = true;
  $("#cancel-btn").classList.remove("hidden");
  // Optional per-tab scope — limits the scan to one group of sections.
  const tabSel = $("#scan-tab");
  const tab = tabSel ? (tabSel.value || "") : "";
  const tabLabel = tab
    ? (tabSel.selectedOptions[0]?.textContent || tab).replace(/^↻\s*/, "")
    : "all tabs";
  setScanState(`${minimal ? "Minimal" : "Full"} scan starting… · ${tabLabel}`);
  const r = minimal ? await api().run_minimal_scan(tab) : await api().run_scan(tab);
  if (r && r.ok === false) {
    state.scanning = false;
    $("#scan-btn").disabled = false;
    $("#cancel-btn").classList.add("hidden");
    setStatus(`Couldn't start scan: ${r.error || "?"}`, "error");
  }
}

async function runXaScan() {
  const btn = $("#xa-scan-btn");
  btn.disabled = true; const t = btn.textContent; btn.textContent = "Scanning…";
  // Refresh the adjuster-receipt queue too (fire-and-forget — it emits its
  // own progress and repopulates the 📨 Adjuster inquiries section).
  try { api().run_adjuster_scan(14); } catch { /* optional */ }
  const r = await api().run_xa_inquiry_scan(30);
  btn.disabled = false; btn.textContent = t;
  if (!r || r.ok === false) { setStatus(`Inbox scan failed: ${r?.error || "?"}`, "error"); return; }
  setStatus(`📨 Inbox scan · ${r.queued || 0} new XA inquir${r.queued === 1 ? "y" : "ies"} (of ${r.scanned || 0} mail)`, "ok");
  await load();
}

// ── Diagnostics + clear cache ───────────────────────────────────────
async function openDiag() {
  setStatus("Loading diagnostics…");
  let info;
  try { info = await api().get_scan_diagnostics(); }
  catch (ex) { setStatus(`Diag failed: ${ex}`, "error"); return; }
  setStatus("");
  renderDiag(info || {});
}

function renderDiag(info) {
  closeDiag();
  const c = info.cache || {};
  const ls = info.last_status || {};
  const val = (v) => (v == null || v === "" ? "—" : v);
  const rows = [
    ["Worker script", info.worker_exists ? "✓ present" : "✗ MISSING"],
    ["Last scan state", val(ls.state || ls.status)],
    ls.error ? ["Last error", String(ls.error)] : null,
    ["Cache", c.empty ? "empty (never scanned)"
      : (c.age_min != null ? `${c.age_min} min old` : "present")],
    ["Persistence file", info.persistence_kb != null
      ? `${info.persistence_kb} KB` : "—"],
    ["Hygiene items", val(c.hygiene)],
    ["Closeout", val(c.closeout)],
    ["IPR", val(c.ipr)],
    ["Estimates", val(c.estimates)],
    ["XA gaps", val(c.xa_gaps)],
  ].filter(Boolean);
  const tbl = rows.map(([k, v]) =>
    `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join("");
  const back = document.createElement("div");
  back.className = "modal-backdrop";
  back.id = "diag-modal";
  back.innerHTML = `<div class="modal">
    <div class="modal-head"><span class="title">🩺 Scan diagnostics</span></div>
    <div class="modal-body">
      <table class="diag-table">${tbl}</table>
      <p class="muted" style="margin-top:12px;">Clearing the cache frees memory and forces the next scan to rebuild from scratch. Use it if the panel is slow or the laptop is low on memory.</p>
    </div>
    <div class="modal-foot">
      <button class="btn danger" id="diag-clear">🗑 Clear cache</button>
      <span class="spacer"></span>
      <button class="btn" id="diag-close">Close</button>
    </div></div>`;
  document.body.appendChild(back);
  back.addEventListener("click", (e) => { if (e.target === back) closeDiag(); });
  $("#diag-close").addEventListener("click", closeDiag);
  $("#diag-clear").addEventListener("click", async () => {
    const b = $("#diag-clear");
    b.disabled = true; b.textContent = "Clearing…";
    let r;
    try { r = await api().clear_hygiene_cache(); }
    catch (ex) { r = { ok: false, error: String(ex) }; }
    closeDiag();
    if (r && r.ok === false) {
      setStatus(`Clear cache failed: ${r.error || "?"}`, "error");
      return;
    }
    setStatus("🗑 Cache cleared — run a scan to rebuild", "ok");
    await load();
  });
}

function closeDiag() { document.getElementById("diag-modal")?.remove(); }

// ── Status helpers ──────────────────────────────────────────────────
let _t = null;
function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
  if (_t) clearTimeout(_t);
  if (kind === "ok") _t = setTimeout(() => { el.textContent = ""; el.className = "status-msg"; }, 4000);
}
function setScanState(msg) { $("#scan-state").textContent = msg || ""; }
