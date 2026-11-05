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

const pipelineQuery = new URLSearchParams(window.location.search);
const jobWorkspaceMode = pipelineQuery.get("job_workspace") === "1";
const snapshotCommentsMode = pipelineQuery.get('snapshot_comments') === '1';
const snapshotCardMode = pipelineQuery.get('snapshot_card') === '1';
if (snapshotCommentsMode) document.documentElement.classList.add('snapshot-comments-mode');
if (snapshotCardMode) document.documentElement.classList.add('snapshot-card-mode');

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
  globalSearchResults: [],
  globalSearchLoading: false,
  globalSearchQuery: "",
  openWorkspace: null,
  backgroundSync: { running: false, lastStartedAt: 0, lastSuccessAt: "", error: "" },
  board_loaded: false,
  stage_render_limit: 350,
};
let workspaceRequestId = 0;
let stagesLoadPromise = null;
let archiveLoadPromise = null;
let quietBoardSyncTimer = null;
let quietCommentSyncTimer = null;
let placementMutationGeneration = 0;

// Only the shell's retained Jobs frame participates. Standalone, pop-out and
// job-workspace frames keep their existing independent presentation lifecycle.
const jobsPanelManaged = window.parent !== window && window.frameElement?.dataset.panelKey === 'pipeline';
const jobsPanelToken = jobsPanelManaged ? crypto.randomUUID() : '';
let jobsPanelActive = !jobsPanelManaged;
let jobsPanelActivated = false;
let jobsPresentationReady = false;
let jobsPresentationQueued = false;
let jobsPresentationTimer = null;
let jobsPresentationRunning = false;

function jobsPresentationActive() {
  return jobsPanelActive && document.visibilityState === 'visible';
}

function queueJobsPresentationRefresh() {
  if (!jobsPresentationReady) return;
  jobsPresentationQueued = true;
  if (!jobsPresentationActive() || jobsPresentationTimer !== null || jobsPresentationRunning) return;
  jobsPresentationTimer = setTimeout(drainJobsPresentationRefresh, 0);
}

async function drainJobsPresentationRefresh() {
  jobsPresentationTimer = null;
  if (!jobsPresentationQueued || !jobsPresentationActive()) return;
  if (savedBoardRefreshRunning || recoveringCardOrder || state.drag || state.laneDrag
      || pendingCardDrop || state.openWorkspace?.refreshing || $("#board-view .lane-name-input")) {
    jobsPresentationTimer = setTimeout(drainJobsPresentationRefresh, 250);
    return;
  }
  jobsPresentationQueued = false; jobsPresentationRunning = true;
  try {
    await Promise.allSettled([
      state.view === 'board' && !jobWorkspaceMode ? refreshSavedBoardInBackground(true) : Promise.resolve(),
      refreshOpenWorkspaceComments(),
      state.openWorkspace?.element?._commentThreads?.refresh?.(),
    ]);
  } finally {
    jobsPresentationRunning = false;
    if (jobsPresentationQueued) queueJobsPresentationRefresh();
  }
}

window.addEventListener('message', event => {
  const data = event.data;
  if (!jobsPanelManaged || event.source !== window.parent || event.origin !== location.origin
      || data?.type !== 'oneloss-jobs-panel-active' || data.token !== jobsPanelToken
      || typeof data.active !== 'boolean' || data.active === jobsPanelActive) return;
  jobsPanelActive = data.active;
  if (!jobsPanelActive) {
    clearTimeout(jobsPresentationTimer); jobsPresentationTimer = null;
  } else {
    // The first activation uses normal boot. Reopening a retained frame checks
    // freshness once, without rebuilding the panel or starting another timer.
    if (jobsPanelActivated || jobsPresentationReady) queueJobsPresentationRefresh();
    jobsPanelActivated = true;
  }
});
if (jobsPanelManaged) window.parent.postMessage({type: 'oneloss-jobs-panel-ready', token: jobsPanelToken}, location.origin);

window.addEventListener('message',event=>{
  if(event.source!==window.parent||event.origin!==location.origin)return;
  const {cardId,commentId}=event.data||{};
  if(!cardId||!commentId)return;
  if(state.openWorkspace?.cardId===cardId)void window.focusNotificationComment?.(state.openWorkspace,cardId,commentId);
  else setStatus('A notification targets another card. Finish your open draft, then reopen that card to view the comment.','warn');
});

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const NEW_LOSS_GROUPS = [
  ["Customer", [
    ["insured_name", "Customer name"],
    ["street_address_1", "Street address"], ["street_address_2", "Apartment / suite / unit"],
    ["city", "City"], ["state", "State (e.g. CA)"], ["postal_code", "ZIP code"],
    ["phone", "Phone"], ["email", "Email"],
    ["additional_contacts", "Other contacts"],
  ]],
  ["Insurance", [
    ["carrier", "Insurance company"], ["claim_number", "Claim number"],
    ["adjuster_name", "Adjuster / claim rep"],
    ["adjuster_email", "Adjuster email"],
    ["adjuster_number", "Adjuster phone"], ["deductible", "Deductible"],
    ["agent_name", "Agent name"],
  ]],
  ["Claim", [
    ["year_built", "Year built"], ["date_of_loss", "Date of loss"],
    ["date_received", "Date received"], ["xa_id", "XA ID"],
  ]],
  ["Notes", [["field_notes", "Field notes"], ["office_notes", "Office notes"]]],
];
const NEW_LOSS_TEXTAREAS = new Set(["field_notes", "office_notes"]);

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", () => bootPipeline().catch(showPipelineStartupError));

async function bootPipeline() {
  if (pipelineQuery.get('intake_only') === '1') {
    document.body.classList.add('intake-only');
    $('#new-loss-btn').addEventListener('click', openNewLossModal);
    window.linguarIntakeReady = true;
    return;
  }
  // Restore the view you left — board vs stages, which board tab, the
  // stage chip and the search box. The panel is destroyed on navigate,
  // so all four reset on every visit before this.
  await PanelState.init("pipeline");
  let preferences = {};
  try { preferences = await pywebview.api.personal_preferences() || {}; } catch (_) {}
  state.devPreview = preferences.dev_preview === true;
  if (preferences.job_views_trial && !jobWorkspaceMode && window.JobViews) {
    await JobViews.init(preferences.views_scope, {
      redraw: () => renderBoard(),
      choose: key => { state.activeBoardKey=key; state.search=''; $('#search-box').value=''; state.boardFilter='all'; },
      search: () => state.search,
      renderCard, open: (c,b) => onAuditCard(c.client||c.name,c.card_id,c.url,divisionForBoardKey(b.key)),
    });
  }
  document.documentElement.classList.toggle("density-compact", preferences.density === "compact");
  document.documentElement.classList.toggle("reduce-motion", !!preferences.reduce_motion);
  window.addEventListener("pipeline:background-sync-done", onBackgroundSyncDone);
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
  const requestedFocus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";
  if (requestedFocus) state.search = requestedFocus;
  // Never let a restored search silently hide lanes while the input looks
  // empty. The visible control and the filter state must remain identical.
  $("#search-box").value = state.search;

  // Cross-tool job opens use the exact same renderer and API as Jobs, but
  // skip the board fetch. This makes the record appear immediately above
  // Clients/Daily Run instead of navigating away or maintaining a duplicate.
  if (jobWorkspaceMode) {
    document.body.classList.add("job-workspace-mode");
    const cardId = pipelineQuery.get("card_id") || "";
    const division = pipelineQuery.get("division") || "EMS";
    await onAuditCard(requestedFocus || "Job", cardId, "", division);
    const jobAction=pipelineQuery.get('job_action');
    const actionSelector={import:'[data-import-files]',photo_report:'[data-quick-photo-report]',companycam:'[data-import-files]',trello_attachments:'[data-import-files]'}[jobAction];
    if(actionSelector)state.openWorkspace?.element?.querySelector(actionSelector)?.click();
    const sourceSelector={companycam:'[data-cc]',trello_attachments:'[data-trello]'}[jobAction];
    if(sourceSelector)document.querySelector('.import-workspace '+sourceSelector)?.click();
    if(pipelineQuery.get('comment_id'))await window.focusNotificationComment?.(state.openWorkspace,cardId,pipelineQuery.get('comment_id'));
    startQuietSyncTimers();
    return;
  }

  $("#view-board-btn").addEventListener("click", () => setView("board"));
  $("#view-stages-btn").addEventListener("click", () => setView("stages"));
  $("#view-daily-btn").addEventListener("click", () => {
    window.parent.postMessage({ type: "linguar-open-daily-run" }, "*");
  });
  $("#new-loss-btn").addEventListener("click", () => openNewLossModal());
  window.linguarIntakeReady = true;
  $("#refresh-btn").addEventListener("click", () => loadBoard(true));
  $("#archived-cards-btn")?.addEventListener("click", openArchivedCards);
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
  startQuietSyncTimers();
  if (requestedFocus) await openFocusedJob(requestedFocus);
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
    ? "🔎 Search client / claim number / lane…" : "🔎 Search client / claim number / lane / owner…";
  if (loadOnEnter && v === "stages" && !state.stages.length) loadStages();
  else if (v === "stages") renderTable();
  else if (loadOnEnter && !state.board_loaded) loadBoard();
  else renderBoard();
}

// ════════════════════════════════════════════════════════════════
//  BOARD VIEW
// ════════════════════════════════════════════════════════════════
async function loadBoard(isRefresh) {
  const placementGeneration = placementMutationGeneration;
  const btn = $("#refresh-btn");
  if (isRefresh) { btn.disabled = true; btn.textContent = "Refreshing…"; }
  if (!isRefresh) $("#board-loading")?.classList.remove("hidden");
  setStatus(isRefresh ? "Refreshing jobs…" : "");
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
    if (placementGeneration !== placementMutationGeneration) return;
    state.board = res;
    state.board_loaded = true;
    reconcileJobShelfWithBoard();
    renderBoard();
    const total = boardCardTotal();
    setStatus(res.placement_warning || (isRefresh ? `✓ ${total} jobs refreshed` : ""), res.placement_warning ? 'warn' : 'ok');
    if (res.stale_cache && !isRefresh) refreshSavedBoardInBackground(true);
  } catch (ex) {
    setStatus(`Board error: ${ex}`, "error");
    if (!isRefresh) showBoardLoadError(ex?.message || ex);
  } finally {
    if (isRefresh) { btn.disabled = false; btn.textContent = "Refresh"; }
  }
}

// Board-only zoom keeps the app chrome readable while dispatchers trade
// detail for lane coverage. Deliberate stops prevent microscopic cards.
function setBoardZoom(value) {
  const next = Math.max(0.5, Math.min(1.4, Math.round(Number(value) * 10) / 10));
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
  if (out) out.disabled = state.boardZoom <= 0.5;
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

let savedBoardRefreshRunning = false;
let recoveringCardOrder = false;
async function refreshSavedBoardInBackground(quiet = false) {
  if ($("#board-view .lane-name-input")) { queueJobsPresentationRefresh(); return; }
  if (savedBoardRefreshRunning || recoveringCardOrder || state.drag || state.laneDrag || pendingCardDrop || !jobsPresentationActive()) return;
  savedBoardRefreshRunning = true;
  const placementGeneration = placementMutationGeneration;
  try {
    const fresh = await pywebview.api.board_view_shared_refresh();
    if (placementGeneration !== placementMutationGeneration || state.drag || state.laneDrag || pendingCardDrop || recoveringCardOrder || !jobsPresentationActive()) return;
    if ($("#board-view .lane-name-input")) { queueJobsPresentationRefresh(); return; }
    if (!fresh?.ok || !(fresh.boards || []).length) return;
    const changed = boardFingerprint(state.board) !== boardFingerprint(fresh);
    const priorScroll = $(".lanes-row")?.scrollLeft || 0;
    const focusedCard = document.activeElement?.matches('.kcard[data-card-id]')
      ? document.activeElement : null;
    state.board = fresh;
    if (changed) {
      renderBoard();
      // A card's presentation attributes change with its content. Restore by
      // identity when the generic view-state selector no longer matches it.
      if (focusedCard && !focusedCard.isConnected && document.activeElement === document.body)
        $("#board-view")?.querySelector(`.kcard[data-card-id="${CSS.escape(focusedCard.dataset.cardId)}"]`)
          ?.focus({preventScroll: true});
      requestAnimationFrame(() => {
        const row = $(".lanes-row");
        if (row) row.scrollLeft = priorScroll;
      });
    }
    if (!quiet) setStatus(`✓ ${boardCardTotal()} jobs are current`, "ok");
  } catch (_) {
    // The saved board remains fully usable. Explicit Sync Jobs surfaces
    // network errors when the user wants to troubleshoot them.
  } finally { savedBoardRefreshRunning = false; }
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
  // Compare the board, saved-view columns and instant-open facts, not provider
  // payloads or polling timestamps. Ordered tuples also preserve drop order.
  const text = value => String(value ?? "");
  const factFields = ["customer_name", "address", "phone", "email", "carrier",
    "claim_number", "date_of_loss", "date_received", "cause_of_loss"];
  return JSON.stringify((payload?.boards || []).map(board => [
    text(board.key), text(board.board_id), text(board.name), Boolean(board.missing),
    (board.lanes || []).map(lane => [
      text(lane.list_id), text(lane.name),
      (lane.cards || []).map(card => [
        text(card.card_id), text(card.list_id), text(card.client),
        text(card.client || card.name), text(card.url), text(card.division),
        (card.loss_types || []).map(text),
        factFields.map(field => text(card.job_info?.[field])),
        card.checklist?.total || 0, card.checklist?.total ? card.checklist.done || 0 : 0,
        text(card.due), text(card.work_completed_date), Boolean(card.overdue), Number(card.days_in_lane || 0),
        text(card.stall), ["pending", "conflict"].includes(card.sync_status) ? card.sync_status : "",
      ]),
    ]),
  ]));
}

async function refreshOneBoard(key) {
  const placementGeneration = placementMutationGeneration;
  const name = (state.board.boards || []).find((b) => b.key === key)?.name || key;
  setStatus(`Refreshing ${name}…`);
  try {
    const res = await pywebview.api.board_view_one(key);
    if (placementGeneration !== placementMutationGeneration) return;
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
  for (const board of (boards || []).filter((item) => item.key !== "logs"))
    for (const lane of board.lanes || []) cards.push(...(lane.cards || []));
  return {
    total: cards.length,
    attention: cards.filter((c) => c.stall === "bad" || c.overdue || c.sync_status === "conflict").length,
    due: cards.filter((c) => c.due && !c.overdue).length,
  };
}

function cardMatchesBoardFilter(card) {
  if (state.boardFilter === "attention")
    return card.stall === "bad" || card.overdue || card.sync_status === "conflict";
  if (state.boardFilter === "due") return Boolean(card.due && !card.overdue);
  return true;
}

// ONE board at a time: a tab strip switches between WORK IN PROGRESS and
// ESTIMATING; only the active board's lanes render. The lanes row is
// `data-hdrag` so h_scroll.js gives it Trello-style grab-to-scroll.
function renderBoard() {
  const root=$("#board-view");
  const key=(state.board.boards || []).find(b=>b.key===state.activeBoardKey)?.key || state.board.boards?.[0]?.key || '';
  if (!window.BoardViewState) {renderBoardContent();window.LaneColors?.mount(activeBoard()?.board_id);return;}
  window.BoardViewState.render(root,key,()=>[
    ['root',root],
    ...Array.from(root.querySelectorAll('.lanes-row')).map(el=>['row',el]),
    ...Array.from(root.querySelectorAll('.lane-cards')).map(el=>['lane:'+el.closest('.lane').dataset.listId,el]),
  ],renderBoardContent);
  paintPendingCardDrop();
  window.LaneColors?.mount(activeBoard()?.board_id);
}

let pendingCardDrop = null;
function paintPendingCardDrop() {
  if (!pendingCardDrop) return;
  const {cardId,toListId,beforeId}=pendingCardDrop;
  const card=document.querySelector(`.kcard[data-card-id="${CSS.escape(cardId)}"]`);
  const lane=document.querySelector(`.lane[data-list-id="${CSS.escape(toListId)}"] .lane-cards`);
  if (!card || !lane) return;
  const before=beforeId ? lane.querySelector(`.kcard[data-card-id="${CSS.escape(beforeId)}"]`) : null;
  lane.insertBefore(card,before);
  card.setAttribute('aria-busy','true');
  if (!card.querySelector('[data-drop-saving]')) {
    const label=document.createElement('small');label.dataset.dropSaving='';
    label.textContent='Saving move…';label.setAttribute('role','status');
    card.append(label);
  }
}

function renderBoardContent() {
  const root = $("#board-view");
  const boards = state.board.boards || [];
  if (window.JobViews?.aggregate(root, boards)) return;
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
  const globalResults = renderGlobalSearchResults(q);

  const tabs = boards.map((b) =>
    `<button class="board-tab ${b.key === active.key ? "active" : ""}" data-board-tab="${escapeAttr(b.key)}">
       ${escapeHtml(b.name)} <span class="board-tab-count">${countFor(b)}</span>
     </button>`).join("") + (boards.some((board) => board.key === "logs") ? "" :
       `<button class="board-tab archive-tab" data-load-archive>Old Jobs <span class="board-tab-count">↗</span></button>`);

  let lanesHtml;
  if (active.missing) {
    lanesHtml = `<div class="board-warn" style="padding:24px;">"${escapeHtml(active.name)}" not found on Trello.</div>`;
  } else {
    const lanes = (active.lanes || []).map((l) => renderLane(active, l, q)).join("");
    lanesHtml = `<div class="lanes-row" data-hdrag data-hdrag-nowheel>${lanes || `<div class="lane-empty">No lanes.</div>`}${active.key === "logs" ? "" : `<div class="lane-add" data-no-drag><button class="lane-add-button" type="button" data-add-lane>＋ Add another lane</button></div>`}</div>`;
  }

  root.innerHTML = `
    <section class="pipeline-summary" aria-label="Filter jobs by status">
      <button class="summary-primary ${state.boardFilter === "all" ? "active" : ""}" data-board-filter="all"><strong>${summary.total}</strong><span>Active jobs</span></button>
      <button class="summary-item ${summary.attention ? "needs-attention" : ""} ${state.boardFilter === "attention" ? "active" : ""}" data-board-filter="attention"><strong>${summary.attention}</strong><span>Need attention</span></button>
      <button class="summary-item ${state.boardFilter === "due" ? "active" : ""}" data-board-filter="due"><strong>${summary.due}</strong><span>Due soon</span></button>
      <div class="summary-help">Click to open · drag to move</div>
    </section>
    ${globalResults}
    <div class="board-tabs">
      ${tabs}
      <span class="board-tabs-spacer"></span>
    </div>
    ${lanesHtml}`;

  // Board tabs.
  root.querySelectorAll("[data-board-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      window.JobViews?.clear();
      state.activeBoardKey = b.dataset.boardTab;
      PanelState.set({ activeBoardKey: state.activeBoardKey });
      applyBoardLook(state.activeBoardKey);
      renderBoard();
    }));
  root.querySelector("[data-load-archive]")?.addEventListener("click", loadArchiveBoard);
  root.querySelectorAll("[data-global-card]").forEach((card) => {
    card.addEventListener("click", () => onAuditCard(
      card.dataset.client || "", card.dataset.cardId || "",
      card.dataset.url || "", card.dataset.division || ""));
    card.addEventListener("contextmenu", onCardContext);
  });
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
  window.JobViews?.mount(root, boards);
}

function startQuietSyncTimers() {
  if (quietBoardSyncTimer || quietCommentSyncTimer) return;
  jobsPresentationReady = true;
  window.startJobsLive?.(queueJobsPresentationRefresh);
  // This cycle owns pending outbound writes as well as a pull. Do not pause it
  // with presentation polling until those responsibilities are separated.
  quietBoardSyncTimer = window.setInterval(requestBackgroundSync, 120_000);
  window.setInterval(() => { if (state.view === 'board') void refreshSavedBoardInBackground(true); }, 30_000);
  quietCommentSyncTimer = window.setInterval(refreshOpenWorkspaceComments, 60_000);
  window.setTimeout(requestBackgroundSync, 8_000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    queueJobsPresentationRefresh();
    const elapsed = Date.now() - Number(state.backgroundSync.lastStartedAt || 0);
    if (elapsed >= 120_000) requestBackgroundSync();
  });
  updateBackgroundSyncIndicator();
}

async function requestBackgroundSync() {
  if (document.visibilityState !== "visible" || state.backgroundSync.running || state.drag || state.laneDrag) return;
  state.backgroundSync.running = true;
  state.backgroundSync.lastStartedAt = Date.now();
  updateBackgroundSyncIndicator();
  try {
    const result = await pywebview.api.background_trello_sync();
    if (!result?.started) {
      state.backgroundSync.running = false;
      updateBackgroundSyncIndicator();
    }
  } catch (error) {
    state.backgroundSync.running = false;
    state.backgroundSync.error = String(error?.message || error || "Sync unavailable");
    updateBackgroundSyncIndicator();
  }
}

async function onBackgroundSyncDone(event) {
  const detail = event?.detail || {};
  state.backgroundSync.running = false;
  state.backgroundSync.error = detail.ok ? "" : String(detail.error || "Sync needs attention");
  state.backgroundSync.mode = detail.mode || "shared";
  state.backgroundSync.queueReason = detail.queue_reason || "";
  if (detail.ok) {
    state.backgroundSync.lastSuccessAt = detail.at || new Date().toISOString();
    // The sync already fetched and saved the board. The regular conditional
    // refresh paints changes without a second immediate network download.
    await refreshOpenWorkspaceComments();
  }
  updateBackgroundSyncIndicator();
}

function updateBackgroundSyncIndicator() {
  const indicator = $("#background-sync-state");
  if (!indicator) return;
  const sync = state.backgroundSync;
  const mode = sync.error ? "attention" : sync.running ? "syncing" : "current";
  indicator.dataset.state = mode;
  indicator.querySelector("span").textContent = sync.error ? "Sync needs attention"
    : !sync.lastSuccessAt ? "Checking sync"
    : sync.mode === "direct" ? "Trello connected" : "Hub current";
  const last = sync.lastSuccessAt ? formatCommentDate(sync.lastSuccessAt) : "not synced yet";
  indicator.title = sync.error
    ? `OneLoss is usable. Trello background sync: ${sync.error}`
    : sync.mode === "direct"
      ? `Direct Trello connection · Last checked ${last}. Shared background write queue is not enabled${sync.queueReason === "workspace_unscoped" ? " for this workspace" : " on this server"}. Changes are sent directly to Trello.`
      : `Shared Hub queue · Trello last checked ${last}`;
}

async function refreshOpenWorkspaceComments() {
  if (snapshotCardMode) return; // The persistent right pane owns this conversation.
  const context = state.openWorkspace;
  if (!context?.cardId || !context.element?.isConnected || context.refreshing ||
      !jobsPresentationActive()) return;
  context.refreshing = true;
  try {
    await context.conversation.refresh();
  } catch (_) {
    // The local conversation remains usable; the global sync indicator is
    // where adapter failures surface without disrupting the open job.
  } finally {
    context.refreshing = false;
  }
}

async function openFocusedJob(name) {
  const normalized = String(name || "").trim().toLowerCase();
  if (!normalized) return;
  for (const board of state.board.boards || []) {
    for (const lane of board.lanes || []) {
      const card = (lane.cards || []).find((item) =>
        String(item.client || item.name || "").trim().toLowerCase() === normalized);
      if (card) {
        onAuditCard(card.client || card.name || name, card.card_id || "",
          card.url || "", divisionForBoardKey(board.key));
        return;
      }
    }
  }
  const result = await withTimeout(pywebview.api.global_card_search(name, 24), 12000,
    "Job lookup took too long").catch(() => null);
  state.globalSearchQuery = normalized;
  state.globalSearchResults = result?.cards || [];
  renderBoard();
  const card = state.globalSearchResults[0];
  if (card) onAuditCard(card.name || name, card.card_id || "", card.url || "", card.division || "");
  else setStatus(`No job matched “${name}”`, "warn");
}

function renderGlobalSearchResults(query) {
  if (!query || query.length < 2) return "";
  if (state.globalSearchLoading && state.globalSearchQuery === query && !state.globalSearchResults.length) {
    return `<section class="global-search-results" aria-live="polite"><div class="global-search-head"><strong>All jobs</strong><span>Searching every board…</span></div></section>`;
  }
  if (state.globalSearchQuery !== query || !state.globalSearchResults.length) return "";
  return `<section class="global-search-results" aria-label="Jobs found outside the visible board">
    <div class="global-search-head"><strong>All jobs</strong><span>${state.globalSearchResults.length} result${state.globalSearchResults.length === 1 ? "" : "s"}${state.globalSearchLoading ? " · Checking Trello…" : " across Trello and job history"}</span></div>
    <div class="global-search-list">${state.globalSearchResults.map((card) => `
      <button type="button" class="global-search-card" data-global-card
        data-card-id="${escapeAttr(card.card_id || "")}" data-client="${escapeAttr(card.name || "Job")}" data-url="${escapeAttr(card.url || "")}" data-division="${escapeAttr(card.division || divisionForBoardName(card.board))}">
        <strong>${escapeHtml(card.name || "Job")}</strong>
        <span>${escapeHtml([card.board, card.list_name, card.source_label].filter(Boolean).join(" · ") || "Job history")}</span>
      </button>`).join("")}</div>
  </section>`;
}

function resolvedBoardLook(boardKey) {
  const chosen = state.boardLooks[boardKey];
  if (chosen && chosen.preset !== "trello") return chosen;
  const board = (state.board.boards || []).find(item => item.key === boardKey);
  const image = (state.localBoardBackgrounds || {})[board?.board_id || boardKey];
  return image ? {preset: "trello", customData: image} : {preset: "asphalt"};
}

function activeBoardLook() {
  return resolvedBoardLook(state.activeBoardKey);
}

function applyBoardLook(boardKey) {
  const root = $("#board-view");
  if (!root) return;
  const look = resolvedBoardLook(boardKey);
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
    button.classList.toggle("selected", button.dataset.boardLook === look.preset && (!look.customData || look.preset === "trello")));
  $("#background-status").textContent = look.customPath
    ? `Using ${look.customPath.split(/[\\/]/).pop()}` : look.preset === "trello" ? "Using a local copy of the Trello background" : "";
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
  try {
    state.localBoardBackgrounds = await pywebview.api.local_board_backgrounds() || {};
  } catch (_) { state.localBoardBackgrounds = {}; }
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
    if (window.JobViews && !JobViews.matches(c, lane)) return false;
    // A dragged/held card lives in the shelf until it is placed or returned.
    // A starred card is only a shortcut and remains visible in its lane.
    if (state.jobShelf.some((item) => item.cardId === c.card_id && item.mode === "held")) return false;
    if (!cardMatchesBoardFilter(c)) return false;
    return !q || `${c.client} ${lane.name}`.toLowerCase().includes(q);
  });
}

function renderLane(board, lane, q) {
  const matches = laneMatches(lane, q);
  const limit = board.key === "logs" ? 80 : matches.length;
  const cards = matches.slice(0, limit);
  // When searching, hide lanes with no matches to cut clutter.
  if (q && !cards.length) return "";
  const cardsHtml = cards.length
    ? cards.map((c) => renderCard(c, board)).join("") + (matches.length > cards.length
      ? `<div class="lane-more">${matches.length - cards.length} more old jobs · search to narrow</div>` : "")
    : `<div class="lane-empty">—</div>`;
  return `<div class="lane" data-list-id="${escapeAttr(lane.list_id)}"
               data-lane-name="${escapeAttr(lane.name)}"
               data-board-key="${escapeAttr(board.key)}">
    <div class="lane-head" draggable="true" title="Drag to reorder lane">
      <span class="lane-grip" aria-hidden="true">⠿</span>
      <span class="lane-name">${escapeHtml(lane.name)}</span>
      <span class="lane-count">${matches.length}</span>
      <button class="lane-menu-button" type="button" data-lane-menu data-no-drag aria-label="Lane actions for ${escapeAttr(lane.name)}">⋯</button>
    </div>
    <div class="lane-cards">${cardsHtml}</div>
  </div>`;
}

async function loadArchiveBoard() {
  if (archiveLoadPromise) return archiveLoadPromise;
  setStatus("Loading old jobs from Trello…");
  archiveLoadPromise = (async () => {
    try {
      const result = await pywebview.api.board_view_one("logs");
      if (!result?.ok) { setStatus(`Old jobs could not load: ${result?.error || "?"}`, "error"); return; }
      const boards = state.board.boards || (state.board.boards = []);
      const index = boards.findIndex((board) => board.key === "logs");
      if (index >= 0) boards[index] = result.board; else boards.push(result.board);
      state.activeBoardKey = "logs";
      PanelState.set({activeBoardKey: "logs"});
      renderBoard();
      setStatus(`✓ ${(result.board.lanes || []).reduce((sum, lane) => sum + (lane.cards || []).length, 0)} old jobs available`, "ok");
    } catch (error) {
      setStatus(`Old jobs could not load: ${error}`, "error");
    } finally {
      archiveLoadPromise = null;
    }
  })();
  return archiveLoadPromise;
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
  window.LaneColors?.controls(menu,laneEl,activeBoard()?.board_id);
  if(activeBoard()?.key==='logs')menu.querySelectorAll('[data-rename-lane],[data-archive-lane]').forEach(button=>button.hidden=true);
  const rect = event.currentTarget.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.right - 180, window.innerWidth - 190)}px`;
  menu.style.top = `${Math.max(8,Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 12))}px`;
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

function renderCardLabels(labels) {
  const labelColors = {green:'#216e4e',yellow:'#7f5f01',orange:'#974f0c',red:'#ae2e24',purple:'#6e5dc6',blue:'#0055cc',sky:'#206a83',lime:'#4c6b1f',pink:'#943d73',black:'#44546f'};
  return (labels || []).map(label => {
    const title = label.name || `${label.color || 'Uncolored'} label`;
    const color = labelColors[String(label.color || '').split('_')[0]] || '#44546f';
    return `<span class="card-trello-label" style="background-color:${color}" title="${escapeAttr(title)}">${escapeHtml(title)}</span>`;
  }).join('');
}

document.addEventListener('oneloss-card-labels', event => {
  const {cardId, labels} = event.detail || {};
  if (!cardId || !Array.isArray(labels)) return;
  for (const board of state.board?.boards || []) for (const lane of board.lanes || []) {
    for (const card of lane.cards || []) if (card.card_id === cardId) card.labels = labels;
  }
  document.querySelectorAll('.kcard[data-card-id]').forEach(card => {
    if (card.dataset.cardId !== cardId) return;
    let chips = card.querySelector('.kcard-chips');
    if (!chips) { chips = document.createElement('div'); chips.className = 'kcard-chips'; card.querySelector('.kcard-title')?.after(chips); }
    chips.querySelectorAll('.card-trello-label').forEach(label => label.remove());
    chips.insertAdjacentHTML('afterbegin', renderCardLabels(labels));
  });
});

function renderCard(c, board = {}) {
  const loss = renderCardLabels(c.labels);
  const carrierChip = c.job_info?.carrier
    ? `<span class="chip-mini" title="Insurance carrier">${escapeHtml(c.job_info.carrier)}</span>`
    : "";
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
    ? `<span class="chip-mini sync-conflict" title="Trello and OneLoss need review">⚠ Sync</span>`
    : c.sync_status === 'pending' ? '<span class="chip-mini" title="Saved in OneLoss; Trello sync queued">Sync pending</span>' : "";
  const completionChip = c.work_completed_date ? `<span class="chip-mini" title="Work completed">✓ Completed ${escapeHtml(fmtDue(c.work_completed_date))}</span>` : '';
  const chips = [loss, carrierChip, ckChip, completionChip, dueChip, stallChip, syncChip].filter(Boolean).join("");
  const starred = isJobStarred(c.card_id);
  return `<div class="kcard stall-border-${escapeAttr(c.stall)}" draggable="false" data-no-drag
               role="button" tabindex="0" aria-label="Open ${escapeAttr(c.client || "job")}"
               data-card-id="${escapeAttr(c.card_id)}"
               data-list-id="${escapeAttr(c.list_id)}"
               data-url="${escapeAttr(c.url)}"
               data-client="${escapeAttr(c.client)}"
               data-division="${escapeAttr(divisionForBoardKey(board.key))}"
               data-card-summary="${escapeAttr(JSON.stringify({
                 due: c.due || "", overdue: Boolean(c.overdue),
                 days_in_lane: Number(c.days_in_lane || 0),
                 loss_types: c.loss_types || [], checklist: ck,
                 job_info: c.job_info || {},
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

function divisionForBoardKey(boardKey) {
  if (boardKey === "contents") return "CONTENTS";
  if (boardKey === "recon") return "RECON";
  return "EMS";
}

function divisionForBoardName(boardName) {
  const name = String(boardName || "").trim().toUpperCase();
  if (name.includes("CONTENTS")) return "CONTENTS";
  if (name.includes("RECON")) return "RECON";
  return "EMS";
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
      finishPointerCardDrag(event, !allowOpen);
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
  if (pendingCardDrop || recoveringCardOrder) { setStatus('Finishing the previous move…'); return; }
  const ghost = document.createElement("div");
  ghost.className = "card-drag-ghost";
  ghost.innerHTML = `<strong>${escapeHtml(cardEl.dataset.client || "Job")}</strong><span>Drop between cards · shelf to hold</span>`;
  document.body.appendChild(ghost);
  cardEl.dataset.didDrag = "true";
  cardEl.classList.add("dragging");
  state.drag = dragDetailsFromCard(cardEl);
  const rect = cardEl.getBoundingClientRect();
  ghost.style.width = `${rect.width}px`;
  // The compact preview should follow below the cursor even when the user
  // grabs the bottom of a tall card.
  const ghostRect = ghost.getBoundingClientRect();
  const inside = (value, size) => Math.max(2, Math.min(value, Math.max(2, size - 2)));
  pointerCardDrag = { cardEl, ghost, offsetX:inside(event.clientX-rect.left, ghostRect.width),
    offsetY:inside(Math.min(event.clientY-rect.top, 14), ghostRect.height), drag: { ...state.drag } };
  showShelfForDrag();
  updatePointerCardDrag(event);
}

function inJobShelfDropZone(event) {
  const rect = document.querySelector('.job-shelf-drop-hint')?.getBoundingClientRect();
  return !!rect && rect.width > 0 && event.clientX >= rect.left && event.clientX <= rect.right
    && event.clientY >= rect.top && event.clientY <= rect.bottom;
}

function updatePointerCardDrag(event) {
  if (!pointerCardDrag) return;
  pointerCardDrag.ghost.style.transform = `translate3d(${event.clientX-pointerCardDrag.offsetX}px,${event.clientY-pointerCardDrag.offsetY}px,0)`;
  const inHandZone = inJobShelfDropZone(event);
  $("#job-shelf").classList.toggle("drop-ready", inHandZone);
  $$(".lane.drop-target").forEach((lane) => lane.classList.remove("drop-target"));
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".lane");
  if (!inHandZone && target) target.classList.add("drop-target");
  window.CardDropPreview?.show(!inHandZone && target?.querySelector('.lane-cards'), '.kcard[data-card-id]', pointerCardDrag.cardEl, event.clientY);
}

function finishPointerCardDrag(event, cancelled = false) {
  if (!pointerCardDrag) return;
  const active = pointerCardDrag;
  const drag = active.drag;
  const inHandZone = inJobShelfDropZone(event);
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".lane");
  if(!cancelled&&!inHandZone&&target)drag.dropOrigin=active.ghost.getBoundingClientRect();
  active.ghost.remove();
  active.cardEl.classList.remove("dragging", "drag-ready");
  pointerCardDrag = null;
  $$(".lane.drop-target").forEach((lane) => lane.classList.remove("drop-target"));
  if (cancelled) {
    window.CardDropPreview?.clear();
    state.drag = null; hideShelfAfterDrag(); return;
  }
  if (inHandZone) {
    window.CardDropPreview?.clear();
    holdDraggedCard(drag);
  } else if (target) {
    hideShelfAfterDrag();
    state.drag = drag;
    void onLaneDrop({ preventDefault() {}, currentTarget: target, clientY:event.clientY });
  } else {
    window.CardDropPreview?.clear();
    state.drag = null;
    hideShelfAfterDrag();
  }
}

function onCardDragStart(ev) {
  if (pendingCardDrop || recoveringCardOrder) { ev.preventDefault(); return; }
  const el = ev.currentTarget;
  window.CardDropPreview?.grab(el,ev);
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
  window.CardDropPreview?.clear();
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
  window.CardDropPreview?.show(ev.currentTarget.querySelector('.lane-cards'), '.kcard[data-card-id]', document.querySelector('.kcard.dragging'), ev.clientY);
}

function onLaneDragLeave(ev) {
  ev.currentTarget.classList.remove("drop-target", "lane-drop-before", "lane-drop-after");
}

