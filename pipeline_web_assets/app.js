/* Linguar Hub Pipeline — Pywebview frontend.
 *
 * Two views, one panel:
 *   🗂 Board  — a live Trello-style kanban of WORK IN PROGRESS,
 *               ESTIMATING, and CONTENTS. Real lanes as columns, cards pulled
 *               from Linguar Hub's shared Pipeline, with Trello mirrored
 *               during the transition, plus per-card audit buttons.
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
  boardFilter: "all",       // all | attention | due | sync
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
let workspaceRequestId = 0;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  // Restore the view you left — board vs stages, which board tab, the
  // stage chip and the search box. The panel is destroyed on navigate,
  // so all four reset on every visit before this.
  await PanelState.init("pipeline");
  let preferences = {};
  try { preferences = await pywebview.api.personal_preferences() || {}; } catch (_) {}
  document.documentElement.classList.toggle("density-compact", preferences.density === "compact");
  document.documentElement.classList.toggle("reduce-motion", !!preferences.reduce_motion);
  state.view           = PanelState.get("view", preferences.default_view || state.view);
  state.activeBoardKey = PanelState.get("activeBoardKey", null);
  state.boardFilter    = PanelState.get("boardFilter", "all");
  state.active_stage   = PanelState.get("active_stage", state.active_stage);
  state.search         = PanelState.get("search", "");

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
  // The bar rides the same stream as the status text: the text says
  // what the workspace sync is on, the bar says how much is left.
  if (window.Progress) window.Progress.bind("pipeline:sync-progress", "pipeline:sync-done");

  window.addEventListener("pipeline:sync-progress", onSyncProgress);
  window.addEventListener("pipeline:sync-done", onSyncDone);

  const initialView = state.view;
  state.view = "";
  setView(initialView);
  await loadBoard();
  if (state.view === "stages" && !state.stages.length) await loadStages();
});

// ── View switching ───────────────────────────────────────────────
function setView(v) {
  if (state.view === v) return;
  state.view = v;
  PanelState.set({ view: v });
  $("#view-board-btn").classList.toggle("active", v === "board");
  $("#view-stages-btn").classList.toggle("active", v === "stages");
  $("#view-board-btn").setAttribute("aria-selected", String(v === "board"));
  $("#view-stages-btn").setAttribute("aria-selected", String(v === "stages"));
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
  if (isRefresh) { btn.disabled = true; btn.textContent = "↻ Syncing…"; }
  if (!isRefresh) $("#board-loading")?.classList.remove("hidden");
  setStatus(isRefresh ? "Refreshing from Trello…" : "Loading shared Pipeline…");
  try {
    const res = await pywebview.api.board_view(Boolean(isRefresh));
    if (!res?.ok) { setStatus(`Board load failed: ${res?.error || "?"}`, "error"); return; }
    state.board = res;
    renderBoard();
    const total = boardCardTotal();
    const source = res.source === "shared" ? "shared Pipeline" :
      (res.mirrored ? "Trello · saved to Pipeline" : "Trello");
    setStatus(`✓ ${total} cards across ${res.boards.length} boards · ${source}`, "ok");
    if (res.stale_cache && !isRefresh) refreshSavedBoardInBackground();
  } catch (ex) {
    setStatus(`Board error: ${ex}`, "error");
  } finally {
    if (isRefresh) { btn.disabled = false; btn.textContent = "↻ Sync Jobs"; }
  }
}

async function refreshSavedBoardInBackground() {
  try {
    const fresh = await pywebview.api.board_view_shared_refresh();
    if (!fresh?.ok || !(fresh.boards || []).length) return;
    state.board = fresh;
    renderBoard();
    setStatus(`✓ ${boardCardTotal()} jobs · shared Pipeline is current`, "ok");
  } catch (_) {
    // The saved board remains fully usable. Explicit Sync Jobs surfaces
    // network errors when the user wants to troubleshoot them.
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

function boardSummary(boards) {
  const cards = [];
  for (const board of boards || [])
    for (const lane of board.lanes || []) cards.push(...(lane.cards || []));
  return {
    total: cards.length,
    attention: cards.filter((c) => c.stall === "bad" || c.overdue || c.sync_status === "conflict").length,
    due: cards.filter((c) => c.due && !c.overdue).length,
    waiting: cards.filter((c) => c.sync_status === "pending").length,
  };
}

function cardMatchesBoardFilter(card) {
  if (state.boardFilter === "attention")
    return card.stall === "bad" || card.overdue || card.sync_status === "conflict";
  if (state.boardFilter === "due") return Boolean(card.due && !card.overdue);
  if (state.boardFilter === "sync") return card.sync_status === "pending";
  return true;
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
  const summary = boardSummary(boards);

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
    <section class="pipeline-summary" aria-label="Filter jobs by status">
      <button class="summary-primary ${state.boardFilter === "all" ? "active" : ""}" data-board-filter="all"><strong>${summary.total}</strong><span>Active jobs</span></button>
      <button class="summary-item ${summary.attention ? "needs-attention" : ""} ${state.boardFilter === "attention" ? "active" : ""}" data-board-filter="attention"><strong>${summary.attention}</strong><span>Need attention</span></button>
      <button class="summary-item ${state.boardFilter === "due" ? "active" : ""}" data-board-filter="due"><strong>${summary.due}</strong><span>Due soon</span></button>
      ${summary.waiting ? `<button class="summary-item ${state.boardFilter === "sync" ? "active" : ""}" data-board-filter="sync"><strong>${summary.waiting}</strong><span>Waiting to sync</span></button>` : ""}
      <div class="summary-help">Click to open · hold to move</div>
    </section>
    <div class="board-tabs">
      ${tabs}
      <span class="board-tabs-spacer"></span>
    </div>
    ${lanesHtml}`;

  // Board tabs.
  root.querySelectorAll("[data-board-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      state.activeBoardKey = b.dataset.boardTab;
      PanelState.set({ activeBoardKey: state.activeBoardKey });
      renderBoard();
    }));
  root.querySelectorAll("[data-board-filter]").forEach((button) =>
    button.addEventListener("click", () => {
      state.boardFilter = button.dataset.boardFilter || "all";
      PanelState.set({ boardFilter: state.boardFilter });
      renderBoard();
    }));
  // Wire drag + drop + per-card actions.
  root.querySelectorAll(".lane").forEach((laneEl) => {
    laneEl.addEventListener("dragover", onLaneDragOver);
    laneEl.addEventListener("dragleave", onLaneDragLeave);
    laneEl.addEventListener("drop", onLaneDrop);
  });
  root.querySelectorAll(".kcard").forEach((cardEl) => {
    wireCardClickAndHold(cardEl);
    cardEl.addEventListener("dragstart", onCardDragStart);
    cardEl.addEventListener("dragend", onCardDragEnd);
    cardEl.addEventListener("contextmenu", onCardContext);
    cardEl.querySelector('[data-act="more"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); openCardMenu(e, cardEl);
    });
  });
}

function laneMatches(lane, q) {
  return (lane.cards || []).filter((c) => {
    if (!cardMatchesBoardFilter(c)) return false;
    return !q || `${c.client} ${lane.name}`.toLowerCase().includes(q);
  });
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
  const syncChip = c.sync_status === "conflict"
    ? `<span class="chip-mini sync-conflict" title="Trello and Linguar Hub need review">⚠ Sync</span>`
    : c.sync_status === "pending"
      ? `<span class="chip-mini sync-pending" title="Saved in Linguar Hub; waiting for Trello">↻ Sync</span>` : "";
  const chips = [loss, ckChip, dueChip, stallChip, syncChip].filter(Boolean).join("");
  return `<div class="kcard stall-border-${escapeAttr(c.stall)}" draggable="false"
               role="button" tabindex="0" aria-label="Open ${escapeAttr(c.client || "job")}"
               data-card-id="${escapeAttr(c.card_id)}"
               data-list-id="${escapeAttr(c.list_id)}"
               data-url="${escapeAttr(c.url)}"
               data-client="${escapeAttr(c.client)}"
               data-card-summary="${escapeAttr(JSON.stringify({
                 due: c.due || "", overdue: Boolean(c.overdue),
                 days_in_lane: Number(c.days_in_lane || 0),
                 loss_types: c.loss_types || [], checklist: ck,
                 sync_status: c.sync_status || "",
               }))}">
    <div class="kcard-title">${escapeHtml(c.client || "(no name)")}</div>
    ${chips ? `<div class="kcard-chips">${chips}</div>` : ""}
    <div class="kcard-actions">
      <button class="kbtn" data-act="more" aria-label="More actions for ${escapeAttr(c.client || "job")}" title="More job actions">⋯</button>
    </div>
  </div>`;
}

// ── Drag to move (write-back with confirm) ───────────────────────
function wireCardClickAndHold(cardEl) {
  let holdTimer = null;
  let startX = 0;
  let startY = 0;
  let dragArmed = false;
  let suppressClick = false;
  const interactive = (target) => Boolean(target.closest("button, a, input, textarea, select, [role='button']"));
  const clearHold = () => {
    if (holdTimer) window.clearTimeout(holdTimer);
    holdTimer = null;
  };
  cardEl.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || interactive(event.target)) return;
    startX = event.clientX;
    startY = event.clientY;
    dragArmed = false;
    suppressClick = false;
    clearHold();
    holdTimer = window.setTimeout(() => {
      dragArmed = true;
      suppressClick = true;
      cardEl.draggable = true;
      cardEl.classList.add("drag-ready");
    }, 180);
  });
  cardEl.addEventListener("pointermove", (event) => {
    if (dragArmed || !holdTimer) return;
    if (Math.hypot(event.clientX - startX, event.clientY - startY) > 5) {
      suppressClick = true;
      clearHold();
    }
  });
  const release = () => {
    clearHold();
    dragArmed = false;
    cardEl.classList.remove("drag-ready");
    window.setTimeout(() => { cardEl.draggable = false; }, 0);
  };
  cardEl.addEventListener("pointerup", release);
  cardEl.addEventListener("pointercancel", release);
  cardEl.addEventListener("click", (event) => {
    if (interactive(event.target)) return;
    if (suppressClick || cardEl.dataset.didDrag === "true") {
      suppressClick = false;
      cardEl.dataset.didDrag = "false";
      return;
    }
    onAuditCard(cardEl);
  });
  cardEl.addEventListener("keydown", (event) => {
    if (interactive(event.target) || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onAuditCard(cardEl);
  });
}

function onCardDragStart(ev) {
  const el = ev.currentTarget;
  el.dataset.didDrag = "true";
  state.drag = {
    cardId:   el.dataset.cardId,
    name:     el.dataset.client,
    fromListId: el.dataset.listId,
  };
  el.classList.add("dragging");
  try { ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", el.dataset.cardId); } catch (_) {}
}

function onCardDragEnd(ev) {
  ev.currentTarget.draggable = false;
  ev.currentTarget.classList.remove("dragging", "drag-ready");
  state.drag = null;
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
  setStatus(res.synced === false
    ? `✓ Moved in Linguar Hub · ${res.warning || "Trello needs review"}`
    : `✓ Moved "${drag.name}" → ${toLane}`, res.synced === false ? "warn" : "ok");
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
async function onAuditCard(cardOrClient, cardId = "", trelloUrl = "", division = "") {
  const isCard = cardOrClient && typeof cardOrClient === "object" && cardOrClient.dataset;
  const client = isCard ? cardOrClient.dataset.client : String(cardOrClient || "");
  const resolvedCardId = isCard ? (cardOrClient.dataset.cardId || "") : cardId;
  const resolvedUrl = isCard ? (cardOrClient.dataset.url || "") : trelloUrl;
  const requestId = ++workspaceRequestId;
  const instant = instantWorkspaceData(cardOrClient, client, resolvedCardId, division);
  let modal = openAuditModal(instant, resolvedUrl);
  setStatus(`Opened "${client}" · loading shared job details…`);
  try {
    // Start deep hydration immediately. It used to begin only after the fast
    // shared-data request completed, stacking two independent waits every
    // time a card opened.
    const fullPromise = pywebview.api.job_card_workspace(
      client, resolvedCardId, division);
    const fast = await pywebview.api.job_card_workspace_fast(client, resolvedCardId, division);
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (!fast?.ok) {
      modal.setDeferredError(fast?.error || "Shared job details unavailable");
      setStatus(`Basic card opened · shared details unavailable`, "warn");
      return;
    }
    if (!modal.hasUserInput()) {
      modal.close();
      modal = openAuditModal(fast, fast.selected_trello_url || resolvedUrl);
    }
    setStatus(`Job opened in ${fast.load_ms || 0} ms · loading audit, Trello, and documents…`);
    const full = await fullPromise;
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (!full?.ok) {
      modal.setDeferredError(full?.error || "Deep refresh unavailable");
      setStatus(`Job opened · some live details could not refresh`, "warn");
      return;
    }
    const replace = () => {
      if (!modal.element.isConnected) return;
      modal.close();
      openAuditModal(full, full.selected_trello_url || resolvedUrl);
      setStatus("");
    };
    if (modal.hasUserInput()) {
      modal.setDeferredReady(replace);
      setStatus("Live details are ready · finish editing or click Load live details", "ok");
    } else {
      replace();
    }
  } catch (error) {
    if (requestId !== workspaceRequestId) return;
    if (!modal.element.isConnected) return;
    modal.setDeferredError(error?.message || String(error));
    setStatus(`Basic card opened · live details failed`, "warn");
  }
}

function instantWorkspaceData(cardOrClient, client, cardId, division) {
  let summary = {};
  if (cardOrClient?.dataset?.cardSummary) {
    try { summary = JSON.parse(cardOrClient.dataset.cardSummary); } catch (_) {}
  }
  const lane = cardOrClient?.closest?.(".lane")?.dataset?.laneName || "Pipeline";
  const selected = division || "EMS";
  const chips = [
    ...(summary.loss_types || []),
    summary.due ? `${summary.overdue ? "Overdue" : "Due"} ${fmtDue(summary.due)}` : "",
    summary.days_in_lane ? `${summary.days_in_lane} days in lane` : "",
  ].filter(Boolean);
  return {
    ok: true, client, card_id: cardId, selected_division: selected,
    selected_trello_url: cardOrClient?.dataset?.url || "",
    deferred_loading: true, load_ms: 0,
    audit: {ok: true, client, found: true, form_issues: [], photo_issues: [],
      requirements: [], activity: chips, path: "", aging: summary.days_in_lane || 0},
    crm: {ok: true, lifecycle_stage: lane.toLowerCase().replaceAll(" ", "_"),
      job_log: [], progress: {items: [], percent_complete: 0}, work_environments: []},
    info_sections: [{name: "Pipeline", fields: [
      {id: "pipeline_lane", label: "Current lane", value: lane},
      ...(summary.loss_types?.length ? [{id: "loss_type", label: "Loss type", value: summary.loss_types.join(", ")}] : []),
      ...(summary.due ? [{id: "due", label: "Due", value: fmtDue(summary.due)}] : []),
    ]}],
    division_trello_cards: [{division: selected, card_id: cardId,
      url: cardOrClient?.dataset?.url || "", pinned: Boolean(cardId)}],
    division_card_reconciliation: {ok: true, divisions: []},
    checklists: [], comments: [], attachments: [], members: [],
    documents: {provider: "DocuSign", request: {}, files: [], connected: false},
  };
}

function openAuditLoadingModal(client) {
  const w = document.createElement("div");
  w.className = "modal-scrim audit-overlay";
  w.innerHTML = `
    <div class="modal-box audit-card audit-loading-card" role="dialog" aria-modal="true" aria-busy="true" aria-label="Loading job workspace">
      <header class="modal-head">
        <div class="audit-head-copy"><div class="modal-title">${escapeHtml(client || "Job workspace")}</div>
        <div class="modal-sub" data-loading-label>Loading job workspace…</div></div>
        <button class="audit-close" data-close aria-label="Close job workspace">×</button>
      </header>
      <div class="modal-body audit-loading-body" data-loading-body>
        <div class="job-card-loading-grid" aria-hidden="true">
          <div class="job-card-loading-main">
            <div class="job-card-skeleton skeleton-tall"></div>
            <div class="job-card-skeleton skeleton-medium"></div>
            <div class="job-card-skeleton skeleton-tall"></div>
          </div>
          <div class="job-card-skeleton skeleton-side"></div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(w);
  const keyClose = (event) => { if (event.key === "Escape") close(); };
  const close = () => {
    document.removeEventListener("keydown", keyClose);
    w.remove();
  };
  w.querySelector("[data-close]").addEventListener("click", close);
  w.addEventListener("click", (event) => { if (event.target === w) close(); });
  document.addEventListener("keydown", keyClose);
  return {
    element: w,
    close,
    showError(message) {
      w.querySelector(".audit-loading-card")?.setAttribute("aria-busy", "false");
      const label = w.querySelector("[data-loading-label]");
      if (label) label.textContent = "Could not load this job";
      const body = w.querySelector("[data-loading-body]");
      if (body) body.innerHTML = `<div class="job-card-load-error"><strong>Job workspace unavailable</strong><p>${escapeHtml(message)}</p><button class="btn" data-error-close>Close</button></div>`;
      body?.querySelector("[data-error-close]")?.addEventListener("click", close);
    },
  };
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
function openAuditModal(data, trelloUrl = "") {
  const res = data.audit || {};
  const crm = data.crm || {};
  const issues = [];
  (res.form_issues || []).forEach((f) => issues.push({ kind: "Form", text: f }));
  (res.photo_issues || []).forEach((p) => issues.push({ kind: "Photos", text: p }));
  (res.requirements || []).forEach((r) => issues.push({ kind: "Photos", text: r }));
  const clean = res.found && !issues.length;
  const missing = data.deferred_loading
    ? `<div class="aud-loading-inline">Checking job folders and current requirements…</div>`
    : !res.found
    ? `<div class="aud-bad">📁 No job folder found for this client.</div>`
    : clean
      ? `<div class="aud-ok">✓ All required forms &amp; photos present.</div>`
      : `<ul class="aud-list">${issues.map((i) =>
          `<li><span class="aud-tag">${escapeHtml(i.kind)}</span> ${escapeHtml(i.text)}</li>`).join("")}</ul>`;
  const facts = (data.info_sections || []).map((section) => `
    <section class="aud-section info-section"><h3>${escapeHtml(section.name)}</h3>
      <dl class="aud-facts">${(section.fields || []).map((f) =>
        `<div><dt>${escapeHtml(f.label)}</dt><dd>${escapeHtml(f.value)}</dd></div>`).join("")}</dl>
    </section>`).join("");
  const copyFacts = (data.info_sections || []).flatMap((section) => section.fields || []);
  const copyField = (id) => (copyFacts.find((field) => field.id === id) || {}).value || "";
  const copyValue = (...needles) => (copyFacts.find((field) => needles.some((needle) =>
    String(field.label || "").toLowerCase().includes(needle))) || {}).value || "";
  const copyOptions = [
    ["Customer name", copyField("customer_name") || copyValue("customer name", "insured name") || data.client || res.client || ""],
    ["Customer phone", copyField("phone")],
    ["Customer email", copyField("email")],
    ["Loss address", copyField("address")],
    ["Claim number", copyField("claim_number")],
    ["Job folder path", res.path || ""],
    ["Trello link", trelloUrl],
  ].filter((item) => item[1]);
  const visibleCopyOptions = copyOptions.filter(([label]) => label !== "Trello link");
  const activity = (res.activity || []).length
    ? `<div class="aud-chips">${res.activity.map((a) => `<span>${escapeHtml(a)}</span>`).join("")}</div>`
    : `<div class="aud-empty">No activity recorded for this run.</div>`;
  const misplaced = [...(res.misplaced_forms || []), ...(res.misplaced_photos || [])];
  const misplacedHtml = misplaced.length
    ? `<ul class="aud-list">${misplaced.map((item) => `<li><span class="aud-tag aud-warn">Moved</span> ${escapeHtml(item.label || item)}${item.where ? ` <small>${escapeHtml(item.where)}</small>` : ""}</li>`).join("")}</ul>`
    : "";
  const progress = crm.progress || {};
  const requirementRows = (items) => items.map((item) => `
    <div class="requirement-row req-${escapeAttr(item.status || "required_now")}">
      <span class="requirement-mark">${item.status === "completed" ? "✓" : item.status === "overdue" ? "!" : "○"}</span>
      <span class="requirement-copy"><strong>${escapeHtml(item.label || "")}</strong>
      <small>${escapeHtml(item.introduced_stage_label || "")} · ${escapeHtml(item.owner || "")}${item.evidence ? " · " + escapeHtml(item.evidence) : ""}</small></span>
    </div>`).join("");
  const requirementGroups = {overdue: [], required_now: [], completed: []};
  (progress.items || []).forEach((item) =>
    (requirementGroups[item.status] || requirementGroups.required_now).push(item));
  const required = (progress.items || []).length ? `
    ${requirementGroups.overdue.length ? `<div class="requirement-group overdue"><h4>Overdue from earlier stages</h4>${requirementRows(requirementGroups.overdue)}</div>` : ""}
    <div class="requirement-group"><h4>Required at ${escapeHtml(progress.stage_label || "this stage")}</h4>${requirementRows(requirementGroups.required_now) || `<div class="aud-empty">Nothing new is required at this stage.</div>`}</div>
    <details class="requirement-history"><summary>Completed &amp; previous requirements <span>${requirementGroups.completed.length}</span></summary>${requirementRows(requirementGroups.completed) || `<div class="aud-empty">No verified requirements yet.</div>`}</details>`
    : `<div class="aud-empty">No stage requirements are active yet.</div>`;
  const workTypeState = Object.fromEntries((crm.work_environments || []).map((env) =>
    [String(env.work_environment || "").toLowerCase(), env]));
  const divisionCards = Object.fromEntries((data.division_trello_cards || []).map((card) =>
    [String(card.division || "").toLowerCase(), card]));
  const workTypeStages = [
    ["not_applicable", "Not part of this job"], ["planned", "Planned"],
    ["scheduled", "Scheduled"], ["active", "Active"], ["waiting", "Waiting"],
    ["ready_for_billing", "Ready for billing"], ["closeout", "Closeout"], ["closed", "Complete"],
  ];
  const pinnedDivisionCards = (data.division_trello_cards || []).filter((card) => card.pinned);
  const selectedDivision = data.selected_division || "EMS";
  const divisionDataTabs = pinnedDivisionCards.length > 1 ? `<div class="division-data-tabs" role="tablist" aria-label="Trello card data">
    ${pinnedDivisionCards.map((card) => `<button type="button" role="tab" data-division-data="${escapeAttr(card.division)}" aria-selected="${card.division === selectedDivision ? "true" : "false"}" class="${card.division === selectedDivision ? "active" : ""}">${card.division === "EMS" ? "💧 EMS" : card.division === "CONTENTS" ? "▣ Contents" : "🔨 Recon"}</button>`).join("")}
  </div>` : "";
  const workTypes = [["EMS", "💧", "Mitigation"], ["Contents", "▣", "Contents"], ["Recon", "🔨", "Reconstruction"]]
    .map(([name, icon, label]) => {
      const env = workTypeState[name.toLowerCase()] || {};
      const trello = divisionCards[name.toLowerCase()] || {};
      const stage = env.stage || "not_applicable";
      return `<div class="work-type work-type-${name.toLowerCase()} ${stage !== "not_applicable" ? "has-stage" : ""}" data-work-type-card="${name}">
        <div class="work-type-head"><span aria-hidden="true">${icon}</span><div><strong>${label}</strong><small>${name}</small></div></div>
        <select data-work-env="${name}" aria-label="${label} status">${workTypeStages.map(([value, text]) => `<option value="${value}" ${value === stage ? "selected" : ""}>${text}</option>`).join("")}</select>
        <input data-work-env-owner="${name}" value="${escapeAttr(env.owner || "")}" placeholder="Owner or crew" aria-label="${label} owner or crew">
        <div class="division-trello ${trello.pinned ? "is-pinned" : ""}">
          <span>${trello.pinned ? "📌 Trello card pinned" : "○ No Trello card"}</span>
          <div>${trello.pinned ? `<button class="text-btn" data-division-trello-open="${name}">Open</button>` : ""}
          ${data.card_id && data.card_id !== trello.card_id ? `<button class="text-btn" data-division-trello-use="${name}">Use open card</button>` : ""}
          <button class="text-btn" data-division-trello-pin="${name}">${trello.pinned ? "Change" : "Pin"}</button>
          ${trello.pinned ? `<button class="text-btn danger" data-division-trello-remove="${name}">Remove</button>` : ""}</div>
        </div>
      </div>`;
    }).join("");
  const checklistGroups = (data.checklists || []).map((list) => `
    <div class="trello-checklist"><h4>${escapeHtml(list.name || "Checklist")}</h4>
      ${(list.items || []).map((item) => `<label class="check-row ${item.complete ? "checked" : ""}">
        <input type="checkbox" data-check-item="${escapeAttr(item.id)}" ${item.complete ? "checked" : ""}/>
        <span>${escapeHtml(item.name || "")}</span></label>`).join("") || `<div class="aud-empty">No items</div>`}
    </div>`).join("") || `<div class="aud-empty">No checklist has been added to this job.</div>`;
  const logs = (crm.job_log || []).slice().reverse().slice(0, 40).map((entry) => `
    <article class="job-log-row" data-job-log-id="${escapeAttr(entry.entry_id || "")}">
      <time>${escapeHtml(entry.work_date || "")}</time><div class="job-log-copy">
      <div><strong>${escapeHtml(entry.work_type || "Job update")}</strong><span>${escapeHtml((entry.status || "").replaceAll("_", " "))}</span></div>
      ${entry.technicians ? `<small>Crew: ${escapeHtml(entry.technicians)}</small>` : ""}
      ${entry.note ? `<p>${escapeHtml(entry.note)}</p>` : ""}
      ${entry.equipment ? `<small>Equipment / readings: ${escapeHtml(entry.equipment)}</small>` : ""}</div>
      <div class="job-log-actions"><button class="text-btn" data-history-job-log="${escapeAttr(entry.entry_id || "")}">History</button><button class="text-btn" data-edit-job-log="${escapeAttr(entry.entry_id || "")}">Edit</button>
      <button class="text-btn danger" data-delete-job-log="${escapeAttr(entry.entry_id || "")}">Delete</button></div></article>`).join("") || `<div class="aud-empty">No Job Log updates yet.</div>`;
  const docs = data.documents || {};
  const dsRequest = docs.request || {};
  const documentRows = data.deferred_loading
    ? `<div class="aud-loading-inline">Reading document index…</div>`
    : (docs.files || []).map((file) => `<button class="signature-file" data-document-path="${escapeAttr(file.path || "")}">
    <span class="signature-file-mark">${file.signed ? "✓" : "□"}</span><span><strong>${escapeHtml(file.name || "Document")}</strong>
    <small>${file.signed ? "Signed/final paperwork" : "Job document"}${file.modified_at ? " · " + escapeHtml(formatCommentDate(file.modified_at)) : ""}</small></span></button>`).join("") || `<div class="aud-empty">No PDFs or Word documents found in this job’s DOCS folders.</div>`;
  const signatureState = dsRequest.state === "pending_signature" ? "Signature pending"
    : dsRequest.state === "pending_email" ? "Needs customer email"
    : (docs.files || []).some((file) => file.signed) ? "Signed file received" : "Not sent";
  const attachments = (data.attachments || []).map((a) =>
    `<button class="attachment-row" data-attachment-url="${escapeAttr(a.url || "")}">📎 ${escapeHtml(a.name || "Attachment")}</button>`).join("") || `<div class="aud-empty">No attachments.</div>`;
  const comments = (data.comments || []).map(renderJobComment).join("") || `<div class="aud-empty activity-empty">No comments yet. Start the job conversation below.</div>`;
  const divisionConflicts = (data.division_card_reconciliation?.divisions || [])
    .filter((item) => item.state === "conflict");
  const divisionConflictBanner = divisionConflicts.length ? `<div class="division-conflict-banner" role="alert">
    <strong>⚠ Review Trello card links</strong>
    <span>${divisionConflicts.map((item) => escapeHtml(item.division)).join(", ")} ${divisionConflicts.length === 1 ? "has" : "have"} more than one possible card or a saved card that no longer matches. Choose the correct card before posting updates.</span>
  </div>` : "";
  const body = `<div class="job-card-layout">
    <div class="job-card-main">
      ${divisionConflictBanner}
      <section class="aud-section audit-summary"><h3>Current audit</h3>${missing}${misplacedHtml}</section>
      <section class="aud-section progress-section"><div class="section-title-row"><h3>Job requirements</h3>
        <span class="progress-label">${progress.percent_complete || 0}% complete</span></div>
        <div class="requirement-progress"><i style="width:${Math.max(0, Math.min(100, progress.percent_complete || 0))}%"></i></div>${required}</section>
      <section class="aud-section"><div class="section-title-row"><div><h3>Work on this job</h3><small>Choose every division involved; each one tracks its own status</small></div></div><div class="work-types">${workTypes}</div></section>
      <section class="aud-section"><div class="section-title-row"><div><h3>Checklists</h3><small>${escapeHtml(selectedDivision)} card · stored in Linguar Hub · Trello sync is temporary</small></div>${divisionDataTabs}</div>${checklistGroups}</section>
      ${facts || `<section class="aud-section"><h3>Job information</h3><div class="aud-empty">No saved job information yet.</div></section>`}
      <section class="aud-section signatures-section"><div class="section-title-row"><div><h3>Documents &amp; signatures</h3><small>DocuSign sends · job folder keeps the completed files</small></div><span class="signature-state state-${escapeAttr((dsRequest.state || "not_sent").replaceAll("_", "-"))}">${escapeHtml(signatureState)}</span></div>
        <div class="signature-flow"><span class="${dsRequest.requested ? "done" : "active"}">1 Prepare</span><i></i><span class="${dsRequest.requested ? "active" : ""}">2 Send</span><i></i><span class="${(docs.files || []).some((file) => file.signed) ? "done" : ""}">3 Signed copy</span></div>
        ${dsRequest.email ? `<div class="signature-recipient">Sent to <strong>${escapeHtml(dsRequest.email)}</strong> · ${Number(dsRequest.days_pending || 0)} day(s) pending</div>` : ""}
        ${!docs.connected ? `<div class="signature-connection"><span><strong>Direct DocuSign connection is next</strong><small>For now, open DocuSign and mark the request sent after the envelope is actually sent.</small></span></div>` : ""}
        <div class="signature-actions"><button class="btn btn-primary" data-open-docusign>Open DocuSign ↗</button><button class="btn" data-mark-docusign-sent ${dsRequest.state ? "disabled" : ""}>Mark envelope sent</button><button class="btn" data-open-docs-folder ${res.path ? "" : "disabled"}>Open job folder</button></div>
        <div class="signature-files">${documentRows}</div></section>
      <section class="aud-section job-log-section"><div class="section-title-row"><div><h3>Job Log</h3><small>Structured updates used to build the Snapshot</small></div>
        <div class="section-actions">${data.card_id ? `<button class="btn compact" data-import-job-log>Refresh from ${escapeHtml(selectedDivision)} Trello</button>` : ""}<button class="btn btn-primary compact" data-add-job-log>+ Add update</button></div></div>
        <div class="job-log-editor" data-job-log-editor hidden></div><div data-job-log-list>${logs}</div></section>
      <details class="aud-section compact-section"><summary>Run activity <span>${(res.activity || []).length}</span></summary>${activity}</details>
      <details class="aud-section compact-section"><summary>Other attachments <span>${(data.attachments || []).length}</span></summary>${attachments}</details>
    </div>
    <aside class="job-card-activity"><div class="activity-head"><div><h3>Comments and activity</h3><small>${escapeHtml(selectedDivision)} Trello card</small></div>
      <span>${(data.comments || []).length}</span></div>
      <div class="comment-stream" data-comment-stream>${comments}</div>
      <div class="comment-compose"><textarea data-comment-input rows="3" placeholder="Write an update for this job…"></textarea>
        <div><span data-comment-state></span><button class="btn btn-primary" data-post-comment>Add comment</button></div></div>
    </aside></div>`;
  const w = document.createElement("div");
  w.className = "modal-scrim audit-overlay";
  w.innerHTML = `
    <div class="modal-box audit-card" role="dialog" aria-modal="true" aria-label="Job audit" tabindex="-1">
      <header class="modal-head">
        <div class="audit-head-copy"><div class="modal-title">${escapeHtml(data.client || res.client || "")}</div>
        <div class="modal-sub">${escapeHtml(crm.lifecycle_stage ? crm.lifecycle_stage.replaceAll("_", " ") : "Job audit")} · ${clean ? "ready" : issues.length + " item(s) need attention"}${res.aging ? " · " + res.aging + " days" : ""}${(data.members || []).length ? " · " + escapeHtml(data.members.join(", ")) : ""}</div></div>
        <div class="workspace-load-state" data-workspace-load-state>${data.deferred_loading ? "Loading live details…" : `<button class="btn compact" type="button" data-refresh-workspace>Refresh live</button>`}</div>
        <button class="audit-close" data-close aria-label="Close job audit">×</button>
      </header>
      <div class="modal-body">${body}</div>
      <footer class="modal-foot">
        <div class="visible-job-actions">
          ${visibleCopyOptions.map(([label, value]) => `<button class="btn compact" data-copy-value="${escapeAttr(value)}">📋 ${escapeHtml(label.replace("Customer ", ""))}</button>`).join("")}
          <button class="btn compact" data-copy-summary>📋 Job summary</button>
          <button class="btn btn-primary compact" data-stage-xa ${res.path ? "" : "disabled"}>📂 Stage for XA</button>
        </div>
        <details class="modal-more-menu"><summary class="btn">More ▾</summary><div>
          <button data-flag-job>🚩 Flag missing item</button>
          <button data-open-trello>Open in Trello ↗</button>
          <button data-open-audit>Open full Audit ▸</button>
        </div></details>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const previousFocus = document.activeElement;
  let userDirty = false;
  w.addEventListener("input", () => { userDirty = true; });
  w.addEventListener("change", () => { userDirty = true; });
  const close = (force = false) => {
    if (!force && userDirty && !window.confirm("Discard unsaved changes to this job?")) return false;
    document.removeEventListener("keydown", keyClose);
    w.remove();
    previousFocus?.focus?.();
    return true;
  };
  w.querySelector("[data-close]").addEventListener("click", () => close());
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  const keyClose = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", keyClose);
  w.querySelector(".audit-card")?.focus();
  w.querySelectorAll("[data-division-data]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.divisionData === selectedDivision) return;
    if (!close()) return;
    await onAuditCard(data.client || res.client || "", "", "", button.dataset.divisionData || "EMS");
  }));
  w.querySelector("[data-open-trello]").addEventListener("click", () => {
    if (trelloUrl) pywebview.api.open_url(trelloUrl);
  });
  w.querySelector("[data-refresh-workspace]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Refreshing…";
    const refreshed = await pywebview.api.refresh_job_card_workspace(
      data.client || res.client || "", data.card_id || "", data.selected_division || "EMS");
    if (!refreshed?.ok) {
      button.disabled = false;
      button.textContent = "Refresh live";
      setStatus(refreshed?.error || "Live refresh failed", "error");
      return;
    }
    close();
    openAuditModal(refreshed, refreshed.selected_trello_url || trelloUrl);
    setStatus(`Live details refreshed in ${refreshed.load_ms || 0} ms`, "ok");
  });
  w.querySelector("[data-flag-job]")?.addEventListener("click", () => {
    onFlagCard({dataset: {client: data.client || res.client || "", cardId: data.card_id || ""}});
  });
  w.querySelector("[data-stage-xa]")?.addEventListener("click", () => {
    openXaStageModal(data.client || res.client || "");
  });
  w.querySelectorAll("[data-copy-value]").forEach((button) => button.addEventListener("click", async () => {
    await pywebview.api.copy_to_clipboard(button.dataset.copyValue || "");
    button.closest(".job-copy-menu")?.removeAttribute("open");
    setStatus(`Copied ${button.textContent}`, "ok");
  }));
  w.querySelector("[data-copy-summary]")?.addEventListener("click", async (event) => {
    const summary = copyOptions.map(([label, value]) => `${label}: ${value}`).join("\n");
    await pywebview.api.copy_to_clipboard(summary);
    event.currentTarget.closest(".job-copy-menu")?.removeAttribute("open");
    setStatus("Copied formatted job summary", "ok");
  });
  w.querySelectorAll("[data-attachment-url]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.attachmentUrl) pywebview.api.open_url(button.dataset.attachmentUrl);
  }));
  w.querySelectorAll("[data-check-item]").forEach((box) => box.addEventListener("change", async () => {
    const row = box.closest(".check-row");
    row?.classList.toggle("checked", box.checked);
    const result = await pywebview.api.set_job_check_item(data.card_id || "", box.dataset.checkItem, box.checked);
    if (!result?.ok) {
      box.checked = !box.checked; row?.classList.toggle("checked", box.checked);
      setStatus(`Checklist update failed: ${result?.error || "Trello unavailable"}`, "error");
    } else if (result.warning) {
      setStatus(`Saved in Linguar Hub · Trello sync needs attention`, "warn");
    } else {
      setStatus("Checklist saved · Trello synced", "ok");
    }
  }));
  const saveWorkType = async (select) => {
    const name = select.dataset.workEnv;
    const tile = select.closest("[data-work-type-card]");
    const owner = tile?.querySelector(`[data-work-env-owner="${name}"]`)?.value || "";
    select.disabled = true;
    const result = await pywebview.api.save_crm_work_environment(
      data.client || res.client || "", name, select.value, owner);
    select.disabled = false;
    if (!result?.ok) {
      setStatus(`Could not update ${name}: ${result?.error || "unknown error"}`, "error");
      return;
    }
    tile?.classList.toggle("has-stage", select.value !== "not_applicable");
    setStatus(`${name} updated for this job`, "ok");
  };
  w.querySelectorAll("[data-work-env]").forEach((select) =>
    select.addEventListener("change", () => saveWorkType(select)));
  w.querySelectorAll("[data-work-env-owner]").forEach((input) =>
    input.addEventListener("change", () => {
      const select = w.querySelector(`[data-work-env="${input.dataset.workEnvOwner}"]`);
      if (select) saveWorkType(select);
    }));
  const pinDivisionCard = async (division, value) => {
    const result = await pywebview.api.pin_crm_division_trello(
      data.client || res.client || "", division, value || "");
    if (!result?.ok) {
      setStatus(`Could not pin ${division}: ${result?.error || "unknown error"}`, "error");
      return;
    }
    close();
    await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS");
    setStatus(`${division} Trello card pinned`, "ok");
  };
  w.querySelectorAll("[data-division-trello-open]").forEach((button) =>
    button.addEventListener("click", () => {
      const card = divisionCards[button.dataset.divisionTrelloOpen.toLowerCase()] || {};
      if (card.url) pywebview.api.open_url(card.url);
    }));
  w.querySelectorAll("[data-division-trello-use]").forEach((button) =>
    button.addEventListener("click", () => {
      const division = button.dataset.divisionTrelloUse;
      if (window.confirm(`Pin the currently open Trello card to ${division}?`))
        pinDivisionCard(division, data.card_id || "");
    }));
  w.querySelectorAll("[data-division-trello-pin]").forEach((button) =>
    button.addEventListener("click", () => {
      const division = button.dataset.divisionTrelloPin;
      const current = (divisionCards[division.toLowerCase()] || {}).url || "";
      const value = window.prompt(`Paste the ${division} Trello card link or card ID:`, current);
      if (value !== null && value.trim()) pinDivisionCard(division, value);
    }));
  w.querySelectorAll("[data-division-trello-remove]").forEach((button) =>
    button.addEventListener("click", async () => {
      const division = button.dataset.divisionTrelloRemove;
      if (!window.confirm(`Remove the pinned ${division} Trello card?`)) return;
      const result = await pywebview.api.unpin_crm_division_trello(
        data.client || res.client || "", division);
      if (!result?.ok) { setStatus(result?.error || "Could not remove card", "error"); return; }
      close(); await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS");
      setStatus(`${division} Trello card removed`, "ok");
    }));
  w.querySelector("[data-open-docusign]")?.addEventListener("click", () => pywebview.api.open_docusign());
  w.querySelector("[data-open-docs-folder]")?.addEventListener("click", () => pywebview.api.open_job_folder(data.client || "", res.path || ""));
  w.querySelectorAll("[data-document-path]").forEach((button) => button.addEventListener("click", () => {
    pywebview.api.open_document(button.dataset.documentPath || "");
  }));
  w.querySelector("[data-mark-docusign-sent]")?.addEventListener("click", async (event) => {
    if (!window.confirm("Only mark this sent after the DocuSign envelope was actually sent. Continue?")) return;
    const button = event.currentTarget; button.disabled = true; button.textContent = "Saving…";
    const result = await pywebview.api.mark_docusign_sent(
      data.client || "", data.card_id || "", copyField("email") || "");
    if (!result?.ok) { button.disabled = false; button.textContent = "Mark envelope sent"; setStatus(result?.error || "Could not track DocuSign request", "error"); return; }
    close(); await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS"); setStatus("DocuSign request marked sent", "ok");
  });
  const openJobLogEditor = (entry = {}) => {
    const host = w.querySelector("[data-job-log-editor]");
    const today = new Date().toISOString().slice(0, 10);
    const activities = ["Initial inspection", "Demo", "Monitor", "Equipment placed", "Equipment pickup", "Contents", "Recon", "Final inspection", "Other"];
    const statuses = ["scheduled", "completed", "rescheduled", "cancelled", "skipped", "needs_review"];
    host.hidden = false;
    host.innerHTML = `<div class="job-log-form">
      <label>Date<input type="date" data-log-field="work_date" value="${escapeAttr(entry.work_date || today)}"></label>
      <label>Activity<select data-log-field="work_type">${activities.map((x) => `<option ${x === entry.work_type ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Status<select data-log-field="status">${statuses.map((x) => `<option value="${x}" ${x === (entry.status || "completed") ? "selected" : ""}>${x.replaceAll("_", " ")}</option>`).join("")}</select></label>
      <label>Technician / crew<input data-log-field="technicians" value="${escapeAttr(entry.technicians || "")}" placeholder="Who completed the work?"></label>
      <label class="wide">Work completed / update<textarea rows="3" data-log-field="note" placeholder="Areas worked, findings, what was completed, and the next step">${escapeHtml(entry.note || "")}</textarea></label>
      <label class="wide">Equipment / readings<input data-log-field="equipment" value="${escapeAttr(entry.equipment || "")}" placeholder="Equipment placed, moved, readings, or pickup"></label>
      <div class="job-log-form-actions"><button class="btn btn-primary" data-save-job-log>Save update</button><button class="btn" data-cancel-job-log>Cancel</button></div></div>`;
    host.querySelector("[data-cancel-job-log]").addEventListener("click", () => { host.hidden = true; host.innerHTML = ""; });
    host.querySelector("[data-save-job-log]").addEventListener("click", async (event) => {
      const payload = {entry_id: entry.entry_id || "", source: entry.source || "pc", source_id: entry.source_id || "", trello_comment_id: entry.trello_comment_id || ""};
      host.querySelectorAll("[data-log-field]").forEach((field) => { payload[field.dataset.logField] = field.value; });
      const button = event.currentTarget; button.disabled = true; button.textContent = "Saving…";
      const result = await pywebview.api.save_job_log_update(data.client || "", payload);
      if (!result?.ok) { button.disabled = false; button.textContent = "Save update"; setStatus(result?.error || "Job Log could not be saved", "error"); return; }
      close(); await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS"); setStatus("Job Log updated", "ok");
    });
  };
  w.querySelector("[data-add-job-log]")?.addEventListener("click", () => openJobLogEditor({}));
  w.querySelector("[data-import-job-log]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget; button.disabled = true; button.textContent = "Reading Trello…";
    const result = await pywebview.api.import_job_log_from_trello(
      data.client || "", data.card_id || "");
    if (!result?.ok) { button.disabled = false; button.textContent = `Refresh from ${selectedDivision} Trello`; setStatus(result?.error || "Could not import the job log", "error"); return; }
    close();
    await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS");
    setStatus(result.imported ? `Added ${result.imported} ${selectedDivision} job-log event(s)` : `${selectedDivision} Job Log is up to date`, "ok");
  });
  w.querySelectorAll("[data-edit-job-log]").forEach((button) => button.addEventListener("click", () => {
    openJobLogEditor((crm.job_log || []).find((entry) => entry.entry_id === button.dataset.editJobLog) || {});
  }));
  w.querySelectorAll("[data-history-job-log]").forEach((button) => button.addEventListener("click", async () => {
    const result = await pywebview.api.job_log_update_history(button.dataset.historyJobLog || "");
    if (!result?.ok) { setStatus(result?.error || "Could not load revision history", "error"); return; }
    openJobLogHistoryModal(result.history || []);
  }));
  w.querySelectorAll("[data-delete-job-log]").forEach((button) => button.addEventListener("click", async () => {
    const entry = (crm.job_log || []).find((item) => item.entry_id === button.dataset.deleteJobLog) || {};
    if (!window.confirm(`Delete the ${entry.work_type || "Job Log"} update from ${entry.work_date || "this job"}?\n\nThis removes the Linguar Hub entry. It does not delete the original Trello comment.`)) return;
    button.disabled = true; button.textContent = "Deleting…";
    const result = await pywebview.api.delete_job_log_update(data.client || "", entry.entry_id || "");
    if (!result?.ok) { button.disabled = false; button.textContent = "Delete"; setStatus(result?.error || "Job Log entry could not be deleted", "error"); return; }
    close(); await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS"); setStatus("Job Log entry deleted", "ok");
  }));
  w.querySelector("[data-post-comment]")?.addEventListener("click", async () => {
    const input = w.querySelector("[data-comment-input]");
    const stateEl = w.querySelector("[data-comment-state]");
    const text = input.value.trim();
    if (!text) return;
    stateEl.textContent = "Saving…";
    const result = await pywebview.api.post_job_comment(data.client || "", data.card_id || "", text);
    if (!result?.ok) { stateEl.textContent = result?.error || "Could not save"; return; }
    w.querySelector("[data-comment-stream]").insertAdjacentHTML("afterbegin", renderJobComment(result.comment));
    input.value = "";
    stateEl.textContent = result.posted_trello ? "Saved · Trello synced" : (result.warning || "Saved in Linguar Hub");
  });
  w.querySelector("[data-comment-stream]")?.addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-comment-edit]");
    const remove = event.target.closest("[data-comment-delete]");
    const button = edit || remove;
    if (!button) return;
    const article = button.closest("[data-comment-id]");
    const id = article?.dataset.commentId || "";
    const source = article?.dataset.commentSource || "linguar";
    const externalId = article?.dataset.commentExternalId || "";
    const current = article?.querySelector("p")?.textContent || "";
    if (edit) {
      const value = window.prompt(`Edit this ${source === "trello" ? "Trello" : "Linguar Hub"} comment:`, current);
      if (value === null || !value.trim() || value.trim() === current.trim()) return;
      button.disabled = true;
      const result = await pywebview.api.edit_job_comment(data.client || "", id, source, value, externalId);
      if (!result?.ok) { button.disabled = false; setStatus(result?.error || "Comment could not be edited", "error"); return; }
      article.querySelector("p").textContent = result.text || value.trim();
      button.disabled = false;
      setStatus(result.warning || (source === "trello" || result.synced_trello ? "Comment updated in Linguar Hub and Trello" : "Linguar Hub comment updated"), result.warning ? "warn" : "ok");
    } else {
      const warning = source === "trello" || externalId ? "This permanently deletes the comment from Trello and Linguar Hub." : "This deletes the Linguar Hub comment only.";
      if (!window.confirm(`${warning}\n\nContinue?`)) return;
      button.disabled = true;
      const result = await pywebview.api.delete_job_comment(data.client || "", id, source, externalId);
      if (!result?.ok) { button.disabled = false; setStatus(result?.error || "Comment could not be deleted", "error"); return; }
      article.remove();
      setStatus(result.warning || (source === "trello" || result.synced_trello ? "Comment deleted from Linguar Hub and Trello" : "Linguar Hub comment deleted"), result.warning ? "warn" : "ok");
    }
  });
  w.querySelector("[data-open-audit]").addEventListener("click", () => {
    if (window.emsNavigateTo) window.emsNavigateTo("audit", res.client || "");
    close();
  });
  return {
    element: w,
    close,
    hasUserInput() {
      return userDirty;
    },
    setDeferredReady(load) {
      const host = w.querySelector("[data-workspace-load-state]");
      if (!host) return;
      host.innerHTML = `<button class="btn compact" type="button">Load live details</button>`;
      host.querySelector("button").addEventListener("click", load);
    },
    setDeferredError(message) {
      const host = w.querySelector("[data-workspace-load-state]");
      if (host) host.textContent = message;
    },
  };
}

function openJobLogHistoryModal(history) {
  const rows = (history || []).map((revision, index) => {
    let after = {};
    try { after = JSON.parse(revision.after_json || "{}"); } catch (_) {}
    return `<article class="revision-row">
      <div><strong>${index === 0 ? "Current version" : `Revision ${history.length - index}`}</strong><time>${escapeHtml(formatCommentDate(revision.changed_at || ""))}</time></div>
      <small>${escapeHtml(revision.changed_by || "Linguar Hub")}</small>
      <p>${escapeHtml(after.note || after.work_type || "Saved update")}</p>
      <span>${escapeHtml((after.status || "").replaceAll("_", " "))}</span>
    </article>`;
  }).join("") || `<div class="aud-empty">No revisions have been saved for this entry.</div>`;
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay";
  modal.innerHTML = `<div class="modal-box revision-modal" role="dialog" aria-modal="true" aria-label="Job Log revision history">
    <header class="modal-head"><div><div class="modal-title">Job Log History</div><div class="modal-sub">Every saved version, newest first</div></div><button class="audit-close" data-close aria-label="Close history">×</button></header>
    <div class="modal-body revision-list">${rows}</div>
    <footer class="modal-foot"><button class="btn" data-close>Close</button></footer></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => { if (event.target === modal) close(); });
}

async function openXaStageModal(client) {
  setStatus(`Loading photo stages for ${client}…`);
  const info = await pywebview.api.list_pics_stages(client);
  if (!info?.ok || !(info.stages || []).length) {
    setStatus(info?.error || `No PICS folders with images found for ${client}`, "warn");
    return;
  }
  const w = document.createElement("div");
  w.className = "modal-scrim audit-overlay xa-picker-overlay";
  w.innerHTML = `<div class="modal-box xa-picker" role="dialog" aria-modal="true" aria-label="Stage photos for XA">
    <header class="modal-head"><div><div class="modal-title">Stage for XA</div><div class="modal-sub">${escapeHtml(client)} · choose a PICS folder</div></div><button class="audit-close" data-close>×</button></header>
    <div class="modal-body xa-stage-list">${info.stages.map((stage) => `<button class="btn xa-stage-choice" data-stage="${escapeAttr(stage.name || "")}"><span>📁 ${escapeHtml(stage.name || "")}</span><small>${Number(stage.count || 0)} images</small></button>`).join("")}</div>
    <footer class="modal-foot"><button class="btn" data-close>Cancel</button></footer></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  w.addEventListener("click", (event) => { if (event.target === w) close(); });
  w.querySelectorAll("[data-stage]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    const original = button.innerHTML;
    button.textContent = "Staging photos…";
    const result = await pywebview.api.copy_pics_to_clipboard(client, button.dataset.stage || "");
    if (!result?.ok) {
      button.disabled = false;
      button.innerHTML = original;
      setStatus(result?.error || "Could not stage the photos", "error");
      return;
    }
    close();
    setStatus(`Staged ${result.count || 0} photos for XA · temporary folder opened`, "ok");
  }));
  setStatus("");
}

function renderJobComment(comment) {
  const actor = comment?.actor || "Linguar Hub";
  const initial = actor.trim().charAt(0).toUpperCase() || "L";
  const source = comment?.source === "trello" ? "trello" : "linguar";
  return `<article class="job-comment" data-comment-id="${escapeAttr(comment?.id || "")}" data-comment-source="${source}" data-comment-external-id="${escapeAttr(comment?.external_id || "")}"><div class="comment-avatar">${escapeHtml(initial)}</div>
    <div><header><strong>${escapeHtml(actor)}</strong><time>${escapeHtml(formatCommentDate(comment?.at || ""))}</time></header>
    <p>${escapeHtml(comment?.text || "")}</p><footer><small>${source === "trello" ? "Trello" : "Linguar Hub"}</small>
    ${comment?.id ? `<span><button class="text-btn" data-comment-edit>Edit</button><button class="text-btn danger" data-comment-delete>Delete</button></span>` : ""}</footer></div></article>`;
}

function formatCommentDate(value) {
  if (!value) return "now";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"});
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
      state.active_stage = b.dataset.stage;
      PanelState.set({ active_stage: state.active_stage });
      renderChips(); renderTable();
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
  PanelState.set({ search: state.search });
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
