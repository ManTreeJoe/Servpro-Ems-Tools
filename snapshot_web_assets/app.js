/* Linguar Hub — Snapshot web frontend.
 *
 * Two views in one page:
 *  • LIST view (default): candidates (closeout + run-doc) + recent PDFs
 *  • GENERATE view: form to fill out + write the snapshot PDF
 *
 * Generation runs entirely in the web — same backend (fill_pdf,
 * append_overflow_pages) but no Tk involvement.
 */
"use strict";
const state = {
  view: "list",
  current: null,
  importBtn: null,
  candidates: [],
  queue: { search: "", board: "all", lane: "all", showAll: false, focusedFromJobs: false },
  openRequest: 0,
  queueLoaded: false,
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const pad2 = (n) => String(n).padStart(2, "0");
let _queueSyncBusy = false;
let _queueSyncPromise = null;
let _queueSyncTimer = null;
let _jobLogSyncTimer = null;

// Live HEIC→JPEG conversion progress from the backend (do_import emits
// `import:progress` per file). Updates the running import button so a
// big photo dump shows "Converting N/M…" instead of a frozen
// "Extracting…". No-op if no import is active or the count is 0.
// Same bar as the audit panel: the import already streamed
// {done, total}, it just never reached the status bar here.
if (window.Progress) window.Progress.bind("import:progress", "import:done");
window.addEventListener("import:progress", (e) => {
  const d = (e && e.detail) || {};
  if (state.importBtn && d.total) {
    state.importBtn.textContent = `Converting ${d.done}/${d.total}…`;
  }
});

window.addEventListener("pywebviewready", async () => {
  // Only the Today/Tracked tab is restored. `state.view` also covers the
  // "gen" form, and reopening the panel into a half-filled new-snapshot
  // form would be worse than forgetting.
  await PanelState.init("snapshot");

  $("#view-list-btn").addEventListener("click", () => switchTo("list"));
  $("#view-gen-btn").addEventListener("click", () => startNew());
  $("#refresh-btn").addEventListener("click", loadList);
  $("#queue-search").addEventListener("input", (e) => {
    state.queue.search = e.target.value;
    state.queue.focusedFromJobs = false;
    renderCandidateQueue();
  });
  $("#queue-board").addEventListener("change", (e) => {
    state.queue.board = e.target.value;
    renderCandidateQueue();
  });
  $("#queue-lane").addEventListener("change", (e) => {
    state.queue.lane = e.target.value;
    renderCandidateQueue();
  });
  $("#queue-show-all").addEventListener("change", (e) => {
    state.queue.showAll = e.target.checked;
    renderCandidateQueue();
  });
  attachTopbarTrelloSearch();
  $("#gen-cancel").addEventListener("click", () => {
    state.openRequest += 1; // invalidate any slow prefill still in flight
    setSnapshotFormLoading(false);
    switchTo("list");
  });
  $("#gen-go").addEventListener("click", generate);
  $("#gen-find").addEventListener("click", openFindCardModal);
  $("#gen-audit").addEventListener("click", runSnapshotAudit);
  $("#parse-comments-btn").addEventListener("click", parseTrelloComments);
  $("#audit-run-btn").addEventListener("click", runSnapshotAudit);
  $("#gen-scope").addEventListener("click", openScopeModal);
  $("#gen-docusign-email").addEventListener("click", copyDocusignEmail);
  $("#snapshot-comments-btn").addEventListener("click", toggleSnapshotComments);
  // After-generate buttons (post-actions panel)
  $("#post-trello-btn").addEventListener("click", postToTrello);
  $("#snapshot-history-btn").addEventListener("click", openSnapshotHistory);
  $("#open-pdf-btn").addEventListener("click",
    () => state.lastPdfPath && pywebview.api.open_pdf(state.lastPdfPath));
  document.querySelectorAll(".add-row-btn[data-tbl]").forEach((b) =>
    b.addEventListener("click", () => addRow(b.dataset.tbl, {})));
  // Tech roster: load the autocomplete options + wire the manage modal.
  loadTechRoster();
  $("#manage-techs-btn")?.addEventListener("click", openTechsModal);
  $("#techs-close-btn")?.addEventListener("click", closeTechsModal);
  $("#tech-add-btn")?.addEventListener("click", addTechFromModal);
  $("#tech-add-name")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addTechFromModal(); }
  });
  $("#tech-add-initials")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addTechFromModal(); }
  });
  $("#techs-overlay")?.addEventListener("click", (e) => {
    if (e.target.id === "techs-overlay") closeTechsModal();
  });
  // Auto-save the snapshot form on every edit (debounced) so switching
  // panels / reloading this iframe no longer loses in-progress work.
  $("#view-gen")?.addEventListener("input", () => {
    clearTimeout(_draftTimer);
    _draftTimer = setTimeout(saveSnapshotDraft, 400);
  });
  // The Snapshot daily-log table is a closeout view of Job Log, not a
  // separate copy. Save complete edited rows after the user pauses typing.
  $("#logs-body")?.addEventListener("input", () => {
    clearTimeout(_jobLogSyncTimer);
    _jobLogSyncTimer = setTimeout(syncSnapshotJobLog, 900);
  });
  // Snapshot list-view tabs (Today vs Tracked)
  document.querySelectorAll("#snap-tabs .tab-btn").forEach((b) =>
    b.addEventListener("click", () => snapshotShowTab(b.dataset.tab)));
  const savedTab = PanelState.get("tab", "");
  if (savedTab === "tracked") snapshotShowTab("tracked");
  // Tracked tab — filter + sheet selector + refresh + open Excel
  $("#tracked-search")?.addEventListener("input", (e) => {
    trackedState.search = e.target.value; renderTracked();
  });
  $("#tracked-sheet")?.addEventListener("change", (e) => {
    trackedState.sheet = e.target.value; renderTracked();
  });
  $("#tracked-refresh")?.addEventListener("click", loadTrackedSnapshots);
  $("#tracked-open-xlsx")?.addEventListener("click",
    () => pywebview.api.open_tracked_workbook());
  $("#tracked-change-dir")?.addEventListener("click", changeTrackingDir);
  $("#tracked-reconcile")?.addEventListener("click", runReconcile);
  $("#tracked-auto-recon")?.addEventListener("change", async (e) => {
    await pywebview.api.set_auto_reconcile(e.target.checked);
  });
  window.addEventListener("snap:recon-progress", (ev) => {
    const d = ev.detail || {};
    const el = $("#tracked-meta");
    if (el) el.textContent = `🔄 Reconciling ${d.done || 0}/${d.total || "?"} · ${d.label || "…"}`;
  });
  window.addEventListener("snap:recon-done", onReconcileDone);
  // Reflect the persisted auto-reconcile preference.
  try {
    const auto = await pywebview.api.get_auto_reconcile();
    const cb = $("#tracked-auto-recon");
    if (cb) cb.checked = !!auto;
  } catch { /* optional */ }
  await loadList();
  // Trello is the queue's source of truth. Coworkers can move cards into the
  // Snapshot lane at any time, so keep this screen current without requiring
  // a manual refresh. Also refresh immediately when the app regains focus.
  _queueSyncTimer = setInterval(() => syncSnapshotQueue(), 60_000);
  window.addEventListener("focus", () => syncSnapshotQueue());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) syncSnapshotQueue();
  });
  // Deep-link from Jobs: keep the user in the Trello-controlled close-out
  // queue and filter it to that job. The old behavior opened Tracked
  // history, which said nothing about whether the card was eligible for
  // a final close-out audit right now.
  const _focus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";
  if (_focus) {
    snapshotShowTab("today");
    state.queue.search = _focus;
    state.queue.focusedFromJobs = true;
    const tb = $("#queue-search");
    if (tb) tb.value = _focus;
    renderCandidateQueue();
    tb?.focus();
  } else {
    // No deep-link — if there's an unsaved snapshot draft from before a
    // panel switch / reload, restore it into the form so nothing is lost.
    const _draft = loadSnapshotDraft();
    if (_draft) restoreSnapshotDraft(_draft);
  }
});

let _reconBusy = false;
async function runReconcile() {
  if (_reconBusy) return;
  const btn = $("#tracked-reconcile");
  const r = await pywebview.api.reconcile_tracked(0);
  if (!r?.started) {
    if (window.toastLog) window.toastLog(`Reconcile busy: ${r?.reason || "?"}`);
    return;
  }
  _reconBusy = true;
  if (btn) { btn.disabled = true; btn.textContent = "Reconciling…"; }
}

async function onReconcileDone(ev) {
  _reconBusy = false;
  const btn = $("#tracked-reconcile");
  if (btn) { btn.disabled = false; btn.textContent = "🔄 Reconcile"; }
  const d = ev.detail || {};
  if (!d.ok) {
    if (window.toastLog) window.toastLog(`Reconcile failed: ${d.error || "?"}`);
    await loadTrackedSnapshots();
    return;
  }
  const res = d.result || {};
  const bt = res.by_target || {};
  const msg = `🔄 Reconcile done · `
    + (res.added_new_loss ? `added ${res.added_new_loss} new · ` : "")
    + `moved ${res.moved || 0} · `
    + `${bt.completed || 0} completed, ${bt.incomplete || 0} incomplete, `
    + `${bt.new_loss || 0} still open`
    + (bt.needs_attention ? `, ${bt.needs_attention} ⚠ needs attention` : "");
  if (window.toastLog) window.toastLog(msg);
  await loadTrackedSnapshots();
}

// ── Tracking-workbook folder (location) ─────────────────────────────
async function refreshTrackingLocation() {
  const el = $("#tracked-loc");
  if (!el) return;
  try {
    const r = await pywebview.api.tracking_location();
    if (r && r.root) {
      const warn = r.workbook_exists ? "" : "  ⚠ no workbook here yet";
      el.textContent = `📁 ${r.root}${warn}`;
    }
  } catch { /* ignore */ }
}

async function changeTrackingDir() {
  const r = await pywebview.api.change_tracking_dir();
  if (r?.canceled) return;
  if (!r?.ok) {
    alert("Couldn't change folder: " + (r?.error || "?"));
    return;
  }
  const moved = r.moved
    ? `moved ${r.moved} workbook${r.moved === 1 ? "" : "s"}`
    : (r.note || "repointed");
  await refreshTrackingLocation();
  await loadTrackedSnapshots();
  if (window.toastLog) window.toastLog(`📁 Tracking folder · ${moved}`);
}

function switchTo(view) {
  state.view = view;
  $("#view-list").classList.toggle("hidden", view !== "list");
  $("#view-gen").classList.toggle("hidden", view !== "gen");
  // Hide the Today/Tracked tab strip when the form is open — it
  // belongs to the list view only.
  const tabs = $("#snap-tabs");
  if (tabs) tabs.style.display = (view === "list") ? "" : "none";
}

function refreshSnapshotCommentsButton() {
  const button = $("#snapshot-comments-btn");
  if (!button) return;
  button.disabled = !state.cardId;
  button.title = state.cardId
    ? "Show this Trello thread beside the snapshot"
    : "Pick or find the Trello card first";
}

function toggleSnapshotComments() {
  const client = $("#f-insured")?.value.trim() || state.lastClient || "Job";
  if (!state.cardId) { setStatus("Pick or find the Trello card first", "warn"); return; }
  const row = { client, display_name: client, trello_card_id: state.cardId };
  const ctx = snapshotAuditCtx();
  window.AuditDetail.syncCommentsDrawer(row, ctx);
  window.AuditDetail.toggleCommentsDrawer(row, ctx);
}

async function loadList() {
  if (!state.queueLoaded) renderQueueSkeleton();
  // Independent sources load together. A slow Trello response must not hold
  // the local recent-PDF list hostage.
  await Promise.allSettled([syncSnapshotQueue(true), loadRecentSnapshots()]);
  refreshTrackedCountBadge();
}

async function loadRecentSnapshots() {
  const pdfs = $("#pdfs");
  if (pdfs && !pdfs.children.length) pdfs.innerHTML = skeletonRows(3, "pdf");
  let data;
  try { data = await pywebview.api.recent_snapshots(50); }
  catch (ex) {
    if (pdfs) pdfs.innerHTML = `<div class="empty-inline">Recent PDFs unavailable: ${esc(ex)}</div>`;
    return;
  }
  $("#open-folder-btn").onclick = () => pywebview.api.open_folder(data.dir);
  $("#pdfs").innerHTML = data.rows.length
    ? data.rows.map((p) => `
        <div class="pdf-row" data-path="${esc(p.path)}">
          <div class="pdf-name">${esc(p.name)}</div>
          <div class="pdf-meta">${esc(p.mtime)}</div>
          <div class="pdf-meta">${p.size_kb} KB</div>
        </div>`).join("")
    : `<div class="empty-inline">No PDFs in <code>${esc(data.dir || "(unset)")}</code></div>`;
  document.querySelectorAll(".pdf-row").forEach((row) =>
    row.addEventListener("click", () => pywebview.api.open_pdf(row.dataset.path)));
  const queued = state.candidates.filter((r) => r.snapshot).length;
  $("#status-counts").textContent = `${queued} in Snapshot · ${data.rows.length} recent PDFs`;
}

async function syncSnapshotQueue(force = false) {
  if (_queueSyncBusy) return _queueSyncPromise;
  if (!force && (document.hidden || state.view !== "list" || $("#tab-today")?.classList.contains("hidden"))) return;
  _queueSyncBusy = true;
  _queueSyncPromise = (async () => {
    const synced = $("#queue-synced");
    if (synced) synced.textContent = state.queueLoaded ? "Refreshing Trello…" : "Loading Snapshot lane…";
    try {
      state.candidates = await pywebview.api.candidate_jobs(!!force) || [];
      state.queueLoaded = true;
      refreshQueueFilterOptions();
      renderCandidateQueue();
      const queued = state.candidates.filter((r) => r.snapshot).length;
      if (synced) synced.textContent = `Trello live · ${new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}`;
      const recent = $("#status-counts")?.textContent.match(/·\s*(\d+) recent PDFs/);
      if (recent) $("#status-counts").textContent = `${queued} in Snapshot · ${recent[1]} recent PDFs`;
    } catch (ex) {
      if (synced) synced.textContent = "Trello unavailable · press ↻";
      if (!state.queueLoaded) $("#candidates").innerHTML = `<div class="empty-inline">Could not load the Snapshot lane. Recent PDFs and manual snapshots are still available.</div>`;
      if (force) setStatus(`Could not load Snapshot lane: ${ex}`, "error");
    } finally {
      _queueSyncBusy = false;
      _queueSyncPromise = null;
    }
  })();
  return _queueSyncPromise;
}

function skeletonRows(count, kind="card") {
  return Array.from({length:count}, () => `<div class="snapshot-skeleton ${kind}"><i></i><span></span><b></b></div>`).join("");
}
function renderQueueSkeleton() {
  const el = $("#candidates");
  if (el) el.innerHTML = skeletonRows(6);
}

