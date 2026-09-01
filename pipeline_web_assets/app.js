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
  boardLooks: {},            // board key -> {preset, customPath, customData}
  boardZoom: 1,
  jobShelf: [],
  drag: null,               // {cardId, name, fromListId, fromLane, boardKey}
  laneDrag: null,           // {listId, name, targetId, side}
  // Stages table view
  rows: [],
  stages: [],               // [{key, label}]
  stage_counts: {},
  active_stage: "all",
  search: "",
  sort_key: "days_in_stage",
  sort_dir: "desc",
  selected_card_id: null,
  board_loaded: false,
  stage_render_limit: 350,
};
let workspaceRequestId = 0;
let stagesLoadPromise = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", () => bootPipeline().catch(showPipelineStartupError));

async function bootPipeline() {
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
  state.boardLooks     = PanelState.get("boardLooks", {});
  state.boardZoom      = Number(PanelState.get("boardZoom", 1)) || 1;
  state.jobShelf       = Array.isArray(PanelState.get("jobShelf", []))
    ? PanelState.get("jobShelf", []).filter((item) => item?.cardId).map((item) => ({
        ...item, mode: item.mode === "held" ? "held" : "starred",
      })) : [];
  state.active_stage   = PanelState.get("active_stage", state.active_stage);
  state.search         = PanelState.get("search", "");

  $("#view-board-btn").addEventListener("click", () => setView("board"));
  $("#view-stages-btn").addEventListener("click", () => setView("stages"));
  $("#new-loss-btn").addEventListener("click", () => {
    window.parent.postMessage({ type: "linguar-open-new-loss" }, "*");
  });
  $("#refresh-btn").addEventListener("click", () => loadBoard(true));
  $("#board-zoom-out").addEventListener("click", () => changeBoardZoom(-0.1));
  $("#board-zoom-in").addEventListener("click", () => changeBoardZoom(0.1));
  $("#board-zoom-reset").addEventListener("click", () => setBoardZoom(1));
  $("#job-shelf-clear").addEventListener("click", clearJobShelf);
  const shelf = $("#job-shelf");
  shelf.addEventListener("dragover", onShelfDragOver);
  shelf.addEventListener("dragleave", onShelfDragLeave);
  shelf.addEventListener("drop", onShelfDrop);
  $("#customize-board-btn").addEventListener("click", openBoardCustomize);
  $("#custom-background-btn").addEventListener("click", chooseCustomBackground);
  $("#clear-background-btn").addEventListener("click", () => setBoardLook({ preset: "asphalt" }));
  $$("[data-board-look]").forEach((button) => button.addEventListener("click", () =>
    setBoardLook({ preset: button.dataset.boardLook })));

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
  window.addEventListener("keydown", onBoardZoomShortcut);

  applyBoardZoom();
  renderJobShelf();

  const initialView = state.view;
  state.view = "";
  setView(initialView, false);
  if (initialView === "board") await loadBoard();
  // A custom board photo is decoration, not job data. Load it only after
  // the lanes are usable so a slow OneDrive path or missing image can never
  // hold the Jobs board on its skeleton.
  hydrateCustomBoardLooks().then(() => applyBoardLook(state.activeBoardKey)).catch(() => {});
  if (initialView === "stages" && !state.stages.length) await loadStages();
}

function showPipelineStartupError(error) {
  const message = String(error?.message || error || "Unknown startup error");
  const root = $("#board-view");
  if (root) {
    root.innerHTML = `<div class="empty-state startup-error">
      <div class="empty-emoji">⚠️</div>
      <strong>Jobs could not finish starting</strong>
      <div>${escapeHtml(message)}</div>
      <button class="btn btn-primary" type="button" data-retry-startup>Retry</button>
    </div>`;
    root.querySelector("[data-retry-startup]")?.addEventListener("click", () => location.reload());
  }
  setStatus(`Jobs startup error: ${message}`, "error");
  console.error("Pipeline startup failed", error);
}

// ── View switching ───────────────────────────────────────────────
function setView(v, loadOnEnter = true) {
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
  if (loadOnEnter && v === "stages" && !state.stages.length) loadStages();
  else if (v === "stages") renderTable();
  else if (loadOnEnter && !state.board_loaded) loadBoard();
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
    const res = await withTimeout(
      pywebview.api.board_view(Boolean(isRefresh)),
      isRefresh ? 45000 : 12000,
      isRefresh ? "Job sync timed out" : "Jobs took too long to respond"
    );
    if (!res?.ok) {
      const message = res?.error || "The board returned no data";
      setStatus(`Board load failed: ${message}`, "error");
      if (!isRefresh) showBoardLoadError(message);
      return;
    }
    state.board = res;
    state.board_loaded = true;
    reconcileJobShelfWithBoard();
    renderBoard();
    const total = boardCardTotal();
    const source = res.source === "shared" ? "shared Pipeline" :
      (res.mirrored ? "Trello · saved to Pipeline" : "Trello");
    setStatus(`✓ ${total} cards across ${res.boards.length} boards · ${source}`, "ok");
    if (res.stale_cache && !isRefresh) refreshSavedBoardInBackground();
  } catch (ex) {
    setStatus(`Board error: ${ex}`, "error");
    if (!isRefresh) showBoardLoadError(ex?.message || ex);
  } finally {
    if (isRefresh) { btn.disabled = false; btn.textContent = "↻ Sync Jobs"; }
  }
}

// Board-only zoom keeps the app chrome readable while dispatchers trade
// detail for lane coverage. Deliberate stops prevent microscopic cards.
function setBoardZoom(value) {
  const next = Math.max(0.7, Math.min(1.4, Math.round(Number(value) * 10) / 10));
  state.boardZoom = next;
  PanelState.set({ boardZoom: next });
  applyBoardZoom();
}

function changeBoardZoom(delta) { setBoardZoom(state.boardZoom + delta); }

function applyBoardZoom() {
  const board = $("#board-view");
  if (board) board.style.setProperty("--board-zoom", String(state.boardZoom));
  const value = $("#board-zoom-reset");
  if (value) {
    value.textContent = `${Math.round(state.boardZoom * 100)}%`;
    value.setAttribute("aria-label", `Jobs board zoom ${value.textContent}; reset to 100%`);
  }
  const out = $("#board-zoom-out"), inside = $("#board-zoom-in");
  if (out) out.disabled = state.boardZoom <= 0.7;
  if (inside) inside.disabled = state.boardZoom >= 1.4;
}

function onBoardZoomShortcut(event) {
  if (state.view !== "board" || !event.ctrlKey || event.altKey) return;
  if (event.key === "+" || event.key === "=") {
    event.preventDefault(); changeBoardZoom(0.1);
  } else if (event.key === "-") {
    event.preventDefault(); changeBoardZoom(-0.1);
  } else if (event.key === "0") {
    event.preventDefault(); setBoardZoom(1);
  }
}

async function refreshSavedBoardInBackground() {
  try {
    const fresh = await pywebview.api.board_view_shared_refresh();
    if (!fresh?.ok || !(fresh.boards || []).length) return;
    const changed = boardFingerprint(state.board) !== boardFingerprint(fresh);
    const priorScroll = $(".lanes-row")?.scrollLeft || 0;
    state.board = fresh;
    if (changed) {
      renderBoard();
      requestAnimationFrame(() => {
        const row = $(".lanes-row");
        if (row) row.scrollLeft = priorScroll;
      });
    }
    const source = fresh.source === "shared" ? "shared Pipeline" : "Trello";
    setStatus(`✓ ${boardCardTotal()} jobs · ${source} is current`, "ok");
  } catch (_) {
    // The saved board remains fully usable. Explicit Sync Jobs surfaces
    // network errors when the user wants to troubleshoot them.
  }
}

function withTimeout(promise, milliseconds, message) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function showBoardLoadError(error) {
  const root = $("#board-view");
  if (!root) return;
  root.innerHTML = `<div class="empty-state startup-error">
    <div class="empty-emoji">⚠️</div>
    <strong>Jobs could not be loaded</strong>
    <div>${escapeHtml(String(error || "Unknown board error"))}</div>
    <button class="btn btn-primary" type="button" data-retry-board>Retry Jobs</button>
  </div>`;
  root.querySelector("[data-retry-board]")?.addEventListener("click", () => loadBoard(false));
}