async function onLaneDrop(ev) {
  ev.preventDefault();
  if (pendingCardDrop || recoveringCardOrder) { window.CardDropPreview?.clear(); state.drag=null; setStatus('Finishing the previous move…'); return; }
  const laneEl = ev.currentTarget;
  if (state.laneDrag) {
    const moving = state.laneDrag;
    const board = activeBoard();
    const lanes = board?.lanes || [];
    const from = lanes.findIndex((lane) => lane.list_id === moving.listId);
    let to = lanes.findIndex((lane) => lane.list_id === laneEl.dataset.listId);
    if (from < 0 || to < 0 || from === to) { onLaneDragEnd(); return; }
    const originalLanes = lanes.slice();
    const [item] = lanes.splice(from, 1);
    if (from < to) to -= 1;
    if (moving.side === "after") to += 1;
    lanes.splice(to, 0, item);
    const previousId = lanes[to - 1]?.list_id || "";
    const nextId = lanes[to + 1]?.list_id || "";
    onLaneDragEnd(); renderBoard();
    let result;
    try { result = await pywebview.api.reorder_lane(item.list_id, previousId, nextId); }
    catch (_) { result = {ok:false, error:'The move could not be confirmed. Refresh before trying again.'}; }
    if (!result?.ok) {
      lanes.splice(0, lanes.length, ...originalLanes);
      renderBoard();
      setStatus(`Could not move lane: ${result?.error || "?"}`, "error");
      try { await loadBoard(true); } catch (_) { /* Keep the previous order visible. */ }
      return;
    }
    setStatus(`✓ Moved “${item.name}” on Trello`, "ok");
    return;
  }
  laneEl.classList.remove("drop-target");
  const drag = state.drag;
  state.drag = null;
  const dropOrigin=drag?.dropOrigin || window.CardDropPreview?.origin(document.querySelector('.kcard.dragging'),ev);
  const preview = window.CardDropPreview?.selection(laneEl.querySelector('.lane-cards'));
  window.CardDropPreview?.clear();
  if (!drag) return;
  const toListId = laneEl.dataset.listId;
  const toLane = laneEl.dataset.laneName;
  if (!toListId) return;
  let targetCards = (state.board.boards || []).flatMap(b => b.lanes || [])
    .find(l => l.list_id === toListId)?.cards?.filter(c => c.card_id !== drag.cardId) || [];
  const before = preview ? preview.before : Array.from(laneEl.querySelectorAll('.kcard[data-card-id]')).find(el => {
    const rect = el.getBoundingClientRect();
    return el.dataset.cardId !== drag.cardId && ev.clientY < rect.top + rect.height/2;
  });
  let insertIndex = before ? targetCards.findIndex(c => c.card_id === before.dataset.cardId) : targetCards.length;
  const moveDiagnostics = response => JSON.stringify({
    action: 'move_card', card: {id: drag.cardId, name: drag.name},
    source_list_id: drag.fromListId, destination: {id: toListId, name: toLane},
    before_card_id: before?.dataset.cardId || null, insert_index: insertIndex,
    neighbors: [targetCards[insertIndex-1], targetCards[insertIndex]].filter(Boolean)
      .map(c => ({id:c.card_id, name:c.name, position:c.pos ?? null})),
    placement: (state.board.placement_snapshot?.placements || []).filter(r => r.card_id === drag.cardId)
      .map(r => ({version:r.version, synced_version:r.synced_version, list_id:r.list_id, position:r.position})),
    response
  }, null, 2);
  const positionForSlot = () => {
    if (insertIndex < 0 || [targetCards[insertIndex-1], targetCards[insertIndex]].some(c => c && (!Number.isFinite(c.pos) || c.pos <= 0))) return null;
    const previous=targetCards[insertIndex-1]?.pos ?? 0, next=targetCards[insertIndex]?.pos;
    const value=next == null ? previous+65536 : (previous+next)/2;
    return value>previous && (next == null || value<next) ? value : null;
  };
  let position = positionForSlot();
  if (position === null) {
    recoveringCardOrder = true;
    setStatus('Updating card order…');
    const generation = placementMutationGeneration;
    try {
      const fresh = await pywebview.api.board_view_shared_refresh();
      if (!fresh?.ok || generation !== placementMutationGeneration) throw Error('Board changes could not be confirmed.');
      const lane = (fresh.boards || []).flatMap(b => b.lanes || []).find(l => l.list_id === toListId);
      if (!lane) throw Error('The destination lane is no longer available.');
      state.board = fresh;
      targetCards = (lane.cards || []).filter(c => c.card_id !== drag.cardId);
      insertIndex = before ? targetCards.findIndex(c => c.card_id === before.dataset.cardId) : targetCards.length;
      position = positionForSlot();
      if (position === null) {
        const label = card => `“${card.name || card.client || card.card_id || 'Unnamed card'}”`;
        const neighbors = [targetCards[insertIndex-1], targetCards[insertIndex]].filter(Boolean);
        const invalid = neighbors.filter(c => !Number.isFinite(c.pos) || c.pos <= 0);
        let reason;
        if (insertIndex < 0) {
          reason = `The drop-target card (${before?.dataset.cardId || 'unknown'}) is no longer in this lane.`;
        } else if (invalid.length) {
          reason = `Missing or invalid saved position for ${invalid.map(label).join(' and ')}.`;
        } else {
          reason = `Conflicting saved positions between ${neighbors.map(label).join(' and ')}; no safe space is available at this drop point.`;
        }
        throw Error(`Could not move ${label({name:drag.name,card_id:drag.cardId})} to “${lane.name || toLane || toListId}”. ${reason} Your card was not moved.`);
      }
    } catch (error) {
      renderBoard(); setStatus(error.message || 'Connection unavailable. Your card was not moved.', 'warn', moveDiagnostics({error:error.message, stack:error.stack})); return;
    } finally { recoveringCardOrder = false; }
  }
  // Dropping is the user's move action; only interrupt for a real conflict.
  if (drag.conflict && !confirm(`Trello moved "${drag.name}" to “${drag.actualLane || "another lane"}” while it was held. Move it to “${toLane}” anyway?`))
    return;
  setStatus(`Moving "${drag.name}" → ${toLane}…`);
  const knownPlacement = (state.board.placement_snapshot?.placements || []).find(r => r.card_id === drag.cardId);
  pendingCardDrop={cardId:drag.cardId,toListId,beforeId:before?.dataset.cardId || null};
  paintPendingCardDrop();
  window.CardDropPreview?.land(document.querySelector(`.kcard[data-card-id="${CSS.escape(drag.cardId)}"]`),dropOrigin);
  let res;
  try { res = await pywebview.api.move_card(drag.cardId, toListId, knownPlacement?.version || 0, position); }
  catch (error) { res={ok:false,error:`Move could not be confirmed: ${error.message || error}. Check before retrying.`}; }
  finally { pendingCardDrop=null; }
  if (!res?.ok) {
    renderBoard();
    setStatus(`Move failed: ${res?.error || "?"}`, "error", moveDiagnostics(res));
    await loadBoard(true);   // reload the saved app placement
    return;
  }
  // Commit confirmed state; the pending preview already appeared at release.
  moveCardLocally(drag.cardId, drag.fromListId, toListId, toLane, insertIndex, position);
  acceptPlacementResult(res);
  if (drag.source === "shelf") removeFromJobShelf(drag.cardId);
  renderBoard();
  showMoveUndo(drag, toListId, toLane);
  setStatus(res.pending_sync
    ? `✓ Moved "${drag.name}" → ${toLane} in OneLoss · Trello sync pending`
    : res.synced === false
      ? `✓ Moved in OneLoss · ${res.warning || "sync needs review"}`
      : `✓ Moved "${drag.name}" → ${toLane}`, res.warning ? "warn" : "ok");
}

function moveCardLocally(cardId, fromListId, toListId, toLane, insertIndex = 0, position = null) {
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
  if (position != null) moved.pos = position;
  const shelfItem = state.jobShelf.find((item) => item.cardId === cardId);
  if (shelfItem) {
    shelfItem.fromListId = toListId;
    shelfItem.lane = toLane;
    persistJobShelf(); renderJobShelf();
  }
  for (const b of state.board.boards || []) {
    for (const l of b.lanes || []) {
      if (l.list_id === toListId) { (l.cards = l.cards || []).splice(insertIndex, 0, moved); return; }
    }
  }
}

// ── Per-card actions ─────────────────────────────────────────────
function boundedWorkspaceRead(request, label, milliseconds = 30000) {
  let timer;
  return Promise.race([Promise.resolve(request), new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(label + ' timed out. Check your connection and retry.')), milliseconds);
  })]).finally(() => clearTimeout(timer));
}

async function onAuditCard(cardOrClient, cardId = "", trelloUrl = "", division = "", navigation = null) {
  const isCard = cardOrClient && typeof cardOrClient === "object" && cardOrClient.dataset;
  const client = isCard ? cardOrClient.dataset.client : String(cardOrClient || "");
  const resolvedCardId = isCard ? (cardOrClient.dataset.cardId || "") : cardId;
  const resolvedUrl = isCard ? (cardOrClient.dataset.url || "") : trelloUrl;
  const resolvedDivision = isCard ? (cardOrClient.dataset.division || division) : division;
  const requestId = ++workspaceRequestId;
  const loadSession = navigation?.loadSession || window.LinkedWorkspacePreload?.create(pywebview.api,
    () => state.openWorkspace?.element?.isConnected && state.openWorkspace.element._divisionLoadSession === loadSession);
  const warmed = loadSession?.peek(resolvedCardId, resolvedDivision);
  const instant = warmed ? {...warmed, deferred_loading:true} : instantWorkspaceData(cardOrClient, client, resolvedCardId, resolvedDivision);
  if (navigation) {
    instant.division_trello_cards = navigation.cards;
    instant.division_card_reconciliation = navigation.reconciliation;
    instant.initial_workspace_tab = navigation.tab;
    if (!warmed) instant.info_sections = navigation.sharedInfo || instant.info_sections;
  }
  let modal;
  try {
    modal = openAuditModal(instant, resolvedUrl);
    if (navigation?.element) {
      // Keep the actual dialog shell (and its dimensions) while giving the new
      // card fresh controllers. Never reuse the previous card's conversation.
      const shell = navigation.element.querySelector('.audit-card');
      const fresh = modal.element.querySelector('.audit-card');
      if (shell && fresh) {
        shell.replaceChildren(...fresh.childNodes);
        fresh.replaceWith(shell);
        shell.classList.add('division-switch-shell');
      }
      navigation.element.remove();
      modal.element.classList.add('division-switch-overlay');
      modal.element.querySelector(`[data-division-data="${resolvedDivision}"]`)?.focus();
    }
    modal.element._divisionLoadSession = loadSession;
  } catch (error) {
    navigation?.element?.remove();
    // Never let a job-specific data shape turn a click into apparent silence.
    modal = openAuditLoadingModal(client);
    modal.showError(`The card opened, but its workspace could not render: ${error?.message || error}`);
    setStatus(`Card opened · workspace layout needs review`, "error", `Card: ${resolvedCardId}\n${error?.stack || error?.message || error}`);
    return;
  }
  setStatus("");
  let notificationsAcknowledged = false;
  const acknowledgeOpenedNotifications = () => {
    if (notificationsAcknowledged || !resolvedCardId || requestId !== workspaceRequestId
        || !modal.element.isConnected || !jobsPresentationActive()
        || !pywebview.api.mark_opened_card_notifications) return;
    notificationsAcknowledged = true;
    void pywebview.api.mark_opened_card_notifications(resolvedCardId).then(result => {
      window.parent.postMessage({type:'oneloss-notifications-changed'}, '*');
      if (!result?.ok && requestId === workspaceRequestId && modal.element.isConnected)
        setStatus(result?.error || 'Notification read status was not confirmed.', 'warn');
    }).catch(() => {
      if (requestId === workspaceRequestId && modal.element.isConnected)
        setStatus('Card opened, but notification read status could not save.', 'warn');
    });
  };
  try {
    // Location is independent of saved facts. A slow provider lookup must not
    // hold back the database response or the subsequent full refresh.
    Promise.resolve().then(() => pywebview.api.job_card_placement?.(resolvedCardId))
      .then(placement => {
        if (placement?.lane && requestId === workspaceRequestId && modal.element.isConnected)
          modal.applyPlacement(placement);
      }).catch(() => {}); // Keep the board preview location if lookup fails.
    let fast;
    try {
      fast = await boundedWorkspaceRead(loadSession ? loadSession.load(client, resolvedCardId, resolvedDivision)
        : pywebview.api.job_card_workspace_fast(client, resolvedCardId, resolvedDivision), 'Saved job details');
    } catch (error) {
      fast = {ok:false, error:error?.message || String(error)};
    }
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (!fast?.ok) {
      modal.setDeferredError(fast?.error || "Shared job details unavailable");
      setStatus("Job details are temporarily limited", "warn", `Card: ${resolvedCardId}\n${fast?.error || "Shared job details unavailable"}`);
    } else {
      modal.applyRefresh(fast);
      setStatus("");
      acknowledgeOpenedNotifications();
    }
    // The full request starts after the shared CRM payload is cached. Running
    // both at once duplicated the same Supabase hydration and could more than
    // double load time on slower office connections.
    const fullPromise = Promise.resolve(pywebview.api.job_card_workspace(
      client, resolvedCardId, resolvedDivision)).then(
        (value) => ({ value }),
        (error) => ({ error }),
      );
    const fullOutcome = await boundedWorkspaceRead(fullPromise, 'Live job details', 45000);
    if (requestId !== workspaceRequestId || !modal.element.isConnected) return;
    if (fullOutcome.error) {
      modal.setDeferredError(fullOutcome.error?.message || String(fullOutcome.error));
      setStatus(`Job opened · live details could not refresh`, "warn", `Card: ${resolvedCardId}\n${fullOutcome.error?.stack || fullOutcome.error?.message || fullOutcome.error}`);
      return;
    }
    const full = fullOutcome.value;
    if (!full?.ok) {
      modal.setDeferredError(full?.error || "Deep refresh unavailable");
      setStatus(`Job opened · some live details could not refresh`, "warn", `Card: ${resolvedCardId}\n${full?.error || "Deep refresh unavailable"}`);
      return;
    }
    modal.applyRefresh(full);
    acknowledgeOpenedNotifications();
    window.AutomaticFileCheck?.run(pywebview.api, client, resolvedCardId, resolvedDivision,
      () => requestId === workspaceRequestId && modal.element.isConnected,
      result => modal.applyRefresh(result),
      text => { const label = modal.element.querySelector('[data-file-check-state]'); if (label) { label.textContent = text; label.hidden = !text; } });
    loadSession?.schedule(full, (id, result) => {
      if (modal.element.isConnected) modal.applyLinkedComments(id, result);
    });
    setStatus("");
  } catch (error) {
    if (requestId !== workspaceRequestId) return;
    if (!modal.element.isConnected) return;
    modal.setDeferredError(error?.message || String(error));
    setStatus(`Basic card opened · live details failed`, "warn", `Card: ${resolvedCardId}\n${error?.stack || error?.message || error}`);
  }
}

function appCardPlacement(cardId) {
  if (!cardId) return {};
  for (const board of state.board.boards || []) {
    for (const lane of board.lanes || []) {
      const card=(lane.cards || []).find(card => card.card_id === cardId);
      if (card)
        return {board: board.name || '', lane: lane.name || '', due:card.due || '', source: 'app_board'};
    }
  }
  return {};
}

function instantWorkspaceData(cardOrClient, client, cardId, division) {
  let summary = {};
  if (cardOrClient?.dataset?.cardSummary) {
    try { summary = JSON.parse(cardOrClient.dataset.cardSummary); } catch (_) {}
  }
  const placement = appCardPlacement(cardId);
  const lane = placement.lane || '';
  const selected = division || "EMS";
  const chips = [
    ...(summary.loss_types || []),
    summary.due ? `${summary.overdue ? "Overdue" : "Due"} ${fmtDue(summary.due)}` : "",
    summary.days_in_lane ? `${summary.days_in_lane} days in lane` : "",
  ].filter(Boolean);
  const jobInfo = summary.job_info || {};
  const section = (name, fields) => ({name, fields: fields.filter((field) => field.value)});
  const infoSections = [
    section("Customer Information", [
      {id: "customer_name", label: "Customer name", value: jobInfo.customer_name || ""},
      {id: "address", label: "Address", value: jobInfo.address || ""},
      {id: "phone", label: "Phone", value: jobInfo.phone || ""},
      {id: "email", label: "Email", value: jobInfo.email || ""},
    ]),
    section("Insurance Information", [
      {id: "carrier", label: "Carrier", value: jobInfo.carrier || ""},
      {id: "claim_number", label: "Claim #", value: jobInfo.claim_number || ""},
    ]),
    section("Property Details", [
      {id: "date_of_loss", label: "Date of loss", value: jobInfo.date_of_loss || ""},
      {id: "date_received", label: "Date received", value: jobInfo.date_received || ""},
      {id: "cause_of_loss", label: "Cause of loss", value: jobInfo.cause_of_loss || ""},
    ]),
    section("App location", [
      {id: "pipeline_lane", label: "Current lane", value: lane},
      ...(summary.loss_types?.length ? [{id: "loss_type", label: "Loss type", value: summary.loss_types.join(", ")}] : []),
      ...(summary.due ? [{id: "due", label: "Due", value: fmtDue(summary.due)}] : []),
    ]),
  ].filter((item) => item.fields.length);
  return {
    ok: true, client, card_id: cardId, selected_division: selected, app_placement: placement,
    selected_trello_url: cardOrClient?.dataset?.url || "",
    deferred_loading: true, load_ms: 0,
    audit: {ok: true, client, found: true, form_issues: [], photo_issues: [],
      requirements: [], activity: chips, path: "", aging: summary.days_in_lane || 0},
    crm: {ok: true, lifecycle_stage: lane.toLowerCase().replaceAll(" ", "_"),
      job_log: [], progress: {items: [], percent_complete: 0}, work_environments: []},
    info_sections: infoSections,
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
  const requestClose = () => { close(); notifyJobWorkspaceClosed(); };
  const keyClose = (event) => { if (event.key === "Escape") requestClose(); };
  const close = () => {
    document.removeEventListener("keydown", keyClose);
    w.remove();
  };
  w.querySelector("[data-close]").addEventListener("click", requestClose);
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
      body?.querySelector("[data-error-close]")?.addEventListener("click", requestClose);
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

const pendingTrelloPins = new Map();
window.addEventListener('pipeline:pin-info', (event) => {
  const {client, info} = event.detail || {};
  if (!info?.ok) setStatus(`${client}: card pinned; Job Info refresh failed. ${info?.error || ''}`, 'warn');
  else if (info.conflicts?.length) setStatus(`${client}: card pinned; Job Info has conflicts to review.`, 'warn');
});

function openChangePinnedTrelloCard(cardEl, onPinned = null) {
  const client = String(cardEl?.dataset?.client || "").trim();
  const sourceCardId = String(cardEl?.dataset?.cardId || "").trim();
  const division = String(cardEl?.dataset?.division || "EMS").trim().toUpperCase();
  if (!client) {
    setStatus("This card does not have a job name to match.", "warn");
    return;
  }

  const previousFocus = document.activeElement;
  const pickerTitle = `Choose ${division === 'CONTENTS' ? 'Contents' : division === 'RECON' ? 'Recon' : 'EMS'} card`;
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay trello-pin-overlay";
  modal.innerHTML = `<div class="modal-box trello-pin-picker" role="dialog" aria-modal="true" aria-label="${escapeAttr(pickerTitle)}">
    <header class="modal-head trello-pin-head">
      <div><div class="modal-title">${escapeHtml(pickerTitle)}</div><div class="modal-sub">${escapeHtml(client)} · Select the matching card to link it to this job.</div></div>
      <button class="audit-close" data-close aria-label="Close">×</button>
    </header>
    <div class="modal-body trello-pin-body">
      <label class="trello-pin-search"><span>Find a Trello card</span><input data-search value="${escapeAttr(client)}" autocomplete="off" spellcheck="false" placeholder="Job name, claim number, or address"></label>
      <div class="trello-pin-results" data-results aria-live="polite"><div class="trello-pin-message">Searching…</div></div>
      <form class="trello-pin-direct" data-direct-form>
        <label><span>Or paste an exact Trello link or card ID</span><input data-direct-input autocomplete="off" spellcheck="false" placeholder="https://trello.com/c/…"></label>
        <button class="btn" type="submit">Use link</button>
      </form>
    </div>
  </div>`;
  document.body.appendChild(modal);

  const searchInput = modal.querySelector("[data-search]");
  const resultsEl = modal.querySelector("[data-results]");
  const directInput = modal.querySelector("[data-direct-input]");
  let searchTimer = null;
  let searchSequence = 0;
  let pinning = false;

  const onKeyDown = (event) => {
    if ([...document.querySelectorAll('.modal-scrim, .overlay')].filter(el => el.getClientRects().length).at(-1) !== modal) return;
    if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); }
    if (event.key === 'Tab') {
      const controls = [...modal.querySelectorAll('button,input')].filter(el => !el.disabled && el.getClientRects().length);
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
    }
  };
  const close = () => {
    ++searchSequence;
    if (searchTimer) clearTimeout(searchTimer);
    document.removeEventListener("keydown", onKeyDown, true);
    modal.remove();
    if (previousFocus?.isConnected) previousFocus.focus();
  };
  const pinCard = async (cardIdOrUrl, cardName = "") => {
    const value = String(cardIdOrUrl || "").trim();
    if (!value || pinning) return;
    const pendingKey = JSON.stringify([sourceCardId || client, division]);
    const previous = pendingTrelloPins.get(pendingKey);
    if (previous && previous.value !== value) {
      resultsEl.textContent = 'A pin change for this job is still saving. Wait for its result before changing it again.';
      return;
    }
    pinning = true;
    ++searchSequence;
    if (searchTimer) clearTimeout(searchTimer);
    resultsEl.innerHTML = `<div class="trello-pin-message">Saving ${escapeHtml(division)} card…</div>`;
    const waitingTimer = setTimeout(() => {
      if (modal.isConnected) resultsEl.textContent = 'Still waiting for the pin save result. Do not retry; this request is still running.';
    }, 12000);
    try {
      const pending = previous || {value, promise: sourceCardId
        ? pywebview.api.pin_crm_division_trello(client, division, value, sourceCardId)
        : pywebview.api.pin_crm_division_trello(client, division, value)};
      pendingTrelloPins.set(pendingKey, pending);
      const result = await pending.promise;
      pendingTrelloPins.delete(pendingKey);
      if (!result?.ok) throw new Error(result?.error || "The card could not be pinned");
      close();
      const imported = Number(result.imported_count || 0);
      const conflicts = (result.conflicts || []).length;
      const pullFailed = result.info_pull && !result.info_pull.ok;
      const detail = result.info_pull_pending ? ' · Job Info refresh is running in the background' : pullFailed
        ? ` · card pinned; Job Info could not be read (${result.info_pull.error || "Trello unavailable"})`
        : ` · ${imported} Job Info field${imported === 1 ? "" : "s"} pulled${conflicts ? ` · ${conflicts} conflict${conflicts === 1 ? "" : "s"} need review` : ""}`;
      setStatus(`${division} Trello card changed${cardName ? ` to ${cardName}` : ""}${detail}.`, pullFailed || conflicts ? "warn" : "ok");
      if (typeof onPinned === "function") await onPinned(result);
    } catch (error) {
      pendingTrelloPins.delete(pendingKey);
      pinning = false;
      resultsEl.innerHTML = `<div class="trello-pin-message error">${escapeHtml(error?.message || String(error))}</div>`;
    } finally {
      clearTimeout(waitingTimer);
    }
  };
  const search = async () => {
    if (pinning) return;
    const query = String(searchInput?.value || "").trim();
    const sequence = ++searchSequence;
    if (query.length < 2) {
      resultsEl.innerHTML = `<div class="trello-pin-message">Enter at least two characters.</div>`;
      return;
    }
    resultsEl.innerHTML = `<div class="trello-pin-message">Searching…</div>`;
    try {
      const result = await withTimeout(pywebview.api.global_card_search(query, 24, division), 12000,
        "Trello search took too long");
      if (sequence !== searchSequence) return;
      if (!result?.ok) throw new Error(result?.error || "Search is unavailable");
      const cards = result.cards || [];
      resultsEl.innerHTML = cards.length ? cards.map((card) => `
        <button type="button" class="trello-pin-result" data-result-card="${escapeAttr(card.card_id || card.url || "")}" data-result-name="${escapeAttr(card.name || "Trello card")}">
          <strong>${escapeHtml(card.name || "Trello card")}</strong>
          <span>${escapeHtml([card.board, card.list_name, card.source_label].filter(Boolean).join(" · ") || "Trello")}</span>
        </button>`).join("") : `<div class="trello-pin-message">No matching cards. Paste the exact Trello link below.</div>`;
      resultsEl.querySelectorAll("[data-result-card]").forEach((button) =>
        button.addEventListener("click", () => pinCard(button.dataset.resultCard, button.dataset.resultName)));
    } catch (error) {
      if (sequence !== searchSequence) return;
      resultsEl.innerHTML = `<div class="trello-pin-message error">${escapeHtml(error?.message || String(error))}</div>`;
    }
  };

  modal.querySelector("[data-close]")?.addEventListener("click", close);
  document.addEventListener("keydown", onKeyDown, true);
  searchInput?.addEventListener("input", () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(search, 220);
  });
  modal.querySelector("[data-direct-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void pinCard(directInput?.value || "");
  });
  searchInput?.focus();
  void search();
}

function openCardMenu(ev, cardEl) {
  const client = cardEl.dataset.client;
  const cardId = cardEl.dataset.cardId;
  if (!window.emsOpenInMenu) return;
  window.emsOpenInMenu(ev, client, {
    extra: [
      { label: "Open in new window", action: () => window.OneLossPopout?.open('pipeline', {cardId,client,division:cardEl.dataset.division || 'EMS'}) },
      { label: "Move to board / section…", action: () => openPlacementAction(cardId, "move") },
      { label: "Archive card…", action: () => openPlacementAction(cardId, "archive") },
    ],
  });
}

function acceptPlacementResult(result) {
  placementMutationGeneration++;
  if (result.board?.ok) state.board = result.board;
  const removed = new Set((state.board.placement_snapshot?.placements || []).filter(r => r.state !== 'active').map(r => r.card_id));
  const priorShelfCount = state.jobShelf.length;
  state.jobShelf = state.jobShelf.filter(item => !removed.has(item.cardId));
  if (state.jobShelf.length !== priorShelfCount) persistJobShelf();
  if (state.board_loaded) { reconcileJobShelfWithBoard(); renderBoard(); }
}

// Reconcile just the acknowledged card. Never replace the whole board with a
// response fetched before another user's action or download Trello to repaint it.
function acceptSavedCardPlacement(context, cardId) {
  const row = context?.placement;
  if (!context?.ok || !row || row.card_id !== cardId) return null;
  const saved = state.board.placement_snapshot || {boards:[], placements:[]};
  const previous = saved.placements?.find(item => item.card_id === cardId);
  if (previous && (Number(previous.version) > Number(row.version) ||
      (Number(previous.version) === Number(row.version) && Number(previous.synced_version) > Number(row.synced_version)))) return null;
  const meta = context.boards?.find(board => board.board_id === row.board_id);
  const laneMeta = meta?.lists?.find(lane => lane.id === row.list_id && !lane.closed);
  if (!meta || !laneMeta || row.state !== 'active') return null;
  let card;
  for (const board of state.board.boards || []) for (const lane of board.lanes || []) {
    card ||= lane.cards?.find(item => item.card_id === cardId);
  }
  // An unopened board/search result need not be injected into this view.
  if (card) {
    let destination = state.board.boards.find(board => board.board_id === row.board_id);
    if (!destination) {
      destination = {key:row.board_id, board_id:row.board_id, name:meta.name, lanes:[]};
      state.board.boards.push(destination);
    }
    let target = destination.lanes.find(lane => lane.list_id === row.list_id);
    if (!target) {
      target = {list_id:row.list_id, name:laneMeta.name, pos:laneMeta.pos, cards:[], count:0};
      destination.lanes.push(target);
      destination.lanes.sort((a,b) => (a.pos || 0) - (b.pos || 0));
    }
    for (const board of state.board.boards) for (const lane of board.lanes || []) {
      lane.cards = (lane.cards || []).filter(item => item.card_id !== cardId);
      lane.count = lane.cards.length;
    }
    target.cards.push({...card, board_id:row.board_id, board_key:destination.key,
      list_id:row.list_id, lane:laneMeta.name,
      pos:row.position ?? card.pos, placement_version:row.version,
      sync_status:row.synced_version < row.version ? 'pending' : 'synced'});
    target.cards.sort((a,b) => (a.pos || 0) - (b.pos || 0));
    target.count = target.cards.length;
  }
  state.board.placement_snapshot = {...saved,
    boards:[...(saved.boards || []).filter(board => board.board_id !== meta.board_id), meta],
    placements:[...(saved.placements || []).filter(item => item.card_id !== cardId), row]};
  placementMutationGeneration++;
  if (card && state.board_loaded) { reconcileJobShelfWithBoard(); renderBoard(); }
  return {board:meta.name, lane:laneMeta.name, board_id:row.board_id, list_id:row.list_id};
}

async function openPlacementAction(cardId, action, options = {}) {
  const modalId = 'placement-action';
  const titles = {move:'Move card', archive:'Archive card', restore:'Restore card', delete:'Delete archived card'};
  const modal = openModal({id:modalId, title:titles[action], body:loadingIndicator('Loading saved card location…')});
  const body = modal.querySelector('.overlay-body');
  try {
    const data = await pywebview.api.card_placement_context(cardId);
    if (!modal.isConnected) return;
    if (!data?.ok) throw new Error(data?.error || 'Card details unavailable');
    const row = data.placement;
    const isDestination = action === 'move' || action === 'restore';
    if (action === 'delete' && (!data.can_delete || row?.state !== 'archived'))
      throw new Error('Only an administrator can delete an archived card.');
    const boards = data.boards || [];
    body.innerHTML = `<p>${escapeHtml(row?.title || 'Selected job card')}</p>
      <p>${action === 'archive' ? 'Hide this card from its board. The job, files, history and other cards stay unchanged.' :
        action === 'delete' ? 'Remove this archived placement from OneLoss. The job and other cards are preserved. Its Trello card stays archived.' :
        'Choose where this card belongs. Other cards for the same job will not move.'}</p>
      ${isDestination ? `<label class="placement-field">Board<select data-board class="input">${boards.map(b =>
        `<option value="${escapeAttr(b.board_id)}">${escapeHtml(b.name)}</option>`).join('')}</select></label>
        <label class="placement-field">Section<select data-section class="input"></select></label>` : ''}
      <p data-error role="alert"></p><div class="placement-actions"><button class="btn modal-cancel">Cancel</button>
      <button class="btn ${action === 'delete' ? 'danger' : 'btn-primary'}" data-save>${titles[action]}</button></div>`;
    body.querySelector('.modal-cancel').onclick = () => closeModal(modalId);
    const boardSelect = body.querySelector('[data-board]');
    const sectionSelect = body.querySelector('[data-section]');
    const save = body.querySelector('[data-save]');
    if (isDestination) {
      if (row?.board_id) boardSelect.value = row.board_id;
      const fill = () => {
        const board = boards.find(b => b.board_id === boardSelect.value);
        const lanes = (board?.lists || []).filter(l => !l.closed).sort((a,b) => (a.pos||0)-(b.pos||0));
        sectionSelect.innerHTML = lanes.map(l => `<option value="${escapeAttr(l.id)}">${escapeHtml(l.name)}</option>`).join('');
        if (lanes.some(l => l.id === row?.list_id)) sectionSelect.value = row.list_id;
        save.disabled = !lanes.length;
      };
      boardSelect.onchange = fill; fill();
      (options.focus === 'app_lane' ? sectionSelect : boardSelect)?.focus({preventScroll:true});
    }
    save.onclick = async () => {
      if (save.disabled) return;
      save.disabled = true; save.textContent = 'Saving…';
      const selectedBoard = boardSelect?.value || null;
      const selectedSection = sectionSelect?.value || null;
      const destination = {board:boardSelect?.selectedOptions[0]?.textContent || '',
        lane:sectionSelect?.selectedOptions[0]?.textContent || '',board_id:selectedBoard,list_id:selectedSection};
      if (boardSelect) boardSelect.disabled = true;
      if (sectionSelect) sectionSelect.disabled = true;
      try {
        const result = await pywebview.api.card_placement_change(cardId, action, row?.version || 0,
          selectedBoard, selectedSection);
        if (!result?.ok) throw new Error(result?.error || 'Save failed');
        acceptPlacementResult(result);
        closeModal(modalId);
        options.onSaved?.(destination, result);
        setStatus('Saved in OneLoss · Trello sync queued', 'ok');
        if (document.getElementById('archived-cards')) await openArchivedCards();
      } catch (error) {
        body.querySelector('[data-error]').textContent = error.message || String(error);
        save.disabled = false; save.textContent = titles[action];
        if (boardSelect) boardSelect.disabled = false;
        if (sectionSelect) sectionSelect.disabled = false;
      }
    };
  } catch (error) { body.textContent = error.message || String(error); }
}

async function openArchivedCards() {
  const modal = openModal({id:'archived-cards', title:'Archived cards', width:760,
    body:loadingIndicator('Loading archived cards…')});
  const body = modal.querySelector('.overlay-body');
  try {
    const data = await pywebview.api.card_placement_context('');
    if (!modal.isConnected) return;
    if (!data?.ok) throw new Error(data?.error || 'Archive unavailable');
    const rows = (data.placements || []).filter(r => r.state === 'archived');
    body.innerHTML = `<label class="placement-field">Find archived card<input type="search" data-search class="input" placeholder="Job name"></label>
      <div class="placement-archive-list"></div><p data-sync role="status"></p>
      <button class="btn" data-retry>Retry pending Trello sync</button>`;
    const render = () => {
      const query = body.querySelector('[data-search]').value.toLowerCase();
      const filtered = rows.filter(r => r.title.toLowerCase().includes(query));
      body.querySelector('.placement-archive-list').innerHTML = filtered.length ? filtered.map(r => {
        const board = data.boards.find(b => b.board_id === r.board_id);
        const lane = (board?.lists || []).find(l => l.id === r.list_id);
        return `<article class="placement-archive-row"><div><strong>${escapeHtml(r.title)}</strong>
          <p>${escapeHtml([board?.name,lane?.name].filter(Boolean).join(' / '))}</p>
          <small>${escapeHtml(r.sync_error || (r.synced_version < r.version ? 'Saved · Trello sync pending' : 'Synced'))}</small></div>
          <div class="placement-actions"><button class="btn" data-restore="${escapeAttr(r.card_id)}">Restore…</button>
          ${data.can_delete ? `<button class="btn danger" data-delete="${escapeAttr(r.card_id)}">Delete…</button>` : ''}</div></article>`;
      }).join('') : '<p>No archived cards match this search.</p>';
      body.querySelectorAll('[data-restore]').forEach(b => b.onclick = () => openPlacementAction(b.dataset.restore,'restore'));
      body.querySelectorAll('[data-delete]').forEach(b => b.onclick = () => openPlacementAction(b.dataset.delete,'delete'));
    };
    body.querySelector('[data-search]').oninput = render;
    body.querySelector('[data-retry]').onclick = async () => {
      await pywebview.api.retry_card_placement_sync();
      body.querySelector('[data-sync]').textContent = 'Retry started. Reopen Archived cards to check the result.';
    };
    render();
  } catch(error) { body.textContent = error.message || String(error); }
}

function onCardContext(ev) {
  ev.preventDefault();
  openCardMenu(ev, ev.currentTarget);
}