function refreshQueueFilterOptions() {
  const unique = (key) => [...new Set(state.candidates.map((r) => r[key]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  const fill = (el, values, allLabel, current) => {
    el.innerHTML = `<option value="all">${allLabel}</option>`
      + values.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    el.value = values.includes(current) ? current : "all";
  };
  fill($("#queue-board"), unique("board"), "All boards", state.queue.board);
  fill($("#queue-lane"), unique("lane"), "All lanes", state.queue.lane);
  state.queue.board = $("#queue-board").value;
  state.queue.lane = $("#queue-lane").value;
}

function renderCandidateQueue() {
  const candsEl = $("#candidates");
  if (!candsEl) return;
  const q = state.queue.search.trim().toLowerCase();
  const filtered = state.candidates.filter((r) => {
    if (!state.queue.showAll && !r.snapshot && !q) return false;
    if (state.queue.board !== "all" && r.board !== state.queue.board) return false;
    if (state.queue.lane !== "all" && r.lane !== state.queue.lane) return false;
    if (!q) return true;
    return [r.client, r.board, r.lane].join(" ").toLowerCase().includes(q);
  });
  const queued = state.candidates.filter(r => r.snapshot).length;
  $("#queue-count").textContent = `${queued} Snapshot · ${filtered.length} shown`;
  // One-click flow: clicking ANYWHERE on the row opens the form with
  // the Trello card already parsed in (carrier/claim/DOL/cause/
  // first-visit/subs/logs/scope). User was complaining about having
  // to click 3 different buttons — Snapshot, then Find Trello, then
  // a result — to get the form filled. Now the row click does it all.
  candsEl.innerHTML = filtered.length
    ? filtered.map((r) => `
        <div class="closeout-row snap-cand" data-client="${esc(r.client)}" data-card="${esc(r.card_id || "")}" style="cursor:pointer;">
          <div>
            <div class="name">${esc(titleCase(r.client))}</div>
            <div class="sub">
              <span class="candidate-pill ${r.snapshot ? "closeout" : "rundoc"}">${esc(r.lane || r.source)}</span>
              ${r.board ? `<span class="muted" style="font-size:10px;">${esc(r.board)}</span>` : ""}
              ${r.card_id ? "· Pinned" : ""}
            </div>
          </div>
          <label class="snapshot-toggle ${r.snapshot ? "on" : ""}" title="Move this Trello card ${r.snapshot ? "out of" : "into"} the Snapshot lane">
            <input type="checkbox" data-snapshot-toggle data-card="${esc(r.card_id)}" data-list="${esc(r.snapshot_list_id)}" ${r.snapshot ? "checked" : ""}>
            <span>Snapshot</span>
          </label>
          ${r.card_id ? `<button class="btn snap-trello-btn" data-url="https://trello.com/c/${esc(r.card_id)}" style="font-size:11px;">🔗</button>` : "<span></span>"}
          <button class="btn btn-primary" data-new="${esc(r.client)}" data-card="${esc(r.card_id || "")}" ${r.snapshot ? "" : "disabled"}>Open</button>
        </div>`).join("")
    : state.queue.focusedFromJobs && q
      ? `<div class="empty-inline"><strong>${esc(state.queue.search)}</strong> is not currently in a SNAPSHOT lane on an Estimating board. Move its Trello card into that lane when it is ready for the final close-out audit.</div>`
      : state.candidates.length
      ? `<div class="empty-inline">No eligible close-out cards match these filters.</div>`
      : `<div class="empty-inline">No open cards were found on an Estimating board with a Snapshot lane.</div>`;
  // Whole-row click → open form with Trello prefill (when card_id present)
  candsEl.querySelectorAll(".snap-cand").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-url]") || e.target.closest("[data-new]")
          || e.target.closest(".snapshot-toggle")) return;
      startNew(row.dataset.client, row.dataset.card || "");
    });
  });
  candsEl.querySelectorAll("[data-new]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      startNew(b.dataset.new, b.dataset.card || "");
    }));
  candsEl.querySelectorAll("[data-url]").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); pywebview.api.open_url(b.dataset.url); }));
  candsEl.querySelectorAll("[data-snapshot-toggle]").forEach((toggle) =>
    toggle.addEventListener("change", async (e) => {
      e.stopPropagation();
      const wanted = toggle.checked;
      let returnListId = "";
      if (!wanted) {
        setStatus("Loading close-out destinations…");
        const choices = await pywebview.api.snapshot_return_destinations(toggle.dataset.card);
        if (!choices?.ok) {
          toggle.checked = true;
          setStatus(`Could not load destinations: ${choices?.error || "?"}`, "error");
          return;
        }
        const picked = await pickSnapshotDestination(choices.destinations || []);
        if (!picked) {
          toggle.checked = true;
          setStatus("Card stayed in Snapshot");
          return;
        }
        returnListId = picked;
      }
      toggle.disabled = true;
      setStatus(`${wanted ? "Adding to" : "Removing from"} Snapshot…`);
      const res = await pywebview.api.set_snapshot(
        toggle.dataset.card, wanted, toggle.dataset.list || "", returnListId);
      if (!res?.ok) {
        toggle.checked = !wanted;
        toggle.disabled = false;
        setStatus(`Snapshot toggle failed: ${res?.error || "?"}`, "error");
        return;
      }
      setStatus(wanted ? "Added to Snapshot" : `Removed from Snapshot · ${res.lane}`, "ok");
      await loadList();
    }));

}

function pickSnapshotDestination(destinations) {
  return new Promise((resolve) => {
    let finished = false;
    const done = (value) => {
      if (finished) return;
      finished = true;
      resolve(value || "");
    };
    const body = destinations.length
      ? `<p class="muted" style="margin:0;">The close-out is finished. Where should this Trello card go next?</p>
         <div style="display:grid;gap:8px;">
           ${destinations.map((lane) => `<button class="btn snapshot-destination" type="button"
             data-list="${escapeAttr(lane.id)}" style="text-align:left;padding:11px 14px;">${escapeHtml(lane.name)}</button>`).join("")}
         </div>
         <div style="text-align:right;"><button class="btn modal-close" type="button">Cancel</button></div>`
      : `<p>No Estimating or Service Call lanes were found on this board.</p>
         <div style="text-align:right;"><button class="btn modal-close" type="button">Keep in Snapshot</button></div>`;
    const modal = openModal({
      id: "snapshot-destination-modal",
      title: "Send card after close-out",
      sub: "Choose the next Trello lane",
      body,
      width: 500,
      onClose: () => done("")
    });
    modal.querySelectorAll(".snapshot-destination").forEach((button) =>
      button.addEventListener("click", () => {
        const value = button.dataset.list || "";
        done(value);
        closeModal("snapshot-destination-modal");
      }));
  });
}

// ── Tab switching ───────────────────────────────────────────────
function snapshotShowTab(tab) {
  try { PanelState.set({ tab }); } catch (_) { /* optional */ }
  document.querySelectorAll("#snap-tabs .tab-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  $("#tab-today").classList.toggle("hidden", tab !== "today");
  $("#tab-tracked").classList.toggle("hidden", tab !== "tracked");
  if (tab === "tracked" && !state._trackedLoaded) {
    state._trackedLoaded = true;
    loadTrackedSnapshots();
    // Auto-reconcile on first open of the Tracked tab when the user
    // opted in — moves closed jobs off NEW LOSS without a manual click.
    if ($("#tracked-auto-recon")?.checked) runReconcile();
  }
}

async function refreshTrackedCountBadge() {
  try {
    const r = await pywebview.api.tracked_snapshots();
    if (r?.ok) {
      $("#tab-tracked-count").textContent = `(${r.total})`;
    }
  } catch (_) {}
}

// ── Tracked snapshots tab (Snapshots <YY>.xlsx as a clean table) ──
const trackedState = { rows: [], search: "", sheet: "all" };

async function loadTrackedSnapshots() {
  $("#tracked-meta").textContent = "Loading…";
  refreshTrackingLocation();
  const r = await pywebview.api.tracked_snapshots();
  if (!r?.ok) {
    $("#tracked-meta").textContent = `Error: ${r?.error || "?"}`;
    return;
  }
  trackedState.rows = r.rows || [];
  $("#tracked-meta").textContent =
    `Year ${r.year} · ${r.by_sheet["NEW LOSS"] || 0} new · ` +
    `${r.by_sheet.Completed || 0} completed · ` +
    `${r.by_sheet.Incomplete || 0} incomplete` +
    (r.by_sheet["Needs Attention"]
      ? ` · ${r.by_sheet["Needs Attention"]} ⚠ needs attention` : "");
  renderTracked();
}

function renderTracked() {
  const q = trackedState.search.trim().toLowerCase();
  const sheet = trackedState.sheet;
  const filtered = trackedState.rows.filter((r) => {
    if (sheet !== "all" && r.sheet !== sheet) return false;
    if (!q) return true;
    const blob = [r.name, r.carrier, r.claim, r.type_of_loss, r.comment]
      .join(" ").toLowerCase();
    return blob.includes(q);
  });
  const tbody = $("#tracked-tbody");
  const empty = $("#tracked-empty");
  if (!filtered.length) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  const cell = (v) => v ? esc(v) : `<span class="cell-x">—</span>`;
  // Format any date-ish string to MM-DD-YYYY. Accepts ISO
  // (2026-05-27), slash (5/27/26, 05/27/2026), or already-MM-DD-YYYY.
  // Pass-through for non-date text so weirdly-shaped cells don't get
  // mangled into "NaN-NaN-NaN".
  const fmtDate = (v) => {
    const s = String(v || "").trim();
    if (!s) return `<span class="cell-x">—</span>`;
    let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return esc(`${pad2(m[2])}-${pad2(m[3])}-${m[1]}`);
    m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/);
    if (m) {
      const yy = m[3].length === 2 ? "20" + m[3] : m[3];
      return esc(`${pad2(m[1])}-${pad2(m[2])}-${yy}`);
    }
    // Excel sometimes serializes dates as ISO with a "T00:00:00"
    // tail — slice and retry.
    const head = s.split(/[T ]/)[0];
    if (head !== s) return fmtDate(head);
    return esc(s);
  };
  const yesNo = (v) => {
    if (!v) return `<span class="cell-x">—</span>`;
    const s = String(v).trim().toLowerCase();
    if (s === "x" || s === "yes" || s === "✓" || s === "done") return `<span class="cell-done">✓</span>`;
    return esc(v);
  };
  tbody.innerHTML = filtered.map((r) => `
    <tr data-name="${esc(r.name)}">
      <td><span class="sheet-pill ${(r.sheet || '').replace(/ /g, '-')}">${esc(r.sheet)}</span></td>
      <td>${fmtDate(r.received)}</td>
      <td style="font-weight:600;">${esc(r.name)}</td>
      <td>${cell(r.carrier)}</td>
      <td style="font-family:monospace;font-size:11px;">${cell(r.claim)}</td>
      <td>${cell(r.type_of_loss)}</td>
      <td>${cell(r.lead)}</td>
      <td>${fmtDate(r.inspection)}</td>
      <td>${fmtDate(r.demo_start)}</td>
      <td>${yesNo(r.docusketch)}</td>
      <td>${yesNo(r.scope)}</td>
      <td>${yesNo(r.final_photos)}</td>
      <td>${fmtDate(r.closing)}</td>
      <td style="text-align:right;white-space:nowrap;"><button class="btn tracked-copy" data-name="${esc(r.name)}" title="Copy this row (tab-separated — pastes straight into Excel)" style="padding:2px 8px;font-size:12px;">📋</button> <button class="btn tracked-edit" data-name="${esc(r.name)}" title="Edit values / move to another sheet" style="padding:2px 8px;font-size:12px;">✎</button></td>
    </tr>`).join("");
  // 📋 Copy — the row as tab-separated text, which pastes straight into
  // Excel as cells rather than one blob. Values are the FORMATTED ones
  // on screen, so what lands matches what you were looking at.
  tbody.querySelectorAll(".tracked-copy").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();                      // don't open the Trello card
      const tr = b.closest("tr");
      if (!tr) return;
      const cells = Array.from(tr.querySelectorAll("td"))
        .slice(0, -1)                           // drop the actions column
        .map((td) => td.textContent.replace(/\s+/g, " ").trim())
        .map((t) => (t === "—" ? "" : t));      // an em-dash means empty
      const line = cells.join("\t");
      let ok = false;
      try {
        const r = await pywebview.api.set_clipboard(line);
        ok = !!(r && (r.ok || r === true));
      } catch (_) { ok = false; }
      if (!ok) {
        try { await navigator.clipboard.writeText(line); ok = true; }
        catch (_) { ok = false; }
      }
      setStatus(ok ? `📋 Copied ${b.dataset.name}` : "Copy failed",
                ok ? "ok" : "error");
    }));

  // ✎ Edit — open the per-row editor (stop the row's open-Trello click).
  tbody.querySelectorAll(".tracked-edit").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const row = trackedState.rows.find((x) => x.name === b.dataset.name);
      if (row) openEditTrackedRow(row);
    }));
  // Click row → open the Trello card tied to this row's name
  // (pinned id wins; falls back to fuzzy search via aliases).
  // Double-click → start a new snapshot form for that name.
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.title = "Click → open Trello card · Double-click → new snapshot · Right-click → Open in…";
    // Right-click → cross-tool "Open in…" (Audit / IUQ / Snapshot) +
    // Open Trello card. Snapshot excluded (we're already here).
    tr.addEventListener("contextmenu", (ev) => {
      const name = tr.dataset.name;
      if (!name || !window.emsOpenInMenu) return;
      window.emsOpenInMenu(ev, name, { exclude: ["snapshot"] });
    });
    tr.addEventListener("click", async () => {
      const name = tr.dataset.name;
      if (!name) return;
      const r = await pywebview.api.open_trello_for_tracked(name);
      if (!r?.ok) {
        setStatus(`No Trello card found for "${name}" — ${r?.error || "?"}`, "warn");
      } else {
        setStatus(`🔗 Opening Trello card for ${name}`, "ok");
      }
    });
    tr.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      const name = tr.dataset.name;
      if (name) startNew(name, "");
    });
  });
}

// ── ✎ Edit a tracked row (adjust cells / move to another sheet) ─────
const TRACKED_SHEETS = ["NEW LOSS", "Completed", "Incomplete", "Needs Attention"];
// {row key → Excel column} for the editable fields. Order = form order.
const TRACKED_EDIT_FIELDS = [
  { key: "name",           col: "Name",           label: "Name" },
  { key: "received",       col: "Date Received",  label: "Date Received" },
  { key: "carrier",        col: "Carrier",        label: "Carrier" },
  { key: "claim",          col: "Claim#",         label: "Claim #" },
  { key: "type_of_loss",   col: "Type of Loss",   label: "Type of Loss" },
  { key: "closing",        col: "Closing Date",   label: "Closing Date" },
  { key: "scheduled_ins",  col: "Scheduled Ins.", label: "Scheduled Ins." },
  { key: "lead",           col: "Lead",           label: "Lead" },
  { key: "inspection",     col: "Inspection",     label: "Inspection" },
  { key: "sketch",         col: "Sketch",         label: "Sketch" },
  { key: "docusketch",     col: "Docusketch ordered?", label: "Docusketch ordered?" },
  { key: "scope",          col: "Scope",          label: "Scope" },
  { key: "final_photos",   col: "Final Photos",   label: "Final Photos" },
  { key: "initial_photos", col: "Initial Photos", label: "Initial Photos" },
  { key: "demo_start",     col: "Demo Start",     label: "Demo Start" },
  { key: "demo_photos",    col: "Demo Photos",    label: "Demo Photos" },
  { key: "atp",            col: "ATP",            label: "ATP" },
  { key: "cif",            col: "CIF",            label: "CIF" },
  { key: "cer",            col: "CER",            label: "CER" },
  { key: "cos",            col: "COS",            label: "COS" },
  { key: "folder",         col: "Folder",         label: "Folder" },
  { key: "addl_docs",      col: "Add'l Docs",     label: "Add'l Docs" },
];

function openEditTrackedRow(row) {
  const opts = TRACKED_SHEETS.map((s) =>
    `<option value="${esc(s)}" ${s === row.sheet ? "selected" : ""}>${esc(s)}</option>`).join("");
  const grid = TRACKED_EDIT_FIELDS.map((f) => `
    <label style="display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--text-muted);">
      ${esc(f.label)}
      <input id="edit-f-${f.key}" class="search" type="text"
             value="${esc(row[f.key] || "")}" style="width:100%;font-size:13px;color:var(--text);" />
    </label>`).join("");
  const wrap = mkSnapModal({
    title: `✎ Edit — ${row.name || "(no name)"}`,
    width: 720,
    body: `
      <div style="display:flex;flex-direction:column;gap:14px;">
        <label style="display:flex;flex-direction:column;gap:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">
          Sheet (move to)
          <select id="edit-sheet" class="search" style="width:220px;font-size:13px;color:var(--text);">${opts}</select>
        </label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;">${grid}</div>
        <label style="display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--text-muted);">
          Comment
          <textarea id="edit-f-comment" rows="3" class="search" style="width:100%;font-size:13px;color:var(--text);resize:vertical;">${esc(row.comment || "")}</textarea>
        </label>
        <div id="edit-status" style="font-size:11px;color:var(--text-muted);min-height:14px;"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="edit-save">Save</button>
        </div>
      </div>`,
  });
  wrap.querySelector("#edit-save").addEventListener("click", async () => {
    const btn = wrap.querySelector("#edit-save");
    const st = wrap.querySelector("#edit-status");
    btn.disabled = true; btn.textContent = "Saving…";
    const fields = {};
    for (const f of TRACKED_EDIT_FIELDS) {
      const el = wrap.querySelector(`#edit-f-${f.key}`);
      if (el) fields[f.col] = el.value;
    }
    const ce = wrap.querySelector("#edit-f-comment");
    if (ce) fields["Comment"] = ce.value;
    const targetSheet = wrap.querySelector("#edit-sheet").value;
    // Move first (by the ORIGINAL name) so the row keeps its identity,
    // then write the field values — which may include a renamed Name.
    // update_tracked_row searches every sheet, so it still finds the
    // row in its new sheet.
    if (targetSheet && targetSheet !== row.sheet) {
      const mv = await pywebview.api.move_tracked_row(row.name, targetSheet, 0);
      if (!mv?.ok) {
        st.textContent = `Move failed: ${mv?.error || "?"}`;
        btn.disabled = false; btn.textContent = "Save"; return;
      }
    }
    const up = await pywebview.api.update_tracked_row(row.name, fields, 0);
    if (!up?.ok) {
      st.textContent = `Save failed: ${up?.error || "?"}`;
      btn.disabled = false; btn.textContent = "Save"; return;
    }
    closeSnapModal();
    const moved = targetSheet !== row.sheet ? ` · moved to ${targetSheet}` : "";
    setStatus(`✓ Saved ${fields["Name"] || row.name}${moved}`, "ok");
    await loadTrackedSnapshots();
  });
}

// ── 📝 Copy DocuSign request email (closeout) ───────────────────────
// Builds the customer email body with the property city auto-filled from
// the job's Trello card, copies it to the clipboard for pasting into
// DocuSign / Outlook.
async function copyDocusignEmail() {
  const insured = $("#f-insured").value.trim();
  const r = await pywebview.api.docusign_email(insured, state.cardId || "");
  if (!r?.ok) { setStatus(`DS email failed: ${r?.error || "?"}`, "error"); return; }
  const ok = await copyToClipboard(r.text);
  if (!ok) { setStatus("Couldn't copy — select the text manually", "warn"); return; }
  setStatus(r.city
    ? `📝 DocuSign email copied · city: ${r.city}`
    : "📝 DocuSign email copied · ⚠ city blank (no address on card — edit before sending)",
    "ok");
}

async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through to the textarea fallback */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