function boardFingerprint(payload) {
  return (payload?.boards || []).map((board) => [
    board.key,
    ...(board.lanes || []).map((lane) => [
      lane.list_id,
      ...(lane.cards || []).map((card) => card.card_id),
    ]),
  ]).flat(4).join("|");
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
  applyBoardLook(active.key);
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
    lanesHtml = `<div class="lanes-row" data-hdrag data-hdrag-nowheel>${lanes || `<div class="lane-empty">No lanes.</div>`}<div class="lane-add" data-no-drag><button class="lane-add-button" type="button" data-add-lane>＋ Add another lane</button></div></div>`;
  }

  root.innerHTML = `
    <section class="pipeline-summary" aria-label="Filter jobs by status">
      <button class="summary-primary ${state.boardFilter === "all" ? "active" : ""}" data-board-filter="all"><strong>${summary.total}</strong><span>Active jobs</span></button>
      <button class="summary-item ${summary.attention ? "needs-attention" : ""} ${state.boardFilter === "attention" ? "active" : ""}" data-board-filter="attention"><strong>${summary.attention}</strong><span>Need attention</span></button>
      <button class="summary-item ${state.boardFilter === "due" ? "active" : ""}" data-board-filter="due"><strong>${summary.due}</strong><span>Due soon</span></button>
      ${summary.waiting ? `<button class="summary-item ${state.boardFilter === "sync" ? "active" : ""}" data-board-filter="sync"><strong>${summary.waiting}</strong><span>Waiting to sync</span></button>` : ""}
      <div class="summary-help">Click to open · drag to move</div>
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
      applyBoardLook(state.activeBoardKey);
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
    cardEl.querySelector('[data-act="star"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); toggleCardShelf(cardEl);
    });
    cardEl.querySelector('[data-act="more"]')?.addEventListener("click", (e) => {
      e.stopPropagation(); openCardMenu(e, cardEl);
    });
  });
  root.querySelectorAll(".lane-head").forEach((head) => {
    head.addEventListener("dragstart", onLaneDragStart);
    head.addEventListener("dragend", onLaneDragEnd);
  });
  root.querySelectorAll("[data-lane-menu]").forEach((button) =>
    button.addEventListener("click", (event) => {
      event.stopPropagation(); openLaneMenu(event, button.closest(".lane"));
    }));
  root.querySelector("[data-add-lane]")?.addEventListener("click", openAddLaneComposer);
}

function activeBoardLook() {
  return state.boardLooks[state.activeBoardKey] || { preset: "asphalt" };
}

function applyBoardLook(boardKey) {
  const root = $("#board-view");
  if (!root) return;
  const look = state.boardLooks[boardKey] || { preset: "asphalt" };
  root.dataset.boardLook = look.preset || "asphalt";
  root.classList.toggle("has-custom-background", Boolean(look.customData));
  root.style.setProperty("--board-custom-image",
    look.customData ? `url("${look.customData}")` : "none");
}

function openBoardCustomize() {
  const dialog = $("#board-customize-dialog");
  if (!dialog) return;
  const look = activeBoardLook();
  dialog.querySelectorAll("[data-board-look]").forEach((button) =>
    button.classList.toggle("selected", button.dataset.boardLook === look.preset && !look.customData));
  $("#background-status").textContent = look.customPath
    ? `Using ${look.customPath.split(/[\\/]/).pop()}` : "";
  if (!dialog.open) dialog.showModal();
}

function setBoardLook(next) {
  if (!state.activeBoardKey) return;
  state.boardLooks[state.activeBoardKey] = { ...next };
  const savedLooks = Object.fromEntries(Object.entries(state.boardLooks).map(([key, look]) =>
    [key, { preset: look.preset || "asphalt", customPath: look.customPath || "" }]));
  PanelState.set({ boardLooks: savedLooks });
  applyBoardLook(state.activeBoardKey);
  $("#background-status").textContent = "Board background updated";
  openBoardCustomize();
}

async function hydrateCustomBoardLooks() {
  const jobs = Object.entries(state.boardLooks).map(async ([key, look]) => {
    if (!look?.customPath) return;
    try {
      const result = await pywebview.api.load_board_background(look.customPath);
      if (result?.ok) state.boardLooks[key] = { ...look, customData: result.data_url };
      else state.boardLooks[key] = { preset: "asphalt" };
    } catch (_) {
      state.boardLooks[key] = { preset: "asphalt" };
    }
  });
  await Promise.all(jobs);
}

async function chooseCustomBackground() {
  const button = $("#custom-background-btn");
  const status = $("#background-status");
  button.disabled = true;
  button.textContent = "Choosing…";
  status.textContent = "";
  try {
    const result = await pywebview.api.choose_board_background();
    if (result?.cancelled) return;
    if (!result?.ok) { status.textContent = result?.error || "Could not use that image."; return; }
    setBoardLook({ preset: "custom", customPath: result.path, customData: result.data_url });
    status.textContent = `Using ${result.name}`;
  } catch (error) {
    status.textContent = `Could not choose a background: ${error}`;
  } finally {
    button.disabled = false;
    button.textContent = "Choose a Photo…";
  }
}

function laneMatches(lane, q) {
  return (lane.cards || []).filter((c) => {
    // A dragged/held card lives in the shelf until it is placed or returned.
    // A starred card is only a shortcut and remains visible in its lane.
    if (state.jobShelf.some((item) => item.cardId === c.card_id && item.mode === "held")) return false;
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
    <div class="lane-head" draggable="true" title="Drag to reorder lane">
      <span class="lane-grip" aria-hidden="true">⠿</span>
      <span class="lane-name">${escapeHtml(lane.name)}</span>
      <span class="lane-count">${cards.length}</span>
      <button class="lane-menu-button" type="button" data-lane-menu data-no-drag aria-label="Lane actions for ${escapeAttr(lane.name)}">⋯</button>
    </div>
    <div class="lane-cards">${cardsHtml}</div>
  </div>`;
}

function activeBoard() {
  return (state.board.boards || []).find((board) => board.key === state.activeBoardKey);
}

function openAddLaneComposer() {
  const host = $(".lane-add");
  if (!host || host.querySelector("form")) return;
  host.innerHTML = `<form class="lane-add-form"><input maxlength="80" aria-label="Lane name" placeholder="Lane name…"><div><button class="btn btn-primary compact" type="submit">Add lane</button><button class="lane-compose-cancel" type="button" aria-label="Cancel">×</button></div></form>`;
  const input = host.querySelector("input");
  input.focus();
  host.querySelector(".lane-compose-cancel").addEventListener("click", renderBoard);
  host.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    const submit = host.querySelector("[type='submit']");
    submit.disabled = true; submit.textContent = "Adding…";
    const result = await pywebview.api.create_lane(state.activeBoardKey, name);
    if (!result?.ok) { setStatus(`Could not add lane: ${result?.error || "?"}`, "error"); submit.disabled = false; submit.textContent = "Add lane"; return; }
    activeBoard()?.lanes.push(result.lane);
    renderBoard();
    requestAnimationFrame(() => { const row = $(".lanes-row"); if (row) row.scrollLeft = row.scrollWidth; });
    setStatus(`✓ Added lane “${name}” to Trello`, "ok");
  });
}

function openLaneMenu(event, laneEl) {
  $(".lane-popover")?.remove();
  const menu = document.createElement("div");
  menu.className = "lane-popover";
  menu.innerHTML = `<button type="button" data-rename-lane>Rename lane</button><button type="button" class="danger" data-archive-lane>Archive lane</button>`;
  document.body.appendChild(menu);
  const rect = event.currentTarget.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.right - 180, window.innerWidth - 190)}px`;
  menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 110)}px`;
  const close = () => menu.remove();
  setTimeout(() => document.addEventListener("click", close, { once: true }), 0);
  menu.addEventListener("click", (e) => e.stopPropagation());
  menu.querySelector("[data-rename-lane]").addEventListener("click", () => { close(); startLaneRename(laneEl); });
  menu.querySelector("[data-archive-lane]").addEventListener("click", async () => {
    close();
    const name = laneEl.dataset.laneName;
    const count = laneEl.querySelectorAll(".kcard").length;
    if (!confirm(`Archive “${name}” on Trello?${count ? `\n\nThis lane contains ${count} job${count === 1 ? "" : "s"}.` : ""}`)) return;
    const result = await pywebview.api.archive_lane(laneEl.dataset.listId);
    if (!result?.ok) { setStatus(`Could not archive lane: ${result?.error || "?"}`, "error"); return; }
    const board = activeBoard();
    board.lanes = board.lanes.filter((lane) => lane.list_id !== laneEl.dataset.listId);
    renderBoard(); setStatus(`✓ Archived “${name}” on Trello`, "ok");
  });
}

function startLaneRename(laneEl) {
  const label = laneEl.querySelector(".lane-name");
  const oldName = laneEl.dataset.laneName;
  label.innerHTML = `<input class="lane-name-input" maxlength="80" value="${escapeAttr(oldName)}" aria-label="Lane name">`;
  const input = label.querySelector("input");
  input.focus(); input.select();
  let finished = false;
  const finish = async (save) => {
    if (finished) return;
    finished = true;
    const name = input.value.trim();
    if (!save || !name || name === oldName) { label.textContent = oldName; return; }
    input.disabled = true;
    const result = await pywebview.api.rename_lane(laneEl.dataset.listId, name);
    if (!result?.ok) { label.textContent = oldName; setStatus(`Could not rename lane: ${result?.error || "?"}`, "error"); return; }
    const lane = activeBoard()?.lanes.find((item) => item.list_id === laneEl.dataset.listId);
    if (lane) lane.name = result.name || name;
    renderBoard(); setStatus(`✓ Renamed lane to “${name}”`, "ok");
  };
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); finish(true); } if (event.key === "Escape") finish(false); });
  input.addEventListener("blur", () => finish(true), { once: true });
}