async function openJobInfoEditor(data, audit, onSaved) {
  const client = data.client || audit.client || "";
  let schema;
  let loaded;
  try {
    [schema, loaded] = await Promise.all([
      pywebview.api.job_settings_schema(),
      pywebview.api.job_settings_load(client, "", data.card_id || ""),
    ]);
  } catch (error) {
    setStatus(`Job info could not load: ${error}`, "error");
    return;
  }
  if (!schema?.ok || !loaded?.ok) {
    setStatus(loaded?.error || schema?.error || "Job info could not load", "error");
    return;
  }
  const values = loaded.values || {};
  if (!loaded.loss_categories_explicit && !values.loss_categories) {
    const facts = (data.info_sections || []).flatMap(section => section.fields || []);
    values.loss_categories = facts.find(field => field.id === 'loss_categories')?.value || '';
  }
  const inherited = new Set(loaded.inherited || []);
  const fields = (schema.fields || []).filter(field => field.id !== 'loss_categories');
  const renderFields = (items) => items.map((field) => {
    const listId = field.options?.length ? `pipeline-job-info-${field.id}` : "";
    return `<label class="job-info-edit-field ${field.multiline ? 'job-info-edit-wide' : ''}"><span>${escapeHtml(field.label)}${inherited.has(field.id) ? " · from client" : ""}</span>
      ${field.multiline ? `<textarea rows="5" data-job-info-input="${escapeAttr(field.id)}">${escapeHtml(values[field.id] || '')}</textarea>` : `<input data-job-info-input="${escapeAttr(field.id)}" value="${escapeAttr(values[field.id] || "")}" ${listId ? `list="${escapeAttr(listId)}"` : ""}>`}
      ${listId ? `<datalist id="${escapeAttr(listId)}">${field.options.map((option) => `<option value="${escapeAttr(option.value)}"></option>`).join("")}</datalist>` : ""}</label>`;
  }).join("");
  const core = fields.filter((field) => field.core);
  const more = fields.filter((field) => !field.core);
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay job-info-edit-overlay";
  modal.innerHTML = `<div class="modal-box job-info-edit-card" role="dialog" aria-modal="true" aria-label="Edit job info">
    <header class="modal-head"><div><div class="modal-title">Edit job info</div><div class="modal-sub">${escapeHtml(client)}</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body"><div class="job-info-edit-grid">${renderFields(core)}</div>
      ${more.length ? `<details class="job-info-more"><summary>More fields (${more.length})</summary><div class="job-info-edit-grid">${renderFields(more)}</div></details>` : ""}
      <footer class="job-info-edit-actions"><span data-job-info-status role="status" aria-live="polite"></span><button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save job info</button></footer>
    </div></div>`;
  document.body.appendChild(modal);
  let dirty = false;
  modal.querySelectorAll("[data-job-info-input]").forEach((input) =>
    input.addEventListener("input", () => { dirty = true; }));
  const closeEditor = () => {
    if (dirty && !window.confirm("Discard your unsaved job-info changes?")) return;
    modal.remove();
  };
  modal.querySelector("[data-close]").addEventListener("click", closeEditor);
  modal.querySelector("[data-cancel]").addEventListener("click", closeEditor);
  modal.querySelector("[data-save]").addEventListener("click", async (event) => {
    const output = {};
    modal.querySelectorAll("[data-job-info-input]").forEach((input) => {
      const id = input.dataset.jobInfoInput;
      if (input.value !== (values[id] || "")) output[id] = input.value;
    });
    const button = event.currentTarget;
    const status = modal.querySelector("[data-job-info-status]");
    button.disabled = true;
    status.textContent = "Saving…";
    let result;
    try {
      result = await pywebview.api.job_settings_save(client, output, "", loaded.card_desc || "", data.card_id || "", loaded.loss_label_context || null, loaded.insurance_context || null);
      if (result?.insurance_context) loaded.insurance_context = result.insurance_context;
    } catch (error) {
      button.disabled = false;
      status.textContent = 'Save could not be confirmed. Your edits are still here; retry or reopen to check.';
      return;
    }
    if (result?.loss_label_context) {
      loaded.loss_label_context = result.loss_label_context;
      loaded.loss_labels_pending = !!result.loss_labels_pending;
    }
    if (!result?.ok) {
      button.disabled = false;
      status.textContent = result?.error || "Job info could not be saved";
      return;
    }
    dirty = false;
    if (result.loss_labels_pending) {
      Object.assign(values, output);
      loaded.loss_labels_pending = true;
      loaded.loss_label_context = result.loss_label_context || loaded.loss_label_context;
      button.disabled = false;
      button.textContent = 'Retry Trello sync';
      status.textContent = result.error || 'Loss types saved · Trello sync pending.';
      return;
    }
    modal.remove();
    setStatus(result.insurance_pending ? "Insurance saved in Dev · live Trello sync disabled" :
      result.pending_push ? "Job info saved · Trello sync pending" : "Job info saved", result.pending_push ? "warn" : "ok");
    await onSaved?.();
  });
  modal.querySelector("[data-job-info-input]")?.focus();
}

// ── Audit result modal (compact summary) ─────────────────────────
function workspaceContentFingerprint(data) {
  const {load_ms, cached, saved_at, source, deferred_loading, refresh_pending,
    comments, ...content} = data;
  return JSON.stringify(content);
}

// Partial projections can know less than the already-visible board preview.
function mergeWorkspaceRefresh(current, next, refreshJobLog = false) {
  const merge = (a, b) => {
    const out = {...a};
    for (const [key, value] of Object.entries(b || {})) {
      if (value && !Array.isArray(value) && typeof value === 'object') out[key] = merge(a?.[key] || {}, value);
      else if (!(next.deferred_loading && (value === '' || (Array.isArray(value) && !value.length)))) out[key] = value;
    }
    return out;
  };
  const result = merge(current, next);
  const logLoaded = Array.isArray(current.crm?.job_log) &&
    (current.crm.job_log_source === 'local_db' || current.crm.job_log_saved_at || !current.deferred_loading);
  if (logLoaded && !refreshJobLog) {
    result.crm = {...result.crm};
    for (const [key, value] of Object.entries(current.crm)) {
      if (key === 'job_log' || key.startsWith('job_log_')) result.crm[key] = value;
    }
  }
  if (logLoaded && !refreshJobLog) {
    // User-controlled log: unrelated card updates cannot replace its rows.
  } else if ((next.crm?.job_log_error || next.crm?.ok === false) && current.crm?.job_log?.length) {
    result.crm = {...result.crm, job_log: current.crm?.job_log || []};
  } else if (Array.isArray(next.crm?.job_log)) {
    // Missing rows in a late/partial response are not deletion evidence.
    const rows = new Map((current.crm?.job_log || []).map(row => [row.entry_id, row]));
    for (const row of next.crm.job_log) {
      const old = rows.get(row.entry_id);
      if (!old || (Date.parse(row.updated_at) || 0) >= (Date.parse(old.updated_at) || 0)) rows.set(row.entry_id, row);
    }
    const deleted = [...new Set([...(current.crm?.job_log_deleted_ids || []), ...(next.crm.job_log_deleted_ids || [])])];
    const sourceKey = value => { try { return JSON.stringify(JSON.parse(value)); } catch (_) { return value; } };
    const deletedSources = [...new Set([...(current.crm?.job_log_deleted_sources || []), ...(next.crm.job_log_deleted_sources || [])].map(sourceKey))];
    for (const [id, row] of rows) {
      if (row.source === 'trello' && row.source_id && deletedSources.includes(JSON.stringify([row.placement_card_id || '', row.source_id]))) {
        rows.delete(id); if (!deleted.includes(id)) deleted.push(id);
      }
    }
    for (const id of deleted) rows.delete(id);
    result.crm = {...result.crm, job_log:[...rows.values()], job_log_deleted_ids:deleted, job_log_deleted_sources:deletedSources};
  }
  const sections = (current.info_sections || []).map(s => ({...s, fields: (s.fields || []).map(f => ({...f}))}));
  for (const section of next.info_sections || []) for (const field of section.fields || []) {
    if (!String(field.value ?? '').trim() && field.id !== 'loss_categories') continue;
    const owner = sections.find(s => s.fields.some(f => f.id === field.id));
    if (owner) Object.assign(owner.fields.find(f => f.id === field.id), field);
    else {
      let target = sections.find(s => s.name === section.name);
      if (!target) { target = {...section, fields: []}; sections.push(target); }
      target.fields.push({...field});
    }
  }
  result.info_sections = sections;
  result.deferred_loading = Boolean(next.deferred_loading);
  result.refresh_pending = Boolean(next.refresh_pending);
  return result;
}

function updateWorkspaceModel(target, source) {
  // Retained buttons close over these objects. Keep their references current.
  for (const [key, value] of Object.entries(source)) {
    if (value && !Array.isArray(value) && typeof value === 'object' && target[key] && !Array.isArray(target[key]) && typeof target[key] === 'object') updateWorkspaceModel(target[key], value);
    else target[key] = value;
  }
}

function workspaceSectionKey(node) {
  return node.tagName + ':' + [...node.classList].filter(c => c !== 'aud-section' && c !== 'compact-section').join('.');
}