// ── Draft auto-save ────────────────────────────────────────────────
// Snapshot forms hold a lot of hand-entered work. Switching to another
// tool reloads this iframe and wiped it. Auto-save the in-progress form to
// localStorage on every edit; restore it when the panel re-loads so a
// "jump off and come back" no longer loses everything. Cleared when the
// snapshot is generated or the user discards it.
const _DRAFT_KEY = "snapshot_draft_v1";
let _draftTimer = null;

function _draftHasContent(d) {
  if (!d) return false;
  if ((d.insured || d.cause || d.comments || d.dol || d.first || d.carrier || "").trim()) {
    return true;
  }
  return [...(d.subs || []), ...(d.logs || [])]
    .some((r) => (r.date || r.activity || r.techs || "").trim());
}

function serializeSnapshotDraft() {
  return {
    insured:  $("#f-insured")?.value || "",
    carrier:  $("#f-carrier")?.value || "",
    dol:      $("#f-dol")?.value || "",
    first:    $("#f-first")?.value || "",
    cause:    $("#f-cause")?.value || "",
    comments: $("#f-comments")?.value || "",
    subs:     collectRows("subs"),
    logs:     collectRows("logs"),
    cardId:   state.cardId || "",
    ts:       Date.now(),
  };
}

function saveSnapshotDraft() {
  try {
    const d = serializeSnapshotDraft();
    if (_draftHasContent(d)) localStorage.setItem(_DRAFT_KEY, JSON.stringify(d));
    else localStorage.removeItem(_DRAFT_KEY);
  } catch (_) { /* storage unavailable — degrade silently */ }
}

function clearSnapshotDraft() {
  try { localStorage.removeItem(_DRAFT_KEY); } catch (_) { /* ignore */ }
  hideDraftBanner();
}

