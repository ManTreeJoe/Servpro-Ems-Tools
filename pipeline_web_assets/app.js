/* Linguar Hub Pipeline — Pywebview frontend.
 *
 * Two views, one panel:
 *   🗂 Board  — a live Trello-style kanban of the WORK IN PROGRESS and
 *               ESTIMATING boards. Real lanes as columns, cards pulled
 *               fresh from Trello, drag-to-move (with a confirm that
 *               writes back to Trello), plus per-card audit buttons.
 *   📊 Stages — the lifecycle stage table (read-only, from ems_db) with
 *               filter chips, sort, timeline, thresholds, export, sync.
 *
 * Vanilla JS, no build step. Talks to Python via pywebview.api.
 */
"use strict";

const state = {
  view: "board",            // "board" | "stages"
  // Board view
  board: { boards: [] },
  activeBoardKey: null,     // which board is shown (one at a time)
  drag: null,               // {cardId, name, fromListId, fromLane, boardKey}
  // Stages table view
  rows: [],
  stages: [],               // [{key, label}]
  stage_counts: {},
  active_stage: "all",
  search: "",
  sort_key: "days_in_stage",
  sort_dir: "desc",
  selected_card_id: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  $("#view-board-btn").addEventListener("click", () => setView("board"));
  $("#view-stages-btn").addEventListener("click", () => setView("stages"));
  $("#refresh-btn").addEventListener("click", () => loadBoard(true));

  // Stages-table controls
  $("#sync-btn").addEventListener("click", onSyncClick);
  $("#thresholds-btn").addEventListener("click", openThresholdsModal);
  $("#export-btn").addEventListener("click", async () => {
    const btn = $("#export-btn");
    btn.disabled = true; btn.textContent = "Exporting…";
    const res = await pywebview.api.export_to_excel();
    btn.disabled = false; btn.textContent = "📊 Export";
    if (!res?.ok) { setStatus(`Export failed: ${res?.error || "?"}`, "error"); return; }
    setStatus(`📊 Exported ${res.rows} rows · ${res.stages} sheets → ${res.path}`, "ok");
  });
  $("#search-box").addEventListener("input", onSearchInput);
  $$(".pipeline-table thead th").forEach((th) => {
    th.addEventListener("click", () => onSortClick(th.dataset.sort));
  });
  document.addEventListener("click", hideCtxMenu);
  $$("#ctx-menu button").forEach((btn) => {
    btn.addEventListener("click", () => onCtxAction(btn.dataset.action));
  });
  window.addEventListener("pipeline:sync-progress", onSyncProgress);
  window.addEventListener("pipeline:sync-done", onSyncDone);

  await loadBoard();   // board is the default view
});

// ── View switching ───────────────────────────────────────────────
function setView(v) {
  if (state.view === v) return;
  state.view = v;
  $("#view-board-btn").classList.toggle("active", v === "board");
  $("#view-stages-btn").classList.toggle("active", v === "stages");
  $("#board-view").classList.toggle("hidden", v !== "board");
  $("#table-view").classList.toggle("hidden", v !== "stages");
  $$(".view-board-only").forEach((el) => el.classList.toggle("hidden", v !== "board"));
  $$(".view-stages-only").forEach((el) => el.classList.toggle("hidden", v !== "stages"));
  $("#search-box").placeholder = v === "board"
    ? "🔎 Search client / lane…" : "🔎 Search client / lane / owner…";
  if (v === "stages" && !state.stages.length) loadStages();
  else if (v === "stages") renderTable();
  else renderBoard();
}

// ════════════════════════════════════════════════════════════════
//  BOARD VIEW
// ════════════════════════════════════════════════════════════════
async function loadBoard(isRefresh) {
  const btn = $("#refresh-btn");
  if (isRefresh) { btn.disabled = true; btn.textContent = "↻ Refreshing…"; }
  if (!isRefresh) $("#board-loading")?.classList.remove("hidden");
  setStatus("Loading boards from Trello…");
  try {
    const res = await pywebview.api.board_view();
    if (!res?.ok) { setStatus(`Board load failed: ${res?.error || "?"}`, "error"); return; }
    state.board = res;
    renderBoard();
    const total = boardCardTotal();
    setStatus(`✓ ${total} cards across ${res.boards.length} boards`, "ok");
  } catch (ex) {
    setStatus(`Board error: ${ex}`, "error");
  } finally {
    if (isRefresh) { btn.disabled = false; btn.textContent = "↻ Refresh"; }
  }
}