function onLaneDragStart(event) {
  if (event.target.closest("button, input")) { event.preventDefault(); return; }
  const lane = event.currentTarget.closest(".lane");
  state.laneDrag = { listId: lane.dataset.listId, name: lane.dataset.laneName };
  lane.classList.add("lane-dragging");
  try { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", `lane:${lane.dataset.listId}`); } catch (_) {}
}

function onLaneDragEnd() {
  state.laneDrag = null;
  $$(".lane").forEach((lane) => lane.classList.remove("lane-dragging", "lane-drop-before", "lane-drop-after"));
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
  const starred = isJobStarred(c.card_id);
  return `<div class="kcard stall-border-${escapeAttr(c.stall)}" draggable="false" data-no-drag
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
      <button class="kbtn card-star ${starred ? "active" : ""}" data-act="star" aria-label="${starred ? "Unstar" : "Star"} ${escapeAttr(c.client || "job")}" title="${starred ? "Remove quick-look shortcut" : "Keep a quick-look shortcut on the Job Shelf"}">★</button>
      <button class="kbtn" data-act="more" aria-label="More actions for ${escapeAttr(c.client || "job")}" title="More job actions">⋯</button>
    </div>
  </div>`;
}

// ── Drag to move (write-back with confirm) ───────────────────────
function wireCardClickAndHold(cardEl) {
  let startX = 0;
  let startY = 0;
  let pressActive = false;
  let suppressClick = false;
  let openedOnPointerUp = false;
  let pointerDragging = false;
  // The card itself has role="button" for keyboard accessibility. Only
  // controls nested inside it should suppress the card-open action.
  const interactive = (target) => {
    const control = target.closest("button, a, input, textarea, select, [role='button']");
    return Boolean(control && control !== cardEl);
  };
  cardEl.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || interactive(event.target)) return;
    startX = event.clientX;
    startY = event.clientY;
    pressActive = true;
    suppressClick = false;
    try { cardEl.setPointerCapture(event.pointerId); } catch (_) {}
  });
  cardEl.addEventListener("pointermove", (event) => {
    if (!pressActive) return;
    if (Math.hypot(event.clientX - startX, event.clientY - startY) > 5) {
      suppressClick = true;
      cardEl.classList.add("drag-ready");
      if (!pointerDragging) {
        pointerDragging = true;
        beginPointerCardDrag(cardEl, event);
      }
      updatePointerCardDrag(event);
    }
  });
  const release = (event, allowOpen = true) => {
    if (pointerDragging) {
      pointerDragging = false;
      pressActive = false;
      cardEl.classList.remove("drag-ready");
      finishPointerCardDrag(event);
      return;
    }
    const shouldOpen = allowOpen && event.button === 0 && !interactive(event.target)
      && pressActive && !suppressClick
      && cardEl.dataset.didDrag !== "true";
    pressActive = false;
    cardEl.classList.remove("drag-ready");
    if (shouldOpen) {
      // Open on pointerup so the ancestor grab-scroll helper cannot swallow
      // the later synthetic click during its capture phase.
      openedOnPointerUp = true;
      onAuditCard(cardEl);
    }
  };
  cardEl.addEventListener("pointerup", release);
  cardEl.addEventListener("pointercancel", (event) => release(event, false));
  cardEl.addEventListener("click", (event) => {
    if (interactive(event.target)) return;
    if (openedOnPointerUp) {
      openedOnPointerUp = false;
      return;
    }
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

let pointerCardDrag = null;

function dragDetailsFromCard(el) {
  const lane = el.closest(".lane");
  return {
    cardId: el.dataset.cardId, name: el.dataset.client,
    fromListId: el.dataset.listId, url: el.dataset.url || "",
    fromLane: lane?.dataset.laneName || "",
    summary: el.dataset.cardSummary || "", source: "board",
  };
}

function beginPointerCardDrag(cardEl, event) {
  const ghost = document.createElement("div");
  ghost.className = "card-drag-ghost";
  ghost.innerHTML = `<strong>${escapeHtml(cardEl.dataset.client || "Job")}</strong><span>Release at the bottom to hold</span>`;
  document.body.appendChild(ghost);
  cardEl.dataset.didDrag = "true";
  cardEl.classList.add("dragging");
  state.drag = dragDetailsFromCard(cardEl);
  pointerCardDrag = { cardEl, ghost, drag: { ...state.drag } };
  showShelfForDrag();
  updatePointerCardDrag(event);
}

function updatePointerCardDrag(event) {
  if (!pointerCardDrag) return;
  pointerCardDrag.ghost.style.transform = `translate3d(${event.clientX + 14}px,${event.clientY + 14}px,0) rotate(2deg)`;
  const inHandZone = event.clientY >= window.innerHeight - 175;
  $("#job-shelf").classList.toggle("drop-ready", inHandZone);
  $$(".lane.drop-target").forEach((lane) => lane.classList.remove("drop-target"));
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".lane");
  if (!inHandZone && target) target.classList.add("drop-target");
}

function finishPointerCardDrag(event) {
  if (!pointerCardDrag) return;
  const active = pointerCardDrag;
  const drag = active.drag;
  const inHandZone = event.clientY >= window.innerHeight - 175;
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".lane");
  active.ghost.remove();
  active.cardEl.classList.remove("dragging", "drag-ready");
  pointerCardDrag = null;
  $$(".lane.drop-target").forEach((lane) => lane.classList.remove("drop-target"));
  if (inHandZone) {
    holdDraggedCard(drag);
  } else if (target) {
    hideShelfAfterDrag();
    state.drag = drag;
    void onLaneDrop({ preventDefault() {}, currentTarget: target });
  } else {
    state.drag = null;
    hideShelfAfterDrag();
  }
}