function loadSnapshotDraft() {
  try {
    const raw = localStorage.getItem(_DRAFT_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (d.ts && (Date.now() - d.ts) > 7 * 864e5) {   // expire after 7 days
      localStorage.removeItem(_DRAFT_KEY);
      return null;
    }
    return _draftHasContent(d) ? d : null;
  } catch (_) { return null; }
}

function restoreSnapshotDraft(d) {
  switchTo("gen");
  $("#f-insured").value = d.insured || "";
  $("#f-carrier").value = d.carrier || "";
  $("#f-dol").value     = d.dol || "";
  $("#f-first").value   = d.first || "";
  $("#f-cause").value   = d.cause || "";
  if ($("#f-comments")) $("#f-comments").value = d.comments || "";
  $("#subs-body").innerHTML = "";
  $("#logs-body").innerHTML = "";
  (d.subs || []).forEach((r) => addRow("subs", r));
  (d.logs || []).forEach((r) => addRow("logs", r));
  if (!$("#subs-body").children.length) addRow("subs", {});
  if (!$("#logs-body").children.length) addRow("logs", {});
  state.cardId = d.cardId || "";
  refreshSnapshotCommentsButton();
  showDraftBanner();
}

function showDraftBanner() {
  if (document.getElementById("draft-banner")) return;
  const sec = document.querySelector("#view-gen .col");
  if (!sec) return;
  const b = document.createElement("div");
  b.id = "draft-banner";
  b.style.cssText = "display:flex;align-items:center;gap:10px;background:var(--surface-2);border:1px solid var(--accent,#3b82f6);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;";
  b.innerHTML = `<span>↩ Restored your unsaved snapshot draft.</span>
    <span style="flex:1;"></span>
    <button class="btn" id="draft-discard">🗑 Discard</button>
    <button class="btn" id="draft-keep">Keep editing</button>`;
  sec.insertBefore(b, sec.firstChild);
  b.querySelector("#draft-discard").addEventListener("click", () => {
    clearSnapshotDraft();
    startNew();
  });
  b.querySelector("#draft-keep").addEventListener("click", hideDraftBanner);
}

function hideDraftBanner() {
  document.getElementById("draft-banner")?.remove();
}

async function startNew(client = "", cardId = "") {
  const requestId = ++state.openRequest;
  hideDraftBanner();
  switchTo("gen");
  // Reset form + hide post-actions panel
  ["insured", "carrier", "dol", "first", "cause"].forEach((id) =>
    $(`#f-${id}`).value = "");
  $("#subs-body").innerHTML = "";
  $("#logs-body").innerHTML = "";
  $("#gen-status").textContent = "";
  $("#gen-status").className = "";
  $("#post-actions").classList.add("hidden");
  $("#post-trello-btn").textContent =
    document.createTextNode("Attach PDF + post comment to Trello").textContent;
  state.lastPdfPath = null;
  state.lastClient = null;
  state.cardId = cardId || "";   // for the DocuSign-email city lookup
  refreshSnapshotCommentsButton();
  $("#f-insured").value = client || "";

  if (client) {
    // When we have a card_id (search result picked) use the full
    // Trello parser — pulls carrier/claim/DOL/first-visit/cause
    // from card desc + paged comments. Falls back to plain run-doc
    // prefill when the user typed a name without picking a card.
    setSnapshotFormLoading(true, cardId
      ? "Loading card details, comments, and Job Log…"
      : "Loading job details and Job Log…");
    let fill;
    try {
      fill = cardId
        ? await pywebview.api.prefill_from_trello_card(cardId, client)
        : await pywebview.api.prefill_for(client);
    } catch (ex) {
      if (requestId !== state.openRequest) return;
      setStatus(`Could not prefill this job: ${ex}. You can still complete it manually.`, "warn");
      fill = {insured:client, subs:[], logs:[]};
    }
    // A slower earlier click must never overwrite the job opened after it.
    if (requestId !== state.openRequest) return;
    fill = fill || {insured:client, subs:[], logs:[]};
    $("#f-insured").value = fill.insured || client;
    $("#f-carrier").value = fill.carrier
      || (fill.claim ? `${fill.carrier || ""} · ${fill.claim}`.replace(/^ · /, "") : "");
    $("#f-dol").value = fill.dol || "";
    $("#f-first").value = fill.first_visit || "";
    $("#f-cause").value = fill.cause || "";
    (fill.subs || []).forEach((r) => addRow("subs", r));
    (fill.logs || []).forEach((r) => addRow("logs", r));
    const bits = [];
    if (fill.carrier) bits.push("carrier");
    if (fill.claim)   bits.push("claim");
    if (fill.dol)     bits.push("DOL");
    if (fill.first_visit) bits.push("first visit");
    if (fill.cause)   bits.push("cause");
    if (fill.subs?.length) bits.push(`${fill.subs.length} subs`);
    if (fill.logs?.length) bits.push(`${fill.logs.length} log rows`);
    const pinNote = fill.auto_pinned
      ? ` · 📌 pinned card to ${fill.insured || client}`
      : "";
    setStatus(
      cardId && bits.length
        ? `📋 Parsed from Trello: ${bits.join(" · ")}${pinNote}`
        : `Pre-filled ${fill.logs?.length || 0} log rows from recent run-docs`,
      "ok");
    setSnapshotFormLoading(false);
  } else {
    setSnapshotFormLoading(false);
    $("#f-insured").focus();
  }

  // Ensure at least one empty row in each table so the user can start typing
  if (!$("#subs-body").children.length) addRow("subs", {});
  if (!$("#logs-body").children.length) addRow("logs", {});

  // Audit the job as soon as it loads. The audit is what tells you what
  // the snapshot is missing, so waiting for a button press meant the
  // form was filled in before anyone looked. Fire-and-forget: it paints
  // into its own subview and must not hold up the form.
  if (client && requestId === state.openRequest) {
    // Let the completed form paint before starting folder/audit work.
    setTimeout(() => {
      if (requestId === state.openRequest && state.view === "gen")
        runSnapshotAudit().catch(() => {});
    }, 250);
  }
  // Capture the (pre-filled) starting state so a switch-away before the
  // first keystroke still restores it. Blank forms save nothing.
  saveSnapshotDraft();
}

function setSnapshotFormLoading(active, label="") {
  const form = $("#snapshot-form-card");
  const banner = $("#snapshot-form-loading");
  if (!form || !banner) return;
  form.classList.toggle("is-loading", !!active);
  form.setAttribute("aria-busy", active ? "true" : "false");
  banner.classList.toggle("hidden", !active);
  const text = banner.querySelector("span");
  if (text && label) text.textContent = label;
}

// ── Tech roster ──────────────────────────────────────────────────
// The snapshot recognizes techs in Trello comments via the canonical
// roster (persistence.user_techs). We surface it here as (a) an
// autocomplete datalist on every Techs field and (b) a manage modal so
// new techs like "Uli" can be added without leaving the snapshot.
let _techRoster = { all: [], user: [] };

async function loadTechRoster() {
  try {
    const r = await pywebview.api.snapshot_techs();
    if (r && r.ok) {
      _techRoster = { all: r.all || [], user: r.user || [] };
      renderTechDatalist();
    }
  } catch { /* optional — fields still work as free text */ }
}

function renderTechDatalist() {
  const dl = $("#tech-options");
  if (!dl) return;
  dl.innerHTML = _techRoster.all
    .map((t) => `<option value="${esc(t)}"></option>`).join("");
}

function openTechsModal() {
  renderTechsList();
  $("#techs-modal-status").textContent = "";
  $("#techs-overlay").classList.remove("hidden");
  setTimeout(() => $("#tech-add-name")?.focus(), 30);
}

function closeTechsModal() {
  $("#techs-overlay").classList.add("hidden");
}

function renderTechsList() {
  const box = $("#techs-list");
  if (!box) return;
  const user = _techRoster.user || [];
  if (!user.length) {
    box.innerHTML = `<div class="muted" style="font-size:12px;padding:4px 0;">No techs on the list. Add one below.</div>`;
    return;
  }
  box.innerHTML = user.map((t) => `
    <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:var(--surface-2);border-radius:6px;">
      <span style="flex:1;">${esc(t.name)}${t.initials ? ` <span class="muted" style="font-size:11px;">(${esc(t.initials)})</span>` : ""}</span>
      <button class="btn" data-tech="${esc(t.name)}" title="Remove ${esc(t.name)}"
              style="padding:2px 8px;">✕</button>
    </div>`).join("");
  box.querySelectorAll("button[data-tech]").forEach((b) =>
    b.addEventListener("click", () => removeTech(b.dataset.tech)));
}

async function addTechFromModal() {
  const nameEl = $("#tech-add-name");
  const iniEl  = $("#tech-add-initials");
  const name = (nameEl.value || "").trim();
  const ini  = (iniEl.value || "").trim();
  if (!name) { setTechStatus("Type a name first.", true); return; }
  setTechStatus("Adding…", false);
  try {
    const r = await pywebview.api.add_snapshot_tech(name, ini);
    if (!r || !r.ok) {
      setTechStatus((r && r.error) || "Couldn't add tech.", true);
      return;
    }
    _techRoster = { all: r.all || [], user: r.user || [] };
    renderTechDatalist();
    renderTechsList();
    nameEl.value = "";
    iniEl.value = "";
    nameEl.focus();
    setTechStatus(`Added ${r.added}. Now recognized in Trello comments everywhere.`, false);
  } catch (ex) {
    setTechStatus("Couldn't add tech: " + ex, true);
  }
}

async function removeTech(name) {
  setTechStatus("Removing…", false);
  try {
    const r = await pywebview.api.remove_snapshot_tech(name);
    if (!r || !r.ok) {
      setTechStatus((r && r.error) || "Couldn't remove tech.", true);
      return;
    }
    _techRoster = { all: r.all || [], user: r.user || [] };
    renderTechDatalist();
    renderTechsList();
    setTechStatus(`Removed ${name}.`, false);
  } catch (ex) {
    setTechStatus("Couldn't remove tech: " + ex, true);
  }
}

function setTechStatus(msg, isErr) {
  const el = $("#techs-modal-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = isErr ? "var(--danger, #e5534b)" : "var(--muted, #8a94a6)";
}

function addRow(tableKey, prefill) {
  const tr = document.createElement("tr");
  tr.dataset.entryId = prefill.entry_id || "";
  tr.dataset.source = prefill.source || "";
  tr.dataset.sourceId = prefill.source_id || "";
  tr.dataset.trelloCommentId = prefill.trello_comment_id || "";
  // Drag is gated behind the ⠿ handle — only mousedown on the
  // col-drag cell sets draggable=true. Otherwise typing inside an
  // input would accidentally start a drag and steal text selection.
  tr.draggable = false;
  tr.innerHTML = `
    <td class="col-drag" title="Drag this handle to reorder" style="cursor:grab;user-select:none;">⋮⋮</td>
    <td><input type="text" data-k="date"     value="${esc(prefill.date || "")}"     placeholder="5/22/26" /></td>
    <td><input type="text" data-k="weekday"  value="${esc(prefill.weekday || "")}"  placeholder="Fri" /></td>
    <td><input type="text" data-k="activity" value="${esc(prefill.activity || "")}" placeholder="Demo / Monitor / etc." /></td>
    <td><input type="text" data-k="techs"    value="${esc(prefill.techs || "")}"    placeholder="ME, JG" list="tech-options" autocomplete="off" /></td>
    <td class="col-rm"><button class="rm-btn" title="Remove row">✕</button></td>`;
  $(`#${tableKey}-body`).appendChild(tr);
  tr.querySelector(".rm-btn").addEventListener("click", () => tr.remove());
  // Only the handle cell turns the row into a drag source. mousedown
  // arms it, dragend disarms — so clicks/typing elsewhere never
  // trigger a drag.
  const handle = tr.querySelector(".col-drag");
  handle.addEventListener("mousedown", () => { tr.draggable = true; });
  handle.addEventListener("mouseup",   () => { tr.draggable = false; });
  // Mouseleave (when the cursor exits the handle without dragging)
  // and dragend both clean up — keeps subsequent input clicks safe.
  handle.addEventListener("mouseleave", (e) => {
    // Only clear if the user RELEASED the button outside the handle.
    if (e.buttons === 0) tr.draggable = false;
  });
  tr.addEventListener("dragend", () => { tr.draggable = false; });
  attachDragHandlers(tr, tableKey);
  // Auto-fill the weekday column whenever the date column parses.
  // Mirrors Tk snapshot's _on_date_changed: type "5/27/26" → "Wed"
  // shows up next door without the user touching it. Won't overwrite
  // a weekday the user has manually typed (only fills when blank or
  // when the cell was previously empty AND the new date resolves).
  const dateIn = tr.querySelector('[data-k="date"]');
  const wkIn   = tr.querySelector('[data-k="weekday"]');
  if (dateIn && wkIn) {
    let lastAuto = wkIn.value; // tracks what *we* set so we can refresh
    dateIn.addEventListener("input", () => {
      const wk = parseDateToWeekday(dateIn.value);
      if (!wk) return;
      // Only auto-fill when blank, or when the field still matches
      // what we previously set (so re-typing the date updates it,
      // but a manual override sticks).
      if (!wkIn.value || wkIn.value === lastAuto) {
        wkIn.value = wk;
        lastAuto = wk;
      }
    });
  }
}

// "5/27/26" / "05/27/2026" / "2026-05-27" → "Wed".
// Returns "" when the input doesn't yet look like a complete date —
// we intentionally bail on partial input so the cell stays empty
// until the user finishes typing.
function parseDateToWeekday(raw) {
  if (!raw) return "";
  const s = raw.trim();
  let y, m, d;
  let mt = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/);
  if (mt) {
    m = +mt[1]; d = +mt[2]; y = +mt[3];
    if (y < 100) y += 2000;
  } else {
    mt = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (mt) { y = +mt[1]; m = +mt[2]; d = +mt[3]; }
    else return "";
  }
  if (m < 1 || m > 12 || d < 1 || d > 31) return "";
  const dt = new Date(y, m - 1, d);
  if (isNaN(dt.getTime()) || dt.getMonth() !== m - 1) return "";
  // Full weekday name to match Tk's get_weekday() (uses %A).
  // snapshot_gui.py:60 returns "Wednesday", not "Wed".
  return ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"][dt.getDay()];
}

// ── Drag-to-reorder rows (subs + logs tables) ────────────────────
// Native HTML5 drag/drop. Drop target gets a green top-border via
// CSS so the user sees exactly where the row will land.
let _dragSrc = null;
function attachDragHandlers(tr, tableKey) {
  tr.addEventListener("dragstart", (e) => {
    _dragSrc = tr;
    tr.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    // Required by Firefox; the actual payload doesn't matter since
    // we use the _dragSrc closure.
    try { e.dataTransfer.setData("text/plain", "row"); } catch (_) {}
  });
  tr.addEventListener("dragend", () => {
    tr.classList.remove("dragging");
    document.querySelectorAll(".drop-target, .drop-target-below")
      .forEach((r) => r.classList.remove("drop-target", "drop-target-below"));
    _dragSrc = null;
  });
  tr.addEventListener("dragover", (e) => {
    if (!_dragSrc || _dragSrc === tr) return;
    // Only allow drops between rows in the same tbody
    if (_dragSrc.parentNode !== tr.parentNode) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    // Decide above/below based on cursor Y inside the row
    const rect = tr.getBoundingClientRect();
    const below = (e.clientY - rect.top) > rect.height / 2;
    tr.parentNode.querySelectorAll(".drop-target, .drop-target-below")
      .forEach((r) => r.classList.remove("drop-target", "drop-target-below"));
    tr.classList.add(below ? "drop-target-below" : "drop-target");
  });
  tr.addEventListener("dragleave", () => {
    tr.classList.remove("drop-target", "drop-target-below");
  });
  tr.addEventListener("drop", (e) => {
    if (!_dragSrc || _dragSrc === tr) return;
    if (_dragSrc.parentNode !== tr.parentNode) return;
    e.preventDefault();
    const rect = tr.getBoundingClientRect();
    const below = (e.clientY - rect.top) > rect.height / 2;
    if (below) tr.parentNode.insertBefore(_dragSrc, tr.nextSibling);
    else       tr.parentNode.insertBefore(_dragSrc, tr);
    tr.classList.remove("drop-target", "drop-target-below");
  });
}

function collectRows(tableKey) {
  return Array.from($(`#${tableKey}-body`).querySelectorAll("tr")).map((tr) => {
    const out = {};
    tr.querySelectorAll("input").forEach((i) => out[i.dataset.k] = i.value);
    if (tableKey === "logs") {
      out.entry_id = tr.dataset.entryId || "";
      out.source = tr.dataset.source || "";
      out.source_id = tr.dataset.sourceId || "";
      out.trello_comment_id = tr.dataset.trelloCommentId || "";
    }
    return out;
  }).filter((r) => r.date || r.activity || r.techs);  // skip blank rows
}

function applySyncedLogRows(rows) {
  const trs = Array.from($("#logs-body").querySelectorAll("tr"));
  (rows || []).forEach((row, index) => {
    const tr = trs[index];
    if (!tr) return;
    tr.dataset.entryId = row.entry_id || tr.dataset.entryId || "";
    tr.dataset.source = row.source || tr.dataset.source || "";
    tr.dataset.sourceId = row.source_id || tr.dataset.sourceId || "";
    tr.dataset.trelloCommentId = row.trello_comment_id || tr.dataset.trelloCommentId || "";
  });
}

async function syncSnapshotJobLog() {
  const client = $("#f-insured")?.value?.trim() || "";
  if (!client) return;
  const rows = collectRows("logs");
  if (!rows.length) return;
  try {
    const res = await pywebview.api.sync_snapshot_job_log(client, rows);
    applySyncedLogRows(res?.rows || []);
    const saveLabel = res?.ok
      ? (res.saved ? "Saved" : (res.skipped ? "Finish date + activity to save" : ""))
      : "Sync pending";
    setJobLogSyncState(saveLabel, res?.ok ? "ok" : "warn");
    if (!res?.ok && res?.error) setStatus(`Snapshot saved locally · Job Log: ${res.error}`, "warn");
  } catch (ex) {
    setJobLogSyncState("Sync pending", "warn");
    setStatus(`Snapshot saved locally · Job Log sync pending: ${ex}`, "warn");
  }
}

function setJobLogSyncState(text, kind="") {
  const el = $("#job-log-sync-state");
  if (!el) return;
  el.textContent = text || "";
  el.className = `inline-save-state ${kind}`;
}

async function generate() {
  if ($("#gen-go").disabled) return;
  let insured = $("#f-insured").value.trim();
  if (!insured) {
    $("#gen-status").textContent = "Insured / job name is required";
    $("#gen-status").className = "error";
    return;
  }
  // Multi-unit gate — Tk parity. Check if the typed insured is
  // really a multi-unit umbrella (Avila Apartments, etc.). When it
  // is, surface a picker letting the user choose: roll up the
  // property or snapshot one specific unit.
  try {
    const mu = await pywebview.api.check_multi_unit(insured);
    if (mu?.multi_unit) {
      const picked = await openMultiUnitPicker(mu);
      if (picked === null) return;           // user cancelled
      if (picked && picked.insured) {
        insured = picked.insured;
        $("#f-insured").value = picked.insured;   // rewrite for clarity
        // Pin the chosen unit's (or umbrella's) folder so the audit +
        // snapshot resolve THIS exact folder, not a stale/parent one.
        if (picked.path) {
          try { await pywebview.api.pin_folder(picked.insured, picked.path); }
          catch (_) { /* non-fatal — generate can still proceed */ }
        }
      }
    }
  } catch (_) { /* fall through — degrade to single-unit generate */ }
  const payload = {
    insured,
    carrier:     $("#f-carrier").value,
    dol:         $("#f-dol").value,
    first_visit: $("#f-first").value,
    cause:       $("#f-cause").value,
    comments:    $("#f-comments")?.value || "",
    subs: collectRows("subs"),
    logs: collectRows("logs"),
  };
  const btn = $("#gen-go");
  btn.disabled = true; btn.textContent = "Creating PDF…";
  $("#snapshot-form-card")?.setAttribute("aria-busy", "true");
  $("#gen-status").textContent = "Writing PDF…";
  $("#gen-status").className = "";
  try {
    const res = await pywebview.api.generate(payload);
    if (!res?.ok) {
      $("#gen-status").textContent = "Failed: " + (res?.error || "?");
      $("#gen-status").className = "error";
      return;
    }
    const revisionNote = res.revision_saved
      ? ` · revision ${res.revision} saved`
      : ` · PDF saved, but revision history failed: ${esc(res.revision_error || "unknown error")}`;
    $("#gen-status").innerHTML =
      `✓ Saved to <code>${esc(res.path)}</code> · ${res.rows_logs} log rows, ${res.rows_subs} subs${revisionNote}`;
    $("#gen-status").className = res.revision_saved ? "ok" : "warn";
    state.lastPdfPath = res.path;
    state.lastClient = insured;
    applySyncedLogRows(res.synced_logs || []);
    if (!res.job_log_synced && res.job_log_error) {
      setStatus(`PDF saved · Job Log sync pending: ${res.job_log_error}`, "warn");
    }
    // Snapshot generated — the draft is no longer "unsaved work".
    clearSnapshotDraft();
    // Open the PDF immediately so the user can review
    pywebview.api.open_pdf(res.path);
    // Refresh the list view's recent PDFs so it'll be there
    await loadList();
    // Reveal the after-generate action panel — post to Trello,
    // mark drafted, open PDF again.
    $("#post-actions").classList.remove("hidden");
  } catch (ex) {
    $("#gen-status").textContent = "Error: " + ex;
    $("#gen-status").className = "error";
  } finally {
    btn.disabled = false; btn.textContent = "📸 Generate PDF";
    $("#snapshot-form-card")?.setAttribute("aria-busy", "false");
  }
}

async function postToTrello() {
  if (!state.lastPdfPath || !state.lastClient) return;
  const btn = $("#post-trello-btn");
  btn.disabled = true; btn.textContent = "Posting…";
  // Build a missing-items list from current form — anything blank in
  // subs/logs that user marked as "missing" via the dedicated UI.
  // For now we just send no list — backend's generic message fires.
  const res = await pywebview.api.post_snapshot_to_trello(
    state.lastClient, state.lastPdfPath, []);
  btn.disabled = false;
  if (!res?.ok) {
    const completed = [res?.attached && "PDF attached", res?.posted && "comment posted"]
      .filter(Boolean).join("; ");
    const detail = res?.error || "Trello did not confirm the upload";
    setStatus(`Trello post incomplete: ${detail}${completed ? ` (${completed})` : ""}`, "error");
    btn.textContent = "Attach PDF + post comment to Trello";
    return;
  }
  const bits = [];
  if (res.attached) bits.push("PDF attached");
  if (res.posted)   bits.push("comment posted");
  btn.textContent = "✓ " + bits.join(" + ");
  setStatus("✓ Posted to Trello", "ok");
}

async function openSnapshotHistory() {
  const client = state.lastClient || $("#f-insured")?.value.trim();
  if (!client) { setStatus("Choose a job first", "warn"); return; }
  const wrap = mkSnapModal({
    title: "Snapshot history — " + client,
    body: '<div id="snapshot-history-body" class="muted">Loading revisions…</div>',
  });
  const body = wrap.querySelector("#snapshot-history-body");
  let res;
  try { res = await pywebview.api.snapshot_history(client, 100); }
  catch (ex) { res = { ok: false, error: String(ex) }; }
  if (!res?.ok) {
    body.textContent = "History unavailable: " + (res?.error || "?"); return;
  }
  if (!(res.revisions || []).length) {
    body.textContent = "No saved revisions for this job yet."; return;
  }
  body.className = "snapshot-history-list";
  body.innerHTML = res.revisions.map(r => `
    <details class="snapshot-history-row">
      <summary><b>Revision ${Number(r.revision || 0)}</b><span>${esc(r.created_at || "")}</span></summary>
      <pre>${esc(r.rendered_text || "No rendered summary")}</pre>
      ${r.pdf_path ? `<div class="muted">PDF: ${esc(r.pdf_path)}</div>` : ""}
    </details>`).join("");
}

// ── Inline audit subview (P0) ──────────────────────────────────
// Renders the same per-row UI the Audit panel does — chips, action
// buttons, right-click menu. Lets the user spot-check the job and
// take every audit action (open OD, import SP, pin folder, flag,
// Docusketch, post comment, re-audit) without leaving the snapshot.
async function runSnapshotAudit() {
  const client = $("#f-insured").value.trim();
  if (!client) {
    setStatus("Insured name required", "warn");
    return;
  }
  const sub = $("#audit-subview");
  const summary = $("#audit-summary");
  const result = $("#audit-result");
  sub.classList.remove("hidden");
  summary.textContent = "Running audit…";
  result.innerHTML = "";

  const res = await pywebview.api.audit_current(client);
  if (!res?.ok) {
    summary.textContent = "Audit failed: " + (res?.error || "?");
    summary.style.color = "var(--red)";
    return;
  }
  renderSnapshotAuditRow(res.row);
}

// Context injected into the shared web_shared/audit_detail.js renderer so
// the Snapshot audit card renders from the SAME source as the Audit tool
// (can't drift). Maps to snapshot's own modals + re-audit + helpers.
function snapshotAuditCtx() {
  return {
    helpers: { escapeHtml: esc, escapeAttr: esc, titleCase, copyText, setStatus },
    modals: {
      openFindFolder: openSnapshotFindFolder,
      openSpImport: openSnapshotSpImport,
      openJobImport: openSnapshotWcImport,
      openScope: openScopeModal,
      openDayUnits: openSnapDayUnits,
      openPin: openSnapshotPinCard,
      openComment: openSnapshotCommentModal,
      openMatchDiag: openSnapshotMatchDiag,
      openCloseout: openCloseoutModal,
      showClaimFolders: showSnapClaimFolders,
    },
    rerender: (r) => renderSnapshotAuditRow(r || state.auditRow),
    reauditAndRerender: () => runSnapshotAudit(),
    attachTrelloHover: (btn, cardId) => {
      if (window.attachTrelloHover) window.attachTrelloHover(btn, cardId);
    },
    showCtxMenu: (ev, r) => showSnapshotAuditCtxMenu(ev, r),
  };
}

function renderSnapshotAuditRow(row) {
  const summary = $("#audit-summary");
  const result = $("#audit-result");
  state.auditRow = row;
  if (row.flagged) {
    summary.textContent = `🚩 ${row.total_missing} items missing`;
    summary.style.color = "var(--red)";
  } else if (!row.found) {
    summary.textContent = "⚠ Folder not found";
    summary.style.color = "var(--amber)";
  } else {
    summary.textContent = "✓ All clean";
    summary.style.color = "var(--green)";
  }
  // Render + wire through the shared module — identical to the Audit tool.
  const ctx = snapshotAuditCtx();
  result.innerHTML = window.AuditDetail.buildDetailBodyHTML(row, ctx);
  window.AuditDetail.wireDetail(result, row, ctx);
}

async function onAuditAction(act, row) {
  switch (act) {
    case "open-folder":
      if (row.path) pywebview.api.open_folder(row.path); break;
    case "copy-name": {
      const ok = await copyText(row.client || "");
      setStatus(ok ? `📋 Copied: ${row.client}` : "Couldn't copy",
                ok ? "ok" : "error");
      break;
    }
    case "copy-path": {
      if (!row.path) { setStatus("No folder path for this job", "warn"); break; }
      const ok = await copyText(row.path);
      setStatus(ok ? `📋 Copied path: ${row.path}` : "Couldn't copy",
                ok ? "ok" : "error");
      break;
    }
    case "open-trello":
      if (row.trello_card_id) pywebview.api.open_trello_card(row.trello_card_id); break;
    case "open-xa": {
      const ok = await pywebview.api.open_xa_link(row.client, row.trello_card_id || "");
      if (!ok) setStatus("No XactAnalysis link on this card yet — add an 'EMS Xactanalysis Link' to the Trello card.", "warn");
      break;
    }
    case "open-companycam": {
      const ok = await pywebview.api.open_companycam_link(row.client);
      if (!ok) setStatus("No CompanyCam link on this card yet — add a 'CompanyCam Link' to the Trello card.", "warn");
      break;
    }
    case "sp-import":
      openSnapshotSpImport(row); break;
    case "wc-import":
      openSnapshotWcImport(row); break;
    case "scope":
      openScopeModal(); break;
    case "attachments":
      window.openTrelloAttachmentsModal({
        cardId: row.trello_card_id, client: row.client
      });
      break;
    case "find-folder":
      openSnapshotFindFolder(row); break;
    case "pin-card":
      openSnapshotPinCard(row); break;
    case "comment":
      openSnapshotCommentModal(row); break;
    case "docusketch":
      if (!confirm(`Post Docusketch request comment on ${row.client}'s Trello card?`)) return;
      const r = await pywebview.api.request_docusketch(row.client, row.trello_card_id || "");
      if (!r?.ok) { setStatus(`Docusketch request failed: ${r?.error || "?"}`, "error"); return; }
      setStatus(r.posted ? "📐 Docusketch request posted" : "📐 Recorded — post manually", "ok");
      break;
    case "match-diag":
      openSnapshotMatchDiag(row); break;
    case "reaudit":
      await runSnapshotAudit(); break;
    case "commercial": {
      const cur = !!row.is_commercial;
      const res = await pywebview.api.set_commercial(row.client, !cur);
      if (!res?.ok) { setStatus(`Toggle failed: ${res?.error || "?"}`, "error"); return; }
      await runSnapshotAudit();
      setStatus(res.on ? "🏢 Marked commercial" : "Unmarked commercial", "ok");
      break;
    }
    // ── Per-client memory items (mirror audit/IUQ) ─────────────
    case "aliases":
      openSnapshotSearchAliases(row); break;
    case "property":
      openSnapshotAddToProperty(row); break;
    case "clear-folder": {
      if (!confirm(`Clear the sticky folder pin for ${row.client}?`)) return;
      const r = await pywebview.api.clear_folder_path(row.client);
      setStatus(r?.ok ? `🧹 Cleared folder pin` : `Failed: ${r?.error || "?"}`,
                r?.ok ? "ok" : "error");
      if (r?.ok) await runSnapshotAudit();
      break;
    }
    case "clear-commercial": {
      if (!confirm(`Un-mark ${row.client} as Commercial?`)) return;
      const r = await pywebview.api.set_commercial(row.client, false);
      setStatus(r?.ok ? `🏢 ${row.client} no longer Commercial` : `Failed: ${r?.error || "?"}`,
                r?.ok ? "ok" : "error");
      if (r?.ok) await runSnapshotAudit();
      break;
    }
    case "claim-folders": {
      const r = await pywebview.api.claim_folders(row.path || "");
      const folders = (r && r.folders) || [];
      if (!folders.length) {
        setStatus("No past claim / date folders in this job's directory", "warn");
        break;
      }
      showSnapClaimFolders(row, folders);
      break;
    }
    case "copy-claim": {
      const res = await pywebview.api.get_claim_number(row.client);
      if (res?.ok && res.claim) {
        const ok = await copyText(res.claim);
        setStatus(ok ? `📋 Copied claim #: ${res.claim}` : "Couldn't copy",
                  ok ? "ok" : "error");
      } else { setStatus(res?.error || "No claim # found", "warn"); }
      break;
    }
    case "copy-issues": {
      const items = [...(row.form_issues || []), ...(row.photo_issues || [])];
      if (!items.length) { setStatus("No missing items — job is clean", "ok"); break; }
      const ok = await copyText(items.map((x) => `• ${x}`).join("\n"));
      setStatus(ok ? `📋 Copied ${items.length} issue${items.length !== 1 ? "s" : ""}`
                   : "Couldn't copy", ok ? "ok" : "error");
      break;
    }
    case "day-units":
      openSnapDayUnits(row); break;
    case "property-structure":
      openSnapPropertyStructure(row); break;
    case "paperwork":
      openSnapPaperwork(row); break;
    case "closeout":
      openCloseoutModal(row); break;
    case "reset-memory": {
      if (!confirm(`Wipe every sticky pin + flag for ${row.client}?\n` +
                   `Clears: folder pin, Trello pins, Commercial flag, aliases.`)) return;
      const r = await pywebview.api.reset_client_memory(row.client);
      setStatus(r?.ok ? `♻ Reset: ${(r.cleared || []).join(", ")}` : `Failed: ${r?.error || "?"}`,
                r?.ok ? "ok" : "error");
      if (r?.ok) await runSnapshotAudit();
      break;
    }
  }
}

// ── Search aliases + property modals (snapshot parity) ──────────
async function openSnapshotSearchAliases(row) {
  const current = await pywebview.api.get_search_aliases(row.client) || [];
  const wrap = mkSnapModal({
    title: "🏷 Search aliases for " + row.client,
    body: `<div class="muted" style="font-size:11px;margin-bottom:6px;">One alias per line.</div>
      <textarea id="al-text" rows="8" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;">${esc(current.join("\n"))}</textarea>
      <div class="modal-footer" style="display:flex;gap:10px;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="al-save">💾 Save</button>
      </div>`,
  });
  wrap.querySelector("#al-save").addEventListener("click", async () => {
    const lines = wrap.querySelector("#al-text").value
      .split("\n").map((s) => s.trim()).filter(Boolean);
    const res = await pywebview.api.set_search_aliases(row.client, lines);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    wrap.remove();
    setStatus(`🏷 Saved ${lines.length} alias${lines.length !== 1 ? "es" : ""}`, "ok");
  });
  wrap.querySelector("#al-text").focus();
}

async function openSnapshotAddToProperty(row) {
  const folderBasename = (row.folder || "").trim();
  if (!folderBasename) {
    setStatus(`Pin a folder for ${row.client} first`, "warn");
    return;
  }
  const [groupsR, currentGroup] = await Promise.all([
    pywebview.api.list_property_groups(),
    pywebview.api.find_property_for_folder(folderBasename),
  ]);
  const existing = (groupsR?.groups || []);
  const wrap = mkSnapModal({
    title: currentGroup ? `🏢 Property — ${row.client}` : `🏢 Add ${row.client} to property`,
    body: `
      ${currentGroup ? `
        <button class="btn" id="pg-remove" style="background:var(--red);color:#FFF;border-color:var(--red);">
          ✕ Remove from "${esc(currentGroup)}"
        </button>
        <hr style="border:none;border-top:1px solid var(--border);margin:14px 0;" />
      ` : ""}
      ${existing.length ? `
        <div class="muted" style="font-size:11px;margin-bottom:6px;">Existing</div>
        <div style="display:flex;flex-direction:column;gap:4px;max-height:200px;overflow-y:auto;margin-bottom:14px;">
          ${existing.map((g) => `
            <button class="btn pg-pick" data-name="${esc(g.name)}" style="text-align:left;justify-content:flex-start;">
              ${esc(g.name)} <span class="muted" style="font-size:10px;">(${g.folders.length})</span>
            </button>`).join("")}
        </div>` : ""}
      <div class="muted" style="font-size:11px;margin-bottom:6px;">+ New property</div>
      <div style="display:flex;gap:6px;">
        <input id="pg-new" class="search" type="text" placeholder="Property name" style="flex:1;" />
        <button class="btn btn-primary" id="pg-create">Create + add</button>
      </div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:14px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  wrap.querySelector("#pg-remove")?.addEventListener("click", async () => {
    const res = await pywebview.api.remove_folder_from_property_group(currentGroup, folderBasename);
    if (!res?.ok) { setStatus(`Failed: ${res?.error || "?"}`, "error"); return; }
    wrap.remove();
    setStatus(`Removed from "${currentGroup}"`, "ok");
  });
  wrap.querySelectorAll(".pg-pick").forEach((b) =>
    b.addEventListener("click", async () => {
      const res = await pywebview.api.add_folder_to_property_group(b.dataset.name, folderBasename);
      if (!res?.ok) { setStatus(`Failed: ${res?.error || "?"}`, "error"); return; }
      wrap.remove();
      setStatus(`🏢 Added to "${b.dataset.name}"`, "ok");
    }));
  wrap.querySelector("#pg-create")?.addEventListener("click", async () => {
    const name = wrap.querySelector("#pg-new").value.trim();
    if (!name) return;
    const res = await pywebview.api.create_property_group(name, folderBasename);
    if (!res?.ok) { setStatus(`Failed: ${res?.error || "?"}`, "error"); return; }
    wrap.remove();
    setStatus(`🏢 Created "${name}"`, "ok");
  });
  wrap.querySelector("#pg-new")?.focus();
}

// ── Ported from Audit for parity: Past claims / Day-units /
//    Property structure / Paperwork-via-Teams. Same backend logic
//    (audit_web via the _aw() proxies), adapted to snapshot's
//    mkSnapModal + esc idiom + runSnapshotAudit refresh. ──────────
function showSnapClaimFolders(row, folders) {
  const rowsHtml = folders.map((f) => `
    <button class="claim-row" data-path="${esc(f.path)}"
      style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:10px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font:inherit;color:var(--text);margin-bottom:6px;">
      <span style="font-size:15px;">${f.kind === "date" ? "📅" : "🗂"}</span>
      <span style="flex:1;">${esc(f.name)}</span>
      ${f.is_current ? '<span style="font-size:10px;color:var(--green);font-weight:700;letter-spacing:.04em;">CURRENT</span>' : ""}
      <span class="muted" style="font-size:11px;">Open ↗</span>
    </button>`).join("");
  const wrap = mkSnapModal({
    title: `🗂 Past claims · ${row.client}`,
    body: `
      <div class="muted" style="font-size:11px;margin-bottom:10px;">${folders.length} claim/date folder${folders.length === 1 ? "" : "s"} in this job's directory</div>
      <div style="max-height:60vh;overflow-y:auto;">${rowsHtml}</div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  wrap.querySelectorAll(".claim-row").forEach((b) =>
    b.addEventListener("click", async () => {
      const ok = await pywebview.api.open_folder(b.dataset.path);
      setStatus(ok ? `📁 Opened ${b.dataset.path}` : "Couldn't open folder", ok ? "ok" : "warn");
    }));
}

async function openSnapDayUnits(row) {
  const res = await pywebview.api.list_day_units(row.client);
  if (!res?.ok) { setStatus(`Day-units unavailable: ${res?.error || "?"}`, "warn"); return; }
  const units = res.units || [];
  if (!units.length) { setStatus(`No unit subfolders under ${row.folder || "this folder"} — single-unit job`, "warn"); return; }
  const wrap = mkSnapModal({
    title: "🏠 Pick units for " + row.client,
    body: `
      <div class="muted" style="font-size:11px;margin-bottom:8px;">Check every unit this row covers today. Multi-pin replicates the row — one card per unit.</div>
      <div class="muted" style="font-size:11px;margin-bottom:8px;">Umbrella: <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">${esc(res.umbrella || "")}</code></div>
      <div style="display:flex;flex-direction:column;gap:4px;max-height:340px;overflow-y:auto;">
        ${units.map((u) => `
          <label class="du-row" style="display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);cursor:pointer;">
            <input type="checkbox" class="du-cb" data-path="${esc(u.path)}" ${u.pinned ? "checked" : ""} />
            <div style="flex:1;min-width:0;">
              <div style="font-weight:600;font-size:13px;">${esc(u.name)}</div>
              <div class="muted" style="font-size:10px;font-family:monospace;word-break:break-all;">${esc(u.path)}</div>
            </div>
          </label>`).join("")}
      </div>
      <div class="modal-footer" style="display:flex;gap:8px;align-items:center;margin-top:12px;">
        <button class="btn" id="du-clear">✕ Clear all</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="du-save">💾 Apply</button>
      </div>`,
  });
  async function applyAndReaudit(paths) {
    const save = await pywebview.api.set_day_units(row.client, paths);
    if (!save?.ok) { setStatus(`Save failed: ${save?.error || "?"}`, "error"); return; }
    closeSnapModal();
    setStatus(paths.length ? `🏠 Pinned ${paths.length} unit${paths.length !== 1 ? "s" : ""} for today` : `🏠 Cleared day-pins for ${row.client}`, "ok");
    await runSnapshotAudit();
  }
  wrap.querySelector("#du-save").addEventListener("click", async () => {
    const picked = [...wrap.querySelectorAll(".du-cb:checked")].map((cb) => cb.dataset.path);
    await applyAndReaudit(picked);
  });
  wrap.querySelector("#du-clear").addEventListener("click", async () => {
    if (!confirm(`Clear all day-pins for ${row.client}?`)) return;
    await applyAndReaudit([]);
  });
}

async function openSnapPropertyStructure(row) {
  const res = await pywebview.api.property_structure(row.client);
  if (!res?.ok) {
    setStatus(`Property structure unavailable: ${res?.error || "?"} — pin the umbrella folder first via 🔎 Find folder`, "warn");
    return;
  }
  const s = res.settings || {};
  let units = res.units || [];
  const wrap = mkSnapModal({ title: "🏢 Property structure — " + row.client, width: 720, body: `<div id="ps-body"></div>` });
  const bodyEl = wrap.querySelector("#ps-body");
  const renderTree = () => `
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:10px;">
      <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;">Umbrella folder</div>
      <div style="font-family:monospace;font-size:12px;word-break:break-all;color:var(--text);margin-top:2px;">${esc(res.umbrella)}</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${res.unit_count} unit subfolder${res.unit_count === 1 ? "" : "s"} detected</div>
      <button class="btn" id="ps-open-umbrella" style="margin-top:6px;font-size:11px;padding:4px 8px;">📁 Open umbrella</button>
      <button class="btn" id="ps-add-unit" style="margin-top:6px;margin-left:4px;font-size:11px;padding:4px 8px;">➕ Create unit</button>
    </div>
    <div style="max-height:320px;overflow:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);">
      ${units.length === 0 ? `<div class="muted" style="padding:14px;">No unit subfolders found — this property may not be multi-unit.</div>`
        : units.map((u) => `
          <div class="ps-unit-row" style="display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);">
            <div>
              <div style="display:flex;gap:8px;align-items:center;">
                <span style="font-weight:600;color:var(--text);">${esc(u.name)}</span>
                ${u.pinned_today ? `<span style="background:var(--green);color:#FFF;font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;">PINNED TODAY</span>` : ""}
                ${!u.pics_exists ? `<span style="background:rgba(245,166,35,.15);color:var(--amber);font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;">NO PICS</span>` : ""}
              </div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">📷 ${u.photo_count} photo${u.photo_count === 1 ? "" : "s"}${u.last_modified ? ` · Last activity ${u.last_modified}` : ""}</div>
            </div>
            <div style="display:flex;gap:4px;">
              <button class="btn ps-pin" data-path="${esc(u.path)}" data-pinned="${u.pinned_today}" style="font-size:11px;padding:4px 8px;">${u.pinned_today ? "✕ Unpin today" : "📌 Pin today"}</button>
              <button class="btn ps-open" data-path="${esc(u.path)}" style="font-size:11px;padding:4px 8px;">📁 Open</button>
            </div>
          </div>`).join("")}
    </div>
    <details style="margin-top:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;">
      <summary style="cursor:pointer;font-weight:600;font-size:12px;color:var(--text);">⚙ Property settings</summary>
      <div style="margin-top:10px;display:flex;flex-direction:column;gap:10px;">
        <label style="display:flex;gap:8px;align-items:center;font-size:12px;cursor:pointer;">
          <input type="checkbox" id="ps-commercial" ${s.is_commercial ? "checked" : ""} />
          <span>Mark as commercial property</span>
        </label>
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">Search aliases</div>
          <textarea id="ps-aliases" rows="4" style="width:100%;font-family:monospace;font-size:12px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:8px;resize:vertical;">${esc((s.aliases || []).join("\n"))}</textarea>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="btn btn-primary" id="ps-save-settings">💾 Save settings</button>
        </div>
      </div>
    </details>
    <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:12px;">
      <button class="btn modal-close">Close</button>
    </div>`;
  function wire() {
    bodyEl.querySelector(".modal-close")?.addEventListener("click", closeSnapModal);
    bodyEl.querySelector("#ps-open-umbrella")?.addEventListener("click", () => pywebview.api.open_folder(res.umbrella));
    // ➕ Create unit — infer the sibling naming style, scaffold, no files
    // (Snapshot has no import staged here). Refresh the modal after.
    bodyEl.querySelector("#ps-add-unit")?.addEventListener("click", () => {
      if (!window.UmbrellaGroup) return;
      const nextNum = (units || []).reduce(
        (m, u) => Math.max(m, parseInt((u.name.match(/\d+/) || [0])[0], 10) || 0), 0) + 1;
      const sample = (units || []).find((u) => /\d/.test(u.name || ""));
      const prefixMatch = sample && (sample.name.match(/^\s*(unit|apt|apartment|suite|ste)/i));
      const suggested = prefixMatch ? `${prefixMatch[1]} ${nextNum}` : `Unit ${nextNum}`;
      window.UmbrellaGroup.openCreateChildModal({
        api: pywebview.api,
        parentPath: res.umbrella,
        parentName: row.client,
        suggestedName: suggested,
        files: [],
        onDone: (r) => {
          if (r && r.ok) {
            setStatus(`✓ Created ${r.path.split(/[\\/]/).pop()}`, "ok");
            closeSnapModal();
            openSnapPropertyStructure(row);   // reopen with the new unit
          } else {
            setStatus(`Create failed: ${(r && r.error) || "?"}`, "error");
          }
        },
      });
    });
    bodyEl.querySelectorAll(".ps-open").forEach((b) => b.addEventListener("click", () => pywebview.api.open_folder(b.dataset.path)));
    bodyEl.querySelectorAll(".ps-pin").forEach((b) => b.addEventListener("click", async () => {
      const cur = await pywebview.api.list_day_units(row.client);
      const pinnedSet = new Set((cur?.units || []).filter((u) => u.pinned).map((u) => u.path));
      const path = b.dataset.path;
      if (b.dataset.pinned === "true") pinnedSet.delete(path); else pinnedSet.add(path);
      await pywebview.api.set_day_units(row.client, Array.from(pinnedSet));
      const fresh = await pywebview.api.property_structure(row.client);
      if (fresh?.ok) { units = fresh.units || []; bodyEl.innerHTML = renderTree(); wire(); }
      setStatus(`📌 ${row.client} unit pins updated`, "ok");
    }));
    const saveBtn = bodyEl.querySelector("#ps-save-settings");
    saveBtn?.addEventListener("click", async () => {
      saveBtn.disabled = true; saveBtn.textContent = "Saving…";
      const isCommercial = bodyEl.querySelector("#ps-commercial")?.checked;
      const aliases = (bodyEl.querySelector("#ps-aliases")?.value || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
      const r = await pywebview.api.set_property_settings(row.client, !!isCommercial, aliases);
      saveBtn.disabled = false; saveBtn.textContent = "💾 Save settings";
      setStatus(r?.ok ? `💾 Saved settings for ${row.client}` : `Save failed: ${r?.error || "?"}`, r?.ok ? "ok" : "error");
    });
  }
  bodyEl.innerHTML = renderTree();
  wire();
}

async function openSnapPaperwork(row) {
  const techs = Array.isArray(row.techs) ? row.techs.filter(Boolean) : [];
  if (!techs.length) { setStatus(`No tech listed for ${row.client} — can't send paperwork request`, "warn"); return; }
  const defaultTech = techs[0];
  const defaultMsg = (t) => `${t} Please collect paperwork for ${row.client}, thank you`;
  const wrap = mkSnapModal({
    title: "📨 Request paperwork — " + row.client,
    body: `
      <div class="muted" style="font-size:11px;margin-bottom:10px;">Opens the Paperwork-collection group chat with the message pre-filled. Just hit Send.</div>
      <div id="pr-chat-row" style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:11px;color:var(--text-muted);margin-bottom:10px;">Loading chat URL…</div>
      <label style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Tech</label>
      <select id="pr-tech" class="search" style="width:100%;margin:4px 0 12px;">
        ${techs.map((t) => `<option value="${esc(t)}" ${t === defaultTech ? "selected" : ""}>${esc(t)}</option>`).join("")}
      </select>
      <label style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Message</label>
      <textarea id="pr-msg" rows="3" style="width:100%;margin-top:4px;font:inherit;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;">${esc(defaultMsg(defaultTech))}</textarea>
      <div class="modal-footer" style="margin-top:14px;display:flex;gap:8px;align-items:center;">
        <button class="btn" id="pr-edit-chat">🔗 Edit chat URL…</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="pr-send">📨 Open Teams</button>
      </div>`,
  });
  const refreshChatRow = async () => {
    const r = await pywebview.api.get_paperwork_chat_url();
    const el = wrap.querySelector("#pr-chat-row");
    if (!el) return;
    const tag = r?.is_default ? '<span style="color:var(--green);">✓ default</span>' : '<span style="color:var(--amber);">⚙ custom</span>';
    const shortUrl = (r?.url || "").length > 70 ? r.url.slice(0, 67) + "…" : (r?.url || "");
    el.innerHTML = `<div style="display:flex;align-items:center;gap:8px;">${tag}<span style="flex:1;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(r?.url || "")}">${esc(shortUrl)}</span></div>`;
  };
  refreshChatRow();
  wrap.querySelector("#pr-tech").addEventListener("change", (ev) => {
    const t = ev.target.value;
    const msgEl = wrap.querySelector("#pr-msg");
    for (const prevTech of techs) { if (msgEl.value === defaultMsg(prevTech)) { msgEl.value = defaultMsg(t); break; } }
  });
  wrap.querySelector("#pr-edit-chat").addEventListener("click", async () => {
    const cur = await pywebview.api.get_paperwork_chat_url();
    const next = prompt(`Teams chat URL for paperwork requests:\n(paste the full https://teams.microsoft.com/l/chat/... link — or empty to reset to default)`, cur?.url || "");
    if (next === null) return;
    const r = await pywebview.api.set_paperwork_chat_url(next.trim());
    if (!r?.ok) { setStatus(`Save failed: ${r?.error || "?"}`, "error"); return; }
    setStatus(next.trim() ? `🔗 Saved paperwork chat URL` : `Reset to default chat URL`, "ok");
    refreshChatRow();
  });
  wrap.querySelector("#pr-send").addEventListener("click", async () => {
    const tech = wrap.querySelector("#pr-tech").value;
    const msg = wrap.querySelector("#pr-msg").value.trim();
    if (!msg) { setStatus("Message can't be empty", "warn"); return; }
    const res = await pywebview.api.send_paperwork_request(row.client, tech, msg);
    if (!res?.ok) { setStatus(`Send failed: ${res?.error || "?"}`, "error"); return; }
    closeSnapModal();
    setStatus(`📨 Teams opened (${res.chat || "group"} chat) — ${tech} for ${row.client}`, "ok");
  });
}

function showSnapshotAuditCtxMenu(ev, row, customItems) {
  ev.preventDefault(); ev.stopPropagation();
  document.getElementById("snap-audit-ctx")?.remove();
  const m = document.createElement("div");
  m.id = "snap-audit-ctx";
  m.className = "ctx-menu";
  m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
    background:var(--surface);border:1px solid var(--border);border-radius:6px;
    box-shadow:0 6px 20px rgba(0,0,0,.4);z-index:200;min-width:240px;overflow:hidden;`;
  // Multi-unit-only actions surface ONLY on umbrella / unit / subjob rows.
  const isMultiUnit = !!(row.is_parent || row.subjob || row.unit || row.parent_canon);
  const muItems = isMultiUnit ? [
    { lbl: "🏠 Pick day-units…", act: "day-units", off: !row.path },
    { lbl: "🏢 Property structure & settings…", act: "property-structure",
      off: !row.path },
  ] : [];
  // Low-use memory/power items collapsed under "Advanced ▸" (usage audit
  // 2026-07-29: 0 clicks in 7 days — kept, demoted, mirrors the Audit panel).
  const advancedItems = [
    { lbl: "🏷 Edit search aliases…", act: "aliases" },
    { lbl: "🏢 Add to property…", act: "property", off: !row.folder },
    { lbl: "🧹 Clear saved folder path", act: "clear-folder", off: !row.path },
    { lbl: "🏢 Clear Commercial flag", act: "clear-commercial", off: !row.is_commercial },
    { lbl: `♻ Reset all memory for ${row.client}`, act: "reset-memory" },
  ];
  const items = customItems || [
    { lbl: "📁 Open OD folder", act: "open-folder", off: !row.path },
    { lbl: row.found ? "🔀 Change folder…" : "🔎 Find folder…", act: "find-folder" },
    { lbl: "🗂 Past claims…", act: "claim-folders", off: !row.path },
    { lbl: "Open Trello card", act: "open-trello",
      off: !row.trello_card_id,
      iconImg: "../web_shared/trello.png" },
    { lbl: "Open CompanyCam", act: "open-companycam",
      off: !row.trello_card_id,
      iconImg: "../web_shared/companycam.png" },
    { lbl: "Open XactAnalysis", act: "open-xa",
      off: !row.trello_card_id,
      iconImg: "../web_shared/xactanalysis.png" },
    { lbl: "📎 Trello attachments…", act: "attachments",
      off: !row.trello_card_id },
    { sep: true },
    { lbl: "📥 Import from SharePoint…", act: "sp-import" },
    { lbl: "🗂 Import from Downloads…", act: "wc-import" },
    { lbl: "📐 Request Docusketch", act: "docusketch", off: !row.trello_card_id },
    ...muItems,
    { sep: true },
    { lbl: "📋 CLOSE OUT checklist…", act: "closeout" },
    { lbl: "↻ Re-audit this job", act: "reaudit" },
    { lbl: "📨 Request paperwork via Teams…", act: "paperwork" },
    { lbl: "📋 Copy claim #", act: "copy-claim", off: !row.trello_card_id },
    { sep: true },
    { lbl: "🧠 Advanced ▸", act: "__advanced__" },
  ];
  m.innerHTML = items.map((it, i) =>
    it.sep ? `<div style="height:1px;background:var(--border);margin:4px 0;"></div>`
    : `<button class="ctx-item" data-i="${i}" style="display:flex;align-items:center;gap:6px;width:100%;
       text-align:left;background:transparent;color:var(--text);border:0;
       padding:8px 14px;cursor:${it.off ? "not-allowed" : "pointer"};
       opacity:${it.off ? .45 : 1};font:inherit;font-size:13px;"
       ${it.off ? "disabled" : ""}>${it.iconImg ? `<img src="${esc(it.iconImg)}" alt="" style="width:13px;height:13px;flex-shrink:0;" onerror="this.remove()" />` : ""}<span>${esc(it.lbl)}</span></button>`).join("");
  document.body.appendChild(m);
  // Clamp into viewport
  const r = m.getBoundingClientRect();
  if (r.right > window.innerWidth) m.style.left = Math.max(6, window.innerWidth - r.width - 6) + "px";
  if (r.bottom > window.innerHeight) m.style.top = Math.max(6, window.innerHeight - r.height - 6) + "px";
  m.querySelectorAll("[data-i]").forEach((b) => {
    const it = items[+b.dataset.i];
    if (it.off) return;
    b.addEventListener("click", () => {
      m.remove();
      if (it.act === "__advanced__") {
        showSnapshotAuditCtxMenu(
          { preventDefault() {}, stopPropagation() {}, clientX: ev.clientX, clientY: ev.clientY },
          row, advancedItems);
        return;
      }
      onAuditAction(it.act, row);
    });
  });
  const closer = (e) => {
    if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", closer); }
  };
  setTimeout(() => document.addEventListener("click", closer), 0);
}

// ── Snapshot-audit modals (Pin / Find / Comment / SP / Match) ───
function openSnapshotPinCard(row) {
  const wrap = mkSnapModal({
    title: "📌 Pin Trello card for " + row.client,
    body: `
      <input class="search" id="pin-q" type="search" placeholder="Search cards…" value="${esc(row.client)}" style="width:100%;margin-bottom:8px;" />
      <div id="pin-hits" style="max-height:260px;overflow:auto;"></div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  const doSearch = async () => {
    const q = wrap.querySelector("#pin-q").value.trim();
    const hits = await pywebview.api.search_trello_for_snapshot(q) || [];
    wrap.querySelector("#pin-hits").innerHTML = hits.length
      ? hits.map((h) => `
          <div class="pdf-row" data-card="${esc(h.card_id)}" style="cursor:pointer;">
            <div class="pdf-name">${esc(h.name)}</div>
            <div class="pdf-meta">${esc(h.lane || "")} · ${esc(h.board || "")}</div>
          </div>`).join("")
      : `<div class="muted" style="padding:12px;">No matches.</div>`;
    wrap.querySelectorAll("[data-card]").forEach((el) => {
      el.addEventListener("click", async () => {
        // Snapshot doesn't have a separate "pin Trello card" backend;
        // search_trello already returns card_id and pin happens via
        // audit_web's pin_folder flow (which also pins the card by
        // running through persistence). For Trello-only pin, we
        // re-use audit_web's open_pin via the Audit panel — for now
        // just save the card_id via persistence.set_trello_card_id
        // through audit_web's match flow indirectly.
        const res = await pywebview.api.match_diagnostic(row.client);
        // Fallback: open the Trello card so user can copy URL into
        // their Audit panel workflow. (Pin-by-card_id helper is the
        // next iteration; for now Trello pin happens via Audit panel.)
        pywebview.api.open_trello_card(el.dataset.card);
        wrap.remove();
        await runSnapshotAudit();
      });
    });
  };
  bindTitleCaseInput(wrap.querySelector("#pin-q"));
  wrap.querySelector("#pin-q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  doSearch();
}

async function openSnapshotFindFolder(row) {
  // Pre-fetch year-folder list so the scope selector surfaces 2025,
  // 2024, fire-job folders, etc. — not just the current year.
  let yearFolders = [];
  try {
    const yr = await pywebview.api.list_year_folders();
    yearFolders = yr?.folders || [];
  } catch (_) {}
  const curYear = String(new Date().getFullYear());
  const scopeOpts = [
    `<option value="">${curYear} (current year)</option>`,
    `<option value="all">— All years + fire jobs</option>`,
    `<option value="fire">— Fire jobs only (every year)</option>`,
  ];
  const seen = new Set();
  for (const f of yearFolders) {
    if (f.year === curYear && !f.is_fire) continue;
    if (seen.has(f.name)) continue;
    seen.add(f.name);
    const label = f.is_fire ? `🔥 ${f.name}` : f.name;
    scopeOpts.push(`<option value="${esc(f.name)}">${esc(label)}</option>`);
  }

  const wrap = mkSnapModal({
    title: (row.found ? "🔀 Change folder" : "🔎 Find folder") + " for " + row.client,
    body: `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <label class="muted" style="font-size:11px;white-space:nowrap;">Search in:</label>
        <select id="ff-scope" class="search" style="flex:1;">${scopeOpts.join("")}</select>
      </div>
      <input id="ff-search" class="search" placeholder="Filter by name…" autocomplete="off" style="width:100%;margin-bottom:8px;" />
      <div id="ff-crumb" style="display:none;align-items:center;gap:8px;margin-bottom:8px;"></div>
      <div id="ff-status" class="muted" style="font-size:11px;margin-bottom:6px;"></div>
      <div id="ff-hits" style="max-height:320px;overflow-y:auto;">Loading candidates…</div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  // Candidate list + drill-in browse state (mirrors the Audit modal so you
  // can descend into a multi-unit umbrella and pin a specific Unit folder).
  let allCandidates = [];
  let browseStack = [];   // [{name, path}] deepest = current folder
  let browseSubs = [];
  let searchTerm = "";

  // The term used to find the PARENT ("Avil") never matches its children
  // ("Unit 526…"), so clear it whenever we drill / navigate.
  const clearSearch = () => {
    searchTerm = "";
    const el = wrap.querySelector("#ff-search");
    if (el) el.value = "";
  };

  const pin = async (path, label) => {
    const res = await pywebview.api.pin_folder(row.client, path);
    if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
    wrap.remove();
    setStatus(`📁 Pinned ${row.client} → ${label || path}`, "ok");
    await runSnapshotAudit();
  };

  const drillInto = async (folder) => {
    const res = await pywebview.api.list_subfolders(folder.path);
    if (!res?.ok) { setStatus(`Couldn't open: ${res?.error || "?"}`, "error"); return; }
    browseStack.push({ name: folder.name, path: folder.path });
    browseSubs = res.subfolders || [];
    clearSearch();
    render();
  };

  const goToDepth = async (depth) => {
    clearSearch();
    if (depth <= 0) { browseStack = []; browseSubs = []; render(); return; }
    browseStack = browseStack.slice(0, depth);
    const cur = browseStack[browseStack.length - 1];
    const res = await pywebview.api.list_subfolders(cur.path);
    browseSubs = res?.ok ? (res.subfolders || []) : [];
    render();
  };

  const renderCrumb = () => {
    const crumb = wrap.querySelector("#ff-crumb");
    if (!browseStack.length) { crumb.style.display = "none"; return; }
    crumb.style.display = "flex";
    const cur = browseStack[browseStack.length - 1];
    const segs = [`<a href="#" data-depth="0" style="color:var(--link,#4A9EFF);text-decoration:none;font-size:12px;">Candidates</a>`];
    browseStack.forEach((s, i) => {
      segs.push(`<span style="color:var(--text-muted);">›</span>`);
      segs.push(`<a href="#" data-depth="${i + 1}" style="font-size:12px;color:${i === browseStack.length - 1 ? "var(--text)" : "var(--link,#4A9EFF)"};text-decoration:none;font-weight:${i === browseStack.length - 1 ? 700 : 400};">${esc(s.name)}</a>`);
    });
    crumb.innerHTML =
      `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1;">${segs.join("")}</div>` +
      `<button class="btn btn-primary" id="ff-use" title="Pin this exact folder">✓ Use “${esc(cur.name)}”</button>`;
    crumb.querySelectorAll("a[data-depth]").forEach((a) =>
      a.addEventListener("click", (e) => { e.preventDefault(); goToDepth(parseInt(a.dataset.depth, 10)); }));
    crumb.querySelector("#ff-use").addEventListener("click", () => pin(cur.path, cur.name));
  };

  const render = () => {
    renderCrumb();
    const hits = wrap.querySelector("#ff-hits");
    const status = wrap.querySelector("#ff-status");
    const browsing = browseStack.length > 0;
    const q = searchTerm.toLowerCase();
    const items = browsing
      ? (q ? browseSubs.filter((c) => c.name.toLowerCase().includes(q)) : browseSubs)
      : (q ? allCandidates.filter((c) => c.name.toLowerCase().includes(q)) : allCandidates);
    if (browsing) {
      const cur = browseStack[browseStack.length - 1];
      status.textContent = items.length
        ? `${items.length} subfolder${items.length !== 1 ? "s" : ""} in ${cur.name}`
        : `No subfolders in ${cur.name} — use “✓ Use” above to pin it.`;
    } else {
      status.textContent = `${items.length} folder${items.length !== 1 ? "s" : ""}`;
    }
    if (!items.length) {
      hits.innerHTML = `<div class="muted" style="padding:14px;text-align:center;">${browsing ? "No subfolders." : "No matches."}</div>`;
      return;
    }
    hits.innerHTML = items.slice(0, 300).map((c) => `
      <div class="pdf-row ff-row" data-path="${esc(c.path)}" data-name="${esc(c.name)}" style="cursor:pointer;display:flex;align-items:center;gap:8px;">
        <div style="flex:1;min-width:0;">
          <div class="pdf-name">${c.is_fire ? "🔥 " : "📁 "}${esc(c.name)}</div>
          ${!browsing ? `<div class="pdf-meta">${esc(c.year_folder || "")} · ${esc(c.path)}</div>` : ""}
        </div>
        <button class="btn ff-open" title="Open — pick a subfolder inside" style="padding:2px 10px;font-size:13px;">›</button>
      </div>`).join("");
    hits.querySelectorAll(".ff-row").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.closest(".ff-open")) return;
        pin(el.dataset.path, el.dataset.name);
      });
      el.querySelector(".ff-open")?.addEventListener("click", (e) => {
        e.stopPropagation();
        drillInto({ name: el.dataset.name, path: el.dataset.path });
      });
    });
  };

  async function loadAt(scope) {
    browseStack = []; browseSubs = [];
    wrap.querySelector("#ff-hits").innerHTML = `<div class="muted">Loading…</div>`;
    const r = await pywebview.api.list_folder_candidates(row.client, scope || "");
    allCandidates = r?.candidates || [];
    render();
  }
  wrap.querySelector("#ff-scope").addEventListener("change",
    (e) => loadAt(e.target.value));
  wrap.querySelector("#ff-search").addEventListener("input",
    (e) => { searchTerm = e.target.value.trim(); render(); });
  loadAt("");
}

function openSnapshotCommentModal(row) {
  const wrap = mkSnapModal({
    title: "💬 Post Trello comment",
    body: `<textarea id="cmt" rows="6" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;" placeholder="Comment text…"></textarea>
      <div class="modal-footer" style="display:flex;gap:10px;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="cmt-go">💬 Post</button>
      </div>`,
  });
  wrap.querySelector("#cmt-go").addEventListener("click", async () => {
    const body = wrap.querySelector("#cmt").value.trim();
    if (!body) return;
    const res = await pywebview.api.post_comment(row.client, body);
    if (!res?.ok) { setStatus(`Post failed: ${res?.error || "?"}`, "error"); return; }
    wrap.remove();
    setStatus("💬 Posted to Trello", "ok");
  });
  wrap.querySelector("#cmt").focus();
}

// ── 📋 CLOSE OUT checklist (mirrors Tk open_close_out_dialog) ───
// Pulls the client's Trello card's CLOSE OUT (or CLOSE OUT - ADMIN)
// checklist + renders the items as toggleable rows. Click toggles
// complete/incomplete. Right-click removes the item from Trello.
async function openCloseoutModal(row) {
  const res = await pywebview.api.load_closeout_checklist(
    row.client, row.trello_card_id || "");
  if (!res?.ok) {
    setStatus(`CLOSE OUT failed: ${res?.error || "?"}`, "error");
    return;
  }
  const cardId = res.card_id;
  let checklistId = res.checklist_id || "";
  const items = res.items || [];
  function renderRows() {
    return items.map((it, i) => {
      if (it.missing) {
        return `<div data-i="${i}" class="co-row missing" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--surface-2);border:1px dashed var(--red);border-radius:6px;margin-bottom:4px;">
          <span style="color:var(--red);font-weight:700;font-size:16px;">❓</span>
          <div style="flex:1;">
            <div style="font-weight:600;">${esc(it.name)}</div>
            <div class="muted" style="font-size:11px;">Missing on the Trello card. Add it back from Trello, then ↻ Refresh.</div>
          </div>
        </div>`;
      }
      const checkChar = it.complete ? "☑" : "☐";
      const color = it.complete ? "var(--green)" : "var(--text-muted)";
      const weight = it.complete ? "600" : "500";
      const bg = it.complete ? "var(--green-soft)" : "var(--surface-2)";
      const extraTag = it.extra
        ? `<span style="background:var(--act-monitor);color:#FFF;font-size:9px;font-weight:700;padding:1px 6px;border-radius:3px;text-transform:uppercase;letter-spacing:.04em;">extra</span>`
        : "";
      return `<button class="co-row" data-i="${i}" data-iid="${esc(it.id)}"
                title="Click to toggle · Right-click to remove from Trello"
                style="display:flex;align-items:center;gap:12px;width:100%;
                       padding:10px 14px;background:${bg};border:1px solid var(--border);
                       border-radius:6px;margin-bottom:4px;cursor:pointer;
                       font:inherit;text-align:left;">
        <span style="font-size:18px;color:${color};font-weight:${weight};">${checkChar}</span>
        <span style="flex:1;font-weight:${weight};${it.complete ? "text-decoration:line-through;color:var(--text-muted);" : ""}">${esc(it.name)}</span>
        ${extraTag}
      </button>`;
    }).join("");
  }

  // Missing-checklist body — surface what checklists ARE on the
  // card so the user can spot a naming mismatch ("Closeout" vs
  // "CLOSE OUT") without flipping to Trello.
  const otherList = (res.card_checklists || []).filter((n) => n.trim());
  const missingBody = res.missing_checklist
    ? `<div style="background:rgba(192,57,43,.08);border:1px solid var(--red);border-radius:6px;padding:14px 16px;margin-bottom:10px;">
         <div style="color:var(--red);font-weight:700;margin-bottom:6px;">⚠ No CLOSE OUT checklist on this card</div>
         <div class="muted" style="font-size:12px;line-height:1.5;">
           Add a checklist named <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">CLOSE OUT</code> or <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">CLOSE OUT - ADMIN</code> on the Trello card, then ↻ Refresh.
         </div>
         ${otherList.length ? `
           <div class="muted" style="font-size:11px;margin-top:10px;">
             <strong>Checklists found on card:</strong> ${otherList.map((n) => `<code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;">${esc(n)}</code>`).join(" · ")}
           </div>` : ""}
       </div>`
    : "";

  const wrap = mkSnapModal({
    title: "📋 CLOSE OUT — " + (res.card_name || row.client),
    body: `
      ${missingBody}
      <div class="muted" style="font-size:11px;margin-bottom:10px;">
        ${res.missing_checklist
          ? ""
          : `Checklist: <strong>${esc(res.checklist_name || "")}</strong> · Click to toggle · Right-click to remove · syncs to Trello`}
      </div>
      <div id="co-list" style="display:flex;flex-direction:column;">${renderRows()}</div>
      <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
        <button class="btn" id="co-refresh">↻ Refresh</button>
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  function wireRows() {
    wrap.querySelectorAll(".co-row").forEach((b) => {
      const it = items[+b.dataset.i];
      if (!it || it.missing) return;
      // Left-click → toggle complete/incomplete
      b.addEventListener("click", async () => {
        if (!it.id) return;
        const next = !it.complete;
        b.disabled = true;
        const r2 = await pywebview.api.toggle_closeout_item(cardId, it.id, next);
        if (!r2?.ok) {
          setStatus(`Toggle failed: ${r2?.error || "?"}`, "error");
          b.disabled = false;
          return;
        }
        it.complete = next;
        wrap.querySelector("#co-list").innerHTML = renderRows();
        wireRows();
        setStatus(next ? `☑ ${it.name}` : `☐ Re-opened ${it.name}`, "ok");
      });
      // Right-click → remove from Trello (matches user's Tk habit)
      b.addEventListener("contextmenu", (ev) => {
        ev.preventDefault();
        showCloseoutItemCtx(ev, it, b);
      });
    });
  }

  function showCloseoutItemCtx(ev, it, btnEl) {
    document.getElementById("co-ctx")?.remove();
    const m = document.createElement("div");
    m.id = "co-ctx";
    m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
      background:var(--surface);border:1px solid var(--border);border-radius:6px;
      box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:300;min-width:200px;padding:4px 0;`;
    const remove = document.createElement("button");
    remove.textContent = "✕ Remove item from Trello";
    remove.style.cssText = "display:block;width:100%;text-align:left;background:transparent;color:var(--red);border:0;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;";
    remove.addEventListener("mouseenter", () => remove.style.background = "rgba(192,57,43,.12)");
    remove.addEventListener("mouseleave", () => remove.style.background = "transparent");
    remove.addEventListener("click", async () => {
      m.remove();
      if (!confirm(`Remove "${it.name}" from the checklist on Trello?\n\nThis can't be undone from here — re-add it from Trello if needed.`)) return;
      btnEl.disabled = true;
      const r2 = await pywebview.api.delete_closeout_item(checklistId, it.id);
      if (!r2?.ok) {
        setStatus(`Remove failed: ${r2?.error || "?"}`, "error");
        btnEl.disabled = false;
        return;
      }
      // Drop the item from local state + re-render
      const idx = items.indexOf(it);
      if (idx >= 0) items.splice(idx, 1);
      wrap.querySelector("#co-list").innerHTML = renderRows();
      wireRows();
      setStatus(`✕ Removed "${it.name}" from Trello`, "ok");
    });
    m.appendChild(remove);
    document.body.appendChild(m);
    const closer = (e) => {
      if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", closer); }
    };
    setTimeout(() => document.addEventListener("click", closer), 0);
  }

  wireRows();
  wrap.querySelector("#co-refresh").addEventListener("click", async () => {
    wrap.remove();
    openCloseoutModal(row);
  });
}

async function openSnapshotMatchDiag(row) {
  const res = await pywebview.api.match_diagnostic(row.client);
  if (!res?.ok) { setStatus(`Diag failed: ${res?.error || "?"}`, "error"); return; }
  const wrap = mkSnapModal({
    title: "🔎 Match diagnostic — " + row.client,
    body: `
      <div style="max-height:60vh;overflow:auto;">
        ${(res.candidates || []).map((c) => `
          <div class="pdf-row" style="cursor:pointer;" data-path="${esc(c.path)}">
            <div class="pdf-name">${esc(c.name)} <span class="muted">· score ${c.score}</span></div>
            <div class="pdf-meta">${esc(c.path)} · ${esc(c.reason || "")}</div>
          </div>`).join("")}
      </div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  wrap.querySelectorAll("[data-path]").forEach((el) =>
    el.addEventListener("click", async () => {
      const r = await pywebview.api.pin_folder(row.client, el.dataset.path);
      if (!r?.ok) { setStatus(`Pin failed: ${r?.error || "?"}`, "error"); return; }
      wrap.remove();
      setStatus(`📁 Pinned ${row.client}`, "ok");
      await runSnapshotAudit();
    }));
}

async function openSnapshotSpImport(row) {
  const wrap = mkSnapModal({
    title: "📥 SharePoint import — " + row.client,
    width: 960,
    body: `<div id="sp-status" class="muted">🔎 Scanning SharePoint…</div>
      <div id="sp-list" style="margin-top:10px;max-height:540px;overflow-y:auto;"></div>
      <div class="modal-footer" style="display:flex;gap:8px;margin-top:10px;align-items:center;">
        <label id="sp-side-toggle" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;user-select:none;"
               title="Route this import into the CONTENTS side (CONTENTS/PICS) instead of EMS/PICS">
          <input type="checkbox" id="sp-contents" style="cursor:pointer;" /> 📦 Contents side
        </label>
        <button class="btn" id="sp-pin">📎 Pin SP folder…</button>
        <button class="btn" id="sp-rescan">↻ Re-scan</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  function renderMatches(matches) {
    const status = wrap.querySelector("#sp-status");
    status.textContent = matches.length
      ? `${matches.length} SharePoint folder${matches.length !== 1 ? "s" : ""} match`
      : "No SharePoint folders match. Use 📎 Pin SP folder… below to attach one manually.";
    wrap.querySelector("#sp-list").innerHTML = matches.map((m, i) => `
      <div class="snap-sp-row" data-i="${i}" data-path="${esc(m.path)}"
           style="display:grid;grid-template-columns:auto 1fr auto auto auto auto;gap:8px;
                  align-items:center;padding:8px 10px;border:1px solid var(--border);
                  border-radius:6px;margin-bottom:4px;background:var(--surface);">
        <span title="${m.matches_date ? 'Matches run date' : ''}">${m.matches_date ? "✓" : "📁"}</span>
        <div style="min-width:0;">
          <div style="font-weight:600;font-size:13px;">${esc(m.name || "")}</div>
          <div class="muted" style="font-size:11px;word-break:break-all;">
            ${esc(m.tech || "—")} · ${m.img_count} files · ${m.new_count} new
            <span class="snap-sp-cloud" data-i="${i}" style="margin-left:6px;"></span>
          </div>
        </div>
        <button class="action-btn" data-act="open" title="Open in Explorer">📁</button>
        <button class="action-btn" data-act="mark_od" title="Already in OD — don't flag as new again" ${m.img_count > 0 ? "" : "disabled"}>✓ In OD</button>
        <button class="action-btn primary" data-act="copy" ${m.new_count > 0 ? "" : "disabled"}>📥 +${m.new_count}</button>
        <button class="action-btn warn" data-act="reject" title="Hide from future scans">✕</button>
      </div>`).join("");
    // Cloud-only chip per row, fires in parallel
    matches.forEach(async (m, i) => {
      try {
        const cr = await pywebview.api.sp_cloud_only_count(m.path);
        const chip = wrap.querySelector(`.snap-sp-cloud[data-i="${i}"]`);
        if (chip && cr?.ok && cr.count > 0) {
          chip.innerHTML = `<span style="background:var(--amber);color:#FFF;padding:1px 6px;border-radius:3px;font-weight:700;font-size:10px;" title="${cr.count} cloud-only placeholders">☁ ${cr.count} cloud-only</span>`;
        }
      } catch (_) {}
    });
    wireRows(matches);
  }

  function wireRows(matches) {
    wrap.querySelectorAll(".snap-sp-row").forEach((rowEl) => {
      const m = matches[+rowEl.dataset.i];
      rowEl.querySelectorAll(".action-btn[data-act]").forEach((b) => {
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          const act = b.dataset.act;
          if (act === "open") {
            await pywebview.api.sp_open_folder(m.path);
          } else if (act === "mark_od") {
            b.disabled = true; b.textContent = "Marking…";
            const r2 = await pywebview.api.sp_mark_in_od(row.client, m.path);
            if (!r2?.ok) { setStatus(`Mark failed: ${r2?.error || "?"}`, "error"); b.disabled = false; b.textContent = "✓ In OD"; return; }
            b.textContent = `✓ ${r2.marked} marked`;
            setStatus(`✓ ${r2.marked} marked already-in-OD`, "ok");
          } else if (act === "copy") {
            b.disabled = true; b.textContent = "Copying…";
            // `side` routes to EMS/PICS or CONTENTS/PICS (Contents toggle).
            const side = wrap.querySelector("#sp-contents")?.checked
              ? "contents" : "ems";
            let r2 = await pywebview.api.sp_copy_to_pics(
              row.client, m.path, "", row.path || "", side, "");
            // SP folders are usually named by the tech; only prompt when
            // the backend couldn't determine one, then retry with the pick.
            if (r2?.need_tech) {
              const t = await window.pickImportTech({ client: row.client, techs: row.techs });
              if (!t) { b.disabled = false; b.textContent = "📥 Copy"; return; }
              r2 = await pywebview.api.sp_copy_to_pics(
                row.client, m.path, "", row.path || "", side, t);
            }
            if (!r2?.ok) {
              const err = r2?.error || "?";
              const needsFolder = /PICS folder|Pin the OD folder/i.test(err);
              if (needsFolder) {
                b.disabled = false; b.textContent = "📥 Copy";
                if (confirm(`No OD folder found for ${row.client}.\n\n${err}\n\nOpen the Find Folder dialog now?`)) {
                  wrap.remove();
                  openSnapshotFindFolder(row);
                } else { setStatus(err, "warn"); }
                return;
              }
              setStatus(`Copy failed: ${err}`, "error"); b.disabled = false; b.textContent = "📥 Copy"; return;
            }
            b.textContent = `✓ ${r2.copied} copied`;
            setStatus(`📥 ${r2.copied} files copied · ${r2.skipped} skipped${r2.pulled ? ` · ☁ ${r2.pulled} pulled` : ""}`, "ok");
            await runSnapshotAudit();
          } else if (act === "reject") {
            await pywebview.api.sp_reject_match(row.client, m.path);
            rowEl.style.display = "none";
            setStatus("Match rejected", "ok");
          }
        });
      });
    });
  }

  async function scan() {
    wrap.querySelector("#sp-status").textContent = "🔎 Scanning…";
    wrap.querySelector("#sp-list").innerHTML = "";
    const r = await pywebview.api.sp_find_matches(row.client);
    if (!r?.ok) {
      wrap.querySelector("#sp-status").textContent = "Error: " + (r?.error || "?");
      return;
    }
    renderMatches(r.matches || []);
  }

  wrap.querySelector("#sp-rescan").addEventListener("click", scan);
  wrap.querySelector("#sp-pin").addEventListener("click", async () => {
    setStatus("Pick a SharePoint folder…");
    const picked = await pywebview.api.sp_browse_for_folder();
    if (!picked) { setStatus("Pin canceled", "warn"); return; }
    const r2 = await pywebview.api.sp_pin_folder(row.client, picked);
    if (!r2?.ok) { setStatus(`Pin failed: ${r2?.error || "?"}`, "error"); return; }
    setStatus(`📎 Pinned ${r2.match?.name || picked}`, "ok");
    await scan();
  });
  scan();
}

// ── 🗂 WorkCenter / DocuSign Downloads scanner ─────────────────
// Same flow IUQ uses — scans Downloads for client-named zips,
// surfaces them as importable candidates with per-extension routing
// to PICS / DOCS. Mirrors the audit panel's "Import from Downloads"
// flow.
async function openSnapshotWcImport(row) {
  const data = await pywebview.api.scan_downloads_for_card(row.client) || {};
  const cands = data.candidates || [];
  const wrap = mkSnapModal({
    title: "🗂 Import from Downloads",
    body: `<div class="muted" style="margin-bottom:8px;">WorkCenter · DocuSign · DocuSketch · loose docs/photos — anything outside SharePoint.<br>Scanning: ${esc(data.downloads || "(Downloads)")} · Client: ${esc(row.client)}</div>
      <div id="wc-list">
        ${cands.length ? cands.map((c, i) => `
          <div class="pdf-row" data-i="${i}" style="display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;">
            <span style="font-size:18px;">${esc(c.icon || "📦")}</span>
            <div>
              <div style="font-weight:600;font-size:13px;">${esc(c.kind_label || c.kind)}</div>
              <div class="muted" style="font-size:11px;word-break:break-all;">${esc(c.label || "")}</div>
            </div>
            <button class="action-btn primary" data-i="${i}">Extract</button>
          </div>`).join("") : `
          <div class="muted" style="padding:12px;text-align:center;">
            Nothing auto-detected in Downloads.<br>
            <span style="font-size:11px;">Save a WorkCenter / DocuSign / DocuSketch download to your Downloads folder and ↻ Re-scan — or use 📁 Pick a file for anything else.</span>
          </div>`}
      </div>
      <div class="modal-footer" style="display:flex;gap:8px;margin-top:14px;align-items:center;">
        <label id="wc-side-toggle" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;user-select:none;"
               title="Route this import into the CONTENTS side (CONTENTS/PICS, CONTENTS/DOCS) instead of EMS — a separate tree outside EMS">
          <input type="checkbox" id="wc-contents" style="cursor:pointer;" /> 📦 Contents side
        </label>
        <button class="btn" id="wc-rescan">↻ Re-scan</button>
        <button class="btn" id="wc-pick" title="Hand-pick any file(s) to import — zips, PDFs, or photos">📁 Pick a file…</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  wrap.querySelector("#wc-rescan")?.addEventListener("click", () => {
    wrap.remove();
    openSnapshotWcImport(row);
  });
  wrap.querySelector("#wc-pick")?.addEventListener("click", async () => {
    const btn = wrap.querySelector("#wc-pick");
    const choice = await window.pickPicsStage({ client: row.client, allowAuto: true, allowDocs: true });
    if (choice === null) return;                     // cancelled
    const dest = choice === "AUTO" ? "" : choice;
    // A PICS stage (or AUTO) means photos → require a tech, same as the
    // other photo-import paths. A DOCS destination is paperwork → skip.
    let tech = "";
    if (!/^DOCS/i.test(String(choice))) {
      tech = await window.pickImportTech({ client: row.client, techs: row.techs });
      if (!tech) return;                             // cancelled / no tech
    }
    btn.disabled = true; btn.textContent = "Picking…";
    state.importBtn = btn;
    const side = wrap.querySelector("#wc-contents")?.checked
      ? "contents" : "ems";
    try {
      const res = await pywebview.api.pick_and_import_file(row.client, dest, side, tech);
      if (res?.cancelled) {
        // user closed the picker — no-op
      } else if (!res?.ok) {
        setStatus(`Import failed: ${res?.error || "?"}`, "error");
      } else {
        const bits = [];
        if (res.pics_count) bits.push(`${res.pics_count} → PICS/${res.subfolder || "Initial"}`);
        if (res.docs_count) bits.push(`${res.docs_count} → DOCS`);
        if (res.sketches_count) bits.push(`${res.sketches_count} → DOCS/Docusketch`);
        setStatus(`✓ ${row.client}: ${bits.join(" · ") || "imported"}`, "ok");
        await runSnapshotAudit();
      }
    } catch (ex) {
      setStatus(`Import error: ${ex}`, "error");
    } finally {
      if (state.importBtn === btn) state.importBtn = null;
      btn.disabled = false; btn.textContent = "📁 Pick a file…";
    }
  });
  wrap.querySelectorAll("[data-i]").forEach((b) => {
    if (b.tagName !== "BUTTON") return;
    b.addEventListener("click", async () => {
      const c = cands[+b.dataset.i];
      // Photo imports → ask which PICS stage folder first.
      let dest = "";
      let tech = "";
      if (c.kind === "companycam" || c.kind === "wc_attachments") {
        const choice = await window.pickPicsStage({ client: row.client, allowAuto: true });
        if (choice === null) return;                 // cancelled
        dest = choice === "AUTO" ? "" : choice;
        // Every photo import must be attributed to a tech (same guard the
        // Daily Run + IUQ import surfaces enforce). Cancel/empty aborts.
        tech = await window.pickImportTech({ client: row.client, techs: row.techs });
        if (!tech) return;                           // cancelled / no tech
      }
      b.disabled = true; b.textContent = "Extracting…";
      state.importBtn = b;
      const side = wrap.querySelector("#wc-contents")?.checked
        ? "contents" : "ems";
      try {
        const res = await pywebview.api.do_import(row.client, c.kind, c.paths, dest, tech, side);
        if (!res?.ok) { setStatus(`Import failed: ${res?.error || "?"}`, "error"); b.textContent = "Failed"; return; }
        b.textContent = "✓ Done";
        const bits = [];
        if (res.pics_count) bits.push(`${res.pics_count} → PICS/${res.subfolder || "Initial"}`);
        if (res.docs_count) bits.push(`${res.docs_count} → DOCS`);
        setStatus(`✓ Extracted: ${bits.join(" · ")}`, "ok");
        await runSnapshotAudit();
      } finally {
        if (state.importBtn === b) state.importBtn = null;
      }
    });
  });
}

// ── Scope dialog (P1) ───────────────────────────────────────────
function openScopeModal() {
  const client = $("#f-insured").value.trim();
  if (!client) { setStatus("Insured required first", "warn"); return; }
  const wrap = mkSnapModal({
    title: "📋 Scope for " + client,
    body: `
      <label style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:4px;">Paste scope text</label>
      <textarea id="sc-raw" rows="8" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;outline:none;resize:vertical;"
        placeholder="Living Room&#10;- Demo carpet&#10;- Replace baseboards&#10;&#10;Master Bedroom&#10;- Pack contents"></textarea>
      <button class="btn" id="sc-parse" style="margin-top:8px;">🧪 Parse + preview</button>
      <div id="sc-preview" style="margin-top:12px;"></div>
      <div class="modal-footer" style="margin-top:14px;display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="sc-save" disabled>📄 Save PDF</button>
      </div>`,
  });
  let parsedRooms = [];
  wrap.querySelector("#sc-parse").addEventListener("click", async () => {
    const raw = wrap.querySelector("#sc-raw").value;
    const res = await pywebview.api.parse_scope_text(raw);
    if (!res?.ok) {
      wrap.querySelector("#sc-preview").innerHTML =
        `<div style="color:var(--red);">Parse failed: ${esc(res?.error || "?")}</div>`;
      return;
    }
    parsedRooms = res.rooms || [];
    wrap.querySelector("#sc-preview").innerHTML = parsedRooms.length
      ? parsedRooms.map((r) => `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:6px;">
          <div style="font-weight:600;">${esc(r.name)}</div>
          <ul style="margin:6px 0 0;padding-left:20px;">
            ${r.items.map((i) => `<li style="font-size:12px;color:var(--text-muted);">${esc(i)}</li>`).join("")}
          </ul>
        </div>`).join("")
      : `<div class="muted">No rooms parsed.</div>`;
    wrap.querySelector("#sc-save").disabled = parsedRooms.length === 0;
  });
  wrap.querySelector("#sc-save").addEventListener("click", async () => {
    const saveBtn = wrap.querySelector("#sc-save");
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    const res = await pywebview.api.save_scope(client, parsedRooms);
    if (!res?.ok) {
      setStatus(`Save failed: ${res?.error || "?"}`, "error");
      saveBtn.disabled = false; saveBtn.textContent = "📄 Save PDF";
      return;
    }
    // Replace the modal body with a saved-confirmation view:
    // shows the exact path, action buttons, and an inline PDF preview.
    const bodyEl = wrap.querySelector("div > div:nth-child(2)");
    if (bodyEl) {
      bodyEl.innerHTML = `
        <div style="background:rgba(46,204,113,.10);border:1px solid var(--green);border-radius:6px;padding:10px 14px;margin-bottom:12px;display:flex;gap:10px;align-items:center;">
          <span style="font-size:18px;">✅</span>
          <div style="flex:1;">
            <div style="font-weight:700;color:var(--green);">Scope PDF saved</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;font-family:monospace;word-break:break-all;">${esc(res.path)}</div>
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
          <button class="btn" id="sc-open-folder">📁 Reveal in Explorer</button>
          <button class="btn" id="sc-open-pdf">🗂 Open PDF in default app</button>
        </div>
        <div id="sc-preview-pane" style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;height:480px;overflow:hidden;">
          <div class="muted" style="padding:14px;">Loading preview…</div>
        </div>
        <div class="modal-footer" style="margin-top:14px;display:flex;gap:10px;justify-content:flex-end;">
          <button class="btn modal-close">Close</button>
        </div>`;
      bodyEl.querySelectorAll(".modal-close").forEach((b) =>
        b.addEventListener("click", closeSnapModal));
      bodyEl.querySelector("#sc-open-folder").addEventListener("click",
        () => pywebview.api.reveal_in_explorer(res.path));
      bodyEl.querySelector("#sc-open-pdf").addEventListener("click",
        () => pywebview.api.open_file(res.path));
      // Inline preview via base64 data URL — file:// from a pywebview-
      // hosted page is unreliable, the data URL works everywhere.
      const pdf = await pywebview.api.read_pdf_b64(res.path);
      const pane = bodyEl.querySelector("#sc-preview-pane");
      if (pdf?.ok) {
        pane.innerHTML = `<embed type="application/pdf"
                                 src="data:application/pdf;base64,${pdf.b64}"
                                 style="width:100%;height:100%;border:0;" />`;
      } else {
        pane.innerHTML = `<div class="muted" style="padding:14px;">Preview unavailable: ${esc(pdf?.error || "?")}</div>`;
      }
    }
    setStatus("📄 Scope saved", "ok");
  });
}

function mkSnapModal({ title, body, width }) {
  closeSnapModal();
  const w = document.createElement("div");
  w.id = "snap-modal-2";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  // Per-caller width override — defaults to 640. SP import dialog
  // wants ~960 so the per-row action buttons fit inline.
  const widthPx = Math.max(320, parseInt(width || 640, 10));
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(${widthPx}px,96vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">${esc(title)}</div>
      </header>
      <div style="padding:18px 20px;overflow-y:auto;">${body}</div>
    </div>`;
  document.body.appendChild(w);
  w.addEventListener("click", (e) => { if (e.target === w) closeSnapModal(); });
  w.querySelectorAll(".modal-close").forEach((b) =>
    b.addEventListener("click", closeSnapModal));
  return w;
}
function closeSnapModal() { document.getElementById("snap-modal-2")?.remove(); }

// ── Find Trello card modal (P0) ─────────────────────────────────
function openFindCardModal() {
  const wrap = document.createElement("div");
  wrap.id = "snap-modal";
  wrap.className = "overlay";
  wrap.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(640px,92vw);max-height:80vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">🔍 Find Trello card</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Search by name OR pick from SNAPSHOT lanes</div>
      </header>
      <div style="padding:14px 20px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;">
        <input id="fc-q" class="search" type="search" autocomplete="off"
               placeholder="Type at least 2 characters…" style="width:100%;" />
        <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;font-weight:700;margin-top:6px;">Or pick from SNAPSHOT lane</div>
        <button class="btn" id="fc-lane-load">↻ Load SNAPSHOT-lane cards</button>
        <div id="fc-results" style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);"></div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);text-align:right;">
        <button class="btn" id="fc-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  $("#fc-close").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });

  function renderResults(rows) {
    const el = $("#fc-results");
    if (!rows.length) {
      el.innerHTML = `<div style="padding:14px;text-align:center;color:var(--text-muted);">No matches.</div>`;
      return;
    }
    el.innerHTML = rows.map((r) => `
      <div class="fc-row" data-name="${esc(r.name)}" data-card="${esc(r.card_id || '')}"
           style="padding:8px 14px;border-bottom:1px solid var(--border);cursor:pointer;">
        <div style="font-weight:600;">${esc(r.name)}</div>
        <div style="font-size:11px;color:var(--text-muted);">${esc(r.lane || "")} · ${esc(r.board || "")}</div>
      </div>`).join("");
    el.querySelectorAll(".fc-row").forEach((row) => {
      row.addEventListener("mouseenter",
        () => row.style.background = "var(--row-hover)");
      row.addEventListener("mouseleave",
        () => row.style.background = "transparent");
      row.addEventListener("click", async () => {
        close();
        $("#f-insured").value = row.dataset.name;
        // Pass the card id so we get the full Trello parse (carrier,
        // claim, DOL, first visit, cause) — not just the run-doc prefill.
        await startNew(row.dataset.name, row.dataset.card);
      });
    });
  }

  let timer = null;
  $("#fc-q").addEventListener("input", (e) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = e.target.value.trim();
      if (q.length < 2) { renderResults([]); return; }
      $("#fc-results").innerHTML =
        `<div style="padding:14px;text-align:center;color:var(--text-muted);">Searching…</div>`;
      const hits = await pywebview.api.search_trello_for_snapshot(q);
      renderResults(hits);
    }, 240);
  });
  $("#fc-lane-load").addEventListener("click", async () => {
    $("#fc-lane-load").disabled = true;
    $("#fc-lane-load").textContent = "Loading…";
    $("#fc-results").innerHTML =
      `<div style="padding:14px;text-align:center;color:var(--text-muted);">Walking boards…</div>`;
    const rows = await pywebview.api.snapshot_lane_candidates(40);
    $("#fc-lane-load").disabled = false;
    $("#fc-lane-load").textContent = "↻ Load SNAPSHOT-lane cards";
    renderResults(rows);
  });
  bindTitleCaseInput($("#fc-q"));
  $("#fc-q").focus();
}

let st = null;
function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || ""; el.className = "status-msg" + (kind ? " " + kind : "");
  if (st) clearTimeout(st);
  if (kind === "ok") st = setTimeout(() => { el.textContent = ""; el.className = "status-msg"; }, 3000);
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
// Display-only Title Case: uppercase the first letter of every word,
// leaving the rest untouched so acronyms (LLC, IPR) and internal caps
// (McDonald) survive. NEVER mutate the stored/identity value.
function titleCase(s) {
  return String(s == null ? "" : s).replace(
    /(^|[\s\-\/,.'"“”‘’([])([a-zà-ÿ])/g,
    (_m, sep, ch) => sep + ch.toUpperCase());
}
// Live auto-capitalize for a search <input>, preserving caret position.
function bindTitleCaseInput(el) {
  if (!el) return;
  el.addEventListener("input", () => {
    const pos = el.selectionStart;
    const next = titleCase(el.value);
    if (next !== el.value) {
      el.value = next;
      try { el.setSelectionRange(pos, pos); } catch (_e) {}
    }
  });
}

// Browser-native clipboard with a hidden-textarea fallback — identical
// to the audit + IUQ panels so every audit surface copies the same way.
async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(String(text));
      return true;
    }
  } catch (_) { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = String(text);
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    ta.style.pointerEvents = "none";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    return true;
  } catch (_) {
    return false;
  }
}