async function refreshOneBoard(key) {
  const name = (state.board.boards || []).find((b) => b.key === key)?.name || key;
  setStatus(`Refreshing ${name}…`);
  try {
    const res = await pywebview.api.board_view_one(key);
    if (!res?.ok) { setStatus(`Refresh failed: ${res?.error || "?"}`, "error"); return; }
    const idx = (state.board.boards || []).findIndex((b) => b.key === key);
    if (idx >= 0) state.board.boards[idx] = res.board;
    renderBoard();
    setStatus(`✓ Refreshed ${res.board.name || name}`, "ok");
  } catch (ex) {
    setStatus(`Refresh error: ${ex}`, "error");
  }
}

function boardCardTotal() {
  let n = 0;
  for (const b of state.board.boards || [])
    for (const l of b.lanes || []) n += (l.cards || []).length;
  return n;
}

// ONE board at a time: a tab strip switches between WORK IN PROGRESS and
// ESTIMATING; only the active board's lanes render. The lanes row is
// `data-hdrag` so h_scroll.js gives it Trello-style grab-to-scroll.
function renderBoard() {
  const root = $("#board-view");
  const boards = state.board.boards || [];
  if (!boards.length) {
    root.innerHTML = `<div class="empty-state"><div class="empty-emoji">🛤</div>
      <div>No boards loaded. Click ↻ Refresh.</div></div>`;
    return;
  }
  const q = state.search.trim().toLowerCase();
  let active = boards.find((b) => b.key === state.activeBoardKey) || boards[0];
  state.activeBoardKey = active.key;
  const countFor = (b) =>
    (b.lanes || []).reduce((s, l) => s + laneMatches(l, q).length, 0);

  const tabs = boards.map((b) =>
    `<button class="board-tab ${b.key === active.key ? "active" : ""}" data-board-tab="${escapeAttr(b.key)}">
       ${escapeHtml(b.name)} <span class="board-tab-count">${countFor(b)}</span>
     </button>`).join("");

  let lanesHtml;
  if (active.missing) {
    lanesHtml = `<div class="board-warn" style="padding:24px;">"${escapeHtml(active.name)}" not found on Trello.</div>`;
  } else {
    const lanes = (active.lanes || []).map((l) => renderLane(active, l, q)).join("");
    lanesHtml = `<div class="lanes-row" data-hdrag data-hdrag-nowheel>${lanes || `<div class="lane-empty">No lanes.</div>`}</div>`;
  }

  root.innerHTML = `
    <div class="board-tabs">
      ${tabs}
      <span class="board-tabs-spacer"></span>
      <button class="board-refresh" data-refresh-board="${escapeAttr(active.key)}" title="Refresh this board from Trello">↻ Refresh</button>
    </div>
    ${lanesHtml}`;

  // Board tabs.
  root.querySelectorAll("[data-board-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      state.activeBoardKey = b.dataset.boardTab;
      renderBoard();
    }));
  // Per-board ↻ refresh.
  root.querySelectorAll("[data-refresh-board]").forEach((b) =>
    b.addEventListener("click", () => refreshOneBoard(b.dataset.refreshBoard)));

  // Wire drag + drop + per-card actions.
  root.querySelectorAll(".lane").forEach((laneEl) => {
    laneEl.addEventListener("dragover", onLaneDragOver);
    laneEl.addEventListener("dragleave", onLaneDragLeave);
    laneEl.addEventListener("drop", onLaneDrop);
  });
  root.querySelectorAll(".kcard").forEach((cardEl) => {
    cardEl.addEventListener("dragstart", onCardDragStart);
    cardEl.addEventListener("dragend", onCardDragEnd);
    cardEl.addEventListener("contextmenu", onCardContext);
    cardEl.querySelector(".kcard-title")?.addEventListener("click", () => {
      const url = cardEl.dataset.url;
      if (url) pywebview.api.open_url(url);
    });
    cardEl.querySelector('[data-act="audit"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); onAuditCard(cardEl);
    });
    cardEl.querySelector('[data-act="flag"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); onFlagCard(cardEl);
    });
    cardEl.querySelector('[data-act="more"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); openCardMenu(e, cardEl);
    });
  });
}