function onCardDragStart(ev) {
  const el = ev.currentTarget;
  el.dataset.didDrag = "true";
  state.drag = {
    cardId:   el.dataset.cardId,
    name:     el.dataset.client,
    fromListId: el.dataset.listId,
    url:        el.dataset.url || "",
    summary:    el.dataset.cardSummary || "",
    source:     "board",
  };
  el.classList.add("dragging");
  showShelfForDrag();
  try { ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", el.dataset.cardId); } catch (_) {}
}

function onCardDragEnd(ev) {
  ev.currentTarget.classList.remove("dragging", "drag-ready");
  state.drag = null;
  hideShelfAfterDrag();
  $$(".lane.drop-target").forEach((l) => l.classList.remove("drop-target"));
}

function onLaneDragOver(ev) {
  if (state.laneDrag) {
    const lane = ev.currentTarget;
    if (lane.dataset.listId === state.laneDrag.listId) return;
    ev.preventDefault();
    const side = ev.clientX < lane.getBoundingClientRect().left + lane.offsetWidth / 2 ? "before" : "after";
    lane.classList.toggle("lane-drop-before", side === "before");
    lane.classList.toggle("lane-drop-after", side === "after");
    state.laneDrag.targetId = lane.dataset.listId; state.laneDrag.side = side;
    return;
  }
  reconcileJobShelfWithBoard();
  if (!state.drag) return;
  ev.preventDefault();
  try { ev.dataTransfer.dropEffect = "move"; } catch (_) {}
  ev.currentTarget.classList.add("drop-target");
}

function onLaneDragLeave(ev) {
  ev.currentTarget.classList.remove("drop-target", "lane-drop-before", "lane-drop-after");
}

async function onLaneDrop(ev) {
  ev.preventDefault();
  const laneEl = ev.currentTarget;
  if (state.laneDrag) {
    const moving = state.laneDrag;
    const board = activeBoard();
    const lanes = board?.lanes || [];
    const from = lanes.findIndex((lane) => lane.list_id === moving.listId);
    let to = lanes.findIndex((lane) => lane.list_id === laneEl.dataset.listId);
    if (from < 0 || to < 0 || from === to) { onLaneDragEnd(); return; }
    const [item] = lanes.splice(from, 1);
    if (from < to) to -= 1;
    if (moving.side === "after") to += 1;
    lanes.splice(to, 0, item);
    const previousId = lanes[to - 1]?.list_id || "";
    const nextId = lanes[to + 1]?.list_id || "";
    onLaneDragEnd(); renderBoard();
    const result = await pywebview.api.reorder_lane(item.list_id, previousId, nextId);
    if (!result?.ok) { setStatus(`Could not move lane: ${result?.error || "?"}`, "error"); await loadBoard(true); return; }
    setStatus(`✓ Moved “${item.name}” on Trello`, "ok");
    return;
  }
  laneEl.classList.remove("drop-target");
  const drag = state.drag;
  state.drag = null;
  if (!drag) return;
  const toListId = laneEl.dataset.listId;
  const toLane = laneEl.dataset.laneName;
  if (!toListId) return;
  if (toListId === drag.fromListId) {
    if (drag.source === "shelf") removeFromJobShelf(drag.cardId);
    return;
  }
  const conflictNote = drag.conflict
    ? `\n\nConflict: Trello moved this card to “${drag.actualLane || "another lane"}” while it was held.` : "";
  if (!confirm(`Move "${drag.name}" to "${toLane}" on Trello?\n\nThis updates the real board everyone sees.${conflictNote}`))
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
  if (drag.source === "shelf") removeFromJobShelf(drag.cardId);
  renderBoard();
  showMoveUndo(drag, toListId, toLane);
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
  const shelfItem = state.jobShelf.find((item) => item.cardId === cardId);
  if (shelfItem) {
    shelfItem.fromListId = toListId;
    shelfItem.lane = toLane;
    persistJobShelf(); renderJobShelf();
  }
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
  let modal;
  try {
    modal = openAuditModal(instant, resolvedUrl);
  } catch (error) {
    // Never let a job-specific data shape turn a click into apparent silence.
    modal = openAuditLoadingModal(client);
    modal.showError(`The card opened, but its workspace could not render: ${error?.message || error}`);
    setStatus(`Card opened · workspace layout needs review`, "error");
    return;
  }
  setStatus(`Opened "${client}" · loading shared job details…`);
  try {
    const fast = await pywebview.api.job_card_workspace_fast(client, resolvedCardId, division);
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (!fast?.ok) {
      modal.setDeferredError(fast?.error || "Shared job details unavailable");
      setStatus(`Basic card opened · loading Trello and local details…`, "warn");
    } else if (!modal.hasUserInput()) {
      modal.close();
      modal = openAuditModal(fast, fast.selected_trello_url || resolvedUrl);
      setStatus(`Job opened in ${fast.load_ms || 0} ms · loading audit, Trello, and documents…`);
    }
    // The full request starts after the shared CRM payload is cached. Running
    // both at once duplicated the same Supabase hydration and could more than
    // double load time on slower office connections.
    const fullPromise = Promise.resolve(pywebview.api.job_card_workspace(
      client, resolvedCardId, division)).then(
        (value) => ({ value }),
        (error) => ({ error }),
      );
    const fullOutcome = await fullPromise;
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (fullOutcome.error) {
      modal.setDeferredError(fullOutcome.error?.message || String(fullOutcome.error));
      setStatus(`Job opened · live details could not refresh`, "warn");
      return;
    }
    const full = fullOutcome.value;
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
      : `<div class="audit-missing-summary"><strong>${issues.length} missing item${issues.length === 1 ? "" : "s"}</strong><span>Complete these before this job can move forward.</span></div><ul class="aud-list missing-audit-list">${issues.map((i) =>
          `<li><span class="aud-tag aud-missing">Missing ${escapeHtml(i.kind.toLowerCase())}</span> ${escapeHtml(i.text)}</li>`).join("")}</ul>`;
  const facts = (data.info_sections || []).map((section) => `
    <section class="aud-section info-section"><h3>${escapeHtml(section.name)}</h3>
      <dl class="aud-facts">${(section.fields || []).map((f) =>
        `<div><dt>${escapeHtml(f.label)}</dt><dd>${escapeHtml(f.value)}</dd></div>`).join("")}</dl>
    </section>`).join("");
  const oldJobs = (data.old_jobs || []).map((job) => `<article class="old-job-row">
    <div><strong>${escapeHtml(job.name || "Previous EMS job")}</strong><small>${escapeHtml([
      job.claim_number ? `Claim ${job.claim_number}` : "",
      job.loss_date ? `Loss ${job.loss_date}` : "",
      job.date_received ? `Received ${job.date_received}` : "",
      job.list_name || "THE LOGS - EMS",
    ].filter(Boolean).join(" · "))}</small></div><span>Closed</span>
    <button class="btn compact" data-open-old-job="${escapeAttr(job.url || "")}" ${job.url ? "" : "disabled"}>Open old card</button>
  </article>`).join("");
  const oldJobsSection = oldJobs ? `<section class="aud-section old-jobs-section"><div class="section-title-row"><div><h3>Previous EMS jobs</h3><small>Separate closed claims found in THE LOGS – EMS</small></div><span>${(data.old_jobs || []).length}</span></div><div class="old-jobs-list">${oldJobs}</div></section>` : "";
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
  const claimNumber = copyField("claim_number");
  const activity = (res.activity || []).length
    ? `<div class="aud-chips">${res.activity.map((a) => `<span>${escapeHtml(a)}</span>`).join("")}</div>`
    : `<div class="aud-empty">No activity recorded for this run.</div>`;
  const misplaced = [...(res.misplaced_forms || []), ...(res.misplaced_photos || [])];
  const misplacedHtml = misplaced.length
    ? `<ul class="aud-list">${misplaced.map((item) => `<li><span class="aud-tag aud-warn">Moved</span> ${escapeHtml(item.label || item)}${item.where ? ` <small>${escapeHtml(item.where)}</small>` : ""}</li>`).join("")}</ul>`
    : "";
  const progress = crm.progress || {};
  const requirementRows = (items) => items.map((item) => {
    const statusLabel = item.status === "completed" ? "Complete"
      : item.status === "not_applicable" ? "N/A"
      : item.status === "blocked" ? "Blocked"
      : item.status === "in_progress" ? "In progress" : "Missing";
    return `
    <div class="requirement-row req-${escapeAttr(item.status || "required_now")}">
      <button type="button" class="requirement-mark" data-requirement-complete="${escapeAttr(item.key || "")}" aria-label="${item.status === "todo" || item.status === "in_progress" ? "Complete" : "Update"} ${escapeAttr(item.label || "requirement")}">${item.status === "completed" ? "✓" : item.status === "not_applicable" ? "—" : item.status === "blocked" ? "×" : item.status === "in_progress" ? "◐" : "○"}</button>
      <span class="requirement-copy"><strong>${escapeHtml(item.label || "")}</strong>
      <b class="req-status status-${escapeAttr((item.status || "todo").replaceAll("_", "-"))}">${statusLabel}</b>
      <small>${escapeHtml((item.status || "todo").replaceAll("_", " "))} · ${escapeHtml(item.assignee || item.owner || "Unassigned")}${item.due_at ? " · Due " + escapeHtml(formatCommentDate(item.due_at)) : ""}${item.evidence ? " · " + escapeHtml(item.evidence) : ""}</small>
      <span class="requirement-flags">${item.importance === "mandatory" ? `<b class="req-flag mandatory">Mandatory</b>` : item.importance === "recommended" ? `<b class="req-flag recommended">Recommended</b>` : ""}${item.overdue ? `<b class="req-flag overdue">Overdue</b>` : ""}${item.carried_forward ? `<b class="req-flag carried">Carried forward</b>` : ""}${item.status === "blocked" && item.follow_up_at ? `<b class="req-flag blocked">Follow up ${escapeHtml(formatCommentDate(item.follow_up_at))}</b>` : ""}</span>
      ${item.manual_actor ? `<small class="requirement-manual">Updated by ${escapeHtml(item.manual_actor)}${item.manual_at ? " · " + escapeHtml(formatCommentDate(item.manual_at)) : ""}${item.manual_note ? " · " + escapeHtml(item.manual_note) : ""}</small>` : ""}</span>
      <button type="button" class="requirement-edit" data-requirement-key="${escapeAttr(item.key || "")}">Update</button>
    </div>`;
  }).join("");
  const requirementGroups = {attention: [], completed: [], not_applicable: [], recommended: []};
  (progress.items || []).forEach((item) => {
    if (item.status === "completed" || item.status === "not_applicable") requirementGroups[item.status].push(item);
    else if (item.importance === "recommended") requirementGroups.recommended.push(item);
    else requirementGroups.attention.push(item);
  });
  const required = (progress.items || []).length ? `
    ${progress.review_mode ? `<div class="requirement-review-note"><strong>Review mode</strong><span>Requirements are visible for testing but do not enforce stage movement yet.</span></div>` : ""}
    <div class="requirement-group ${progress.counts?.overdue ? "overdue" : ""}"><h4>Needs attention</h4>${requirementRows(requirementGroups.attention) || `<div class="aud-empty">No required work needs attention.</div>`}</div>
    ${requirementGroups.recommended.length ? `<details class="requirement-history"><summary>Recommended <span>${requirementGroups.recommended.length}</span></summary>${requirementRows(requirementGroups.recommended)}</details>` : ""}
    <details class="requirement-history"><summary>Completed &amp; previous requirements <span>${requirementGroups.completed.length + requirementGroups.not_applicable.length}</span></summary>${requirementRows([...requirementGroups.completed, ...requirementGroups.not_applicable]) || `<div class="aud-empty">No verified requirements yet.</div>`}</details>`
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
  const checklistDivisionTabs = pinnedDivisionCards.length > 1 ? `<div class="checklist-division-tabs" role="tablist" aria-label="Checklist division">
    ${pinnedDivisionCards.map((card) => `<button type="button" role="tab" data-checklist-division="${escapeAttr(card.division)}" aria-selected="${card.division === selectedDivision ? "true" : "false"}" class="${card.division === selectedDivision ? "active" : ""}">${card.division === "EMS" ? "💧 EMS" : card.division === "CONTENTS" ? "▣ Contents" : "🔨 Recon"}</button>`).join("")}
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
    <article class="job-log-row snapshot-log-row" data-job-log-id="${escapeAttr(entry.entry_id || "")}">
      <div class="job-log-date"><time>${escapeHtml(formatAppDate(entry.work_date || ""))}</time><span>${escapeHtml((entry.status || "completed").replaceAll("_", " "))}</span></div><div class="job-log-copy">
      <div class="job-log-title"><strong>${escapeHtml(entry.work_type || "Job update")}</strong>${entry.technicians ? `<span>Crew · ${escapeHtml(entry.technicians)}</span>` : ""}</div>
      ${entry.source !== "trello" && entry.note ? `<div class="job-log-field"><b>Update</b><p>${escapeHtml(entry.note)}</p></div>` : ""}
      ${entry.equipment ? `<div class="job-log-field"><b>Equipment / readings</b><p>${escapeHtml(entry.equipment)}</p></div>` : ""}
      ${entry.source === "trello" && entry.note ? `<details class="job-log-source"><summary>Original Trello comment</summary><div><small>Imported from the ${escapeHtml(selectedDivision)} card${entry.updated_by ? ` · ${escapeHtml(entry.updated_by)}` : ""}</small><p>${escapeHtml(entry.note)}</p></div></details>` : ""}</div>
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
      <section class="aud-section audit-summary"><div class="section-title-row"><h3>Current audit</h3>${!data.deferred_loading && issues.length ? `<span class="audit-missing-count">${issues.length} missing</span>` : ""}</div>${missing}${misplacedHtml}</section>
      <section class="aud-section progress-section"><div class="section-title-row"><h3>Job requirements</h3>
        <span class="progress-label">${progress.counts?.overdue || 0} overdue · ${progress.counts?.blocked || 0} blocked · ${progress.percent_complete || 0}% complete</span></div>
        <div class="requirement-progress"><i style="width:${Math.max(0, Math.min(100, progress.percent_complete || 0))}%"></i></div>${required}</section>
      <section class="aud-section"><div class="section-title-row"><div><h3>Work on this job</h3><small>Choose every division involved; each one tracks its own status</small></div></div><div class="work-types">${workTypes}</div></section>
      <section class="aud-section checklist-section"><div class="section-title-row"><div><h3>Checklists</h3><small>${escapeHtml(selectedDivision)} card · stored in Linguar Hub · Trello sync is temporary</small></div>${checklistDivisionTabs}</div>${checklistGroups}</section>
      ${facts || `<section class="aud-section"><h3>Job information</h3><div class="aud-empty">No saved job information yet.</div></section>`}
      ${oldJobsSection}
      <section class="aud-section signatures-section"><div class="section-title-row"><div><h3>Documents &amp; signatures</h3><small>DocuSign sends · job folder keeps the completed files</small></div><span class="signature-state state-${escapeAttr((dsRequest.state || "not_sent").replaceAll("_", "-"))}">${escapeHtml(signatureState)}</span></div>
        <div class="signature-flow"><span class="${dsRequest.requested ? "done" : "active"}">1 Prepare</span><i></i><span class="${dsRequest.requested ? "active" : ""}">2 Send</span><i></i><span class="${(docs.files || []).some((file) => file.signed) ? "done" : ""}">3 Signed copy</span></div>
        ${dsRequest.email ? `<div class="signature-recipient">Sent to <strong>${escapeHtml(dsRequest.email)}</strong> · ${Number(dsRequest.days_pending || 0)} day(s) pending</div>` : ""}
        ${!docs.connected ? `<div class="signature-connection"><span><strong>Direct DocuSign connection is next</strong><small>For now, open DocuSign and mark the request sent after the envelope is actually sent.</small></span></div>` : ""}
        <div class="signature-actions"><button class="btn btn-primary" data-open-docusign>Open DocuSign ↗</button><button class="btn" data-mark-docusign-sent ${dsRequest.state ? "disabled" : ""}>Mark envelope sent</button><button class="btn" data-open-docs-folder ${res.path ? "" : "disabled"}>Open job folder</button></div>
        <div class="signature-files">${documentRows}</div></section>
      <section class="aud-section photo-report-section"><div class="section-title-row"><div><h3>Photo reports</h3><small>Build in CompanyCam or generate a standardized report from job photos</small></div><span class="report-division">${escapeHtml(selectedDivision)}</span></div>
        <div class="photo-report-route"><div class="report-route-mark">CC</div><div><strong>CompanyCam editor</strong><small>Opens the matched project in a Linguar Hub window. In CompanyCam, choose Documents → Reports.</small></div>
          <button class="btn btn-primary" data-companycam-report>Create in CompanyCam</button></div>
        <div class="photo-report-route is-quick"><div class="report-route-mark">PDF</div><div><strong>Quick Photo Report</strong><small>Choose stage, dates, and photos; the finished PDF files into this job’s DOCS folder.</small></div>
          <button class="btn" data-quick-photo-report>Build quick report</button></div>
        <div class="photo-report-status" data-photo-report-status></div></section>
      <section class="aud-section job-log-section"><div class="section-title-row"><div><h3>Job Log</h3><small>Structured updates used to build the Snapshot</small></div>
        <div class="section-actions">${data.card_id ? `<button class="btn compact" data-import-job-log>Refresh from ${escapeHtml(selectedDivision)} Trello</button>` : ""}<button class="btn btn-primary compact" data-add-job-log>+ Add update</button></div></div>
        <div class="job-log-editor" data-job-log-editor hidden></div><div data-job-log-list>${logs}</div></section>
      <details class="aud-section compact-section"><summary>Run activity <span>${(res.activity || []).length}</span></summary>${activity}</details>
      <details class="aud-section compact-section"><summary>Other attachments <span>${(data.attachments || []).length}</span></summary>${attachments}</details>
    </div>
    <aside class="job-card-activity"><div class="activity-head"><div><h3>Comments and activity</h3><small>${escapeHtml(selectedDivision)} Trello card</small></div>
      <span>${(data.comments || []).length}</span></div>
      <div class="comment-stream" data-comment-stream>${comments}</div>
      <div class="comment-compose"><textarea data-comment-input name="job-comment" rows="3" aria-label="Job comment" autocomplete="off" placeholder="Write an update for this job…"></textarea>
        <div><span data-comment-state></span><button class="btn btn-primary" data-post-comment>Add comment</button></div></div>
    </aside></div>`;
  const w = document.createElement("div");
  w.className = "modal-scrim audit-overlay";
  w.innerHTML = `
    <div class="modal-box audit-card" role="dialog" aria-modal="true" aria-label="Job audit" tabindex="-1">
      <header class="modal-head">
        <div class="audit-head-main"><div class="audit-head-copy"><div class="modal-title-row"><div class="modal-title">${escapeHtml(data.client || res.client || "")}</div><button type="button" class="client-page-link" data-open-client-page>👤 Client page</button></div>
        <div class="modal-sub">${claimNumber ? `Claim ${escapeHtml(claimNumber)} · ` : ""}${escapeHtml(crm.lifecycle_stage ? crm.lifecycle_stage.replaceAll("_", " ") : "Job audit")} · ${clean ? "ready" : issues.length + " item(s) need attention"}${res.aging ? " · " + res.aging + " days" : ""}</div>${divisionDataTabs}</div>
        <div class="workspace-load-state" data-workspace-load-state>${data.deferred_loading ? "Loading live details…" : `<button class="btn compact" type="button" data-refresh-workspace>Refresh live</button>`}</div>
        <button class="audit-close" data-close aria-label="Close job audit">×</button></div>
        <div class="card-quick-actions" aria-label="Job actions">
          <div class="quick-primary-actions">
            <button class="action-btn primary" data-add-job-log><span class="quick-action-icon">＋</span>Add update</button>
            <details class="copy-quick-menu"><summary class="action-btn copy-trigger">📋 Copy <small>⌄</small></summary><div class="copy-menu-panel"><header><strong>Copy job details</strong><small>Uses the saved Job Info record</small></header>${visibleCopyOptions.map(([label, value]) => `<button data-copy-value="${escapeAttr(value)}"><span>${escapeHtml(label.replace("Customer ", ""))}</span><small>${escapeHtml(value)}</small></button>`).join("")}<button class="copy-summary-row" data-copy-summary><span>Job summary</span><small>Copy all available details</small></button></div></details>
            <button class="action-btn" data-quick-photo-report>Photo report</button>
          </div>
          <div class="quick-destination-actions" aria-label="Open job in">
            <button class="action-btn" ${res.path ? "data-open-docs-folder" : "data-link-job-folder"}>${res.path ? "📁 Folder" : "🔗 Link folder"}</button>
            <button class="action-btn destination" data-open-trello ${trelloUrl ? "" : "disabled"}><img src="../web_shared/trello.png" alt="">Trello</button>
            <button class="action-btn destination" data-open-xa ${data.card_id ? "" : "disabled"}><img src="../web_shared/xactanalysis.png" alt="">XA</button>
            <button class="action-btn destination" data-open-companycam ${data.card_id ? "" : "disabled"}><img src="../web_shared/companycam.png" alt="">CompanyCam</button>
          </div>
          <div class="quick-utility-actions">
            <button class="action-btn quiet" data-stage-xa ${res.path ? "" : "disabled"}>Stage for XA</button>
            <button class="action-btn quiet" data-open-audit>All actions</button>
          </div>
        </div>
      </header>
      <div class="modal-body">${body}</div>
      <footer class="modal-foot">
        <div class="visible-job-actions"><span class="footer-job-context">${escapeHtml(selectedDivision)} · ${claimNumber ? `Claim ${escapeHtml(claimNumber)}` : "Job workspace"}</span></div>
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
  w.querySelector("[data-open-client-page]")?.addEventListener("click", () => {
    const client = data.client || res.client || "";
    close(true);
    if (window.emsNavigateTo) window.emsNavigateTo("audit", client);
  });
  w.querySelectorAll("[data-division-data]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.divisionData === selectedDivision) return;
    if (!close()) return;
    await onAuditCard(data.client || res.client || "", "", "", button.dataset.divisionData || "EMS");
  }));
  w.querySelectorAll("[data-checklist-division]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.checklistDivision === selectedDivision) return;
    if (!close()) return;
    await onAuditCard(data.client || res.client || "", "", "", button.dataset.checklistDivision || "EMS");
  }));
  w.querySelectorAll("[data-open-trello]").forEach((button) => button.addEventListener("click", () => {
    if (trelloUrl) pywebview.api.open_url(trelloUrl);
  }));
  w.querySelector("[data-open-xa]")?.addEventListener("click", async () => {
    const ok = await pywebview.api.open_xa_link(data.client || res.client || "", data.card_id || "");
    if (!ok) setStatus("No XactAnalysis link is saved for this job", "warn");
  });
  w.querySelector("[data-open-companycam]")?.addEventListener("click", async () => {
    const ok = await pywebview.api.open_companycam_link(data.client || res.client || "");
    if (!ok) setStatus("No CompanyCam project is linked to this job", "warn");
  });
  w.querySelector("[data-link-job-folder]")?.addEventListener("click", () =>
    openJobFolderLinkModal(data, close));
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
  const refreshAfterRequirement = async () => {
    const refreshed = await pywebview.api.refresh_job_card_workspace(
      data.client || res.client || "", data.card_id || "", data.selected_division || "EMS");
    if (refreshed?.ok) {
      close(true);
      openAuditModal(refreshed, refreshed.selected_trello_url || trelloUrl);
    }
    return refreshed;
  };
  const showRequirementUndo = (item, previousState) => {
    document.querySelector(".requirement-undo")?.remove();
    const undo = document.createElement("div");
    undo.className = "requirement-undo";
    undo.innerHTML = `<span><strong>Requirement completed</strong><small>${escapeHtml(item.label || "")}</small></span><button type="button">Undo</button>`;
    document.body.appendChild(undo);
    const timer = window.setTimeout(() => undo.remove(), 7000);
    undo.querySelector("button").addEventListener("click", async () => {
      window.clearTimeout(timer);
      undo.querySelector("button").disabled = true;
      const result = await pywebview.api.set_job_requirement(
        data.client || res.client || "", item.key, previousState || "todo", "Undo completion", {});
      undo.remove();
      if (result?.ok) {
        document.querySelector(".audit-overlay [data-close]")?.click();
        await onAuditCard(data.client || res.client || "", data.card_id || "", "",
          data.selected_division || "EMS");
      }
      else setStatus(`Undo failed: ${result?.error || "unknown error"}`, "error");
    });
  };
  const editRequirement = (key) => {
    const item = (progress.items || []).find((entry) => entry.key === key);
    if (!item) return;
    const dateValue = (value) => value ? String(value).slice(0, 16) : "";
    const editor = document.createElement("div");
    editor.className = "requirement-editor-scrim";
    editor.innerHTML = `<form class="requirement-editor" aria-label="Update job requirement">
      <div><span class="requirement-mark req-preview">${item.status === "completed" ? "✓" : item.status === "not_applicable" ? "—" : item.status === "blocked" ? "×" : "○"}</span>
      <div><h4>${escapeHtml(item.label || "Requirement")}</h4><small>${escapeHtml(item.introduced_stage_label || "")} · ${escapeHtml(item.importance || "required")}</small></div></div>
      <div class="requirement-editor-grid">
        <label>Status<select name="state">
          ${[["todo","To do"],["in_progress","In progress"],["blocked","Blocked"],["completed","Complete"],["not_applicable","Not applicable"]].map(([value,label]) => `<option value="${value}" ${item.status === value ? "selected" : ""}>${label}</option>`).join("")}
        </select></label>
        <label>Assigned to<input name="assignee" value="${escapeAttr(item.assignee || "")}" placeholder="Person or role"></label>
        <label>Due date<input type="datetime-local" name="due_at" value="${escapeAttr(dateValue(item.due_at))}"></label>
        <label data-blocked-field>Follow-up date<input type="datetime-local" name="follow_up_at" value="${escapeAttr(dateValue(item.follow_up_at))}"></label>
      </div>
      <label data-blocked-field>Blocked reason<input name="blocked_reason" value="${escapeAttr(item.blocked_reason || "")}" placeholder="What are we waiting for?"></label>
      <label>Note<textarea name="note" rows="3" placeholder="Required for N/A; optional otherwise">${escapeHtml(item.manual_note || "")}</textarea></label>
      ${(item.history || []).length ? `<details class="requirement-change-history"><summary>Change history <span>${item.history.length}</span></summary>
        <div>${[...(item.history || [])].reverse().map((entry) => `<p><strong>${escapeHtml((entry.state || "todo").replaceAll("_", " "))}</strong><span>${escapeHtml(entry.actor || "User")} · ${escapeHtml(formatCommentDate(entry.at || ""))}</span>${entry.note ? `<small>${escapeHtml(entry.note)}</small>` : ""}</p>`).join("")}</div></details>` : ""}
      <div class="requirement-editor-actions">
        <button type="button" class="btn" data-requirement-cancel>Cancel</button>
        <button type="submit" class="btn btn-primary">Save changes</button>
      </div></form>`;
    w.querySelector(".audit-card")?.appendChild(editor);
    const dismiss = () => editor.remove();
    editor.addEventListener("click", (event) => { if (event.target === editor) dismiss(); });
    editor.querySelector("[data-requirement-cancel]").addEventListener("click", dismiss);
    const stateSelect = editor.querySelector('[name="state"]');
    const updateBlockedFields = () => editor.querySelectorAll("[data-blocked-field]").forEach((field) =>
      field.classList.toggle("field-muted", stateSelect.value !== "blocked"));
    stateSelect.addEventListener("change", updateBlockedFields);
    updateBlockedFields();
    stateSelect.focus();
    editor.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      editor.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      const details = {
        assignee: editor.querySelector('[name="assignee"]').value,
        due_at: editor.querySelector('[name="due_at"]').value,
        follow_up_at: editor.querySelector('[name="follow_up_at"]').value,
        blocked_reason: editor.querySelector('[name="blocked_reason"]').value,
        importance: item.importance || "required",
      };
      const result = await pywebview.api.set_job_requirement(
        data.client || res.client || "", item.key, stateSelect.value,
        editor.querySelector("textarea")?.value || "", details);
      if (!result?.ok) {
        editor.querySelectorAll("button").forEach((button) => { button.disabled = false; });
        setStatus(`Requirement update failed: ${result?.error || "unknown error"}`, "error");
        return;
      }
      dismiss();
      setStatus("Requirement updated", "ok");
      await refreshAfterRequirement();
    });
  };
  w.querySelectorAll("[data-requirement-key]").forEach((button) =>
    button.addEventListener("click", () => editRequirement(button.dataset.requirementKey || "")));
  w.querySelectorAll("[data-requirement-complete]").forEach((button) =>
    button.addEventListener("click", async () => {
      const item = (progress.items || []).find((entry) => entry.key === button.dataset.requirementComplete);
      if (!item) return;
      if (!(["todo", "in_progress"].includes(item.status))) {
        editRequirement(item.key);
        return;
      }
      button.disabled = true;
      button.textContent = "✓";
      const result = await pywebview.api.set_job_requirement(
        data.client || res.client || "", item.key, "completed", "", {});
      if (!result?.ok) {
        button.disabled = false;
        button.textContent = item.status === "in_progress" ? "◐" : "○";
        setStatus(`Requirement update failed: ${result?.error || "unknown error"}`, "error");
        return;
      }
      const previousState = result.previous_state || item.status;
      await refreshAfterRequirement();
      showRequirementUndo(item, previousState);
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
  w.querySelector("[data-companycam-report]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const status = w.querySelector("[data-photo-report-status]");
    button.disabled = true; button.textContent = "Finding project…";
    status.textContent = "Matching this job to CompanyCam…";
    const result = await pywebview.api.open_companycam_report_editor(
      data.client || res.client || "", res.path || "", selectedDivision);
    button.disabled = false; button.textContent = "Create in CompanyCam";
    if (!result?.ok) {
      status.textContent = result?.error || "CompanyCam could not be opened.";
      status.className = "photo-report-status error";
      return;
    }
    status.textContent = result.docs_folder
      ? `CompanyCam opened · finished PDF belongs in ${result.docs_folder}`
      : "CompanyCam opened · choose Documents → Reports to build the report.";
    status.className = "photo-report-status ok";
  });
  w.querySelector("[data-quick-photo-report]")?.addEventListener("click", () =>
    openQuickPhotoReportModal(data.client || res.client || "", res.path || "", selectedDivision));
  w.querySelectorAll("[data-open-docs-folder]").forEach((button) => button.addEventListener("click", () => pywebview.api.open_job_folder(data.client || "", res.path || "")));
  w.querySelectorAll("[data-open-old-job]").forEach((button) => button.addEventListener("click", () => pywebview.api.open_url(button.dataset.openOldJob)));
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
  w.querySelectorAll("[data-add-job-log]").forEach((button) => button.addEventListener("click", () => openJobLogEditor({})));
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

function showMoveUndo(drag, toListId, toLane) {
  if (!drag?.fromListId || drag.fromListId === toListId) return;
  document.querySelector(".move-undo")?.remove();
  const undo = document.createElement("div");
  undo.className = "requirement-undo move-undo";
  undo.innerHTML = `<span><strong>Job moved to ${escapeHtml(toLane)}</strong><small>${escapeHtml(drag.name || "Job")}</small></span><button type="button">Undo</button>`;
  document.body.appendChild(undo);
  const timer = window.setTimeout(() => undo.remove(), 9000);
  undo.querySelector("button").addEventListener("click", async () => {
    window.clearTimeout(timer);
    const button = undo.querySelector("button");
    button.disabled = true; button.textContent = "Undoing…";
    const result = await pywebview.api.move_card(drag.cardId, drag.fromListId);
    if (!result?.ok) { setStatus(`Undo failed: ${result?.error || "?"}`, "error"); undo.remove(); return; }
    moveCardLocally(drag.cardId, toListId, drag.fromListId, drag.fromLane || "Previous lane");
    renderBoard(); undo.remove(); setStatus(`Returned “${drag.name}” to ${drag.fromLane || "its previous lane"}`, "ok");
  });
}

// ── Persistent Job Shelf ─────────────────────────────────────────
function isJobShelved(cardId) {
  return state.jobShelf.some((item) => item.cardId === cardId);
}

function isJobStarred(cardId) {
  return state.jobShelf.some((item) => item.cardId === cardId && item.mode === "starred");
}

function shelfEntryFromCard(cardEl) {
  const lane = cardEl.closest(".lane");
  return {
    cardId: cardEl.dataset.cardId || "",
    name: cardEl.dataset.client || "(no name)",
    url: cardEl.dataset.url || "",
    fromListId: cardEl.dataset.listId || "",
    lane: lane?.dataset.laneName || "",
    boardKey: lane?.dataset.boardKey || state.activeBoardKey || "",
    summary: cardEl.dataset.cardSummary || "",
  };
}

function persistJobShelf() {
  PanelState.set({ jobShelf: state.jobShelf });
}

function reconcileJobShelfWithBoard() {
  if (!state.jobShelf.length) return;
  let changed = false;
  for (const item of state.jobShelf) {
    let match = null;
    for (const board of state.board.boards || []) {
      for (const lane of board.lanes || []) {
        const card = (lane.cards || []).find((candidate) => candidate.card_id === item.cardId);
        if (card) { match = { board, lane, card }; break; }
      }
      if (match) break;
    }
    if (!match) continue;
    const actualListId = match.lane.list_id;
    const heldConflict = item.mode === "held" && Boolean(item.fromListId) && item.fromListId !== actualListId;
    const next = {
      name: match.card.client || item.name,
      url: match.card.url || item.url,
      boardKey: match.board.key,
      conflict: heldConflict,
      actualListId: heldConflict ? actualListId : "",
      actualLane: heldConflict ? match.lane.name : "",
    };
    if (item.mode !== "held") {
      next.fromListId = actualListId;
      next.lane = match.lane.name;
    }
    for (const [key, value] of Object.entries(next)) {
      if (item[key] !== value) { item[key] = value; changed = true; }
    }
  }
  if (changed) { persistJobShelf(); renderJobShelf(); }
}

function addToJobShelf(entry, mode = "starred") {
  if (!entry?.cardId) return;
  const index = state.jobShelf.findIndex((item) => item.cardId === entry.cardId);
  const next = { ...entry, mode };
  if (index >= 0) state.jobShelf[index] = { ...state.jobShelf[index], ...next };
  else state.jobShelf.push(next);
  persistJobShelf(); renderJobShelf();
  setStatus(mode === "held"
    ? `Held ${entry.name} on the Job Shelf · drag it to a lane to place it`
    : `★ ${entry.name} starred for quick access`, "ok");
}

function removeFromJobShelf(cardId) {
  state.jobShelf = state.jobShelf.filter((item) => item.cardId !== cardId);
  persistJobShelf(); renderJobShelf(); renderBoard();
}

function clearJobShelf() {
  state.jobShelf = [];
  persistJobShelf(); renderJobShelf(); renderBoard();
  setStatus("Job Shelf cleared", "ok");
}

function toggleCardShelf(cardEl) {
  const entry = shelfEntryFromCard(cardEl);
  if (isJobStarred(entry.cardId)) removeFromJobShelf(entry.cardId);
  else { addToJobShelf(entry, "starred"); renderBoard(); }
}

function showShelfForDrag() {
  const shelf = $("#job-shelf");
  shelf.classList.remove("hidden");
  shelf.classList.add("drag-visible");
}

function hideShelfAfterDrag() {
  const shelf = $("#job-shelf");
  shelf.classList.remove("drag-visible", "drop-ready");
  if (!state.jobShelf.length) shelf.classList.add("hidden");
}

function onShelfDragOver(event) {
  if (!state.drag || state.drag.source === "shelf") return;
  event.preventDefault();
  try { event.dataTransfer.dropEffect = "copy"; } catch (_) {}
  event.currentTarget.classList.add("drop-ready");
}

function onShelfDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget))
    event.currentTarget.classList.remove("drop-ready");
}

function onShelfDrop(event) {
  event.preventDefault();
  const drag = state.drag;
  event.currentTarget.classList.remove("drop-ready");
  if (!drag || drag.source === "shelf") return;
  holdDraggedCard(drag);
}

function holdDraggedCard(drag) {
  if (!drag || drag.source === "shelf") return;
  const live = document.querySelector(`.kcard[data-card-id="${cssEsc(drag.cardId)}"]`);
  addToJobShelf(live ? shelfEntryFromCard(live) : {
    cardId: drag.cardId, name: drag.name, url: drag.url,
    fromListId: drag.fromListId, summary: drag.summary,
  }, "held");
  state.drag = null;
  hideShelfAfterDrag();
  renderBoard();
  setStatus(`Held “${drag.name}” locally · Trello stays in its current lane until you place it`, "ok");
}

function renderJobShelf() {
  const shelf = $("#job-shelf");
  const track = $("#job-shelf-track");
  if (!shelf || !track) return;
  const heldCount = state.jobShelf.filter((item) => item.mode === "held").length;
  const starredCount = state.jobShelf.length - heldCount;
  $("#job-shelf-count").textContent = `${heldCount} held · ${starredCount} starred`;
  $("#job-shelf-clear").hidden = !state.jobShelf.length;
  const fanCenter = (state.jobShelf.length - 1) / 2;
  track.innerHTML = state.jobShelf.map((item, index) => {
    const offset = index - fanCenter;
    const angle = Math.max(-13, Math.min(13, offset * 4));
    const drop = Math.min(18, Math.abs(offset) * 4);
    return `
    <article class="shelf-card mode-${escapeAttr(item.mode || "starred")} ${item.conflict ? "has-conflict" : ""}" draggable="true" data-shelf-card="${escapeAttr(item.cardId)}"
      data-list-id="${escapeAttr(item.fromListId || "")}" style="--fan-angle:${angle}deg;--fan-drop:${drop}px;--fan-z:${index + 1}"
      title="${item.mode === "held" ? "Held locally — drag to a lane to update Trello" : "Starred quick look — original stays in its lane"}">
      <span class="shelf-corner" aria-hidden="true">${item.mode === "held" ? "↗" : "★"}</span>
      <button class="shelf-open" type="button" draggable="false"><strong>${escapeHtml(item.name)}</strong><span>${item.conflict ? `⚠ Trello moved to ${escapeHtml(item.actualLane || "another lane")}` : (item.mode === "held" ? "In hand · Trello unchanged" : "★ Quick look · stays in lane")}${item.lane && !item.conflict ? ` · ${escapeHtml(item.lane)}` : ""}</span></button>
      <button class="shelf-remove" type="button" aria-label="Remove ${escapeAttr(item.name)} from Job Shelf">×</button>
    </article>`;
  }).join("");
  shelf.classList.toggle("hidden", !state.jobShelf.length && !shelf.classList.contains("drag-visible"));
  track.querySelectorAll(".shelf-card").forEach((card) => {
    const item = state.jobShelf.find((entry) => entry.cardId === card.dataset.shelfCard);
    card.querySelector(".shelf-open").addEventListener("click", () =>
      onAuditCard(item.name, item.cardId, item.url || ""));
    card.querySelector(".shelf-remove").addEventListener("click", () => removeFromJobShelf(item.cardId));
    card.addEventListener("dragstart", (event) => {
      state.drag = { cardId: item.cardId, name: item.name,
        fromListId: item.actualListId || item.fromListId || card.dataset.listId,
        fromLane: item.actualLane || item.lane || "", url: item.url || "",
        summary: item.summary || "", source: "shelf", conflict: Boolean(item.conflict), actualLane: item.actualLane || "" };
      card.classList.add("dragging");
      try { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", item.cardId); } catch (_) {}
    });
    card.addEventListener("dragend", () => { card.classList.remove("dragging"); state.drag = null; });
  });
}

function openQuickPhotoReportModal(client, jobPath, division) {
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay quick-report-overlay";
  modal.innerHTML = `<div class="modal-box quick-report-modal" role="dialog" aria-modal="true" aria-label="Quick Photo Report">
    <header class="modal-head"><div><div class="modal-title">Quick Photo Report</div><div class="modal-sub">${escapeHtml(client)} · ${escapeHtml(division)} · CompanyCam photos</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body">
      <section class="quick-report-step"><div class="quick-report-step-head"><span>1</span><div><strong>Set up the report</strong><small>Use dates or a CompanyCam tag only when you need to narrow the job photos.</small></div></div><div class="quick-report-controls">
        <label><span>Report</span><select data-report-type><option>Initial Photo Report</option><option>Daily Monitoring Report</option><option>Progress Photo Report</option><option>Final Photo Report</option><option>Contents Photo Report</option><option>Reconstruction Photo Report</option></select></label>
        <label><span>From</span><input type="date" data-report-start value="${monthAgo}"></label>
        <label><span>Through</span><input type="date" data-report-end value="${today}"></label>
        <label><span>CompanyCam tag</span><input data-report-tag placeholder="Optional: Initial, Demo, Kitchen…"></label>
        <button class="btn btn-primary" type="button" data-preview-report>Find photos</button>
      </div></section>
      <section class="quick-report-step gallery-step"><div class="quick-report-step-head"><span>2</span><div><strong>Review and select photos</strong><small>Open any photo full-size, then keep exactly what belongs in the PDF.</small></div></div>
      <div class="quick-report-message" data-report-message>Select dates and find the CompanyCam photos for this report.</div>
      <div class="quick-report-gallery-tools" data-gallery-tools hidden><button class="text-btn" data-select-loaded>Select loaded</button><button class="text-btn" data-clear-selection>Clear selection</button><span data-gallery-count></span></div>
      <div class="quick-report-photos" data-report-photos></div>
      <button class="btn quick-report-more" data-load-more hidden>Load more photos</button>
      </section>
    </div>
    <footer class="modal-foot quick-report-foot"><span class="quick-report-step-number">3</span><div><strong>Generate the PDF</strong><small data-report-selection>0 selected</small></div><i></i><button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-generate-report disabled>Generate PDF</button></footer>
  </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => { if (event.target === modal) close(); });
  const photosHost = modal.querySelector("[data-report-photos]");
  const message = modal.querySelector("[data-report-message]");
  const generate = modal.querySelector("[data-generate-report]");
  const selection = modal.querySelector("[data-report-selection]");
  let generatedPath = "";
  let loadedPhotos = [];
  let selectedIds = new Set();
  let totalPhotos = 0;
  const filters = () => ({
    start: modal.querySelector("[data-report-start]").value,
    end: modal.querySelector("[data-report-end]").value,
    tag: modal.querySelector("[data-report-tag]").value.trim(),
  });
  const updateSelection = () => {
    const count = selectedIds.size;
    selection.textContent = `${count} selected`;
    generate.disabled = count === 0;
  };
  const renderLoadedPhotos = () => {
    photosHost.innerHTML = loadedPhotos.map((photo) => `<article class="quick-report-photo ${selectedIds.has(photo.id) ? "is-selected" : ""}" data-photo-id="${escapeAttr(photo.id)}"><label><input type="checkbox" value="${escapeAttr(photo.id)}" ${selectedIds.has(photo.id) ? "checked" : ""}><span class="sr-only">Include photo</span></label><button type="button" class="quick-report-preview" data-preview-photo="${escapeAttr(photo.id)}"><img src="${escapeAttr(photo.preview_url || photo.url)}" alt="View full-size jobsite photo"></button><span><strong>${escapeHtml(photo.description || "Jobsite photo")}</strong><small>${escapeHtml([photo.date, photo.creator, (photo.tags || []).join(", ")].filter(Boolean).join(" · "))}</small></span></article>`).join("");
    photosHost.querySelectorAll("input").forEach((input) => input.addEventListener("change", () => {
      if (input.checked) selectedIds.add(input.value); else selectedIds.delete(input.value);
      input.closest(".quick-report-photo")?.classList.toggle("is-selected", input.checked);
      updateSelection();
    }));
    photosHost.querySelectorAll("[data-preview-photo]").forEach((button) => button.addEventListener("click", () => {
      const photo = loadedPhotos.find((item) => item.id === button.dataset.previewPhoto);
      if (!photo) return;
      const viewer = document.createElement("div");
      viewer.className = "photo-lightbox";
      viewer.innerHTML = `<button type="button" aria-label="Close photo">×</button><img src="${escapeAttr(photo.url)}" alt=""><div><strong>${escapeHtml(photo.description || "Jobsite photo")}</strong><small>${escapeHtml([photo.date, photo.creator, (photo.tags || []).join(", ")].filter(Boolean).join(" · "))}</small></div>`;
      modal.appendChild(viewer);
      viewer.addEventListener("click", (event) => { if (event.target === viewer || event.target.closest("button")) viewer.remove(); });
    }));
    modal.querySelector("[data-gallery-count]").textContent = `${loadedPhotos.length} of ${totalPhotos} shown`;
    modal.querySelector("[data-gallery-tools]").hidden = loadedPhotos.length === 0;
    updateSelection();
  };
  const loadPhotos = async (reset = false) => {
    const button = reset ? modal.querySelector("[data-preview-report]") : modal.querySelector("[data-load-more]");
    const f = filters();
    if (reset) { loadedPhotos = []; selectedIds = new Set(); totalPhotos = 0; photosHost.innerHTML = ""; }
    button.disabled = true; button.textContent = "Reading CompanyCam…";
    message.textContent = "Loading project photos and tags…";
    const result = await pywebview.api.companycam_quick_report_plan(client, jobPath, division, f.start, f.end, f.tag, loadedPhotos.length, 120);
    button.disabled = false; button.textContent = reset ? "Find photos" : "Load more photos";
    if (!result?.ok) { message.textContent = result?.error || "Photos could not be loaded."; message.className = "quick-report-message error"; return; }
    const photos = result.photos || [];
    loadedPhotos.push(...photos);
    photos.forEach((photo) => selectedIds.add(photo.id));
    totalPhotos = Number(result.total || loadedPhotos.length);
    message.textContent = loadedPhotos.length ? `${totalPhotos} matching photos · open any photo to inspect it, then check exactly what belongs in the PDF` : "No photos match these dates and tag.";
    message.className = "quick-report-message";
    modal.querySelector("[data-load-more]").hidden = !result.has_more;
    renderLoadedPhotos();
  };
  modal.querySelector("[data-preview-report]").addEventListener("click", () => loadPhotos(true));
  modal.querySelector("[data-load-more]").addEventListener("click", () => loadPhotos(false));
  modal.querySelector("[data-select-loaded]").addEventListener("click", () => { loadedPhotos.forEach((photo) => selectedIds.add(photo.id)); renderLoadedPhotos(); });
  modal.querySelector("[data-clear-selection]").addEventListener("click", () => { selectedIds.clear(); renderLoadedPhotos(); });
  generate.addEventListener("click", async () => {
    if (generatedPath) { pywebview.api.open_document(generatedPath); return; }
    const f = filters();
    const ids = Array.from(selectedIds);
    generate.disabled = true; generate.textContent = "Building PDF…";
    message.textContent = `Downloading and formatting ${ids.length} photos…`;
    const result = await pywebview.api.generate_companycam_quick_report(
      client, jobPath, division, modal.querySelector("[data-report-type]").value,
      ids, f.start, f.end, f.tag);
    if (!result?.ok) { generate.disabled = false; generate.textContent = "Generate PDF"; message.textContent = result?.error || "The report could not be generated."; message.className = "quick-report-message error"; return; }
    message.textContent = `Created ${result.filename} with ${result.photos} photos.`;
    message.className = "quick-report-message ok";
    generatedPath = result.path || "";
    generate.textContent = "Open PDF"; generate.disabled = false;
    setStatus(`Photo report saved to ${result.docs_folder}`, "ok");
  });
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
    <header class="modal-head"><div><div class="modal-title">Stage for XA</div><div class="modal-sub">${escapeHtml(client)} · choose a PICS folder</div></div><button class="audit-close" data-close aria-label="Close Stage for XA">×</button></header>
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
    ${comment?.id && comment?.can_manage ? `<span><button class="text-btn" data-comment-edit>Edit</button><button class="text-btn danger" data-comment-delete>Delete</button></span>` : ""}</footer></div></article>`;
}

function formatCommentDate(value) {
  if (!value) return "now";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : `${formatAppDate(d)} at ${d.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"})}`;
}

async function openJobFolderLinkModal(data, closeWorkspace) {
  const client = data.client || data.audit?.client || "";
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay";
  modal.innerHTML = `<div class="modal-box folder-link-modal" role="dialog" aria-modal="true" aria-label="Link OD job folder">
    <header class="modal-head"><div><div class="modal-title">Link OD job folder</div><div class="modal-sub">${escapeHtml(client)} · this folder becomes the job's saved file location</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body"><div class="folder-link-tools"><input type="search" data-folder-filter placeholder="Filter folder names…" aria-label="Filter folder names"><button class="btn" data-all-years>Search all years</button></div>
      <div class="folder-link-message" data-folder-message>Finding the best matching folders…</div><div class="folder-link-list" data-folder-list></div></div>
    <footer class="modal-foot"><small>Pick the actual job folder—not EMS, DOCS, or PICS inside it.</small><button class="btn" data-close>Cancel</button></footer></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => { if (event.target === modal) close(); });
  const list = modal.querySelector("[data-folder-list]");
  const message = modal.querySelector("[data-folder-message]");
  const filter = modal.querySelector("[data-folder-filter]");
  let candidates = [];
  const render = () => {
    const query = (filter.value || "").trim().toLowerCase();
    const shown = candidates.filter((item) => !query || `${item.name} ${item.parent || ""} ${item.year || ""}`.toLowerCase().includes(query)).slice(0, 60);
    list.innerHTML = shown.map((item) => `<button class="folder-link-row" data-folder-path="${escapeAttr(item.path || "")}"><span><strong>${escapeHtml(item.name || "Job folder")}</strong><small>${escapeHtml([item.parent, item.year_folder || item.year].filter(Boolean).join(" · "))}</small></span><b>Link folder</b></button>`).join("") || `<div class="aud-empty">No matching folders. Search all years or change the filter.</div>`;
    list.querySelectorAll("[data-folder-path]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true; button.querySelector("b").textContent = "Linking…";
      let result = await pywebview.api.link_job_folder(client, button.dataset.folderPath || "", false);
      if (result?.needs_confirm && window.confirm(`${result.warning}\n\nLink this folder anyway?`)) {
        result = await pywebview.api.link_job_folder(client, button.dataset.folderPath || "", true);
      }
      if (!result?.ok) {
        button.disabled = false; button.querySelector("b").textContent = "Link folder";
        message.textContent = result?.error || result?.warning || "Folder could not be linked";
        message.className = "folder-link-message error";
        return;
      }
      close(); closeWorkspace(true);
      setStatus(`Linked OD folder to ${client}`, "ok");
      await onAuditCard(client, data.card_id || "", "", data.selected_division || "EMS");
    }));
  };
  const load = async (scope = "") => {
    message.textContent = scope === "all" ? "Searching every job year…" : "Finding current-year job folders…";
    message.className = "folder-link-message";
    const result = await pywebview.api.list_job_folder_candidates(client, scope);
    if (!result?.ok) {
      message.textContent = result?.error || "Job folders could not be read";
      message.className = "folder-link-message error"; candidates = []; render(); return;
    }
    candidates = result.candidates || [];
    message.textContent = `${candidates.length} folders found · best matches first`;
    render();
  };
  filter.addEventListener("input", render);
  modal.querySelector("[data-all-years]").addEventListener("click", () => load("all"));
  filter.focus();
  await load("");
}

function formatAppDate(value) {
  if (!value) return "";
  const d = value instanceof Date ? value : new Date(String(value).match(/^\d{4}-\d{2}-\d{2}$/) ? `${value}T12:00:00` : value);
  if (Number.isNaN(d.getTime())) return String(value);
  const two = (number) => String(number).padStart(2, "0");
  return `${two(d.getMonth() + 1)}-${two(d.getDate())}-${two(d.getFullYear() % 100)}`;
}

function fmtDue(iso) {
  return formatAppDate(iso);
}

// ════════════════════════════════════════════════════════════════
//  STAGES TABLE VIEW  (lifecycle — read-only from ems_db)
// ════════════════════════════════════════════════════════════════
async function loadStages() {
  if (stagesLoadPromise) return stagesLoadPromise;
  stagesLoadPromise = loadStagesOnce();
  try { return await stagesLoadPromise; }
  finally { stagesLoadPromise = null; }
}

async function loadStagesOnce() {
  setStatus("Loading lifecycle…");
  $("#loading-state")?.classList.remove("hidden");
  try {
    const result = await withTimeout(
      pywebview.api.lifecycle_view(false), 15000,
      "Lifecycle took too long to respond"
    );
    if (!result?.ok) throw new Error(result?.error || "Lifecycle returned no data");
    state.stages = result.stages || [];
    state.rows = result.rows || [];
    state.stage_counts = result.counts || {};
    state.stage_render_limit = 350;
    renderChips();
    renderTable();
    setStatus(`✓ ${state.rows.length} lifecycle jobs loaded`, "ok");
  } catch (ex) {
    showStagesLoadError(ex?.message || ex);
    setStatus(`Lifecycle failed: ${ex?.message || ex}`, "error");
  } finally {
    $("#loading-state")?.classList.add("hidden");
  }
}

async function refreshRows() {
  const result = await withTimeout(pywebview.api.lifecycle_view(true), 20000,
    "Lifecycle refresh took too long");
  if (!result?.ok) throw new Error(result?.error || "Lifecycle refresh failed");
  state.stages = result.stages || [];
  state.rows = result.rows || [];
  state.stage_counts = result.counts || {};
  state.stage_render_limit = 350;
  renderChips(); renderTable();
}

function showStagesLoadError(error) {
  const tbody = $("#pipeline-tbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state startup-error">
    <div class="empty-emoji">⚠️</div><strong>Lifecycle could not be loaded</strong>
    <div>${escapeHtml(String(error || "Unknown lifecycle error"))}</div>
    <button class="btn btn-primary" type="button" data-retry-stages>Retry Lifecycle</button>
  </div></td></tr>`;
  tbody.querySelector("[data-retry-stages]")?.addEventListener("click", loadStages);
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
      state.stage_render_limit = 350;
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
  const visible = rows.slice(0, state.stage_render_limit);
  const remaining = rows.length - visible.length;
  tbody.innerHTML = visible.map(renderRow).join("") + (remaining > 0 ? `
    <tr class="load-more-row"><td colspan="7"><button class="btn" data-load-more-stages>
      Show ${Math.min(350, remaining)} more · ${remaining} remaining
    </button></td></tr>` : "");
  tbody.querySelector("[data-load-more-stages]")?.addEventListener("click", () => {
    state.stage_render_limit += 350; renderTable();
  });
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
  $("#status-counts").textContent = `${visible.length} shown · ${rows.length} matching · ${state.rows.length} total`;
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
  state.stage_render_limit = 350;
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
          <button class="btn" data-reset="${escapeAttr(s.key)}" style="font-size:10px;padding:3px 6px;" title="Reset to default (${s.default})" aria-label="Reset ${escapeAttr(s.label)} to default">↻</button>
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