// ── Topbar Trello search (always-visible, any view) ──────────────
// Live-searches Trello cards; clicking a result opens the generate
// view pre-filled. Replaces having to click + New snapshot → 🔍 Find.
function attachTopbarTrelloSearch() {
  const input = $("#trello-search");
  const results = $("#trello-search-results");
  if (!input || !results) return;
  let timer = null;
  const hide = () => { results.style.display = "none"; };
  const show = () => { results.style.display = "block"; };

  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { hide(); return; }
    results.innerHTML =
      `<div style="padding:12px;color:var(--text-muted);">Searching Trello…</div>`;
    show();
    timer = setTimeout(async () => {
      const hits = await pywebview.api.search_trello_for_snapshot(q) || [];
      if (!hits.length) {
        results.innerHTML =
          `<div style="padding:12px;color:var(--text-muted);">No matches for "${esc(q)}"</div>`;
        return;
      }
      results.innerHTML = hits.map((r) => `
        <div class="ts-row" data-name="${esc(r.name)}" data-card="${esc(r.card_id || '')}"
             style="padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;">
          <div style="font-weight:600;color:var(--text);">${esc(r.name)}</div>
          <div style="font-size:11px;color:var(--text-muted);">
            ${esc(r.lane || "")} · ${esc(r.board || "")}
          </div>
        </div>`).join("");
      results.querySelectorAll(".ts-row").forEach((row) => {
        row.addEventListener("mouseenter",
          () => row.style.background = "var(--row-hover)");
        row.addEventListener("mouseleave",
          () => row.style.background = "transparent");
        row.addEventListener("click", async () => {
          hide();
          input.value = "";
          // Switch to generate view + parse the chosen card fully
          // (desc + comments + Subs checklist → carrier/claim/DOL/etc).
          await startNew(row.dataset.name, row.dataset.card);
        });
      });
    }, 240);
  });

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#trello-search-wrap")) hide();
  });
  // Re-show on focus if there's still a query
  input.addEventListener("focus", () => {
    if (input.value.trim().length >= 2 && results.innerHTML) show();
  });
}