function laneMatches(lane, q) {
  if (!q) return lane.cards || [];
  return (lane.cards || []).filter((c) =>
    `${c.client} ${lane.name}`.toLowerCase().includes(q));
}

function renderLane(board, lane, q) {
  const cards = laneMatches(lane, q);
  // When searching, hide lanes with no matches to cut clutter.
  if (q && !cards.length) return "";
  const cardsHtml = cards.length
    ? cards.map((c) => renderCard(c)).join("")
    : `<div class="lane-empty">—</div>`;
  return `<div class="lane" data-list-id="${escapeAttr(lane.list_id)}"
               data-lane-name="${escapeAttr(lane.name)}"
               data-board-key="${escapeAttr(board.key)}">
    <div class="lane-head">
      <span class="lane-name">${escapeHtml(lane.name)}</span>
      <span class="lane-count">${cards.length}</span>
    </div>
    <div class="lane-cards">${cardsHtml}</div>
  </div>`;
}

function renderCard(c) {
  const loss = (c.loss_types || []).map((t) =>
    `<span class="chip-loss loss-${escapeAttr(t.toLowerCase())}">${escapeHtml(t)}</span>`).join("");
  const ck = c.checklist || { done: 0, total: 0 };
  const ckChip = ck.total
    ? `<span class="chip-mini ${ck.done >= ck.total ? "ck-done" : ""}" title="Checklist progress">✓ ${ck.done}/${ck.total}</span>`
    : "";
  const dueChip = c.due
    ? `<span class="chip-mini ${c.overdue ? "due-over" : "due"}" title="Due date">📅 ${escapeHtml(fmtDue(c.due))}</span>`
    : "";
  const stallChip = c.days_in_lane > 0
    ? `<span class="chip-mini stall-${escapeAttr(c.stall)}" title="Days since last activity">${c.days_in_lane}d</span>`
    : "";
  const chips = [loss, ckChip, dueChip, stallChip].filter(Boolean).join("");
  return `<div class="kcard stall-border-${escapeAttr(c.stall)}" draggable="true"
               data-card-id="${escapeAttr(c.card_id)}"
               data-list-id="${escapeAttr(c.list_id)}"
               data-url="${escapeAttr(c.url)}"
               data-client="${escapeAttr(c.client)}">
    <div class="kcard-title" title="Open in Trello">${escapeHtml(c.client || "(no name)")}</div>
    ${chips ? `<div class="kcard-chips">${chips}</div>` : ""}
    <div class="kcard-actions">
      <button class="kbtn" data-act="audit" title="Run audit on this job">🔎</button>
      <button class="kbtn" data-act="flag" title="Flag a missing item + comment Trello">🚩</button>
      <button class="kbtn" data-act="more" title="Open in… / Trello / folder / XA">⋯</button>
    </div>
  </div>`;
}