function retainWorkspaceSectionView(previous, incoming) {
  // Selection/expansion belongs to the reader, not to the refreshed payload.
  // Apply it before comparing DOM so unchanged sections stay untouched.
  const role = previous.querySelector('[data-checklist-role][aria-selected="true"]')?.dataset.checklistRole;
  if (role && incoming.querySelector(`[data-checklist-role="${cssEsc(role)}"]`)) {
    incoming.querySelectorAll('[data-checklist-role]').forEach(tab => {
      const active = tab.dataset.checklistRole === role;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    incoming.querySelectorAll('[data-checklist-pane]').forEach(pane => {
      const active = pane.dataset.checklistPane === role;
      pane.classList.toggle('active', active);
      pane.hidden = !active;
    });
  }
  const detailKey = node => JSON.stringify([
    node.closest('[data-job-log-id]')?.dataset.jobLogId || '',
    node.className, node.querySelector(':scope > summary')?.textContent || ''
  ]);
  const expanded = new Map([...previous.querySelectorAll('details')].map(node => [detailKey(node), node.open]));
  incoming.querySelectorAll('details').forEach(node => {
    if (expanded.has(detailKey(node))) node.open = expanded.get(detailKey(node));
  });
  for (const selector of ['[data-log-party-filter]', '[data-log-company-filter]']) {
    const old = previous.querySelector(selector), next = incoming.querySelector(selector);
    if (old && next && [...next.options].some(o => o.value === old.value)) next.value = old.value;
  }
  incoming.querySelector('[data-log-party-filter]')?.dispatchEvent(new Event('change'));
  if (previous.tagName === 'DETAILS') incoming.open = previous.open;
}

function patchJobLogSection(previous, incoming) {
  const list = previous.querySelector('[data-job-log-list]');
  const nextList = incoming.querySelector('[data-job-log-list]');
  if (!list || !nextList) return false;
  const existing = new Map([...list.querySelectorAll('[data-job-log-id]')].map(node => [node.dataset.jobLogId, node]));
  const desired = [...nextList.children].map(node => {
    const old = existing.get(node.dataset.jobLogId);
    return old?.isEqualNode(node) ? old : node;
  });
  const keep = new Set(desired);
  for (const node of [...list.children]) if (!keep.has(node)) node.remove();
  desired.forEach((node, index) => {
    if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
  });
  // Keep the incoming handlers/current division attached to all toolbar actions.
  const oldToolbar = previous.querySelector('.job-log-toolbar');
  const nextToolbar = incoming.querySelector('.job-log-toolbar');
  if (oldToolbar && nextToolbar) oldToolbar.replaceWith(nextToolbar);
  for (const selector of ['[data-log-filters]', '[data-log-filter-empty]']) {
    const old = previous.querySelector(selector), node = incoming.querySelector(selector);
    if (old && node) old.replaceWith(node);
  }
  for (const selector of ['.section-title-row', '[data-job-log-status]']) {
    const old = previous.querySelector(selector), node = incoming.querySelector(selector);
    if (old && node && !old.isEqualNode(node)) old.replaceWith(node);
  }
  return true;
}

function patchWorkspaceSections(root, prepared, editedSections, refreshJobLog = false) {
  const scrollPositions = [...root.querySelectorAll('.modal-body, .job-card-main, .job-workspace-panel')].map(node => [node, node.scrollTop, node.scrollLeft]);
  for (const panel of prepared.querySelectorAll('.job-workspace-panel')) {
    const live = root.querySelector('#' + panel.id);
    if (!live) continue;
    const existing = new Map([...live.children].map(node => [workspaceSectionKey(node), node]));
    const incoming = new Set();
    for (const node of [...panel.children]) {
      const id = workspaceSectionKey(node); incoming.add(id);
      const old = existing.get(id);
      if (!old) { live.append(node); continue; }
      if (old.classList.contains('job-files-section')) continue;
      if (old.classList.contains('job-timing-section') && old.dataset.timingCard === node.dataset.timingCard) continue;
      if (old.classList.contains('job-run-section') && old._runActivity) continue;
      const explicitLogRefresh = refreshJobLog && old.classList.contains('job-log-section');
      if ((!explicitLogRefresh && (editedSections.has(id) || old.contains(document.activeElement))) || old.querySelector('[data-job-log-editor]:not([hidden])')) continue;
      retainWorkspaceSectionView(old, node);
      if (old.isEqualNode(node)) continue;
      if (old.classList.contains('job-log-section') && patchJobLogSection(old, node)) continue;
      const scroll = old.scrollTop;
      if (old.tagName === 'DETAILS') node.open = old.open;
      old.replaceWith(node); node.scrollTop = scroll;
    }
    for (const [id, old] of existing) if (!incoming.has(id) && !editedSections.has(id) && !old.contains(document.activeElement)) old.remove();
  }
  for (const selector of ['.modal-head', '.modal-foot', '.division-conflict-banner']) {
    const old = root.querySelector(selector), node = prepared.querySelector(selector);
    if (old && node && !old.contains(document.activeElement) && !old.isEqualNode(node)) old.replaceWith(node);
    else if (!old && node && selector === '.division-conflict-banner') root.querySelector('.job-card-main').prepend(node);
    else if (old && !node && selector === '.division-conflict-banner') old.remove();
  }
  for (const [node, top, left] of scrollPositions) { node.scrollTop = top; node.scrollLeft = left; }
  for (const timing of root.querySelectorAll('.job-timing-section')) {
    if (timing._timing && !timing.childElementCount) timing._timing.activate();
  }
}

function savedDocuSketchUrl(sections) {
  return savedJobLinkUrl(sections, 'link_docusketch');
}

function savedJobLinkUrl(sections, fieldId) {
  const value = (sections || []).flatMap(section => section.fields || [])
    .find(field => field.id === fieldId)?.value;
  try {
    const url = new URL(String(value || '').trim());
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
  } catch (_) { return ''; }
}

function jobSummaryCopyText(sections) {
  const fields = Object.fromEntries((sections || []).flatMap(section => section.fields || [])
    .map(field => [field.id, String(field.value ?? '').trim()]));
  const groups = [
    ['CUSTOMER INFORMATION', [
      ['Customer Name', 'customer_name'], ['Address', 'address'], ['Phone Number', 'phone'],
      ['Email', 'email'], ['Additional Contacts', 'addl_contacts', 'additional_contacts'],
      ['Source of Lead', 'source_of_lead']]],
    ['INSURANCE INFORMATION', [
      ['Inspection Fee (Self Pay)', 'inspection_fee'], ['Insurance Company', 'carrier'],
      ['Claim Number', 'claim_number'], ['Adjuster Name', 'adjuster_name'],
      ['Adjuster Email', 'adjuster_email'], ['Adjuster Number', 'adjuster_phone'],
      ['Deductible', 'deductible'], ['Agent Name', 'agent_name']]],
  ];
  return groups.map(([heading, rows]) => heading + '\n\n' + rows.map(([label, ...ids]) => {
    const value = ids.map(id => fields[id]).find(value => value !== undefined && value !== '') || '';
    return `${label}:${value ? (value.includes('\n') ? '\n' : ' ') + value : ''}`;
  }).join('\n\n')).join('\n\n');
}

function customerInfoCopyText(sections) {
  const ids = new Set(['customer_name', 'phone', 'email', 'address', 'carrier',
    'claim_number', 'adjuster', 'adjuster_name', 'adjuster_email', 'adjuster_phone', 'deductible']);
  const seen = new Set();
  return (sections || []).flatMap(section => (section.fields || []).filter(field =>
    ids.has(field.id) || /^(customer|insurance) information$/i.test(section.name || '')))
    .filter(field => {
      const key = field.id || field.label;
      if (!String(field.value ?? '').trim() || seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map(field => `${field.label || field.id}: ${String(field.value).trim()}`).join('\n');
}

function positionDevCommentComposer(root, data) {
  const pane = root.querySelector('.job-card-activity');
  const head = pane?.querySelector('.activity-head');
  const compose = pane?.querySelector('.comment-compose');
  const search = pane?.querySelector('.comment-search-tools');
  if (head && compose && search) {
    pane.classList.add('dev-compact-comments');
    // Moving an already-positioned editor detaches it and drops typing focus.
    // Background workspace loads must leave the live composer untouched.
    if (head.nextElementSibling !== compose) head.after(compose);
    if (compose.nextElementSibling !== search) compose.after(search);
    const toggle = pane.querySelector('[data-toggle-comment-search]');
    const post = compose.querySelector('[data-post-comment]');
    if (toggle && post && post.previousElementSibling !== toggle) post.before(toggle);
  }
}

function openAuditModal(data, trelloUrl = "", preparation = null) {
  const res = data.audit || {};
  if (data.folder_error) res.path = '';
  const crm = data.crm || {};
  const emptyWorkspaceText = (subject, empty, error = res.trello_error) => error
    ? `${subject} could not be checked. Try refreshing.`
    : data.deferred_loading || data.refresh_pending ? `Loading ${subject.toLowerCase()}…` : empty;
  const workspace = data.workspace || {};
  const issues = [...(res.form_issues || []), ...(res.photo_issues || []), ...(res.requirements || [])];
  const clean = res.found && !issues.length;
  const currentPlacement = appCardPlacement(data.card_id);
  const placement = currentPlacement.lane ? currentPlacement : (data.app_placement || {});
  const cardDue = data.card_due ?? placement.due ?? '';
  const locationSection = {name: 'App location', fields: [
    {id:'app_board',label:'Board',value:placement.board || ''},
    {id:'app_lane',label:'Lane / section',value:placement.lane || 'App location not loaded'}
  ]};
  const detailSections = (data.info_sections || []).filter(section => !['Pipeline','App location'].includes(section.name));
  const isScopeSection = section => (section.fields || []).some(field => ['scope_initial','scope_additional'].includes(field.id));
  const populatedInfoSections = [locationSection, ...detailSections.filter(section => !isScopeSection(section)), ...detailSections.filter(isScopeSection)].map((section) => ({
    ...section,
    fields: (section.fields || []).filter((field) => String(field.value || "").trim()),
  })).filter((section) => section.fields.length);
  const overviewFields = detailSections.flatMap(section => section.fields || []);
  const overviewTopIds = new Set(['address','poc_name','poc_phone','poc_email','phone','email']);
  const overviewPencil = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15z"/></svg>';
  const overviewCopyIcon = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M15 8V4H4v11h4"/></svg>';
  const overviewEdit = label => `<button type="button" class="overview-edit" data-edit-job-info title="Edit job information" aria-label="Edit ${escapeAttr(label)}">${overviewPencil}</button>`;
  const overviewTopField = (id,label) => {
    const field=overviewFields.find(f=>f.id===id);
    return String(field?.value || '').trim() ? `<button type="button" class="job-info-field" data-copy-job-field="${escapeAttr(field.value)}" data-copy-job-label="${escapeAttr(field.label || label)}" title="${escapeAttr(field.label || label)}: ${escapeAttr(field.value)}&#10;Click to copy"><span>${escapeHtml(field.label || label)}</span><strong>${escapeHtml(field.value)}</strong><i aria-hidden="true">${overviewCopyIcon}</i></button>` : `<div class="overview-missing"><span>${escapeHtml(label)}</span><strong>Not provided</strong></div>`;
  };
  const hasPoc = overviewFields.some(f=>['poc_name','poc_phone','poc_email'].includes(f.id) && String(f.value || '').trim());
  const overviewTop = `<div class="overview-top"><div class="overview-top-block"><header><h4>Job location</h4>${overviewEdit('job location')}</header>${overviewTopField('address','Address')}</div><div class="overview-top-block"><header><h4>${hasPoc ? 'Point of contact' : 'Customer contact'}</h4>${overviewEdit('contact information')}</header>${hasPoc ? ['poc_name','poc_phone','poc_email'].map((id,i)=>overviewTopField(id,['Name','Phone','Email'][i])).join('') : overviewTopField('phone','Phone')+overviewTopField('email','Email')}</div></div>`;
  const compactSections = [...populatedInfoSections.filter(s=>s.name!==locationSection.name), ...populatedInfoSections.filter(s=>s.name===locationSection.name)];
  const descReview = data.description_review;
  const descSuggestions = (descReview?.suggestions || []).map(field => `<li><b>${escapeHtml(field.label)}</b><span>${escapeHtml(field.value)}</span></li>`).join('');
  const descriptionReview = descReview ? `<div class="description-review">
    <details><summary>Additional Trello details</summary><p>Text that may need review. Some details may also appear above.</p><pre>${escapeHtml(descReview.additional || 'No additional lines found.')}</pre></details>
    <details><summary>Review Trello field mapping</summary><p>Values read from this card. Compare these with the saved Overview; nothing is changed here.</p>${descSuggestions ? `<ul>${descSuggestions}</ul>` : '<p>No standard fields recognized.</p>'}</details>
    <details><summary>Original Trello description</summary><pre>${escapeHtml(descReview.original || 'This card has no description.')}</pre>${descReview.original ? '<button type="button" class="btn compact" data-copy-description>Copy description</button>' : ''}</details>
  </div>` : `<div class="description-review"><small>Trello description has not loaded for this card.</small></div>`;
  const facts = overviewTop + compactSections.map(section=>({...section, fields:section.fields.filter(f=>!overviewTopIds.has(f.id) || (hasPoc && ['phone','email'].includes(f.id)))})).filter(s=>s.fields.length).map((section) => `
    <div class="job-info-group"><header><h4>${escapeHtml(section.name === 'Property Details' ? 'Loss & property' : section.name)}</h4>${overviewEdit(section.name)}</header>
      <div class="job-info-grid">${section.fields.map((field) =>
        `<button type="button" class="job-info-field ${['scope_initial','scope_additional'].includes(field.id) ? 'job-scope-field' : ''}" ${['app_board','app_lane'].includes(field.id)
          ? `data-move-job-location="${field.id}" aria-haspopup="dialog" title="${escapeAttr(field.label)}: ${escapeAttr(field.value)}&#10;Click to change" ${data.card_id ? '' : 'disabled'}`
          : `data-copy-job-field="${escapeAttr(field.value)}" data-copy-job-label="${escapeAttr(field.label)}" title="${escapeAttr(field.label)}: ${escapeAttr(field.value)}&#10;Click to copy"`}>
          <span>${escapeHtml(field.label)}</span><strong>${escapeHtml(field.value)}</strong><i aria-hidden="true">${['app_board','app_lane'].includes(field.id) ? 'Move ▾' : overviewCopyIcon}</i>
        </button>`).join("")}</div>
    </div>`).join("");
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
  const mapAddress = String(copyField('address') || '').trim();
  const claimNumber = copyField("claim_number");
  const lossCategories = copyFacts.some(field=>field.id==='loss_categories') ? copyField('loss_categories') : copyField('loss_type');
  const headerTags = [...new Set([copyField('carrier'), ...(window.CardLabels ? [] : String(lossCategories || '').split(','))]
    .map(value => String(value || '').trim()).filter(Boolean))];
  const headerTagsHtml = headerTags.length ? `<div class="job-header-tags" aria-label="Insurance and loss types">${headerTags.map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div>` : '';
  const activity = (res.activity || []).length
    ? `<div class="aud-chips">${res.activity.map((a) => `<span>${escapeHtml(a)}</span>`).join("")}</div>`
    : `<div class="aud-empty">No activity recorded for this run.</div>`;
  const progress = crm.progress || {};
  const paperwork = crm.paperwork || { items: [], counts: {} };
  const paperworkState = {
    present: ["✓", "On file"], missing: ["!", "Missing"],
    unknown: ["?", "Not checked"], not_due: ["–", "Not due"],
    not_applicable: ["–", "N/A"],
  };
  const paperworkRows = (paperwork.items || []).map((item) => {
    const state = paperworkState[item.status] || paperworkState.unknown;
    return `<div class="paperwork-row paperwork-${escapeAttr(item.status || "unknown")}">
      <span class="paperwork-mark" aria-hidden="true">${state[0]}</span>
      <span><strong>${escapeHtml(item.label || "")}</strong><small>${escapeHtml(item.source || "Stored job data")}</small></span>
      <b>${state[1]}</b>
      <div class="paperwork-actions"><div class="paperwork-matches">${(item.files || []).map(file => {
        const name = String(file).split(/[\\/]/).pop();
        const current = item.file_confirmed && String(file).replaceAll('\\', '/').endsWith('/' + item.confirmed_file);
        return `<div class="paperwork-match">
          <button type="button" class="paperwork-file-link" title="${escapeAttr(file)}" aria-label="Open matched file" data-open-form-match data-form-label="${escapeAttr(item.label)}" data-form-file="${escapeAttr(file)}">${escapeHtml(name)}</button>
          <button type="button" class="btn compact paperwork-confirm" title="Confirm this file belongs in this form slot; does not mark it signed or complete" data-confirm-form-match data-form-label="${escapeAttr(item.label)}" data-form-file="${escapeAttr(file)}" ${current ? 'disabled' : ''}>${current ? 'Confirmed' : item.file_confirmed ? 'Use this file' : 'Confirm'}</button>
          <details class="paperwork-file-menu"><summary aria-label="Actions for ${escapeAttr(name)}" title="File actions">⋯</summary><div class="paperwork-file-options">
          ${jobFormAction(item.label, item.status).replace('Prepare blank form', 'Prepare another form')}
          </div></details></div>`;
      }).join('')}<small data-form-match-feedback role="status"></small></div>
      ${(item.files || []).length ? '' : jobFormAction(item.label, item.status).replace('Prepare blank form', 'Prepare form')}
      </div>
    </div>`;
  }).join("");
  const paperworkSummary = paperwork.audit_complete
    ? `${paperwork.profile_name || 'Standard'} · ${paperwork.counts?.present || 0} on file · ${paperwork.counts?.missing || 0} missing · ${paperwork.counts?.unknown || 0} not checked`
    : `${paperwork.profile_name || 'Standard'} · file evidence not checked yet`;
  const docuSketchAccess = `<div class="paperwork-row paperwork-unknown" data-docusketch-folder role="status"><span class="paperwork-mark" aria-hidden="true">?</span><span><strong>DocuSketch</strong><small>${res.path ? 'Checking for a DocuSketch folder…' : 'Pin a job folder to check for DocuSketch files'}</small></span><b>Not checked</b></div>`;
  const profileChoices = crm.job_profile_suggestions || [];
  const workTypeState = Object.fromEntries((crm.work_environments || []).map((env) =>
    [String(env.work_environment || "").toLowerCase(), env]));
  const contractDivisionCards = (workspace.divisions || []).map((division) => ({
    division: division.type,
    ...(division.external_references?.trello || {}),
    card_id: division.external_references?.trello?.id || "",
  }));
  const workspaceDivisionCards = contractDivisionCards.length
    ? contractDivisionCards
    : (data.division_trello_cards || []);
  const divisionCards = Object.fromEntries(workspaceDivisionCards.map((card) =>
    [String(card.division || "").toLowerCase(), card]));
  const workTypeStagesFor = (name) => [
    ["not_applicable", "Not part of this job"],
    ...(name === "EMS" ? [] : [["interested", "Interested"]]),
    ["waiting", "Awaiting scheduling"], ["scheduled", "Scheduled"], ["active", "Active"],
    ["ready_for_billing", "Ready to bill"], ["on_hold", "On hold"],
    ["closeout", "Closeout / completed"],
  ];
  const visibleWorkStage = (stage) => ({
    planned: "waiting", billing: "ready_for_billing",
    mitigation: "active", closed: "closeout",
  })[stage] || stage;
  const pinnedDivisionCards = workspaceDivisionCards.filter((card) => card.pinned);
  const divisionPlacements = data.division_trello_placements || [];
  const selectedDivision = String(workspace.selected_division || data.selected_division || "EMS").toUpperCase();
  const blockedDivisionTargets = new Set((data.division_card_reconciliation?.divisions || [])
    .filter(item => ['conflict', 'ambiguous'].includes(item.state)).map(item => String(item.division).toUpperCase()));
  const divisionTargets = {};
  for (const division of ['EMS', 'CONTENTS', 'RECON']) {
    const candidates = workspaceDivisionCards.filter(card => String(card.division).toUpperCase() === division && card.card_id && card.pinned !== false && !card.conflict);
    const ids = new Set(candidates.map(card => card.card_id));
    const target = candidates[0];
    const shared = target && workspaceDivisionCards.some(card => String(card.division).toUpperCase() !== division && card.card_id === target.card_id);
    if (ids.size === 1 && !shared && !blockedDivisionTargets.has(division)) divisionTargets[division] = target;
  }
  const divisionDataTabs = `<div class="job-division-folder-tabs" role="tablist" aria-label="Job division">
    ${['EMS', 'CONTENTS', 'RECON'].map(division => {
      const active = division === selectedDivision;
      const disabled = !active && !divisionTargets[division];
      return `<button type="button" role="tab" data-division-data="${division}" data-unlinked="${disabled}" aria-selected="${active}" tabindex="${active ? 0 : -1}" title="${disabled ? 'Link a card — click or right-click' : 'Open ' + division + ' job and comments'}">${division === 'CONTENTS' ? 'Contents' : division === 'RECON' ? 'Recon' : 'EMS'}</button>`;
    }).join('')}
  </div>`;
  const checklistDivisionTabs = `<div class="checklist-division-tabs" role="tablist" aria-label="Checklist division">
    ${["EMS", "CONTENTS", "RECON"].map((division) => {
      const linked = pinnedDivisionCards.some((card) => card.division === division);
      const label = division === "EMS" ? "💧 EMS" : division === "CONTENTS" ? "▣ Contents" : "🔨 Recon";
      return `<button type="button" role="tab" data-checklist-division="${division}" data-linked="${linked}" aria-selected="${division === selectedDivision ? "true" : "false"}" class="${division === selectedDivision ? "active" : ""}" title="${linked ? `Open ${label} checklist` : `${label} checklist · no Trello card linked yet`}">${label}${linked ? "" : " ·"}</button>`;
    }).join("")}
  </div>`;
  const workTypes = [["EMS", "💧", "Mitigation"], ["Contents", "▣", "Contents"], ["Recon", "🔨", "Reconstruction"]]
    .filter(([name]) => !snapshotCardMode || name.toUpperCase() === selectedDivision.toUpperCase())
    .map(([name, icon, label]) => {
      const env = workTypeState[name.toLowerCase()] || {};
      const trello = divisionCards[name.toLowerCase()] || {};
      const extraPlacements = divisionPlacements.filter((item) =>
        String(item.division || "").toLowerCase() === name.toLowerCase() &&
        item.card_id && !item.primary && item.card_id !== trello.card_id);
      const stage = visibleWorkStage(env.stage || "not_applicable");
      const workTypeStages = workTypeStagesFor(name);
      // Imported pipeline stages need not match the editable status vocabulary.
      // Preserve unknown values visibly instead of letting the browser select
      // the first option ("Not part of this job") for an involved division.
      if (!workTypeStages.some(([value]) => value === stage)) {
        workTypeStages.push([stage, stage === 'unverified' ? 'Status not verified' : `Current: ${String(stage).replaceAll('_', ' ')}`]);
      }
      return `<div class="work-type work-type-${name.toLowerCase()} ${stage !== "not_applicable" ? "has-stage" : ""}" data-work-type-card="${name}">
        <div class="work-type-head"><span aria-hidden="true">${icon}</span><div><strong>${label}</strong><small>${name}${env.inferred ? ` · Detected from ${(env.detected_sources || []).join(" + ")}` : ""}</small></div></div>
        ${stage === 'not_applicable' ? '<details class="inactive-division-tools" open><summary>Manage division</summary>' : ''}
        <div class="division-trello ${trello.pinned ? "is-pinned" : ""}">
          <span>${trello.pinned ? "📌 Trello card pinned" : "○ No Trello card"}</span>
          <div>${trello.pinned ? `<button class="text-btn" data-division-trello-open="${name}">Open</button>` : ""}
          ${data.card_id && data.card_id !== trello.card_id ? `<button class="text-btn" data-division-trello-use="${name}">Use open card</button>` : ""}
          <button class="text-btn" data-division-trello-pin="${name}">${trello.pinned ? "Change" : "Link card"}</button>
          ${trello.pinned ? `<button class="text-btn danger" data-division-trello-remove="${name}">Remove</button>` : ""}</div>
          ${name === "EMS" && trello.pinned ? `<button class="text-btn" data-create-ems-copy>Create linked placeholder…</button><button class="text-btn" data-link-ems-copy>Link WIP / Estimating copy</button>` : ""}
          ${name === 'Recon' ? '<small>Existing cards only. No Recon card will be created.</small>' : ''}
          ${extraPlacements.length ? `<div class="division-placement-list">${extraPlacements.map((item) => `<button class="division-placement" data-placement-open="${escapeAttr(item.url || `https://trello.com/c/${item.card_id}`)}"><span>Also on ${escapeHtml(item.board || item.purpose || "linked board")}</span><small>${escapeHtml(item.lane || "Open card")}</small></button>`).join("")}</div>` : ""}
        </div>
        ${stage === 'not_applicable' ? '</details>' : ''}
      </div>`;
    }).join("");
  const checklistRoles = [
    ["intake", "Intake"], ["admin", "Admin"], ["coord", "Coordinator"],
    ["field", "Field"], ["est", "Estimating"], ["misc", "Misc"],
  ];
  const checklistRole = (name) => {
    const normalized = String(name || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (normalized === "intake") return "intake";
    if (normalized === "estimating" || /\s-\s*estimating$/.test(normalized)) return "est";
    if (/\s-\s*admin$/.test(normalized) || ["initial", "in progress", "close out", "closeout"].includes(normalized)) return "admin";
    if (/\s-\s*coordinator$/.test(normalized) || normalized === "contents") return "coord";
    if (/\s-\s*field(\s+leads?)?$/.test(normalized) || /\bfield\s+leads?\b/.test(normalized)) return "field";
    return "misc";
  };
  const checklistByRole = Object.fromEntries(checklistRoles.map(([key]) => [key, []]));
  const displayChecklists = window.checklistDisplayLists ? window.checklistDisplayLists(data, selectedDivision) : (data.checklists || []);
  const checklistPending = displayChecklists.some(list => list.pending);
  displayChecklists.forEach((list) => checklistByRole[checklistRole(list?.name)].push(list));
  const visibleChecklistRoles = checklistRoles.filter(([key]) => checklistByRole[key].length);
  const firstChecklistRole = visibleChecklistRoles[0]?.[0] || "intake";
  const renderChecklist = (list) => {
    const items = list.items || [];
    const done = items.filter((item) => item.complete).length;
    return `<div class="trello-checklist" data-checklist-id="${escapeAttr(list.id)}"><div class="checklist-title"><h4>${escapeHtml(list.name || "Checklist")}</h4><span>${list.pending ? 'Loading marks…' : `${done}/${items.length}`}</span></div>
      <div class="checklist-progress" ${list.pending ? 'hidden' : ''}><i style="width:${items.length ? Math.round((done / items.length) * 100) : 0}%"></i></div>
      ${items.map((item) => {
        return `<div class="check-item-line"><label class="check-row ${item.complete ? "checked" : ""}">
        ${list.pending ? '<span class="check-mark-pending" aria-label="Status loading">…</span>' : `<input type="checkbox" data-check-item="${escapeAttr(item.id)}" data-check-name="${escapeAttr(item.name || "")}" ${item.complete ? "checked" : ""}/>`}
        <span>${escapeHtml(item.name || "")}</span></label><button type="button" class="check-item-edit" data-edit-check-item="${escapeAttr(item.id)}" ${list.pending ? 'disabled' : ''} title="Edit item" aria-label="Edit ${escapeAttr(item.name || 'item')}">✎</button></div>`;
      }).join("") || `<div class="aud-empty">No items</div>`}
      <button type="button" class="check-item-add" data-add-check-item ${list.pending ? 'disabled' : ''}>＋ Add item</button>
    </div>`;
  };
  const checklistGroups = visibleChecklistRoles.length ? `
    <div class="checklist-role-tabs" role="tablist" aria-label="Checklist responsibility">
      ${visibleChecklistRoles.map(([key, label]) => {
        const lists = checklistByRole[key];
        const total = lists.reduce((sum, list) => sum + (list.items || []).length, 0);
        const done = lists.reduce((sum, list) => sum + (list.items || []).filter((item) => item.complete).length, 0);
        return `<button type="button" role="tab" data-checklist-role="${key}" aria-selected="${key === firstChecklistRole ? "true" : "false"}" class="${key === firstChecklistRole ? "active" : ""}">${label}<span>${checklistPending ? '…' : `${done}/${total}`}</span></button>`;
      }).join("")}
    </div>
    <div class="checklist-role-panes">${visibleChecklistRoles.map(([key]) => `
      <div class="checklist-role-pane ${key === firstChecklistRole ? "active" : ""}" data-checklist-pane="${key}" ${key === firstChecklistRole ? "" : "hidden"}>
        ${checklistByRole[key].map(renderChecklist).join("")}
      </div>`).join("")}</div>` : `<div class="aud-empty">${emptyWorkspaceText('Checklists', 'No checklist has been added to this job.')}</div>`;
  const logs = (crm.job_log || []).slice().sort((a,b)=>String(b.work_date||'').localeCompare(String(a.work_date||''))||String(b.created_at||'').localeCompare(String(a.created_at||''))).map((entry) => `
    <article class="job-log-row snapshot-log-row" data-job-log-id="${escapeAttr(entry.entry_id || "")}">
      <div class="job-log-date"><time>${escapeHtml(formatAppDate(entry.work_date || ""))}</time><span>${escapeHtml((entry.status || "completed").replaceAll("_", " "))}</span></div><div class="job-log-copy">
      <div class="job-log-title"><strong>${escapeHtml(entry.work_type || "Job update")}</strong>${entry.work_party === 'subcontractor' ? `<span>Sub · ${escapeHtml(entry.subcontractor || '')}</span>` : ''}${entry.technicians ? entry.technicians.split(' | ').map(person => `<span>${escapeHtml(person)}</span>`).join('') : ""}</div>
      ${entry.source !== "trello" && entry.note ? `<div class="job-log-field"><b>Update</b><p>${escapeHtml(entry.note)}</p></div>` : ""}
      ${entry.equipment ? `<div class="job-log-field"><b>Equipment / readings</b><p>${escapeHtml(entry.equipment)}</p></div>` : ""}
      ${entry.source === "trello" && entry.note ? `<details class="job-log-source"><summary>Original Trello comment</summary><div><small>Imported from the ${escapeHtml(selectedDivision)} card${entry.updated_by ? ` · ${escapeHtml(entry.updated_by)}` : ""}</small><p>${escapeHtml(entry.note)}</p></div></details>` : ""}</div>
      <div class="job-log-actions"><button class="text-btn" data-history-job-log="${escapeAttr(entry.entry_id || "")}">History</button><button class="text-btn" data-edit-job-log="${escapeAttr(entry.entry_id || "")}">Edit</button>
      <button class="text-btn danger" data-delete-job-log="${escapeAttr(entry.entry_id || "")}">Delete log entry</button></div></article>`).join("") || `<div class="aud-empty">${emptyWorkspaceText('Job Log entries', 'No Job Log updates yet.', crm.job_log_error || crm.ok === false)}</div>`;
  const docs = data.documents || {};
  const dsRequest = docs.request || {};
  const documentRows = (data.deferred_loading || res.audit_pending) && !(docs.files || []).length
    ? `<div class="aud-empty">No saved document index yet. Run an audit to check files.</div>`
    : (docs.files || []).map((file) => `<button class="signature-file" data-document-path="${escapeAttr(file.path || "")}">
    <span class="signature-file-mark">${file.signed ? "✓" : "□"}</span><span><strong>${escapeHtml(file.name || "Document")}</strong>
    <small>${file.signed ? "Signed/final paperwork" : "Job document"}${file.modified_at ? " · " + escapeHtml(formatCommentDate(file.modified_at)) : ""}</small></span></button>`).join("") || `<div class="aud-empty">No PDFs or Word documents found in this job’s DOCS folders.</div>`;
  const signatureState = dsRequest.state === "pending_signature" ? "Signature pending"
    : dsRequest.state === "pending_email" ? "Needs customer email"
    : (docs.files || []).some((file) => file.signed) ? "Signed file received" : "Not sent";
  const attachments = (data.attachments || []).map((a) =>
    `<button class="attachment-row" data-attachment-url="${escapeAttr(a.url || "")}">📎 ${escapeHtml(a.name || "Attachment")}</button>`).join("") || `<div class="aud-empty">${emptyWorkspaceText('Attachments', 'No attachments.')}</div>`;
  const comments = (data.comments || []).map(renderJobComment).join("");
  const divisionConflicts = (data.division_card_reconciliation?.divisions || [])
    .filter((item) => item.state === "conflict");
  const divisionConflictBanner = divisionConflicts.length ? `<div class="division-conflict-banner" role="alert">
    <strong>⚠ Review Trello card links</strong>
    <span>${divisionConflicts.map((item) => escapeHtml(item.division)).join(", ")} ${divisionConflicts.length === 1 ? "has" : "have"} more than one possible card or a saved card that no longer matches. Choose the correct card before posting updates.</span>
  </div>` : "";
  const body = `<div class="job-card-layout">
    <div class="job-card-main">
      ${divisionConflictBanner}
      <section class="aud-section job-info-section compact-overview"><div class="section-title-row"><div><h3>Job overview</h3><small>Click a value to copy</small></div><div class="job-info-actions"><button type="button" class="btn compact" data-job-members>Members</button><button type="button" class="btn compact" data-copy-customer-info>Copy info</button></div></div>
        ${facts || `<div class="aud-empty">${emptyWorkspaceText('Job information', 'No saved job information yet.')}</div>`}${descriptionReview}</section>
      <section class="aud-section job-log-section"><div class="section-title-row"><div><h3>Job Log</h3><small>Structured updates used to build the Snapshot</small></div>
        <button class="btn btn-primary compact" data-add-job-log>+ Add update</button></div>
        <div class="job-log-toolbar" role="group" aria-label="Job Log actions">${data.card_id ? `<button class="btn compact" data-refresh-job-log title="Reload saved Job Log entries without importing Trello comments">Refresh saved log</button><button class="btn compact" data-import-job-log title="Manually import comments from this division's Trello card">Pull from ${escapeHtml(selectedDivision)} Trello</button>` : ""}
        <button class="btn compact" data-create-snapshot ${data.card_id ? '' : 'disabled'} title="Open the Snapshot editor for this card and its saved completed Job Log entries">Create Snapshot</button>
        <div data-job-log-export><button class="btn compact" data-print-job-log ${(crm.job_log || []).length ? '' : 'disabled'} title="${(crm.job_log || []).length ? 'Save the currently loaded division Job Log as a Snapshot-style PDF' : 'Add or import a Job Log entry before printing'}">Print / PDF</button><small data-job-log-export-status role="status"></small></div></div>
        <small data-job-log-status role="status">${crm.job_log_dismissal_pending ? 'Dismissal saved on this PC · waiting to sync' : crm.job_log_error || crm.ok === false ? 'Showing saved entries — refresh unavailable' : crm.job_log_saved_at ? `Saved on this PC${data.deferred_loading || data.refresh_pending ? ' · Checking for changes…' : ''}` : data.deferred_loading ? 'Checking for saved Job Log entries…' : ''}</small>
        <div data-log-filters aria-label="Filter Job Log">
          <label>Show <select data-log-party-filter aria-label="Work performed by"><option value="all">All updates</option><option value="crew">Our crew</option><option value="subcontractor">Subs</option><option value="">Unclassified</option></select></label>
          <label data-log-company-filter-row hidden>Company <select data-log-company-filter aria-label="Filter subcontractor company"><option value="">All companies</option>${[...new Set((crm.job_log || []).filter(e => e.work_party === 'subcontractor').map(e => e.subcontractor).filter(Boolean))].sort().map(name => `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`).join('')}</select></label>
          <small data-log-filter-count role="status"></small>
        </div>
        <div class="job-log-editor" data-job-log-editor hidden></div><div data-job-log-list>${logs}</div><div class="aud-empty" data-log-filter-empty hidden>No updates match this filter.</div></section>
        <section class="aud-section paperwork-section"><div class="section-title-row"><div><h3>Forms &amp; paperwork</h3><small>${escapeHtml(paperworkSummary)}</small></div><small data-file-check-state role="status" hidden></small></div>
        <div class="import-sources"><button type="button" class="action-btn" data-edit-payer>Change payer</button><span data-payer-editor></span></div>
        <div class="paperwork-list">${paperworkRows || `<div class="aud-empty">The paperwork list is unavailable for this saved job.</div>`}${docuSketchAccess}</div></section>
      <section class="aud-section checklist-section"><div class="section-title-row"><div><h3>Checklists</h3><small>${escapeHtml(selectedDivision)} requirements</small></div>${checklistDivisionTabs}</div>${checklistGroups}<button type="button" class="check-item-add" data-new-checklist ${data.card_id ? '' : 'disabled'}>＋ Add checklist</button></section>
      ${oldJobsSection}
      <section class="aud-section job-files-section"></section>
      <section class="aud-section signatures-section"><div class="section-title-row"><div><h3>Documents &amp; signatures</h3><small>DocuSign sends · job folder keeps the completed files</small></div><span class="signature-state state-${escapeAttr((dsRequest.state || "not_sent").replaceAll("_", "-"))}">${escapeHtml(signatureState)}</span></div>
        <div class="signature-flow"><span class="${dsRequest.requested ? "done" : "active"}">1 Prepare</span><i></i><span class="${dsRequest.requested ? "active" : ""}">2 Send</span><i></i><span class="${(docs.files || []).some((file) => file.signed) ? "done" : ""}">3 Signed copy</span></div>
        ${dsRequest.email ? `<div class="signature-recipient">Sent to <strong>${escapeHtml(dsRequest.email)}</strong> · ${Number(dsRequest.days_pending || 0)} day(s) pending</div>` : ""}
        ${!docs.connected ? `<div class="signature-connection"><span><strong>Direct DocuSign connection is next</strong><small>For now, open DocuSign and mark the request sent after the envelope is actually sent.</small></span></div>` : ""}
        <div class="signature-actions"><button class="btn btn-primary" data-open-docusign>Open DocuSign ↗</button><button class="btn" data-mark-docusign-sent ${dsRequest.state ? "disabled" : ""}>Mark envelope sent</button><button class="btn" data-open-docs-folder ${res.path ? "" : "disabled"}>Open job folder</button></div>
        <div class="signature-files">${documentRows}</div></section>
      <section class="aud-section job-details-section"><div class="section-title-row"><h3>Card Details</h3><button class="btn compact" data-details-open-card ${data.card_id ? '' : 'disabled'}>Open in Trello ↗</button></div>
        <h4>Board placement</h4><div class="details-placement">${locationSection.fields.map(field=>`<button class="job-info-field" data-move-job-location="${field.id}" ${data.card_id ? '' : 'disabled'}><span>${escapeHtml(field.label)}</span><strong>${escapeHtml(field.value)}</strong><i>Move ▾</i></button>`).join('')}</div>
        ${selectedDivision==='EMS' ? '<div class="details-completion"><span>Field work finished? Move to Estimating and record completion.</span><button class="btn compact" data-details-complete>Move to Estimating</button></div>' : ''}
        <h4>Dates</h4><div class="details-dates"><div><small>Card due date</small><strong>${cardDue ? escapeHtml(fmtDue(cardDue)) : 'No due date available'}</strong><button class="text-btn" data-details-open-card ${data.card_id ? '' : 'disabled'}>Edit due date</button></div><div><small>Work completed</small><strong data-completion-date-value>Not recorded</strong><button class="text-btn" data-edit-completion-date ${data.card_id ? '' : 'disabled'}>Add date</button><small>Separate from the card deadline</small></div></div>
        <h4>Connected division cards</h4><div class="details-linked-cards">${workTypes}</div>
      </section>
      <details class="aud-section compact-section job-run-section" open><summary>Card history <span>${(res.activity || []).length}</span></summary>${activity}</details>
      <details class="aud-section compact-section job-attachments-section" open><summary>Other attachments <span>${(data.attachments || []).length}</span></summary>${attachments}</details>
    </div>
    <aside class="job-card-activity"><div class="activity-head"><div><h3>Comments <span data-comment-count title="Loaded comments">${(data.comments || []).length}</span></h3></div></div>
      <div class="comment-stream" data-comment-stream>${comments}</div>
      <div class="comment-compose"><textarea data-comment-input name="job-comment" rows="3" aria-label="Job comment" autocomplete="off" placeholder="Write an update for this job…"></textarea>
        <div class="comment-send-row"><button class="btn btn-primary" data-post-comment>Post</button></div><span data-comment-state role="status"></span></div>
      <div class="comment-search-tools">
        <button type="button" class="btn comment-search-toggle" data-toggle-comment-search aria-label="Search comments" title="Search comments" aria-expanded="false"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="m16 16 5 5"></path></svg></button>
        <label class="comment-search" hidden><input type="search" data-comment-search placeholder="Search comments" aria-label="Search comments"><small data-comment-search-count role="status"></small></label>
      </div>
    </aside></div>`;
  let w = document.createElement("div");
  w.className = "modal-scrim audit-overlay";
  w.innerHTML = `
    <div class="modal-box audit-card" role="dialog" aria-modal="true" aria-label="Job workspace" tabindex="-1">
      <button type="button" class="audit-close workspace-corner-close" data-close aria-label="Close job workspace" title="Close job workspace">×</button>
      <header class="modal-head">
        <div class="audit-head-main"><div class="audit-head-copy"><div class="modal-title-row"><div class="modal-title">${escapeHtml(data.client || res.client || "")}</div><button type="button" class="client-page-link" data-open-client-page>👤 Client page</button></div>
        <div class="modal-sub">${claimNumber ? `Claim ${escapeHtml(claimNumber)} · ` : ""}${escapeHtml(crm.lifecycle_stage ? crm.lifecycle_stage.replaceAll("_", " ") : "Job audit")} · ${clean ? "ready" : issues.length + " item(s) need attention"}${res.aging ? " · " + res.aging + " days" : ""}</div></div>
        <div class="workspace-load-state" data-workspace-load-state>${data.deferred_loading ? "Checking details…" : data.refresh_pending ? "Saved details · checking for updates" : ''}</div>
        </div>
        <div class="job-header-meta">
          ${headerTagsHtml}
          <div data-quick-members></div>
          <div data-quick-labels></div>
        </div>
        <div class="modal-sub" data-field-work-completed ${workTypeState.ems?.field_work_completed_at ? '' : 'hidden'}>${workTypeState.ems?.field_work_completed_at ? `Field work completed · ${escapeHtml(new Date(workTypeState.ems.field_work_completed_at).toLocaleString())}` : ''}</div>
        ${snapshotCardMode ? `<div class="snapshot-division-label">${escapeHtml(selectedDivision)} · Snapshot</div>` : divisionDataTabs}
        <div class="card-quick-actions" aria-label="Job actions">
          <div class="quick-main-actions">
          <div class="quick-primary-actions" aria-label="Work actions">
            <button class="action-btn" aria-label="Import files" data-import-files title="Import downloaded or selected files into this job's OD folder"><span aria-hidden="true">📥</span><span class="quick-tool-label">Import files</span></button>
            <button type="button" class="action-btn" aria-label="Documents — build photo report" data-quick-photo-report title="Documents — build photo report"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h8"/></svg><span class="quick-tool-label">Photo report</span></button>
            <div class="tool-quick-menu"><button type="button" class="action-btn destination tool-menu-trigger" title="Folder" aria-label="Folder" aria-haspopup="menu" aria-expanded="false"><span aria-hidden="true">📁</span><span class="quick-tool-label">Folder</span> <small>⌄</small></button><div class="tool-menu-panel" role="menu" aria-label="Job folder actions">
              <button data-open-docs-folder ${res.path ? "" : "disabled"}>Open folder</button>
              <button data-repin-job-folder>Pin / repin folder</button>
              <button data-copy-folder-path ${res.path ? "" : "disabled"}>Copy path</button>
            </div></div>
          </div>
          <div class="quick-destination-actions" aria-label="Connected tools">
            <div class="tool-quick-menu"><button type="button" class="action-btn destination tool-menu-trigger" title="Trello" aria-label="Trello" aria-haspopup="menu" aria-expanded="false"><img src="../web_shared/trello.png" alt=""><span class="quick-tool-label">Trello</span> <small>⌄</small></button><div class="tool-menu-panel" role="menu" aria-label="Trello card actions">
              <button data-open-trello ${trelloUrl ? "" : "disabled"}>Open card</button>
              <button data-repin-trello>Change pinned card</button>
            </div></div>
            <div class="tool-quick-menu"><button type="button" class="action-btn destination tool-menu-trigger" title="XA" aria-label="XA" aria-haspopup="menu" aria-expanded="false"><img src="../web_shared/xactanalysis.png" alt=""><span class="quick-tool-label">XA</span> <small>⌄</small></button><div class="tool-menu-panel" role="menu">
              <button data-open-xa ${data.card_id || data.client ? "" : "disabled"}>Open XactAnalysis</button>
              <button data-xa-note ${data.card_id ? "" : "disabled"}>Add XA note</button>
              <button data-stage-xa ${res.path ? "" : "disabled"}>Stage files for XA</button>
            </div></div>
            <div class="tool-quick-menu"><button type="button" class="action-btn destination tool-menu-trigger" title="CompanyCam" aria-label="CompanyCam" aria-haspopup="menu" aria-expanded="false"><img src="../web_shared/companycam.png" alt=""><span class="quick-tool-label">CompanyCam</span> <small>⌄</small></button><div class="tool-menu-panel" role="menu">
              <button data-open-companycam ${data.card_id || data.client ? "" : "disabled"}>Open project</button>
              <button data-change-companycam ${data.client || res.client ? "" : "disabled"}>Change project…</button>
              <button data-initial-video data-video-url="${escapeAttr(savedJobLinkUrl(data.info_sections, 'link_video'))}" ${savedJobLinkUrl(data.info_sections, 'link_video') ? '' : 'disabled'} title="${savedJobLinkUrl(data.info_sections, 'link_video') ? 'Open the saved initial video in your browser' : 'Add an Initial video link in Job info'}">Initial video viewer</button>
            </div></div>
            <button type="button" class="action-btn destination" aria-label="DocuSketch" data-open-docusketch data-docusketch-url="${escapeAttr(savedDocuSketchUrl(data.info_sections) || '')}" ${savedDocuSketchUrl(data.info_sections) ? '' : 'disabled'} title="${savedDocuSketchUrl(data.info_sections) ? 'Open saved DocuSketch link' : 'No DocuSketch link saved for this section'}"><img src="../web_shared/docusketch.jpg" alt=""><span class="quick-tool-label">DocuSketch</span></button>
            <button type="button" class="action-btn destination" aria-label="DocuSign" data-open-docusign title="Open DocuSign"><img src="../web_shared/docusign.png" alt=""><span class="quick-tool-label">DocuSign</span></button>
          </div>
          </div>
          <div class="quick-utility-actions"><button type="button" class="action-btn quiet workspace-refresh" data-refresh-workspace aria-label="Refresh details" title="Refresh job details">↻</button><div class="tool-quick-menu more-quick-menu"><button type="button" class="action-btn quiet tool-menu-trigger" title="More job actions" aria-label="More job actions" aria-haspopup="menu" aria-expanded="false"><svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg></button><div class="tool-menu-panel" role="menu" aria-label="More job actions">
            ${!snapshotCardMode && !snapshotCommentsMode && data.card_id ? `<button type="button" data-hold-in-hand ${state.jobShelf.some(item => item.cardId === data.card_id && item.mode === 'held') ? 'disabled' : ''}>${state.jobShelf.some(item => item.cardId === data.card_id && item.mode === 'held') ? 'Already in hand' : 'Put in hand'}</button>` : ''}
            <button type="button" data-manage-linked-cards hidden>Connected cards…</button>
            ${selectedDivision === 'EMS' && data.card_id ? '<button type="button" data-create-ems-copy>Create linked placeholder…</button>' : ''}
            <button data-initial-notes ${data.card_id ? "" : "disabled"}>Initial notes</button>
            <button data-import-existing-initial-notes>Copy existing initial notes</button><button type="button" data-copy-customer-info title="Copy formatted customer and insurance information" ${customerInfoCopyText(data.info_sections) ? '' : 'disabled'}>Copy info</button>
          </div></div></div>
        </div>
      </header>
      ${data.folder_error ? `<div class="job-folder-alert" role="status"><span>Job folder needs a verified link. Files and photos will be unavailable until it is linked.</span><button type="button" data-review-folder-link>Review folder</button></div>` : ''}
      <div class="modal-body">${body}</div>
      <footer class="modal-foot">
        <div class="visible-job-actions"><span class="footer-job-context">${escapeHtml(selectedDivision)} · ${claimNumber ? `Claim ${escapeHtml(claimNumber)}` : "Job workspace"}</span></div>
      </footer>
    </div>`;
  positionDevCommentComposer(w, data);
  if (!preparation) document.body.appendChild(w);
  if (!preparation) window.CardLabels?.mount(w, data.client || res.client || '', data.card_id);
  if (!preparation) window.JobMemberChips?.mount(w, data.card_id);
  if (!preparation) window.CardTitle?.mount(w, data.client || res.client || '', data.card_id);
  if (!preparation) window.ExtraJobTasks?.mount(w, data.client || res.client || '', data.card_id);
  if (selectedDivision === 'EMS') window.CardCompletion?.mount(w, data.client || res.client || '', data.card_id);
  const manageLinks = w.querySelector('[data-manage-linked-cards]');
  try {
    if (manageLinks && window.top.document.querySelector('[data-key="job_reconciliation"]')) {
      manageLinks.hidden = false;
      manageLinks.addEventListener('click', () => {
        window.top.postMessage({type:'ems-connected-cards',key:'job_reconciliation',focus:JSON.stringify({
          job_id:data.job_id || '',card_id:data.card_id || '',client:data.client || res.client || '',
          section:selectedDivision
        })}, location.origin);
      });
    }
  } catch (_) { /* This Dev-only tool is not available in standalone/Main. */ }
  const previousFocus = preparation ? null : document.activeElement;
  window.JobFiles?.mount(w.querySelector('.job-files-section'), {client:data.client || res.client || '', cardId:data.card_id || '', division:selectedDivision, attachments:data.attachments || []});
  window.SavedRunActivity?.mount(w.querySelector('.job-run-section'), data.client || res.client || '', selectedDivision, data.card_id || '');
  const workspaceTabs = window.JobWorkspaceTabs.mount(w, `${state.department || ''}:${data.card_id || data.client || ''}`, {excludeTabs:snapshotCardMode ? ['log', 'files'] : ['files']});
  const popoutTab=new URLSearchParams(location.search).get('job_tab');
  if(popoutTab)workspaceTabs.select(popoutTab);
  if (snapshotCardMode && !preparation) {
    const observer = new ResizeObserver(() => window.parent.postMessage({type:'snapshot-card-height',height:Math.ceil(w.querySelector('.audit-card').getBoundingClientRect().height)},location.origin));
    observer.observe(w.querySelector('.audit-card'));
    w._snapshotSizeObserver = observer;
  }
  window.JobCardTiming?.mount(w, data.card_id, pywebview.api);
  const dueBadge=document.createElement('button');dueBadge.className='btn compact header-card-completed';dueBadge.textContent='Add date';dueBadge.title='Work completed date';dueBadge.disabled=!data.card_id;
  const openDueCard=()=>w.querySelector('[data-open-trello]')?.click();
  w.querySelector('.modal-head .modal-sub')?.append(dueBadge);
  window.CompletionDate?.mount(w,data.client || '',data.card_id,completed=>{
    data.work_completed_date=completed;
    for(const board of state.board.boards || [])for(const lane of board.lanes || [])for(const card of lane.cards || [])if(card.card_id===data.card_id)card.work_completed_date=completed;
    if(document.querySelector('#board-view'))renderBoard();
  });
  w.querySelectorAll('[data-details-open-card]').forEach(button=>button.onclick=openDueCard);
  window.CardDue?.mount(w,data.client || '',data.card_id,due=>{
    data.card_due=due;
    for(const board of state.board.boards || [])for(const lane of board.lanes || [])for(const card of lane.cards || [])if(card.card_id===data.card_id){card.due=due?due.slice(0,10):'';card.overdue=!!due&&new Date(due)<new Date()&&!card.due_complete;}
    if(document.querySelector('#board-view'))renderBoard();
  });
  const completeButton=w.querySelector('[data-details-complete]');if(completeButton){completeButton.disabled=!w.querySelector('[data-complete-card]');completeButton.onclick=()=>w.querySelector('[data-complete-card]')?.click();}
  if (!preparation && data.initial_workspace_tab) workspaceTabs.select(data.initial_workspace_tab);
  const dirtyDrafts = preparation?.dirtyDrafts || new Set();
  const recoveredDrafts = preparation?.recoveredDrafts || new Set();
  const editedSections = preparation?.editedSections || new Set();
  let workspaceContext = null;
  const markDraftDirty = (key, dirty = true) => {
    if (dirty) dirtyDrafts.add(key);
    else dirtyDrafts.delete(key);
  };
  const clearDraftDirty = (key) => dirtyDrafts.delete(key);
  const close = (force = false, switching = false) => {
    if (preparation) return preparation.close(force, switching);
    if (!force && dirtyDrafts.size) {
      if (!window.confirm("Discard your unsaved draft? Saved job changes will not be lost.")) return false;
      recoveredDrafts.forEach(draft => draft.clear());
    }
    recoveredDrafts.forEach(draft => draft.dispose());
    w._snapshotSizeObserver?.disconnect();
    w.querySelector('[data-comment-input]')?._richEditor?.destroy();
    document.removeEventListener("keydown", keyClose);
    if (w._contentsListener) window.removeEventListener("pipeline:contents-card", w._contentsListener);
    if (state.openWorkspace === workspaceContext) state.openWorkspace = null;
    w.querySelector('.job-files-section')?._jobFiles?.dispose();
    if (!switching) {
      w.remove();
      previousFocus?.focus?.();
    }
    return true;
  };
  const requestClose = () => { if (!snapshotCommentsMode && !snapshotCardMode && close()) notifyJobWorkspaceClosed(); };
  w.querySelector("[data-close]").addEventListener("click", requestClose);
  const keyClose = (e) => {
    if (e.key !== "Escape") return;
    if ([...document.querySelectorAll('.modal-scrim, .overlay')].filter(el => el.getClientRects().length).at(-1) !== w) return;
    const openMenus = w.querySelectorAll(".tool-quick-menu.is-open");
    if (openMenus.length) {
      openMenus.forEach((menu) => {
        menu.classList.remove("is-open");
        menu.querySelector(".tool-menu-trigger")?.setAttribute("aria-expanded", "false");
      });
      return;
    }
    requestClose();
  };
  if (!preparation) {
    window.bindBackdropClick?.(w, requestClose);
    document.addEventListener("keydown", keyClose);
    w.querySelector(".audit-card")?.focus();
    w.addEventListener('input', event => {
      const section = event.target.closest('.aud-section');
      if (section) editedSections.add(workspaceSectionKey(section));
    });
    w.addEventListener('change', event => {
      const section = event.target.closest('.aud-section');
      if (section) editedSections.add(workspaceSectionKey(section));
    });
  }
  w.querySelectorAll(".tool-quick-menu").forEach((menu) => {
    const trigger = menu.querySelector(".tool-menu-trigger");
    const setOpen = (open) => {
      menu.classList.toggle("is-open", open);
      trigger?.setAttribute("aria-expanded", open ? "true" : "false");
    };
    trigger?.addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = !menu.classList.contains("is-open");
      w.querySelectorAll(".tool-quick-menu.is-open").forEach((other) => {
        other.classList.remove("is-open");
        other.querySelector(".tool-menu-trigger")?.setAttribute("aria-expanded", "false");
      });
      setOpen(opening);
    });
    menu.querySelectorAll(".tool-menu-panel button").forEach((button) =>
      button.addEventListener("click", () => setOpen(false)));
  });
  w.querySelector('[data-hold-in-hand]')?.addEventListener('click', event => {
    const input = {cardId:data.card_id, name:data.client || res.client || '', url:trelloUrl, placement:data.app_placement};
    if (!input.cardId) return;
    let jobsFrame = null;
    if (jobWorkspaceMode && window.parent !== window) {
      try { jobsFrame = window.parent.document.querySelector('iframe[data-panel-key="pipeline"]')?.contentWindow; } catch (_) {}
    }
    if (typeof jobsFrame?.holdJobInHandFromWorkspace === 'function') {
      jobsFrame.holdJobInHandFromWorkspace(input);
      setStatus(`Held ${input.name || 'job'} in hand · open Jobs to place it`, 'ok');
    } else {
      holdJobInHandFromWorkspace(input);
    }
    event.currentTarget.textContent = 'Already in hand';
    event.currentTarget.disabled = true;
  });
  w.addEventListener("click", (event) => {
    if (event.target.closest(".tool-quick-menu")) return;
    w.querySelectorAll(".tool-quick-menu.is-open").forEach((menu) => {
      menu.classList.remove("is-open");
      menu.querySelector(".tool-menu-trigger")?.setAttribute("aria-expanded", "false");
    });
  });
  w.querySelector("[data-open-client-page]")?.addEventListener("click", () => {
    const client = data.client || res.client || "";
    close(true);
    notifyJobWorkspaceClosed();
    if (window.emsNavigateTo) window.emsNavigateTo("clients", client);
  });
  if(window.ClientTransfer){
    const transfer=document.createElement('button');transfer.type='button';transfer.className='client-page-link';transfer.textContent='Change client';
    transfer.onclick=()=>window.ClientTransfer.open(data.client||res.client||'',data.card_id||res.card_id||'',()=>setStatus('Client relationship saved. Folders and job history unchanged.','ok'));
    w.querySelector('[data-open-client-page]')?.after(transfer);
  }
  w.querySelectorAll("[data-division-data]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.divisionData === selectedDivision) return;
    const target = divisionTargets[button.dataset.divisionData];
    if (!target) { linkDivisionTab(button.dataset.divisionData); return; }
    const tab = w.querySelector('.job-workspace-tabs [aria-selected="true"]')?.id.replace('job-tab-', '');
    if (!close(false, true)) return;
    await onAuditCard(data.client || res.client || "", target.card_id, target.url || "", button.dataset.divisionData || "EMS", {
      cards: workspaceDivisionCards, reconciliation: data.division_card_reconciliation, tab,
      element: w,
      sharedInfo: (data.info_sections || []).filter(section => ['Customer Information', 'Property Details'].includes(section.name)),
      loadSession: w._divisionLoadSession
    });
  }));
  w.querySelectorAll('[data-division-data]').forEach(button => {
    const link = event => {
      if (divisionTargets[button.dataset.divisionData]) return;
      event.preventDefault();event.stopPropagation();
      linkDivisionTab(button.dataset.divisionData);
    };
    button.addEventListener('contextmenu', link);
    button.addEventListener('keydown', event => {
      if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) link(event);
    });
  });
  w.querySelector('.job-division-folder-tabs')?.addEventListener('keydown', event => {
    const buttons = [...w.querySelectorAll('[data-division-data]:not(:disabled)')];
    const index = buttons.indexOf(event.target);
    if (index < 0 || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next].focus();
  });
  w.querySelectorAll("[data-checklist-division]").forEach((button) => button.addEventListener("click", async () => {
    if (button.dataset.checklistDivision === selectedDivision) return;
    const target = workspaceDivisionCards.find(card => card.division === button.dataset.checklistDivision && card.card_id && card.pinned !== false);
    if (!target) { setStatus('Choose a linked card for that division first.', 'warn'); return; }
    if (!close()) return;
    await onAuditCard(data.client || res.client || "", target.card_id, target.url || "", button.dataset.checklistDivision || "EMS");
  }));
  const linkedCardTarget = { dataset: {
    client: data.client || res.client || "",
    cardId: data.card_id || "",
    division: selectedDivision,
  }};
  const repinTrello = () => openChangePinnedTrelloCard(linkedCardTarget, async (result) => {
    // Re-open from the shared source so the new card title, link, Job Info,
    // and import-conflict state are visible without making the user refresh.
    // The existing close guard protects any unfinished edits in this modal.
    if (!close()) {
      setStatus("Trello card changed. Finish or discard the open draft, then reopen the job to see its imported Job Info.", "warn");
      return;
    }
    notifyJobWorkspaceClosed();
    await onAuditCard(
      data.client || res.client || "",
      result?.card_id || data.card_id || "",
      result?.url || "",
      selectedDivision,
    );
  });
  const checkDocuSketchFolder = async () => {
    const path = data.audit?.path || res.path || '';
    const badge = w.querySelector('[data-docusketch-folder]');
    if (!badge || !path) return;
    const show = (state, message, label) => {
      badge.className = `paperwork-row paperwork-${state}`;
      badge.querySelector('.paperwork-mark').textContent = paperworkState[state][0];
      badge.querySelector('small').textContent = message;
      badge.querySelector('b').textContent = label;
    };
    show('unknown', 'Checking for a DocuSketch folder…', 'Checking');
    try {
      const result = await pywebview.api.job_docusketch_folder(path);
      if ((data.audit?.path || res.path) !== path || !badge.isConnected) return;
      if (result?.status === 'found') show('present', 'Folder found · sketch completion not verified', 'Found');
      else if (result?.status === 'not_found') show('missing', 'No DocuSketch folder found in the checked job folders', 'Missing');
      else show('unknown', 'DocuSketch folder could not be verified', 'Not checked');
      badge.title = result.path || 'Checks the job folder and two nested folder levels; does not verify account access.';
    } catch (_) { if (badge.isConnected) show('unknown', 'DocuSketch folder could not be verified', 'Not checked'); }
  };
  if (!preparation) checkDocuSketchFolder();
  const repinFolder = () => openJobFolderLinkModal(data, null, async (result) => {
    res.path = result.path;
    data.audit = {...(data.audit || {}), path: result.path};
    w.querySelector('.job-files-section')?._jobFiles?.reset();
    w.querySelectorAll('[data-open-docs-folder], [data-copy-folder-path], [data-stage-xa]').forEach(button => { button.disabled = false; });
    checkDocuSketchFolder();
  });
  w.querySelector('[data-review-folder-link]')?.addEventListener('click', repinFolder);
  const currentFolderPath = () => data.audit?.path || '';
  const openFolder = async () => {
    const result = await localFileAction(() => pywebview.api.open_job_folder(data.client || "", currentFolderPath(), data.card_id || ""));
    if (!result?.ok) setStatus(result?.error || "The job folder could not open. Pin the exact folder and try again.", "error");
    else if (result.path) data.audit = {...(data.audit || {}), path: result.path};
  };
  const copyFolderPath = async () => {
    try {
      const result = await pywebview.api.job_folder_path(data.client || '', data.card_id || '');
      if (!result?.ok || !result.path) throw new Error(result?.error || 'No verified job folder is linked.');
      data.audit = {...(data.audit || {}), path: result.path};
      await pywebview.api.copy_to_clipboard(result.path);
    }
    catch (error) { setStatus(error?.message || String(error), "error"); return; }
    setStatus("Job folder path copied", "ok");
  };
  const showFolderContext = (event) => {
    event.preventDefault(); event.stopPropagation();
    if (!window.showContextMenu) { repinFolder(); return; }
    window.showContextMenu(event, [
      { label: "Open folder", action: openFolder, disabled: !currentFolderPath() },
      { label: "Pin / repin folder…", action: repinFolder },
      { label: "Copy path", action: copyFolderPath, disabled: !currentFolderPath() },
    ], { minWidth: 210 });
  };
  w.querySelectorAll("[data-open-trello]").forEach((button) => button.addEventListener("click", () => {
    if (trelloUrl) pywebview.api.open_url(trelloUrl);
  }));
  w.querySelectorAll("[data-open-trello]").forEach((button) => button.addEventListener("contextmenu", (event) => {
    event.preventDefault(); event.stopPropagation(); repinTrello();
  }));
  w.querySelector("[data-repin-trello]")?.addEventListener("click", repinTrello);
  w.querySelector("[data-open-xa]")?.addEventListener("click", async () => {
    const ok = await pywebview.api.open_xa_link(data.client || res.client || "", data.card_id || "");
    if (!ok) setStatus("No XactAnalysis link is saved for this job", "warn");
  });
  w.querySelector("[data-open-companycam]")?.addEventListener("click", async () => {
    const ok = await pywebview.api.open_companycam_link(data.client || res.client || "", data.card_id || "");
    if (!ok) setStatus("No CompanyCam project is linked to this job", "warn");
  });
  w.querySelector("[data-open-docusketch]")?.addEventListener("click", async (event) => {
    const url = savedDocuSketchUrl([{fields:[{id:'link_docusketch',value:event.currentTarget.dataset.docusketchUrl}]}]);
    if (!url) return;
    try {
      const opened = await pywebview.api.open_url(url);
      if (opened === false) setStatus('The DocuSketch link could not be opened.', 'warn');
    } catch (error) {
      setStatus('The DocuSketch link could not be opened.', 'error', error?.message || String(error));
    }
  });
  w.querySelector('[data-initial-video]')?.addEventListener('click', async event => {
    const url = savedJobLinkUrl([{fields:[{id:'link_video', value:event.currentTarget.dataset.videoUrl}]}], 'link_video');
    if (!url) return;
    try {
      const opened = await pywebview.api.open_url(url);
      if (opened === false) setStatus('The initial video could not be opened.', 'warn');
    } catch (error) {
      setStatus('The initial video could not be opened.', 'error', error?.message || String(error));
    }
  });
  w.querySelector('[data-open-job-map]')?.addEventListener('click', async () => {
    if (!mapAddress) return;
    try {
      const opened = await pywebview.api.open_url('https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(mapAddress));
      if (opened === false) throw Error('Map could not be opened.');
    } catch (error) { setStatus(error.message || 'Map could not be opened.', 'warn'); }
  });
  w.querySelector("[data-xa-note]")?.addEventListener("click", () =>
    openXaNoteModal(data.client || res.client || "", data.card_id || ""));
  w.querySelector("[data-initial-notes]")?.addEventListener("click", () =>
    openInitialNoteModal(data.client || res.client || "", data.card_id || "", selectedDivision));
  w.querySelector("[data-import-existing-initial-notes]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const result = await pywebview.api.import_initial_notes(
      data.client || res.client || "", data.card_id || "");
    button.disabled = false;
    if (!result?.ok || !result.summary) {
      setStatus(result?.error || "No existing initial notes were found", "warn");
      return;
    }
    await pywebview.api.copy_to_clipboard(result.summary);
    setStatus("Existing initial notes copied", "ok");
  });
  w.querySelector("[data-import-files]")?.addEventListener("click", () =>
    openJobFileImportModal(data, res));
  if(data.card_id){
    for(const [selector,jobAction] of [['[data-import-files]','import'],['[data-quick-photo-report]','photo_report']]){
      w.querySelectorAll(selector).forEach(button=>{
        button.dataset.popoutTool='pipeline';
        button.dataset.popoutContext=JSON.stringify({cardId:data.card_id,client:data.client||res.client||'',division:selectedDivision,jobAction});
      });
    }
  }
  w.querySelector('[data-change-companycam]')?.addEventListener('click', () =>
    window.CompanyCamRelink.open({client:data.client || res.client || '', cardId:data.card_id || '', api:pywebview.api, onSaved:() => setStatus('CompanyCam project link updated. Future pulls use the selected project.', 'ok')}));
  w.querySelector("[data-link-job-folder]")?.addEventListener("click", repinFolder);
  w.querySelector("[data-repin-job-folder]")?.addEventListener("click", repinFolder);
  w.querySelector("[data-copy-folder-path]")?.addEventListener("click", copyFolderPath);
  w.querySelectorAll("[data-refresh-workspace], [data-run-folder-audit]").forEach(control => control.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const iconRefresh = button.hasAttribute('data-refresh-workspace');
    button.disabled = true;
    button.textContent = iconRefresh ? '↻' : 'Refreshing…';
    button.setAttribute('aria-busy', 'true');
    let refreshed;
    try { refreshed = await pywebview.api.refresh_job_card_workspace(
      data.client || res.client || "", data.card_id || "", data.selected_division || "EMS"); }
    catch (error) { refreshed = {ok:false, error:String(error)}; }
    button.removeAttribute('aria-busy');
    if (!refreshed?.ok) {
      button.disabled = false;
      button.textContent = iconRefresh ? '↻' : 'Refresh live';
      setStatus(refreshed?.error || "Live refresh failed", "error");
      return;
    }
    button.disabled = false;
    button.textContent = iconRefresh ? '↻' : 'Run audit';
    if (!w.isConnected) return;
    state.openWorkspace?.applyRefresh?.(refreshed);
    setStatus(`Live details refreshed in ${refreshed.load_ms || 0} ms`, "ok");
  }));
  w.querySelector("[data-flag-job]")?.addEventListener("click", () => {
    onFlagCard({dataset: {client: data.client || res.client || "", cardId: data.card_id || ""}});
  });
  w.querySelector("[data-stage-xa]")?.addEventListener("click", () => {
    openXaStageModal(data.client || res.client || "", res.path || "", data.card_id || '');
  });
  w.querySelectorAll("[data-copy-job-field]").forEach((button) => button.addEventListener("click", async () => {
    try {
    if (!await pywebview.api.copy_to_clipboard(button.dataset.copyJobField || "")) throw new Error('Copy failed');
    button.classList.add("copied");
    window.setTimeout(() => button.classList.remove("copied"), 900);
    setStatus(`Copied ${button.dataset.copyJobLabel || "job info"}`, "ok");
    } catch (_) { setStatus('Could not copy. Please try again.', 'error'); }
  }));
  w.querySelector('[data-copy-description]')?.addEventListener('click', async () => {
    try {
      if (!await pywebview.api.copy_to_clipboard(data.description_review?.original || '')) throw new Error('Copy failed');
      setStatus('Copied Trello description', 'ok');
    } catch (_) { setStatus('Could not copy. Please try again.', 'error'); }
  });
  w.querySelectorAll('[data-move-job-location]').forEach(button => button.addEventListener('click', () => {
    if (!data.card_id) return;
    void openPlacementAction(data.card_id, 'move', {
      focus:button.dataset.moveJobLocation,
      onSaved(destination) {
        data.app_placement = {...(data.app_placement || {}), ...destination};
        if (!w.isConnected) return;
        const board = w.querySelector('[data-move-job-location="app_board"] strong');
        const lane = w.querySelector('[data-move-job-location="app_lane"] strong');
        if (board) { board.textContent = destination.board; board.closest('button').title = `Board: ${destination.board}\nClick to change`; }
        if (lane) { lane.textContent = destination.lane; lane.closest('button').title = `Lane / section: ${destination.lane}\nClick to change`; }
      }
    });
  }));
  w.querySelector('[data-job-members]')?.addEventListener('click', () => openJobMembers(data.card_id || '', () => w.querySelector('[data-quick-members]')?.refreshMembers?.()));
  const formsButton = document.createElement('button');
  formsButton.type = 'button'; formsButton.className = 'btn compact'; formsButton.textContent = 'Forms';
  formsButton.onclick = () => openJobForms(data.client || res.client || '', data.card_id || res.card_id || '');
  formsButton.dataset.jobForms = '';
  w.querySelector('.paperwork-section .section-title-row')?.append(formsButton);
  w.querySelectorAll('[data-prepare-form]').forEach(button => button.addEventListener('click', () =>
    openJobForms(data.client || res.client || '', data.card_id || res.card_id || '', button.dataset.prepareForm)));
  w.querySelectorAll('[data-open-form-match], [data-confirm-form-match]').forEach(button => button.addEventListener('click', async () => {
    const feedback = button.closest('.paperwork-matches').querySelector('[data-form-match-feedback]');
    const confirming = button.hasAttribute('data-confirm-form-match');
    const controls = [...button.closest('.paperwork-matches').querySelectorAll('button')];
    const disabled = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    feedback.textContent = confirming ? 'Saving file confirmation…' : 'Opening matched document…';
    try {
      const method = confirming ? 'confirm_form_file' : 'open_matched_form';
      const result = await pywebview.api[method](data.client || '', data.card_id || '', button.dataset.formLabel, button.dataset.formFile);
      if (!result?.ok) throw new Error(result?.error || 'Action was not confirmed. Please retry.');
      if (confirming) {
        feedback.textContent = 'File confirmed. Signed/completed status and checklist unchanged.';
        button.blur(); // This save is finished; allow the section to refresh.
        controller.applyRefresh({ok: true, card_id: data.card_id, crm: {paperwork: result.paperwork}});
        [...w.querySelectorAll('[data-open-form-match]')].find(control =>
          control.dataset.formLabel === button.dataset.formLabel &&
          control.dataset.formFile === button.dataset.formFile)?.focus();
        setStatus('File confirmed—not marked signed or complete.', 'ok');
      } else {
        const confirmControl = controls.find(control => control.hasAttribute('data-confirm-form-match') && control.dataset.formFile === button.dataset.formFile);
        showMatchedFormPreview(button.dataset.formFile, result, button, {
          confirmed: confirmControl ? disabled[controls.indexOf(confirmControl)] : false,
          confirm: () => pywebview.api.confirm_form_file(data.client || '', data.card_id || '', button.dataset.formLabel, button.dataset.formFile),
          onConfirmed: saved => {
            button.blur();
            controller.applyRefresh({ok: true, card_id: data.card_id, crm: {paperwork: saved.paperwork}});
            [...w.querySelectorAll('[data-open-form-match]')].find(control =>
              control.dataset.formLabel === button.dataset.formLabel && control.dataset.formFile === button.dataset.formFile)?.focus();
            setStatus('File confirmed—not marked signed or complete.', 'ok');
          }
        });
        feedback.textContent = 'Preview opened in OneLoss.';
      }
    } catch (error) {
      feedback.textContent = error?.message || String(error);
    } finally {
      controls.forEach((control, index) => { control.disabled = disabled[index]; });
    }
  }));
  w.querySelectorAll('[data-copy-customer-info]').forEach(control => control.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const text = jobSummaryCopyText(data.info_sections);
      if (!text || !await pywebview.api.copy_to_clipboard(text)) throw new Error('Copy failed');
      button.textContent = 'Copied';
      setStatus('Copied customer, address and insurance info', 'ok');
    } catch (_) {
      button.textContent = 'Retry copy';
      setStatus('Could not copy customer info. Please try again.', 'error');
    } finally {
      button.disabled = false;
      window.setTimeout(() => { if (button.isConnected) button.textContent = 'Copy info'; }, 1500);
    }
  }));
  w.querySelector('.modal-title')?.addEventListener('contextmenu', event => window.OneLossPopout?.menu(event,'pipeline',{
    cardId:data.card_id||'',client:data.client||res.client||'',division:selectedDivision}));
  if(data.card_id)window.OneLossPopout?.mount(w.querySelector('.modal-head'),'pipeline',()=>({
    cardId:data.card_id,client:data.client||res.client||'',division:selectedDivision,
    jobTab:w.querySelector('.job-workspace-tabs [aria-selected="true"]')?.id.replace('job-tab-','')||'overview'}));
  w.querySelectorAll("[data-edit-job-info]").forEach(control => control.addEventListener("click", () => openJobInfoEditor(data, res, async () => {
    close(true);
    await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS");
  })));
  w.querySelector("[data-dispatch-subcontractor]")?.addEventListener("click", () => {
    const fields = Object.fromEntries(copyFacts
      .filter((field) => field?.id)
      .map((field) => [field.id, field.value || ""]));
    fields.client = data.client || res.client || "";
    openSubcontractorDispatchModal(fields);
  });
  w.querySelectorAll("[data-checklist-role]").forEach((button) => button.addEventListener("click", () => {
    w.querySelectorAll("[data-checklist-role]").forEach((tab) => {
      const active = tab === button;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    w.querySelectorAll("[data-checklist-pane]").forEach((pane) => {
      const active = pane.dataset.checklistPane === button.dataset.checklistRole;
      pane.classList.toggle("active", active);
      pane.hidden = !active;
    });
  }));
  const refreshChecklistProgress = () => {
    w.querySelectorAll(".trello-checklist").forEach((checklist) => {
      const boxes = [...checklist.querySelectorAll("[data-check-item]")];
      const done = boxes.filter((box) => box.checked).length;
      const count = checklist.querySelector(".checklist-title span");
      const fill = checklist.querySelector(".checklist-progress i");
      if (count) count.textContent = `${done}/${boxes.length}`;
      if (fill) fill.style.width = `${boxes.length ? Math.round((done / boxes.length) * 100) : 0}%`;
    });
    w.querySelectorAll("[data-checklist-role]").forEach((tab) => {
      const pane = w.querySelector(`[data-checklist-pane="${cssEsc(tab.dataset.checklistRole)}"]`);
      const boxes = pane ? [...pane.querySelectorAll("[data-check-item]")] : [];
      const done = boxes.filter((box) => box.checked).length;
      const count = tab.querySelector("span");
      if (count) count.textContent = `${done}/${boxes.length}`;
      tab.classList.toggle("complete", boxes.length > 0 && done === boxes.length);
    });
  };
  window.InlineChecklistEditor?.mount(w,data.card_id,(lists, checklistId)=>{
    data.checklists=lists;
    const list=lists.find(list=>list.id===checklistId);
    const current=[...w.querySelectorAll('[data-checklist-id]')].find(el=>el.dataset.checklistId===checklistId);
    if(list&&current)current.outerHTML=renderChecklist(list);
    else if(list){w.querySelector('.checklist-section > .aud-empty')?.remove();w.querySelector('[data-new-checklist]').insertAdjacentHTML('beforebegin',renderChecklist(list));}
    refreshChecklistProgress();
  });
  w.querySelectorAll("[data-attachment-url]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.attachmentUrl) pywebview.api.open_url(button.dataset.attachmentUrl);
  }));
  w.addEventListener("change", async event => {
    const box=event.target.closest('[data-check-item]');if(!box)return;
    const row = box.closest(".check-row");
    row?.classList.toggle("checked", box.checked);
    refreshChecklistProgress();
    box.disabled = true;
    let result;
    try {
      result = await pywebview.api.set_job_check_item(data.card_id || "", box.dataset.checkItem, box.checked,
        box.dataset.checkName || "", data.client || res.client || "");
    } catch (error) { result = {ok: false, error: String(error)}; }
    finally { box.disabled = false; }
    if (!result?.ok) {
      box.checked = !box.checked; row?.classList.toggle("checked", box.checked);
      refreshChecklistProgress();
      setStatus(`Checklist update failed: ${result?.error || "Trello unavailable"}`, "error");
    } else if (result.comment_ok === false) {
      setStatus(`Checklist saved, but automatic comment failed: ${result.comment_error || "Trello unavailable"}`, "warn");
    } else if (result.warning) {
      setStatus(`Saved in OneLoss · Trello sync needs attention`, "warn");
    } else {
      setStatus(result.comment_ok ? "Checklist saved · automatic comment posted" : "Checklist saved", "ok");
    }
  });
  const refreshAfterRequirement = async () => {
    const refreshed = await pywebview.api.refresh_job_card_workspace(
      data.client || res.client || "", data.card_id || "", data.selected_division || "EMS");
    if (refreshed?.ok) {
      close(true);
      openAuditModal(refreshed, refreshed.selected_trello_url || trelloUrl);
    }
    return refreshed;
  };
  // Section payer editor: reuse exact-card resolution and optimistic save guards.
  w.querySelector('[data-edit-payer]')?.addEventListener('click', async event => {
    const trigger=event.currentTarget, host=w.querySelector('[data-payer-editor]');
    trigger.disabled=true;host.textContent='Loading saved payer…';
    try {
      const client=data.client||res.client||'', card=data.card_id||res.card_id||'';
      const result=await pywebview.api.section_profile_review(client,card);
      if(!result?.ok)throw Error(result?.error||'Could not load payer.');
      host.innerHTML=`<label>Payer for ${escapeHtml(result.section)} <select data-payer-choice>${[['','Not confirmed'],['insurance','Insurance'],['self_pay','Self Pay'],['commercial','Commercial'],['management','Property management']].map(([value,label])=>`<option value="${value}" ${result.facts.payer_type===value?'selected':''}>${label}</option>`).join('')}</select></label> <button type="button" class="action-btn" data-save-payer>Save payer</button> <button type="button" class="action-btn" data-cancel-payer>Cancel</button><small data-payer-status role="status">Only this section changes. Self Pay uses Home Improvement Contract and Certificate of Satisfaction, plus job-specific forms.</small>`;
      host.querySelector('[data-cancel-payer]').onclick=()=>{host.replaceChildren();trigger.disabled=false;};
      host.querySelector('[data-save-payer]').onclick=async()=>{
        const status=host.querySelector('[data-payer-status]'),payer=host.querySelector('[data-payer-choice]').value;
        if(!payer){status.textContent='Choose a payer first.';return;}
        host.querySelectorAll('button,select').forEach(el=>el.disabled=true);
        status.textContent='Saving payer…';
        try {
          const saved=await pywebview.api.section_profile_save(client,card,{...result.facts,payer_type:payer},result.expected_token,'');
          if(!saved?.ok)throw Error(saved?.error||'Save not confirmed.');
          status.textContent='Payer saved. Refreshing forms…';
          const fresh=await refreshAfterRequirement();
          if(!fresh?.ok){status.textContent='Payer saved, but forms could not refresh. Reopen the card.';host.querySelector('[data-cancel-payer]').disabled=false;}
        }catch(error){status.textContent=error.message||'Could not save payer. Reopen this editor before retrying.';host.querySelector('[data-cancel-payer]').disabled=false;}
      };
      host.querySelector('[data-payer-choice]').focus();
    }catch(error){host.textContent=error.message||'Could not load payer.';trigger.disabled=false;}
  });
  // End section payer editor.
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
        data.client || res.client || "", item.key, previousState || "todo", "Undo completion", {}, data.card_id || "");
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
        editor.querySelector("textarea")?.value || "", details, data.card_id || "");
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
  w.querySelector('[data-section-profile-review]')?.addEventListener('click', async (event) => {
    const trigger=event.currentTarget;
    let host=w.querySelector('[data-section-profile-panel]');
    if(!host){host=document.createElement('section');host.dataset.sectionProfilePanel='';trigger.after(host);}
    async function review(facts){
      trigger.disabled=true;host.textContent='Checking this section’s profiles…';
      try {
        const result=await pywebview.api.section_profile_review(data.client||res.client||'',data.card_id||res.card_id||'',facts);
        if(!result?.ok)throw Error(result?.error||'Could not load section profiles.');
        host.innerHTML=`<h4>${escapeHtml(result.section)} · Profile review</h4><p>${escapeHtml(result.notice)}</p>
          <p>Save payer and carrier for this section only. Customer information and other sections stay unchanged.</p>
          <label>Payer for this section <select data-profile-payer>${[['','Not confirmed'],['insurance','Insurance'],['self_pay','Self-pay'],['commercial','Commercial'],['management','Property management']].map(([v,n])=>`<option value="${v}" ${result.facts.payer_type===v?'selected':''}>${n}</option>`).join('')}</select></label>
          <label>Carrier / client <input data-profile-carrier value="${escapeAttr(result.facts.carrier)}"></label>
          <label>Loss type <input data-profile-loss value="${escapeAttr(result.facts.loss_type)}"></label>
          <button type="button" class="action-btn" data-profile-recheck>Update suggestions</button>
          <button type="button" class="action-btn" data-profile-save>Save section details</button>
          <label>Profile to add <select data-section-profile-choice><option value="">Details only — no new requirements</option>${result.profiles.filter(p=>!p.missing.length).map(p=>`<option value="${escapeAttr(p.profile_id)}">${escapeHtml(p.name)}</option>`).join('')}</select></label>
          <button type="button" class="action-btn" data-profile-apply>Save and add selected profile</button>
          <p data-section-save-status role="status"></p>
          ${result.profiles.map(p=>`<details class="requirement-history" ${p.profile_id===result.suggested_id?'open':''}><summary>${escapeHtml(p.name)}${p.profile_id===result.suggested_id?' · Suggested':''}</summary><p>Matches: ${escapeHtml(p.reasons.join(' · '))}</p>${p.missing.length?`<p>Needs confirmation: ${escapeHtml(p.missing.join(', '))}</p>`:''}<ul>${p.requirements.map(r=>`<li>${escapeHtml(typeof r==='string'?r:r.label||'')}</li>`).join('')}</ul></details>`).join('')||'<p>No matching active profiles. Check Settings → Job Profiles.</p>'}`;
        host.querySelector('[data-profile-recheck]').onclick=()=>review({payer_type:host.querySelector('[data-profile-payer]').value,carrier:host.querySelector('[data-profile-carrier]').value,loss_type:host.querySelector('[data-profile-loss]').value});
        async function saveSection(apply){
          const profileId=apply?host.querySelector('[data-section-profile-choice]').value:'';
          const status=host.querySelector('[data-section-save-status]');
          if(apply&&!profileId){status.textContent='Choose a profile first.';return;}
          if(apply&&!confirm(`Add this profile’s requirements to ${result.section}? Existing requirements will remain.`))return;
          const buttons=host.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
          const facts={payer_type:host.querySelector('[data-profile-payer]').value,carrier:host.querySelector('[data-profile-carrier]').value,loss_type:host.querySelector('[data-profile-loss]').value};
          try{
            const saved=await pywebview.api.section_profile_save(data.client||res.client||'',data.card_id||res.card_id||'',facts,result.expected_token,profileId);
            if(!saved?.ok)throw Error(saved?.error||'Save failed');
            setStatus(`${result.section} details saved${apply?' and profile added':''}. Reopen the card to refresh requirements.`,'ok');
            await review();
          }catch(error){status.textContent=error.message||'Save failed. Reload and retry.';}
          finally{buttons.forEach(b=>b.disabled=false);}
        }
        host.querySelector('[data-profile-save]').onclick=()=>saveSection(false);
        host.querySelector('[data-profile-apply]').onclick=()=>saveSection(true);
      }catch(error){host.textContent=error.message||'Could not load section profiles. Try again.';}
      finally{trigger.disabled=false;}
    }
    await review();
  });
  w.querySelector('[data-job-profile-apply]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const id = w.querySelector('[data-job-profile]')?.value;
    const profile = profileChoices.find(p => p.profile_id === id);
    if (!profile || !confirm(`Add requirements from “${profile.name}”? Existing requirements will stay. Use only one full baseline to avoid duplicates.`)) return;
    button.disabled = true;
    try {
      const result = await pywebview.api.apply_job_profile(data.client || res.client || '', id, data.card_id || '');
      if (!result?.ok) throw new Error(result?.error || 'Could not apply profile');
      setStatus(`${profile.name} applied`, 'ok');
      document.querySelector('.audit-overlay [data-close]')?.click();
      await onAuditCard(data.client || res.client || '', data.card_id || '', '', data.selected_division || 'EMS');
    } catch (error) { setStatus(error.message || 'Could not apply profile', 'error'); }
    finally { button.disabled = false; }
  });
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
        data.client || res.client || "", item.key, "completed", "", {}, data.card_id || "");
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
  let contentsJobKey = crm.canon_key || "";
  if (w._contentsListener) window.removeEventListener("pipeline:contents-card", w._contentsListener);
  w._contentsListener = event => {
    if (!w.isConnected) { window.removeEventListener("pipeline:contents-card", w._contentsListener); return; }
    const result = event.detail || {};
    if (!contentsJobKey || result.job_key !== contentsJobKey) return;
    const division = String(result.division || "CONTENTS").toUpperCase();
    const label = {EMS: "EMS", CONTENTS: "Contents", RECON: "Recon"}[division];
    if (!label) return;
    const saveState = w.querySelector("[data-job-save-state]");
    if (!result.ok) {
      if (saveState) saveState.textContent = `Saved · ${label} card waiting to sync`;
      setStatus(result.error || `${label} is saved. Card creation will retry in the background.`, "warn");
      return;
    }
    divisionCards[division.toLowerCase()] = { card_id: result.card_id, url: result.url, pinned: true };
    const section = w.querySelector(`[data-work-type-card="${label}"] .division-trello`);
    if (section) {
      section.classList.add("is-pinned");
      section.querySelector("span").textContent = "📌 Trello card pinned";
      const pin = section.querySelector(`[data-division-trello-pin="${label}"]`);
      if (pin) pin.textContent = "Change";
      if (!section.querySelector(`[data-division-trello-open="${label}"]`)) {
        const open = document.createElement("button");
        open.className = "text-btn"; open.textContent = "Open";
        open.dataset.divisionTrelloOpen = label;
        open.addEventListener("click", () => pywebview.api.open_url(divisionCards[division.toLowerCase()].url));
        section.querySelector("div").prepend(open);
      }
    }
    if (saveState) saveState.textContent = `Saved · ${label} card linked`;
    setStatus(`${label} card is linked to this job`, "ok");
  };
  window.addEventListener("pipeline:contents-card", w._contentsListener);
  const saveWorkType = async (select) => {
    if (select.disabled || !select.isConnected) return;
    const name = select.dataset.workEnv;
    const ownerDraftKey = `work-owner-${name}`;
    const tile = select.closest("[data-work-type-card]");
    const ownerInput = tile?.querySelector(`[data-work-env-owner="${name}"]`);
    const owner = ownerInput?.value || "";
    const requestedStage = select.value;
    const previousStage = visibleWorkStage((select._confirmedWorkEnvironment || workTypeState[name.toLowerCase()])?.stage || 'not_applicable');
    const section = tile?.closest('.aud-section');
    if (section) editedSections.add(workspaceSectionKey(section));
    let feedback = tile?.querySelector('[data-work-save-feedback]');
    if (!feedback && tile) {
      feedback = document.createElement('p'); feedback.dataset.workSaveFeedback = '';
      feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
      tile.append(feedback);
    }
    if (feedback) feedback.textContent = requestedStage === 'ready_for_billing' && name === 'EMS'
      ? 'Saving · moving to Estimating / Snapshot…' : 'Saving…';
    tile?.setAttribute('aria-busy', 'true');
    tile?.classList.toggle('has-stage', requestedStage !== 'not_applicable');
    const saveState = w.querySelector("[data-job-save-state]");
    if (saveState) saveState.textContent = "Saving…";
    select.disabled = true;
    if (ownerInput) ownerInput.disabled = true;
    let result;
    try {
      result = await pywebview.api.save_crm_work_environment(
        data.client || res.client || "", name, requestedStage, owner, data.card_id || "");
    } catch (error) {
      result = {ok: false, error: error?.message || String(error)};
    } finally {
      select.disabled = false;
      if (ownerInput) ownerInput.disabled = false;
      tile?.removeAttribute('aria-busy');
    }
    if (!result?.ok) {
      select.dataset.workSaveUncertain = 'true';
      select.value = previousStage;
      tile?.classList.toggle('has-stage', previousStage !== 'not_applicable');
      if (feedback) {
        // A transport failure can arrive after the DB commit. Restore only
        // the displayed value; never claim the server rolled the action back.
        feedback.textContent = 'Save not confirmed. Previous status shown; check details before retrying. ';
        const verify = document.createElement('button'); verify.type = 'button'; verify.className = 'text-btn';
        verify.textContent = 'Check details';
        verify.onclick = async () => {
          verify.disabled = true; verify.textContent = 'Checking…';
          try {
            const fresh = await pywebview.api.refresh_job_card_workspace(
              data.client || res.client || '', data.card_id || '', data.selected_division || 'EMS');
            if (!fresh?.ok) throw new Error(fresh?.error || 'Saved details unavailable');
            if (w.isConnected) controller.applyRefresh(fresh);
          } catch (error) {
            if (w.isConnected) setStatus(`Could not verify saved status: ${error?.message || error}`, 'warn');
          } finally { verify.disabled = false; verify.textContent = 'Check details'; }
        };
        const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'text-btn';
        retry.textContent = 'Retry';
        retry.onclick = () => { select.value = requestedStage; void saveWorkType(select); };
        feedback.append(verify, document.createTextNode(' · '), retry);
      }
      if (saveState) saveState.textContent = "Save not confirmed";
      if (w.isConnected) setStatus(`Could not update ${name}: ${result?.error || "unknown error"}`, "error");
      return;
    }
    const confirmed = {...workTypeState[name.toLowerCase()], ...result.work_environment,
      work_environment:name, stage:result.work_environment?.stage || requestedStage, owner};
    workTypeState[name.toLowerCase()] = confirmed;
    select._confirmedWorkEnvironment = confirmed;
    delete select.dataset.workSaveUncertain;
    crm.work_environments = [...(crm.work_environments || []).filter(env => env.work_environment?.toLowerCase() !== name.toLowerCase()), confirmed];
    if (feedback) feedback.textContent = 'Saved in OneLoss';
    clearDraftDirty(ownerDraftKey);
    if (result.job_key) contentsJobKey = result.job_key;
    if (saveState) saveState.textContent = "Saved";
    if (name === 'EMS' && result.work_environment?.field_work_completed_at) {
      const stamp = w.querySelector('[data-field-work-completed]');
      if (stamp) { stamp.hidden = false; stamp.textContent = `Field work completed · ${new Date(result.work_environment.field_work_completed_at).toLocaleString()}`; }
      if (requestedStage === 'ready_for_billing') {
        if (saveState) saveState.textContent = 'Saved · Estimating / Snapshot · Trello sync queued';
        if (feedback) feedback.textContent = 'Saved · updating card location…';
        const generation = ++placementMutationGeneration;
        void (async () => {
          try {
            const context = await pywebview.api.card_placement_context(data.card_id);
            if (generation !== placementMutationGeneration) {
              if (w.isConnected && feedback) feedback.textContent = 'Saved. Newer board activity is being shown; refresh Jobs to verify location.';
              return;
            }
            const location = acceptSavedCardPlacement(context, data.card_id);
            if (!location) throw new Error('Saved location could not be confirmed');
            data.app_placement = {...data.app_placement, ...location};
            if (!w.isConnected) return;
            for (const [key, value] of [['app_board',location.board], ['app_lane',location.lane]]) {
              const label = w.querySelector(`[data-move-job-location="${key}"] strong`);
              if (label) label.textContent = value;
            }
            if (feedback) feedback.textContent = `Saved · ${location.board} / ${location.lane}`;
          } catch (_) {
            if (w.isConnected && feedback) feedback.textContent = 'Saved. Card location could not refresh; use Refresh Jobs. Do not resubmit.';
          }
        })();
      }
    }
    tile?.classList.toggle("has-stage", select.value !== "not_applicable");
    if ((result.division_card || result.contents_card)?.pending) {
      if (saveState) saveState.textContent = `Saved · Linking ${name} card…`;
      if (w.isConnected) setStatus(`${name} saved. Creating or linking its card in the background.`, "ok");
    } else if (w.isConnected) setStatus(`${name} updated for this job`, "ok");
  };
  w.querySelectorAll("[data-work-env]").forEach((select) =>
    select.addEventListener("change", () => saveWorkType(select)));
  w.querySelectorAll("[data-work-env-owner]").forEach((input) =>
    {
      input.addEventListener("input", () => markDraftDirty(`work-owner-${input.dataset.workEnvOwner}`, true));
      input.addEventListener("change", () => {
      const select = w.querySelector(`[data-work-env="${input.dataset.workEnvOwner}"]`);
      if (select) saveWorkType(select);
      });
    });
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
  w.querySelectorAll("[data-placement-open]").forEach((button) =>
    button.addEventListener("click", () => pywebview.api.open_url(button.dataset.placementOpen || "")));
  w.querySelector("[data-link-ems-copy]")?.addEventListener("click", () => {
    const source = divisionCards.ems?.card_id || "";
    openEmsCopyLinkModal(data.client || res.client || "", source, async () => {
      close();
      await onAuditCard(data.client || res.client || "", data.card_id || "", "", "EMS");
    });
  });
  w.querySelectorAll('[data-create-ems-copy]').forEach(button => button.addEventListener('click', () => {
    const source = selectedDivision === 'EMS' ? data.card_id : divisionCards.ems?.card_id;
    openEmsCopyCreateModal(data.client || res.client || '', source || '', async () => {
      close();
      await onAuditCard(data.client || res.client || '', data.card_id || '', '', 'EMS');
    });
  }));
  w.querySelectorAll("[data-division-trello-use]").forEach((button) =>
    button.addEventListener("click", () => {
      const division = button.dataset.divisionTrelloUse;
      pinDivisionCard(division, data.card_id || "");
    }));
  const linkDivisionTab = division => {
      openChangePinnedTrelloCard({dataset: {client: data.client || res.client || "", division, cardId:data.card_id || ''}}, async result => {
        if (!w.isConnected) return;
        if (result.card_id) {
          const linked = {division, card_id:result.card_id, url:result.url || '', pinned:true};
          divisionTargets[division] = linked;
          const index = workspaceDivisionCards.findIndex(card => card.division === division);
          if (index >= 0) workspaceDivisionCards[index] = linked; else workspaceDivisionCards.push(linked);
          const button = w.querySelector(`[data-division-data="${division}"]`);
          if (button) {button.dataset.unlinked='false';button.title=`Open ${division} job and comments`;}
          if (data.division_card_reconciliation?.divisions) data.division_card_reconciliation.divisions = data.division_card_reconciliation.divisions.filter(item => item.division !== division);
        }
        if (!close()) {
          setStatus(`${division} card linked. Finish your open draft, then use its tab.`, "warn");
          return;
        }
        notifyJobWorkspaceClosed();
        await onAuditCard(data.client || res.client || "", result.card_id || data.card_id || "", result.url || "", result.card_id ? division : selectedDivision);
      });
  };
  w.querySelectorAll("[data-division-trello-pin]").forEach(button =>
    button.addEventListener('click', () => linkDivisionTab(button.dataset.divisionTrelloPin)));
  w.querySelectorAll("[data-division-trello-remove]").forEach((button) =>
    button.addEventListener("click", async () => {
      const division = button.dataset.divisionTrelloRemove;
      if (!window.confirm(`Remove the pinned ${division} Trello card?`)) return;
      const result = await pywebview.api.unpin_crm_division_trello(
        data.client || res.client || "", division, data.card_id || "");
      if (!result?.ok) { setStatus(result?.error || "Could not remove card", "error"); return; }
      close(); await onAuditCard(data.client || res.client || "", data.card_id || "", "", data.selected_division || "EMS");
      setStatus(`${division} Trello card removed`, "ok");
    }));
  w.querySelectorAll("[data-open-docusign]").forEach(button => button.addEventListener("click", async () => {
    try {
      if (await pywebview.api.open_docusign() === false) setStatus("DocuSign could not be opened.", "error");
    } catch (_) { setStatus("DocuSign could not be opened. Try again.", "error"); }
  }));
  w.querySelectorAll("[data-companycam-report]").forEach((control) => control.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const originalHtml = button.innerHTML;
    button.disabled = true; button.textContent = "Finding project…";
    setStatus("Matching this job to CompanyCam…");
    const result = await pywebview.api.open_companycam_report_editor(
      data.client || res.client || "", res.path || "", selectedDivision, "", data.card_id || "");
    button.disabled = false; button.innerHTML = originalHtml;
    if (!result?.ok) {
      setStatus(result?.error || "CompanyCam could not be opened.", "error");
      return;
    }
    setStatus(result.docs_folder
      ? `CompanyCam opened · finished PDF belongs in ${result.docs_folder}`
      : "CompanyCam opened · choose Documents → Reports to build the report.", "ok");
  }));
  w.querySelectorAll("[data-quick-photo-report]").forEach((control) => control.addEventListener("click", () =>
    openQuickPhotoReportModal(data.client || res.client || "", res.path || "", selectedDivision, data.card_id)));
  w.querySelectorAll("[data-open-docs-folder]").forEach((button) => {
    button.addEventListener("click", openFolder);
    button.addEventListener("contextmenu", showFolderContext);
  });
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
  w.querySelector('[data-create-snapshot]')?.addEventListener('click', () => {
    if (dirtyDrafts.has('job-log')) { setStatus('Save or cancel the Job Log edit before creating a Snapshot.', 'warn'); return; }
    window.parent.postMessage({type:'ems-open-tool-modal', key:'snapshot', focus:data.client || res.client || '', cardId:data.card_id || '', division:selectedDivision, create:true}, '*');
  });
  w.querySelector('[data-print-job-log]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const status = w.querySelector('[data-job-log-export-status]');
    button.disabled = true;
    status.textContent = 'Preparing PDF…';
    try {
      const result = await pywebview.api.export_job_log_pdf({
        client: data.client || res.client || '', division: selectedDivision,
        carrier: copyField('carrier'), dol: copyField('dol'),
        entries: crm.job_log || []
      });
      status.textContent = !result?.ok ? result?.error || 'Could not create PDF.'
        : result.cancelled ? '' : `PDF saved${result.opened ? ' — print from the PDF viewer' : ''}: ${result.path}`;
    } catch (error) { status.textContent = `Could not create PDF: ${error.message || error}`; }
    finally { button.disabled = false; }
  });
  const applyLogFilter = () => {
    const party = w.querySelector('[data-log-party-filter]').value;
    const query = (w.querySelector('[data-log-search]')?.value || '').trim().toLowerCase();
    const company = w.querySelector('[data-log-company-filter]').value;
    w.querySelector('[data-log-company-filter-row]').hidden = party !== 'subcontractor';
    let visible = 0;
    w.querySelectorAll('[data-job-log-id]').forEach(row => {
      const entry = (crm.job_log || []).find(e => e.entry_id === row.dataset.jobLogId) || {};
      row.hidden = !(party === 'all' || (entry.work_party || '') === party) ||
        (party === 'subcontractor' && company !== '' && entry.subcontractor !== company) ||
        (query && ![entry.work_type,entry.note,entry.equipment,entry.technicians,entry.subcontractor].join(' ').toLowerCase().includes(query));
      if (!row.hidden) visible++;
    });
    w.querySelector('[data-log-filter-count]').textContent = `${visible} of ${(crm.job_log || []).length} updates`;
    w.querySelector('[data-log-filter-empty]').hidden = visible > 0 || !(crm.job_log || []).length;
  };
  w.querySelectorAll('[data-log-party-filter], [data-log-company-filter]').forEach(el => el.addEventListener('change', applyLogFilter));
  const logSearch=document.createElement('input');logSearch.type='search';logSearch.dataset.logSearch='';logSearch.placeholder='Search work, crew, or notes…';logSearch.setAttribute('aria-label','Search job log');
  w.querySelector('[data-log-filters]').prepend(logSearch);logSearch.addEventListener('input',applyLogFilter);
  applyLogFilter();
  const openJobLogEditor = (entry = {}) => {
    const host = w.querySelector("[data-job-log-editor]");
    if (!host.hidden) { host.querySelector('input,select,textarea')?.focus(); setStatus('Save or cancel the open update first.', 'warn'); return; }
    const row = entry.entry_id ? [...w.querySelectorAll('[data-job-log-id]')].find(el => el.dataset.jobLogId === entry.entry_id) : null;
    const home = document.createComment('Job Log editor home');
    host.before(home);
    const rowHeight = row?.getBoundingClientRect().height;
    const originalChildren = row ? [...row.children].map(el => [el, el.hidden]) : [];
    if (row) {
      originalChildren.forEach(([el]) => { el.hidden = true; });
      row.classList.add('is-editing'); row.append(host);
    }
    const filters = [...w.querySelectorAll('[data-log-filters] select')];
    filters.forEach(el => { el.disabled = true; });
    const animateHeight = (el, from) => {
      el?._jobLogMotion?.cancel();
      if (!el || !from || !el.animate || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const to = el.getBoundingClientRect().height;
      el._jobLogMotion = el.animate([{height:`${from}px`,overflow:'hidden'}, {height:`${to}px`,overflow:'hidden'}], {duration:180,easing:'cubic-bezier(.2,.7,.2,1)'});
    };
    const closeEditor = () => {
      const height = row?.getBoundingClientRect().height;
      home.replaceWith(host);
      host.hidden = true; host.innerHTML = '';
      originalChildren.forEach(([el, hidden]) => { el.hidden = hidden; });
      row?.classList.remove('is-editing');
      filters.forEach(el => { el.disabled = false; });
      return height;
    };
    host._draft?.dispose(); recoveredDrafts.delete(host._draft);
    const today = new Date().toISOString().slice(0, 10);
    const activities = ["Initial inspection", "Demo", "Monitor", "Equipment placed", "Equipment pickup", "Contents", "Recon", "Final inspection"];
    const statuses = ["scheduled", "completed", "rescheduled", "cancelled", "skipped", "needs_review"];
    host.hidden = false;
    host.innerHTML = `<div class="job-log-form">
      <label>Date<input type="date" data-log-field="work_date" value="${escapeAttr(entry.work_date || today)}"></label>
      <label>Activities<select data-log-field="work_type">${activities.map((x) => `<option>${x}</option>`).join("")}</select></label>
      <label>Status<select data-log-field="status">${statuses.map((x) => `<option value="${x}" ${x === (entry.status || "completed") ? "selected" : ""}>${x.replaceAll("_", " ")}</option>`).join("")}</select></label>
      <label>Work performed by<select data-log-field="work_party"><option value="" ${entry.entry_id && !entry.work_party ? 'selected' : ''}>Unclassified</option><option value="crew" ${entry.work_party === 'crew' || !entry.entry_id ? 'selected' : ''}>Our crew</option><option value="subcontractor" ${entry.work_party === 'subcontractor' ? 'selected' : ''}>Subcontractor</option></select></label>
      <label data-log-company-row ${entry.work_party === 'subcontractor' ? '' : 'hidden'}>Subcontractor company<input data-log-field="subcontractor" list="job-log-companies" value="${escapeAttr(entry.subcontractor || '')}" placeholder="Select or enter company"><datalist id="job-log-companies">${[...new Set((crm.job_log || []).map(e => e.subcontractor).filter(Boolean))].sort().map(name => `<option value="${escapeAttr(name)}"></option>`).join('')}</datalist></label>
      <label>Technician / crew<input data-log-field="technicians" value="${escapeAttr(entry.technicians || "")}" placeholder="Who completed the work?"></label>
      <label class="wide">Work completed / update<textarea rows="3" data-log-field="note" placeholder="Areas worked, findings, what was completed, and the next step">${escapeHtml(entry.note || "")}</textarea></label>
      <label class="wide">Equipment / readings<input data-log-field="equipment" value="${escapeAttr(entry.equipment || "")}" placeholder="Equipment placed, moved, readings, or pickup"></label>
      ${!entry.entry_id ? `<label class="wide job-log-post-option"><input type="checkbox" data-log-post-trello checked><span>Also post this new entry as a Trello comment<small>Uncheck to save in OneLoss only.</small></span></label>` : entry.source === 'pc_only' ? `<p class="wide">OneLoss-only entry · no Trello comment will be created.</p>` : ''}
      <div class="job-log-form-actions"><button class="btn btn-primary" data-save-job-log>Save update</button><button class="btn" data-cancel-job-log>Cancel</button></div></div>`;
    const partySelect = host.querySelector('[data-log-field="work_party"]');
    const companyInput = host.querySelector('[data-log-field="subcontractor"]');
    const syncParty = () => { host.querySelector('[data-log-company-row]').hidden = partySelect.value !== 'subcontractor'; companyInput.required = partySelect.value === 'subcontractor'; };
    partySelect.addEventListener('change', syncParty);
    syncParty();
    host.querySelector('[data-log-post-trello]')?.addEventListener('change', () => markDraftDirty('job-log', true));
    host.querySelectorAll("[data-log-field]").forEach((field) =>
      field.addEventListener("input", () => markDraftDirty("job-log", true)));
    const activitySelect = host.querySelector('[data-log-field="work_type"]');
    const activityPicker = JobActivities.mount(activitySelect, entry.work_type, host.querySelector('[data-log-field="technicians"]'));
    const logDraft = window.JobDrafts?.mount(host, [data.card_id || '', selectedDivision, 'job-log', entry.entry_id || ''], () => {
      const fields = Object.fromEntries([...host.querySelectorAll('[data-log-field]')].map(field => [field.dataset.logField, field.value]));
      return {...fields, post_to_trello: host.querySelector('[data-log-post-trello]')?.checked};
    }, saved => {
      host.querySelectorAll('[data-log-field]').forEach(field => { if (saved[field.dataset.logField] !== undefined) field.value = saved[field.dataset.logField]; });
      activityPicker.set(saved.work_type === '__custom__' ? saved.custom : saved.work_type, saved.technicians || '');
      syncParty();
      const post = host.querySelector('[data-log-post-trello]'); if (post) post.checked = saved.post_to_trello === true;
      markDraftDirty('job-log', true);
    });
    host._draft = logDraft;
    if (logDraft) recoveredDrafts.add(logDraft);
    host.querySelector("[data-cancel-job-log]").addEventListener("click", () => {
      logDraft?.clear(); logDraft?.dispose(); recoveredDrafts.delete(logDraft);
      clearDraftDirty("job-log");
      const height = closeEditor(); animateHeight(row, height);
      row?.querySelector('[data-edit-job-log]')?.focus({preventScroll:true});
    });
    host.querySelector("[data-save-job-log]").addEventListener("click", async (event) => {
      const payload = {entry_id: entry.entry_id || "", source: entry.source || "pc", source_id: entry.source_id || "", trello_comment_id: entry.trello_comment_id || ""};
      host.querySelectorAll("[data-log-field]").forEach((field) => { payload[field.dataset.logField] = field.value; });
      if (!entry.entry_id) payload.post_to_trello = host.querySelector('[data-log-post-trello]').checked;
      if (!payload.work_type) { activityPicker.focus(); setStatus('Select at least one activity.', 'error'); return; }
      if (payload.work_party === 'subcontractor' && !payload.subcontractor.trim()) { companyInput.setCustomValidity('Enter the subcontractor company.'); companyInput.reportValidity(); companyInput.oninput = () => companyInput.setCustomValidity(''); return; }
      if (payload.work_party !== 'subcontractor') payload.subcontractor = '';
      const button = event.currentTarget; button.disabled = true; button.textContent = "Saving…";
      const controls = [...host.querySelectorAll('input,select,textarea,button')];
      controls.forEach(el => { el.disabled = true; });
      let result;
      try { result = await pywebview.api.save_job_log_update(
        data.client || "", payload, data.card_id || "", selectedDivision); }
      catch (_) { result = {ok:false,error:'Save could not be confirmed. Your draft is still here; check before retrying.'}; }
      if (!result?.ok || !result.entry?.entry_id) {
        controls.forEach(el => { el.disabled = false; });
        button.disabled = false; button.textContent = "Save update";
        let notice = host.querySelector('[data-log-save-status]');
        if (!notice) { notice=document.createElement('p'); notice.dataset.logSaveStatus=''; notice.setAttribute('role','alert'); host.append(notice); }
        notice.textContent = result?.error || 'Job Log save could not be confirmed.';
        setStatus(notice.textContent, "error"); return;
      }
      clearDraftDirty("job-log");
      logDraft?.clear(); logDraft?.dispose(); recoveredDrafts.delete(logDraft);
      const height = closeEditor();
      controller.applyJobLogSave(result);
      const savedRow = [...w.querySelectorAll('[data-job-log-id]')].find(el => el.dataset.jobLogId === result.entry.entry_id);
      animateHeight(savedRow, height);
      savedRow?.querySelector('[data-edit-job-log]')?.focus({preventScroll:true});
    });
    animateHeight(row, rowHeight);
    if (!row) host.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: "nearest" });
    activityPicker.focus();
  };
  w.querySelectorAll("[data-add-job-log]").forEach((button) => button.addEventListener("click", () => openJobLogEditor({})));
  w.querySelector('[data-refresh-job-log]')?.addEventListener('click', async (event) => {
    if (w.querySelector('[data-job-log-editor]:not([hidden])')) {
      setStatus('Save or cancel the open Job Log edit before refreshing.', 'error');
      return;
    }
    const button = event.currentTarget;
    button.disabled = true; button.textContent = 'Refreshing saved log…';
    try {
      const result = await pywebview.api.refresh_saved_job_log(data.card_id || '', selectedDivision);
      if (!result?.ok) throw new Error(result?.error || 'Saved log could not refresh');
      controller.applyRefresh({...data, crm:{...crm, ...result.crm}}, true);
      setStatus('Saved Job Log refreshed. No Trello comments imported.', 'ok');
    } catch (error) { setStatus(error.message || 'Refresh failed; your saved log was kept.', 'error'); }
    finally { button.disabled = false; button.textContent = 'Refresh saved log'; }
  });
  w.querySelector("[data-import-job-log]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget; button.disabled = true; button.textContent = "Reading Trello…";
    const result = await pywebview.api.import_job_log_from_trello(
      data.client || "", data.card_id || "", selectedDivision);
    if (!result?.ok) { button.disabled = false; button.textContent = `Pull from ${selectedDivision} Trello`; setStatus(result?.error || "Could not import the job log", "error"); return; }
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
  w.querySelectorAll("[data-delete-job-log], [data-dismiss-job-log]").forEach((button) => button.addEventListener("click", async () => {
    const dismiss = button.hasAttribute('data-dismiss-job-log');
    const entry = (crm.job_log || []).find((item) => item.entry_id === (button.dataset.dismissJobLog || button.dataset.deleteJobLog)) || {};
    const message = dismiss
      ? `Dismiss the incorrect ${entry.work_type || "Job Log"} interpretation?\n\nThe original Trello comment and other interpretations from it will stay.`
      : `Delete the ${entry.work_type || "Job Log"} update from ${entry.work_date || "this job"}?\n\nOnly this OneLoss log entry will be removed. Trello comments will not be changed.`;
    if (!window.confirm(message)) return;
    const originalLabel = button.textContent;
    button.disabled = true; button.textContent = dismiss ? "Dismissing…" : "Deleting…";
    let result;
    try { result = await pywebview.api[dismiss ? 'dismiss_job_log_update' : 'delete_job_log_update'](
      data.client || "", entry.entry_id || "", data.card_id || "", selectedDivision);
    } catch (_) { result = {ok: false, error: 'Deletion could not be confirmed. The entry was kept; check the original comment before retrying.'}; }
    if (!result?.ok) {
      button.disabled = false; button.textContent = originalLabel;
      const message = result?.error || "Job Log change could not be confirmed";
      let notice = button.closest('[data-job-log-id]').querySelector('[data-log-action-error]');
      if (!notice) { notice = document.createElement('p'); notice.dataset.logActionError = ''; notice.setAttribute('role','alert'); button.closest('[data-job-log-id]').append(notice); }
      notice.textContent = message;
      setStatus(message, "error"); return;
    }
    const deletedIds = new Set(result.deleted_ids || [entry.entry_id]);
    crm.job_log_deleted_ids = [...new Set([...(crm.job_log_deleted_ids || []), ...deletedIds])];
    crm.job_log_deleted_sources = [...new Set([...(crm.job_log_deleted_sources || []), ...(result.deleted_sources || [])])];
    crm.job_log = (crm.job_log || []).filter(item => !deletedIds.has(item.entry_id));
    w.querySelectorAll('[data-job-log-id]').forEach(row => {
      if (deletedIds.has(row.dataset.jobLogId)) row.remove();
    });
    if (result.deleted_comment_id) w.querySelectorAll('[data-comment-id]').forEach(row => {
      if (row.dataset.commentId === result.deleted_comment_id) row.remove();
    });
    if (dismiss) {
      let notice = w.querySelector('[data-log-dismissal-state]');
      if (!notice) { notice = document.createElement('p'); notice.dataset.logDismissalState = ''; notice.setAttribute('role','status'); w.querySelector('#job-panel-log').prepend(notice); }
      notice.textContent = result.pending_sync ? 'Dismissed on this PC · waiting to sync. Original Trello comment kept.' : 'Dismissed · original Trello comment kept.';
    }
    setStatus(result.pending_sync ? "Removed from this PC · shared sync pending. Trello comment unchanged." : "Job Log entry deleted · Trello comment unchanged", "ok");
  }));
  const commentInput = w.querySelector("[data-comment-input]");
  window.AuditCommentLinks?.bind(w,target=>{
    const row=target.closest('[data-comment-id]');if(!row)return null;
    return {row,card:row.dataset.commentCardId||data.card_id,comment:{id:row.dataset.commentExternalId||row.dataset.commentId,
      text:row.querySelector('[data-comment-raw]')?.dataset.commentRaw||'',author:row.dataset.auditAuthor||'',date:row.dataset.auditAt||''}};
  });
  const commentSearch = w.querySelector("[data-comment-search]");
  const filterComments = () => {
    const query = String(commentSearch?.value || "").trim().toLocaleLowerCase();
    const rows = Array.from(w.querySelectorAll("[data-comment-stream] [data-comment-id]"));
    let shown = 0;
    rows.forEach((row) => {
      const matches = (!query || row.textContent.toLocaleLowerCase().includes(query)) &&
        (!w._pinnedCommentsOnly || row.dataset.commentPinned === 'true');
      row.hidden = !matches;
      if (matches) shown += 1;
    });
    const count = w.querySelector("[data-comment-search-count]");
    if (count) count.textContent = query ? `${shown} found` : "";
  };
  commentSearch?.addEventListener("input", filterComments);
  const commentSearchToggle = w.querySelector('[data-toggle-comment-search]');
  const setCommentSearchOpen = (open) => {
    commentSearch.closest('.comment-search').hidden = !open;
    commentSearchToggle.setAttribute('aria-expanded', String(open));
    if (open) commentSearch.focus();
    else {
      commentSearch.value = '';
      filterComments();
      commentSearchToggle.focus();
    }
  };
  commentSearchToggle.addEventListener('click', () => setCommentSearchOpen(commentSearchToggle.getAttribute('aria-expanded') !== 'true'));
  commentSearch.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation(); setCommentSearchOpen(false);
    }
  });
  const conflictedDivisions = new Set((data.division_card_reconciliation?.divisions || [])
    .filter(item => ['conflict', 'ambiguous'].includes(item.state))
    .map(item => String(item.division || '').toUpperCase()));
  const conversation = preparation?.conversation || window.JobConversation.mount(w, {
    followWorkspace: true,
    lockedCard: snapshotCommentsMode,
    cardId: data.card_id || '', division: selectedDivision,
    cards: workspaceDivisionCards.map(card => ({...card,
      conflict: conflictedDivisions.has(String(card.division || '').toUpperCase())})),
    placements: data.division_trello_placements || [],
    comments: data.comments || [], render: renderJobComment,
    initialComplete: !data.deferred_loading && !data.refresh_pending && !data.audit?.trello_error && Array.isArray(data.comments),
    initialError: data.audit?.trello_error || '',
    fetchSaved: cardId => snapshotCardMode ? {ok:true,comments:[]} : pywebview.api.saved_job_comments?.(cardId),
    fetch: (cardId, force) => snapshotCardMode ? {ok:true,comments:[]} : !force && w._divisionLoadSession?.comments(cardId) || pywebview.api.refresh_job_comments(cardId), onChange: filterComments,
  });
  workspaceContext = {
    element: w,
    client: data.client || res.client || "",
    cardId: data.card_id || "",
    division: selectedDivision,
    refreshing: false,
    conversation,
  };
  if (!preparation) state.openWorkspace = workspaceContext;
  let editingComment = null;
  const commentDraft = preparation?.commentDraft || (!preparation && !snapshotCardMode && window.JobDrafts?.mount(w.querySelector('.comment-compose'), [data.card_id || '', selectedDivision, 'comment', ''], () =>
    editingComment ? editingComment.draft : commentInput.value.trim() ? {text:commentInput.value, targets:conversation.targets().map(target => target.cardId), reply:w._commentReply || null, unconfirmed:w._commentUnconfirmed || null} : null,
    saved => { commentInput.value = saved.text || ''; w._commentReply = saved.reply || null; w._commentUnconfirmed = saved.unconfirmed || null; w.dispatchEvent(new Event('comment-reply-restored')); conversation.restoreTargets?.(saved.targets || []); markDraftDirty('comment', !!commentInput.value.trim()); }));
  if (commentDraft) recoveredDrafts.add(commentDraft);
  if (snapshotCommentsMode && !preparation) window.flushSnapshotCommentDraft = () => commentDraft?.flush();
  if (!preparation) {
    w.addEventListener('mousedown', event => {
      // Keep the editor from collapsing between pointer-down and click.
      if (event.target.closest('.comment-actions-menu summary')) event.preventDefault();
    }, true);
    w.addEventListener('click', event => {
      const menu = event.target.closest('.comment-actions-menu');
      w.querySelectorAll('.comment-actions-menu[open]').forEach(item => {
        if (item !== menu || event.target.closest('.comment-actions-menu button')) item.open = false;
      });
      if (menu && event.target.closest('.comment-actions-menu summary')) {
        event.preventDefault();
        menu.open = !menu.open;
      }
    }, true);
    commentInput._mentionTargets = () => editingComment ? [{cardId:editingComment.cardId,division:selectedDivision}] : conversation.targets();
    if (!snapshotCardMode) {
      window.CommentMarkdown?.mount(commentInput);
      window.CommentThreads?.mount(w, conversation, data.card_id || '', {isActive: jobsPresentationActive});
    }
  }
  w.querySelector('.comment-compose')?.addEventListener('click', event => {
    if (event.target.closest('[data-comment-destination],[data-comment-placement]')) commentDraft?.capture();
  });
  commentInput?.addEventListener("input", () => markDraftDirty("comment", Boolean(commentInput.value.trim())));
  const editBanner = document.createElement('div');
  editBanner.className = 'comment-edit-banner'; editBanner.hidden = true;
  editBanner.innerHTML = '<strong>Editing comment</strong><span>The original comment will be updated.</span><button type="button" class="text-btn" data-cancel-comment-edit>Cancel edit</button>';
  if (!preparation) w.querySelector('.comment-compose')?.prepend(editBanner);
  function finishCommentEdit() {
    const saved = editingComment; if (!saved) return;
    editingComment = null; w._editingComment = false; editBanner.hidden = true;
    commentInput.value = saved.draft?.text || '';
    w._commentReply = saved.draft?.reply || null;
    if (commentDraft?.notice) commentDraft.notice.hidden = false;
    for (const [control, disabled, threadDisabled] of saved.controls) {
      control.disabled = disabled;
      if (threadDisabled === undefined) delete control.dataset.threadDisabled;
      else control.dataset.threadDisabled = threadDisabled;
    }
    w.dispatchEvent(new Event('comment-reply-restored'));
    w.querySelector('[data-post-comment]').textContent = saved.buttonLabel;
    markDraftDirty('comment', Boolean(commentInput.value.trim()));
    commentDraft?.capture();
  }
  editBanner.querySelector('[data-cancel-comment-edit]').onclick = () => {
    if (editingComment?.saving) return;
    finishCommentEdit(); w.querySelector('[data-comment-state]').textContent = 'Edit canceled. Your previous draft is restored.';
  };
  w.querySelector("[data-post-comment]")?.addEventListener("click", async (event) => {
    if (w._commentSending) return;
    const input = commentInput;
    const stateEl = w.querySelector("[data-comment-state]");
    const text = input.value.trim();
    if (!text) return;
    if (/(^|\s)@members\b/i.test(text)) { stateEl.textContent = 'Select @members from the suggestions to insert the assigned people before saving.'; return; }
    if (editingComment) {
      const edit = editingComment, button = event.currentTarget;
      if (edit.saving) return;
      edit.saving = true; button.disabled = true; stateEl.textContent = 'Saving changes…';
      editBanner.querySelector('button').disabled = true;
      try {
        const result = edit.source === 'thread'
          ? await pywebview.api.edit_job_reply(edit.cardId, edit.id, text, edit.expected)
          : await pywebview.api.edit_job_comment(data.client || '', edit.id, edit.source, text, edit.externalId, edit.cardId);
        if (!result?.ok) throw Error(result?.error || 'Changes could not be saved. Your edit is still here.');
        if (edit.source === 'thread') {
          w.dispatchEvent(new CustomEvent('comment-thread-edited', {detail:result.comment}));
          edit.expected = result.comment.body;
        } else conversation.update(edit.cardId, edit.id, result.text || text);
        // Don't discard typing that happened while a save was in flight.
        if (input.value.trim() === text && !(edit.source === 'thread' && result.warning)) finishCommentEdit();
        stateEl.textContent = result.warning || (editingComment ? 'Saved. You have additional unsaved changes.' : 'Comment updated. Your previous draft is restored.');
      } catch (error) { stateEl.textContent = error.message || 'Changes could not be saved.'; }
      finally { edit.saving = false;button.disabled=false;editBanner.querySelector('button').disabled=false; }
      return;
    }
    const targets = conversation.targets?.() || [conversation.target()];
    const target = targets[0] || {};
    if (!target.cardId) { stateEl.textContent = 'Choose a linked card first'; return; }
    const uncertain = w._commentUnconfirmed;
    if (uncertain?.text === text && targets.some(item => uncertain.cards.includes(item.cardId)) &&
        !window.confirm('The previous delivery was not confirmed. Check the original card first—sending again could duplicate the message. Send again?')) return;
    const button = event.currentTarget;
    w._commentSending = true;
    const destinationControls = [...w.querySelectorAll('[data-comment-destination],[data-comment-placement]')].map(control => [control, control.disabled]);
    destinationControls.forEach(([control]) => { control.disabled = true; });
    button.disabled = true;
    const previousLabel = button.textContent;
    button.textContent = 'Sending…';
    stateEl.setAttribute('role', 'status');
    stateEl.textContent = `Sending to ${targets.map(item => item.division || 'linked card').join(', ')}… You can keep typing.`;
    let result;
    try {
      result = targets.length > 1
        ? await pywebview.api.post_job_comment_multi(
            data.client || "", targets.map(item => item.cardId), text)
        : await pywebview.api.post_job_comment(data.client || "", target.cardId, text);
    }
    catch (error) {
      w._commentUnconfirmed = {text, cards:targets.map(item => item.cardId)};
      commentDraft?.capture();
      stateEl.textContent = 'Delivery could not be confirmed. Your draft is kept; check the card before sending again.';
      return;
    }
    finally {
      w._commentSending = false; button.disabled = false; button.textContent = previousLabel;
      destinationControls.forEach(([control, disabled]) => { control.disabled = disabled; });
    }
    if (!result?.ok) {
      const unknown = result?.unconfirmed || (result?.delivery === 'unconfirmed' ? [target.cardId] : []);
      w._commentUnconfirmed = unknown.length ? {text, cards:unknown} : null;
      if (result?.partial) {
        for (const row of result.results || []) if (row.ok && row.comment) conversation.add(row.card_id, row.comment);
        if (input.value.trim() === text) conversation.retainFailedTargets((result.failed || []).map(row => row.card_id));
        commentDraft?.capture();
      }
      stateEl.textContent = result?.partial
        ? `Saved to ${result.posted} destination(s). ${unknown.length ? 'Other delivery is unconfirmed—check those cards before retrying.' : 'Some destinations failed; your draft is kept.'}`
        : result?.error || result?.warning || "Could not save. Your draft is kept.";
      return;
    }
    w._commentUnconfirmed = null;
    if (targets.length > 1) {
      for (const row of result.results || []) {
        if (row.ok && row.comment) conversation.add(row.card_id, row.comment);
      }
    } else conversation.add(target.cardId, result.comment);
    filterComments();
    const unchanged = input.value.trim() === text;
    if (unchanged) {
      input.value = ""; clearDraftDirty("comment"); commentDraft?.clear();
      conversation.resetTargets();
    } else commentDraft?.capture();
    stateEl.textContent = targets.length > 1
      ? `Saved to ${result.posted || targets.length} linked cards${result.pending_sync ? ' · Trello sync pending' : ' · Trello updated'}`
      : result.warning || (result.pending_sync ? `Saved to ${target.division} · Trello sync pending` : `Saved to ${target.division}`);
    if (!unchanged) stateEl.textContent += ' · Your newer text is still an unsent draft.';
    const notificationWarnings=(result.results||[result]).map(row=>row.notification_warning).filter(Boolean);
    if(notificationWarnings.length)stateEl.textContent=notificationWarnings.join(' ');
  });
  w.addEventListener("click", async (event) => {
    const link = event.target.closest('.comment-markdown a');
    if (link) {
      event.preventDefault();
      const url = link.getAttribute('href') || '';
      if (/^(https?:\/\/|mailto:)/i.test(url)) {
        try { await pywebview.api.open_url(url); }
        catch (_) { setStatus('The comment link could not be opened.', 'error'); }
      }
      return;
    }
    const edit = event.target.closest("[data-comment-edit]");
    const remove = event.target.closest("[data-comment-delete]");
    const button = edit || remove;
    if (!button) return;
    if (w._commentSending) { setStatus('Finish the current send before editing or deleting a comment.', 'warn'); return; }
    const article = button.closest("[data-comment-id]");
    const id = article?.dataset.commentId || "";
    const source = article?.dataset.commentSource || "linguar";
    const externalId = article?.dataset.commentExternalId || "";
    const current = article?.querySelector('[data-comment-raw]')?.dataset.commentRaw ?? article?.querySelector("p")?.textContent ?? "";
    if (edit) {
      if (editingComment) { setStatus('Save or cancel the current edit first.', 'warn'); return; }
      const post = w.querySelector('[data-post-comment]');
      const draft = {text:commentInput.value,targets:conversation.targets().map(t=>t.cardId),reply:w._commentReply || null};
      const controls = [...w.querySelectorAll('[data-comment-destination],[data-comment-placement]')].map(control=>[control,control.disabled,control.dataset.threadDisabled]);
      editingComment = {id,source,externalId,expected:current,cardId:article.dataset.commentCardId || data.card_id,draft,controls,buttonLabel:post.textContent};
      w._editingComment = true;
      w._commentReply = null; w.dispatchEvent(new Event('comment-reply-restored'));
      controls.forEach(([control])=>{control.disabled=true;});
      if (commentDraft?.notice) commentDraft.notice.hidden = true;
      commentInput.value = current; post.textContent = 'Save changes'; editBanner.hidden = false;
      w.querySelector('[data-comment-state]').textContent = '';
      markDraftDirty('comment', true);
      commentInput._richEditor?.editor?.commands.focus('end');
      if (!commentInput._richEditor) commentInput.focus();
      w.querySelector('.comment-compose')?.scrollIntoView({block:'nearest'});
    } else {
      const warning = source === "trello" || externalId ? "This permanently deletes the comment from Trello and OneLoss." : "This deletes the OneLoss comment only.";
      if (!window.confirm(`${warning}\n\nContinue?`)) return;
      button.disabled = true;
      let result;
      try { result = await pywebview.api.delete_job_comment(data.client || "", id, source, externalId, article.dataset.commentCardId); }
      catch (_) { button.disabled = false; setStatus('Deletion could not be confirmed. Check the original card before retrying.', 'error'); return; }
      if (!result?.ok) { button.disabled = false; setStatus(result?.error || "Comment could not be deleted", "error"); return; }
      conversation.remove(article.dataset.commentCardId, id);
      setStatus(result.warning || (source === "trello" || result.synced_trello ? "Comment deleted from OneLoss and Trello" : "OneLoss comment deleted"), result.warning ? "warn" : "ok");
    }
  });
  const controller = {
    element: w,
    close,
    adoptRoot(root) { w = root; },
    applyLinkedComments(cardId, result) {
      if (w.isConnected) conversation.applyInitialRefresh(cardId, result.comments || [], true);
    },
    applyJobLogSave(result) {
      if (!w.isConnected) return;
      const saved = result.entry;
      const rows = (crm.job_log || []).filter(row => row.entry_id !== saved.entry_id);
      rows.push(saved);
      rows.sort((a,b) => String(a.work_date || '').localeCompare(String(b.work_date || '')) || String(a.created_at || '').localeCompare(String(b.created_at || '')));
      crm.job_log = rows;
      const next = {...data, crm};
      const prepared = openAuditModal(next, trelloUrl, {close,dirtyDrafts,editedSections,conversation,recoveredDrafts,commentDraft});
      const currentSection = w.querySelector('.job-log-section');
      const nextSection = prepared.element.querySelector('.job-log-section');
      retainWorkspaceSectionView(currentSection, nextSection);
      patchJobLogSection(currentSection, nextSection);
      prepared.adoptRoot(w);
      updateWorkspaceModel(data, next);
      const message = result.pending_sync ? 'Job Log saved · Trello comment pending sync'
        : saved.source === 'pc_only' ? 'Job Log saved in OneLoss only' : 'Job Log saved';
      const notice = w.querySelector('[data-job-log-status]');
      if (notice) notice.textContent = message;
      setStatus(message, 'ok');
    },
    applyPlacement(placement) {
      const host = w.querySelector('[data-workspace-load-state]');
      const previousStatus = host?.textContent;
      const applied = controller.applyRefresh({ok:true, card_id:data.card_id,
        app_placement:placement, deferred_loading:data.deferred_loading,
        refresh_pending:data.refresh_pending});
      if (host && applied) host.textContent = previousStatus;
      return applied;
    },
    applyRefresh(next, refreshJobLog = false) {
      if (!w.isConnected || (next.card_id && data.card_id && next.card_id !== data.card_id)) return false;
      // A failed transport is not evidence of a rollback. An explicit details
      // refresh can confirm the saved status without replacing crew/comment drafts.
      for (const select of w.querySelectorAll('[data-work-save-uncertain]')) {
        const env = next.crm?.work_environments?.find(row => row.work_environment?.toLowerCase() === select.dataset.workEnv?.toLowerCase());
        if (!env?.stage || select.disabled) continue;
        select._confirmedWorkEnvironment = env;
        select.value = visibleWorkStage(env.stage);
        delete select.dataset.workSaveUncertain;
        const tile = select.closest('[data-work-type-card]');
        tile?.classList.toggle('has-stage', select.value !== 'not_applicable');
        const feedback = tile?.querySelector('[data-work-save-feedback]');
        if (feedback) feedback.textContent = 'Saved status checked';
      }
      const merged = mergeWorkspaceRefresh(data, next, refreshJobLog);
      const prepared = openAuditModal(merged, next.selected_trello_url || trelloUrl, {close, dirtyDrafts, editedSections, conversation,recoveredDrafts,commentDraft});
      // Prepare bound sections off-screen; never detach the visible workspace.
      const quickLabels = w.querySelector('[data-quick-labels]');
      const quickMembers = w.querySelector('[data-quick-members]');
      patchWorkspaceSections(w, prepared.element, editedSections, refreshJobLog);
      const refreshedLabels = w.querySelector('[data-quick-labels]');
      if (quickLabels && refreshedLabels && quickLabels !== refreshedLabels) refreshedLabels.replaceWith(quickLabels);
      const refreshedMembers = w.querySelector('[data-quick-members]');
      if (quickMembers && refreshedMembers && quickMembers !== refreshedMembers) refreshedMembers.replaceWith(quickMembers);
      if (!w.querySelector('[aria-label="Edit this card name in OneLoss and Trello"]')) window.CardTitle?.mount(w, data.client || res.client || '', data.card_id);
      if (w.dataset.renamedCardTitle) w.querySelector('.audit-head-main .modal-title').textContent = w.dataset.renamedCardTitle;
      // Cached cards may predate the layout flag. Move the existing controls,
      // preserving the draft and listeners, when fresh data arrives.
      positionDevCommentComposer(w, merged);
      // Header focus can defer replacement; still remove or update stale links.
      const sketchUrl = savedDocuSketchUrl(merged.info_sections);
      const videoUrl = savedJobLinkUrl(merged.info_sections, 'link_video');
      const videoButton = w.querySelector('[data-initial-video]');
      if (videoButton) {
        videoButton.dataset.videoUrl = videoUrl;
        videoButton.disabled = !videoUrl;
        videoButton.title = videoUrl ? 'Open the saved initial video in your browser' : 'Add an Initial video link in Job info';
      }
      const sketchButton = w.querySelector('[data-open-docusketch]');
      if (sketchButton) {
        sketchButton.dataset.docusketchUrl = sketchUrl || '';
        sketchButton.disabled = !sketchUrl;
        sketchButton.title = sketchUrl ? 'Open saved DocuSketch link' : 'No DocuSketch link saved for this section';
        // Keep the icon and label intact while refreshing link availability.
      }
      else if (sketchUrl) {
        const freshButton = prepared.element.querySelector('[data-open-docusketch]');
        const toolbar = w.querySelector('[data-open-companycam]')?.closest('.tool-quick-menu')?.parentElement;
        if (freshButton && toolbar) toolbar.append(freshButton);
      }
      prepared.adoptRoot(w);
      updateWorkspaceModel(data, merged);
      w.querySelectorAll('[data-open-docs-folder], [data-copy-folder-path], [data-stage-xa]').forEach(button => {
        button.disabled = !data.audit?.path;
      });
      w.querySelector('.job-files-section')?._jobFiles?.update({client:data.client || '', cardId:data.card_id || '', division:selectedDivision, attachments:data.attachments || []});
      if (!next.deferred_loading) {
        const conflicts = new Set((data.division_card_reconciliation?.divisions || []).filter(row => ['conflict','ambiguous'].includes(row.state)).map(row => String(row.division || '').toUpperCase()));
        conversation.updateCards((data.division_trello_cards || []).map(row => ({...row, conflict:conflicts.has(String(row.division || '').toUpperCase())})));
      }
      conversation.applyInitialRefresh(data.card_id, next.comments || [],
        !next.deferred_loading && !next.refresh_pending && !next.audit?.trello_error && Array.isArray(next.comments), next.audit?.trello_error || '');
      const host = w.querySelector('[data-workspace-load-state]');
      if (host) host.textContent = next.audit?.trello_error ? 'Saved details · Trello refresh unavailable' : next.deferred_loading || next.refresh_pending ? 'Saved details · checking for updates' : 'Up to date';
      checkDocuSketchFolder();
      return true;
    },
    hasUserInput() {
      return dirtyDrafts.size > 0;
    },
    applyIfUnchanged(next) {
      if (data.deferred_loading || workspaceContentFingerprint(data) !== workspaceContentFingerprint(next)) return false;
      conversation.applyInitialRefresh(data.card_id, next.comments || [],
        !next.deferred_loading && !next.refresh_pending && !next.audit?.trello_error && Array.isArray(next.comments), next.audit?.trello_error || '');
      const host = w.querySelector('[data-workspace-load-state]');
      if (host) host.textContent = next.cached ? 'Saved details' : 'Up to date';
      return true;
    },
    setDeferredReady(load) {
      const host = w.querySelector("[data-workspace-load-state]");
      if (!host) return;
      host.innerHTML = `<button class="btn compact" type="button">Load live details</button>`;
      host.querySelector("button").addEventListener("click", load);
    },
    setDeferredError(message) {
      data.deferred_loading = false;
      data.refresh_pending = false;
      // Keep saved data and drafts intact; only replace unresolved placeholders.
      for (const placeholder of w.querySelectorAll('.aud-empty')) {
        if (/^Loading .+…$/.test(placeholder.textContent.trim())) {
          placeholder.textContent = 'Details could not be loaded. Use Retry details.';
        }
      }
      const host = w.querySelector("[data-workspace-load-state]");
      if (host) {
        host.replaceChildren();
        const label = document.createElement('span'); label.textContent = message;
        const retry = document.createElement('button');
        retry.type = 'button'; retry.className = 'btn compact'; retry.textContent = 'Retry details';
        retry.onclick = () => {
          if (dirtyDrafts.size) { setStatus('Save or cancel your edits before reopening details.', 'warn'); return; }
          onAuditCard(data.client || '', data.card_id || '', trelloUrl, data.selected_division || 'EMS');
        };
        host.append(label, retry);
      }
      if (snapshotCommentsMode) window.parent.postMessage({type:'snapshot-job-overview',cardId:data.card_id || '',error:message,pending:false},location.origin);
    },
  };
  if (!preparation) workspaceContext.applyRefresh = controller.applyRefresh;
  if (snapshotCardMode) window.parent.postMessage({type:'snapshot-job-overview',
    cardId:data.card_id || '', client:data.client || res.client || '',
    sections:data.info_sections || [], placement:data.app_placement || {},
    division:selectedDivision, pending:!!data.deferred_loading}, location.origin);
  const notificationToken = new URLSearchParams(location.search).get('notification_token');
  if (notificationToken && !data.deferred_loading && data.card_id === new URLSearchParams(location.search).get('card_id'))
    window.parent.postMessage({type:'oneloss-notification-opened',token:notificationToken}, '*');
  return controller;
}

function openEmsCopyLinkModal(client, sourceId, onLinked) {
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay";
  modal.innerHTML = `<div class="modal-box compact-dialog" role="dialog" aria-modal="true" aria-label="Link EMS card copy">
    <header class="modal-head"><div class="modal-title">Link EMS card copy</div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <form class="modal-body job-log-form">
      <p class="wide">Paste the other card's Trello link. This connects the same EMS job on main Work in Progress and main Estimating. Comments will be copied both ways in the background; checklists and Job Logs stay separate.</p>
      <label class="wide">Copied card link<input data-copy-link type="text" required autocomplete="off" placeholder="https://trello.com/c/…"></label>
      <p class="wide" data-message role="status"></p>
      <div class="job-log-form-actions"><button class="btn btn-primary" type="submit">Link copy</button><button class="btn" type="button" data-close>Cancel</button></div>
    </form></div>`;
  document.body.appendChild(modal);
  const priorFocus = document.activeElement;
  const close = () => { document.removeEventListener("keydown", onKey, true); modal.remove(); priorFocus?.focus(); };
  const onKey = event => { if (event.key === "Escape") { event.stopImmediatePropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  modal.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", close));
  const input = modal.querySelector("[data-copy-link]");
  input.focus();
  modal.querySelector("form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = modal.querySelector("[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    const message = modal.querySelector("[data-message]");
    message.textContent = "Checking the two EMS cards…";
    try {
      const result = await pywebview.api.link_ems_card_copy(client, sourceId, input.value.trim());
      if (!result?.ok) throw new Error(result?.error || "Could not link this copy.");
      close();
      await onLinked();
      setStatus("EMS copy linked. Comment sharing uses the background sync.", "ok");
    } catch (error) {
      message.textContent = error?.message || String(error);
      button.disabled = false;
    }
  });
}

function openXaNoteModal(client, cardId) {
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay xa-note-overlay";
  modal.innerHTML = `<div class="modal-box compact-dialog" role="dialog" aria-modal="true" aria-label="XA note">
    <header class="modal-head"><div><div class="modal-title">XA note</div><div class="modal-sub">${escapeHtml(client)} · posts to Trello, copies the note, and opens XA</div></div><button class="audit-close" data-close aria-label="Close XA note">×</button></header>
    <div class="modal-body job-log-form">
      <label class="wide">Note<textarea rows="6" data-xa-note-text placeholder="What needs to be recorded in XactAnalysis?"></textarea></label>
      <label>Notify on Trello (optional)<input data-xa-note-tag placeholder="username"></label>
      <div class="job-log-form-actions"><button class="btn btn-primary" data-submit-xa-note>Post, copy &amp; open XA</button><button class="btn" data-close>Cancel</button></div>
    </div></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  const note = modal.querySelector("[data-xa-note-text]");
  note.focus();
  modal.querySelector("[data-submit-xa-note]").addEventListener("click", async (event) => {
    const text = note.value.trim();
    if (!text) { note.focus(); return; }
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Posting…";
    const result = await pywebview.api.post_xa_note(
      client, text, modal.querySelector("[data-xa-note-tag]").value.trim(), cardId);
    if (!result?.ok) {
      button.disabled = false;
      button.textContent = "Post, copy & open XA";
      setStatus(result?.error || "XA note could not be posted", "error");
      return;
    }
    await pywebview.api.copy_to_clipboard(result.comment || text);
    close();
    setStatus(result.xa_opened
      ? "XA note posted to Trello, copied, and XA opened"
      : "XA note posted and copied · no XA link was found", result.xa_opened ? "ok" : "warn");
  });
}

async function openInitialNoteModal(client, cardId, division = "EMS") {
  const loaded = await pywebview.api.initial_note_templates(division);
  if (!loaded?.ok || !(loaded.templates || []).length) {
    setStatus(loaded?.error || `No ${division} Initial Note templates are configured`, "warn");
    return;
  }
  const templates = loaded.templates || [];
  const today = new Date().toLocaleDateString([], {month:"2-digit", day:"2-digit", year:"numeric"});
  const expand = (body) => String(body || "")
    .replaceAll("{customer}", client).replaceAll("{division}", division)
    .replaceAll("{date}", today);
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay initial-note-overlay";
  modal.innerHTML = `<div class="modal-box compact-dialog" role="dialog" aria-modal="true" aria-label="Create Initial Note">
    <header class="modal-head"><div><div class="modal-title">Initial Note</div><div class="modal-sub">${escapeHtml(client)} · saved in OneLoss first, then synced to ${escapeHtml(division)} Trello</div></div><button class="audit-close" data-close aria-label="Close Initial Note">×</button></header>
    <div class="modal-body job-log-form">
      <label class="wide">Template<select data-initial-template>${templates.map((template, index) => `<option value="${index}">${escapeHtml(template.name || "Initial note")}</option>`).join("")}</select></label>
      <label class="wide">Note<textarea rows="12" data-initial-note-text>${escapeHtml(expand(templates[0].body))}</textarea></label>
      <small class="wide">Review the note before saving. You can change every field.</small>
      <div class="job-log-form-actions"><button class="btn btn-primary" data-save-initial-note>Save Initial Note</button><button class="btn" data-close>Cancel</button></div>
    </div></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  const picker = modal.querySelector("[data-initial-template]");
  const note = modal.querySelector("[data-initial-note-text]");
  picker.addEventListener("change", () => {
    note.value = expand(templates[Number(picker.value) || 0]?.body);
    note.focus();
  });
  modal.querySelector("[data-save-initial-note]").addEventListener("click", async (event) => {
    const text = note.value.trim();
    if (!text) { note.focus(); return; }
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Saving…";
    const result = await pywebview.api.post_job_comment(client, cardId, text);
    if (!result?.ok) {
      button.disabled = false;
      button.textContent = "Save Initial Note";
      setStatus(result?.error || "Initial Note could not be saved", "error");
      return;
    }
    close();
    setStatus(result.pending_sync
      ? "Initial Note saved · Trello sync pending"
      : "Initial Note saved", "ok");
  });
  note.focus();
}

function openJobLogHistoryModal(history) {
  const rows = (history || []).map((revision, index) => {
    let after = {};
    try { after = JSON.parse(revision.after_json || "{}"); } catch (_) {}
    return `<article class="revision-row">
      <div><strong>${index === 0 ? "Current version" : `Revision ${history.length - index}`}</strong><time>${escapeHtml(formatCommentDate(revision.changed_at || ""))}</time></div>
      <small>${escapeHtml(revision.changed_by || "OneLoss")}</small>
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
    const placement = (state.board.placement_snapshot?.placements || []).find(r => r.card_id === drag.cardId);
    const result = await pywebview.api.move_card(drag.cardId, drag.fromListId, placement?.version || 0);
    if (!result?.ok) { setStatus(`Undo failed: ${result?.error || "?"}`, "error"); undo.remove(); return; }
    moveCardLocally(drag.cardId, toListId, drag.fromListId, drag.fromLane || "Previous lane");
    acceptPlacementResult(result);
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

function shelfEntryFromWorkspace(cardId, name, url, placement = {}) {
  for (const board of state.board.boards || []) {
    for (const lane of board.lanes || []) {
      const card = (lane.cards || []).find(item => item.card_id === cardId);
      if (card) return {
        cardId, name: card.client || card.name || name || '(no name)',
        url: card.url || url || '', fromListId: lane.list_id || '',
        lane: lane.name || '', boardKey: board.key || '', summary: '',
      };
    }
  }
  const saved = (state.board.placement_snapshot?.placements || []).find(item => item.card_id === cardId) || {};
  return {cardId, name: name || '(no name)', url: url || '',
    fromListId: saved.list_id || placement?.list_id || '', lane: placement?.lane || '',
    boardKey: placement?.board_key || '', summary: ''};
}

function holdJobInHandFromWorkspace({cardId, name, url, placement}) {
  const existing = state.jobShelf.find(item => item.cardId === cardId);
  if (existing?.mode === 'held') {
    setStatus(`${existing.name || 'Job'} is already in hand`, 'ok');
    return;
  }
  const entry = shelfEntryFromWorkspace(cardId, name, url, placement);
  if (!entry.cardId) return;
  entry.fromListId ||= existing?.fromListId || '';
  entry.lane ||= existing?.lane || '';
  entry.boardKey ||= existing?.boardKey || '';
  addToJobShelf(entry, 'held');
  if (!jobWorkspaceMode && !snapshotCardMode && !snapshotCommentsMode) renderBoard();
}
window.holdJobInHandFromWorkspace = holdJobInHandFromWorkspace;

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

function openQuickPhotoReportModal(client, jobPath, division, cardId = '') {
  if (window.PhotoReportBuilder) return window.PhotoReportBuilder.open(client, jobPath, division, cardId);
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

// Local file actions must surface bridge/OS failures instead of leaving
// controls permanently loading. Do not retry writes automatically.
async function localFileAction(action) {
  try { return await action(); }
  catch (error) { return {ok: false, error: error?.message || String(error)}; }
}

async function openXaStageModal(client, jobPath = "", cardId = '') {
  setStatus(`Loading photo stages for ${client}…`);
  const info = await localFileAction(() => pywebview.api.list_pics_stages(client, jobPath, cardId));
  if (!info?.ok || !(info.stages || []).length) {
    setStatus(info?.error || `No PICS folders with images found for ${client}`, "warn");
    return;
  }
  jobPath = info.job_path || jobPath;
  const w = document.createElement("div");
  w.className = "modal-scrim audit-overlay xa-picker-overlay";
  w.innerHTML = `<div class="modal-box xa-picker" role="dialog" aria-modal="true" aria-label="Stage photos for XA">
    <header class="modal-head"><div><div class="modal-title">Stage for XA</div><div class="modal-sub">${escapeHtml(client)} · choose a PICS folder</div></div><button class="audit-close" data-close aria-label="Close Stage for XA">×</button></header>
    <div class="modal-body xa-stage-list">${info.stages.map((stage) => `<button class="btn xa-stage-choice" data-stage="${escapeAttr(stage.name || "")}"><span>📁 ${escapeHtml(stage.name || "")}</span><small>${Number(stage.count || 0)} images</small></button>`).join("")}</div>
    <footer class="modal-foot"><button class="btn" data-close>Cancel</button></footer></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  w.querySelectorAll("[data-stage]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    const original = button.innerHTML;
    button.textContent = "Staging photos…";
    const result = await localFileAction(() => pywebview.api.copy_pics_to_clipboard(client, button.dataset.stage || "", jobPath, cardId));
    if (!result?.ok) {
      button.disabled = false;
      button.innerHTML = original;
      setStatus(result?.error || "Could not stage the photos", "error");
      return;
    }
    close();
    setStatus(`Staged ${result.count || 0} files for XA · temporary folder opened${result.failed_count ? ` · ${result.failed_count} files failed` : ""}`, result.failed_count ? "warn" : "ok");
  }));
  setStatus("");
}

function renderJobComment(comment) {
  const actor = comment?.actor || "OneLoss";
  const initial = window.CommentMarkdown?.initials(actor) || actor.trim().charAt(0).toUpperCase() || "L";
  const avatarColor = window.CommentMarkdown?.avatarColor(actor) || '#315A40';
  const source = comment?.source === "trello" ? "trello" : comment?.source === 'thread' ? 'thread' : "linguar";
  const thread = comment?.thread;
  const key = thread?.id || comment?.external_id || comment?.id || '';
  const pinned=!!(thread?.pinned || comment?.pin_state?.pinned), mine=!!comment?.pin_state?.mine;
  return `<article class="job-comment" data-pin-mine="${mine}" data-pin-legacy="${!!thread?.pinned}" data-audit-at="${escapeAttr(comment?.at || '')}" data-audit-author="${escapeAttr(actor)}" data-thread-key="${escapeAttr(key)}" data-thread-root="${escapeAttr(thread?.root_id || key)}" data-comment-pinned="${pinned}" data-comment-id="${escapeAttr(comment?.id || "")}" data-comment-card-id="${escapeAttr(comment?.card_id || "")}" data-comment-source="${source}" data-comment-external-id="${escapeAttr(comment?.external_id || "")}"><div class="comment-avatar" style="background:${avatarColor};color:#fff" title="${escapeAttr(actor)}">${escapeHtml(initial)}</div>
    <div><header><strong>${escapeHtml(actor)}</strong>${pinned ? '<span title="Pinned comment" aria-label="Pinned comment">📌</span>' : ''}<time>${escapeHtml(formatCommentDate(comment?.at || ""))}</time></header>
    ${thread?.parent_id ? '<button class="text-btn comment-reply-reference" data-open-thread>↳ Reply · View thread</button>' : ''}
    <div class="comment-markdown" data-comment-raw="${escapeAttr(comment?.text || '')}">${window.CommentMarkdown ? window.CommentMarkdown.display(comment?.text) : `<p>${escapeHtml(comment?.text || '')}</p>`}</div><footer><small>${escapeHtml(comment?.division ? comment.division + ' · ' : '')}${source === "trello" ? "Trello" : "OneLoss"}${thread?.native && thread.delivery !== 'sent' ? ' · Trello delivery unconfirmed' : ''}</small>
    ${key && comment?.reply_count > 0 && !thread?.parent_id ? `<button class="text-btn" data-open-thread>${comment.reply_count} ${comment.reply_count === 1 ? 'reply' : 'replies'}</button>` : ''}
    ${key || (comment?.id && comment?.can_manage) ? `<details class="comment-actions-menu"><summary aria-label="Comment actions" title="Comment actions">…</summary><div>
      ${key ? `<button class="text-btn" data-reply-comment>Reply</button><button class="text-btn" data-pin-comment aria-pressed="${mine || !!thread?.pinned}">${mine || thread?.pinned ? 'Unpin' : 'Pin'}</button>` : ''}
      ${comment?.id && comment?.can_manage ? `<button class="text-btn" data-comment-edit>Edit</button>${source === 'thread' ? '' : '<button class="text-btn danger" data-comment-delete>Delete</button>'}` : ''}
    </div></details>` : ''}</footer>${window.CommentReactions?.markup(comment) || ''}</div></article>`;
}

function formatCommentDate(value) {
  if (!value) return "now";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : `${formatAppDate(d)} at ${d.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"})}`;
}

function confirmJobFolderLink(warning) {
  return new Promise((resolve) => {
    if (!window.openModal) {
      resolve(false);
      return;
    }
    const modalId = "job-folder-link-confirm";
    let settled = false;
    const finish = (accepted) => {
      if (settled) return;
      settled = true;
      resolve(accepted);
    };
    const overlay = window.openModal({
      id: modalId,
      width: 520,
      title: "Link this job folder?",
      sub: "The folder name differs from the job name",
      body: `<p class="folder-link-confirm-copy">${escapeHtml(warning || "Please confirm this is the correct job folder.")}</p>
        <p class="folder-link-confirm-note">Property-management, commercial, unit, and claim folders may legitimately use a different name.</p>
        <div class="modal-footer"><button class="btn modal-close" type="button">Cancel</button><button class="btn btn-primary" id="job-folder-link-confirm-yes" type="button">Link folder</button></div>`,
      onClose: () => finish(false),
    });
    overlay.querySelector("#job-folder-link-confirm-yes")?.addEventListener("click", () => {
      finish(true);
      window.closeModal(modalId);
    });
  });
}

async function openJobFolderLinkModal(data, closeWorkspace = () => {}, onLinked = null) {
  const client = data.client || data.audit?.client || "";
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay";
  modal.innerHTML = `<div class="modal-box folder-link-modal" role="dialog" aria-modal="true" aria-label="Link OD job folder">
    <header class="modal-head"><div><div class="modal-title">Link OD job folder</div><div class="modal-sub">${escapeHtml(client)} · this folder becomes the job's saved file location</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body"><div class="folder-link-tools"><input type="search" data-folder-filter placeholder="Filter folder names…" aria-label="Filter folder names"><button class="btn" data-all-years>Search all years</button><button class="btn btn-primary" data-choose-exact-folder>Choose exact folder…</button></div>
      <div class="folder-link-message" data-folder-message>Finding the best matching folders…</div><div class="folder-link-list" data-folder-list></div></div>
    <footer class="modal-foot"><small>Pick the actual job folder—not EMS, DOCS, or PICS inside it.</small><button class="btn" data-close>Cancel</button></footer></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", close));
  const list = modal.querySelector("[data-folder-list]");
  const message = modal.querySelector("[data-folder-message]");
  const filter = modal.querySelector("[data-folder-filter]");
  let candidates = [];
  let localSuggestion = null;
  const linkPath = async (path, button = null) => {
    if (button) button.disabled = true;
    let result = await localFileAction(() => pywebview.api.link_job_folder(client, path || "", false, data.card_id || ""));
    if (result?.needs_confirm) {
      const accepted = await confirmJobFolderLink(result.warning);
      if (!accepted) {
        if (button) button.disabled = false;
        message.textContent = "Folder link cancelled";
        message.className = "folder-link-message";
        return;
      }
      result = await localFileAction(() => pywebview.api.link_job_folder(client, path || "", true, data.card_id || ""));
    }
    if (!result?.ok) {
      if (button) button.disabled = false;
      message.textContent = result?.error || result?.warning || "Folder could not be linked";
      message.className = "folder-link-message error";
      return;
    }
    close();
    if (typeof closeWorkspace === "function") closeWorkspace(true);
    setStatus(`Linked exact OD folder to ${client}`, "ok");
    if (typeof onLinked === "function") await onLinked(result);
    else await onAuditCard(client, data.card_id || "", "", data.selected_division || "EMS");
  };
  const render = () => {
    const query = (filter.value || "").trim().toLowerCase();
    const shown = [localSuggestion, ...candidates].filter(Boolean)
      .filter((item) => !query || `${item.name} ${item.parent || ""} ${item.year || ""}`.toLowerCase().includes(query))
      .filter((item, index, all) => all.findIndex(candidate => candidate.path === item.path) === index)
      .slice(0, 60);
    list.innerHTML = shown.map((item) => `<button class="folder-link-row" data-folder-path="${escapeAttr(item.path || "")}"><span><strong>${escapeHtml(item.name || "Job folder")}</strong><small>${escapeHtml([item.parent, item.year_folder || item.year].filter(Boolean).join(" · "))}</small></span><b>Link folder</b></button>`).join("") || `<div class="aud-empty">No matching folders. Search all years or change the filter.</div>`;
    list.querySelectorAll("[data-folder-path]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true; button.querySelector("b").textContent = "Linking…";
      await linkPath(button.dataset.folderPath || "", button);
      if (button.isConnected) button.querySelector("b").textContent = "Link folder";
    }));
  };
  const load = async (scope = "") => {
    message.textContent = scope === "all" ? "Searching every job year…" : "Finding current-year job folders…";
    message.className = "folder-link-message";
    const result = await localFileAction(() => pywebview.api.list_job_folder_candidates(client, scope));
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
  modal.querySelector("[data-choose-exact-folder]").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    message.textContent = "Opening the Windows folder picker…";
    const startPath = candidates[0]?.path || "";
    const picked = await localFileAction(() => pywebview.api.choose_exact_job_folder(startPath));
    button.disabled = false;
    if (!picked?.ok) {
      message.textContent = picked?.error || "The folder picker could not open";
      message.className = "folder-link-message error";
      return;
    }
    if (picked.cancelled || !picked.path) {
      message.textContent = "No folder selected";
      message.className = "folder-link-message";
      return;
    }
    message.textContent = `Selected ${picked.name || picked.path}`;
    await linkPath(picked.path, button);
  });
  filter.focus();
  if (data.card_id) {
    void localFileAction(() => pywebview.api.suggest_job_folder(client, data.card_id)).then(result => {
      if (!modal.isConnected || !result?.ok || !result.suggestion) return;
      localSuggestion = {...result.suggestion, parent: result.suggestion.source};
      render();
    });
  }
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
let globalSearchSequence = 0;
function onSearchInput(ev) {
  state.search = ev.target.value;
  state.stage_render_limit = 350;
  PanelState.set({ search: state.search });
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (state.view === "board") renderBoard();
    else renderTable();
    if (state.view === "board") void runGlobalCardSearch(state.search);
  }, 120);
}

function notifyJobWorkspaceClosed() {
  if (jobWorkspaceMode) {
    window.parent.postMessage({ type: "linguar-close-job-workspace" }, "*");
  }
}

const companyCamPullWatchers = new Map();

// A completed batch changes folder evidence, not the user's open drafts.
// Serialize repeat batches so a slower audit cannot replace a newer result.
window.addEventListener('pipeline:files-imported', event => {
  const workspace = state.openWorkspace;
  if (!workspace || workspace.client.trim().toLowerCase() !==
      String(event.detail?.client || '').trim().toLowerCase()) return;
  workspace.importRefreshPending = true;
  if (workspace.importRefreshRunning) return;
  workspace.importRefreshRunning = true;
  void (async () => {
    try {
      while (workspace.importRefreshPending && state.openWorkspace === workspace) {
        workspace.importRefreshPending = false;
        setStatus('Files imported · checking paperwork and requirements…', '');
        const fresh = await pywebview.api.refresh_job_card_workspace(
          workspace.client, workspace.cardId, workspace.division);
        if (state.openWorkspace !== workspace || !workspace.element.isConnected) return;
        if (!fresh?.ok) throw Error(fresh?.error || 'Folder check unavailable');
        workspace.applyRefresh?.(fresh);
        setStatus('Files imported · paperwork and requirements refreshed', 'ok');
      }
    } catch (error) {
      if (state.openWorkspace === workspace)
        setStatus(`Files imported, but requirements could not refresh. Use Run audit. ${error.message || error}`, 'warn');
    } finally { workspace.importRefreshRunning = false; }
  })();
});

async function openJobFileImportModal(data, audit) {
  if (window.JobImportWorkspace) return window.JobImportWorkspace.open(data, audit, {
    pullCompanyCam: () => openCompanyCamPullModal(data, audit)
  });
  const client = data.client || audit.client || "";
  const cardId = data.card_id || "";
  const modal = document.createElement("div");
  modal.className = "modal-scrim";
  modal.innerHTML = `<div class="modal-box job-file-import-card" role="dialog" aria-modal="true" aria-label="Import files into job">
    <header class="modal-head"><div><div class="modal-title">Import files</div><div class="modal-sub">${escapeHtml(client)} · files go into this job's OD folder</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body job-file-import-body">
      <div class="job-file-import-toolbar">
        <label><span>Job side</span><select data-import-side><option value="ems">EMS</option><option value="contents">Contents</option></select></label>
        <label><span>Destination</span><select data-import-destination><option value="">Auto-sort</option><option value="Initial">PICS / Initial</option><option value="Reinspection">PICS / Reinspection</option><option value="Abatement">PICS / Abatement</option><option value="Cleaning">PICS / Cleaning</option><option value="CONTENTS_PICS">Contents / PICS (creates folder)</option><option value="Monitor">PICS / Moisture Checks (Monitor)</option><option value="Walkthroughs">PICS / Walkthroughs</option><option value="Demo">PICS / Demo</option><option value="Mold Prep">PICS / Mold Prep</option><option value="Final">PICS / Final</option><option value="DOCS">DOCS</option></select></label>
        <label><span>Tech, if photos</span><input data-import-tech placeholder="Name"></label>
      </div>
      <div class="job-file-import-actions"><button class="btn btn-primary" data-import-scan>Scan Downloads</button><button class="btn" data-import-pick>Choose files…</button><button class="btn" data-import-trello ${cardId ? "" : "disabled"} title="${cardId ? "Browse and pull attachments from this division's Trello card" : "Link a Trello card first"}">Pull from Trello attachments</button><button class="btn" data-import-workcenter>Open WorkCenter</button><button class="btn" data-import-docusign>Open DocuSign</button></div>
      <div class="job-file-import-path" data-import-path>Choose Scan Downloads or select files yourself.</div>
      <div class="job-file-import-candidates" data-import-candidates></div>
      <div class="job-file-import-result" data-import-result aria-live="polite"></div>
    </div>
  </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelector("[data-close]")?.addEventListener("click", close);
  const side = () => destination() === 'CONTENTS_PICS' ? 'contents' : modal.querySelector("[data-import-side]")?.value || "ems";
  const destination = () => modal.querySelector("[data-import-destination]")?.value || "";
  modal.querySelector('[data-import-destination]').addEventListener('change', () => {
    if (destination() === 'CONTENTS_PICS') modal.querySelector('[data-import-side]').value = 'contents';
  });
  const tech = () => modal.querySelector("[data-import-tech]")?.value.trim() || "";
  const resultEl = modal.querySelector("[data-import-result]");
  const showResult = (result, fallback = "Import failed") => {
    if (!result?.ok) {
      resultEl.textContent = result?.cancelled ? "No files selected." : (result?.error || fallback);
      resultEl.className = "job-file-import-result error";
      return false;
    }
    const parts = [];
    if (result.pics_count) parts.push(`${result.pics_count} photo${result.pics_count === 1 ? "" : "s"} filed`);
    if (result.docs_count) parts.push(`${result.docs_count} document${result.docs_count === 1 ? "" : "s"} filed`);
    if (result.sketches_count) parts.push(`${result.sketches_count} sketch${result.sketches_count === 1 ? "" : "es"} filed`);
    resultEl.textContent = parts.join(" · ") || "Files imported.";
    resultEl.className = "job-file-import-result ok";
    return true;
  };
  const scan = async () => {
    const button = modal.querySelector("[data-import-scan]");
    const list = modal.querySelector("[data-import-candidates]");
    button.disabled = true;
    button.textContent = "Scanning…";
    list.innerHTML = loadingIndicator('Checking Downloads…');
    let response;
    try { response = await pywebview.api.scan_downloads(client); }
    catch (error) { response = {candidates: [], error: String(error)}; }
    button.disabled = false;
    button.textContent = "Scan Downloads";
    modal.querySelector("[data-import-path]").textContent = response?.downloads ? `Downloads · ${response.downloads}` : "Downloads could not be scanned.";
    const candidates = response?.candidates || [];
    if (!candidates.length) {
      list.innerHTML = `<div class="aud-empty">No importable downloads found. Download the file, then scan again—or choose it directly.</div>`;
      if (response?.error) showResult(response);
      return;
    }
    list.innerHTML = candidates.map((candidate, index) => `<article class="job-file-import-candidate" data-import-candidate="${index}"><span>${escapeHtml(candidate.icon || "📄")}</span><div><strong>${escapeHtml(candidate.kind_label || "File")}</strong><small>${escapeHtml(candidate.label || "")}</small></div><button class="btn" data-import-candidate-button="${index}">Import</button></article>`).join("");
    list.querySelectorAll("[data-import-candidate-button]").forEach((candidateButton) => candidateButton.addEventListener("click", async () => {
      const candidate = candidates[Number(candidateButton.dataset.importCandidateButton)] || {};
      candidateButton.disabled = true;
      candidateButton.textContent = "Importing…";
      let imported;
      try { imported = await pywebview.api.do_import(client, candidate.kind || "", candidate.paths || [], destination(), tech(), side()); }
      catch (error) { imported = {ok:false, error:String(error)}; }
      if (showResult(imported)) {
        candidateButton.textContent = "Imported";
        candidateButton.closest("[data-import-candidate]")?.classList.add("done");
      } else {
        candidateButton.disabled = false;
        candidateButton.textContent = "Try again";
      }
    }));
  };
  modal.querySelector("[data-import-scan]")?.addEventListener("click", scan);
  modal.querySelector("[data-import-trello]")?.addEventListener("click", async () => {
    try {
      if (!cardId) return;
      if (!window.openTrelloAttachmentsModal) throw new Error("Trello attachment picker did not load. Reopen Jobs and try again.");
      await window.openTrelloAttachmentsModal({cardId, client});
    } catch (error) {
      showResult({ok: false, error: String(error)});
    }
  });
  modal.querySelector("[data-import-pick]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Choosing…";
    let result;
    try { result = await pywebview.api.pick_and_import_file(client, destination(), side(), tech()); }
    catch (error) { result = {ok:false, error:String(error)}; }
    showResult(result);
    button.disabled = false;
    button.textContent = "Choose files…";
  });
  modal.querySelector("[data-import-workcenter]")?.addEventListener("click", async () => {
    const result = await pywebview.api.open_workcenter();
    if (!result?.ok) showResult(result, "WorkCenter could not be opened.");
  });
  modal.querySelector("[data-import-docusign]")?.addEventListener("click", () =>
    pywebview.api.open_url("https://app.docusign.com/"));
}

async function openCompanyCamPullModal(data, audit, reviewedPlan = null, skipReceipt = false) {
  const client = data.client || audit.client || "";
  const cardId = data.card_id || "";
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay cc-pull-overlay";
  modal.innerHTML = `<div class="modal-box cc-pull-card" role="dialog" aria-modal="true" aria-label="Pull CompanyCam photos">
    <header class="modal-head"><div><div class="modal-title">Pull CompanyCam photos</div><div class="modal-sub">${escapeHtml(client)}</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body cc-pull-body">${loadingIndicator('Checking CompanyCam and the job folder…')}</div>
  </div>`;
  document.body.appendChild(modal);
  if(cardId){const header=modal.querySelector('header');header.dataset.popoutTool='pipeline';header.dataset.popoutContext=JSON.stringify({cardId,client,division:data.selected_division||'EMS',jobAction:'companycam'});header.title='Open a fresh photo window; current selections stay here.';}
  const requestId = `cc-plan-${crypto.randomUUID()}`;
  const progress = (event) => {
    const detail = event.detail || {};
    if (detail.request_id !== requestId || !modal.isConnected) return;
    const body = modal.querySelector(".cc-pull-body");
    if (detail.phase === "photos") {
      body.innerHTML = `<div class="cc-pull-summary"><strong>${Number(detail.total || 0)} CompanyCam photos found</strong><span data-plan-status role="status">Checking which are already filed. Choose visits next; tags are checked only for your selection.</span></div>
        <div class="cc-pull-groups">${(detail.shoots || []).map((shoot) => `<article class="cc-pull-group"><div class="cc-pull-shoot"><strong>${escapeHtml(shoot.date || "Unknown date")}</strong><small>${Number(shoot.count || 0)} photos · ${escapeHtml(shoot.tech || "Unknown technician")}</small></div></article>`).join("")}</div>`;
    } else if (detail.phase === "tags") {
      const status = body.querySelector("[data-plan-status]");
      if (status) status.textContent = `Checking stage and room tags: ${Number(detail.done || 0)} of ${Number(detail.total || 0)} photos. Import choices appear when checked.`;
    }
  };
  window.addEventListener("companycam:plan-progress", progress);
  const close = () => {
    window.removeEventListener("companycam:plan-progress", progress);
    modal.remove();
  };
  modal.querySelector("[data-close]").addEventListener("click", close);

  if (!reviewedPlan && !skipReceipt && pywebview.api.companycam_import_status) {
    let receipt;
    try { receipt = await pywebview.api.companycam_import_status(client, cardId); }
    catch (_) { receipt = {ok:false}; }
    if (!modal.isConnected) return;
    // A successful past import is history, not a gate to selecting more photos.
    if (!receipt?.ok || (receipt.found && receipt.state !== "complete")) {
      const running = receipt?.state === "running";
      const result = receipt?.result || {};
      const message = !receipt?.ok ? "Previous import status could not be checked. Check again before starting another pull."
        : running ? "An import is running. You can close this window; do not start another pull."
        : receipt.state === "interrupted" ? "The app restarted before a final result was saved. Some photos may already be filed. Review the folder before choosing another pull."
        : `Last import ${receipt.state === "complete" ? "complete" : "failed"} · ${result.pulled || 0} pulled · ${result.skipped || 0} skipped${result.error ? ` · ${result.error}` : ""}`;
      modal.querySelector(".cc-pull-body").innerHTML = `<div class="cc-pull-summary"><strong role="status">${escapeHtml(message)}</strong>${result.pics ? `<span>Photo folder: ${escapeHtml(result.pics)}</span>` : ''}</div><div class="cc-pull-recovery"><button class="btn" data-check-import>Check status</button>${receipt?.ok && !running ? '<button class="btn btn-primary" data-next-preview>Choose visits for another pull</button>' : ''}</div>`;
      modal.querySelector("[data-check-import]").addEventListener("click", () => {close(); openCompanyCamPullModal(data, audit);});
      modal.querySelector("[data-next-preview]")?.addEventListener("click", () => {close(); openCompanyCamPullModal(data, audit, null, true);});
      if (running) watchCompanyCamPull(client, cardId, receipt.operation_id);
      return;
    }
  }

  let plan;
  try {
    plan = reviewedPlan || await pywebview.api.companycam_plan_pull(client, "", cardId, "", requestId, null, '', true);
  } catch (error) {
    plan = {ok:false, error:String(error)};
  } finally {
    window.removeEventListener("companycam:plan-progress", progress);
  }
  if (!modal.isConnected) return;
  const body = modal.querySelector(".cc-pull-body");
  if (!plan?.ok) {
    body.innerHTML = `<div class="job-card-load-error"><strong>CompanyCam import is unavailable</strong><p>${escapeHtml(plan?.error || "The project could not be matched.")}</p><div class="cc-pull-recovery">${plan?.recovery === "folder" ? '<button class="btn btn-primary" data-choose-job-folder>Choose exact folder…</button>' : '<button class="btn btn-primary" data-retry-cc-preview>Retry preview</button>'}<button class="btn" data-open-cc-project>Open CompanyCam</button></div></div>`;
    body.querySelector("[data-retry-cc-preview]")?.addEventListener("click", () => {close(); openCompanyCamPullModal(data, audit);});
    body.querySelector("[data-open-cc-project]")?.addEventListener("click", () => pywebview.api.open_companycam_link(client, cardId));
    body.querySelector("[data-choose-job-folder]")?.addEventListener("click", () => {
      close();
      openJobFolderLinkModal(data, () => {}, () => openCompanyCamPullModal(data, audit));
    });
    return;
  }
  if (!plan.missing) {
    body.innerHTML = `<div class="cc-pull-ready"><strong>${reviewedPlan ? 'The selected photos are already filed.' : `All ${Number(plan.total || 0)} photos are already filed.`}</strong><span>Nothing new needs to be imported from this selection.</span></div>`;
    return;
  }

  if (plan.tags_pending) {
    body.innerHTML = `<div class="cc-pull-summary"><strong>${Number(plan.missing || 0)} photos available</strong><span>Select visits first. Stage and room tags have not been checked.</span></div>
      <div class="cc-photo-selection"><button class="btn" data-select-all disabled>Select all</button><button class="btn" data-clear-all disabled>Clear selection</button><span data-selection-count role="status"></span></div>
      <label class="cc-photo-selection">Organization<select data-import-mode><option value="quick">Quick import — destination / crew + date</option><option value="tags">CompanyCam tags — stage and room folders</option></select></label>
      <div class="cc-photo-selection"><span data-tag-progress role="status">Tags will check while you browse.</span><button class="btn" data-retry-tags hidden>Retry unfinished checks</button></div>
      <div class="cc-photo-scroll"><div class="cc-photo-days"></div><button class="btn" data-load-older>Load older photos</button></div>
      <footer class="cc-pull-actions"><span data-review-status role="status"></span><button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-review-visits disabled>Choose visits</button></footer>`;
    body.querySelector('.cc-pull-summary span').textContent = 'Newest first · scroll for older photos. Select photos to review their destination. Nothing is imported yet.';
    body.querySelector('.cc-photo-scroll').insertAdjacentHTML('beforebegin','<div class="cc-photo-selection"><label>From <input type="date" data-photo-from></label><label>Through <input type="date" data-photo-through></label><button class="btn" data-reset-dates>Clear dates</button><span data-range-status role="status"></span></div>');
    const selectedPhotos = new Set();
    const chosen = () => [...selectedPhotos];
    const button = body.querySelector('[data-review-visits]');
    const status = body.querySelector('[data-review-status]');
    let catalog = [], catalogReady = false;
    const mode = body.querySelector('[data-import-mode]');
    const quickImport = () => mode.value === 'quick';
    const tagReady = new Set(), loadedPhotos = new Set();
    let tagBusy = false, tagPaused = false, tagError = '';
    const tagProgress = body.querySelector('[data-tag-progress]'), retryTags = body.querySelector('[data-retry-tags]');
    async function checkNextTags() {
      if (quickImport() || tagBusy || tagPaused || reviewing || !modal.isConnected) return;
      const ids = [...new Set([...selectedPhotos, ...loadedPhotos])].filter(id => !tagReady.has(id)).slice(0, 8);
      if (!ids.length) return;
      tagBusy = true; updateTagProgress();
      try {
        const result = await pywebview.api.companycam_preview_tags(client, cardId, plan.project_id, plan.preview_id, ids);
        if (!modal.isConnected) return;
        (result?.ready || []).forEach(id => tagReady.add(id));
        if (!result?.ok || ids.some(id => !tagReady.has(id))) throw Error(result?.error || 'Some tags could not be checked.');
      } catch (error) { tagPaused = true; tagError = error.message || 'Connection interrupted.'; }
      finally {
        tagBusy = false;
        if (modal.isConnected) { updateSelection(); if (!tagPaused) setTimeout(checkNextTags, 0); }
      }
    }
    function updateTagProgress() {
      if (quickImport()) {
        tagProgress.textContent = 'No tag scan or tag changes. Choose a destination for each shoot on the next screen.';
        retryTags.hidden = true;
        return;
      }
      const readySelected = [...selectedPhotos].filter(id => tagReady.has(id)).length;
      tagProgress.textContent = tagPaused ? `${tagError} ${tagReady.size} checked; your selection is kept.`
        : `${tagReady.size} photos checked${selectedPhotos.size ? ` · ${readySelected}/${selectedPhotos.size} selected ready` : ''}${tagBusy ? ' · checking tags…' : ''}`;
      retryTags.hidden = !tagPaused; retryTags.disabled = reviewing || tagBusy;
    }
    retryTags.onclick = () => { tagPaused = false; tagError = ''; updateTagProgress(); checkNextTags(); };
    mode.onchange = () => { updateSelection(); checkNextTags(); };
    const days = new Map(), dayIds = new Map(), bulkButtons = [], personChecks = [];
    const dayOf = photo => photo.date ? new Date(photo.date * 1000).toLocaleDateString() : 'Unknown date';
    const updateSelection = () => {
      const count = chosen().length;
      button.disabled = reviewing || !count || (!quickImport() && chosen().some(id => !tagReady.has(id)));
      mode.disabled = reviewing;
      button.textContent = count ? `Review ${count} photos` : 'Select photos';
      body.querySelector('[data-selection-count]').textContent = `${count} of ${Number(plan.missing || 0)} selected`;
      body.querySelector('[data-select-all]').disabled = reviewing || !catalogReady;
      body.querySelector('[data-clear-all]').disabled = reviewing || !count;
      body.querySelectorAll('[data-cc-visit]').forEach(box => {
        box.checked = selectedPhotos.has(box.dataset.ccVisit); box.disabled = reviewing;
      });
      bulkButtons.forEach(({control, ids}) => {
        const selected = ids.filter(id => selectedPhotos.has(id)).length;
        control.textContent = selected === ids.length ? `Deselect day (${ids.length})` : `Select whole day (${ids.length})`;
        control.disabled = reviewing;
        control.setAttribute('aria-pressed', String(selected === ids.length));
      });
      personChecks.forEach(({control, ids}) => {
        const count = ids.filter(id => selectedPhotos.has(id)).length;
        control.checked = ids.length > 0 && count === ids.length;
        control.indeterminate = count > 0 && count < ids.length;
        control.disabled = reviewing;
      });
      days.forEach(({readyLabel, reviewDay}, day) => {
        const ids = dayIds.get(day) || [], checked = ids.filter(id => tagReady.has(id)).length;
        readyLabel.textContent = quickImport() ? `${ids.length} photos` : `${checked}/${ids.length} tags checked`;
        const selected = ids.filter(id => selectedPhotos.has(id));
        reviewDay.disabled = reviewing || !selected.length || (!quickImport() && selected.some(id => !tagReady.has(id)));
      });
      updateTagProgress();
      if (!tagBusy && !tagPaused) setTimeout(checkNextTags, 0);
    };
    let offset = 0, loading = false, finished = false, reviewing = false;
    body.querySelector('[data-select-all]').onclick = () => { catalog.forEach(photo => selectedPhotos.add(photo.id)); updateSelection(); };
    body.querySelector('[data-clear-all]').onclick = () => { selectedPhotos.clear(); updateSelection(); };
    const scroll = body.querySelector('.cc-photo-scroll'), more = body.querySelector('[data-load-older]');
    const fromDate=body.querySelector('[data-photo-from]'),throughDate=body.querySelector('[data-photo-through]');
    let rangeStart=null,rangeEnd=null;
    function filterDates(){
      if(loading||reviewing)return;
      if(fromDate.value&&throughDate.value&&fromDate.value>throughDate.value){body.querySelector('[data-range-status]').textContent='From must be on or before Through.';return;}
      rangeStart=fromDate.value?new Date(fromDate.value+'T00:00:00').getTime()/1000:null;
      const end=throughDate.value?new Date(throughDate.value+'T00:00:00'):null;
      if(end)end.setDate(end.getDate()+1);
      rangeEnd=end?end.getTime()/1000:null;
      offset=0;finished=false;catalogReady=false;catalog=[];days.clear();dayIds.clear();bulkButtons.length=0;personChecks.length=0;loadedPhotos.clear();
      body.querySelector('.cc-photo-days').replaceChildren();scroll.scrollTop=0;more.hidden=false;
      void loadPhotos();
    }
    fromDate.onchange=filterDates;throughDate.onchange=filterDates;
    body.querySelector('[data-reset-dates]').onclick=()=>{fromDate.value='';throughDate.value='';filterDates();};
    async function loadPhotos() {
      if (loading || finished || reviewing || !modal.isConnected) return;
      loading = true; more.disabled = true; more.textContent = 'Loading photos…';
      [fromDate,throughDate,body.querySelector('[data-reset-dates]')].forEach(el=>el.disabled=true);
      try {
        const page = await pywebview.api.companycam_preview_page(client, cardId, plan.project_id, plan.preview_id, offset, rangeStart, rangeEnd);
        if (!modal.isConnected) return;
        if (!page?.ok) throw Error(page?.error || 'Photos could not load.');
        body.querySelector('[data-range-status]').textContent=`${page.total} matching photos · selections are kept when filtering`;
        if (page.catalog) {
          catalog = page.catalog; catalogReady = true;
          for (const photo of catalog) {
            const day = dayOf(photo);
            if (!dayIds.has(day)) dayIds.set(day, []);
            dayIds.get(day).push(photo.id);
          }
        }
        for (const photo of page.photos) {
          const day = dayOf(photo), person = photo.creator || 'Unknown photographer';
          if (!days.has(day)) {
            const section = document.createElement('section'); section.className = 'cc-photo-day';
            const heading = document.createElement('header');
            const title = document.createElement('h3'); title.textContent = day;
            const control = document.createElement('button'); control.className = 'btn'; control.type = 'button';
            const ids = dayIds.get(day) || [];
            control.onclick = () => {
              const remove = ids.every(id => selectedPhotos.has(id));
              ids.forEach(id => remove ? selectedPhotos.delete(id) : selectedPhotos.add(id));
              updateSelection();
            };
            bulkButtons.push({control, ids});
            const readyLabel = document.createElement('small');
            const reviewDay = document.createElement('button'); reviewDay.className = 'btn'; reviewDay.textContent = 'Review selected day';
            reviewDay.onclick = () => reviewPhotos(ids.filter(id => selectedPhotos.has(id)));
            heading.append(title, readyLabel, control, reviewDay); section.append(heading);
            body.querySelector('.cc-photo-days').append(section);
            days.set(day, {section, people:new Map(), readyLabel, reviewDay});
          }
          const group = days.get(day);
          if (!group.people.has(person)) {
            const section = document.createElement('section'); section.className = 'cc-photo-person';
            const heading = document.createElement('h4');
            const label = document.createElement('label'); label.className = 'cc-photo-person-select';
            const name = document.createElement('span'); name.textContent = person;
            const control = document.createElement('input'); control.type = 'checkbox';
            control.setAttribute('aria-label', `Select all photos by ${person} on ${day}`);
            const ids = catalog.filter(p => dayOf(p) === day && (p.creator || 'Unknown photographer') === person).map(p => p.id);
            control.onchange = () => {
              ids.forEach(id => control.checked ? selectedPhotos.add(id) : selectedPhotos.delete(id));
              updateSelection();
            };
            personChecks.push({control, ids});
            label.append(name, control); heading.append(label);
            const grid = document.createElement('div'); grid.className = 'cc-photo-grid';
            section.append(heading, grid); group.section.append(section); group.people.set(person, grid);
          }
          const tile = document.createElement('div'); tile.className = 'cc-photo-tile';
          const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.ccVisit = photo.id;
          checkbox.disabled = reviewing;
          const date = photo.date ? new Date(photo.date * 1000).toLocaleString() : 'Unknown date';
          checkbox.setAttribute('aria-label', `Select photo ${photo.id}, ${date}`);
          checkbox.onchange = () => { checkbox.checked ? selectedPhotos.add(photo.id) : selectedPhotos.delete(photo.id); updateSelection(); };
          const caption = document.createElement('span'); caption.textContent = photo.date ? new Date(photo.date * 1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : 'Unknown time';
          const preview = document.createElement('button'); preview.type = 'button'; preview.className = 'cc-photo-preview'; preview.textContent = 'Preview unavailable';
          preview.setAttribute('aria-label', `Preview photo ${photo.id}`);
          preview.onclick = () => window.openImportImagePreview({title:`${person} · ${date}`, source:photo.image || photo.thumbnail});
          if (/^https:\/\//i.test(photo.thumbnail || '')) {
            const image = document.createElement('img'); image.loading = 'lazy'; image.alt = `Job photo ${photo.id}`; image.src = photo.thumbnail;
            image.onerror = () => image.remove();
            preview.append(image);
          }
          tile.append(checkbox, preview, caption); group.people.get(person).append(tile);
          loadedPhotos.add(photo.id);
        }
        updateSelection();
        offset = page.next; finished = offset >= page.total;
        more.hidden = finished;
        more.textContent = 'Load older photos';
      } catch (error) { more.textContent = 'Retry loading photos'; status.textContent = error.message; }
      finally { loading = false; more.disabled = false;[fromDate,throughDate,body.querySelector('[data-reset-dates]')].forEach(el=>el.disabled=reviewing); }
    }
    more.onclick = loadPhotos;
    scroll.addEventListener('scroll', () => {
      if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 250) loadPhotos();
    });
    updateSelection();
    loadPhotos();
    body.querySelector('[data-cancel]').addEventListener('click', close);
    async function reviewPhotos(ids) {
      if (reviewing || !ids.length || (!quickImport() && ids.some(id => !tagReady.has(id)))) return;
      const quick = quickImport();
      reviewing = true;
      updateSelection();
      button.disabled = true;
      body.querySelectorAll('[data-cc-visit]').forEach(box => {box.disabled = true;});
      status.textContent = quick ? `Checking the destination for ${ids.length} photos — no tag scan…` : `Checking the saved folder, then tags for ${ids.length} selected photos…`;
      const reviewId = `cc-review-${crypto.randomUUID()}`;
      const reviewProgress = event => {
        if (event.detail?.request_id === reviewId && event.detail.phase === 'tags' && modal.isConnected)
          status.textContent = `Checking selected tags: ${Number(event.detail.done)} of ${Number(event.detail.total)}`;
      };
      window.addEventListener('companycam:plan-progress', reviewProgress);
      try {
        const result = await pywebview.api.companycam_plan_pull(client, '', cardId, '', reviewId, ids, plan.project_id, true, plan.preview_id || '', quick);
        if (!modal.isConnected) return;
        if (!result?.ok) throw new Error(result?.error || 'Selected photos could not be checked.');
        close();
        await openCompanyCamPullModal(data, audit, result);
      } catch (error) {
        if (modal.isConnected) status.textContent = error.message || 'Review failed. Your selection is kept; try again.';
      } finally {
        reviewing = false;
        window.removeEventListener('companycam:plan-progress', reviewProgress);
        body.querySelectorAll('[data-cc-visit]').forEach(box => {box.disabled = false;});
        updateSelection();
      }
    }
    button.addEventListener('click', () => reviewPhotos(chosen()));
    return;
  }

  const groups = plan.groups || [];
  const stages = ["Initial", "Demo", "Monitor", "Abatement Prep", "Mold Prep", "Reinspection", "Contents", "Scope", "Post", "Cleaning"];
  body.innerHTML = `<div class="cc-pull-summary"><strong>${Number(plan.missing || 0)} photos to import</strong><span>${groups.length} shoot${groups.length === 1 ? "" : "s"} · ${plan.quick_import ? 'Quick import: chosen destination / crew + date. CompanyCam tags are unchanged.' : 'added tags sync to CompanyCam; existing tags stay'}</span></div>
    <div class="cc-pull-groups">${groups.map((group, index) => {
      const tagged = group.stage && group.stage !== "(no stage tag)";
      const suggested = group.suggested_stage || "";
      const currentTags = group.current_tags || [];
      return `<article class="cc-pull-group">
        <input type="checkbox" data-cc-group="${index}" checked aria-label="Import this shoot">
        <div class="cc-pull-shoot"><strong>${escapeHtml(formatAppDate(group.date || "") || group.date || "Unknown date")}</strong><small>${Number(group.count || (group.photo_ids || []).length)} photos${group.rooms?.length ? ` · ${escapeHtml(group.rooms.slice(0, 3).map((room) => room[0]).join(", "))}` : ""}</small></div>
        <label><span>Stage</span>${tagged
          ? `<strong>${escapeHtml(group.stage)}</strong>`
          : `<select data-cc-stage="${index}"><option value="">Choose stage…</option>${stages.map((stage) => `<option value="${escapeAttr(stage)}" ${stage === suggested ? "selected" : ""}>${escapeHtml(stage)}</option>`).join("")}</select>`}</label>
        <label><span>Tech</span><input data-cc-tech="${index}" value="${escapeAttr(group.tech || "")}" placeholder="Technician"></label>
        <div class="cc-pull-tags"><span>${plan.quick_import ? 'Quick import' : 'CompanyCam stage tag'}</span><small data-cc-auto-tag="${index}"></small><small>${plan.quick_import ? 'No tag scan or tag changes' : currentTags.length ? `Current: ${escapeHtml(currentTags.join(", "))}` : "No current tags"}</small></div>
        <div class="cc-pull-target"><span>Files to</span><strong>${escapeHtml(group.target || "Job photos")}</strong></div>
      </article>`;
    }).join("")}</div>
    <footer class="cc-pull-actions"><span data-cc-pull-status></span><button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-start-pull>Pull selected photos</button></footer>`;

  body.querySelector("[data-cancel]").addEventListener("click", close);
  const selectedAssignments = () => Array.from(body.querySelectorAll("[data-cc-group]:checked")).map((box) => {
    const index = Number(box.dataset.ccGroup);
    const group = groups[index] || {};
    return {photo_ids: group.photo_ids || [],
      stage: body.querySelector(`[data-cc-stage="${index}"]`)?.value || "",
      tech: body.querySelector(`[data-cc-tech="${index}"]`)?.value.trim() || "",
      quick_import: plan.quick_import === true};
  });
  const refresh = () => {
    body.querySelectorAll('[data-cc-auto-tag]').forEach((label) => {
      const index = label.dataset.ccAutoTag;
      const stage = body.querySelector(`[data-cc-stage="${index}"]`)?.value || '';
      const tag = plan.stage_tags?.[stage];
      label.textContent = !plan.quick_import && tag ? `Auto-add on pull: ${tag}` : '';
    });
    const assignments = selectedAssignments();
    const missingStage = Array.from(body.querySelectorAll("[data-cc-group]:checked")).some((box) => {
      const select = body.querySelector(`[data-cc-stage="${box.dataset.ccGroup}"]`);
      return select && !select.value;
    });
    const total = assignments.reduce((sum, item) => sum + item.photo_ids.length, 0);
    const button = body.querySelector("[data-start-pull]");
    button.disabled = !total || missingStage;
    button.textContent = missingStage ? "Choose a stage" : `Pull ${total} photo${total === 1 ? "" : "s"}`;
  };
  body.querySelectorAll("[data-cc-group], [data-cc-stage]").forEach((control) => control.addEventListener("change", refresh));
  refresh();
  body.querySelector("[data-start-pull]").addEventListener("click", async (event) => {
    const assignments = selectedAssignments();
    event.currentTarget.disabled = true;
    body.querySelector("[data-cc-pull-status]").textContent = "Starting import…";
    const operationId = crypto.randomUUID();
    const watcher = watchCompanyCamPull(client, cardId, operationId);
    let started;
    try {
      started = await pywebview.api.companycam_pull_assigned_bg(client, assignments, "", cardId, plan.project_id || "", operationId);
    } catch (error) {
      // The worker may have started even if the bridge acknowledgement was lost.
      close();
      if (!watcher.finished) setStatus("CompanyCam start confirmation was lost. Reopen the pull to check its saved status before retrying.", "warn");
      return;
    }
    if (!started?.ok) {
      watcher.stop();
      body.querySelector("[data-cc-pull-status]").textContent = started?.error || "Import could not start.";
      refresh();
      return;
    }
    close();
    if (!watcher.finished) setStatus(`Pulling ${started.total || 0} CompanyCam photos in the background…`, "ok");
  });
}

async function openSubcontractorDispatchModal(jobFields) {
  const modal = document.createElement("div");
  modal.className = "modal-scrim audit-overlay subcontract-dispatch-overlay";
  modal.innerHTML = `<div class="modal-box subcontract-dispatch-card" role="dialog" aria-modal="true" aria-label="Dispatch subcontractor">
    <header class="modal-head"><div><div class="modal-title">Dispatch subcontractor</div><div class="modal-sub">Build a draft from the saved job information</div></div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body subcontract-dispatch-body">
      <div class="subcontract-fields">
        <label><span>Subcontractor email</span><input data-vendor-email type="email" value="dispatch@titan-enviro.com" placeholder="dispatch@vendor.com" autofocus></label>
        <label><span>CC</span><input data-dispatch-cc type="email" value="EMS@servpro10100.com"></label>
        <label><span>Service</span><input data-dispatch-service value="Mold clearance" placeholder="Mold clearance"></label>
        <label><span>Ready date</span><input data-ready-date type="date"></label>
        <label class="span-all"><span>Dispatch details</span><textarea data-scope-notes rows="3" placeholder="One containment in Kitchen"></textarea></label>
      </div>
      <div class="subcontract-preview" data-dispatch-preview><span>Complete the fields to preview the email.</span></div>
      <footer class="subcontract-actions"><span data-dispatch-state></span><button class="btn" data-copy-dispatch>Copy draft</button><button class="btn btn-primary" data-open-dispatch>Open email draft</button></footer>
    </div>
  </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelector("[data-close]").addEventListener("click", close);
  const value = (selector) => modal.querySelector(selector)?.value.trim() || "";
  let currentDraft = null;
  let sequence = 0;
  const build = async () => {
    const request = ++sequence;
    const options = {
      vendor_email: value("[data-vendor-email]"), cc: value("[data-dispatch-cc]"),
      service: value("[data-dispatch-service]"), ready_date: value("[data-ready-date]"),
      scope_notes: value("[data-scope-notes]"),
    };
    const draft = await pywebview.api.subcontractor_dispatch_draft(jobFields, options);
    if (request !== sequence || !modal.isConnected) return null;
    currentDraft = draft?.ok ? draft : null;
    const preview = modal.querySelector("[data-dispatch-preview]");
    if (!currentDraft) {
      preview.innerHTML = `<strong>Draft unavailable</strong><span>${escapeHtml(draft?.error || "Try again.")}</span>`;
      return null;
    }
    preview.innerHTML = `<div><span>To</span><strong>${escapeHtml(currentDraft.to || "Add a subcontractor email")}</strong></div><div><span>CC</span><strong>${escapeHtml(currentDraft.cc || "—")}</strong></div><div><span>Subject</span><strong>${escapeHtml(currentDraft.subject)}</strong></div><pre>${escapeHtml(currentDraft.body)}</pre>`;
    modal.querySelector("[data-dispatch-state]").textContent = currentDraft.missing?.length
      ? `Still needed: ${currentDraft.missing.join(", ")}` : "Ready to review in Outlook";
    return currentDraft;
  };
  let timer;
  modal.querySelectorAll("input, textarea").forEach((control) => control.addEventListener("input", () => {
    clearTimeout(timer); timer = setTimeout(build, 160);
  }));
  modal.querySelector("[data-copy-dispatch]").addEventListener("click", async () => {
    const draft = await build();
    if (!draft) return;
    await pywebview.api.copy_to_clipboard(`To: ${draft.to}\nCc: ${draft.cc}\nSubject: ${draft.subject}\n\n${draft.body}`);
    setStatus("Subcontractor dispatch draft copied", "ok");
  });
  modal.querySelector("[data-open-dispatch]").addEventListener("click", async () => {
    const draft = await build();
    if (!draft || !draft.to) {
      modal.querySelector("[data-dispatch-state]").textContent = "Add the subcontractor email first.";
      return;
    }
    const url = `mailto:${encodeURIComponent(draft.to.replaceAll("; ", ","))}?cc=${encodeURIComponent(draft.cc)}&subject=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(draft.body)}`;
    await pywebview.api.open_url(url);
  });
  await build();
}

function watchCompanyCamPull(client, cardId = "", operationId = "") {
  const key = operationId || client;
  if (companyCamPullWatchers.has(key)) return companyCamPullWatchers.get(key);
  let timer;
  const controller = {finished:false, stop:() => {
    clearTimeout(timer);
    window.removeEventListener("companycam:pull-progress", progress);
    window.removeEventListener("companycam:pull-done", done);
    companyCamPullWatchers.delete(key);
  }};
  const matches = (detail) => operationId ? detail.operation_id === operationId : detail.client === client;
  const progress = (event) => {
    const detail = event.detail || {};
    if (!matches(detail) || controller.finished) return;
    setStatus(`CompanyCam · ${detail.stage || "photos"} · shoot ${detail.i || 0}/${detail.n || 0}`, "");
  };
  const done = (event) => {
    const result = event.detail || {};
    if (!matches(result) || controller.finished) return;
    controller.finished = true;
    controller.stop();
    setStatus(result.ok
      ? `CompanyCam import complete · ${result.pulled || 0} pulled${result.error ? ` · ${result.error}` : ""}`
      : `CompanyCam import failed · ${result.pulled || 0} pulled · ${result.error || "Unknown error"}`, result.ok && !result.error ? "ok" : "warn");
    if (result.receipt_error) setStatus(result.receipt_error, "warn");
    if (Number(result.pulled || 0) > 0) window.dispatchEvent(
      new CustomEvent('pipeline:files-imported', {detail:{client}}));
  };
  companyCamPullWatchers.set(key, controller);
  window.addEventListener("companycam:pull-progress", progress);
  window.addEventListener("companycam:pull-done", done);
  let missedChecks = 0;
  const poll = async () => {
    if (controller.finished || !companyCamPullWatchers.has(key)) return;
    try {
      const receipt = await pywebview.api.companycam_import_status(client, cardId, operationId);
      if (companyCamPullWatchers.get(key) !== controller) return;
      missedChecks = receipt?.ok && receipt.found ? 0 : missedChecks + 1;
      if (receipt?.found && ["complete", "failed"].includes(receipt.state)) {
        done({detail:{...receipt.result, client, operation_id:operationId}});
      }
      if (receipt?.state === "interrupted") {
        controller.stop();
        setStatus("CompanyCam import was interrupted. Reopen the pull and check the folder before retrying.", "warn");
      }
    } catch (_) { missedChecks += 1; }
    if (missedChecks >= 3 && companyCamPullWatchers.get(key) === controller) {
      controller.stop();
      setStatus("CompanyCam import status is unavailable. Reopen the pull to check before retrying; no import was restarted.", "warn");
    }
    if (!controller.finished && companyCamPullWatchers.has(key)) timer = setTimeout(poll, 5000);
  };
  if (operationId && pywebview.api.companycam_import_status) timer = setTimeout(poll, 5000);
  return controller;
}

async function runGlobalCardSearch(rawQuery) {
  const query = String(rawQuery || "").trim();
  const sequence = ++globalSearchSequence;
  if (query.length < 2) {
    state.globalSearchQuery = "";
    state.globalSearchResults = [];
    state.globalSearchLoading = false;
    renderBoard();
    return;
  }
  state.globalSearchQuery = query.toLowerCase();
  state.globalSearchResults = [];
  state.globalSearchLoading = true;
  renderBoard();
  const isCurrent = () => sequence === globalSearchSequence &&
    state.search.trim().toLowerCase() === query.toLowerCase();
  let fullSucceeded = false;
  if (pywebview.api.local_card_search) {
    Promise.resolve().then(() => pywebview.api.local_card_search(query, 24)).then(result => {
      if (!isCurrent() || fullSucceeded || !result?.ok) return;
      state.globalSearchResults = result.cards || [];
      renderBoard();
    }).catch(() => {});
  }
  try {
    const result = await withTimeout(pywebview.api.global_card_search(query, 24), 30000,
      "All-board search took too long");
    if (!isCurrent()) return;
    if (!result?.ok) throw new Error(result?.error || "Search failed");
    const matches = new Map((result.cards || []).map(card => [card.card_id, card]));
    for (const card of state.globalSearchResults) if (!matches.has(card.card_id)) matches.set(card.card_id, card);
    state.globalSearchResults = [...matches.values()].slice(0, 24);
    fullSucceeded = true;
    if (result.remote_unavailable) setStatus("Trello search is unavailable; showing saved matches.", "warn");
  } catch (error) {
    if (isCurrent()) setStatus(state.globalSearchResults.length
      ? "Trello search unavailable; saved matches remain visible."
      : "Trello search unavailable. Try again; saved matches may still load.", "warn");
  } finally {
    if (isCurrent()) {
      state.globalSearchLoading = false;
      renderBoard();
    }
  }
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
  else if (action === "popout") await window.OneLossPopout?.open('pipeline',{cardId:row.card_id,client:row.client,division:row.division||'EMS'});
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
function openNewLossModal() {
  const alreadyOpen = document.getElementById("nl-paste");
  if (alreadyOpen) { alreadyOpen.focus(); return; }
  if (!window.openModal) {
    setStatus("New Loss dialog could not load. Refresh Jobs and try again.", "error");
    return;
  }

  const renderField = ([key, label]) => `
    <label class="new-loss-field">
      <span>${escapeHtml(label)}</span>
      ${NEW_LOSS_TEXTAREAS.has(key)
        ? `<textarea id="nl-${key}" rows="${key === "field_notes" ? 3 : 2}"></textarea>`
        : `<input id="nl-${key}" type="text" autocomplete="off" />`}
    </label>`;
  const renderGroup = ([label, fields]) => `
    <section class="new-loss-group">
      <h3>${escapeHtml(label)}</h3>
      <div class="new-loss-fields">${fields.map(renderField).join("")}</div>
    </section>`;

  const overlay = window.openModal({
    title: "New Loss",
    width: 860,
    body: `
      <div id="nl-board-line" class="new-loss-board-line">Loading templates…</div>
      <section class="new-loss-paste">
        <label for="nl-paste">Paste assignment</label>
        <textarea id="nl-paste" rows="8" placeholder="Paste the carrier assignment email here…" autofocus></textarea>
        <div class="new-loss-parse-row">
          <button class="btn" id="nl-parse" type="button">Parse assignment</button>
          <span id="nl-parse-status" aria-live="polite"></span>
        </div>
      </section>
      <div class="new-loss-heading-fields">
        <label class="new-loss-field"><span>Template</span>
          <select id="nl-loss_type">
            <option value="water" data-kind="water">Water</option>
            <option value="fire" data-kind="fire">Fire</option>
            <option value="property" data-kind="property">Property management</option>
          </select>
        </label>
        <label class="new-loss-field"><span>Job / card name</span>
          <input id="nl-card_name" type="text" autocomplete="off" placeholder="Customer - Carrier" />
        </label>
      </div>
      <div id="nl-folder-card" class="new-loss-folder hidden"></div>
      <div class="new-loss-grid">${NEW_LOSS_GROUPS.map(renderGroup).join("")}</div>
      <details class="new-loss-parent">
        <summary>File under an existing client</summary>
        <p>Use this for a unit, tenant, school, or another claim that belongs under an existing client.</p>
        <input id="nl-parent-q" type="search" autocomplete="off" placeholder="Search client folders…" />
        <div id="nl-parent-hits"></div>
      </details>
      <div class="new-loss-provisioning">
        <strong>Creates and links</strong>
        <span>OD job folder</span><span>Trello card</span><span>CompanyCam project</span>
      </div>
      <footer class="new-loss-footer">
        <span id="nl-status" aria-live="polite"></span>
        <button class="btn modal-close" type="button">Cancel</button>
        <button class="btn btn-primary" id="nl-create" type="button">Create job</button>
      </footer>`,
  });

  const find = (selector) => overlay.querySelector(selector);
  const put = (key, value) => {
    const field = find(`#nl-${key}`);
    if (field) field.value = value || "";
  };
  let parent = "";
  let parentSearchTimer = null;
  let lastSuggestedName = '';
  let namePreviewSequence = 0;
  const syncSuggestedName = async () => {
    const sequence = ++namePreviewSequence;
    const field = find('#nl-card_name');
    let preview;
    try { preview = await pywebview.api.preview_intake_names({insured_name: find('#nl-insured_name')?.value.trim(), carrier: find('#nl-carrier')?.value.trim()}); }
    catch (_) { return; }
    if (sequence !== namePreviewSequence) return;
    const suggested = preview.trello || '';
    if (!field.value.trim() || field.value === lastSuggestedName) field.value = suggested;
    lastSuggestedName = suggested;
  };
  ['#nl-insured_name', '#nl-carrier'].forEach(selector => find(selector)?.addEventListener('input', syncSuggestedName));

  async function refreshFolderPlan() {
    const insured = (find("#nl-insured_name")?.value || "").trim();
    const panel = find("#nl-folder-card");
    if (!insured) { panel.classList.add("hidden"); return; }
    const child = (find("#nl-child-name")?.value || "").trim();
    const secondClaim = !!find("#nl-second-claim")?.checked;
    let result;
    try {
      result = await pywebview.api.plan_new_loss_folder(
        { insured_name: insured }, child, secondClaim, parent);
    } catch (_) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden", "ok", "warn");
    if (!result?.ok) {
      panel.classList.add("warn");
      panel.innerHTML = `<strong>Folder needs attention</strong><span>${escapeHtml(result?.error || "Folder unavailable")}</span>`;
      return;
    }
    panel.classList.add("ok");
    if (result.mode === "new_client") {
      panel.innerHTML = `<strong>New client folder</strong><code>${escapeHtml(result.path || "")}</code>`;
      return;
    }
    const promote = result.promote_first_claim || {};
    panel.innerHTML = `
      <strong>${escapeHtml(result.client || insured)} already exists</strong>
      <span>This job will be filed inside that client.</span>
      <div class="new-loss-folder-options">
        <input id="nl-child-name" type="text" value="${escapeAttr(result.child || "")}" placeholder="Job subfolder name" />
        <label><input id="nl-second-claim" type="checkbox" ${secondClaim ? "checked" : ""} /> New claim number</label>
        ${promote.eligible ? `<label><input id="nl-promote" type="checkbox" /> Move existing loose files into 1st Claim</label>` : ""}
      </div>
      <code>${escapeHtml(result.path || "")}</code>`;
    find("#nl-child-name")?.addEventListener("change", refreshFolderPlan);
    find("#nl-second-claim")?.addEventListener("change", refreshFolderPlan);
  }

  async function searchParents(query) {
    const hits = find("#nl-parent-hits");
    hits.innerHTML = `<span class="muted">Searching…</span>`;
    let result;
    try { result = await pywebview.api.search_client_folders(query || "", 40); }
    catch (_) { result = null; }
    if (!hits.isConnected) return;
    const rows = result?.clients || [];
    hits.innerHTML = rows.length ? rows.map((row) => `
      <button type="button" data-parent="${escapeAttr(row.name || "")}">
        <strong>${escapeHtml(row.name || "")}</strong>
        ${row.child_count ? `<span>${row.child_count} jobs</span>` : ""}
      </button>`).join("") : `<span class="muted">No matching client folders.</span>`;
    hits.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
      parent = button.dataset.parent || "";
      find("#nl-parent-q").value = parent;
      hits.innerHTML = `<span class="new-loss-parent-selected">Filing under <strong>${escapeHtml(parent)}</strong></span>`;
      refreshFolderPlan();
    }));
  }

  find(".new-loss-parent")?.addEventListener("toggle", (event) => {
    if (event.currentTarget.open) searchParents("");
  });
  find("#nl-parent-q")?.addEventListener("input", (event) => {
    parent = "";
    clearTimeout(parentSearchTimer);
    parentSearchTimer = setTimeout(() => searchParents(event.currentTarget.value), 180);
  });

  (async () => {
    let result;
    try { result = await pywebview.api.new_loss_templates(); }
    catch (error) { result = { ok: false, error: String(error) }; }
    const line = find("#nl-board-line");
    if (!line) return;
    if (!result?.ok) {
      line.classList.add("warn");
      line.textContent = result?.error || "The WIP templates are unavailable.";
      return;
    }
    const templates = result.templates || [];
    line.innerHTML = `<strong>${escapeHtml(result.board || "WIP")}</strong><span>${escapeHtml(result.intake || "Intake")}</span>`;
    if (!templates.length) return;
    const select = find("#nl-loss_type");
    select.innerHTML = templates.map((template) => `
      <option value="${escapeAttr(template.id || "")}" data-template-id="${escapeAttr(template.id || "")}" data-kind="${escapeAttr(template.kind || "water")}">${escapeHtml(template.name || "Template")}</option>`).join("");
    if (result.default_template_id && [...select.options].some(option => option.value === result.default_template_id)) {
      select.value = result.default_template_id;
    }
  })();

  find("#nl-parse").addEventListener("click", async () => {
    const raw = find("#nl-paste").value.trim();
    if (!raw) { find("#nl-parse-status").textContent = "Paste the assignment first."; return; }
    find("#nl-parse-status").textContent = "Reading assignment…";
    let result;
    try { result = await pywebview.api.parse_new_loss(raw); }
    catch (error) { result = { ok: false, error: String(error) }; }
    if (!result?.ok) { find("#nl-parse-status").textContent = result?.error || "Could not parse assignment."; return; }
    const fields = result.fields || {};
    NEW_LOSS_GROUPS.forEach(([, items]) => items.forEach(([key]) => put(key, fields[key])));
    put("card_name", fields.card_name);
    lastSuggestedName = fields.card_name || '';
    syncSuggestedName();
    // Parsing job details must not replace the default or a user's template choice.
    find("#nl-parse-status").textContent = "Assignment read. Review the highlighted job details.";
    refreshFolderPlan();
  });

  find("#nl-insured_name")?.addEventListener("change", refreshFolderPlan);
  find("#nl-insured_name")?.addEventListener("blur", refreshFolderPlan);
  find("#nl-create").addEventListener("click", async () => {
    const selected = find("#nl-loss_type").selectedOptions[0];
    const fields = {
      loss_type: selected?.dataset.kind || find("#nl-loss_type").value,
      template_id: selected?.dataset.templateId || "",
    };
    NEW_LOSS_GROUPS.forEach(([, items]) => items.forEach(([key]) => {
      fields[key] = (find(`#nl-${key}`)?.value || "").trim();
    }));
    fields.card_name = (find("#nl-card_name")?.value || "").trim();
    const status = find("#nl-status");
    if (fields.street_address_1.length > 100) {
      status.textContent = 'Street address must be 100 characters or fewer. Use the separate unit, city, state and ZIP fields; put instructions in Notes.';
      find('#nl-street_address_1').focus();
      return;
    }
    fields.state = fields.state.toUpperCase();
    fields.address = [fields.street_address_1, fields.street_address_2, fields.city,
      [fields.state, fields.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    if (!fields.card_name && !fields.insured_name) {
      status.textContent = "Enter a customer name or job name.";
      return;
    }
    const button = find("#nl-create");
    button.disabled = true;
    fields.client_choice = await window.IntakeClient.choose(fields);
    if (!fields.client_choice) { button.disabled = false; return; }
    status.textContent = "Creating folder, Trello card, and CompanyCam project…";
    let result;
    try {
      result = await pywebview.api.create_new_loss(
        fields,
        (find("#nl-child-name")?.value || "").trim(),
        !!find("#nl-second-claim")?.checked,
        !!find("#nl-promote")?.checked,
        true, true, parent);
    } catch (error) { result = { ok: false, error: String(error) }; }
    if (!result?.ok) {
      if (result?.partial) {
        window.closeModal("modal-overlay");
        setStatus(result.error || `Created ${result.name}, but setup needs attention. Do not create it again.`, "warn");
        if (pipelineQuery.get('intake_only') !== '1') await loadBoard(true);
        return;
      }
      button.disabled = false;
      status.textContent = result?.error || "The job could not be created.";
      status.classList.add("error");
      return;
    }
    window.closeModal("modal-overlay");
    const provisioning = result.provisioning || {};
    const incomplete = provisioning.complete === false;
    setStatus(
      incomplete
        ? (result.warning || `Created ${result.name}, but ${((provisioning.failed || []).join(", ") || "part of setup")} needs attention.`)
        : `Created and linked ${result.name}.`,
      incomplete ? "warn" : "ok");
    if (pipelineQuery.get('intake_only') !== '1') await loadBoard(true);
  });
}

function setStatus(msg, kind = "", diagnostics = null) {
  if (diagnostics && (kind === 'error' || kind === 'warn')) {
    try {
      const d = JSON.parse(diagnostics);
      // Explicit allowlist: do not upload response bodies, stacks or neighbors.
      const context = {tool:d.action, card_id:d.card?.id, job_name:d.card?.name,
        destination_list_id:d.destination?.id, destination_list:d.destination?.name};
      Promise.resolve(pywebview.api.report_app_error('pipeline', msg, context)).catch(() => {});
    } catch (_) { /* Reporting must not interrupt the failed action. */ }
  }
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
function loadingIndicator(label) {
  return `<div class="ui-loading-state" role="status" title="${escapeAttr(label)}"><span class="ui-spinner" aria-hidden="true"></span><span class="ui-loading-label">${escapeHtml(label)}</span></div>`;
}
function escapeAttr(s) { return esc(s); }
function cssEsc(s) { return String(s ?? "").replace(/["\\\]]/g, "\\$&"); }