// ── Multi-unit picker (Tk parity) ───────────────────────────────
// Returns a Promise resolving to:
//   • {insured, path} when user picks a unit (path = that unit's folder,
//     pinned by the caller so the audit/snapshot resolve the RIGHT unit)
//   • {insured: property, path: umbrella} when user picks "roll up"
//   • null when user cancels (abort the generate)
function openMultiUnitPicker(mu) {
  return new Promise((resolve) => {
    const w = document.createElement("div");
    w.id = "sn-mu-modal";
    w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
    const camePrefix = mu.came_in_as === "umbrella"
      ? "You typed the property umbrella"
      : "The unit you typed has siblings";
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">🏢 Multi-unit property</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
            ${camePrefix} — <b>${esc(mu.property_name)}</b> has ${mu.units.length} units.
            Pick what to snapshot.
          </div>
        </header>
        <div style="padding:14px 18px;">
          <button class="btn" id="mu-rollup" style="width:100%;text-align:left;padding:10px 14px;margin-bottom:10px;">
            🏢 Roll up the property — snapshot <b>${esc(mu.property_name)}</b> as a single job
          </button>
          <div style="font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin:8px 0 4px;">
            Or pick one specific unit:
          </div>
          <div id="mu-units" style="max-height:340px;overflow-y:auto;display:flex;flex-direction:column;gap:4px;"></div>
        </div>
        <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
          <button class="btn" id="mu-cancel">Cancel</button>
        </footer>
      </div>`;
    document.body.appendChild(w);
    const close = (val) => { w.remove(); resolve(val); };
    document.getElementById("mu-cancel").addEventListener("click", () => close(null));
    w.addEventListener("click", (e) => { if (e.target === w) close(null); });
    document.getElementById("mu-rollup").addEventListener("click",
      () => close({ insured: mu.property_name, path: mu.umbrella_path || "" }));
    document.getElementById("mu-units").innerHTML = (mu.units || []).map((u) => `
      <button class="btn mu-unit"
              data-display="${esc(u.display_name || "")}"
              data-path="${esc(u.path || "")}"
              style="text-align:left;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
        <span>${esc(u.display_name || ("Unit " + u.unit_number))}</span>
        <span style="font-size:10px;color:var(--text-muted);font-variant-numeric:tabular-nums;">
          ${esc(u.unit_number || "")}
        </span>
      </button>`).join("");
    document.querySelectorAll(".mu-unit").forEach((b) =>
      b.addEventListener("click", () =>
        close({ insured: b.dataset.display, path: b.dataset.path || "" })));
  });
}

// ── Comments paste parser (Tk parity) ──────────────────────────
// Takes whatever's in the Trello-comments textarea and pipes it
// through snapshot_gui.parse_comments() + detect_first_visit() +
// parse_scope() — populates the subs + logs tables and the
// first-visit input. Replaces existing rows so re-parsing after an
// edit doesn't duplicate.
async function parseTrelloComments() {
  const raw = $("#f-comments").value;
  if (!raw.trim()) { setStatus("Nothing to parse", "warn"); return; }
  setStatus("✂ Parsing comments…");
  const res = await pywebview.api.parse_comments_blob(raw);
  if (!res?.ok) {
    setStatus(`Parse failed: ${res?.error || "?"}`, "error");
    return;
  }
  // Replace subs + logs from the parsed result. Tk re-builds both
  // tables from scratch on parse; mirror that here.
  $("#subs-body").innerHTML = "";
  $("#logs-body").innerHTML = "";
  (res.subs || []).forEach((r) => addRow("subs", r));
  (res.logs || []).forEach((r) => addRow("logs", r));
  if (res.first_visit && !$("#f-first").value) {
    $("#f-first").value = res.first_visit;
  }
  const scope = res.scope_rooms || [];
  const bits = [];
  if (res.subs?.length) bits.push(`${res.subs.length} subs`);
  if (res.logs?.length) bits.push(`${res.logs.length} log rows`);
  if (res.first_visit)  bits.push(`first visit ${res.first_visit}`);
  if (scope.length)     bits.push(`${scope.length} scope rooms`);
  setStatus(`✂ Parsed: ${bits.join(" · ") || "no rows detected"}`, "ok");
}