// ── Drag to move (write-back with confirm) ───────────────────────
function onCardDragStart(ev) {
  const el = ev.currentTarget;
  state.drag = {
    cardId:   el.dataset.cardId,
    name:     el.dataset.client,
    fromListId: el.dataset.listId,
  };
  el.classList.add("dragging");
  try { ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", el.dataset.cardId); } catch (_) {}
}

function onCardDragEnd(ev) {
  ev.currentTarget.classList.remove("dragging");
  $$(".lane.drop-target").forEach((l) => l.classList.remove("drop-target"));
}

function onLaneDragOver(ev) {
  if (!state.drag) return;
  ev.preventDefault();
  try { ev.dataTransfer.dropEffect = "move"; } catch (_) {}
  ev.currentTarget.classList.add("drop-target");
}

function onLaneDragLeave(ev) {
  ev.currentTarget.classList.remove("drop-target");
}

async function onLaneDrop(ev) {
  ev.preventDefault();
  const laneEl = ev.currentTarget;
  laneEl.classList.remove("drop-target");
  const drag = state.drag;
  state.drag = null;
  if (!drag) return;
  const toListId = laneEl.dataset.listId;
  const toLane = laneEl.dataset.laneName;
  if (!toListId || toListId === drag.fromListId) return;   // same lane, no-op
  if (!confirm(`Move "${drag.name}" to "${toLane}" on Trello?\n\nThis updates the real board everyone sees.`))
    return;
  setStatus(`Moving "${drag.name}" → ${toLane}…`);
  const res = await pywebview.api.move_card(drag.cardId, toListId);
  if (!res?.ok) {
    setStatus(`Move failed: ${res?.error || "?"}`, "error");
    await loadBoard(true);   // re-pull truth from Trello
    return;
  }
  // Optimistic local move so the board updates instantly.
  moveCardLocally(drag.cardId, drag.fromListId, toListId, toLane);
  renderBoard();
  setStatus(`✓ Moved "${drag.name}" → ${toLane}`, "ok");
}

function moveCardLocally(cardId, fromListId, toListId, toLane) {
  let moved = null;
  for (const b of state.board.boards || []) {
    for (const l of b.lanes || []) {
      if (l.list_id !== fromListId) continue;
      const i = (l.cards || []).findIndex((c) => c.card_id === cardId);
      if (i >= 0) { moved = l.cards.splice(i, 1)[0]; break; }
    }
    if (moved) break;
  }
  if (!moved) return;
  moved.list_id = toListId; moved.lane = toLane;
  for (const b of state.board.boards || []) {
    for (const l of b.lanes || []) {
      if (l.list_id === toListId) { (l.cards = l.cards || []).unshift(moved); return; }
    }
  }
}

// ── Per-card actions ─────────────────────────────────────────────
async function onAuditCard(cardEl) {
  const client = cardEl.dataset.client;
  setStatus(`Auditing "${client}"…`);
  const res = await pywebview.api.audit_card(client);
  if (!res?.ok) { setStatus(`Audit failed: ${res?.error || "?"}`, "error"); return; }
  setStatus("");
  openAuditModal(res);
}

async function onFlagCard(cardEl) {
  const client = cardEl.dataset.client;
  const cardId = cardEl.dataset.cardId;
  const item = prompt(`Flag a missing item for "${client}":\n\n(posts a 🚩 comment on the Trello card)`, "");
  if (!item || !item.trim()) return;
  const res = await pywebview.api.flag_missing_card(cardId, client, item.trim(), "");
  if (!res?.ok) { setStatus(`Flag failed: ${res?.error || "?"}`, "error"); return; }
  setStatus(res.posted_trello ? `🚩 Flagged "${item.trim()}" + commented Trello` : `🚩 Flagged "${item.trim()}"`, "ok");
}

function openCardMenu(ev, cardEl) {
  const client = cardEl.dataset.client;
  const cardId = cardEl.dataset.cardId;
  if (!window.emsOpenInMenu) return;
  window.emsOpenInMenu(ev, client, {
    extra: [
      { label: "🔎 Run audit on this job", action: () => onAuditCard(cardEl) },
      { label: "🚩 Flag missing item…", action: () => onFlagCard(cardEl) },
    ],
  });
}

function onCardContext(ev) {
  ev.preventDefault();
  openCardMenu(ev, ev.currentTarget);
}

// ── Audit result modal (compact summary) ─────────────────────────
function openAuditModal(res) {
  const issues = [];
  (res.form_issues || []).forEach((f) => issues.push({ kind: "Form", text: f }));
  (res.photo_issues || []).forEach((p) => issues.push({ kind: "Photos", text: p }));
  (res.requirements || []).forEach((r) => issues.push({ kind: "Photos", text: r }));
  const clean = res.found && !issues.length;
  const body = !res.found
    ? `<div class="aud-bad">📁 No job folder found for this client.</div>`
    : clean
      ? `<div class="aud-ok">✓ All required forms &amp; photos present.</div>`
      : `<ul class="aud-list">${issues.map((i) =>
          `<li><span class="aud-tag">${escapeHtml(i.kind)}</span> ${escapeHtml(i.text)}</li>`).join("")}</ul>`;
  const w = document.createElement("div");
  w.className = "modal-scrim";
  w.innerHTML = `
    <div class="modal-box">
      <header class="modal-head">
        <div class="modal-title">🔎 Audit — ${escapeHtml(res.client || "")}</div>
        <div class="modal-sub">${clean ? "Clean" : issues.length + " issue(s)"}${res.aging ? " · aging " + res.aging + "d" : ""}</div>
      </header>
      <div class="modal-body">${body}</div>
      <footer class="modal-foot">
        <button class="btn" data-open-audit>Open in Audit ▸</button>
        <button class="btn btn-primary" data-close>Close</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("[data-close]").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  w.querySelector("[data-open-audit]").addEventListener("click", () => {
    if (window.emsNavigateTo) window.emsNavigateTo("audit", res.client || "");
    close();
  });
}

function fmtDue(iso) {
  const m = String(iso).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  return m ? `${+m[2]}/${+m[3]}` : iso;
}

// ════════════════════════════════════════════════════════════════
//  STAGES TABLE VIEW  (lifecycle — read-only from ems_db)
// ════════════════════════════════════════════════════════════════
async function loadStages() {
  setStatus("Loading lifecycle…");
  try {
    state.stages = await pywebview.api.stages();
    await refreshRows();
  } catch (ex) {
    setStatus(`Failed to load: ${ex}`, "error");
  }
}

async function refreshRows() {
  state.rows = await pywebview.api.lifecycle_rows();
  state.stage_counts = await pywebview.api.stage_counts();
  renderChips();
  renderTable();
  $("#loading-state")?.classList.add("hidden");
  setStatus("");
}

function renderChips() {
  const nav = $("#filter-chips");
  const total = state.rows.length;
  const chips = [
    { key: "all", label: "All", count: total },
    ...state.stages.map((s) => ({
      key: s.key, label: s.label, count: state.stage_counts[s.key] || 0,
    })),
  ];
  nav.innerHTML = chips.map((c) => `
    <button class="chip ${c.key === state.active_stage ? "active" : ""}" data-stage="${c.key}">
      ${escapeHtml(c.label)}<span class="count">${c.count}</span>
    </button>`).join("");
  nav.querySelectorAll(".chip").forEach((b) =>
    b.addEventListener("click", () => {
      state.active_stage = b.dataset.stage; renderChips(); renderTable();
    }));
}

function filteredAndSortedRows() {
  const q = state.search.trim().toLowerCase();
  let rows = state.rows.filter((r) => {
    if (state.active_stage !== "all" && r.stage !== state.active_stage) return false;
    if (!q) return true;
    return `${r.client} ${r.lane} ${r.board} ${r.owner}`.toLowerCase().includes(q);
  });
  const k = state.sort_key;
  const dir = state.sort_dir === "asc" ? 1 : -1;
  rows.sort((a, b) => {
    const av = a[k] ?? "", bv = b[k] ?? "";
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
  return rows;
}

function renderTable() {
  if (state.view !== "stages") return;
  const rows = filteredAndSortedRows();
  const tbody = $("#pipeline-tbody");
  tbody.innerHTML = rows.map(renderRow).join("");
  $("#empty-state").classList.toggle("hidden", rows.length > 0);
  $$(".pipeline-table thead th").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === state.sort_key)
      th.classList.add(state.sort_dir === "asc" ? "sort-asc" : "sort-desc");
  });
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("dblclick", () => onRowOpen(tr.dataset.cardId));
    tr.addEventListener("contextmenu", (ev) => onRowContext(ev, tr.dataset.cardId));
  });
  $("#status-counts").textContent = `${rows.length} shown · ${state.rows.length} total`;
}

function renderRow(r) {
  const daysClass = r.stall === "bad" ? "days bad" : r.stall === "warn" ? "days warn" : "days";
  const anomalyBadge = r.is_anomaly
    ? `<span class="anomaly" title="Days-in-stage > 3× median for this stage">🚨</span>` : "";
  const boardLane = [r.board, r.lane].filter(Boolean).join(" · ");
  return `
    <tr data-card-id="${escapeAttr(r.card_id)}" data-card-url="${escapeAttr(r.card_url)}" data-client="${escapeAttr(r.client)}">
      <td class="client-cell">${escapeHtml(r.client)}${anomalyBadge}</td>
      <td><span class="stage-pill" data-stage="${escapeAttr(r.stage)}">${escapeHtml(r.stage_label)}</span></td>
      <td class="num ${daysClass}">${r.days_in_stage}d</td>
      <td class="num muted">${r.age}d</td>
      <td class="muted">${escapeHtml(r.last_activity || "")}</td>
      <td class="muted">${escapeHtml(r.owner || "")}</td>
      <td class="muted">${escapeHtml(boardLane)}</td>
    </tr>`;
}

// ── Search routes to the active view ─────────────────────────────
let searchTimer = null;
function onSearchInput(ev) {
  state.search = ev.target.value;
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (state.view === "board") renderBoard();
    else renderTable();
  }, 120);
}

function onSortClick(key) {
  if (state.sort_key === key) state.sort_dir = state.sort_dir === "asc" ? "desc" : "asc";
  else { state.sort_key = key; state.sort_dir = (key === "days_in_stage" || key === "age") ? "desc" : "asc"; }
  renderTable();
}

// ── Sync flow (Stages) ───────────────────────────────────────────
async function onSyncClick() {
  const btn = $("#sync-btn");
  btn.disabled = true; btn.textContent = "↻ Syncing…";
  setStatus("Starting sync…");
  try {
    const res = await pywebview.api.sync_from_trello();
    if (!res || !res.started) {
      setStatus(res?.reason || "Couldn't start sync", "warn");
      btn.disabled = false; btn.textContent = "↻ Sync";
    }
  } catch (ex) {
    setStatus(`Sync error: ${ex}`, "error");
    btn.disabled = false; btn.textContent = "↻ Sync";
  }
}

function onSyncProgress(ev) {
  const { i, n, board } = ev.detail;
  setStatus(`Syncing ${i}/${n} · ${board}`);
}

async function onSyncDone(ev) {
  const { ok, cards, boards, error } = ev.detail;
  const btn = $("#sync-btn");
  btn.disabled = false; btn.textContent = "↻ Sync";
  if (ok) {
    setStatus(`✓ Synced ${cards} cards across ${boards} boards`, "ok");
    if (state.view === "stages") await refreshRows();
  } else {
    setStatus(`Sync failed: ${error}`, "error");
  }
}

// ── Stages row actions + ctx menu ────────────────────────────────
async function onRowOpen(cardId) {
  const row = state.rows.find((r) => r.card_id === cardId);
  if (!row || !row.card_url) return;
  await pywebview.api.open_url(row.card_url);
}

function onRowContext(ev, cardId) {
  ev.preventDefault();
  state.selected_card_id = cardId;
  const menu = $("#ctx-menu");
  menu.style.left = `${ev.clientX}px`;
  menu.style.top = `${ev.clientY}px`;
  menu.classList.remove("hidden");
}

function hideCtxMenu() { $("#ctx-menu").classList.add("hidden"); }

async function onCtxAction(action) {
  hideCtxMenu();
  const row = state.rows.find((r) => r.card_id === state.selected_card_id);
  if (!row) return;
  if (action === "open-trello") await pywebview.api.open_url(row.card_url);
  else if (action === "timeline") openTimelineModal(row);
  else if (action === "copy-client") { await pywebview.api.copy_to_clipboard(row.client); setStatus(`Copied: ${row.client}`, "ok"); }
  else if (action === "copy-id") { await pywebview.api.copy_to_clipboard(row.card_id); setStatus(`Copied card ID`, "ok"); }
}

async function openTimelineModal(row) {
  const res = await pywebview.api.card_timeline(row.card_id);
  const transitions = res?.transitions || [];
  const w = document.createElement("div");
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  const fmtDate = (s) => {
    if (!s) return "—";
    const m = String(s).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    return m ? `${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}-${m[1]}` : s;
  };
  const body = transitions.length
    ? `<ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;">
        ${transitions.map((t) => `
          <li style="display:grid;grid-template-columns:90px 1fr auto;gap:10px;align-items:center;padding:8px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
            <span style="font-family:monospace;font-size:11px;color:var(--text-muted);">${esc(fmtDate(t.when))}</span>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
              <span style="padding:2px 8px;border-radius:3px;background:var(--surface-2);font-size:11px;font-weight:600;">${esc(t.from_stage || "—")}</span>
              <span style="color:var(--text-muted);">→</span>
              <span style="padding:2px 8px;border-radius:3px;background:var(--chip-active);color:#FFF;font-size:11px;font-weight:600;">${esc(t.to_stage || "")}</span>
            </div>
            <span style="font-size:11px;color:var(--text-muted);">${t.days_in_from || 0}d in prev</span>
          </li>`).join("")}
       </ul>`
    : `<div style="padding:30px 14px;text-align:center;color:var(--text-muted);font-style:italic;">
        No stage transitions logged for this card yet.</div>`;
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(620px,92vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">🕒 Stage timeline</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${esc(row.client || "(no client)")}</div>
      </header>
      <div style="padding:18px 20px;overflow-y:auto;">${body}</div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:flex-end;">
        <button class="btn" id="tl-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  w.querySelector("#tl-close").addEventListener("click", () => w.remove());
  w.addEventListener("click", (e) => { if (e.target === w) w.remove(); });
}

async function openThresholdsModal() {
  const data = await pywebview.api.get_thresholds();
  const stages = data.stages || [];
  const w = document.createElement("div");
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">⏱ Stage thresholds</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Days in stage before a job is flagged Stalled. Blank = default.</div>
      </header>
      <div style="padding:14px 20px;overflow-y:auto;display:grid;grid-template-columns:1fr 90px 60px;gap:8px;align-items:center;">
        <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Stage</div>
        <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Days</div>
        <div></div>
        ${stages.map((s) => `
          <div style="font-size:13px;">${escapeHtml(s.label)}</div>
          <input type="number" min="0" data-stage="${escapeAttr(s.key)}" value="${s.days}"
                 style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:5px 8px;width:80px;font:inherit;" />
          <button class="btn" data-reset="${escapeAttr(s.key)}" style="font-size:10px;padding:3px 6px;" title="Reset to default (${s.default})">↻</button>
        `).join("")}
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="th-reset-all">↻ Reset all</button>
        <button class="btn" id="th-cancel">Cancel</button>
        <button class="btn btn-primary" id="th-save">💾 Save</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#th-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  w.querySelectorAll("[data-reset]").forEach((b) =>
    b.addEventListener("click", () => {
      const input = w.querySelector(`input[data-stage="${b.dataset.reset}"]`);
      const def = stages.find((s) => s.key === b.dataset.reset)?.default;
      if (input && def !== undefined) input.value = def;
    }));
  w.querySelector("#th-reset-all").addEventListener("click", async () => {
    await pywebview.api.reset_thresholds(); close(); setTimeout(openThresholdsModal, 100);
  });
  w.querySelector("#th-save").addEventListener("click", async () => {
    for (const inp of w.querySelectorAll("input[data-stage]")) {
      const days = inp.value === "" ? null : parseInt(inp.value, 10);
      await pywebview.api.set_threshold(inp.dataset.stage, days);
    }
    close();
    if (state.view === "stages") await refreshRows();
  });
}

// ── Status + escaping helpers ────────────────────────────────────
let statusTimer = null;
function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
  if (statusTimer) clearTimeout(statusTimer);
  if (msg && kind === "ok") {
    statusTimer = setTimeout(() => { el.textContent = ""; el.className = "status-msg"; }, 3500);
  }
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
function escapeHtml(s) { return esc(s); }
function escapeAttr(s) { return esc(s); }
function cssEsc(s) { return String(s ?? "").replace(/["\\\]]/g, "\\$&"); }
