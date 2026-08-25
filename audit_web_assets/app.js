/* Daily Audit — Pywebview spike frontend (two-pane layout).
 *
 * Left pane = compact one-line list of every audited job.
 * Right pane = full detail of the selected job.
 *
 * Selection model: `state.selected_client` tracks which job is in
 * the right pane. Auto-selects first row on initial load + after
 * filter changes if the prior selection drops out of the result
 * set. Arrow keys (↑ / ↓) move selection like an email client.
 */
"use strict";

const state = {
  rows: [],
  meta: {},
  filter: "all",
  search: "",
  loading: false,
  selected_client: null,   // client name of the job in the right pane
  starred_clients: [],     // lowercase client names the user has ⭐'d
  selected_set: new Set(), // client names selected for bulk action
  importBtn: null,         // <button> currently running an import (HEIC progress target)
  oneoffHits: [],          // jobs pulled up by Search — they ACCUMULATE so
                           // several can be worked side by side, and survive
                           // clearing the box (✕ Clear results empties them)
  oneoffTried: "",         // last term we auto-ran a one-off for (avoid repeats)
  oneoffRunning: false,    // guard against overlapping auto one-off audits
  dayOffset: 0,            // 0 = today, -1 = yesterday …
  auditForDay: undefined,  // which day the in-flight audit was started for
  queuedAudit: null,       // a day picked while an audit was running
  selectedDate: "",        // YYYY-MM-DD currently shown by the day walker
  calendar: { year: 0, month: 0, dates: new Set(), seq: 0 },
};

// Commercial-parent groups (e.g. "Menifee Union School District") the
// user has collapsed in the list. Keyed by lowercased parent name.
// Module-level so it survives re-renders within the session.
// Cap on jobs held on the Search tab. They accumulate as you search, so a
// long session would otherwise grow an unbounded list; newest wins.
const ONEOFF_MAX = 40;

const collapsedParents = new Set();
// Parent keys we've already seeded as collapsed-on-startup, so a manual
// expand isn't re-collapsed on the next render — only brand-new parents
// (from a fresh audit) get auto-collapsed.
const _seenParentKeys = new Set();

// Multi-unit umbrellas: rows that carry a unit are clustered under a
// synthetic property header. Today's referenced units always peek through;
// the caret expands to reveal the property's OTHER units (fetched lazily
// from disk). Keyed by lowercased client name.
const expandedUnitGroups = new Set();     // which unit umbrellas are expanded
const unitSiblingsCache = new Map();      // key -> [{name, path}] (all units on disk)

// Live HEIC→JPEG conversion progress from the backend (do_import emits
// `import:progress` per file). Updates whichever import button is
// running so a big photo dump shows "Converting N/M…" instead of a
// frozen "Extracting…". No-op if no import is active or the count is 0.
window.addEventListener("import:progress", (e) => {
  const d = (e && e.detail) || {};
  if (state.importBtn && d.total) {
    state.importBtn.textContent = `Converting ${d.done}/${d.total}…`;
  }
});

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  // Load starred-clients list once on boot — used by ⭐ buttons +
  // the Starred filter. Updates push back via toggleStarred.
  try {
    state.starred_clients = await pywebview.api.get_starred_clients() || [];
  } catch (_) { state.starred_clients = []; }
  $("#run-btn").addEventListener("click", () => runAudit(true));
  $("#rerun-btn").addEventListener("click", () => runAudit(false));
  attachBulkToolbar();
  attachMoreMenu();
  $("#search-box").addEventListener("input", onSearchInput);
  // P0: day walker + section toggles + Audit One
  $("#day-prev").addEventListener("click", () => walkDay(-1));
  $("#day-today").addEventListener("click", () => walkDay(0));
  $("#day-next").addEventListener("click", () => walkDay(+1));
  $("#audit-date-label").addEventListener("click", (event) => {
    event.stopPropagation(); toggleRunCalendar();
  });
  $("#calendar-prev").addEventListener("click", (event) => {
    event.stopPropagation(); shiftCalendarMonth(-1);
  });
  $("#calendar-next").addEventListener("click", (event) => {
    event.stopPropagation(); shiftCalendarMonth(1);
  });
  $("#open-doc-btn").addEventListener("click",
    () => pywebview.api.open_run_doc(state.dayOffset || 0));
  $("#new-loss-btn")?.addEventListener("click", () => openNewLossModal());
  $("#usage-btn")?.addEventListener("click", () => openUsagePanel());
  $("#overview-btn")?.addEventListener("click", () => openOverviewPanel());
  $("#name-issues-btn")?.addEventListener("click", () => openNameIssuesPanel());
  $("#cc-sync-btn")?.addEventListener("click", () => runCompanyCamSync());
  $("#notes-btn")?.addEventListener("click", () => openNotesPanel());
  $("#sec-work").addEventListener("change", () => refreshDayLabel());
  $("#sec-monitor").addEventListener("change", () => refreshDayLabel());
  // Right-click context menu (close on outside click)
  document.addEventListener("click", () => $("#ctx-menu")?.remove());
  // Dismiss the type-ahead when focus moves elsewhere. Scoped to clicks
  // OUTSIDE the wrapper so picking a row isn't cancelled before it fires.
  document.addEventListener("click", (e) => {
    if (!e.target.closest?.("#search-wrap")) hideSuggestions();
    if (!e.target.closest?.("#run-calendar-anchor")) closeRunCalendar();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeRunCalendar();
  });
  // ↓/↑ to walk the list, Enter to take the top hit, Esc to dismiss.
  $("#search-box").addEventListener("keydown", (e) => {
    const rows = Array.from(document.querySelectorAll(".suggest-row"));
    if (e.key === "Escape") { hideSuggestions(); return; }
    if (!rows.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); rows[0].focus(); }
    else if (e.key === "Enter") { e.preventDefault(); rows[0].click(); }
  });
  state.dayOffset = 0;
  state.mode = "search";
  refreshDayLabel();
  updateNotesBadge();          // show the open-notes count on the 📝 button
  // Mode switcher (streamlined 2026-07: Search default, Daily Run, Starred)
  $("#clear-oneoff-btn")?.addEventListener("click", () => {
    state.oneoffHits = [];
    state.oneoffTried = "";
    saveRecents();                 // clearing has to persist too
    renderList();
    renderDetail();
    setStatus("Cleared searched jobs", "ok");
  });
  $("#mode-search")?.addEventListener("click",  () => switchMode("search"));
  $("#mode-daily")?.addEventListener("click",   () => switchMode("daily"));
  $("#mode-starred")?.addEventListener("click", () => switchMode("starred"));
  // Bulk action buttons
  $("#push-new-losses-btn").addEventListener("click", pushNewLosses);
  $("#post-daily-misses-btn").addEventListener("click", postDailyMisses);
  $("#export-flagged-btn").addEventListener("click", () => exportPdf("flagged"));
  $("#export-all-btn").addEventListener("click", () => exportPdf("all"));
  $("#archive-month-btn").addEventListener("click", openArchiveMonthModal);
  $("#copy-xa-apology-btn").addEventListener("click", copyXaApologyNote);
  $$(".filter").forEach((b) => {
    b.addEventListener("click", () => setFilter(b.dataset.filter));
    // Paint the restored filter onto the buttons. state.filter is set from
    // the saved panel state before this runs, and without this the list
    // would be filtered while every button still looked like "All".
    b.classList.toggle("active", b.dataset.filter === state.filter);
  });
  // SP stats tile = one-click filter to "Has SP". Clicking again
  // returns to All. Mirrors the way the Flagged tile would feel if
  // it were clickable.
  document.getElementById("stat-sp")?.addEventListener("click", () => {
    setFilter(state.filter === "has_sp" ? "all" : "has_sp");
  });
  window.addEventListener("audit:progress", onAuditProgress);
  window.addEventListener("audit:done",    onAuditDone);
  // SP enrichment runs as a background pass AFTER audit:done so the
  // loading icon goes away immediately. Each enriched row arrives
  // via audit:sp_update — splice + re-render the matching row.
  window.addEventListener("audit:sp_update", onSpUpdate);
  window.addEventListener("audit:sp_done",   onSpDone);
  // SP cloud-only force-pull (from the SP import dialog)
  // The bar rides the same stream as the text — it says how far along,
  // which the text can't at a glance.
  if (window.Progress) {
    window.Progress.bind("sp:pull-progress", "sp:pull-done");
    // The audit run itself. It already streamed {i, n, client} into
    // the loading label; the label says WHICH job, the bar says how
    // much is left, and on a 300-row day those are different
    // questions.
    window.Progress.bind("audit:progress", "audit:done");
    // The SharePoint enrichment pass. It runs 30-120s AFTER the
    // audit finishes, so the panel looked idle for the longest
    // stretch of the whole run.
    window.Progress.bind("audit:sp_update", "audit:sp_done");
    // Imports (HEIC conversion + copy) already streamed
    // {done, total} to a button label only.
    window.Progress.bind("import:progress", "import:done");
  }
  window.addEventListener("sp:pull-progress", (ev) => {
    const d = ev.detail || {};
    setStatus(`☁ Pulling ${d.done || 0}/${d.total || "?"} · ${d.name || "…"}`);
  });
  window.addEventListener("sp:pull-done", (ev) => {
    const d = ev.detail || {};
    if (!d.ok) {
      setStatus(`Pull failed: ${d.error || "?"}`, "error");
    } else {
      const r = d.result || {};
      setStatus(
        `☁ Pull complete · ${r.pulled || 0} downloaded · ${r.failed || 0} failed · ${r.elapsed_s || 0}s`,
        "ok");
    }
    // Re-enable any Pull buttons + reset their text
    document.querySelectorAll("#sp-list .action-btn[data-act='pull']").forEach((b) => {
      b.disabled = false; b.textContent = "☁ Pull";
    });
    // Re-fetch cloud-only counts since files just got hydrated
    document.querySelectorAll(".sp-cloud-tag").forEach(async (chip) => {
      const i = chip.dataset.i;
      const row = document.querySelector(`.target-row[data-i="${i}"]`);
      if (!row) return;
      const r = await pywebview.api.sp_cloud_only_count(row.dataset.path);
      if (r?.ok) {
        if (r.count > 0) {
          chip.innerHTML = `<span style="background:var(--amber);color:#FFF;padding:1px 6px;border-radius:3px;font-weight:700;font-size:10px;">☁ ${r.count} cloud-only</span>`;
        } else {
          chip.innerHTML = `<span style="background:var(--green);color:#FFF;padding:1px 6px;border-radius:3px;font-weight:700;font-size:10px;">☁ ✓ all local</span>`;
          // Hide the pull button — nothing to pull anymore
          const pullBtn = row.querySelector(".action-btn[data-act='pull']");
          if (pullBtn) pullBtn.style.display = "none";
        }
      }
    });
  });
  document.addEventListener("keydown", onKeyDown);

  // Register audit keyboard shortcuts in the shared `?` overlay.
  if (window.registerKeyboardHelp) {
    window.registerKeyboardHelp([
      { keys: "/",  desc: "Focus search" },
      { keys: "j",  desc: "Next row" },
      { keys: "k",  desc: "Previous row" },
      { keys: "r",  desc: "Re-audit current job" },
      { keys: "↵", desc: "Open OD folder for selected row" },
      { keys: "C",  desc: "Copy day summary as Markdown" },
    ]);
  }

  // Deep-link focus from a cross-tool "Open in → Audit" (a one-off /
  // quick pull-up). Read it BEFORE loading the daily board so we can
  // skip the board's async auto-refresh — that background re-audit's
  // re-render is what used to wipe the pulled-up job and dump the user
  // back on the whole board.
  const _focus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";

  // Decide the landing tab BEFORE the first paint. This used to happen at
  // the very END of boot: the cached daily-run rows were rendered, and only
  // then did a trailing switchMode("search") run — so every launch flashed
  // the daily board and jumped to Search. That trailing call also passed no
  // isRestore flag, which PERSISTED mode="search" on every boot and quietly
  // overwrote whichever tab you'd actually left open.
  if (!_focus && !state.userSwitchedMode) {
    let landing = "search";
    try {
      // PanelState caches the whole panel record, so the filter restore
      // below costs no extra round trip.
      const st = await PanelState.init("audit");
      if (st && ["search", "daily", "starred"].includes(st.mode)) {
        landing = st.mode;
      }
      const savedFilter = PanelState.get("filter", "");
      if (savedFilter) state.filter = savedFilter;
    } catch (_) { /* no saved tab — Search is the default */ }
    // Chrome only: the data load below paints once, under the right tab.
    if (!state.userSwitchedMode) applyModeChrome(landing);
    // After PanelState.init, so the saved list is in memory. Not awaited:
    // it re-audits each job in turn, and the panel should be usable
    // while that happens.
    restoreRecents();
  }

  try {
    const cached = await pywebview.api.last_audit();
    if (cached && cached.rows && cached.rows.length) {
      state.rows = cached.rows;
      state.meta = cached.meta || {};
      renderAll();
      // Auto-refresh if the cached audit is >30 min old. Quietly
      // triggers a background re-audit — the user gets fresh data
      // without having to remember to click ↻. Skipped when deep-
      // linking to one job: we're about to leave the daily board for
      // one-off mode, so a background daily re-audit would just fight
      // the pull-up.
      const ranAt = cached.meta?.ran_at_iso;
      const ageMin = ranAt ? (Date.now() - new Date(ranAt).getTime()) / 60000 : Infinity;
      if (!_focus && ageMin > 30) {
        setStatus(`Cached audit ${Math.floor(ageMin)}min old — refreshing…`, "");
        runAudit(true);
      }
    } else if (!_focus) {
      const meta = await pywebview.api.today_meta();
      state.meta = {
        ...meta,
        ran_at: "—",
        total: meta.job_count,
        flagged: 0,
        ok: 0,
      };
      renderStats();
      // DO NOT auto-fire. User explicitly clicks ↻ Run Audit when
      // they want fresh data. Audits walk the X: drive and take
      // 10-30 seconds — running them on every tab visit was wrong.
      setStatus(
        `${meta.job_count} jobs in today's run-doc · Click ↻ Run Audit to scan`,
        "");
    }
    $("#run-btn").disabled = false;
  } catch (ex) {
    setStatus(`Failed to load: ${ex}`, "error");
  }

  // A deep-link pulls up that ONE job in one-off mode (audit it on the
  // spot and land on its row) instead of dropping the user on the daily
  // board and hoping the name filters — a one-off job usually isn't on
  // today's run-doc, so filtering matched nothing.
  if (_focus) {
    await openFocusJob(_focus);
  } else if (state.mode !== "daily") {
    // The tab was already chosen above; this only loads that tab's data.
    // Daily is skipped because the cached-audit block just loaded it —
    // re-entering switchMode("daily") would fetch and repaint it twice.
    // isRestore: boot is not a user choice, so it must not persist.
    await switchMode(state.mode, true);
  } else {
    renderAll();
  }
});

// Pull up a single job from a cross-tool deep-link: audit it and switch
// to one-off mode with the row selected. Falls back to filtering the
// current rows if the one-off audit can't resolve the name.
async function openFocusJob(name) {
  setStatus(`🔍 Pulling up ${name}…`, "");
  let res = null;
  try {
    res = await pywebview.api.audit_one_job(name, "", false);
  } catch (ex) {
    res = { ok: false, error: String(ex) };
  }
  if (!res?.ok || !res.row) {
    // Couldn't resolve to a single job — degrade to a name filter on
    // whatever's already loaded so the user still gets a starting point.
    const box = $("#search-box");
    if (box) { box.value = name; box.dispatchEvent(new Event("input")); }
    setStatus(`Couldn't pull up “${name}”${res?.error ? ": " + res.error : ""} — filtered instead`,
              "error");
    return;
  }
  await switchMode("search");
  state.selected_client = rowKey(res.row);
  renderAll();
  // Bring the selected row into view.
  try {
    document.querySelector(".list-row.active")
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  } catch (_) { /* best-effort */ }
  setStatus(`🔍 ${name}`, "ok");
}

// ── Mode switcher (Daily / Backlog / SP Recent / One-off — P1) ──
// NOTE: the tab is restored during boot (see pywebviewready), not here.
// An async restore fired alongside boot raced the trailing landing switch
// and flashed the daily board; resolving the tab before the first paint
// removes the race instead of guarding against it.

// Tab chrome only — active pill, toolbar visibility, button labels. Split
// out of switchMode so boot can set the landing tab BEFORE the first paint
// without also re-running switchMode's data loading.
function applyModeChrome(mode) {
  state.mode = mode;
  ["search", "daily", "starred"].forEach((m) => {
    document.getElementById("mode-" + m)?.classList.toggle("active", m === mode);
  });
  // Only Daily Run uses the day-walker + section toggles
  $("#daily-toolbar").style.display = mode === "daily" ? "" : "none";
  // A daily-run load keeps running in the background when you leave the tab;
  // its loading overlay is only meaningful on the Daily Run tab.
  if (state.loading) {
    $("#loading-state").classList.toggle("hidden", mode !== "daily");
  }
  $("#run-btn").textContent = mode === "daily" ? "↻ Run Audit"
    : mode === "starred" ? "↻ Reload starred"
    :                      "↻ Reload";
}

async function switchMode(mode, isRestore) {
  // Remember the tab for next launch. Fire-and-forget — losing this costs
  // a restore, never the switch the user just asked for.
  if (!isRestore) {
    state.userSwitchedMode = true;
    try { pywebview?.api?.set_ui_state?.("audit", { mode }); } catch (_) { /**/ }
  }
  applyModeChrome(mode);

  // Search tab (default) — start from previously-audited jobs; the search box
  // auto-audits any typed name not already in the list (type-to-find).
  if (mode === "search") {
    const res = await pywebview.api.list_oneoff();
    if (res?.ok) {
      state.rows = res.rows || [];
      state.meta = { date_iso: "(search)", ran_at: "", total: res.total,
                     flagged: 0, ok: 0 };
      renderAll();
    }
    setStatus("🔍 Search above to pull a job up — it stays here while you work", "");
    $("#search-box")?.focus();
    return;
  }

  // Load the right dataset
  if (mode === "backlog") {
    // Run auto-close BEFORE loading so EMS-LOG cards drop out
    const ac = await pywebview.api.check_backlog_auto_close();
    if (ac?.auto_closed?.length) {
      setStatus(`🏁 Auto-closed ${ac.auto_closed.length} jobs now in EMS LOG`, "ok");
    }
    const res = await pywebview.api.list_backlog();
    if (res?.ok) {
      state.rows = res.rows || [];
      state.meta = { date_iso: "(backlog)", ran_at: "", total: res.total, flagged: state.rows.filter((r) => r.flagged).length, ok: 0 };
      renderAll();
      if (!ac?.auto_closed?.length) {
        setStatus(`Loaded ${res.total} backlog rows`, "ok");
      }
    }
  } else if (mode === "sp") {
    const res = await pywebview.api.list_sp_recent(7);
    if (res?.ok) {
      state.rows = res.rows || [];
      state.meta = { date_iso: "(sp_recent)", ran_at: "", total: res.total, flagged: 0, ok: res.total };
      renderAll();
      setStatus(`Loaded ${res.total} SP folders from last 7 days`, "ok");
    }
  } else if (mode === "starred") {
    const res = await pywebview.api.list_starred();
    if (res?.ok) {
      state.rows = res.rows || [];
      state.meta = { date_iso: "(starred)", ran_at: "",
                     total: res.total,
                     flagged: state.rows.filter((r) => r.flagged).length,
                     ok: state.rows.filter((r) => !r.flagged).length };
      renderAll();
      setStatus(
        res.total
          ? `⭐ ${res.total} starred client${res.total === 1 ? "" : "s"}`
          : (res.empty_reason || "No starred clients"),
        res.total ? "ok" : "");
    } else {
      setStatus(`Couldn't load starred: ${res?.error || "?"}`, "error");
    }
  } else if (mode === "daily") {
    // Restore the cached daily-run rows. Without this, switching
    // out of one-off/backlog/sp and back to Daily Run left the
    // table showing whatever the other tab loaded — Daily Run
    // looked empty or showed wrong rows. Cheap call (no audit
    // re-run): just returns the in-process cache.
    const res = await pywebview.api.last_audit();
    state.rows = res?.rows || [];
    state.meta = res?.meta || state.meta || {};
    renderAll();
    if (!state.rows.length) {
      setStatus("No daily-run audit loaded yet — click ↻ Run Audit", "");
    } else {
      setStatus(`Daily Run · ${state.rows.length} jobs`, "ok");
    }
  }
}

// ── ⋯ More dropdown — secondary actions (full re-scan + bulk) ────
function attachMoreMenu() {
  const btn  = document.getElementById("more-btn");
  const menu = document.getElementById("more-menu");
  if (!btn || !menu) return;
  const hide = () => { menu.style.display = "none"; };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.style.display = menu.style.display === "block" ? "none" : "block";
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#more-wrap")) hide();
  });
  // Auto-close after any item click. Each item already has its own
  // handler bound at boot (export-flagged-btn / push-new-losses-btn
  // etc.) — this just collapses the dropdown.
  menu.querySelectorAll(".more-item").forEach((el) =>
    el.addEventListener("click", () => setTimeout(hide, 0)));
}

async function exportPdf(scope) {
  const btn = scope === "flagged" ? $("#export-flagged-btn") : $("#export-all-btn");
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "Generating…";
  const res = await pywebview.api.export_audit_pdf(scope);
  btn.disabled = false;
  btn.textContent = orig;
  if (!res?.ok) { setStatus(`Export failed: ${res?.error || "?"}`, "error"); return; }
  setStatus(`📄 PDF saved · ${res.rows} jobs · ${res.path}`, "ok");
}

async function copyXaApologyNote() {
  // Single source of truth lives in Python (ar_followup.DEFAULT_NOTE)
  // — fetch over the bridge so a wording change in one place takes
  // effect everywhere without re-deploying the web assets.
  let note = "";
  try {
    const r = await pywebview.api.get_xa_apology_note();
    note = (r && r.note) ? r.note : "";
  } catch (_) {}
  if (!note) {
    // Fallback so a bridge hiccup doesn't leave the user staring at a
    // silent button. Same wording as ar_followup.DEFAULT_NOTE.
    note = ("Our apologies for the delay. Please note our estimating "
            + "team is diligently working on the file.");
  }
  const ok = await copyText(note);
  setStatus(ok ? "📋 Copied XA apology note"
              : "Couldn't copy — clipboard blocked", ok ? "ok" : "warn");
}

async function pushNewLosses() {
  const btn = $("#push-new-losses-btn");
  btn.disabled = true; btn.textContent = "Pushing…";
  const res = await pywebview.api.push_new_losses_to_apa();
  btn.disabled = false; btn.textContent = "📊 Push new losses → APA";
  if (!res?.ok) { setStatus(`Push failed: ${res?.error || "?"}`, "error"); return; }
  if (!res.added?.length) { setStatus(res.note || "Nothing to push", "warn"); return; }
  setStatus(`📊 Added ${res.added.length} new losses to APA Initial Uploads`, "ok");
}

async function postDailyMisses() {
  if (!confirm("Post a 'Daily miss' Trello comment on every flagged + pinned card?")) return;
  const btn = $("#post-daily-misses-btn");
  btn.disabled = true; btn.textContent = "Posting…";
  const res = await pywebview.api.post_daily_misses_to_trello();
  btn.disabled = false; btn.textContent = "💬 Post daily misses → Trello";
  if (!res?.ok) { setStatus(`Post failed: ${res?.error || "?"}`, "error"); return; }
  const bits = [];
  if (res.posted?.length) bits.push(`${res.posted.length} posted`);
  if (res.skipped_no_pin?.length) bits.push(`${res.skipped_no_pin.length} skipped (no pin)`);
  if (res.errored?.length) bits.push(`${res.errored.length} errored`);
  setStatus(`💬 ${bits.join(" · ")}`, "ok");
}

// ── Day walker (P0) ─────────────────────────────────────────────
async function walkDay(delta) {
  if (delta === 0) state.dayOffset = 0;
  else state.dayOffset = (state.dayOffset || 0) + delta;
  await refreshDayLabel();
  // If audit was already run for today's offset, immediately re-run
  // for the new day so the user sees fresh data after clicking.
  requestAudit(true);
}

async function refreshDayLabel() {
  const want = state.dayOffset || 0;
  const r = await pywebview.api.find_run_doc_for(want);
  // Clicking through days fast means several of these are in flight; only
  // the one for the day still selected may paint.
  if ((state.dayOffset || 0) !== want) return;
  state.selectedDate = r.date_iso || "";
  $("#audit-date-text").textContent = r.date_label || "—";
  $("#open-doc-btn").disabled = !r.exists;
  $("#open-doc-btn").style.opacity = r.exists ? "1" : "0.5";
  if (!$("#run-calendar").classList.contains("hidden")) renderRunCalendar();
}

// ── Month calendar — dots mark dates with real run documents ─────
function toggleRunCalendar() {
  const popover = $("#run-calendar");
  if (!popover.classList.contains("hidden")) { closeRunCalendar(); return; }
  const selected = parseIsoDate(state.selectedDate) || new Date();
  state.calendar.year = selected.getFullYear();
  state.calendar.month = selected.getMonth() + 1;
  popover.classList.remove("hidden");
  $("#audit-date-label").setAttribute("aria-expanded", "true");
  loadRunCalendarMonth();
}

function closeRunCalendar() {
  $("#run-calendar")?.classList.add("hidden");
  $("#audit-date-label")?.setAttribute("aria-expanded", "false");
}

function shiftCalendarMonth(delta) {
  const d = new Date(state.calendar.year, state.calendar.month - 1 + delta, 1);
  state.calendar.year = d.getFullYear();
  state.calendar.month = d.getMonth() + 1;
  loadRunCalendarMonth();
}

async function loadRunCalendarMonth() {
  const { year, month } = state.calendar;
  const seq = ++state.calendar.seq;
  $("#calendar-title").textContent = new Intl.DateTimeFormat(undefined, {
    month: "long", year: "numeric"
  }).format(new Date(year, month - 1, 1));
  $("#calendar-grid").innerHTML = '<div class="calendar-loading">Finding run documents…</div>';
  $("#calendar-count").textContent = "";
  let result;
  try { result = await pywebview.api.run_doc_calendar(year, month); }
  catch (error) { result = { ok: false, error: String(error), dates: [] }; }
  if (seq !== state.calendar.seq) return;
  state.calendar.dates = new Set(result?.dates || []);
  renderRunCalendar();
  $("#calendar-count").textContent = result?.ok
    ? `${state.calendar.dates.size} run day${state.calendar.dates.size === 1 ? "" : "s"}`
    : "Couldn’t scan this month";
}

function renderRunCalendar() {
  const { year, month, dates } = state.calendar;
  if (!year || !month) return;
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = localIso(new Date());
  const cells = [];
  for (let i = 0; i < firstWeekday; i += 1) cells.push('<span class="calendar-blank"></span>');
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const hasRun = dates.has(iso);
    const classes = ["calendar-day", hasRun ? "has-run" : "no-run"];
    if (iso === today) classes.push("today");
    if (iso === state.selectedDate) classes.push("selected");
    const label = new Date(year, month - 1, day).toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric", year: "numeric"
    });
    cells.push(`<button class="${classes.join(" ")}" data-date="${iso}"
      aria-label="${escapeHtml(label)}${hasRun ? ", run document available" : ", no run document"}">${day}</button>`);
  }
  $("#calendar-grid").innerHTML = cells.join("");
  $("#calendar-grid").querySelectorAll(".calendar-day").forEach((button) =>
    button.addEventListener("click", () => selectCalendarDate(button.dataset.date)));
}

async function selectCalendarDate(iso) {
  const chosen = parseIsoDate(iso);
  if (!chosen) return;
  const today = new Date();
  state.dayOffset = Math.round((
    Date.UTC(chosen.getFullYear(), chosen.getMonth(), chosen.getDate()) -
    Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  ) / 86400000);
  closeRunCalendar();
  await refreshDayLabel();
  requestAudit(true);
}

function parseIsoDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

function localIso(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// Ask for an audit of the CURRENT day, coping with one already running.
//
// runAuditFiltered used to just `return` when state.loading was set. So
// changing day mid-run moved dayOffset and the label, silently dropped the
// request, and then the in-flight run finished and rendered the OLD day.
// Nothing ever re-requested, so the day you picked never loaded — you had
// to leave the tab and come back. Now the request is remembered and fired
// when the running one reports back.
function requestAudit(useCache) {
  if (state.loading) {
    state.queuedAudit = { useCache, day: state.dayOffset || 0 };
    $("#loading-label").textContent = "Switching day…";
    return;
  }
  runAuditFiltered(useCache);
}

// Called from onAuditDone once the in-flight run has released state.loading.
function _drainQueuedAudit() {
  const q = state.queuedAudit;
  if (!q) return false;
  state.queuedAudit = null;
  runAuditFiltered(q.useCache);
  return true;
}

async function runAuditFiltered(useCache) {
  if (state.loading) { state.queuedAudit = { useCache, day: state.dayOffset || 0 }; return; }
  state.loading = true;
  // Remember which day this run is FOR, so a result that arrives after you
  // have moved on can be recognised as stale instead of overwriting the
  // rows for the day now on screen.
  state.auditForDay = state.dayOffset || 0;
  $("#run-btn").disabled = true;
  $("#rerun-btn").disabled = true;
  $("#loading-label").textContent = "Auditing…";
  $("#loading-state").classList.remove("hidden");
  setStatus("");
  try {
    const res = await pywebview.api.run_audit_filtered(
      $("#sec-work").checked,
      $("#sec-monitor").checked,
      useCache,
      state.dayOffset || 0);
    // Backend may refuse to start (concurrent audit / no run-doc).
    // Without this branch the loading overlay stays visible forever
    // because audit:done never fires for the request we didn't start.
    if (res && res.started === false) {
      state.loading = false;
      $("#loading-state").classList.add("hidden");
      $("#run-btn").disabled = false;
      $("#rerun-btn").disabled = false;
      // The backend refuses while its own run is in flight. Retry rather
      // than strand the day: without this the request is lost the same way
      // the old client-side guard lost it.
      if (_drainQueuedAudit()) return;
      setStatus(res.reason || "Couldn't start audit", "warn");
    }
  } catch (ex) {
    setStatus(`Audit error: ${ex}`, "error");
    state.loading = false;
    $("#loading-state").classList.add("hidden");
    $("#run-btn").disabled = false;
    $("#rerun-btn").disabled = false;
    _drainQueuedAudit();
  }
}

// ── Incoming downloads panel ─────────────────────────────────────
// Surfaces every importable download (WC attachments / WC docs /
// DocuSign) sitting in Downloads and lets the user pick the job + import
// in one place — no need to find the row first. WC photo dumps carry no
// client name, so the job field defaults to the currently-selected row
// but is editable. Multi-stage/day batches auto-split via pickImportGroups.
async function importDownloadForClient(client, cand) {
  const kind = cand.kind;
  const paths = cand.paths || [];
  if (kind === "companycam" || kind === "wc_attachments") {
    let detection = null;
    try { detection = await pywebview.api.detect_import_groups(paths); }
    catch (_) { detection = null; }
    if (detection && detection.ok && detection.multi) {
      const assignments = await window.pickImportGroups({ client, techs: [], detection });
      if (!assignments) return null;             // cancelled
      return await pywebview.api.do_import_grouped(client, kind, paths, assignments, "ems");
    }
    const choice = await window.pickPicsStage({ client, allowAuto: true });
    if (choice === null) return null;            // cancelled
    const dest = choice === "AUTO" ? "" : choice;
    const tech = await window.pickImportTech({ client, techs: [] });
    if (!tech) return null;                       // cancelled
    return await pywebview.api.do_import(client, kind, paths, dest, tech, "ems");
  }
  // WC documents / DocuSign → paperwork, straight to DOCS (no stage/tech).
  return await pywebview.api.do_import(client, kind, paths, "", "", "ems");
}

async function openIncomingPanel() {
  const overlay = createOverlay({
    title: "📥 Incoming downloads",
    sub:   "New Workcenter / DocuSign files in Downloads — pick the job and import (photos auto-split by stage).",
    body: `
      <div id="inc-status" class="muted"></div>
      <div id="inc-list" class="target-list" style="margin-top:8px;max-height:360px;"></div>
      <div class="modal-footer">
        <button class="btn" id="inc-rescan">🔄 Rescan</button>
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  const listEl   = overlay.querySelector("#inc-list");
  const statusEl = overlay.querySelector("#inc-status");

  const defClient = (() => {
    const r = findRowByKey(state.selected_client);
    return r ? (r.display_name || titleCase(r.client)) : "";
  })();

  const scan = async () => {
    statusEl.textContent = "Scanning Downloads…";
    listEl.innerHTML = "";
    let res;
    try { res = await pywebview.api.scan_downloads(""); }
    catch (ex) { statusEl.textContent = `Scan failed: ${ex}`; return; }
    const cands = (res && res.candidates) || [];
    if (!cands.length) {
      statusEl.textContent = "Nothing importable in Downloads right now.";
      return;
    }
    statusEl.textContent = `${cands.length} download${cands.length !== 1 ? "s" : ""} — set a job and import each:`;
    listEl.innerHTML = cands.map((c, i) => `
      <div class="target-row" data-i="${i}" style="align-items:center;">
        <span>${escapeHtml(c.icon || "📥")}</span>
        <div style="flex:1;min-width:0;">
          <div class="name">${escapeHtml(c.label || c.kind)}</div>
          <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(c.kind_label || c.kind)}${(c.paths && c.paths.length > 1) ? ` · ${c.paths.length} parts` : ""}</div>
        </div>
        <input class="inc-job search" data-i="${i}" type="text" placeholder="Job / client…"
               value="${escapeAttr(defClient)}" autocomplete="off" style="width:190px;" />
        <button class="btn btn-primary inc-go" data-i="${i}" style="margin-left:6px;white-space:nowrap;">📥 Import</button>
      </div>`).join("");
    listEl.querySelectorAll(".inc-go").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const i = parseInt(btn.dataset.i, 10);
        const client = (listEl.querySelector(`.inc-job[data-i="${i}"]`).value || "").trim();
        if (!client) { setStatus("Type a job/client for this download first.", "warn"); return; }
        btn.disabled = true; btn.textContent = "Importing…";
        try {
          const r = await importDownloadForClient(client, cands[i]);
          if (r === null) { btn.disabled = false; btn.textContent = "📥 Import"; return; }
          if (!r.ok) {
            btn.disabled = false; btn.textContent = "📥 Import";
            setStatus(`Import failed for ${client}: ${r.error || "?"}`, "error");
            return;
          }
          btn.textContent = "✓ Done";
          const parts = r.routed
            ? Object.entries(r.routed).map(([f, n]) => `${n} → ${f}`)
            : (r.pics_count ? [`${r.pics_count} photos`]
               : (r.docs_count ? [`${r.docs_count} → DOCS`] : ["imported"]));
          if (r.failed && r.failed.length) parts.push(`⚠ ${r.failed.length} failed`);
          setStatus(`✓ ${client}: ${parts.join(" · ")}`, "ok");
          // Refresh the audit row if this job is in today's list.
          try {
            const re = await pywebview.api.reaudit_one(client);
            if (re?.ok) {
              applyRow(re.row); renderAll();
            }
          } catch (_) { /* not in today's list — fine */ }
        } catch (ex) {
          btn.disabled = false; btn.textContent = "📥 Import";
          setStatus(`Import error: ${ex}`, "error");
        }
      });
    });
  };

  overlay.querySelector("#inc-rescan")?.addEventListener("click", scan);
  scan();
}

// ── Job admin overview (🩺) ──────────────────────────────────────
// The simplified Hygiene job board, surfaced right in the audit so the
// DocuSign / initial+final paperwork / weekly-check-in status of every
// active job is one click away. Shares web_shared/hygiene_board.js with
// the Hygiene panel, so the two never drift.
// ── 🧩 Name issues ────────────────────────────────────────────────────
// One insured, two spellings. The job key comes from the name, so
// "Seth Knudsen" and "Knudsen, Seth - Mercury" are two jobs, and the
// carrier, claim and photos land on whichever row a tool resolved.
//
// Nothing here decides on its own. Folding two people who share a
// surname is worse than the split, so each pair is shown with the facts
// that agree and the facts that conflict, and the answer is yours. A
// pair marked "different people" is remembered and not offered again.
async function openNameIssuesPanel() {
  const overlay = createOverlay({
    title: "🧩 Name issues",
    sub: "Jobs that look like one insured typed two ways. Keep the spelling you want, or say they're different people.",
    body: `<div id="ni-body" class="muted">Looking for split names…</div>
           <div class="modal-footer"><button class="btn modal-close">Close</button></div>`,
  });
  const body = overlay.querySelector("#ni-body");

  const load = async () => {
    body.innerHTML = `<div class="muted">Looking for split names…</div>`;
    let res;
    try { res = await pywebview.api.list_name_issues(); }
    catch (ex) { res = { ok: false, error: String(ex) }; }
    if (!res?.ok) {
      body.innerHTML = `<div style="color:var(--red);">Couldn't check: ${escapeHtml(res?.error || "?")}</div>`;
      return;
    }
    const pairs = res.pairs || [];
    if (!pairs.length) {
      body.innerHTML = `<div style="padding:8px 0;">✓ No split names found`
        + (res.ignored ? ` · ${res.ignored} pair(s) marked as different people` : "")
        + `</div>`;
      return;
    }
    // Facts first: a shared carrier or claim is the argument FOR folding,
    // a conflicting one the argument against. Showing them is the whole
    // point — the names alone can't tell you.
    const side = (s, other, pk) => `
      <div class="ni-side">
        <div class="ni-name">${escapeHtml(s.display_name || s.canon_key)}</div>
        <div class="ni-meta">${escapeHtml(s.canon_key)}</div>
        ${["carrier", "claim_number", "address", "phone"].map((f) => {
          const v = (s[f] || "").trim();
          if (!v) return "";
          const clash = ((other[f] || "").trim()
                         && (other[f] || "").trim().toLowerCase() !== v.toLowerCase());
          return `<div class="ni-fact${clash ? " clash" : ""}">`
            + `${f.replace("_", " ")}: <strong>${escapeHtml(v)}</strong></div>`;
        }).join("")}
        <div class="ni-meta">first seen ${escapeHtml(s.first_seen || "—")}</div>
        <button class="btn ni-keep" data-keep="${escapeAttr(s.canon_key)}"
                data-drop="${escapeAttr(other.canon_key)}" data-pair="${escapeAttr(pk)}">
          Keep this name</button>
      </div>`;

    body.innerHTML = pairs.map((p) => `
      <div class="ni-pair" data-pair="${escapeAttr(p.pair_key)}">
        <div class="ni-verdict ${p.likely_same ? "same" : "unsure"}">
          ${p.likely_same
            ? `Probably the same — ${escapeHtml(p.agrees.join(", "))} match`
            : (p.conflicts.length
                ? `⚠ ${escapeHtml(p.conflicts.join(", "))} differ — check before folding`
                : "No shared details to compare — your call")}
        </div>
        <div class="ni-sides">
          ${side(p.a, p.b, p.pair_key)}
          ${side(p.b, p.a, p.pair_key)}
        </div>
        <div class="ni-actions">
          <button class="btn ni-ignore" data-pair="${escapeAttr(p.pair_key)}">
            These are different people</button>
        </div>
      </div>`).join("");

    body.querySelectorAll(".ni-keep").forEach((b) => {
      b.addEventListener("click", async () => {
        const keep = b.dataset.keep, drop = b.dataset.drop;
        if (!confirm(`Fold "${drop}" into "${keep}"?\n\n`
                     + `Aliases, folder and Trello links and history move across, `
                     + `and any detail only the folded job had is carried over first. `
                     + `This can't be undone from here.`)) return;
        b.disabled = true; b.textContent = "Folding…";
        let r;
        try { r = await pywebview.api.merge_name_issue(keep, drop); }
        catch (ex) { r = { ok: false, error: String(ex) }; }
        if (!r?.ok) {
          setStatus(`Fold failed: ${r?.error || "?"}`, "error");
          b.disabled = false; b.textContent = "Keep this name";
          return;
        }
        setStatus(`🧩 Folded into ${keep}`
          + ((r.carried || []).length ? ` · carried ${r.carried.join(", ")}` : ""), "ok");
        load();
      });
    });
    body.querySelectorAll(".ni-ignore").forEach((b) => {
      b.addEventListener("click", async () => {
        b.disabled = true;
        try { await pywebview.api.ignore_name_issue(b.dataset.pair, true); }
        catch (_) {}
        setStatus("Marked as different people — won't be offered again", "ok");
        load();
      });
    });
  };
  load();
}

function openOverviewPanel() {
  const overlay = createOverlay({
    title: "🩺 Job admin overview",
    sub:   "DocuSign · initial/final paperwork · weekly check-ins — click a — chip to stamp today.",
    body: `
      <div id="ov-board"></div>
      <div class="modal-footer"><button class="btn modal-close">Close</button></div>`,
  });
  const board = overlay.querySelector("#ov-board");
  if (window.HygieneBoard) {
    window.HygieneBoard.render(board, { api: pywebview.api, setStatus });
  } else {
    board.innerHTML = "Board renderer not loaded.";
  }
}

// ── Tracked notes (📝) ───────────────────────────────────────────
// To-do notes, tied to a job or loose. Check to mark done. Shared with the
// audit detail's "📝 Note" action (window.openAuditNotes).
async function updateNotesBadge() {
  const btn = document.getElementById("notes-btn");
  if (!btn) return;
  try {
    const r = await pywebview.api.notes_open_count("");
    const n = (r && r.count) || 0;
    btn.textContent = n ? `📝 Notes (${n})` : "📝 Notes";
  } catch (_) {}
}

function openNotesPanel(prefillJob) {
  const selClient = (() => {
    const r = findRowByKey(state.selected_client); return r ? r.client : "";
  })();
  const scopeJob = prefillJob || "";
  let filter = scopeJob || "all";       // "all" | "__untied__" | <client>
  let showDone = false;
  const chipJob = scopeJob || selClient;
  const overlay = createOverlay({
    title: "📝 Tracked notes",
    sub:   "To-dos tied to a job or loose — check to mark done.",
    body: `
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <input id="nt-text" class="search" type="text" placeholder="New note…" style="flex:1;" />
        <input id="nt-job" class="search" type="text" placeholder="Job (optional)" value="${escapeAttr(prefillJob || selClient || "")}" style="width:160px;" />
        <button class="btn btn-primary" id="nt-add-btn">➕ Add</button>
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
        <button class="btn nt-f" data-f="all">All</button>
        <button class="btn nt-f" data-f="__untied__">Loose</button>
        ${chipJob ? `<button class="btn nt-f" data-f="${escapeAttr(chipJob)}">🔗 ${escapeHtml(chipJob)}</button>` : ""}
        <span style="flex:1;"></span>
        <label style="font-size:12px;cursor:pointer;"><input type="checkbox" id="nt-showdone" /> Show done</label>
      </div>
      <div id="nt-list" class="target-list" style="max-height:340px;"></div>
      <div class="modal-footer"><button class="btn modal-close">Close</button></div>`,
  });
  const listEl = overlay.querySelector("#nt-list");

  const render = async () => {
    overlay.querySelectorAll(".nt-f").forEach((b) =>
      b.classList.toggle("active", b.dataset.f === filter));
    listEl.innerHTML = `<div class="muted" style="padding:8px;">Loading…</div>`;
    let notes = [];
    try {
      const res = await pywebview.api.notes_list(filter === "all" ? "" : filter, showDone);
      notes = (res && res.notes) || [];
    } catch (ex) { listEl.innerHTML = `Failed: ${escapeHtml(String(ex))}`; return; }
    if (!notes.length) {
      listEl.innerHTML = `<div class="muted" style="padding:10px;">No ${showDone ? "" : "open "}notes${filter !== "all" ? " here" : ""} — add one above.</div>`;
      return;
    }
    listEl.innerHTML = notes.map((n) => `
      <div class="nt-note" data-id="${n.id}" style="display:flex;gap:8px;align-items:flex-start;padding:8px 4px;border-bottom:1px solid var(--border);">
        <input type="checkbox" class="nt-done" ${n.done ? "checked" : ""} style="margin-top:3px;cursor:pointer;" title="Mark ${n.done ? "open" : "done"}" />
        <div style="flex:1;min-width:0;">
          <div class="nt-txt" style="font-size:13px;${n.done ? "text-decoration:line-through;color:var(--text-muted);" : ""}">${escapeHtml(n.text)}</div>
          <div style="font-size:10px;color:var(--text-muted);margin-top:2px;">${n.job ? `🔗 ${escapeHtml(n.job)} · ` : "loose · "}${escapeHtml((n.created_at || "").slice(0, 16))}${n.done && n.done_at ? ` · ✓ ${escapeHtml(n.done_at.slice(0, 10))}` : ""}</div>
        </div>
        <button class="nt-edit" title="Edit" style="background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:13px;">✏</button>
        <button class="nt-del" title="Delete" style="background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:13px;">✕</button>
      </div>`).join("");
    listEl.querySelectorAll(".nt-note").forEach((el) => {
      const id = parseInt(el.dataset.id, 10);
      el.querySelector(".nt-done").addEventListener("change", async (e) => {
        await pywebview.api.notes_set_done(id, e.target.checked);
        render(); updateNotesBadge();
      });
      el.querySelector(".nt-del").addEventListener("click", async () => {
        await pywebview.api.notes_delete(id); render(); updateNotesBadge();
      });
      el.querySelector(".nt-edit").addEventListener("click", async () => {
        const t = prompt("Edit note:", el.querySelector(".nt-txt").textContent);
        if (t != null && t.trim()) { await pywebview.api.notes_update(id, t.trim()); render(); }
      });
    });
  };

  const addNote = async () => {
    const text = overlay.querySelector("#nt-text").value.trim();
    const job = overlay.querySelector("#nt-job").value.trim();
    if (!text) { overlay.querySelector("#nt-text").focus(); return; }
    await pywebview.api.notes_add(text, job);
    overlay.querySelector("#nt-text").value = "";
    render(); updateNotesBadge();
  };
  overlay.querySelector("#nt-add-btn").addEventListener("click", addNote);
  overlay.querySelector("#nt-text").addEventListener("keydown", (e) => { if (e.key === "Enter") addNote(); });
  overlay.querySelectorAll(".nt-f").forEach((b) =>
    b.addEventListener("click", () => { filter = b.dataset.f; render(); }));
  overlay.querySelector("#nt-showdone").addEventListener("change", (e) => { showDone = e.target.checked; render(); });
  overlay.querySelector("#nt-text").focus();
  render();
}
window.openAuditNotes = openNotesPanel;

// ── Usage report (📊) ────────────────────────────────────────────
// Shows how the app is actually used — top tools, most-clicked buttons,
// and activity by day — from the local usage_tracker log. Read-only, no
// job data. Meant to guide what to streamline next.
async function openUsagePanel() {
  const overlay = createOverlay({
    title: "📊 My usage",
    sub:   "How you use the app — to find what to make faster. Local only, no job data.",
    body: `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <label class="modal-lbl" style="margin:0;">Last</label>
        <select id="us-days" class="search" style="width:120px;">
          <option value="7">7 days</option>
          <option value="30" selected>30 days</option>
          <option value="90">90 days</option>
          <option value="3650">All time</option>
        </select>
        <span style="flex:1;"></span>
        <button class="btn" id="us-reset" title="Erase the usage log">🗑 Reset log</button>
      </div>
      <div id="us-body" class="muted">Loading…</div>
      <div class="modal-footer"><button class="btn modal-close">Close</button></div>`,
  });
  const bodyEl = overlay.querySelector("#us-body");
  const daysSel = overlay.querySelector("#us-days");

  const bar = (n, max) => {
    const w = max > 0 ? Math.round((n / max) * 100) : 0;
    return `<span style="display:inline-block;height:9px;width:${w}%;min-width:2px;background:var(--green,#3D6549);border-radius:3px;vertical-align:middle;"></span>`;
  };

  const load = async () => {
    bodyEl.innerHTML = "Loading…";
    let rep;
    try { rep = await pywebview.api.usage_report(parseInt(daysSel.value, 10)); }
    catch (ex) { bodyEl.innerHTML = `Failed: ${escapeHtml(String(ex))}`; return; }
    if (!rep?.ok) { bodyEl.innerHTML = `Failed: ${escapeHtml(rep?.error || "?")}`; return; }
    if (!rep.total) {
      bodyEl.innerHTML = `<div style="padding:10px 0;">No usage recorded yet — use the app for a bit and check back. (Tracking is on; it logs buttons/tools, never job data.)</div>`;
      return;
    }
    const tools = rep.tools || [];
    const buttons = rep.buttons || [];
    const perDay = rep.per_day || [];
    const tMax = Math.max(...tools.map((t) => t.count), 1);
    const bMax = Math.max(...buttons.map((b) => b.count), 1);
    const dMax = Math.max(...perDay.map((d) => d.count), 1);
    bodyEl.innerHTML = `
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">
        ${rep.total.toLocaleString()} actions over ${rep.active_days} active day${rep.active_days === 1 ? "" : "s"}${rep.first ? ` · since ${escapeHtml(rep.first.slice(0, 10))}` : ""}
      </div>
      <h3 style="margin:6px 0;">Tools used</h3>
      <div class="us-table">${tools.map((t) => `
        <div style="display:grid;grid-template-columns:110px 1fr 44px;gap:8px;align-items:center;padding:2px 0;font-size:12px;">
          <span>${escapeHtml(t.tool)}</span>${bar(t.count, tMax)}<span style="text-align:right;color:var(--text-muted);">${t.count}</span>
        </div>`).join("")}</div>
      <h3 style="margin:14px 0 6px;">Most-used buttons</h3>
      <div class="us-table">${buttons.slice(0, 20).map((b) => `
        <div style="display:grid;grid-template-columns:1fr 44px;gap:8px;align-items:center;padding:2px 0;font-size:12px;">
          <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(b.label)} <span style="color:var(--text-dim,#6b7280);font-size:10px;">· ${escapeHtml(b.tool)}</span></span>
          <span style="text-align:right;color:var(--text-muted);">${b.count}</span>
        </div>`).join("")}</div>
      <h3 style="margin:14px 0 6px;">Activity by day</h3>
      <div class="us-table">${perDay.slice(-21).map((d) => `
        <div style="display:grid;grid-template-columns:80px 1fr 44px;gap:8px;align-items:center;padding:1px 0;font-size:11px;">
          <span style="color:var(--text-muted);">${escapeHtml(d.day.slice(5))}</span>${bar(d.count, dMax)}<span style="text-align:right;color:var(--text-muted);">${d.count}</span>
        </div>`).join("")}</div>`;
  };

  daysSel.addEventListener("change", load);
  overlay.querySelector("#us-reset")?.addEventListener("click", async () => {
    if (!confirm("Erase the entire usage log? This can't be undone.")) return;
    try { await pywebview.api.usage_reset(); } catch (_) {}
    load();
  });
  load();
}

// ── Quick-jump palette (Ctrl+K) ──────────────────────────────────
// Type a client → Enter opens it in Audit (selects the row + detail);
// 📸/📁 buttons jump to Snapshot / open the OD folder. No match → Enter
// runs a one-off audit of what was typed.
function openQuickJump() {
  if (document.getElementById("qj-input")) return;   // already open
  const overlay = createOverlay({
    title: "⚡ Quick jump",
    sub:   "Type a client · ↑↓ to move · Enter opens in Audit · 📸 Snapshot · 📁 OD",
    body: `
      <input id="qj-input" class="search" type="text" autocomplete="off" placeholder="Client name…" style="width:100%;" />
      <div id="qj-list" class="target-list" style="margin-top:8px;max-height:340px;"></div>`,
  });
  const input  = overlay.querySelector("#qj-input");
  const listEl = overlay.querySelector("#qj-list");
  let hits = [];
  let active = 0;

  const jumpAudit = (r) => {
    closeOverlay();
    state.search = "";
    const sb = $("#search-box"); if (sb) sb.value = "";
    state.filter = "all";
    state.selected_client = rowKey(r);
    renderList(); renderDetail();
    scrollSelectedIntoView();
    setStatus(`⚡ ${r.display_name || titleCase(r.client)}`, "");
  };

  const render = () => {
    const q = input.value.trim().toLowerCase();
    hits = (q
      ? state.rows.filter((r) =>
          (r.client || "").toLowerCase().includes(q) ||
          (r.display_name || "").toLowerCase().includes(q))
      : state.rows).slice(0, 10);
    if (active >= hits.length) active = Math.max(0, hits.length - 1);
    if (!hits.length) {
      listEl.innerHTML = q
        ? `<div class="muted" style="padding:8px;">No loaded job matches — press Enter to audit “${escapeHtml(input.value.trim())}” as a one-off.</div>`
        : `<div class="muted" style="padding:8px;">Start typing a client name…</div>`;
      return;
    }
    listEl.innerHTML = hits.map((r, i) => `
      <div class="target-row qj-hit" data-i="${i}" style="cursor:pointer;${i === active ? "background:var(--chip-active,#2d4636);" : ""}">
        <span>${r.flagged ? "🚩" : "✓"}</span>
        <div style="flex:1;min-width:0;">
          <div class="name">${escapeHtml(titleCase(r.display_name || r.client))}</div>
          <div style="font-size:10px;color:var(--text-muted);">${escapeHtml((r.techs || []).join(", "))}${r.unit ? ` · 🏢 ${escapeHtml(String(r.unit))}` : ""}</div>
        </div>
        <button class="btn qj-snap" data-i="${i}" title="Open in Snapshot" style="font-size:11px;padding:2px 7px;">📸</button>
        <button class="btn qj-od" data-i="${i}" title="Open OD folder" style="font-size:11px;padding:2px 7px;">📁</button>
      </div>`).join("");
    listEl.querySelectorAll(".qj-hit").forEach((el) => {
      el.addEventListener("click", (e) => {
        const i = parseInt(el.dataset.i, 10);
        if (e.target.closest(".qj-snap")) {
          closeOverlay();
          if (window.emsNavigateTo) window.emsNavigateTo("snapshot", hits[i].client);
          return;
        }
        if (e.target.closest(".qj-od")) { onDetailAction("open-folder", hits[i]); return; }
        jumpAudit(hits[i]);
      });
    });
  };

  input.addEventListener("input", () => { active = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, hits.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (hits[active]) jumpAudit(hits[active]);
      else { const t = input.value.trim(); if (t) { closeOverlay(); runOneoffFromSearch(t); } }
    } else if (e.key === "Escape") {
      closeOverlay();
    }
  });
  render();
  setTimeout(() => input.focus(), 30);
}

// ── Scope dialog (P0) ───────────────────────────────────────────
function openScopeDialog(row) {
  const overlay = createOverlay({
    title: "📋 Scope for " + row.client,
    sub:   "Paste a Trello-style room block, preview rooms, generate Scope.pdf",
    body: `
      <label class="modal-lbl">Paste scope text</label>
      <textarea id="sc-raw" class="modal-textarea" rows="8"
                placeholder="Living Room&#10;- Demo carpet&#10;- Replace baseboards&#10;&#10;Master Bedroom&#10;- Pack contents…"></textarea>
      <button class="btn" id="sc-parse" style="margin-top:8px;">🧪 Parse + preview</button>
      <div id="sc-preview" style="margin-top:12px;"></div>
      <div id="sc-dest" style="margin-top:12px;"></div>
      <div class="modal-footer">
        <button class="btn" id="sc-cancel">Cancel</button>
        <button class="btn btn-primary" id="sc-save" disabled>📄 Save PDF</button>
      </div>`,
  });
  let parsedRooms = [];
  // Destination state — what the backend resolved + any user override.
  let destState = { dir: "", filename: "", path: "", overridden: false };
  overlay.querySelector("#sc-cancel").addEventListener("click", closeOverlay);
  // Resolve + render the proposed save destination so the user can
  // verify (and correct) BEFORE saving. Runs on open + on demand.
  async function refreshDestination() {
    const destEl = overlay.querySelector("#sc-dest");
    destEl.innerHTML = `<div class="muted" style="font-size:11px;">Resolving destination…</div>`;
    const r = await pywebview.api.preview_scope_path(row.client);
    if (!r?.ok) {
      destState = { dir: "", filename: "", path: "", overridden: false };
      destEl.innerHTML = `
        <div style="background:rgba(192,57,43,.10);border:1px solid var(--red);border-radius:6px;padding:10px 14px;">
          <div style="font-weight:600;color:var(--red);">⚠ Can't auto-resolve destination</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${escapeHtml(r?.error || "?")}</div>
          <button class="btn" id="sc-pick-dir" style="margin-top:8px;">📁 Pick folder…</button>
        </div>`;
    } else {
      if (!destState.overridden) {
        destState = { dir: r.dir, filename: r.filename, path: r.path, overridden: false };
      }
      const overwrite = r.would_overwrite;
      destEl.innerHTML = `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">
            <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;">
              Save destination ${destState.overridden ? "(custom)" : "(auto-resolved)"}
            </div>
            <button class="btn" id="sc-pick-dir" style="font-size:11px;padding:4px 8px;">📁 Change folder…</button>
          </div>
          <div style="font-family:monospace;font-size:12px;word-break:break-all;color:var(--text);">
            ${escapeHtml(destState.dir)}
          </div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;">
            <span style="font-size:11px;color:var(--text-muted);">Filename:</span>
            <input id="sc-filename" type="text" value="${escapeAttr(destState.filename)}"
                   style="flex:1;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font:inherit;font-size:12px;font-family:monospace;" />
          </div>
          ${overwrite
            ? `<div style="margin-top:6px;font-size:11px;color:var(--amber);">⚠ A file with this name already exists — saving will overwrite it.</div>`
            : ""}
        </div>`;
      overlay.querySelector("#sc-filename").addEventListener("input", (e) => {
        destState.filename = e.target.value;
        destState.overridden = true;
      });
    }
    overlay.querySelector("#sc-pick-dir")?.addEventListener("click", async () => {
      const r = await pywebview.api.pick_scope_save_dir(destState.dir || row.path || "");
      if (r?.ok && r.path) {
        destState.dir = r.path;
        destState.overridden = true;
        refreshDestination();
      }
    });
  }
  refreshDestination();
  overlay.querySelector("#sc-parse").addEventListener("click", async () => {
    const raw = overlay.querySelector("#sc-raw").value;
    const res = await pywebview.api.parse_scope_text(raw);
    if (!res?.ok) {
      setStatus(`Parse failed: ${res?.error || "?"}`, "error");
      return;
    }
    parsedRooms = res.rooms || [];
    const html = parsedRooms.length
      ? parsedRooms.map((r) => `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:6px;">
          <div style="font-weight:600;color:var(--text);">${escapeHtml(r.name)}</div>
          <ul style="margin:6px 0 0;padding-left:20px;">
            ${r.items.map((it) => `<li style="font-size:12px;color:var(--text-muted);">${escapeHtml(it)}</li>`).join("")}
          </ul>
        </div>`).join("")
      : `<div class="muted">No rooms parsed — check formatting.</div>`;
    overlay.querySelector("#sc-preview").innerHTML = html;
    overlay.querySelector("#sc-save").disabled = parsedRooms.length === 0;
  });
  overlay.querySelector("#sc-save").addEventListener("click", async () => {
    const saveBtn = overlay.querySelector("#sc-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    // Pass the override dir/filename when the user changed either —
    // otherwise pass empty strings so save_scope re-resolves the
    // default destination on its own.
    const overrideDir = destState.overridden ? destState.dir : "";
    const overrideFilename = destState.overridden ? destState.filename : "";
    const res = await pywebview.api.save_scope(
      row.client, parsedRooms, overrideDir, overrideFilename);
    if (!res?.ok) {
      // Show the backend traceback inline so silent build failures
      // ("docs dir created but no PDF inside") become diagnosable.
      const errBody = res?.traceback
        ? `<div style="margin-top:8px;font-family:monospace;font-size:10px;color:var(--text-muted);white-space:pre-wrap;max-height:140px;overflow:auto;">${escapeHtml(res.traceback)}</div>`
        : "";
      setStatus(`Save failed: ${res?.error || "?"}`, "error");
      overlay.querySelector("#sc-dest").insertAdjacentHTML("beforeend",
        `<div style="margin-top:8px;background:rgba(192,57,43,.10);border:1px solid var(--red);border-radius:6px;padding:8px 12px;color:var(--red);font-size:12px;">
          <strong>Save failed:</strong> ${escapeHtml(res?.error || "?")}${errBody}
        </div>`);
      saveBtn.disabled = false;
      saveBtn.textContent = "📄 Save PDF";
      return;
    }
    // Replace the modal body with a "saved!" view showing the full
    // path + inline PDF preview + Open buttons. User wanted to know
    // (a) where the file went and (b) be able to see it in the
    // browser without leaving the panel.
    await showScopeSavedView(overlay, row.client, res.path);
    setStatus(`📄 Saved: ${res.path}`, "ok");
    // Re-audit since Scope was likely a missing form
    const reRes = await pywebview.api.reaudit_one(row.client);
    if (reRes?.ok) {
      applyRow(reRes.row);
      renderAll();
    }
  });
  overlay.querySelector("#sc-raw").focus();
}

async function showScopeSavedView(overlay, client, pdfPath) {
  // Pull the PDF bytes as base64 so we can embed it inline. file://
  // URLs aren't reliable from a pywebview-served page origin; the
  // data: URL works everywhere.
  const bodyEl = overlay.querySelector(".overlay-body");
  bodyEl.innerHTML = `
    <div style="background:rgba(46,204,113,.10);border:1px solid var(--green);border-radius:6px;padding:10px 14px;margin-bottom:12px;display:flex;gap:10px;align-items:center;">
      <span style="font-size:18px;">✅</span>
      <div style="flex:1;">
        <div style="font-weight:700;color:var(--green);">Scope PDF saved</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;font-family:monospace;word-break:break-all;">${escapeHtml(pdfPath)}</div>
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
      <button class="btn" id="sc-open-folder">📁 Reveal in Explorer</button>
      <button class="btn" id="sc-open-pdf">🗂 Open PDF in default app</button>
    </div>
    <div id="sc-preview-pane" style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;height:480px;overflow:hidden;">
      <div class="muted" style="padding:14px;">Loading preview…</div>
    </div>
    <div class="modal-footer">
      <button class="btn modal-close">Close</button>
    </div>`;
  // Re-bind the modal close handler — the original .modal-close on
  // the header X still works, but Cancel/Close in the new footer
  // needs the click handler too.
  bodyEl.querySelectorAll(".modal-close").forEach((b) =>
    b.addEventListener("click", closeOverlay));
  bodyEl.querySelector("#sc-open-folder").addEventListener("click",
    () => pywebview.api.reveal_in_explorer(pdfPath));
  bodyEl.querySelector("#sc-open-pdf").addEventListener("click",
    () => pywebview.api.open_file(pdfPath));
  // Load + embed the PDF preview
  try {
    const pdf = await pywebview.api.read_pdf_b64(pdfPath);
    const pane = bodyEl.querySelector("#sc-preview-pane");
    if (!pdf?.ok) {
      pane.innerHTML = `<div class="muted" style="padding:14px;">Preview unavailable: ${escapeHtml(pdf?.error || "?")}</div>`;
      return;
    }
    pane.innerHTML = `<embed type="application/pdf"
                              src="data:application/pdf;base64,${pdf.b64}"
                              style="width:100%;height:100%;border:0;" />`;
  } catch (err) {
    const pane = bodyEl.querySelector("#sc-preview-pane");
    pane.innerHTML = `<div class="muted" style="padding:14px;">Preview failed: ${escapeHtml(String(err))}</div>`;
  }
}

// ── Past-claims jump list ───────────────────────────────────────
// Lists the claim / date sibling folders in a job's directory so the
// user can open a PAST claim (older "Nth Claim" or a date-named folder
// like "9-20-25"). Backed by audit_logic.list_claim_folders.
function showClaimFoldersModal(row, folders) {
  document.getElementById("claims-modal")?.remove();
  const rowsHtml = folders.map((f) => `
    <button class="claim-row" data-path="${escapeHtml(f.path)}"
      style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:10px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font:inherit;color:var(--text);">
      <span style="font-size:15px;">${f.kind === "date" ? "📅" : "🗂"}</span>
      <span style="flex:1;">${escapeHtml(f.name)}</span>
      ${f.is_current ? '<span style="font-size:10px;color:var(--green);font-weight:700;letter-spacing:.04em;">CURRENT</span>' : ""}
      <span class="muted" style="font-size:11px;">Open ↗</span>
    </button>`).join("");
  const wrap = document.createElement("div");
  wrap.id = "claims-modal";
  wrap.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(520px,92vw);max-height:80vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:14px;font-weight:600;">🗂 Past claims · ${escapeHtml(row.client)}</div>
        <div class="muted" style="font-size:11px;margin-top:2px;">${folders.length} claim/date folder${folders.length === 1 ? "" : "s"} in this job's directory</div>
      </header>
      <div style="padding:14px 18px;display:flex;flex-direction:column;gap:8px;overflow-y:auto;">${rowsHtml}</div>
      <footer style="padding:10px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:flex-end;">
        <button class="btn" id="claims-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector("#claims-close").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  wrap.querySelectorAll(".claim-row").forEach((b) =>
    b.addEventListener("click", async () => {
      const ok = await pywebview.api.open_folder(b.dataset.path);
      setStatus(ok ? `📁 Opened ${b.dataset.path}` : "Couldn't open folder", ok ? "ok" : "warn");
    }));
}

// Shows the actual folders + files inside a job's OD folder without
// leaving the app. Folders drill in (breadcrumb 'up'); files show size
// and a ☁/✓ badge marking OneDrive cloud-only placeholders vs. downloaded
// files. Backed by Api.od_contents; clicking opens folders/files.
function showOdContentsModal(row, startPath) {
  if (!startPath) {
    setStatus("No OD folder resolved yet — use Find/Change folder first", "warn");
    return;
  }
  document.getElementById("od-contents-modal")?.remove();
  const stack = [];            // breadcrumb of parent paths
  let curPath = startPath;
  const fmtSize = (n) => {
    if (!n) return "0 B";
    const u = ["B", "KB", "MB", "GB"]; let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return (i === 0 ? v : v.toFixed(1)) + " " + u[i];
  };
  const wrap = document.createElement("div");
  wrap.id = "od-contents-modal";
  wrap.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(620px,94vw);max-height:82vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:14px;font-weight:600;">📁 OD contents · ${escapeHtml(row.client)}</div>
        <div class="muted" id="od-crumb" style="font-size:11px;margin-top:2px;word-break:break-all;"></div>
      </header>
      <div id="od-list" style="padding:14px 18px;display:flex;flex-direction:column;gap:6px;overflow-y:auto;">Loading…</div>
      <footer style="padding:10px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <button class="btn" id="od-up" style="visibility:hidden;">↑ Up</button>
        <div style="display:flex;gap:8px;">
          <button class="btn" id="od-open">📂 Open in Explorer</button>
          <button class="btn" id="od-close">Close</button>
        </div>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector("#od-close").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  const upBtn = wrap.querySelector("#od-up");
  upBtn.addEventListener("click", () => { if (stack.length) { curPath = stack.pop(); load(); } });
  wrap.querySelector("#od-open").addEventListener("click", async () => {
    const ok = await pywebview.api.open_folder(curPath);
    setStatus(ok ? `📁 Opened ${curPath}` : "Couldn't open folder", ok ? "ok" : "warn");
  });
  async function load() {
    const listEl = wrap.querySelector("#od-list");
    wrap.querySelector("#od-crumb").textContent = curPath;
    upBtn.style.visibility = stack.length ? "visible" : "hidden";
    listEl.textContent = "Loading…";
    let r;
    try { r = await pywebview.api.od_contents(curPath); }
    catch (e) { listEl.textContent = "Error: " + e; return; }
    if (!r || !r.ok) { listEl.textContent = (r && r.error) || "Couldn't read folder"; return; }
    const folders = r.folders || [], files = r.files || [];
    if (!folders.length && !files.length) {
      listEl.innerHTML = '<div class="muted" style="padding:8px;">(empty folder)</div>';
      return;
    }
    const foldersHtml = folders.map((f) => `
      <button class="od-folder" data-path="${escapeHtml(f.path)}"
        style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:8px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font:inherit;color:var(--text);">
        <span>📁</span><span style="flex:1;">${escapeHtml(f.name)}</span>
        <span class="muted" style="font-size:11px;">Open ↘</span>
      </button>`).join("");
    const filesHtml = files.map((f) => `
      <button class="od-file" data-path="${escapeHtml(f.path)}"
        style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:8px 10px;background:transparent;border:1px solid transparent;border-radius:6px;cursor:pointer;font:inherit;color:var(--text);">
        <span>📄</span><span style="flex:1;">${escapeHtml(f.name)}</span>
        <span class="muted" style="font-size:11px;">${fmtSize(f.size)}</span>
        <span title="${f.cloud_only ? "Online-only (not downloaded)" : "Downloaded to this PC"}" style="font-size:12px;">${f.cloud_only ? "☁" : "✓"}</span>
      </button>`).join("");
    listEl.innerHTML =
      (folders.length ? `<div class="muted" style="font-size:10px;letter-spacing:.05em;">FOLDERS · ${folders.length}</div>${foldersHtml}` : "") +
      (files.length ? `<div class="muted" style="font-size:10px;letter-spacing:.05em;margin-top:8px;">FILES · ${files.length}</div>${filesHtml}` : "");
    listEl.querySelectorAll(".od-folder").forEach((b) =>
      b.addEventListener("click", () => { stack.push(curPath); curPath = b.dataset.path; load(); }));
    listEl.querySelectorAll(".od-file").forEach((b) =>
      b.addEventListener("click", async () => {
        const ok = await pywebview.api.open_file(b.dataset.path);
        if (!ok) setStatus("Couldn't open file", "warn");
      }));
  }
  load();
}

// Per-job JOB TRACKER — one newest-first timeline weaving the run-doc
// activity (with the crew each day) together with the Trello upload
// history (who uploaded which form/photo, when). Backed by
// Api.job_work_log (→ job_history.job_tracker); 💾 writes a .md doc.
function showWorkLogModal(row) {
  if (!row.client) { setStatus("No client on this row", "warn"); return; }
  document.getElementById("worklog-modal")?.remove();
  const wrap = document.createElement("div");
  wrap.id = "worklog-modal";
  wrap.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(600px,94vw);max-height:82vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:14px;font-weight:600;">📖 Job tracker · ${escapeHtml(titleCase(row.client))}</div>
        <div class="muted" id="wl-sub" style="font-size:11px;margin-top:2px;">compiling activity + uploads…</div>
      </header>
      <div id="wl-list" style="padding:14px 18px;display:flex;flex-direction:column;gap:4px;overflow-y:auto;">
        <div class="muted" style="padding:8px;">⏳ Scanning run docs + Trello…</div>
      </div>
      <footer style="padding:10px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <span class="muted" id="wl-saved" style="font-size:11px;"></span>
        <div style="display:flex;gap:8px;">
          <button class="btn" id="wl-save" disabled>💾 Save as doc</button>
          <button class="btn" id="wl-close">Close</button>
        </div>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector("#wl-close").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  const saveBtn = wrap.querySelector("#wl-save");
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    const r = await pywebview.api.save_job_work_log(row.client);
    if (r && r.ok) {
      wrap.querySelector("#wl-saved").textContent = "saved · opening…";
      await pywebview.api.open_file(r.path);
      setStatus("📖 Job tracker saved & opened", "ok");
    } else {
      setStatus((r && r.error) || "Couldn't save tracker", "warn");
    }
    saveBtn.disabled = false; saveBtn.textContent = "💾 Save as doc";
  });
  (async () => {
    const listEl = wrap.querySelector("#wl-list");
    let r;
    try { r = await pywebview.api.job_work_log(row.client); }
    catch (e) { listEl.textContent = "Error: " + e; return; }
    if (!r || !r.ok) { listEl.textContent = (r && r.error) || "Couldn't build tracker"; return; }
    const timeline = r.timeline || [];
    const a = r.activity_count || 0, u = r.upload_count || 0;
    wrap.querySelector("#wl-sub").textContent = timeline.length
      ? `${a} activity · ${u} upload${u === 1 ? "" : "s"} — newest first`
      : "no activity or uploads found";
    if (r.saved_path) wrap.querySelector("#wl-saved").textContent = "saved doc exists";
    saveBtn.disabled = false;
    if (!timeline.length) {
      listEl.innerHTML = '<div class="muted" style="padding:8px;">No run-doc activity or Trello uploads for this job yet.</div>';
      return;
    }
    listEl.innerHTML = timeline.map((h) => {
      if (h.kind === "upload") {
        const who = h.uploader ? `<span style="color:var(--green);">${escapeHtml(h.uploader)}</span>` : '<span class="muted">unknown</span>';
        return `
          <div style="display:flex;gap:10px;align-items:baseline;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:transparent;" title="${escapeHtml(h.file || "")}">
            <span style="min-width:58px;font-variant-numeric:tabular-nums;font-weight:600;font-size:12px;">${escapeHtml(h.date_str || "—")}</span>
            <span style="flex:1;font-size:13px;">${h.is_image ? "📷" : "📎"} ${escapeHtml(h.file || "(file)")}</span>
            <span style="font-size:11px;">⬆ ${who}</span>
          </div>`;
      }
      const techs = (h.techs || []).length
        ? `<span style="font-size:11px;color:var(--act-monitor,#4A9EFF);">👷 ${escapeHtml(h.techs.join(", "))}</span>`
        : "";
      const slot = h.time_slot ? `<span class="muted" style="font-size:10px;">${escapeHtml(h.time_slot)}</span>` : "";
      // The full run-doc line is the "note" — show it collapsed, expand
      // on click, but only when it actually adds detail beyond the work
      // summary (recognized stages: work="Demo", note=the whole line).
      const noteText = (h.raw || "").trim();
      const hasNote = noteText && noteText !== (h.work || "").trim();
      const caret = hasNote
        ? `<span class="wl-caret" style="cursor:pointer;user-select:none;font-size:10px;color:var(--text-muted);width:10px;">▸</span>`
        : `<span style="width:10px;display:inline-block;"></span>`;
      return `
        <div class="wl-entry">
          <div class="wl-head" style="display:flex;gap:8px;align-items:baseline;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);${hasNote ? "cursor:pointer;" : ""}">
            ${caret}
            <span style="min-width:52px;font-variant-numeric:tabular-nums;font-weight:600;font-size:12px;">${escapeHtml(h.date_str || "—")}</span>
            <span style="flex:1;font-size:13px;">🔧 ${escapeHtml(h.work || "—")} ${slot}</span>
            ${techs}
          </div>
          ${hasNote ? `<div class="wl-note" style="display:none;font-size:12px;color:var(--text-muted);white-space:pre-wrap;padding:6px 10px 8px 30px;">📝 ${escapeHtml(noteText)}</div>` : ""}
        </div>`;
    }).join("");
    // Click an entry with a note to expand/collapse the run-doc detail.
    listEl.querySelectorAll(".wl-entry").forEach((el) => {
      const note = el.querySelector(".wl-note");
      const caret = el.querySelector(".wl-caret");
      const head = el.querySelector(".wl-head");
      if (!note || !caret || !head) return;
      head.addEventListener("click", () => {
        const open = note.style.display !== "none";
        note.style.display = open ? "none" : "";
        caret.textContent = open ? "▸" : "▾";
      });
    });
  })();
}

// ── Right-click context menu (P0) ───────────────────────────────
function showCtxMenu(ev, row, customItems) {
  ev.preventDefault();
  ev.stopPropagation();
  document.getElementById("ctx-menu")?.remove();
  const m = document.createElement("div");
  m.id = "ctx-menu";
  m.className = "ctx-menu";
  // Position first, then clamp to viewport after measuring.
  m.style.left = ev.clientX + "px";
  m.style.top = ev.clientY + "px";
  m.style.visibility = "hidden";
  // `customItems` (3rd arg) lets button-level handlers show a tiny
  // 1-item menu without rebuilding the giant row-level menu. Mirrors
  // the OD-folder right-click pattern: small focused menu next to the
  // thing you clicked.
  // Low-use power/memory items collapsed under "Advanced ▸" (usage audit
  // 2026-07-29: each 0 clicks in 7 days — kept, not deleted, just demoted).
  const advancedItems = [
    { label: "📖 Job tracker (activity + who)…",
      action: () => onDetailAction("work-log", row) },
    { label: "📄 Show OD files/folders…",
      action: () => onDetailAction("od-contents", row),
      disabled: !row.path },
    { label: "🧠 Client memory…",
      action: () => openClientMemoryModal(row) },
    { label: "🏷 Edit search aliases…",
      action: () => openSearchAliasesModal(row) },
    { label: "🏢 Add to property…",
      action: () => openAddToPropertyModal(row) },
    { label: "🧹 Clear saved folder path",
      action: async () => {
        if (!confirm(`Clear the sticky folder pin for ${row.client}?\nAudit will re-auto-resolve on the next run.`)) return;
        const r = await pywebview.api.clear_folder_path(row.client);
        if (!r?.ok) { setStatus(`Clear failed: ${r?.error || "?"}`, "error"); return; }
        setStatus(`🧹 Cleared folder pin for ${row.client}`, "ok");
        const re = await pywebview.api.reaudit_one(row.client);
        if (re?.ok) {
          applyRow(re.row);
          renderAll();
        }
      },
      disabled: !row.path },
    { label: "🏢 Clear Commercial flag",
      action: async () => {
        if (!confirm(`Un-mark ${row.client} as Commercial?`)) return;
        const r = await pywebview.api.set_commercial(row.client, false);
        if (!r?.ok) { setStatus(`Toggle failed: ${r?.error || "?"}`, "error"); return; }
        setStatus(`🏢 ${row.client} no longer marked Commercial`, "ok");
        const re = await pywebview.api.reaudit_one(row.client);
        if (re?.ok) {
          applyRow(re.row);
          renderAll();
        }
      },
      disabled: !row.is_commercial },
    { label: `♻ Reset all memory for ${row.client}`,
      action: async () => {
        if (!confirm(`Wipe every sticky pin + flag for ${row.client}?\n\n` +
                     `Clears: folder pin, Trello pins, Commercial flag, aliases.\n` +
                     `Audit will re-auto-resolve everything on the next run.`)) return;
        const r = await pywebview.api.reset_client_memory(row.client);
        if (!r?.ok) { setStatus(`Reset failed: ${r?.error || "?"}`, "error"); return; }
        setStatus(`♻ Reset for ${row.client}: ${(r.cleared || []).join(", ")}`, "ok");
        const re = await pywebview.api.reaudit_one(row.client);
        if (re?.ok) {
          applyRow(re.row);
          renderAll();
        }
      } },
  ];
  // Multi-unit-only actions surface ONLY on umbrella / unit / subjob rows
  // (audit: 0 clicks because they're situational, not useless).
  const isMultiUnit = !!(row.is_parent || row.subjob || row.unit || row.parent_canon);
  const muItems = isMultiUnit ? [
    { label: "🏠 Pick day-units…",
      action: () => openDayUnitsModal(row),
      disabled: !row.path },
    { label: "🏢 Property structure & settings…",
      action: () => openPropertyStructureModal(row) },
  ] : [];
  const items = customItems || [
    // Cross-tool jump (Audit excluded — we're already here). Switches the
    // shell's view to the target tool, focused on this client.
    { label: "📸 Open in Snapshot",
      action: () => window.emsNavigateTo?.("snapshot", row.client) },
    { sep: true },
    { label: "📁 Open OD folder",
      action: () => onDetailAction("open-folder", row) },
    { label: "🗂 Past claims…",
      action: () => onDetailAction("claim-folders", row),
      disabled: !row.path },
    { label: row.found ? "🔀 Change folder…" : "🔎 Find folder…",
      action: () => openFindFolderModal(row) },
    { iconImg: "../web_shared/trello.png", label: "Open Trello card", action: () => pywebview.api.open_trello_card(row.trello_card_id), disabled: !row.trello_card_id },
    { iconImg: "../web_shared/xactanalysis.png", label: "Open XactAnalysis", action: async () => { const ok = await pywebview.api.open_xa_link(row.client, row.trello_card_id || ""); if (!ok) setStatus("No XactAnalysis link on this card yet — add an 'EMS Xactanalysis Link' line to the card's LINKS section.", "warn"); }, disabled: !row.trello_card_id },
    { iconImg: "../web_shared/companycam.png", label: "Open CompanyCam", action: async () => {
        const ok = await pywebview.api.open_companycam_link(row.client);
        if (!ok) setStatus("No CompanyCam link on this card yet", "warn");
      }, disabled: !row.trello_card_id },
    { label: "📎 Trello attachments…",
      action: () => window.openTrelloAttachmentsModal({ cardId: row.trello_card_id, client: row.client }),
      disabled: !row.trello_card_id },
    { sep: true },
    { label: "📥 Import from SharePoint…", action: () => openSpImportModal(row) },
    { label: "📂 Stage PICS for XA (drag-and-drop)…",
      action: () => openCopyPicsToXaModal(row),
      disabled: !row.path },
    ...muItems,
    { label: "📨 Request paperwork via Teams…",
      action: () => openPaperworkRequestModal(row) },
    { sep: true },
    { label: "📐 Request Docusketch",
      action: async () => {
        if (!confirm(`Post Docusketch request comment on ${row.client}'s Trello card?`)) return;
        const r = await pywebview.api.request_docusketch(row.client, row.trello_card_id || "");
        if (!r?.ok) { setStatus(`Docusketch request failed: ${r?.error || "?"}`, "error"); return; }
        setStatus(r.posted
          ? `📐 Docusketch request posted to Trello`
          : "📐 Recorded — comment failed, post manually", "ok");
      },
      disabled: !row.trello_card_id },
    { label: "↻ Re-audit this job", action: () => doReaudit(row) },
    { label: "📋 Copy client name", action: () => copyText(row.client) },
    { label: "📋 Copy claim #", disabled: !row.trello_card_id,
      action: async () => {
        const res = await pywebview.api.get_claim_number(row.client);
        if (res?.ok && res.claim) {
          const ok = await copyText(res.claim);
          setStatus(ok ? `📋 Copied claim #: ${res.claim}` : "Couldn't copy",
                    ok ? "ok" : "error");
        } else { setStatus(res?.error || "No claim # found", "warn"); }
      } },
    { sep: true },
    { label: "🧠 Advanced ▸",
      action: () => showCtxMenu(
        { preventDefault() {}, stopPropagation() {}, clientX: ev.clientX, clientY: ev.clientY },
        row, advancedItems) },
  ];
  m.innerHTML = items.map((it) => {
    if (it.sep) return `<div class="ctx-sep"></div>`;
    const iconHtml = it.iconImg
      ? `<img class="ctx-icon" src="${it.iconImg}" alt="" />`
      : "";
    return `<button class="ctx-item ${it.disabled ? "disabled" : ""}" data-i="${items.indexOf(it)}">${iconHtml}${escapeHtml(it.label)}</button>`;
  }).join("");
  document.body.appendChild(m);
  // Clamp position so the menu stays inside the viewport. After
  // appending we can measure offsetWidth/Height; flip to the left
  // /top of the click point when there's not enough room.
  const margin = 6;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const rect = m.getBoundingClientRect();
  let left = ev.clientX;
  let top = ev.clientY;
  if (left + rect.width + margin > vw)  left = Math.max(margin, vw - rect.width - margin);
  if (top + rect.height + margin > vh)  top = Math.max(margin, vh - rect.height - margin);
  m.style.left = left + "px";
  m.style.top = top + "px";
  m.style.visibility = "visible";
  m.querySelectorAll("[data-i]").forEach((b) => {
    const it = items[+b.dataset.i];
    if (it.disabled) return;
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      m.remove();
      it.action();
    });
  });
}

// ── Run / re-run audit ──────────────────────────────────────────
async function runAudit(useCache) {
  if (state.loading) return;
  state.loading = true;
  $("#run-btn").disabled = true;
  $("#rerun-btn").disabled = true;
  $("#loading-label").textContent = useCache
    ? "Running audit (cached)…"
    : "Full re-scan in progress…";
  $("#loading-state").classList.remove("hidden");
  setStatus("");
  try {
    const res = await pywebview.api.run_audit(useCache);
    if (!res || !res.started) {
      setStatus(res?.reason || "Couldn't start audit", "warn");
      $("#loading-state").classList.add("hidden");
      state.loading = false;
      $("#run-btn").disabled = false;
      $("#rerun-btn").disabled = false;
    }
  } catch (ex) {
    setStatus(`Audit error: ${ex}`, "error");
    state.loading = false;
    $("#loading-state").classList.add("hidden");
    $("#run-btn").disabled = false;
    $("#rerun-btn").disabled = false;
  }
}

function onAuditProgress(ev) {
  const { i, n, client } = ev.detail || {};
  $("#loading-label").textContent =
    `Auditing ${i}/${n} · ${client || "…"}`;
}

// Streamed SP enrichment — runs after audit:done. Each call updates
// the SP fields on one row + re-renders the list/detail so the chip
// appears as soon as enrich finishes for that client.
function onSpUpdate(ev) {
  const d = ev.detail || {};
  if (!d.client) return;
  // SP enrichment fires per CLIENT NAME (it's keyed off the property
  // folder, not per-unit). Update every row whose client matches so
  // both Avila Apartments rows (Unit 1413 + Unit 1416) pick up the
  // chip together.
  let touched = 0;
  for (const r of state.rows) {
    if (r.client === d.client) {
      r.sharepoint_matches = d.sharepoint_matches || [];
      r.sharepoint_new     = d.sharepoint_new || 0;
      r.pics_count         = d.pics_count || 0;
      touched++;
    }
  }
  if (!touched) return;
  renderStats();
  renderList();
  // Refresh detail when the currently-selected row is one of the
  // updated ones (any unit of this property).
  const sel = findRowByKey(state.selected_client);
  if (sel && sel.client === d.client) renderDetail();
}

function onSpDone() {
  // Background SP scan finished — show a one-line confirmation in
  // the status bar (no overlay since the audit was already "done").
  const total = state.rows.reduce((n, r) => n + (r.sharepoint_new || 0), 0);
  if (total > 0) {
    setStatus(`📥 SP scan complete — ${total} new file${total !== 1 ? "s" : ""} available across rows`, "ok");
  } else {
    setStatus("✓ SP scan complete — no new files", "ok");
  }
}

function onAuditDone(ev) {
  const { ok, rows, meta, error } = ev.detail || {};
  state.loading = false;
  $("#loading-state").classList.add("hidden");
  $("#run-btn").disabled = false;
  $("#rerun-btn").disabled = false;
  // You changed day while this was running: these rows are for the day you
  // left. Drop them and run the day now on screen — rendering them first
  // would flash the wrong day's jobs.
  const staleDay = state.auditForDay !== undefined &&
                   state.auditForDay !== (state.dayOffset || 0);
  if (state.queuedAudit || staleDay) {
    if (!state.queuedAudit) state.queuedAudit = { useCache: true, day: state.dayOffset || 0 };
    _drainQueuedAudit();
    return;
  }
  if (!ok) {
    setStatus(`Audit failed: ${error || "unknown"}`, "error");
    return;
  }
  // If you navigated to another tab while the run was loading, DON'T yank
  // you back to Daily Run. The fresh rows are cached on the backend, so
  // switching back to Daily (which calls last_audit) shows them then. Just
  // note completion in the status bar.
  if (state.mode !== "daily") {
    setStatus(
      `✓ Daily Run finished in background · ${meta?.flagged || 0} flagged / ${meta?.ok || 0} OK`,
      "ok");
    return;
  }
  state.rows = rows || [];
  state.meta = meta || {};
  // Auto-select first flagged job (most useful to attend to), else
  // the first row.
  if (!state.selected_client && state.rows.length) {
    const firstFlagged = state.rows.find((r) => r.flagged);
    state.selected_client = rowKey(firstFlagged || state.rows[0]);
  }
  renderAll();
  const refreshBits = state.meta.use_cache
    ? `${state.meta.rechecked || 0} rechecked · ${state.meta.cached || 0} unchanged`
    : `${state.meta.rechecked || state.meta.total || 0} rechecked · full scan`;
  setStatus(
    `Audit complete · ${state.meta.flagged || 0} flagged / ${state.meta.ok || 0} OK · ${refreshBits}`,
    "ok");
}

// Stable per-row identifier — the same property name can appear
// multiple times on a single run-doc with different units (Avila
// Apartments Unit 1413 + Unit 1416 on Tue 5/26 is the canonical
// case). The backend ships `row_key` when it exists; we fall back
// to `client` so older cached rows / one-off audits keep working.
function rowKey(r) {
  return r?.row_key || r?.client || "";
}

// ── Render ───────────────────────────────────────────────────────
function renderAll() {
  renderStats();
  renderList();
  renderDetail();
}

function renderStats() {
  // Stats bar (Total / Flagged / OK / SP tiles) removed in the 2026-07
  // streamline — no-op kept so existing renderAll() call sites don't break.
}

function renderList() {
  const body = $("#list-body");
  // "✕ Clear results" only exists when there's something to clear — the
  // searched jobs now persist, so there has to be a way to empty them.
  const clearBtn = $("#clear-oneoff-btn");
  if (clearBtn) {
    // Only on Recent, where those results are actually visible — offering
    // to clear something you can't see is just a confusing button.
    const n = state.mode === "search" ? (state.oneoffHits || []).length : 0;
    clearBtn.classList.toggle("hidden", n === 0);
    clearBtn.textContent = n > 1 ? `✕ Clear ${n}` : "✕ Clear result";
  }
  const filtered = filterRows();
  // If the selected job dropped out of the filter, fall back to first.
  // Selection keys off `rowKey(r)` so two rows for the same property
  // (e.g. Avila Apartments Unit 1413 + Unit 1416) are individually
  // selectable instead of collapsing to a single client name.
  if (filtered.length && !filtered.find((r) => rowKey(r) === state.selected_client)) {
    state.selected_client = rowKey(filtered[0]);
  } else if (!filtered.length) {
    state.selected_client = null;
  }

  if (filtered.length === 0) {
    const q = state.search.trim();
    if (q) {
      // Don't claim "no jobs match" while we're still looking. The loaded
      // list not matching is NOT the answer — a one-off audit resolves the
      // folder and audits it, and only when THAT comes back empty is the
      // job genuinely not found. `queued` covers the debounce window,
      // where the lookup hasn't started but is about to.
      const queued = q.length >= 3
        && q.toLowerCase() !== (state.oneoffTried || "").toLowerCase();
      if (state.oneoffRunning || queued) {
        body.innerHTML =
          `<div class="list-empty">🔍 Searching “${escapeHtml(q)}”…</div>`;
      } else if (q.length < 3) {
        // Too short to trigger a lookup — you're still typing, so this
        // isn't a "not found" either.
        body.innerHTML =
          `<div class="list-empty muted">Keep typing to search…</div>`;
      } else {
        body.innerHTML =
          `<div class="list-empty">No job found for “${escapeHtml(q)}”.`
          + `<br><button class="btn" id="oneoff-search-btn" style="margin-top:8px;">`
          + `🔍 Search again</button></div>`;
        const b = document.getElementById("oneoff-search-btn");
        if (b) b.addEventListener("click", () => {
          state.oneoffTried = "";      // allow the same term to re-run
          runOneoffFromSearch(q);
        });
      }
    } else {
      body.innerHTML = `<div class="list-empty">No jobs match.</div>`;
    }
    $("#list-count").textContent = `0 / ${state.rows.length} jobs`;
    $("#status-counts").textContent =
      `0 shown · ${state.rows.length} total`;
    return;
  }

  // Collapsed-on-startup: the first time a set of umbrella parents shows,
  // start them collapsed so a big multi-unit/campus property doesn't eat
  // the whole list. Only referenced children peek through (renderSubjobGroup
  // keeps the header + collapsed body). Manual expands persist for the
  // session; a fresh audit re-seeds any newly-seen parents as collapsed.
  for (const r of filtered) {
    const pk = (r.claim_origin || "").toLowerCase();
    if (pk && !_seenParentKeys.has(pk)) {
      _seenParentKeys.add(pk);
      collapsedParents.add(pk);
    }
  }

  body.innerHTML = buildListHtml(filtered);
  // ➕ create-missing-unit / 📁 open-parent — one delegated handler on the
  // list body (guards against double-wiring internally). After a create,
  // re-run the audit so the new folder shows up populated.
  if (window.UmbrellaGroup) {
    window.UmbrellaGroup.wire(body, {
      api: pywebview.api,
      setStatus,
      onCreated: (res) => { if (res && res.ok) runAudit(false); },
    });
    // ⚠ loose-files chip — flag (don't move) photos sitting in a property
    // root that never made it into a unit. Filled async per umbrella so
    // the initial paint isn't blocked on N scandir calls.
    body.querySelectorAll(".umb-loose-slot[data-umbrella]").forEach((slot) => {
      const u = slot.dataset.umbrella;
      if (!u) return;
      pywebview.api.count_loose_parent_photos(u).then((res) => {
        if (res && res.count) {
          slot.innerHTML = window.UmbrellaGroup.looseChipHTML(res.count);
        }
      }).catch(() => {});
    });
  }
  body.querySelectorAll(".list-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      // Caret on a multi-unit umbrella → reveal/hide the property's OTHER
      // units (lazily fetched from disk). Checked before the campus caret
      // since a unit caret also carries the .subjob-caret class.
      const unitCaret = e.target.closest(".unit-caret");
      if (unitCaret) {
        e.stopPropagation();
        const key = unitCaret.dataset.unitKey;
        if (expandedUnitGroups.has(key)) {
          expandedUnitGroups.delete(key);
          renderList();
        } else {
          expandedUnitGroups.add(key);
          if (!unitSiblingsCache.has(key)) {
            const match = state.rows.find(
              (r) => (r.client || "").toLowerCase() === key);
            const client = (match && match.client) || key;
            renderList();   // shows the "Loading…" ghost row
            pywebview.api.list_day_units(client).then((res) => {
              const units = (res && res.units) || [];
              unitSiblingsCache.set(key,
                units.map((u) => ({ name: u.name, path: u.path })));
              renderList();
            }).catch(() => { unitSiblingsCache.set(key, []); renderList(); });
          } else {
            renderList();
          }
        }
        return;
      }
      // Caret on a commercial-parent header → collapse/expand its
      // campuses, don't select the row.
      const caret = e.target.closest(".subjob-caret");
      if (caret) {
        e.stopPropagation();
        const key = caret.dataset.parentKey;
        if (collapsedParents.has(key)) collapsedParents.delete(key);
        else collapsedParents.add(key);
        renderList();
        return;
      }
      // Star button click → toggle, don't select the row.
      if (e.target.closest(".star-btn")) {
        e.stopPropagation();
        const client = row.dataset.client;
        toggleStarred(client);
        return;
      }
      // Bulk checkbox → toggle selection, don't activate the row.
      if (e.target.closest(".bulk-cb")) {
        e.stopPropagation();
        const client = row.dataset.client;
        if (state.selected_set.has(client)) state.selected_set.delete(client);
        else state.selected_set.add(client);
        row.classList.toggle("bulk-selected", state.selected_set.has(client));
        renderBulkToolbar();
        return;
      }
      // Selection keys off row_key so two Avila Apartments rows
      // (Unit 1413 + Unit 1416) are individually selectable.
      state.selected_client = row.dataset.rowKey || row.dataset.client;
      // Opening a job from Recents is fresh activity. Promote that exact
      // row to the top and persist the new order, just like re-running the
      // audit would. This also handles a job found by typing in Search and
      // then clicking its already-present Recent row.
      if (state.mode === "search") {
        touchRecentRow(state.selected_client, row.dataset.client);
      }
      // Stash this job in the recent-jobs list (localStorage).
      // Shared sidebar/launcher reads it for the "recently opened"
      // section so the user can jump back across panels.
      if (window.recordRecent) {
        window.recordRecent({
          client: row.dataset.client,
          source: "audit",
        });
      }
      renderList();
      renderDetail();
      scrollSelectedIntoView();
    });
    row.addEventListener("contextmenu", (ev) => {
      const key = row.dataset.rowKey || row.dataset.client;
      const r = state.rows.find((x) => rowKey(x) === key);
      if (r) showCtxMenu(ev, r);
    });
    // Trello hover popover on every row that has a pinned card.
    // Shared helper from web_shared/trello_hover.js — 400ms hover,
    // 60s backend cache, auto-hides on scroll/click.
    const _hoverKey = row.dataset.rowKey || row.dataset.client;
    const r = state.rows.find((x) => rowKey(x) === _hoverKey);
    if (r?.trello_card_id && window.attachTrelloHover) {
      window.attachTrelloHover(row, r.trello_card_id);
    }
  });

  $("#list-count").textContent = `${filtered.length} / ${state.rows.length} jobs`;
  $("#status-counts").textContent =
    `${filtered.length} shown · ${state.rows.length} total`;
}

// Build the list HTML, grouping commercial-parent sub-jobs (e.g.
// "Menifee Union School District" → its campus folders) under a single
// collapsible parent header so it's obvious the campuses are children
// of one insured. Non-grouped rows render exactly as before.
function buildListHtml(rows) {
  const childrenByParent = new Map();
  for (const r of rows) {
    if (r.subjob && r.claim_origin) {
      if (!childrenByParent.has(r.claim_origin)) {
        childrenByParent.set(r.claim_origin, []);
      }
      childrenByParent.get(r.claim_origin).push(r);
    }
  }
  // Multi-unit umbrellas — cluster non-campus rows that carry a unit by
  // their property (client). Group only when ≥2 units of one property are
  // on today's run (the canonical Avila 1413+1416 case); a lone unit row
  // stays flat (it still gets its 🏢 tag / ➕ create button).
  const unitRowsByClient = new Map();
  for (const r of rows) {
    if (r.subjob || r.is_parent) continue;
    if (!r.unit && !r.unit_folder) continue;
    const k = r.client || "";
    if (!unitRowsByClient.has(k)) unitRowsByClient.set(k, []);
    unitRowsByClient.get(k).push(r);
  }
  const unitGroupClients = new Set();
  for (const [k, v] of unitRowsByClient) if (v.length >= 2) unitGroupClients.add(k);

  if (childrenByParent.size === 0 && unitGroupClients.size === 0) {
    return rows.map((r) => renderListRow(r)).join("");
  }

  const emitted = new Set();
  const emittedUnit = new Set();
  const out = [];
  for (const r of rows) {
    // A parent (umbrella) row: client name matches a sub-job's origin.
    if (!r.subjob && childrenByParent.has(r.client)) {
      out.push(renderSubjobGroup(r, childrenByParent.get(r.client)));
      emitted.add(r.client);
      continue;
    }
    // A campus child row: rendered inside its parent's group, skip standalone.
    if (r.subjob && childrenByParent.has(r.claim_origin)) {
      if (!emitted.has(r.claim_origin)) {
        // Parent row filtered out of this view — emit a synthetic
        // header at the first child so the grouping still reads.
        out.push(renderSubjobGroup(null, childrenByParent.get(r.claim_origin),
                                   r.claim_origin));
        emitted.add(r.claim_origin);
      }
      continue;
    }
    // A multi-unit row → render the whole property's unit umbrella once.
    if (!r.subjob && !r.is_parent && (r.unit || r.unit_folder)
        && unitGroupClients.has(r.client)) {
      if (!emittedUnit.has(r.client)) {
        out.push(renderUnitGroup(r.client, unitRowsByClient.get(r.client)));
        emittedUnit.add(r.client);
      }
      continue;
    }
    out.push(renderListRow(r));
  }
  return out.join("");
}

// Parent (umbrella) directory of a path — the folder that CONTAINS a unit
// folder is the property root new siblings get created under.
function _parentDir(p) {
  const parts = (p || "").split(/[\\/]+/).filter(Boolean);
  parts.pop();
  return parts.join("\\");
}

// Best-effort property-root for a cluster of unit rows: the folder holding
// a resolved unit is the umbrella; failing that, a missing unit's `path`
// is the property root find_unit searched.
function deriveUnitUmbrella(children) {
  for (const c of children) {
    if (c.unit_folder && c.path) return _parentDir(c.path);
  }
  for (const c of children) { if (c.path) return c.path; }
  return "";
}

// One collapsible multi-unit property. Today's referenced units always
// show (peek); the caret reveals the property's OTHER on-disk units.
function renderUnitGroup(clientName, children) {
  const key = (clientName || "").toLowerCase();
  const expanded = expandedUnitGroups.has(key);
  const umbrella = deriveUnitUmbrella(children);
  const attention = children.filter((c) => c.flagged).length;
  const openBtn = (umbrella && window.UmbrellaGroup)
    ? window.UmbrellaGroup.openParentBtnHTML(umbrella) : "";
  const caret = `<button class="subjob-caret unit-caret" data-unit-key="${escapeAttr(key)}"
                   title="${expanded ? "Hide other units" : "Show the property's other units"}">${expanded ? "▾" : "▸"}</button>`;
  const looseSlot = `<span class="umb-loose-slot" data-umbrella="${escapeAttr(umbrella || "")}"></span>`;
  const header = `
    <div class="list-row subjob-parent unit-parent">
      ${caret}
      <div class="list-main">
        <div class="list-name"><span class="list-status umbrella">🏢</span> ${escapeHtml(titleCase(clientName))}</div>
        <div class="list-sub">
          <span class="subjob-badge" title="${children.length} unit(s) on today's run">🏢 ${children.length} today</span>
          ${attention
            ? `<span class="subjob-attn">${attention} need attention</span>`
            : `<span class="subjob-attn ok">all clean</span>`}
          ${looseSlot}
        </div>
      </div>
      <div class="list-end">${openBtn}</div>
    </div>`;
  const kids = children.map((c) => renderListRow(c, { role: "child" })).join("");
  const siblings = expanded ? renderUnitSiblings(key, children) : "";
  return `
    <div class="subjob-group unit-group" data-unit-key="${escapeAttr(key)}">
      ${header}
      <div class="subjob-children">${kids}${siblings}</div>
    </div>`;
}

// Ghost rows for the property's units that are NOT on today's run — only
// rendered when the group is expanded. Fetched lazily into unitSiblingsCache.
function renderUnitSiblings(key, children) {
  const sibs = unitSiblingsCache.get(key);
  if (sibs === undefined) {
    return `<div class="list-row subjob-child unit-sibling loading">
              <span class="list-status">⏳</span>
              <div class="list-main"><div class="list-sub">Loading other units…</div></div>
            </div>`;
  }
  const todayPaths = new Set(
    children.map((c) => (c.unit_folder || c.path || "").toLowerCase()).filter(Boolean));
  const others = sibs.filter((s) => !todayPaths.has((s.path || "").toLowerCase()));
  if (!others.length) {
    return `<div class="list-row subjob-child unit-sibling none">
              <div class="list-main"><div class="list-sub" style="color:var(--text-muted);">No other units on disk.</div></div>
            </div>`;
  }
  return others.map((s) => `
    <div class="list-row subjob-child unit-sibling">
      <span class="list-status ok">🏢</span>
      <div class="list-main">
        <div class="list-name">${escapeHtml(s.name)}</div>
        <div class="list-sub"><span class="mini-chip" title="Not referenced on today's run">not on today's run</span></div>
      </div>
      <div class="list-end">
        <button class="umb-openparent" data-parent-path="${escapeAttr(s.path)}" title="Open this unit folder">📁</button>
      </div>
    </div>`).join("");
}

// One collapsible parent group: header (the umbrella insured) + its
// indented campus children. `parentRow` may be null when the umbrella
// row isn't in the current filter — `parentName` is then used for the
// header label.
function renderSubjobGroup(parentRow, children, parentName) {
  const name = parentRow ? parentRow.client : (parentName || "");
  const key = (name || "").toLowerCase();
  const collapsed = collapsedParents.has(key);
  const attention = children.filter((c) => c.flagged).length;
  const meta = {
    childCount: children.length,
    attention,
    collapsed,
    parentKey: key,
    synthetic: !parentRow,
  };
  const header = parentRow
    ? renderListRow(parentRow, { role: "parent", group: meta })
    : renderSyntheticParentHeader(name, meta);
  const kids = children.map((c) => renderListRow(c, { role: "child" })).join("");
  return `
    <div class="subjob-group" data-parent-key="${escapeAttr(key)}">
      ${header}
      <div class="subjob-children ${collapsed ? "collapsed" : ""}">${kids}</div>
    </div>`;
}

// Header used when the umbrella row itself isn't in the filtered list.
// Pure label + caret + campus rollup — not selectable (no backing row).
function renderSyntheticParentHeader(name, meta) {
  const caret = `<button class="subjob-caret" data-parent-key="${escapeAttr(meta.parentKey)}"
                   title="${meta.collapsed ? "Expand" : "Collapse"} campuses">${meta.collapsed ? "▸" : "▾"}</button>`;
  const badge = `<span class="subjob-badge" title="${meta.childCount} campus job(s)">🏫 ${meta.childCount}</span>`;
  const attn = meta.attention
    ? `<span class="subjob-attn">${meta.attention} need attention</span>`
    : `<span class="subjob-attn ok">all clean</span>`;
  return `
    <div class="list-row subjob-parent synthetic">
      ${caret}
      <div class="list-main">
        <div class="list-name">${escapeHtml(name)}</div>
        <div class="list-sub">${badge} ${attn}</div>
      </div>
    </div>`;
}

// Short, distinguishing name for a campus child row. Every sub-job
// folder repeats the umbrella name at the front ("Menifee Union School
// District  Kirkpatrick Elementary 6.9.26"), which truncates off the
// only part that differs. Strip the umbrella (the campus folder's parent
// dir) so the row shows just "Kirkpatrick Elementary 6.9.26".
function campusShortName(r) {
  let name = r.client || "";
  const parts = (r.path || "").split(/[\\/]+/).filter(Boolean);
  const umbrella = parts.length >= 2 ? parts[parts.length - 2] : "";
  if (umbrella && name.toLowerCase().startsWith(umbrella.toLowerCase())) {
    const rest = name.slice(umbrella.length).replace(/^[\s\-–—_]+/, "").trim();
    if (rest) return rest;
  }
  const co = r.claim_origin || "";
  if (co && name.toLowerCase().startsWith(co.toLowerCase())) {
    const rest = name.slice(co.length).replace(/^[\s\-–—_]+/, "").trim();
    if (rest) return rest;
  }
  return name;
}

function renderListRow(r, opts = {}) {
  const role = opts.role;          // "parent" | "child" | undefined
  const group = opts.group || null;
  // Prefer the pinned Trello card's name (r.display_name) for normal
  // rows — the job's canonical identity. Campus children keep their
  // short name; parents fall back to the client (no card).
  const displayName = (role === "child")
    ? titleCase(campusShortName(r))
    : firstLast(r.display_name || titleCase(r.client));
  // Flat-search breadcrumb: while searching, a matched child can render
  // far from its umbrella header, so prefix the property name ("Keystone ›
  // Unit 1416B") to keep context — the "find the one-off, don't pull the
  // parent" ask. Injected as raw HTML (breadcrumbHTML self-escapes); kept
  // separate from displayName, which is escaped downstream.
  const crumbHTML = (role === "child" && state.search.trim() && window.UmbrellaGroup)
    ? window.UmbrellaGroup.breadcrumbHTML(r.claim_origin || r.client || "")
    : "";
  const classes = ["list-row"];
  if (role === "child")  classes.push("subjob-child");
  if (role === "parent") classes.push("subjob-parent");
  if (r.flagged) classes.push("flagged");
  if (r.aging_days >= 3 && r.flagged) classes.push("aging");
  if (rowKey(r) === state.selected_client) classes.push("active");

  // Parent (umbrella) header gets a collapse caret; its own audit count
  // is umbrella noise (paperwork lives in the campuses), so we show a
  // campus rollup instead of a 🚩/missing number.
  const caretBtn = (role === "parent" && group)
    ? `<button class="subjob-caret" data-parent-key="${escapeAttr(group.parentKey)}"
              title="${group.collapsed ? "Expand" : "Collapse"} campuses">${group.collapsed ? "▸" : "▾"}</button>`
    : "";

  const statusIcon = role === "parent"
    ? `<span class="list-status umbrella">🏫</span>`
    : (r.flagged
        ? `<span class="list-status flagged">🚩</span>`
        : `<span class="list-status ok">✓</span>`);

  const subChips = [];
  if (r._stale) {
    subChips.push('<span class="mini-chip pending" title="From your last '
      + 'session — re-checking now">⏳ not checked yet</span>');
  }
  // No carrier chip on the LIST row. It still shows on the detail card,
  // where you're looking at one job — on the list it competed with the
  // chips that say something is wrong (aging, not-found, missing), and
  // who is paying isn't what you scan the list for.
  if (r.aging_days >= 3) {
    const hot = r.aging_days >= 7 ? "hot" : "";
    subChips.push(`<span class="mini-chip aging ${hot}">⏰${r.aging_days}d</span>`);
  }
  if (!r.found) {
    subChips.push(`<span class="mini-chip not-found">⚠</span>`);
  }
  // SharePoint match chip — flashes when the audit found photos on
  // SP that aren't in OneDrive yet. Clicks bubble up through the
  // row click handler; right-click goes to the SP import dialog.
  if ((r.sharepoint_new || 0) > 0) {
    // Bumped from mini-chip → bigger, brighter, with an animated
    // dot so it's impossible to miss when scanning the list.
    subChips.push(`<span class="mini-chip sp-new-chip" title="${r.sharepoint_new} new SharePoint files to import">📥 ${r.sharepoint_new} on SP</span>`);
  }
  // Show the first activity label so the user can scan the type at a glance
  const firstAct = (r.activity || [])[0];
  if (firstAct) {
    subChips.push(`<span class="mini-chip activity" data-act="${escapeAttr(firstAct)}">${escapeHtml(firstAct)}</span>`);
  }
  // Misplaced items — found elsewhere in the parent tree (wrong folder),
  // not actually missing. Compact ⚠ chip; the detail pane shows where.
  const misplacedCount = (r.total_misplaced != null)
    ? r.total_misplaced
    : ((r.misplaced_forms || []).length + (r.misplaced_photos || []).length);
  // HIDDEN 2026-08-14, same as the detail card's chip and section: the
  // detection reports correctly-filed items as misfiled. A wrong warning
  // on the list is the worst place for one — it's the column people scan
  // to decide what needs work, so it sends them after files that are
  // already where they belong. Re-enable by deleting the `false &&`
  // once the detection is trustworthy.
  if (false && misplacedCount > 0 && !r.subjob && !r.is_parent) {
    subChips.push(`<span class="mini-chip misplaced" title="${misplacedCount} item(s) found in the wrong folder — see detail">⚠ ${misplacedCount} misfiled</span>`);
  }

  // A restored recent has not been audited yet, so its counts are
  // placeholders. Rendering 0 in the "zero" style would read as CLEAN —
  // the same stale-answer-shown-as-current trap this panel keeps
  // hitting — so say "not checked yet" until the re-audit lands.
  const missClass = r._stale ? "miss-num pending"
    : (r.total_missing > 0 ? "miss-num" : "miss-num zero");
  const _starred = (state.starred_clients || []).includes((r.client || "").toLowerCase());
  // Parent (umbrella) header shows a campus rollup instead of its own
  // (noisy) missing count.
  const openParentBtn = (role === "parent" && r.path && window.UmbrellaGroup)
    ? window.UmbrellaGroup.openParentBtnHTML(r.path) : "";
  const listEnd = (role === "parent" && group)
    ? openParentBtn
      + `<span class="subjob-badge" title="${group.childCount} campus job(s) under this insured">🏫 ${group.childCount}</span>`
      + (group.attention
          ? `<span class="subjob-attn">${group.attention} need attention</span>`
          : `<span class="subjob-attn ok">all clean</span>`)
    : `<button class="star-btn ${_starred ? "starred" : ""}"
                data-client="${escapeAttr(r.client)}"
                title="${_starred ? "Unstar" : "Star — appears in ⭐ Starred filter"}"
                style="background:transparent;border:none;cursor:pointer;font-size:14px;padding:2px 6px;color:${_starred ? "var(--amber)" : "var(--text-muted)"};">${_starred ? "★" : "☆"}</button>`;

  // ── Per-tech color stripe ──────────────────────────────────────
  // Each row gets a left-edge color bar derived from the first tech.
  // Same tech → same color across runs so the user develops muscle
  // memory ("orange = Fernando, blue = JG, etc."). Color comes from
  // a deterministic hash of the tech initials.
  const primaryTech = (r.techs || [])[0] || "";
  const techColor = techStripeColor(primaryTech);
  const techStripe = techColor
    ? `<span class="tech-stripe" style="background:${techColor};" title="${escapeAttr(primaryTech)}"></span>`
    : `<span class="tech-stripe"></span>`;

  const isStarred = (state.starred_clients || []).includes((r.client || "").toLowerCase());
  const isSelected = state.selected_set.has(r.client);
  // Multi-unit suffix on the client name — show the resolved unit
  // subfolder (or just the run-doc unit number when the audit couldn't
  // find a matching folder yet) so a property like Avila Apartments
  // doesn't render identically across every row that lives under it.
  // Prefer the actual folder name when we descended; fall back to the
  // run-doc value with a "Unit" prefix so the user sees what was
  // requested even when the folder is missing.
  const unitLabel = r.unit_folder
    ? r.unit_folder
    : (r.unit ? `Unit ${r.unit}` : "");
  const unitMissing = !!r.unit && !r.unit_folder;
  // When the run-doc names a unit but no matching subfolder exists yet,
  // offer a ➕ to create it under the property root (r.path) — matches
  // the property's sibling naming, scaffolds, routes any pending import.
  const createBtn = (unitMissing && r.path && window.UmbrellaGroup)
    ? " " + window.UmbrellaGroup.createBtnHTML(
        r.path, `Unit ${r.unit}`, r.client)
    : "";
  const nameSuffix = unitLabel
    ? ` <span class="list-unit-tag ${unitMissing ? "missing" : ""}"
              title="${unitMissing ? `Run-doc says Unit ${escapeAttr(r.unit)} but no matching subfolder was found` : `Resolved unit subfolder: ${escapeAttr(r.unit_folder)}`}">
            🏢 ${escapeHtml(unitLabel)}
        </span>${createBtn}`
    : "";
  // Tenant — when present (e.g. "Mendiola, Mary" inside a Unit 104 SP
  // folder), show it as a smaller secondary chip so the user can scan
  // who's actually in the unit without opening the row.
  if (r.tenant) {
    subChips.unshift(`<span class="mini-chip tenant" title="Tenant from run-doc">${escapeHtml(r.tenant)}</span>`);
  }
  // Time slot — surface "9-11" / "@12pm" on the row sub-line so the
  // user sees scheduling at a glance.
  if (r.time_slot) {
    subChips.unshift(`<span class="mini-chip time-slot">⏱ ${escapeHtml(r.time_slot)}</span>`);
  }
  return `
    <div class="${classes.join(" ")}" data-client="${escapeAttr(r.client)}" data-row-key="${escapeAttr(rowKey(r))}" data-tech="${escapeAttr(primaryTech)}">
      ${caretBtn}
      ${techStripe}
      ${statusIcon}
      <div class="list-main">
        <div class="list-name">${crumbHTML}${escapeHtml(displayName)}${nameSuffix}</div>
        <div class="list-sub">${subChips.join(" ")}</div>
      </div>
      <div class="list-end">
        ${listEnd}
      </div>
    </div>
  `;
}

// Deterministic color from tech initials — same tech always picks
// the same stripe. Returns "" for empty / unknown tech so the row
// just gets the placeholder transparent stripe.
const _TECH_PALETTE = [
  "#E67E22", "#3498DB", "#27AE60", "#9B59B6", "#E74C3C",
  "#16A085", "#F39C12", "#2980B9", "#D35400", "#8E44AD",
  "#1ABC9C", "#C0392B", "#7F8C8D", "#2C3E50", "#BDC3C7",
];
function techStripeColor(tech) {
  if (!tech) return "";
  let h = 0;
  for (let i = 0; i < tech.length; i++) {
    h = ((h << 5) - h + tech.charCodeAt(i)) | 0;
  }
  return _TECH_PALETTE[Math.abs(h) % _TECH_PALETTE.length];
}

// Context injected into the shared web_shared/audit_detail.js renderer so
// the Audit + Snapshot tools render the per-job detail from ONE source
// (can't drift). Audit maps it to its own modals / helpers / re-render.
function buildAuditDetailCtx() {
  return {
    helpers: { escapeHtml, escapeAttr, titleCase, copyText, setStatus },
    modals: {
      openFindFolder: openFindFolderModal,
      openSpImport: openSpImportModal,
      openJobImport: openJobImportModal,
      openScope: openScopeDialog,
      openCopyPicsToXa: openCopyPicsToXaModal,
      openDayUnits: openDayUnitsModal,
      openPin: openPinModal,
      openComment: openCommentModal,
      openMatchDiag: openMatchDiagnostic,
      openAttachments: (row) => window.openTrelloAttachmentsModal(
        { cardId: row.trello_card_id, client: row.client }),
      showClaimFolders: showClaimFoldersModal,
      showOdContents: showOdContentsModal,
      showWorkLog: showWorkLogModal,
    },
    rerender: () => renderDetail(),
    rerenderList: () => renderList(),
    openSnapshot: (row) => {
      window.parent.postMessage({
        type: "ems-open-tool-modal",
        key: "snapshot",
        focus: row.client || row.display_name || "",
      }, "*");
    },
    reauditAndRerender: async (client) => {
      const re = await pywebview.api.reaudit_one(client);
      if (re?.ok) {
        applyRow(re.row);
        renderAll();
      } else { renderDetail(); }
    },
    // The SHARED module, not a local copy. This used to call a private
    // duplicate with none of its defences — no pointer-events:none, no
    // hide on scroll/click/blur, no liveness check — which is why the
    // hover card kept getting stranded on the detail pane even after the
    // shared one was hardened. The list rows already used the shared one,
    // so the same popover behaved two different ways on one screen.
    attachTrelloHover: (btn, cardId) => {
      if (window.attachTrelloHover) window.attachTrelloHover(btn, cardId);
    },
  };
}

// ── Recents, remembered across restarts ──────────────────────────────
//
// The Search tab accumulates the jobs you pull up, and closing the app
// threw the lot away — you came back in and re-typed the same names.
// PanelState persists per-panel state to state.json on this machine, so
// the list survives a restart.
//
// What is saved is the job's IDENTITY, never its audit numbers. A row
// carries "3 missing" and a photo count, and those go stale the moment
// someone drops a form in overnight; restoring them would show
// yesterday's answer as though it were today's, which is the exact
// failure this panel keeps having. Names come back instantly, and the
// numbers are re-audited.
const RECENTS_KEY = "recents";

function touchRecentRow(key, client) {
  if (!Array.isArray(state.oneoffHits) || !state.oneoffHits.length) return;
  let ix = state.oneoffHits.findIndex((r) => rowKey(r) === key);
  if (ix < 0 && client) {
    ix = state.oneoffHits.findIndex((r) =>
      (r.client || "").trim().toLowerCase() === client.trim().toLowerCase());
  }
  if (ix <= 0) return;
  const [hit] = state.oneoffHits.splice(ix, 1);
  state.oneoffHits.unshift(hit);
  saveRecents();
}

function saveRecents() {
  try {
    const list = (state.oneoffHits || []).slice(0, ONEOFF_MAX).map((r) => ({
      client: r.client,
      display_name: r.display_name || "",
      row_key: r.row_key || "",
      path: r.path || "",
      trello_card_id: r.trello_card_id || "",
    })).filter((r) => r.client);
    PanelState.set({ [RECENTS_KEY]: list });
  } catch (_) { /* persistence is a convenience, never a blocker */ }
}

// Restore the names immediately, then re-audit them in the background so
// the counts are real. Sequential on purpose: a burst of parallel audits
// would hammer the share for a list nobody is looking at yet.
async function restoreRecents() {
  let saved = [];
  try { saved = PanelState.get(RECENTS_KEY, []) || []; } catch (_) { return; }
  if (!Array.isArray(saved) || !saved.length) return;
  state.oneoffHits = saved.map((r) => ({
    ...r,
    form_issues: [],
    photo_issues: [],
    total_missing: 0,
    flagged: false,
    found: true,
    _stale: true,            // "from last session" until re-audited
  }));
  renderList();
  for (const r of saved) {
    if (!state.oneoffHits.some((h) => h.client === r.client)) break;  // cleared
    try {
      const re = await pywebview.api.reaudit_one(r.client);
      if (re && re.ok && re.row) {
        applyRow(re.row);
        renderAll();
      }
    } catch (_) { /* leave it marked stale */ }
  }
}

// Find a row by rowKey across BOTH the loaded list AND one-off search
// hits. A search for a job that isn't in today's run surfaces it via
// state.oneoffHits (a separate array); without checking it, the row shows
// in the list but selecting it left the detail blank and Enter/actions
// did nothing ("can't see the audit for what I just searched"). Hoisted,
// so earlier callers resolve fine. (bugfix 2026-07-23)
function findRowByKey(key) {
  const pool = (state.oneoffHits && state.oneoffHits.length)
    ? state.oneoffHits.concat(state.rows) : state.rows;
  return pool.find((x) => rowKey(x) === key);
}

// The write-side twin of findRowByKey: put a freshly re-audited row back
// into whichever list it came from.
//
// Every caller used to splice into state.rows ONLY. A job pulled up
// through Search lives in state.oneoffHits instead, so findIndex returned
// -1, the fresh row was dropped on the floor, and renderDetail() ->
// findRowByKey() -- which reads oneoffHits FIRST -- went on repainting
// the stale one. That is why missing forms sat there after an import
// until the whole tool was reloaded: the re-audit ran, the backend
// returned the right answer (audit_web.reaudit_one picks _oneoff_rows vs
// _last_rows correctly), and the UI threw it away.
//
// Matching is by rowKey, not client: multi-unit rows share a client name
// ("Avila Apartments::1413" vs "::1416"), so matching on client alone
// overwrote the first unit's row with a different unit's audit.
function applyRow(row) {
  if (!row) return false;
  const key = rowKey(row);
  let hit = false;
  for (const list of [state.oneoffHits, state.rows]) {
    if (!Array.isArray(list)) continue;
    let ix = list.findIndex((x) => rowKey(x) === key);
    // Fall back to the client name: a re-audit can legitimately change a
    // row's key (a job that splits into per-unit rows once days are
    // pinned), and landing the update on the matching client beats
    // silently discarding it — the bug this helper exists to fix.
    if (ix < 0) ix = list.findIndex((x) => x.client === row.client);
    if (ix >= 0) { list[ix] = row; hit = true; }
  }
  return hit;
}

function renderDetail() {
  // selected_client holds a row_key (e.g. "Avila Apartments::1413") so
  // look up by rowKey to disambiguate multi-unit rows.
  const r = findRowByKey(state.selected_client);
  const empty = $("#detail-empty");
  const view = $("#detail-view");
  if (!r) {
    empty.classList.remove("hidden");
    view.classList.add("hidden");
    view.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");
  view.classList.remove("hidden");

  // Commercial-parent UMBRELLA head: a container, not a job. Show a
  // minimal view — the campus list + Open-folder only — NO per-job
  // buttons (SP/WC import, pin, flag, comment) and no audit chips.
  if (r.is_parent) {
    const kids = state.rows.filter(
      (x) => x.subjob && x.claim_origin === r.client);
    const attention = kids.filter((x) => x.flagged).length;
    const hasPath = !!r.path;
    view.innerHTML = `
      <header class="detail-head">
        <div class="detail-name">🏫 ${escapeHtml(titleCase(r.client))}</div>
        <div class="detail-techs">Umbrella folder · ${kids.length} campus job${kids.length === 1 ? "" : "s"}${attention ? ` · ${attention} need attention` : ""}</div>
      </header>
      <section class="detail-section">
        <div class="muted" style="padding:6px 0;">This is the container folder for the campus jobs — it isn't a job itself, so it has no paperwork checks, SharePoint scan, or import actions. Open a campus below to work it.</div>
      </section>
      ${kids.length ? `<section class="detail-section">
        <h3>Campuses (${kids.length})</h3>
        <ul class="issue-list">
          ${kids.map((c) => `<li>${c.flagged ? "🚩" : "✓"} ${escapeHtml(campusShortName(c))}</li>`).join("")}
        </ul></section>` : ""}
      <section class="detail-section">
        <h3>Folder</h3>
        <div class="detail-meta">
          <span class="label">Path</span>
          <span class="value">${escapeHtml(r.path || "—")}</span>
        </div>
      </section>
      <footer class="detail-actions">
        <div class="action-row">
          <button class="action-btn primary" data-action="open-folder" ${hasPath ? "" : "disabled"}>📁 OD folder</button>
        </div>
        <div class="action-row">
          <button class="action-btn" data-action="copy-client">📋 Copy name</button>
          <button class="action-btn" data-action="copy-path" ${hasPath ? "" : "disabled"}>📋 Copy path</button>
        </div>
      </footer>`;
    view.querySelectorAll(".action-btn[data-action]").forEach((b) => {
      b.addEventListener("click", () => onDetailAction(b.dataset.action, r));
    });
    return;
  }

  const ctx = buildAuditDetailCtx();
  view.innerHTML = window.AuditDetail.buildDetailBodyHTML(r, ctx);
  window.AuditDetail.wireDetail(view, r, ctx);
}

function scrollSelectedIntoView() {
  const active = $(".list-row.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

// ── Filtering ────────────────────────────────────────────────────
function filterRows() {
  let rows = state.rows;
  // One-off audit rows belong to the Recent tab and ONLY there. They used
  // to be prepended onto whatever list was showing, which put searched
  // jobs into the Daily Run list where they read as part of the day's run
  // — they aren't, and no amount of scrolling told you which was which.
  if (state.mode === "search" && state.oneoffHits && state.oneoffHits.length) {
    const have = new Set(rows.map(rowKey));
    const extra = state.oneoffHits.filter((h) => !have.has(rowKey(h)));
    if (extra.length) rows = extra.concat(rows);
  }
  const f = state.filter;
  if (f === "flagged")    rows = rows.filter((r) => r.flagged);
  else if (f === "ok")    rows = rows.filter((r) => !r.flagged);
  else if (f === "aging") rows = rows.filter((r) => r.aging_days >= 3);
  else if (f === "forms") rows = rows.filter((r) => r.form_issues.length);
  else if (f === "photos") rows = rows.filter((r) => r.photo_issues.length);
  else if (f === "not_found") rows = rows.filter((r) => !r.found);
  else if (f === "new_loss") rows = rows.filter((r) => r.new_loss);
  else if (f === "has_sp")   rows = rows.filter((r) => (r.sharepoint_new || 0) > 0);
  // ── Smart presets ──
  // "Needs attention" — combines the three high-signal failure modes
  // (aged-flagged, SP-files-waiting, missing forms) into a single
  // click. Catches jobs that need action right now without forcing
  // the user to flip through 3 chips.
  else if (f === "needs_attention") {
    rows = rows.filter((r) =>
      (r.flagged && r.aging_days >= 3) ||
      (r.sharepoint_new || 0) > 0 ||
      (r.form_issues || []).length > 0);
  }
  // "Starred" — only clients the user has bookmarked.
  else if (f === "starred") {
    const starred = new Set(state.starred_clients || []);
    rows = rows.filter((r) => starred.has((r.client || "").toLowerCase()));
  }

  const q = state.search.trim().toLowerCase();
  if (q) {
    rows = rows.filter((r) => {
      const techs = Array.isArray(r.techs) ? r.techs : [];
      const formIssues = Array.isArray(r.form_issues) ? r.form_issues : [];
      const photoIssues = Array.isArray(r.photo_issues) ? r.photo_issues : [];
      const hay = [r.client || "", ...techs, ...formIssues, ...photoIssues]
        .join(" ").toLowerCase();
      return hay.includes(q);
    });
  }
  return rows;
}

function setFilter(value) {
  state.filter = value;
  // Remembered across visits — setting "flagged" and finding it back on
  // "all" every time you return is the whole complaint.
  try { PanelState.set({ filter: value }); } catch (_) { /* optional */ }
  $$(".filter").forEach((b) => {
    b.classList.toggle("active", b.dataset.filter === value);
  });
  renderList();
  renderDetail();
}

// ── 🗳 Bulk actions toolbar ────────────────────────────────────
// Wired once on boot. Becomes visible when ≥1 checkbox is ticked.
// Each action iterates the selected set with a per-row progress
// status so the user sees what's happening on a 12-row bulk.
function renderBulkToolbar() {
  const bar = document.getElementById("bulk-toolbar");
  const n   = state.selected_set.size;
  if (!bar) return;
  bar.classList.toggle("hidden", n === 0);
  const cnt = document.getElementById("bulk-count");
  if (cnt) cnt.textContent = `${n} selected`;
}

function attachBulkToolbar() {
  const sel = () => [...state.selected_set];
  document.getElementById("bulk-clear")?.addEventListener("click", () => {
    state.selected_set.clear();
    document.querySelectorAll(".list-row").forEach((r) => r.classList.remove("bulk-selected"));
    document.querySelectorAll(".bulk-cb").forEach((c) => (c.checked = false));
    renderBulkToolbar();
  });
  document.getElementById("bulk-reaudit")?.addEventListener("click", async () => {
    const clients = sel();
    if (!clients.length) return;
    let done = 0;
    for (const c of clients) {
      setStatus(`↻ Re-auditing ${++done}/${clients.length} · ${c}`);
      try {
        const re = await pywebview.api.reaudit_one(c);
        if (re?.ok) {
          applyRow(re.row);
        }
      } catch (_) {}
    }
    renderAll();
    setStatus(`↻ Re-audited ${done} client${done !== 1 ? "s" : ""}`, "ok");
  });
  document.getElementById("bulk-copy-issues")?.addEventListener("click", async () => {
    const clients = sel();
    const lines = [];
    for (const c of clients) {
      const r = state.rows.find((x) => x.client === c);
      if (!r) continue;
      const bits = [
        ...(r.form_issues || []).map((i) => `  📋 ${i}`),
        ...(r.photo_issues || []).map((i) => `  📷 ${i}`),
      ];
      lines.push(`${r.client}${bits.length ? "" : " — clean"}`);
      lines.push(...bits);
      lines.push("");
    }
    const txt = lines.join("\n").trim();
    if (!txt) { setStatus("No issues to copy", "warn"); return; }
    const ok = await copyText(txt);
    setStatus(ok ? `📋 Copied issues for ${clients.length} clients` : "Copy failed",
              ok ? "ok" : "error");
  });
  document.getElementById("bulk-import-sp")?.addEventListener("click", () => {
    const clients = sel();
    if (!clients.length) return;
    // Open the SP import modal for the FIRST one — too many parallel
    // modals would overwhelm. Bulk-SP in the Tk audit is also serial.
    const first = state.rows.find((x) => x.client === clients[0]);
    if (first) openSpImportModal(first);
    setStatus(`📥 SP import for ${clients[0]} (${clients.length} selected — close to continue to next)`, "");
  });
  document.getElementById("bulk-snapshot")?.addEventListener("click", () => {
    const clients = sel();
    if (!clients.length) return;
    // Snapshots are interactive (fill the form), so open the Snapshot
    // tool for the FIRST selected; the rest stay selected to work through.
    // Mirrors the serial bulk-SP pattern.
    if (window.emsNavigateTo) window.emsNavigateTo("snapshot", clients[0]);
    setStatus(`📸 Snapshot for ${clients[0]}${clients.length > 1 ? ` (${clients.length} selected — come back for the next)` : ""}`, "");
  });
  document.getElementById("bulk-flag")?.addEventListener("click", () => {
    const clients = sel();
    if (!clients.length) return;
    const item = prompt(`Flag a missing item across ${clients.length} client${clients.length !== 1 ? "s" : ""}:\n\nLabel (e.g. "ATP", "Demo pics", "Moisture map"):`);
    if (!item || !item.trim()) return;
    (async () => {
      let done = 0, failed = 0;
      for (const c of clients) {
        setStatus(`🚩 Flagging ${++done}/${clients.length} · ${c}`);
        try {
          const r = await pywebview.api.flag_missing(c, item.trim(), "");
          if (!r?.ok) failed += 1;
        } catch (_) { failed += 1; }
      }
      setStatus(`🚩 Flagged "${item}" on ${done - failed}/${done} clients${failed ? ` · ${failed} failed` : ""}`,
                failed ? "warn" : "ok");
    })();
  });
}

// 🗂 In Progress - ADMIN Trello checklist, rendered inline in the
// detail pane below the action buttons. Fetched async so the detail
// render stays instant; each item is a checkbox that writes straight
// back to Trello on toggle (reverting on failure).
// 🎴 Trello enrichment — everything the audit row doesn't carry, pulled
// from ONE get_card call (backend caches 60s): lane, loss type, labels,
// due, last activity, members, checklist %, adjuster/customer email, and
// the latest comments. Loaded async so the detail render stays instant.
async function loadTrelloInfo(row) {
  const statusEl = document.getElementById("trello-info-status");
  const bodyEl = document.getElementById("trello-info-body");
  if (!bodyEl) return;
  let r;
  try { r = await pywebview.api.trello_enrichment(row.client, row.trello_card_id || ""); }
  catch (e) { if (statusEl) statusEl.textContent = "error"; return; }
  // Detail may have re-rendered to a different row while awaiting.
  const still = document.getElementById("trello-info-body");
  if (!still || still !== bodyEl) return;
  if (!r || !r.ok) { if (statusEl) statusEl.textContent = r && r.error ? "error" : ""; return; }
  if (!r.has_card) { document.getElementById("trello-info")?.remove(); return; }
  if (statusEl) statusEl.textContent = "";
  const chip = (txt, color) => `<span style="display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;background:${color || "var(--surface-2)"};color:var(--text);margin:0 4px 4px 0;">${escapeHtml(txt)}</span>`;
  const chips = [];
  if (r.lane) chips.push(chip("📍 " + r.lane, "rgba(74,158,255,.18)"));
  if (r.loss_type) chips.push(chip("💧 " + r.loss_type, "rgba(245,166,35,.18)"));
  const lossLc = (r.loss_type || "").toLowerCase();
  (r.labels || []).forEach((l) => { if (l && l.toLowerCase() !== lossLc) chips.push(chip(l)); });
  if (r.due) chips.push(chip((r.due_complete ? "✅ due " : "📅 due ") + r.due, r.due_complete ? "rgba(63,185,80,.18)" : "rgba(245,166,35,.18)"));
  if (r.last_activity) chips.push(chip("🕒 " + r.last_activity));
  if ((r.members || []).length) chips.push(chip("👤 " + r.members.join(", ")));
  if (r.checklist_total > 0) {
    const pct = Math.round((r.checklist_done / r.checklist_total) * 100);
    chips.push(chip(`☑ ${r.checklist_done}/${r.checklist_total} (${pct}%)`, pct === 100 ? "rgba(63,185,80,.18)" : "var(--surface-2)"));
  }
  let html = chips.length ? `<div style="display:flex;flex-wrap:wrap;margin-bottom:6px;">${chips.join("")}</div>` : "";
  const emails = [];
  if (r.customer_email) emails.push(["Customer", r.customer_email]);
  if (r.adjuster_email) emails.push(["Adjuster", r.adjuster_email]);
  if (emails.length) {
    html += `<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">${emails.map(([k, v]) => `${k}: <a href="#" class="tr-email" data-email="${escapeAttr(v)}" style="color:var(--text);">${escapeHtml(v)}</a>`).join(" &nbsp;·&nbsp; ")}</div>`;
  }
  if ((r.comments || []).length) {
    html += `<div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin:6px 0 4px;">Recent comments</div>`;
    html += r.comments.map((c) => `
      <div style="border-left:2px solid var(--border);padding:2px 0 2px 8px;margin-bottom:4px;">
        <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(c.author || "")}${c.date ? " · " + escapeHtml(c.date) : ""}</div>
        <div style="font-size:12px;white-space:pre-wrap;">${escapeHtml((c.text || "").slice(0, 400))}</div>
      </div>`).join("");
  }
  if (!html) html = '<div class="muted" style="font-size:11px;">Card pinned, but no extra info filled in yet.</div>';
  bodyEl.innerHTML = html;
  const email = r.customer_email || r.adjuster_email || "";
  const emailBtn = document.getElementById("trello-copy-email");
  if (emailBtn && email) {
    emailBtn.style.display = "";
    emailBtn.onclick = async () => {
      const ok = await copyText(email);
      setStatus(ok ? `📧 Copied ${email}` : "Couldn't copy", ok ? "ok" : "warn");
    };
  }
  bodyEl.querySelectorAll(".tr-email").forEach((a) =>
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const ok = await copyText(a.dataset.email);
      setStatus(ok ? `📧 Copied ${a.dataset.email}` : "Couldn't copy", ok ? "ok" : "warn");
    }));
}

async function loadInProgressChecklist(row) {
  const statusEl = document.getElementById("inprog-cl-status");
  const listEl = document.getElementById("inprog-cl-items");
  if (!listEl) return;
  let res;
  try {
    res = await pywebview.api.get_inprogress_checklist(row.client);
  } catch (ex) {
    if (statusEl) statusEl.textContent = "(load failed)";
    return;
  }
  // Detail may have been re-rendered to a different row while we waited.
  const stillHere = document.getElementById("inprog-cl-items");
  if (stillHere !== listEl) return;
  if (!res || !res.ok || !(res.items || []).length) {
    const sec = document.getElementById("inprog-cl");
    if (sec) sec.remove();   // no checklist on this card — hide section
    return;
  }
  const cardId = res.card_id;
  if (statusEl) statusEl.textContent = `(${res.items.length})`;
  listEl.innerHTML = res.items.map((it, i) => `
    <li class="cl-item">
      <label>
        <input type="checkbox" data-i="${i}" data-id="${escapeAttr(it.id)}"
               ${it.complete ? "checked" : ""}/>
        <span class="${it.complete ? "cl-done" : ""}">${escapeHtml(it.name)}</span>
      </label>
    </li>`).join("");
  listEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener("change", async () => {
      const itemId = cb.dataset.id;
      const want = cb.checked;
      cb.disabled = true;
      let ok = false;
      try {
        const r = await pywebview.api.toggle_checklist_item(
          cardId, itemId, want);
        ok = !!(r && r.ok);
      } catch (_) { ok = false; }
      cb.disabled = false;
      if (!ok) {
        cb.checked = !want;   // revert
        setStatus("Trello update failed", "error");
        return;
      }
      const span = cb.parentElement.querySelector("span");
      if (span) span.className = want ? "cl-done" : "";
      setStatus(want ? "Ticked ✓" : "Un-ticked", "ok");
    });
  });
}

// INITIAL checklist (INITIAL / INITIAL - ADMIN) + canned intake comments,
// folded in from the IUQ. Renders the checklist item(s) with tick boxes
// (reusing toggle_checklist_item) plus the two canned-comment buttons.
async function loadInitialChecklists(row) {
  const sec = document.getElementById("initial-cl");
  const statusEl = document.getElementById("initial-cl-status");
  const bodyEl = document.getElementById("initial-cl-body");
  if (!sec || !bodyEl) return;
  let res;
  try {
    res = await pywebview.api.get_initial_checklists(row.client);
  } catch (_) { if (statusEl) statusEl.textContent = "(load failed)"; return; }
  // Detail may have re-rendered to a different row while we waited.
  if (document.getElementById("initial-cl-body") !== bodyEl) return;
  const cardId = res && res.card_id;
  if (!cardId) { sec.remove(); return; }   // no pinned card resolved
  const checklists = (res.ok && res.checklists) || [];
  const total = checklists.reduce((n, cl) => n + (cl.items || []).length, 0);
  if (statusEl) statusEl.textContent = total ? `(${total})` : "";

  const clHtml = checklists.map((cl) => `
    <div class="cl-group">
      <div class="cl-group-name">${escapeHtml(cl.name)}</div>
      <ul class="issue-list">
        ${(cl.items || []).map((it) => `
          <li class="cl-item"><label>
            <input type="checkbox" data-id="${escapeAttr(it.id)}" ${it.complete ? "checked" : ""}/>
            <span class="${it.complete ? "cl-done" : ""}">${escapeHtml(it.name)}</span>
          </label></li>`).join("")}
      </ul>
    </div>`).join("");
  // Gone: ticking the checklist item posts the comment now. Two ways to
  // record one fact meant the tick and the comment could disagree, and
  // the comment was the half that got forgotten.
  const cannedHtml = "";
  bodyEl.innerHTML =
    (clHtml || `<div class="muted" style="padding:4px 0 2px;">No INITIAL checklist on this card.</div>`)
    + cannedHtml;

  bodyEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener("change", async () => {
      const itemId = cb.dataset.id;
      const want = cb.checked;
      cb.disabled = true;
      let ok = false;
      try {
        // The item NAME decides whether a comment goes with the tick
        // (Initial Photo Report, Initial Upload, Order Docusketch).
        // It lives in the sibling span, so read it rather than
        // threading it through every render.
        const _nm = cb.parentElement.querySelector("span");
        const r = await pywebview.api.toggle_checklist_item(
          cardId, itemId, want, _nm ? _nm.textContent.trim() : "",
          (typeof clientName !== "undefined" && clientName) || "");
        ok = !!(r && r.ok);
      } catch (_) { ok = false; }
      cb.disabled = false;
      if (!ok) { cb.checked = !want; setStatus("Trello update failed", "error"); return; }
      const span = cb.parentElement.querySelector("span");
      if (span) span.className = want ? "cl-done" : "";
      setStatus(want ? "Ticked ✓" : "Un-ticked", "ok");
    });
  });
}

// ⭐ Toggle starred status for a client — cross-panel shared list.
// The HomeApi `toggle_starred_client` flips persistence then
// returns the new state; we update local state + re-render the
// row's star icon without a full panel reload.
async function toggleStarred(client) {
  if (!client) return;
  const res = await pywebview.api.toggle_starred_client(client);
  if (!res?.ok) {
    setStatus(`Star toggle failed: ${res?.error || "?"}`, "error");
    return;
  }
  const lc = client.toLowerCase();
  const cur = new Set(state.starred_clients);
  if (res.starred) cur.add(lc); else cur.delete(lc);
  state.starred_clients = [...cur];
  renderList();
  setStatus(res.starred ? `★ Starred ${client}` : `☆ Unstarred ${client}`, "ok");
}

let searchTimer = null;
function onSearchInput(ev) {
  state.search = ev.target.value;
  // Clearing the box no longer discards what you've pulled up — the jobs
  // you searched stay on the Search tab so you can work across several at
  // once. Use ✕ Clear results to empty the list deliberately.
  if (!state.search.trim()) {
    state.oneoffTried = "";
  }
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    renderList();
    renderDetail();
    // Typing no longer triggers an audit. It used to run a FULL one-off
    // audit (folder walk + SharePoint scan) at 3 characters against a
    // single guessed name — slow, and it gave one answer instead of a
    // choice. Now we ask the job index for candidates and let you pick;
    // the scan happens on the pick.
    const q = state.search.trim();
    if (q.length >= 3) {
      await showSuggestions(q);
    } else {
      hideSuggestions();
    }
  }, 180);
}

// ── Type-ahead ────────────────────────────────────────────────────────
// Pure DB read via suggest_jobs — no disk, no network, so this can run on
// keystrokes. Picking a row is what triggers the expensive audit.

function hideSuggestions() {
  state.suggestSeq = (state.suggestSeq || 0) + 1;   // cancel in-flight
  $("#suggest-box")?.remove();
}

async function showSuggestions(q) {
  const seq = (state.suggestSeq || 0) + 1;
  state.suggestSeq = seq;
  let res = null;
  try {
    res = await pywebview.api.suggest_jobs(q, 8);
  } catch (ex) {
    return;
  }
  // A slower earlier request must not overwrite a newer one's results.
  if (seq !== state.suggestSeq) return;

  const rows = (res && res.ok && res.rows) || [];
  renderSuggestions(q, rows);
  // Then let Trello catch up. suggest_jobs is a pure DB read and only
  // knows jobs we've already recorded, but work is STARTED on the board —
  // searching "Bell Mountain" showed nothing while three cards carried
  // the name, one live on WORK IN PROGRESS. Fired after the local rows
  // are on screen so the network never delays the instant answer.
  appendTrelloSuggestions(q, seq);
}

// Trello rows land in the SAME dropdown, appended under a divider, so
// arrow-key nav keeps working across both groups (it re-queries
// .suggest-row). Guarded by suggestSeq: a slow reply for a query you've
// already typed past must not paint over the current one.
async function appendTrelloSuggestions(q, seq) {
  let res = null;
  try {
    res = await pywebview.api.suggest_trello(q, 6);
  } catch (ex) {
    return;                       // offline / rate-limited — local stands
  }
  if (seq !== state.suggestSeq) return;
  const rows = (res && res.ok && res.rows) || [];
  if (!rows.length) return;
  const el = $("#suggest-box");
  if (!el) return;                // dropdown closed while we waited
  // Don't repeat a job the local index already offered.
  const have = new Set([...el.querySelectorAll(".suggest-name")]
    .map((n) => (n.textContent || "").trim().toLowerCase()));
  const fresh = rows.filter((r) =>
    !have.has((r.name || "").trim().toLowerCase()));
  if (!fresh.length) return;
  const head = document.createElement("div");
  head.className = "suggest-group";
  head.textContent = "On Trello";
  el.appendChild(head);
  fresh.forEach((r) => {
    const row = document.createElement("div");
    row.className = "suggest-row";
    row.tabIndex = 0;
    const where = [r.board, r.lane].filter(Boolean).join(" · ");
    row.innerHTML = `<span>🎴</span>`
      + `<span class="suggest-name">${escapeHtml(r.name)}</span>`
      + (where ? `<span class="suggest-why">${escapeHtml(where)}</span>` : "");
    // Picking a card IS choosing the card for the job — pin it before the
    // audit, the same order the deep picker uses. Without this the audit
    // ran against the name only and the card you just chose was thrown
    // away, so the job came back with no Trello pin at all.
    const go = async () => {
      hideSuggestions();
      if (r.card_id) {
        try {
          const p = await pywebview.api.pin_trello(r.name, r.card_id);
          if (!p?.ok) setStatus(`Pin failed: ${p?.error || "?"}`, "warn");
        } catch (ex) {
          setStatus(`Pin failed: ${ex}`, "warn");
        }
      }
      runOneoffFromSearch(r.name, true);
    };
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); go(); }
    });
    el.appendChild(row);
  });
}

// Create (or reuse) the dropdown under the search box. Reused rather than
// recreated so the deep picker below can repaint in place — rebuilding it
// mid-flow would drop the listeners the picker just wired.
function ensureSuggestBox() {
  const box = $("#search-box");
  if (!box) return null;
  let el = $("#suggest-box");
  if (!el) {
    el = document.createElement("div");
    el.id = "suggest-box";
    el.className = "suggest-box";
    ($("#search-wrap") || box.parentNode).appendChild(el);
  }
  return el;
}

function renderSuggestions(q, rows) {
  const el = ensureSuggestBox();
  if (!el) return;
  if (!rows.length) {
    // A name the index has never seen is exactly when someone needs to
    // force an audit, so that stays ONE click. Folding it behind the
    // deep-scan row cost a click and renamed the control people reach
    // for — reported as "I can't force an audit any more".
    el.innerHTML = `<div class="suggest-empty">No job matches “${escapeHtml(q)}”</div>`
      + `<div class="suggest-row sg-force" tabindex="0">`
      + `<span>🔍</span>`
      + `<span class="suggest-name">Search folders for “${escapeHtml(q)}”</span>`
      + `<span class="suggest-why">audit it</span>`
      + `</div>`;
  } else {
    const KIND = { unit: "🏢 unit", claim: "📄 claim", subjob: "🔧 sub-job" };
    el.innerHTML = rows.map((r, i) => {
      const why = r.why && r.why !== "starts with" && r.why !== "matches"
        ? `<span class="suggest-why">${escapeHtml(r.why)}</span>` : "";
      // A child is a different thing from a client — say which, or
      // "Unit 418" and "Metro at Main" look like the same kind of row.
      const kind = r.child_kind
        ? `<span class="suggest-why">${escapeHtml(KIND[r.child_kind] || r.child_kind)}</span>`
        : "";
      const dept = r.department
        ? `<span class="suggest-dept">${escapeHtml(r.department)}</span>` : "";
      return `<div class="suggest-row" data-i="${i}" tabindex="0">`
        + `<span class="suggest-name">${escapeHtml(r.display_name)}</span>`
        + kind + why + dept + `</div>`;
    }).join("");
  }
  // Type-ahead is a DB read, so it can't see a job that has a folder but
  // no row yet, and it carries no variant/card data. This row is the way
  // down to the authoritative scan.
  el.insertAdjacentHTML("beforeend",
    `<div class="suggest-row sg-deep" tabindex="0">`
    + `<span>🗂</span>`
    + `<span class="suggest-name">Search folders — all years, merge, attach a card…</span>`
    + `</div>`);

  bindSuggestKeys(el);
  el.querySelectorAll(".suggest-row[data-i]").forEach((row) => {
    row.addEventListener("click", () => pickSuggestion(rows[+row.dataset.i]));
  });
  // An async handler that throws becomes an unhandled rejection — no
  // error, no log, nothing on screen. Report it instead: a button that
  // says why it failed is debuggable; one that does nothing is not.
  const go = (scope) => {
    try {
      const p = runDeepPicker(q, scope);
      if (p && p.catch) p.catch((ex) => setStatus(`Folder search failed: ${ex}`, "error"));
    } catch (ex) {
      setStatus(`Folder search failed: ${ex}`, "error");
    }
  };
  const deep = el.querySelector(".sg-deep");
  deep?.addEventListener("click", () => go(""));
  deep?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") go("");
  });
  // Same scan, straight from the empty state. It goes through the picker
  // rather than the old blind fuzzy match, so a weak match still can't
  // silently audit the wrong job — it just doesn't cost an extra click to
  // reach.
  const force = el.querySelector(".sg-force");
  force?.addEventListener("click", () => go(""));
  force?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") go("");
  });
}

// Arrow/Escape movement, shared by the type-ahead and the deep picker so
// both lists navigate the same way.
function bindSuggestKeys(el) {
  el.querySelectorAll(".suggest-row").forEach((row) => {
    row.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { hideSuggestions(); $("#search-box")?.focus(); return; }
      const all = Array.from(el.querySelectorAll(".suggest-row"));
      const i = all.indexOf(row);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        (all[i + 1] || all[0]).focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (i === 0) $("#search-box")?.focus(); else all[i - 1].focus();
      }
    });
  });
}

// ── Deep candidate picker ────────────────────────────────────────────
// Was the "🔍 Audit one" toolbar dialog. Same three sources (run-doc,
// pinned cards, year folders) and the same confirm-before-auditing rule,
// reached from Search instead of a button of its own — so there's one
// place to look up a job rather than two that half-overlapped.
//
// list_audit_candidates hits disk, so it stays behind a deliberate click;
// the type-ahead above remains a pure DB read safe to run on keystrokes.

function auditCandidateIcon(c) {
  const srcs = (c.sources && c.sources.length) ? c.sources : [c.source];
  if (srcs.includes("run")) return "📋";
  if (srcs.includes("pin")) return "📌";
  if (srcs.includes("folder")) return "📁";
  // Found only on Trello — no folder here yet. Jobs are started on the
  // board today, so this is a normal result, not an error.
  return srcs.includes("trello") ? "🎴" : "•";
}

// skip_canon=true — the user just told us which job this is, so don't
// re-fuzz the name. A child carries its own folder; pass it so the audit
// pins THAT folder instead of resolving back to the parent client.
async function auditCandidate(c) {
  hideSuggestions();
  await runOneoffFromSearch(c.name, true, c.path || "");
}

// Cardless job → offer a Trello card, THEN audit. 1 match → attach/skip;
// several → pick-list; none → audit anyway.
async function offerCardThenAudit(host, c) {
  host.innerHTML = `<div class="suggest-empty">Looking for a Trello card for ${escapeHtml(c.name)}…</div>`;
  let cards = [];
  try {
    const sres = await pywebview.api.suggest_card_for(c.name);
    cards = (sres && sres.cards) || [];
  } catch (_) { cards = []; }
  if (!cards.length) { auditCandidate(c); return; }
  host.innerHTML =
    `<div class="suggest-empty">${cards.length === 1
      ? "Found a matching Trello card — attach it?"
      : `Found ${cards.length} possible cards — pick one:`}</div>`
    + cards.map((cd, i) => `
        <div class="suggest-row sg-card" data-i="${i}" tabindex="0">
          <span>📎</span>
          <span class="suggest-name">${escapeHtml(cd.name)}</span>
          <span class="suggest-dept">${escapeHtml(cd.board || "")}${cd.list_name ? " · " + escapeHtml(cd.list_name) : ""}</span>
        </div>`).join("")
    + `<div class="suggest-row sg-skipcard" tabindex="0"><span>⏭</span>`
    + `<span class="suggest-name">Skip — audit without a card</span></div>`;
  bindSuggestKeys(host);
  host.querySelectorAll(".sg-card").forEach((el) => {
    el.addEventListener("click", async () => {
      const cd = cards[+el.dataset.i];
      try { await pywebview.api.pin_trello(c.name, cd.card_id); } catch (_) {}
      auditCandidate(c);
    });
  });
  host.querySelector(".sg-skipcard")?.addEventListener("click",
    () => auditCandidate(c));
}

function renderAuditCandidates(host, cands, typed, widened) {
  const head = cands.length
    ? `${cands.length} match${cands.length !== 1 ? "es" : ""} — pick the right one:`
    : (widened ? `No matches anywhere for “${escapeHtml(typed)}”.`
               : `No current-year matches for “${escapeHtml(typed)}”.`);
  const rows = cands.map((c, i) => `
    <div class="suggest-row sg-cand" data-i="${i}" tabindex="0">
      <span>${auditCandidateIcon(c)}</span>
      <span class="suggest-name">${escapeHtml(titleCase(c.label || c.name))}</span>
      ${c.detail ? `<span class="suggest-dept">${escapeHtml(c.detail)}</span>` : ""}
      ${(!c.has_card && !c.path) ? `<span class="suggest-why">no folder/card</span>` : ""}
      ${c.mergeable ? `<button class="btn sg-merge" data-i="${i}"
          style="font-size:10px;padding:2px 8px;flex:none;"
          title="Fold ${c.variants.length} duplicate spellings into one job">🔗 ${c.variants.length}</button>` : ""}
    </div>`).join("");
  // Widen only while we're still on the current year.
  const moreRow = !widened
    ? `<div class="suggest-row sg-more" tabindex="0"><span>🗂</span>
         <span class="suggest-name">Search all years + fire jobs…</span></div>`
    : "";
  // The old auto-resolve, kept as an explicit choice rather than the
  // default — picking the top fuzzy match silently audits the wrong job.
  const rawRow = `
    <div class="suggest-row sg-raw" tabindex="0" style="opacity:.85;">
      <span>⌨</span>
      <span class="suggest-name">Audit “${escapeHtml(typed)}” as typed</span>
      <span class="suggest-why">auto-resolve</span>
    </div>`;
  host.innerHTML = `<div class="suggest-empty">${head}</div>`
    + rows + moreRow + rawRow;

  bindSuggestKeys(host);
  host.querySelectorAll(".sg-cand").forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (ev.target.closest(".sg-merge")) return;   // merge handled below
      const c = cands[+el.dataset.i];
      // Same reasoning as the scan button: an async handler that throws
      // here reaches nothing at all, so the row just looks dead.
      setStatus(`🔍 Auditing ${c && c.name ? c.name : "job"}…`, "info");
      try {
        const p = (!c.has_card) ? offerCardThenAudit(host, c) : auditCandidate(c);
        if (p && p.catch) p.catch((ex) => setStatus(`Audit failed: ${ex}`, "error"));
      } catch (ex) {
        setStatus(`Audit failed: ${ex}`, "error");
      }
    });
  });
  host.querySelectorAll(".sg-merge").forEach((el) => {
    el.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const c = cands[+el.dataset.i];
      host.innerHTML = `<div class="suggest-empty">Merging ${c.variants.length} spellings into ${escapeHtml(c.name)}…</div>`;
      let res;
      try { res = await pywebview.api.merge_candidates(c.name, c.variants); }
      catch (ex) { res = { ok: false, error: String(ex) }; }
      if (!res?.ok) {
        host.innerHTML = `<div class="suggest-empty">Merge failed: ${escapeHtml(res?.error || "?")}</div>`;
        return;
      }
      setStatus(`🔗 Merged ${res.dropped} duplicate${res.dropped === 1 ? "" : "s"} into ${c.name}`, "ok");
      runDeepPicker(typed, widened ? "all" : "");   // re-list — dupes gone
    });
  });
  host.querySelector(".sg-more")?.addEventListener("click",
    () => runDeepPicker(typed, "all"));
  host.querySelector(".sg-raw")?.addEventListener("click", () => {
    hideSuggestions();
    runOneoffFromSearch(typed);
  });
}

async function runDeepPicker(typed, scope) {
  // Say something in the STATUS BAR too, not only in the dropdown. A JS
  // error in here reached nowhere: it doesn't go to ems.log, and the
  // dropdown it would have drawn into is the thing that failed — so a
  // dead click looked like a dead button with nothing to go on.
  try { setStatus(`🔍 Searching folders for “${typed}”…`, "info"); } catch (_) {}
  const t = (typed || "").trim();
  if (!t) return;
  const host = ensureSuggestBox();
  if (!host) {
    try { setStatus("Couldn't open the results list", "error"); } catch (_) {}
    return;
  }
  // Cancel any in-flight type-ahead so its results can't repaint over the
  // picker after the slower scan has already drawn.
  state.suggestSeq = (state.suggestSeq || 0) + 1;
  host.innerHTML = `<div class="suggest-empty">Searching ${scope === "all" ? "all years" : "folders"} for “${escapeHtml(t)}”…</div>`;
  let res;
  try { res = await pywebview.api.list_audit_candidates(t, scope || ""); }
  catch (ex) { res = { ok: false, error: String(ex) }; }
  if (!res?.ok) {
    host.innerHTML = `<div class="suggest-empty">Search failed: ${escapeHtml(res?.error || "?")}</div>`;
    return;
  }
  const cands = res.candidates || [];
  // Exactly one match is not a choice. The picker exists so a weak match
  // can't silently audit the wrong job — with a single hit from a scan
  // the user explicitly asked for, there is no ambiguity to resolve, and
  // making them click a list of one is what made this read as "the
  // button does nothing": the scan ran, a list appeared, and nothing
  // seemed to happen because the second click was never obvious.
  if (cands.length === 1 && cands[0]) {
    const only = cands[0];
    setStatus(`🔍 ${only.name} — auditing…`, "info");
    if (only.has_card) {
      hideSuggestions();
      await auditCandidate(only);
    } else {
      // No card yet: offering one before auditing is the point of that
      // step, and it draws into the dropdown — so the list stays open
      // for it rather than being hidden first.
      await offerCardThenAudit(host, only);
    }
    return;
  }
  renderAuditCandidates(host, cands, t, scope === "all");
}

// The pick is where the real work starts: we already know the canonical
// name, so skip_canon avoids re-fuzzing a name the user just confirmed.
// A child (unit / claim / sub-job) carries its own folder — pass it so the
// audit pins THAT folder instead of re-resolving to the parent client.
async function pickSuggestion(r) {
  if (!r) return;
  hideSuggestions();
  await runOneoffFromSearch(r.audit_name || r.display_name, true,
                            r.folder_path || "");
}

// Run a one-off audit for a typed search term and surface the result in
// the list. Shared by the auto-fallback and the empty-state button.
async function runOneoffFromSearch(term, skipCanon, folderPath) {
  const t = (term || "").trim();
  if (!t || state.oneoffRunning) return;
  // The result lands on Recent and shows nowhere else, so searching from
  // Daily Run or Starred used to audit the job into a tab you weren't
  // looking at — it read as "nothing happened". Switch first, so the
  // audit visibly runs where its result will appear. Matches what the
  // "Audit one" dialog already does.
  if (state.mode !== "search") await switchMode("search");
  state.oneoffRunning = true;
  state.oneoffTried = t;
  renderList();  // repaint the empty-state button as "Searching…"
  setStatus(`🔍 Auditing “${t}” — scanning folders…`, "info");
  try {
    const res = await pywebview.api.audit_one_job(t, folderPath || "",
                                                  !!skipCanon);
    if (res?.ok && (res.rows || []).length) {
      // ACCUMULATE rather than replace: searching a second job used to
      // wipe the first, so you couldn't hold two jobs side by side on the
      // Search tab. Newest first, deduped by row key, capped so a long
      // session doesn't grow an unbounded list.
      const fresh = res.rows;
      const seen = new Set(fresh.map(rowKey));
      const kept = (state.oneoffHits || []).filter((h) => !seen.has(rowKey(h)));
      state.oneoffHits = fresh.concat(kept).slice(0, ONEOFF_MAX);
      saveRecents();
      // The job you picked is now ON the tab, so the term that found it has
      // done its work — and it's also a FILTER, so leaving it there hides
      // every other job you pulled up. Clear it: the box is ready for the
      // next name and the tab shows everything you're holding.
      // oneoffTried too, or re-typing the same name is treated as a repeat
      // and silently does nothing.
      state.search = "";
      state.oneoffTried = "";
      const sb = $("#search-box");
      if (sb) sb.value = "";
      hideSuggestions();
      // Land ON the job just audited. The removed "Audit one" dialog did
      // this; without it you clear the box and lose track of which of the
      // held rows is the one you just pulled up.
      const landed = res.row || fresh[0];
      if (landed) state.selected_client = rowKey(landed);
      renderList();
      renderDetail();
      if (landed && typeof scrollSelectedIntoView === "function") {
        scrollSelectedIntoView();
      }
      const held = state.oneoffHits.length;
      setStatus(
        `🔍 ${firstLast(res.canonical)}`
        + (res.resolved ? ` (from “${t}”)` : "")
        + ` — ${res.count} row${res.count === 1 ? "" : "s"}`
        + (held > res.count ? ` · ${held} jobs on this tab` : ""), "ok");
    } else {
      setStatus(res?.error
        ? `No one-off match for “${t}”: ${res.error}`
        : `No job found for “${t}”`, "warn");
    }
  } catch (ex) {
    setStatus(`One-off audit failed: ${ex}`, "error");
  } finally {
    state.oneoffRunning = false;
    renderList();
  }
}

// ── Detail actions ───────────────────────────────────────────────
async function onDetailAction(action, row) {
  return window.AuditDetail.detailAction(action, row, buildAuditDetailCtx());
}

// ── Archive month modal (P2) ────────────────────────────────────
// ── 🆘 Escalation contacts modal (mirrors Tk _open_escalation_contacts_dialog) ──
// Set the email address for each escalation role (Estimator, Lead,
// Owner, etc.) — used by the per-row 🆘 Escalate button to know
// who gets the Teams message. Without this the Escalate action
// fails with "no email for role".
async function openArchiveMonthModal() {
  // Default to LAST month — that's the common workflow (early-of-
  // month cleanup of the prior month's photos).
  const now = new Date();
  let y = now.getFullYear(), m = now.getMonth(); // 0-indexed; -1 = last month
  if (m === 0) { y -= 1; m = 12; } else { m = m; }
  const monthNames = ["January","February","March","April","May","June",
                      "July","August","September","October","November","December"];
  const overlay = createOverlay({
    title: "🗄 Archive month",
    sub:   "Move every dated tech folder into a MonthName YYYY archive under its tech.",
    body: `
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px;">
        <label class="modal-lbl" style="margin:0;">Year</label>
        <input id="am-year" type="number" min="2020" max="2099" value="${y}"
               class="search" style="width:90px;" />
        <label class="modal-lbl" style="margin:0;">Month</label>
        <select id="am-month" class="search" style="width:140px;">
          ${monthNames.map((n, i) =>
            `<option value="${i+1}" ${i+1 === m ? "selected" : ""}>${n}</option>`).join("")}
        </select>
        <button class="btn btn-primary" id="am-scan">🔎 Scan</button>
      </div>
      <div id="am-result" style="max-height:420px;overflow-y:auto;"></div>
      <div class="modal-footer">
        <button class="btn modal-close">Cancel</button>
        <span style="flex:1;"></span>
        <button class="btn btn-primary" id="am-apply" disabled>🗄 Move selected</button>
      </div>`,
  });

  let lastPlan = null;
  async function scan() {
    const year = parseInt(overlay.querySelector("#am-year").value || y, 10);
    const month = parseInt(overlay.querySelector("#am-month").value || m, 10);
    overlay.querySelector("#am-result").innerHTML =
      `<div style="padding:14px;text-align:center;color:var(--text-muted);">Walking photo roots…</div>`;
    const res = await pywebview.api.archive_month_plan(year, month);
    if (!res?.ok) {
      overlay.querySelector("#am-result").innerHTML =
        `<div style="padding:14px;color:var(--red);">Error: ${escapeHtml(res?.error || "?")}</div>`;
      return;
    }
    lastPlan = res;
    if (!res.total) {
      overlay.querySelector("#am-result").innerHTML =
        `<div style="padding:14px;text-align:center;color:var(--text-muted);">No folders match this month.</div>`;
      overlay.querySelector("#am-apply").disabled = true;
      return;
    }
    overlay.querySelector("#am-result").innerHTML = `
      <div style="margin-bottom:8px;color:var(--text-muted);font-size:11px;">
        ${res.total} folders across ${res.groups.length} techs · select to move
      </div>
      ${res.groups.map((g) => `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-weight:600;">
            <input type="checkbox" data-tech="${escapeAttr(g.tech)}" class="am-tech-all" checked />
            <span>👷 ${escapeHtml(g.tech)} (${g.count})</span>
          </div>
          ${g.folders.map((f) => `
            <label style="display:flex;gap:8px;padding:3px 0 3px 22px;font-size:12px;cursor:pointer;">
              <input type="checkbox" class="am-folder" data-tech="${escapeAttr(g.tech)}" data-src="${escapeAttr(f.src)}" checked />
              <span>${escapeHtml(f.name)}</span>
            </label>`).join("")}
        </div>`).join("")}
    `;
    overlay.querySelector("#am-apply").disabled = false;
    // Wire tech-level select-all checkboxes
    overlay.querySelectorAll(".am-tech-all").forEach((cb) =>
      cb.addEventListener("change", (e) => {
        e.stopPropagation();
        overlay.querySelectorAll(`.am-folder[data-tech="${cb.dataset.tech}"]`)
          .forEach((c) => c.checked = cb.checked);
      }));
  }
  overlay.querySelector("#am-scan").addEventListener("click", scan);
  overlay.querySelector("#am-apply").addEventListener("click", async () => {
    if (!lastPlan) return;
    const srcs = Array.from(overlay.querySelectorAll(".am-folder"))
      .filter((c) => c.checked).map((c) => c.dataset.src);
    if (!srcs.length) return setStatus("Nothing selected", "warn");
    if (!confirm(`Move ${srcs.length} folder${srcs.length !== 1 ? "s" : ""} into ${["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][lastPlan.month]} ${lastPlan.year} archives?`)) return;
    const btn = overlay.querySelector("#am-apply");
    btn.disabled = true; btn.textContent = "Moving…";
    const res = await pywebview.api.archive_month_apply(
      lastPlan.year, lastPlan.month, srcs);
    btn.textContent = "🗄 Move selected"; btn.disabled = false;
    if (!res?.ok) { setStatus(`Archive failed: ${res?.error || "?"}`, "error"); return; }
    closeOverlay();
    setStatus(`🗄 Archived ${res.moved} folders${res.errors.length ? ` (${res.errors.length} errors)` : ""}`, "ok");
  });
  scan();
}

// ── SP Importer modal (P1) ──────────────────────────────────────
async function openSpImportModal(row) {
  const overlay = createOverlay({
    title: "📥 Import from SharePoint",
    sub:   `Client: ${row.client}`,
    // Wider than the default 620 — every SP row has 7 action buttons
    // (Why / Run-doc / Open / Pull / In-OD / Copy / Reject) plus the
    // folder name + tech / count line. At 620 the buttons wrapped or
    // truncated the name. 960 fits everything inline on a normal
    // 1280-wide window and still leaves the panel anchored to the
    // viewport.
    width: 960,
    body: `
      <div id="sp-status" class="muted"></div>
      <div id="sp-list" class="target-list"
           style="margin-top:10px;max-height:540px;overflow-y:auto;"></div>
      <div class="modal-footer">
        <label id="sp-side-toggle" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;user-select:none;"
               title="Route this import into the CONTENTS side (CONTENTS/PICS) instead of EMS/PICS">
          <input type="checkbox" id="sp-contents" style="cursor:pointer;" /> 📦 Contents side
        </label>
        <button class="btn" id="sp-pin">📎 Pin folder…</button>
        <button class="btn" id="sp-open-rundoc" title="Open the run-doc for this SP folder's date">📄 Run-doc</button>
        <button class="btn" id="sp-rescan">↻ Re-scan SharePoint</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  function renderMatches(matches, source) {
    const tag = source === "cached" ? "  ·  from last audit"
              : source === "live"   ? "  ·  fresh from SharePoint"
              :                       "";
    document.getElementById("sp-status").textContent =
      matches.length
        ? `${matches.length} SharePoint folder${matches.length !== 1 ? "s" : ""} match this client${tag}`
        : `No SharePoint folders match${tag}. Use 📎 Pin folder… below to attach one manually.`;
    document.getElementById("sp-list").innerHTML = matches.map((m, i) => {
      // Per-match diff breakdown — surfaces the audit's reasoning so
      // the user can see WHY N files are flagged "new" (vs blindly
      // trusting the count). Stats: name = basename hit in OD,
      // fp = (size,mtime) fingerprint hit, size = size-only fallback
      // hit, new = still genuinely new after all three checks.
      const st = m.match_stats || {};
      const breakdownTitle = (st.total || m.img_count || 0)
        ? `Of ${st.total || m.img_count} SP files: ${st.name || 0} matched by name, ${st.fp || 0} by fingerprint, ${st.size || 0} by size, ${st.new || m.new_count || 0} still flagged new`
        : "";
      const newSample = (m.new_names && m.new_names.length)
        ? `\n\nFlagged new (first ${Math.min(m.new_names.length, 10)}): ${m.new_names.slice(0, 10).join(", ")}${m.new_names.length > 10 ? "…" : ""}`
        : "";
      return `
      <div class="target-row" data-i="${i}" data-path="${escapeAttr(m.path)}"
           style="grid-template-columns:auto 1fr auto auto auto auto auto auto;gap:8px;">
        <span title="${m.matches_date ? 'Matches run date' : ''}">${m.matches_date ? "✓" : "📁"}</span>
        <div>
          <div class="name">${escapeHtml(m.name)}</div>
          <div style="font-size:11px;color:var(--text-muted);"
               title="${escapeAttr(breakdownTitle + newSample)}">
            ${escapeHtml(m.tech || "—")} · ${m.img_count} files · ${m.new_count} new
            ${(st.total && st.new !== undefined && st.new < st.total)
              ? `<span style="margin-left:6px;color:var(--text-dim);">(${(st.name || 0) + (st.fp || 0) + (st.size || 0)} already in OD)</span>`
              : ""}
            <span class="sp-cloud-tag" data-i="${i}" style="margin-left:6px;"></span>
          </div>
        </div>
        <button class="action-btn" data-act="why" title="Show file-level diff — exactly which files the audit thinks are new">🔍 Why?</button>
        <button class="action-btn" data-act="rundoc" title="Open the run-doc for THIS folder's date (parsed from name, e.g. '3-19-26' → 3/19)">📄</button>
        <button class="action-btn" data-act="open" title="Open in Explorer">📁</button>
        <button class="action-btn" data-act="pull" title="Download all OneDrive cloud-only placeholders so they're actually on disk" style="display:none;">☁ Pull</button>
        <button class="action-btn" data-act="mark_od" title="These are already in OD (renamed/recompressed) — don't flag as new again" ${m.img_count > 0 ? "" : "disabled"}>✓ In OD</button>
        <button class="action-btn primary" data-act="copy" ${m.new_count > 0 ? "" : "disabled"}>📥 Copy +${m.new_count}</button>
        <button class="action-btn warn" data-act="reject" title="Hide this from future scans">✕</button>
      </div>`;
    }).join("");
    wireButtons();
    // Async cloud-only count per match — fires off in parallel so
    // the list paints immediately; chip updates as each completes.
    matches.forEach(async (m, i) => {
      try {
        const r = await pywebview.api.sp_cloud_only_count(m.path);
        const chip = document.querySelector(`.sp-cloud-tag[data-i="${i}"]`);
        const pullBtn = document.querySelector(`.target-row[data-i="${i}"] .action-btn[data-act="pull"]`);
        if (chip && r?.ok && r.count > 0) {
          chip.innerHTML = `<span style="background:var(--amber);color:#FFF;padding:1px 6px;border-radius:3px;font-weight:700;font-size:10px;" title="${r.count} OneDrive cloud-only placeholders — click ☁ Pull to download them first">☁ ${r.count} cloud-only</span>`;
          if (pullBtn) pullBtn.style.display = "";
        }
      } catch (_) {}
    });
  }

  // Show the pre-computed matches from the last audit FIRST so the
  // user sees results instantly instead of waiting for a re-walk.
  // The ↻ Re-scan button forces a live SharePoint walk if needed.
  if ((row.sharepoint_matches || []).length) {
    renderMatches(row.sharepoint_matches, "cached");
  } else {
    document.getElementById("sp-status").textContent =
      "Scanning SharePoint…";
  }

  async function scan() {
    document.getElementById("sp-status").textContent =
      "🔎 Searching SharePoint…";
    document.getElementById("sp-list").innerHTML = "";
    const res = await pywebview.api.sp_find_matches(row.client, "");
    if (!res?.ok) {
      document.getElementById("sp-status").textContent =
        "Error: " + (res?.error || "?");
      return;
    }
    renderMatches(res.matches || [], "live");
    // Explicit completion toast so user knows the scan finished.
    setStatus(
      res.matches?.length
        ? `✓ SP scan complete — ${res.matches.length} folder${res.matches.length !== 1 ? "s" : ""} found`
        : "✓ SP scan complete — no matches (try 📎 Pin folder)",
      "ok");
  }

  async function pinFolder() {
    setStatus("Pick a SharePoint folder…");
    const picked = await pywebview.api.sp_browse_for_folder();
    if (!picked) {
      setStatus("Pin canceled", "warn");
      return;
    }
    setStatus(`📎 Attaching ${picked}…`);
    const res = await pywebview.api.sp_pin_folder(row.client, picked);
    if (!res?.ok) {
      setStatus(`Pin failed: ${res?.error || "?"}`, "error");
      return;
    }
    if (res.outside_root) {
      setStatus(`⚠ Pinned (outside photos root): ${res.match.name}`, "warn");
    } else {
      setStatus(`📎 Pinned: ${res.match.name} — ${res.match.new_count} new files ready to copy`, "ok");
    }
    // Refresh the list — fastest path is to re-scan so pinned overrides
    // appear in their natural order alongside auto-matches.
    await scan();
  }

  function wireButtons() {
    document.querySelectorAll("#sp-list .action-btn[data-act]").forEach((btn) =>
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const parent = btn.closest(".target-row");
        const path = parent.dataset.path;
        const act = btn.dataset.act;
        if (act === "open") {
          await pywebview.api.sp_open_folder(path);
        } else if (act === "why") {
          // Diff explainer — show the user exactly why this folder
          // shows N new. Pulls the breakdown stats + sample of
          // flagged names off the cached row.
          const idx = parseInt(parent.dataset.i, 10);
          const m = (row.sharepoint_matches || [])[idx];
          if (!m) return;
          const st = m.match_stats || {};
          const sample = (m.new_names || []).slice(0, 30);
          openSpWhyModal(row, m, st, sample);
        } else if (act === "rundoc") {
          // Per-row run-doc opener — resolves the date FROM THIS
          // folder's name (e.g. "Smith 3-19-26 Demo" → 3/19/26)
          // and opens that day's run-doc. Walks back up to 7 days
          // if the exact day has no run-doc (weekend coverage).
          const res = await pywebview.api.open_rundoc_for_sp_match(path);
          if (res?.ok) {
            const back = res.days_back > 0 ? ` · ${res.days_back}d back` : "";
            const tail = res.source && res.source !== "today"
              ? ` (from ${res.source})` : "";
            setStatus(`📄 Opening ${res.date_label}${tail}${back}`, "ok");
          } else {
            setStatus(`Couldn't open: ${res?.error || "no run-doc"}`, "warn");
          }
        } else if (act === "pull") {
          // Force-pull every cloud-only file in this SP folder.
          // Streams sp:pull-progress events for the toast; ends
          // with sp:pull-done. Disables the button while running.
          btn.disabled = true;
          btn.textContent = "Pulling…";
          // Indeterminate from the click. The first sp:pull-progress
          // event only lands once the walk has found something, so
          // starting the bar on that event left the opening wait blank.
          if (window.Progress) window.Progress.start();
          const r = await pywebview.api.sp_force_pull(path);
          if (!r?.started) {
            if (window.Progress) window.Progress.fail();
            btn.disabled = false; btn.textContent = "☁ Pull";
            setStatus(`Pull busy: ${r?.reason || "?"}`, "warn");
          }
        } else if (act === "reject") {
          await pywebview.api.sp_reject_match(row.client, path);
          parent.style.display = "none";
          setStatus("Match rejected — won't show again", "ok");
        } else if (act === "mark_od") {
          btn.disabled = true; btn.textContent = "Marking…";
          const res = await pywebview.api.sp_mark_in_od(row.client, path);
          if (!res?.ok) {
            setStatus(`Mark in OD failed: ${res?.error || "?"}`, "error");
            btn.disabled = false; btn.textContent = "✓ In OD";
            return;
          }
          btn.textContent = `✓ Marked (${res.marked})`;
          parent.style.opacity = "0.6";
          setStatus(`✓ ${res.marked} files marked as already-in-OD — future audits won't flag them`, "ok");
        } else if (act === "copy") {
          btn.disabled = true; btn.textContent = "Copying…";
          // Pass row.path so the backend doesn't depend on
          // persistence.get_folder_path — the audit already
          // resolved the job folder. `side` routes to EMS or CONTENTS.
          const side = document.getElementById("sp-contents")?.checked
            ? "contents" : "ems";
          let res = await pywebview.api.sp_copy_to_pics(
            row.client, path, "", row.path || "", side, "");
          // SP folders are usually named by the tech; only prompt when the
          // backend couldn't determine one, then retry with the pick.
          if (res?.need_tech) {
            const t = await window.pickImportTech({ client: row.client, techs: row.techs });
            if (!t) { btn.disabled = false; btn.textContent = "📥 Copy"; return; }
            res = await pywebview.api.sp_copy_to_pics(
              row.client, path, "", row.path || "", side, t);
          }
          if (!res?.ok) {
            // "Couldn't resolve PICS folder" → the OD job folder
            // isn't pinned yet. Offer to open Find Folder so the
            // user can pick one without leaving the SP modal.
            const err = res?.error || "?";
            const needsFolder = /PICS folder|Pin the OD folder/i.test(err);
            if (needsFolder) {
              btn.disabled = false; btn.textContent = "📥 Copy";
              if (confirm(`No OD folder found for ${row.client}.\n\n${err}\n\nOpen the Find Folder dialog now to pick one?`)) {
                closeOverlay();
                openFindFolderModal(row);
              } else {
                setStatus(err, "warn");
              }
              return;
            }
            setStatus(`Copy failed: ${err}`, "error");
            btn.disabled = false;
            btn.textContent = "📥 Copy";
            return;
          }
          btn.textContent = `✓ ${res.copied} copied · ${res.skipped} skipped`;
          parent.style.opacity = "0.7";
          // Show the actual destination folder name (Tk format:
          // "<TECH> <DATE> <CLIENT> [TAG]") so the user sees exactly
          // where files landed. Also call out any cloud-only files
          // that were hydrated inline during the copy.
          const landed = res.folder_name || `From SharePoint - ${res.tech}`;
          const pullNote = res.pulled > 0
            ? ` · ☁ ${res.pulled} pulled from cloud`
            : "";
          const sideNote = res.side === "contents" ? " · 📦 Contents side" : "";
          setStatus(
            `✓ Copy complete: ${res.copied} new files copied (${res.skipped} dupes skipped${pullNote}${sideNote}) into ${landed}/`,
            "ok");
          // Re-audit so photo counts + SP +N chip update
          const re = await pywebview.api.reaudit_one(row.client);
          if (re?.ok) {
            applyRow(re.row);
            renderAll();
          }
        }
      }));
  }

  document.getElementById("sp-rescan").addEventListener("click", scan);
  document.getElementById("sp-pin").addEventListener("click", pinFolder);
  document.getElementById("sp-open-rundoc").addEventListener("click", async () => {
    // Pick the SP match best representing the date the tech was on
    // site: prefer one whose folder name matches the run-date, else
    // the most-recently-modified folder (sorted by mtime if backend
    // returns it). Tk's "📄 Run-doc" button uses the same heuristic.
    const matches = row.sharepoint_matches || [];
    const dated = matches.find((m) => m.matches_date) || matches[0];
    const path = dated?.path || "";
    const res = await pywebview.api.open_rundoc_for_sp_match(path);
    if (res?.ok) {
      const tail = res.source && res.source !== "today"
        ? ` (from SP ${res.source})`
        : "";
      const back = res.days_back > 0 ? ` · ${res.days_back}d back` : "";
      setStatus(`📄 Opening ${res.date_label}${tail}${back}`, "ok");
    } else {
      setStatus(`Couldn't open: ${res?.error || "no run-doc"}`, "warn");
    }
  });
  // Only auto-scan when we have NO cached matches to show — otherwise
  // the dialog renders the audit's pre-computed matches instantly
  // and the user clicks Re-scan if they need fresh data.
  if (!(row.sharepoint_matches || []).length) {
    scan();
  }
}

// ── SP "Why?" modal — file-level diff explainer ─────────────────
// User reported "+26 new but all 26 are in OD" symptoms. The audit's
// new-count is the residual after THREE matching passes (basename,
// fingerprint, size-when-unique); when all three miss, a file is
// flagged new. This modal surfaces the math + the actual flagged
// names so the user can verify before importing again.
function openSpWhyModal(row, m, stats, sample) {
  const matchedTotal = (stats.name || 0) + (stats.fp || 0) + (stats.size || 0);
  const inOdNote = (stats.total && matchedTotal === stats.total)
    ? `<div style="background:rgba(46,204,113,.10);border:1px solid var(--green);border-radius:6px;padding:10px 14px;margin-bottom:10px;">
         ✅ <strong>All ${stats.total} files in this SP folder were matched in OneDrive.</strong>
         The "+${stats.new || m.new_count}" chip means the audit is showing a stale count — re-run the audit to refresh.
       </div>`
    : matchedTotal === 0 && stats.total
      ? `<div style="background:rgba(245,166,35,.10);border:1px solid var(--amber);border-radius:6px;padding:10px 14px;margin-bottom:10px;">
           ⚠ <strong>None of the SP files matched anything in OneDrive.</strong>
           Either (a) this folder was never imported, (b) the import landed somewhere outside ${escapeHtml(row.folder || "this job's PICS")}, or (c) the photos were renamed downstream.
           Use <strong>✓ In OD</strong> on the dialog row if they really are imported elsewhere.
         </div>`
      : "";
  const sampleHtml = sample && sample.length
    ? `<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-top:8px;">
         <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">
           First ${sample.length} flagged-as-new filename${sample.length === 1 ? "" : "s"}
         </div>
         <div style="font-family:monospace;font-size:11px;line-height:1.5;color:var(--text);max-height:240px;overflow:auto;word-break:break-all;">
           ${sample.map((n) => `<div>📄 ${escapeHtml(n)}</div>`).join("")}
         </div>
         ${m.new_count > sample.length
           ? `<div style="font-size:11px;color:var(--text-muted);margin-top:6px;">…and ${m.new_count - sample.length} more</div>`
           : ""}
       </div>`
    : "";
  createOverlay({
    title: "🔍 Why is this +" + (m.new_count || 0) + " new?",
    sub:   escapeHtml(m.name),
    body: `
      ${inOdNote}
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:12px 14px;">
        <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;">
          Diff breakdown (${stats.total || m.img_count || 0} SP files total)
        </div>
        <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:12px;">
          <span style="color:var(--green);">✓ Matched by name</span><span style="font-variant-numeric:tabular-nums;">${stats.name || 0}</span>
          <span style="color:var(--green);">✓ Matched by fingerprint (size + mtime)</span><span style="font-variant-numeric:tabular-nums;">${stats.fp || 0}</span>
          <span style="color:var(--text-muted);">≈ Matched by size only (loose fallback)</span><span style="font-variant-numeric:tabular-nums;">${stats.size || 0}</span>
          <span style="color:var(--amber);font-weight:600;">⚠ Still flagged new</span><span style="font-variant-numeric:tabular-nums;font-weight:600;">${stats.new || m.new_count || 0}</span>
        </div>
      </div>
      ${sampleHtml}
      <div class="modal-footer">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
}

// ── Keyboard nav ─────────────────────────────────────────────────
// Shift-C: copy today's audit summary as Markdown.
async function copyDaySummary() {
  const res = await pywebview.api.day_summary_markdown();
  if (!res?.ok) {
    setStatus(`Day summary failed: ${res?.error || "?"}`, "error");
    return;
  }
  try {
    await navigator.clipboard.writeText(res.markdown);
    setStatus(`📋 Copied: ${res.flagged} flagged · ${res.ok_count} OK · ${res.total} total`, "ok");
  } catch (err) {
    setStatus(`Copy failed: ${err}`, "error");
  }
}

function onKeyDown(ev) {
  // Ctrl/Cmd+K → quick-jump palette. Checked BEFORE the input guard so it
  // fires even while typing in a field.
  if ((ev.ctrlKey || ev.metaKey) && (ev.key === "k" || ev.key === "K")) {
    ev.preventDefault();
    openQuickJump();
    return;
  }
  // One shared guard — typing anywhere, or any dialog open, means these
  // single-key shortcuts are not for us. Falls back to the old test if
  // keyboard.js somehow didn't load.
  if (window.shouldIgnoreKey
        ? window.shouldIgnoreKey(ev)
        : (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA")) return;
  if (ev.key === "/") {
    $("#search-box").focus();
    ev.preventDefault();
    return;
  }
  if (ev.key === "r" || ev.key === "R") {
    runAudit(true);
    return;
  }
  if (ev.key === "C" && ev.shiftKey) {
    copyDaySummary();
    ev.preventDefault();
    return;
  }
  if (ev.key === "Enter") {
    // Open OD for the selected row.
    const r = findRowByKey(state.selected_client);
    if (r) onDetailAction("open-folder", r);
    return;
  }
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp" ||
      ev.key === "j" || ev.key === "k") {
    const filtered = filterRows();
    if (filtered.length === 0) return;
    const ix = filtered.findIndex((r) => rowKey(r) === state.selected_client);
    let next = ix;
    if (ev.key === "ArrowDown" || ev.key === "j") next = ix + 1;
    if (ev.key === "ArrowUp"   || ev.key === "k") next = ix - 1;
    next = Math.max(0, Math.min(filtered.length - 1, next));
    state.selected_client = rowKey(filtered[next]);
    renderList();
    renderDetail();
    scrollSelectedIntoView();
    ev.preventDefault();
  }
}

// ── Status helpers ───────────────────────────────────────────────
let statusTimer = null;
function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
  if (statusTimer) clearTimeout(statusTimer);
  if (msg && kind === "ok") {
    statusTimer = setTimeout(() => {
      el.textContent = "";
      el.className = "status-msg";
    }, 4000);
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function escapeAttr(s) { return escapeHtml(s); }
// Display-only Title Case: uppercase the first letter of every word,
// leaving the rest untouched so acronyms (LLC, IPR) and internal caps
// (McDonald) survive. NEVER mutate the stored/identity value — apply
// this only when rendering a name into the DOM.
function titleCase(s) {
  return String(s == null ? "" : s).replace(
    /(^|[\s\-\/,.'"“”‘’([])([a-zà-ÿ])/g,
    (_m, sep, ch) => sep + ch.toUpperCase());
}
// "Last, First" → "First Last" for personal names (strips a trailing
// " - Carrier" / " (Unit …)"); names without a comma are returned as-is.
// So one-off jobs (resolved from a "Last, First" folder) display the same
// First-Last order as run-doc rows.
function firstLast(name) {
  const raw = String(name == null ? "" : name).trim();
  const ci = raw.indexOf(",");
  if (ci < 0) return raw;
  const last = raw.slice(0, ci).trim();
  const first = raw.slice(ci + 1).trim()
    .replace(/\s+[-–—]\s+.*$/, "").replace(/\s*\(.*$/, "").trim();
  return (first && last) ? `${first} ${last}` : raw;
}
// Live auto-capitalize for a search <input>: title-cases what the user
// types while preserving the caret position.
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

// Browser-native clipboard with a hidden-textarea fallback for
// when navigator.clipboard isn't available (older WebView2 or
// strict permissions). Replaces the Python copy_to_clipboard
// which was destroying its Tk root before the clipboard contents
// became visible to other apps — copied data disappeared
// instantly. This one writes to the real OS clipboard.
async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(String(text));
      return true;
    }
  } catch (_) { /* fall through to textarea fallback */ }
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

// ── Phase 2 actions (re-audit, pin, flag, comment, DS req) ───────
const origRenderDetail = renderDetail;
renderDetail = function () {
  origRenderDetail();
  const r = findRowByKey(state.selected_client);
  if (!r) return;
  const actions = document.querySelector(".detail-actions");
  if (!actions) return;
  // The shared card owns Scope / Re-audit / More. Audit used to append
  // another copy here after every render, creating duplicate controls.
  // Keep this extension point only for mode-specific actions.
  const toolsRow = actions.querySelector(".detail-more .action-buttons")
    || actions.querySelector(".action-row:last-child .action-buttons")
    || actions;
  const add = (label, cls, fn) => {
    const b = document.createElement("button");
    b.className = "action-btn" + (cls ? " " + cls : "");
    b.textContent = label;
    b.addEventListener("click", fn);
    toolsRow.appendChild(b);
    return b;
  };
  // When the audit couldn't resolve a folder, surface the find-
  // folder action prominently instead of burying it in the menu.
  if (!r.found) {
    add("🔎 Find folder", "primary", () => openFindFolderModal(r));
  }
  // Backlog mode: extra "Closed" button to manually drop a job from the backlog
  if (state.mode === "backlog") {
    add("🏁 Closed", "", async () => {
      const res = await pywebview.api.close_backlog_row(r.client);
      if (!res?.ok) { setStatus(`Close failed: ${res?.error || "?"}`, "error"); return; }
      // Remove from local state + re-render
      state.rows = state.rows.filter((x) => x.client !== r.client);
      state.selected_client = null;
      renderAll();
      setStatus(`🏁 ${r.client} closed`, "ok");
    });
  }

  // Render per-item resolved checkboxes
  decorateIssueListsWithCheckboxes(r);
};

async function doReaudit(r) {
  setStatus(`Re-auditing ${r.client}…`);
  const res = await pywebview.api.reaudit_one(r.client);
  if (!res?.ok) {
    setStatus(`Re-audit failed: ${res?.error || "?"}`, "error");
    return;
  }
  applyRow(res.row);
  renderAll();
  setStatus(
    `Re-audited ${r.client} — ${res.row.flagged ? `${res.row.total_missing} missing` : "clean ✓"}`,
    res.row.flagged ? "warn" : "ok");
}

// ── Per-item resolved checkboxes (Phase 2) ───────────────────────
async function decorateIssueListsWithCheckboxes(r) {
  // Skip when there are no issues
  if (!r.form_issues.length && !r.photo_issues.length) return;
  const resolvedMap = await pywebview.api.get_resolved_map(r.client) || {};
  // Walk every audit-issue <li> and prepend a "resolved" checkbox.
  // Skip .cl-item rows — those are Trello checklist items (Initial /
  // In Progress) that already carry their own native checkbox; adding
  // a resolved-box there renders a confusing double checkbox.
  document.querySelectorAll(".issue-list li:not(.cl-item)").forEach((li) => {
    const text = li.textContent.trim();
    if (li.querySelector(".resolved-box")) return; // already decorated
    const isResolved = !!resolvedMap[text];
    const box = document.createElement("span");
    box.className = "resolved-box" + (isResolved ? " checked" : "");
    box.title = "Mark resolved";
    if (isResolved) {
      li.classList.add("is-resolved");
    }
    box.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const next = !box.classList.contains("checked");
      box.classList.toggle("checked", next);
      li.classList.toggle("is-resolved", next);
      const res = await pywebview.api.toggle_resolved(r.client, text, next);
      if (!res?.ok) {
        // Revert on failure
        box.classList.toggle("checked", !next);
        li.classList.toggle("is-resolved", !next);
        setStatus(`Couldn't persist: ${res?.error || "?"}`, "error");
      } else {
        setStatus(
          next ? `✓ Marked resolved: ${text}` : `Re-opened: ${text}`,
          "ok");
      }
    });
    li.insertBefore(box, li.firstChild);
  });
}

// ── Pin Trello card modal (Phase 2) ──────────────────────────────
function openPinModal(r) {
  const overlay = createOverlay({
    title: r.trello_card_id ? "Re-pin Trello card" : "Pin Trello card",
    sub:   `Client: ${r.client}`,
    body: `
      <input id="pin-q" class="search" type="search" autocomplete="off"
             placeholder="🔎 Search Trello cards by name…"
             value="${escapeAttr(r.client)}" />
      <div id="pin-results" class="target-list" style="margin-top:10px;"></div>
      ${r.trello_card_id ? `
        <div style="margin-top:14px; padding-top:12px; border-top:1px solid var(--border);">
          <button class="btn" id="pin-clear">✕ Unpin current card</button>
        </div>` : ""}
    `,
  });
  const q = overlay.querySelector("#pin-q");
  const results = overlay.querySelector("#pin-results");
  let timer = null;
  async function doSearch() {
    const text = q.value.trim();
    if (text.length < 2) { results.innerHTML = ""; return; }
    results.innerHTML = `<div class="target-row" style="opacity:.6;">Searching…</div>`;
    const hits = await pywebview.api.search_trello(text);
    if (!hits.length) {
      results.innerHTML = `<div class="target-row" style="opacity:.6;">No matches</div>`;
      return;
    }
    results.innerHTML = hits.map((h) => `
      <div class="target-row" data-card="${escapeAttr(h.card_id)}">
        <span>📌</span>
        <span class="name">${escapeHtml(h.name)}</span>
        <span class="miss">${escapeHtml(h.lane || h.board || "")}</span>
      </div>
    `).join("");
    results.querySelectorAll(".target-row[data-card]").forEach((row) =>
      row.addEventListener("click", async () => {
        const res = await pywebview.api.pin_trello(r.client, row.dataset.card);
        if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
        r.trello_card_id = res.card_id;
        setStatus(`📌 Pinned ${r.client}`, "ok");
        closeOverlay();
        renderDetail();
        renderList();
      }));
  }
  q.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(doSearch, 220);
  });
  q.focus();
  q.select();
  doSearch();
  const clearBtn = overlay.querySelector("#pin-clear");
  if (clearBtn) clearBtn.addEventListener("click", async () => {
    await pywebview.api.unpin_trello(r.client);
    r.trello_card_id = "";
    setStatus("Unpinned", "ok");
    closeOverlay();
    renderDetail();
  });
}

// ── Comment posting modal (Phase 2) ──────────────────────────────
function openCommentModal(r) {
  if (!r.trello_card_id) {
    setStatus("Pin a Trello card first to comment", "warn");
    openPinModal(r);
    return;
  }
  const allItems = ["(no item — general comment)", ...r.form_issues, ...r.photo_issues];
  const overlay = createOverlay({
    title: "💬 Post Trello comment",
    sub:   `Client: ${r.client}`,
    body: `
      <label class="modal-lbl">Tag to a missing item? (optional)</label>
      <select id="cmt-item" class="search" style="width:100%;">
        ${allItems.map((it, i) =>
          `<option value="${i === 0 ? "" : escapeAttr(it)}">${escapeHtml(it)}</option>`).join("")}
      </select>
      <label class="modal-lbl" style="margin-top:12px;">Comment text</label>
      <textarea id="cmt-text" class="modal-textarea" rows="5"
                placeholder="Type your comment…"></textarea>
      <div class="modal-footer">
        <button class="btn" id="cmt-cancel">Cancel</button>
        <button class="btn btn-primary" id="cmt-go">💬 Post</button>
      </div>`,
  });
  overlay.querySelector("#cmt-cancel").addEventListener("click", closeOverlay);
  overlay.querySelector("#cmt-go").addEventListener("click", async () => {
    const item = overlay.querySelector("#cmt-item").value;
    const text = overlay.querySelector("#cmt-text").value.trim();
    if (!text) { setStatus("Comment can't be empty", "warn"); return; }
    const res = await pywebview.api.post_comment(r.client, text, item);
    if (!res?.ok) { setStatus(`Post failed: ${res?.error || "?"}`, "error"); return; }
    closeOverlay();
    setStatus("💬 Posted to Trello", "ok");
  });
  overlay.querySelector("#cmt-text").focus();
}

// ── DocuSign request modal (Phase 2) ─────────────────────────────
function openDocuSignModal(r) {
  const overlay = createOverlay({
    title: "✍ Send DocuSign via Trello",
    sub:   `Client: ${r.client}`,
    body: `
      <p style="font-size:13px;color:var(--text);">
        Posts a DocuSign request comment on this client's Trello card and
        queues a Hygiene reminder until the paperwork is signed.
      </p>
      <p class="muted" style="margin-top:8px;">
        The actual DocuSign send happens in Trello — this just kicks off
        the workflow and tracks it. To import a signed packet back, use
        the 📥 Import Center.
      </p>
      <div class="modal-footer">
        <button class="btn" id="ds-cancel">Cancel</button>
        <button class="btn btn-primary" id="ds-go">✍ Send request</button>
      </div>`,
  });
  overlay.querySelector("#ds-cancel").addEventListener("click", closeOverlay);
  overlay.querySelector("#ds-go").addEventListener("click", async () => {
    const btn = overlay.querySelector("#ds-go");
    btn.disabled = true; btn.textContent = "Sending…";
    const res = await pywebview.api.request_docusign(r.client);
    if (!res?.ok) {
      setStatus(`DS request failed: ${res?.error || "?"}`, "error");
      btn.disabled = false; btn.textContent = "✍ Send request";
      return;
    }
    closeOverlay();
    const where = res.email ? ` → ${res.email}` : "";
    setStatus(
      `✍ Requested DocuSign for ${r.client}${where}` +
      (res.posted ? "" : " (comment failed — post manually)"),
      "ok");
  });
}

// ── Guarded folder pin ──────────────────────────────────────────
// Every pin goes through here. The backend refuses — with needs_confirm —
// when the folder's name belongs to somebody else, so the one case worth
// interrupting (pinning a job into another client's folder, which then
// silently steers every later import) gets a second look. Everything else
// pins on the first call exactly as before.
// Deliberately NOT window.confirm: pywebview's backends don't reliably
// implement it, and a confirm that returns undefined reads as "cancel" —
// which would silently refuse the pin and look exactly like the folder
// not being accepted. This is an in-app modal, so it also matches every
// other dialog in the panel.
function confirmPin(warning) {
  return new Promise((resolve) => {
    if (!window.openModal) { resolve(true); return; }  // never block on a missing modal
    const overlay = window.openModal({
      title: "📌 Pin this folder?",
      sub: "It doesn't look like this job's folder",
      width: 520,
      id: "pin-confirm-overlay",
      body: `
        <div style="font-size:12.5px;line-height:1.5;">${escapeHtml(warning || "")}</div>
        <div style="font-size:11.5px;color:var(--text-muted);margin-top:10px;">
          Commercial jobs filed under a business name, and address-only folders,
          legitimately don't match — pin anyway if this is right.
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="pin-yes">Pin anyway</button>
        </div>`,
      onClose: () => resolve(false),
    });
    overlay.querySelector("#pin-yes")?.addEventListener("click", () => {
      resolve(true);
      try { window.closeModal("pin-confirm-overlay"); } catch (_) { overlay.remove(); }
    });
  });
}

async function pinFolderGuarded(client, path) {
  let res = await pywebview.api.set_folder_path(client, path);
  if (res?.needs_confirm) {
    if (!(await confirmPin(res.warning))) {
      return { ok: false, cancelled: true };
    }
    res = await pywebview.api.set_folder_path(client, path, true);
  }
  return res;
}

// ── Find / Change folder modal (P0) ─────────────────────────────
async function openFindFolderModal(row) {
  // Pre-fetch the list of year folders so the scope dropdown can
  // surface every option (2026, 2025, fire-job folders, etc.).
  // Doing this BEFORE building the modal body keeps the UI tight.
  let yearFolders = [];
  try {
    const yr = await pywebview.api.list_year_folders();
    yearFolders = yr?.folders || [];
  } catch (_) { yearFolders = []; }
  const currentYear = String(new Date().getFullYear());

  // Build a flat <option> list grouped by current-year / older / fire.
  // The "All years" sentinel scans every folder including fire-jobs.
  const scopeOpts = [
    `<option value="">${currentYear} (current year)</option>`,
    `<option value="all">— All years + fire jobs</option>`,
    `<option value="fire">— Fire jobs only (every year)</option>`,
  ];
  const seen = new Set();
  for (const f of yearFolders) {
    if (f.year === currentYear && !f.is_fire) continue;  // already covered
    if (seen.has(f.name)) continue;
    seen.add(f.name);
    const label = f.is_fire ? `🔥 ${f.name}` : f.name;
    scopeOpts.push(`<option value="${escapeAttr(f.name)}">${escapeHtml(label)}</option>`);
  }

  const overlay = createOverlay({
    title: row.found ? "🔀 Change folder for " + row.client
                     : "🔎 Find folder for " + row.client,
    sub: row.found
      ? `Currently: ${row.folder || "(none)"} — pick a different folder to override.`
      : "Audit couldn't auto-resolve a folder. Pick from the year-folder candidates below.",
    body: `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <label class="muted" style="font-size:11px;white-space:nowrap;">Search in:</label>
        <select id="ff-scope" class="search" style="flex:1;">
          ${scopeOpts.join("")}
        </select>
      </div>
      <input id="ff-search" class="search" type="text"
             placeholder="🔎 Filter candidates…"
             style="width:100%;" />
      <div id="ff-crumb" style="display:none; margin-top:8px; align-items:center; gap:8px; flex-wrap:wrap;"></div>
      <div id="ff-status" class="muted" style="margin-top:8px;">Loading candidates…</div>
      <div id="ff-list" class="target-list" style="margin-top:10px; max-height:340px;"></div>
      <div class="modal-footer">
        ${row.found ? `<button class="btn" id="ff-clear">✕ Clear override</button>` : ""}
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
      </div>`,
  });

  let allCandidates = [];
  let searchTerm = "";
  let currentScope = "";  // matches first <option>
  // Drill-in browse state. Empty stack = candidate (search) mode; a
  // non-empty stack = browsing INTO folders to pin a specific subfolder
  // (campus / unit / claim). Each entry: {name, path}. `browseSubs` are
  // the children of the deepest stack entry.
  let browseStack = [];
  let browseSubs = [];

  // Pin a folder path and close — shared by candidate rows, subfolder
  // rows, and the "✓ Use this folder" button.
  const selectFolder = async (path, label) => {
    const res = await pinFolderGuarded(row.client, path);
    if (res?.cancelled) { setStatus("Pin cancelled", "warn"); return; }
    if (!res?.ok) { setStatus(`Set failed: ${res?.error || "?"}`, "error"); return; }
    closeOverlay();
    const re = await pywebview.api.reaudit_one(row.client);
    if (re?.ok) {
      applyRow(re.row);
      renderAll();
    }
    setStatus(`📁 Folder set: ${label || path}`, "ok");
  };

  // Reset the search box — the term used to find the PARENT candidate
  // ("Avil") almost never matches its child folders ("Unit 526 2-28-26"),
  // so carrying it into browse mode hides every real subfolder. Clear it on
  // any drill / breadcrumb move; the user can retype to filter children.
  const clearSearch = () => {
    searchTerm = "";
    const el = document.getElementById("ff-search");
    if (el) el.value = "";
  };

  // Drill INTO a folder — load its subfolders and switch to browse mode.
  const drillInto = async (folder) => {
    const status = document.getElementById("ff-status");
    status.textContent = `Opening ${folder.name}…`;
    const res = await pywebview.api.list_subfolders(folder.path);
    if (!res?.ok) { setStatus(`Couldn't open: ${res?.error || "?"}`, "error"); return; }
    browseStack.push({ name: folder.name, path: folder.path });
    browseSubs = res.subfolders || [];
    clearSearch();
    renderList();
  };

  // Climb to a given depth in the breadcrumb (0 = back to candidates).
  const goToDepth = async (depth) => {
    clearSearch();
    if (depth <= 0) { browseStack = []; browseSubs = []; renderList(); return; }
    browseStack = browseStack.slice(0, depth);
    const cur = browseStack[browseStack.length - 1];
    const res = await pywebview.api.list_subfolders(cur.path);
    browseSubs = res?.ok ? (res.subfolders || []) : [];
    renderList();
  };

  const renderCrumb = () => {
    const crumb = document.getElementById("ff-crumb");
    if (!browseStack.length) { crumb.style.display = "none"; return; }
    crumb.style.display = "flex";
    const cur = browseStack[browseStack.length - 1];
    const segs = [`<a href="#" data-depth="0" style="color:var(--link,#4A9EFF);text-decoration:none;">Candidates</a>`];
    browseStack.forEach((s, i) => {
      segs.push(`<span style="color:var(--text-muted);">›</span>`);
      segs.push(`<a href="#" data-depth="${i + 1}" style="color:${i === browseStack.length - 1 ? "var(--text)" : "var(--link,#4A9EFF)"};text-decoration:none;font-weight:${i === browseStack.length - 1 ? 700 : 400};">${escapeHtml(s.name)}</a>`);
    });
    crumb.innerHTML =
      `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:12px;">${segs.join("")}</div>` +
      `<span style="flex:1;"></span>` +
      `<button class="btn btn-primary" id="ff-use" title="Pin this exact folder">✓ Use “${escapeHtml(cur.name)}”</button>`;
    crumb.querySelectorAll("a[data-depth]").forEach((a) =>
      a.addEventListener("click", (e) => {
        e.preventDefault();
        goToDepth(parseInt(a.dataset.depth, 10));
      }));
    crumb.querySelector("#ff-use").addEventListener("click", () =>
      selectFolder(cur.path, cur.name));
  };

  // Render one folder row with a name (click = pin it) and a "›" drill
  // button (click = open it to see subfolders). Used in both modes.
  const folderRow = (item, subLabel) => `
      <div class="target-row" data-path="${escapeAttr(item.path)}">
        <span>${item.is_fire ? "🔥" : "📁"}</span>
        <div class="ff-pick" style="flex:1;min-width:0;cursor:pointer;" title="Pin this folder">
          <div class="name">${escapeHtml(item.name)}</div>
          ${subLabel || ""}
        </div>
        <button class="btn ff-open" data-path="${escapeAttr(item.path)}"
                title="Open — pick a subfolder inside"
                style="padding:2px 10px;font-size:13px;">›</button>
      </div>`;

  const renderList = () => {
    renderCrumb();
    const list = document.getElementById("ff-list");
    const status = document.getElementById("ff-status");
    const browsing = browseStack.length > 0;
    const q = searchTerm.toLowerCase();

    let items;
    if (browsing) {
      items = q
        ? browseSubs.filter((c) => c.name.toLowerCase().includes(q))
        : browseSubs;
      const cur = browseStack[browseStack.length - 1];
      status.textContent = items.length
        ? `${items.length} subfolder${items.length !== 1 ? "s" : ""} in ${cur.name}`
        : `No subfolders in ${cur.name} — use “✓ Use” above to pin it.`;
    } else {
      items = q
        ? allCandidates.filter((c) => c.name.toLowerCase().includes(q))
        : allCandidates;
    }

    if (!items.length) {
      list.innerHTML = `<div style="padding:14px;text-align:center;color:var(--text-muted);">${browsing ? "No subfolders." : "No matches."}</div>`;
    } else {
      list.innerHTML = items.slice(0, 300).map((c) => {
        const subLabel = (!browsing &&
          (currentScope === "all" || currentScope === "fire" ||
           (c.year_folder && c.year_folder !== currentScope)))
          ? `<div style="font-size:10px;color:var(--text-muted);">${c.is_fire ? "🔥 " : ""}${escapeHtml(c.year_folder || c.year || "")}</div>`
          : "";
        return folderRow(c, subLabel);
      }).join("");
    }

    // Name area → pin that folder. "›" button → drill into it.
    list.querySelectorAll(".target-row").forEach((rowEl) => {
      const path = rowEl.dataset.path;
      const name = rowEl.querySelector(".name")?.textContent || path;
      rowEl.querySelector(".ff-pick")?.addEventListener("click", () =>
        selectFolder(path, name));
      rowEl.querySelector(".ff-open")?.addEventListener("click", (e) => {
        e.stopPropagation();
        drillInto({ name, path });
      });
    });
  };

  async function loadCandidates(scope) {
    currentScope = scope;
    browseStack = [];   // changing scope exits any drill-in browse
    browseSubs = [];
    document.getElementById("ff-status").textContent = "Loading candidates…";
    const res = await pywebview.api.list_folder_candidates(row.client, scope);
    if (!res?.ok) {
      document.getElementById("ff-status").textContent =
        "Error: " + (res?.error || "?");
      document.getElementById("ff-status").style.color = "var(--red)";
      allCandidates = [];
      document.getElementById("ff-list").innerHTML = "";
      return;
    }
    allCandidates = res.candidates || [];
    document.getElementById("ff-status").style.color = "";
    const folderNames = (res.year_folders || []).join(", ");
    document.getElementById("ff-status").textContent =
      `${allCandidates.length} folder${allCandidates.length !== 1 ? "s" : ""} in ${folderNames || (res.year + "/")}`;
    renderList();
  }

  // Initial load uses default (current year)
  await loadCandidates("");
  document.getElementById("ff-scope").addEventListener("change", (e) => {
    loadCandidates(e.target.value);
  });
  document.getElementById("ff-search").addEventListener("input", (e) => {
    searchTerm = e.target.value.trim();
    renderList();
  });
  bindTitleCaseInput(document.getElementById("ff-search"));
  document.getElementById("ff-search").focus();
  const clearBtn = document.getElementById("ff-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      await pywebview.api.clear_folder_path(row.client);
      closeOverlay();
      const re = await pywebview.api.reaudit_one(row.client);
      if (re?.ok) {
        applyRow(re.row);
        renderAll();
      }
      setStatus("📁 Override cleared — re-audited", "ok");
    });
  }
}

// ── Shared modal helpers ─────────────────────────────────────────
// Thin wrappers around the shared web_shared/modal.js helper so the
// existing audit call sites (createOverlay({...}) / closeOverlay())
// keep working without per-site edits.
function createOverlay(opts) { return window.openModal(opts); }
function closeOverlay() { window.closeModal("modal-overlay"); }

// Tech picker for CompanyCam imports — the export carries no
// photographer, so ask who shot the batch. Defaults to the job's
// run-doc tech; lists the roster + a free-text option. Resolves the
// chosen tech name, "" to proceed with no tech, or null if cancelled.
// The import tech-picker lives in web_shared/stage_picker.js as
// window.pickImportTech — one implementation shared by the Daily Run,
// IUQ, and Snapshot import surfaces so they never drift.

// After an import that landed photos with NO date metadata (screenshots,
// pasted PNGs, undated downloads), ask when they were taken and stamp
// that EXIF capture date on the whole batch — so CompanyCam + date
// sorting see them on the right day. No-op when every photo already had
// a date. Resolves once the user stamps or skips.
async function maybeStampImportDates(res) {
  const n = (res && res.undated_photos) || 0;
  const dir = (res && res.undated_dir) || "";
  if (!n || !dir) return;
  const today = new Date().toISOString().slice(0, 10);
  const overlay = createOverlay({
    title: "📅 When were these taken?",
    sub: `${n} imported photo${n === 1 ? "" : "s"} have no date. Set the day `
       + `they were taken so CompanyCam and date-sorting show them right.`,
    body: `
      <input id="stamp-date" class="search" type="date"
             value="${today}" max="${today}"
             style="width:100%;font-size:15px;padding:8px;" />
      <div class="muted" style="margin-top:8px;">
        Stamps EXIF “Date taken” on all ${n}. PNG/HEIC are converted to
        JPEG; originals go to the Recycle Bin.
      </div>
      <div class="modal-footer">
        <button class="btn modal-close" id="stamp-skip">Skip</button>
        <span style="flex:1;"></span>
        <button class="btn btn-primary" id="stamp-go">📅 Stamp date</button>
      </div>`,
  });
  return new Promise((resolve) => {
    const finish = () => { closeOverlay(); resolve(); };
    overlay.querySelector("#stamp-skip").addEventListener("click", finish);
    overlay.querySelector("#stamp-go").addEventListener("click", async () => {
      const d = overlay.querySelector("#stamp-date").value;
      if (!d) { setStatus("Pick a date or Skip", "warn"); return; }
      const go = overlay.querySelector("#stamp-go");
      go.disabled = true; go.textContent = "Stamping…";
      const r = await pywebview.api.stamp_photo_dates(dir, d);
      if (r?.ok) {
        setStatus(`📅 Dated ${r.stamped} photo${r.stamped === 1 ? "" : "s"} → ${r.date}`, "ok");
      } else {
        setStatus(`Stamp failed: ${r?.error || "?"}`, "error");
      }
      finish();
    });
  });
}

// ── Per-job Import modal (replaces the old Import Center) ────────
// Opens scoped to ONE job — no target picker, target is the row
// passed in. User clicked 📥 Import on a specific job, so we
// already know who they want to import into.
async function openJobImportModal(row) {
  const overlay = createOverlay({
    title: "📥 Import for " + row.client,
    sub:   "Review sources and destinations. Nothing imports until you press Extract or choose a file.",
    width: 860,
    body: `
      <section class="import-hub-section">
        <div class="import-hub-title">Sources</div>
        <div class="import-source-grid">
          <button class="import-source active" id="job-source-downloads" data-track="import_source_downloads"><span>⬇</span><b>Downloads</b><small>Scan local exports</small></button>
          <button class="import-source" id="job-import-pick" data-track="import_source_manual"><span>📁</span><b>Choose files</b><small>Pick a local file</small></button>
          <button class="import-source" id="job-source-sp" data-track="import_source_sharepoint"><span>☁</span><b>SharePoint</b><small>Review cloud candidates</small></button>
          <button class="import-source" id="job-source-cc" data-track="import_source_companycam" ${row.trello_card_id ? "" : "disabled"}><span>📷</span><b>CompanyCam</b><small>Open job project</small></button>
          <button class="import-source" id="job-source-trello" data-track="import_source_trello" ${row.trello_card_id ? "" : "disabled"}><span>📎</span><b>Trello</b><small>Review attachments</small></button>
        </div>
      </section>
      <section class="import-hub-section">
      <div class="import-hub-title">Downloads ready to review</div>
      <div class="muted" id="job-import-path">Scanning Downloads…</div>
      <div class="candidates" id="job-import-candidates"
           style="margin-top:14px;"></div>
      <div class="empty-inline hidden" id="job-import-empty">
        <p>Nothing importable in Downloads right now.</p>
        <p class="muted">Open the source, download the zip, then ↻ re-scan.</p>
        <div class="source-links">
          <button class="btn" id="job-open-wc">↗ Open Workcenter</button>
          <button class="btn" id="job-open-ds">↗ Open DocuSign</button>
          <button class="btn" id="job-ds-via-trello">✍ Send DocuSign via Trello</button>
        </div>
      </div>
      </section>
      <section class="import-hub-section import-results" aria-live="polite">
        <div class="import-hub-title">This import session</div>
        <div class="muted" id="job-import-result-empty">No files imported yet.</div>
        <div id="job-import-result-list"></div>
      </section>
      <div class="modal-footer" style="align-items:center;">
        <label id="job-import-side" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;user-select:none;"
               title="Route this import into the CONTENTS side (CONTENTS/PICS, CONTENTS/DOCS) instead of EMS — a separate tree outside EMS">
          <input type="checkbox" id="job-import-contents" style="cursor:pointer;" /> 📦 Contents side
        </label>
        <button class="btn" id="job-import-rescan">↻ Re-scan</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  const sessionResults = [];
  function addImportResult(ok, source, details) {
    sessionResults.push({ ok, source, details });
    overlay.querySelector("#job-import-result-empty")?.classList.add("hidden");
    const list = overlay.querySelector("#job-import-result-list");
    if (!list) return;
    list.innerHTML = sessionResults.map(r => `
      <div class="import-result ${r.ok ? "ok" : "failed"}">
        <span aria-hidden="true">${r.ok ? "✓" : "!"}</span>
        <div><b>${escapeHtml(r.source)}</b><small>${escapeHtml(r.details)}</small></div>
      </div>`).join("");
  }

  async function scan() {
    const data = await pywebview.api.scan_downloads(row.client);
    const cands = data.candidates || [];
    const fixed = data.repaired || [];
    let scannedMsg = "Scanned: " + (data.downloads || "—");
    if (fixed.length) {
      // CompanyCam etc. drop files with no extension; scan_downloads
      // auto-added the right one so they open + import normally.
      scannedMsg += `  ·  🔧 fixed ${fixed.length} file name${
        fixed.length !== 1 ? "s" : ""} (` +
        fixed.map((r) => r.new).join(", ") + ")";
    }
    overlay.querySelector("#job-import-path").textContent = scannedMsg;
    const empty = overlay.querySelector("#job-import-empty");
    const wrap = overlay.querySelector("#job-import-candidates");
    if (!cands.length) {
      wrap.innerHTML = "";
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");
    wrap.innerHTML = cands.map((c, i) => {
      const extras = c.paths.length > 1
        ? `Multi-part: ${c.paths.length} files`
        : "";
      return `
        <div class="candidate" data-i="${i}">
          <span class="candidate-icon">${escapeHtml(c.icon)}</span>
          <div class="candidate-meta">
            <div class="candidate-kind">${escapeHtml(c.kind_label)}</div>
            <div class="candidate-label">${escapeHtml(c.label)}</div>
            ${extras ? `<div class="candidate-extras">${escapeHtml(extras)}</div>` : ""}
          </div>
          <button class="candidate-btn" data-i="${i}">Extract</button>
        </div>`;
    }).join("");
    wrap.querySelectorAll(".candidate-btn").forEach((b) =>
      b.addEventListener("click", async () => {
        const cand = cands[+b.dataset.i];
        const card = b.closest(".candidate");
        // Photo imports → ask which PICS stage folder first.
        let dest = "";
        let tech = "";
        // Auto-split: when a download spans multiple stages/days, review +
        // route each group to its own PICS folder with one tech per
        // day+stage (instead of the single stage/tech pickers below).
        if (cand.kind === "companycam" || cand.kind === "wc_attachments") {
          let detection = null;
          try { detection = await pywebview.api.detect_import_groups(cand.paths); }
          catch (_) { detection = null; }
          if (detection && detection.ok && detection.multi) {
            const assignments = await window.pickImportGroups({
              client: row.client, techs: row.techs, detection });
            if (!assignments) return;                // cancelled
            b.disabled = true; b.textContent = "Extracting…"; state.importBtn = b;
            const gside = overlay.querySelector("#job-import-contents")?.checked
              ? "contents" : "ems";
            try {
              const res = await pywebview.api.do_import_grouped(
                row.client, cand.kind, cand.paths, assignments, gside);
              if (!res?.ok) {
                b.textContent = "Failed"; card.classList.add("failed");
                addImportResult(false, cand.kind_label,
                                res?.error || "Import failed");
                setStatus(`Import failed: ${res?.error || "?"}`, "error");
                return;
              }
              b.textContent = "✓ Done"; card.classList.add("done");
              const parts = Object.entries(res.routed || {})
                .map(([f, n]) => `${n} → PICS/${f}`);
              if (res.failed && res.failed.length)
                parts.push(`⚠ ${res.failed.length} failed`);
              addImportResult(!(res.failed || []).length, cand.kind_label,
                              parts.join(" · ") || "Imported");
              setStatus(`✓ ${row.client}: ${parts.join(" · ")}`, "ok");
              const reRes = await pywebview.api.reaudit_one(row.client);
              if (reRes?.ok) {
                applyRow(reRes.row);
                renderAll();
              }
            } catch (ex) {
              b.textContent = "Failed"; card.classList.add("failed");
              addImportResult(false, cand.kind_label, String(ex));
              setStatus(`Import error: ${ex}`, "error");
            } finally {
              if (state.importBtn === b) state.importBtn = null;
            }
            return;                                  // grouped import handled
          }
        }
        if (cand.kind === "companycam" || cand.kind === "wc_attachments") {
          const choice = await window.pickPicsStage({ client: row.client, allowAuto: true });
          if (choice === null) return;               // cancelled
          dest = choice === "AUTO" ? "" : choice;
        }
        // Every photo import must be filed under a tech — CompanyCam and
        // WC attachments are both field photos. Ask (pre-filled from the
        // run-doc); a cancel or empty pick aborts the import.
        if (cand.kind === "companycam" || cand.kind === "wc_attachments") {
          tech = await window.pickImportTech({ client: row.client, techs: row.techs });
          if (!tech) return;                          // cancelled / no tech
        }
        b.disabled = true; b.textContent = "Extracting…";
        state.importBtn = b;
        // 📦 Contents side → route into CONTENTS/ instead of EMS/.
        const side = overlay.querySelector("#job-import-contents")?.checked
          ? "contents" : "ems";
        try {
          const res = await pywebview.api.do_import(
            row.client, cand.kind, cand.paths, dest, tech, side);
          if (!res?.ok) {
            b.textContent = "Failed";
            card.classList.add("failed");
            addImportResult(false, cand.kind_label,
                            res?.error || "Import failed");
            setStatus(`Import failed: ${res?.error || "?"}`, "error");
            return;
          }
          b.textContent = "✓ Done";
          card.classList.add("done");
          const bits = [];
          if (res.pics_count) bits.push(`${res.pics_count} → PICS/${res.subfolder || "Initial"}`);
          if (res.docs_count) bits.push(`${res.docs_count} → DOCS`);
          if (res.sketches_count) bits.push(`${res.sketches_count} → DOCS/Docusketch`);
          addImportResult(true, cand.kind_label,
                          bits.join(" · ") || "Imported");
          setStatus(`✓ ${row.client}: ${bits.join(" · ")}`, "ok");
          // Offer to date any photos that landed with no metadata.
          await maybeStampImportDates(res);
          // Re-audit so the detail pane reflects the new files
          const reRes = await pywebview.api.reaudit_one(row.client);
          if (reRes?.ok) {
            applyRow(reRes.row);
            renderAll();
          }
        } catch (ex) {
          b.textContent = "Failed";
          card.classList.add("failed");
          addImportResult(false, cand.kind_label, String(ex));
          setStatus(`Import error: ${ex}`, "error");
        } finally {
          if (state.importBtn === b) state.importBtn = null;
        }
      }));
  }

  overlay.querySelector("#job-import-rescan").addEventListener("click", scan);
  overlay.querySelector("#job-source-downloads").addEventListener("click", scan);
  overlay.querySelector("#job-source-sp").addEventListener("click", () =>
    openSpImportModal(row));
  overlay.querySelector("#job-source-cc").addEventListener("click", async () => {
    const ok = await pywebview.api.open_companycam_link(row.client);
    if (!ok) setStatus("No CompanyCam link is saved for this job", "warn");
  });
  overlay.querySelector("#job-source-trello").addEventListener("click", () =>
    window.openTrelloAttachmentsModal({
      cardId: row.trello_card_id, client: row.client }));
  // Manual file picker — always available, regardless of what the
  // auto-scanner found. Lets the user import any loose file or
  // renamed export the scanner missed.
  overlay.querySelector("#job-import-pick").addEventListener("click",
    async () => {
      const btn = overlay.querySelector("#job-import-pick");
      const buttonHtml = btn.innerHTML;
      const choice = await window.pickPicsStage({ client: row.client, allowAuto: true, allowDocs: true });
      if (choice === null) return;                   // cancelled
      const dest = choice === "AUTO" ? "" : choice;
      // A PICS stage (or AUTO) means photos → require a tech, same as the
      // other photo-import paths. A DOCS destination is paperwork → skip.
      let tech = "";
      if (!/^DOCS/i.test(String(choice))) {
        tech = await window.pickImportTech({ client: row.client, techs: row.techs });
        if (!tech) return;                           // cancelled / no tech
      }
      btn.disabled = true; btn.textContent = "Picking…";
      state.importBtn = btn;
      const side = overlay.querySelector("#job-import-contents")?.checked
        ? "contents" : "ems";
      try {
        const res = await pywebview.api.pick_and_import_file(row.client, dest, side, tech);
        if (res?.cancelled) {
          // User closed the picker — no-op, just restore the button.
        } else if (!res?.ok) {
          addImportResult(false, "Chosen file",
                          res?.error || "Import failed");
          setStatus(`Import failed: ${res?.error || "?"}`, "error");
        } else {
          const bits = [];
          if (res.pics_count) bits.push(`${res.pics_count} → PICS/${res.subfolder || "Initial"}`);
          if (res.docs_count) bits.push(`${res.docs_count} → DOCS`);
          if (res.sketches_count) bits.push(`${res.sketches_count} → DOCS/Docusketch`);
          addImportResult(true, "Chosen file",
                          bits.join(" · ") || "Imported");
          setStatus(`✓ ${row.client}: ${bits.join(" · ") || "imported"}`, "ok");
          // Offer to date any photos that landed with no metadata.
          await maybeStampImportDates(res);
          // Re-audit so the detail pane reflects the new files.
          const reRes = await pywebview.api.reaudit_one(row.client);
          if (reRes?.ok) {
            applyRow(reRes.row);
            renderAll();
          }
          await scan();  // refresh candidate list (sources got trashed)
        }
      } catch (ex) {
        addImportResult(false, "Chosen file", String(ex));
        setStatus(`Import error: ${ex}`, "error");
      } finally {
        if (state.importBtn === btn) state.importBtn = null;
        btn.disabled = false; btn.innerHTML = buttonHtml;
      }
    });
  overlay.querySelector("#job-open-wc").addEventListener("click", () =>
    pywebview.api.open_workcenter());
  overlay.querySelector("#job-open-ds").addEventListener("click", () =>
    pywebview.api.open_url("https://app.docusign.com/"));
  overlay.querySelector("#job-ds-via-trello").addEventListener("click",
    async () => {
      closeOverlay();
      openDocuSignModal(row);
    });
  await scan();
}

// ── Match diagnostic modal (Tk parity) ──────────────────────────
// ── Search aliases modal (mirrors Tk job_widgets:open_search_aliases_dialog) ──
// One alias per line. Aliases feed every name-based lookup (SP
// folder scan, OD folder match, Trello fuzzy match) so registering
// them once means every panel finds the job by the alias too.
async function openSearchAliasesModal(row) {
  const current = await pywebview.api.get_search_aliases(row.client) || [];
  const overlay = createOverlay({
    title: "🏷 Search aliases for " + row.client,
    sub:   "One alias per line. Each alias is matched anywhere the canonical name would be — folder scan, Trello search, SP match.",
    body: `
      <textarea id="al-text" rows="8" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;">${escapeHtml(current.join("\n"))}</textarea>
      <div class="modal-footer">
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="al-save">💾 Save aliases</button>
      </div>`,
  });
  document.getElementById("al-save").addEventListener("click", async () => {
    const lines = document.getElementById("al-text").value
      .split("\n").map((s) => s.trim()).filter(Boolean);
    const res = await pywebview.api.set_search_aliases(row.client, lines);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    closeOverlay();
    setStatus(`🏷 Saved ${lines.length} alias${lines.length !== 1 ? "es" : ""} for ${row.client}`, "ok");
  });
  document.getElementById("al-text").focus();
}

// ── Add/Remove from property modal (multi-unit umbrella) ────────
// Mirrors Tk job_widgets cascade menu — when the job's folder is
// already in a property group, offer "Remove from 'X'"; otherwise
// show the existing groups + "+ New property…" option.
async function openAddToPropertyModal(row) {
  // Resolve the folder basename from the row's path. Without a
  // pinned folder there's nothing to anchor a property group to.
  const folder = (row.folder || "").trim();
  if (!folder) {
    setStatus(`Pin a folder for ${row.client} first — property groups attach to folders`, "warn");
    return;
  }
  const [groupsR, currentGroup] = await Promise.all([
    pywebview.api.list_property_groups(),
    pywebview.api.find_property_for_folder(folder),
  ]);
  const existing = (groupsR?.groups || []);
  const overlay = createOverlay({
    title: currentGroup
      ? `🏢 Property group for ${row.client}`
      : `🏢 Add ${row.client} to a property`,
    sub: currentGroup
      ? `Currently in: ${currentGroup}`
      : "Park this job under a multi-unit umbrella so future audits see it as part of the property.",
    body: `
      ${currentGroup ? `
        <button class="btn" id="pg-remove" style="background:var(--red);color:#FFF;border-color:var(--red);">
          ✕ Remove from "${escapeHtml(currentGroup)}"
        </button>
        <hr style="border:none;border-top:1px solid var(--border);margin:14px 0;" />
      ` : ""}
      ${existing.length ? `
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:6px;">Existing properties</div>
        <div id="pg-list" style="display:flex;flex-direction:column;gap:4px;max-height:200px;overflow-y:auto;margin-bottom:14px;">
          ${existing.map((g) => `
            <button class="btn pg-pick" data-name="${escapeAttr(g.name)}" style="text-align:left;justify-content:flex-start;">
              ${escapeHtml(g.name)} <span class="muted" style="font-size:10px;">(${g.folders.length})</span>
            </button>`).join("")}
        </div>` : ""}
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:6px;">+ New property</div>
      <div style="display:flex;gap:6px;">
        <input id="pg-new" class="search" type="text" placeholder="Property name (e.g. Avila Apartments)" style="flex:1;" />
        <button class="btn btn-primary" id="pg-create">Create + add</button>
      </div>
      <div class="modal-footer">
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  // Wire Remove
  document.getElementById("pg-remove")?.addEventListener("click", async () => {
    const r = await pywebview.api.remove_folder_from_property_group(currentGroup, folder);
    if (!r?.ok) { setStatus(`Remove failed: ${r?.error || "?"}`, "error"); return; }
    closeOverlay();
    setStatus(`Removed from "${currentGroup}"`, "ok");
  });
  // Wire Pick existing
  document.querySelectorAll(".pg-pick").forEach((b) =>
    b.addEventListener("click", async () => {
      const name = b.dataset.name;
      const r = await pywebview.api.add_folder_to_property_group(name, folder);
      if (!r?.ok) { setStatus(`Add failed: ${r?.error || "?"}`, "error"); return; }
      closeOverlay();
      setStatus(`🏢 Added to "${name}"`, "ok");
    }));
  // Wire Create + add
  document.getElementById("pg-create")?.addEventListener("click", async () => {
    const name = document.getElementById("pg-new").value.trim();
    if (!name) return;
    const r = await pywebview.api.create_property_group(name, folder);
    if (!r?.ok) { setStatus(`Create failed: ${r?.error || "?"}`, "error"); return; }
    closeOverlay();
    setStatus(`🏢 Created "${name}" + added ${row.client}`, "ok");
  });
  document.getElementById("pg-new")?.focus();
}

// ── 🏠 Day-units modal (mirrors Tk run_audit_gui.py:2780) ───────
// Multi-unit jobs (umbrella folder w/ unit subfolders) get pinned to
// specific units for TODAY only. Each pinned unit becomes its own
// audit row on the next refresh. Tomorrow re-derives from scratch
// unless the user re-pins; right-click "Change folder…" is the
// permanent equivalent.
// ── 📂 Stage PICS into a temp folder for XA / Xactimate upload ──
// XA / Xactimate doesn't accept clipboard pastes — it only takes
// drag-from-Explorer. So we (hard)link every matched image into a
// fresh TEMP folder, open it in Explorer, and the user drags into
// XA. The temp folder auto-deletes after 5 min so it doesn't leak.
async function openCopyPicsToXaModal(row) {
  const info = await pywebview.api.list_pics_stages(row.client);
  if (!info?.ok) {
    setStatus(`Stage list failed: ${info?.error || "no folder pinned"}`, "warn");
    return;
  }
  const stages = info.stages || [];
  if (!stages.length) {
    setStatus(`No PICS subfolders with images for ${row.client}`, "warn");
    return;
  }
  const overlay = createOverlay({
    title: "📂 Stage PICS for XA — " + row.client,
    sub: "Pick a PICS subfolder. Every image is hardlinked into a TEMP folder + Explorer opens on it. Drag the files into XactAnalysis from there. Folder auto-deletes after 1 min.",
    body: `
      <div style="display:flex;flex-direction:column;gap:6px;max-height:50vh;overflow-y:auto;">
        ${stages.map((s) => `
          <button class="action-btn xa-stage" data-stage="${escapeAttr(s.name)}"
                  style="text-align:left;justify-content:flex-start;display:flex;align-items:center;gap:8px;">
            <span style="flex:1;">📁 ${escapeHtml(s.name)}</span>
            <span class="muted" style="font-size:11px;">${s.count} image${s.count !== 1 ? "s" : ""}</span>
          </button>`).join("")}
      </div>
      <div class="modal-footer">
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
      </div>`,
  });
  document.querySelectorAll(".xa-stage").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const stage = btn.dataset.stage;
      btn.disabled = true; btn.textContent = "Copying…";
      const res = await pywebview.api.copy_pics_to_clipboard(row.client, stage);
      if (!res?.ok) {
        setStatus(`Copy failed: ${res?.error || "?"}`, "error");
        btn.disabled = false;
        return;
      }
      closeOverlay();
      const matched = res.matched_stage || stage;
      // Temp folder is already opened in Explorer by the backend.
      // Tell the user what's happening + when it disappears so they
      // know they have a 5 min window to drag-into-XA.
      setStatus(`📂 Staged ${res.count} image${res.count !== 1 ? "s" : ""} from ${matched} → ${res.folder} · drag into XA · auto-deletes at ${res.deletes_at}`, "ok");
    }));
}

// ── Property structure & settings (multi-unit commercial) ──────
// Shows the full OD tree for a multi-unit property like "Avila
// Apartments" — every Unit XXXX subfolder with its photo count,
// last-modified date, and pin-today control. Run-doc lines like
//   "Avila Apartments: 28155 Encanto Dr Unit 1413 Menifee 92585/…"
// resolve property="Avila Apartments" + unit="1413"; this dialog
// lets the admin see every sibling unit at a glance + edit the
// property's commercial flag + alias list inline.
// ── 📨 Paperwork-request via Teams ──────────────────────────────
// Mirrors the user's canonical wording:
//   "Mike Escobar Please collect paperwork for Nicolas Laszkiewicz,
//    thank you"
// Tech is auto-picked from row.techs (first one when multiple).
// Modal exposes a tech dropdown + editable message + email lookup
// so first-time techs can have their Teams email saved inline.
async function openPaperworkRequestModal(row) {
  const techs = Array.isArray(row.techs) ? row.techs.filter(Boolean) : [];
  if (!techs.length) {
    setStatus(`No tech listed for ${row.client} — can't send paperwork request`, "warn");
    return;
  }
  const defaultTech = techs[0];
  const defaultMsg = (t) =>
    `${t} Please collect paperwork for ${row.client}, thank you`;

  const overlay = createOverlay({
    title: "📨 Request paperwork — " + row.client,
    sub:   "Opens the Paperwork-collection group chat with the message pre-filled. User just hits Send.",
    body: `
      <div id="pr-chat-row" style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:11px;color:var(--text-muted);margin-bottom:10px;">
        Loading chat URL…
      </div>
      <label class="modal-lbl">Tech</label>
      <select id="pr-tech" class="search" style="width:100%;">
        ${techs.map((t) => `<option value="${escapeAttr(t)}" ${t === defaultTech ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <label class="modal-lbl" style="margin-top:12px;">Message</label>
      <textarea id="pr-msg" class="modal-textarea" rows="3"
                style="width:100%;font:inherit;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;">${escapeHtml(defaultMsg(defaultTech))}</textarea>
      <div class="modal-footer" style="margin-top:14px;display:flex;gap:8px;">
        <button class="btn" id="pr-edit-chat">🔗 Edit chat URL…</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="pr-send">📨 Open Teams</button>
      </div>`,
  });

  const refreshChatRow = async () => {
    const r = await pywebview.api.get_paperwork_chat_url();
    const el = overlay.querySelector("#pr-chat-row");
    const tag = r?.is_default
      ? '<span style="color:var(--green);">✓ default</span>'
      : '<span style="color:var(--amber);">⚙ custom</span>';
    const shortUrl = (r?.url || "").length > 70
      ? r.url.slice(0, 67) + "…"
      : r?.url || "";
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;">
        ${tag}
        <span style="flex:1;font-family:monospace;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeAttr(r?.url || '')}">${escapeHtml(shortUrl)}</span>
      </div>`;
  };
  refreshChatRow();

  // When tech changes, rebuild default message (only if user hasn't
  // already customized it).
  overlay.querySelector("#pr-tech").addEventListener("change", (ev) => {
    const t = ev.target.value;
    const msgEl = overlay.querySelector("#pr-msg");
    for (const prevTech of techs) {
      if (msgEl.value === defaultMsg(prevTech)) {
        msgEl.value = defaultMsg(t);
        break;
      }
    }
  });

  overlay.querySelector("#pr-edit-chat").addEventListener("click", async () => {
    const cur = await pywebview.api.get_paperwork_chat_url();
    const next = prompt(
      `Teams chat URL for paperwork requests:\n(paste the full https://teams.microsoft.com/l/chat/... link — or empty to reset to default)`,
      cur?.url || "");
    if (next === null) return;
    const r = await pywebview.api.set_paperwork_chat_url(next.trim());
    if (!r?.ok) { setStatus(`Save failed: ${r?.error || "?"}`, "error"); return; }
    setStatus(next.trim() ? `🔗 Saved paperwork chat URL` : `Reset to default chat URL`, "ok");
    refreshChatRow();
  });

  overlay.querySelector("#pr-send").addEventListener("click", async () => {
    const tech = overlay.querySelector("#pr-tech").value;
    const msg  = overlay.querySelector("#pr-msg").value.trim();
    if (!msg) { setStatus("Message can't be empty", "warn"); return; }
    const res = await pywebview.api.send_paperwork_request(row.client, tech, msg);
    if (!res?.ok) {
      setStatus(`Send failed: ${res?.error || "?"}`, "error");
      return;
    }
    closeOverlay();
    setStatus(`📨 Teams opened (${res.chat || "group"} chat) — ${tech} for ${row.client}`, "ok");
  });
}

// ── New Loss modal — paste a carrier assignment email, make the card ──
const NL_FIELD_GROUPS = [
  { group: "Customer", items: [
    ["insured_name", "Customer Name"],
    ["address", "Address"],
    ["phone", "Phone"],
    ["email", "Email"],
    ["additional_contacts", "Additional Contacts"],
  ]},
  { group: "Insurance", items: [
    ["carrier", "Insurance Company"],
    ["claim_number", "Claim Number"],
    ["adjuster_name", "Adjuster / Claim Rep"],
    ["adjuster_email", "Adjuster Email"],
    ["adjuster_number", "Adjuster Phone"],
    ["deductible", "Deductible"],
    ["agent_name", "Agent Name"],
  ]},
  { group: "Property / claim", items: [
    ["year_built", "Year Built"],
    ["date_of_loss", "Date of Loss"],
    ["date_received", "Date Received"],
    ["xa_id", "XA ID"],
  ]},
  { group: "Notes", items: [
    ["field_notes", "Field Notes (loss details)"],
    ["office_notes", "Office Notes"],
  ]},
];
const NL_TEXTAREA_KEYS = new Set(["field_notes", "office_notes", "address"]);

// 📷 Bulk CompanyCam sync — dry-run to count, confirm, then pull.
async function runCompanyCamSync() {
  const menu = document.getElementById("more-menu");
  if (menu) menu.style.display = "none";
  setStatus("📷 Checking CompanyCam for new photos…", "");
  let dry;
  try { dry = await pywebview.api.companycam_sync(true); }
  catch (e) { setStatus("CompanyCam sync failed: " + e, "error"); return; }
  if (!dry || !dry.ok) { setStatus("CompanyCam: " + ((dry && dry.error) || "?"), "error"); return; }
  const matched = (dry.results || []).filter((r) => r.matched);
  const n = dry.total || 0;
  if (!n) { setStatus(dry.note || "📷 CompanyCam: no new photos across active jobs", "ok"); return; }
  if (!confirm(`Pull ${n} new CompanyCam photo${n === 1 ? "" : "s"} into ${matched.length} active job${matched.length === 1 ? "" : "s"}?\n\nDownloads into each job's PICS folder — may take a few minutes.`)) {
    setStatus("", ""); return;
  }
  setStatus(`📷 Syncing ${n} photos… this can take a few minutes, please wait`, "");
  let res;
  try { res = await pywebview.api.companycam_sync(false); }
  catch (e) { setStatus("Sync failed: " + e, "error"); return; }
  if (!res || !res.ok) { setStatus("Sync failed: " + ((res && res.error) || "?"), "error"); return; }
  const pulled = res.total || 0;
  const jobs = (res.results || []).filter((r) => r.matched && (r.pulled || 0) > 0).length;
  setStatus(`✓ CompanyCam sync complete — pulled ${pulled} photo${pulled === 1 ? "" : "s"} into ${jobs} job${jobs === 1 ? "" : "s"}`, "ok");
}

function openNewLossModal() {
  const inputStyle =
    "width:100%;font:inherit;background:var(--surface-2);color:var(--text);" +
    "border:1px solid var(--border);border-radius:6px;padding:6px 9px;";
  const fieldRow = ([key, label]) => `
    <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);margin:8px 0 2px;">${label}</label>
    ${NL_TEXTAREA_KEYS.has(key)
      ? `<textarea id="nl-${key}" rows="${key === "field_notes" ? 3 : 2}" style="${inputStyle}resize:vertical;"></textarea>`
      : `<input type="text" id="nl-${key}" style="${inputStyle}" autocomplete="off" />`}`;
  const groupBlock = (g) => `
    <div style="margin-top:14px;">
      <div style="font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border);padding-bottom:3px;">${g.group}</div>
      ${g.items.map(fieldRow).join("")}
    </div>`;

  const overlay = createOverlay({
    title: "🆕 New Loss — create Trello card from assignment email",
    sub:   "Paste the carrier email, hit Parse, review/fill the fields, then Create. Fields the email omits can be typed in.",
    body: `
      <div id="nl-board-line" style="font-size:11px;color:var(--text-muted);margin-bottom:8px;">Resolving board…</div>
      <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);margin-bottom:2px;">Paste assignment email</label>
      <textarea id="nl-paste" rows="14" placeholder="From: Mercury - Servpro …" style="${inputStyle}resize:vertical;min-height:240px;line-height:1.4;"></textarea>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
        <button class="btn" id="nl-parse">✨ Parse email</button>
        <span id="nl-parse-status" style="font-size:11px;color:var(--text-muted);"></span>
      </div>

      <div style="display:flex;gap:10px;margin-top:14px;">
        <div style="flex:1;">
          <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);margin-bottom:2px;">Loss type / template</label>
          <select id="nl-loss_type" class="search" style="width:100%;">
            <option value="water">Water</option>
            <option value="fire">Fire</option>
            <option value="property">Property Mgmt</option>
          </select>
        </div>
        <div style="flex:2;">
          <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);margin-bottom:2px;">Card name</label>
          <input type="text" id="nl-card_name" style="${inputStyle}" autocomplete="off" placeholder="Insured - Carrier" />
        </div>
      </div>

      <div id="nl-folder-card" style="margin-top:16px;padding:10px 12px;
           border:1px solid var(--border);border-left-width:3px;border-radius:0 6px 6px 0;
           background:var(--surface-2);font-size:12px;display:none;"></div>

      ${NL_FIELD_GROUPS.map(groupBlock).join("")}

      <label id="nl-cc-row" style="display:none;align-items:center;gap:6px;
             margin-top:14px;font-size:12px;">
        <input type="checkbox" id="nl-make-companycam" checked />
        <span>Also create the <b>CompanyCam project</b> now and pin it
              <span class="muted">— so photos don't have to be matched by
              name later. An EXISTING project is pinned either way.</span></span>
      </label>

      <div class="modal-footer" style="margin-top:16px;display:flex;gap:8px;align-items:center;">
        <span id="nl-status" style="flex:1;font-size:11px;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="nl-create">🆕 Create card</button>
      </div>`,
  });

  const $$ = (sel) => overlay.querySelector(sel);
  const setVal = (key, val) => { const el = $$(`#nl-${key}`); if (el) el.value = val || ""; };

  // ── Where the folder will go ────────────────────────────────────
  // A customer gets ONE folder. A second claim, a unit, or a tenant of a
  // property-management client is a CHILD inside it — never a second
  // top-level folder. This panel shows which of those is about to happen
  // and lets the child be renamed BEFORE anything is created, because
  // the name is the one thing the parser can't infer.
  let nlPlan = null;
  // The parent the operator picked, if any. A commercial loss titled
  // "Bell Mountain Middle School" carries nothing to say which district
  // owns it — and on the live share the children of "Val Verde Unified
  // School" are "Mead Valley", "Rancho Verde", "Red Maple", sharing no
  // token with the parent. So it's chosen, never guessed: creation
  // matches exactly on purpose (a fuzzy hit once nested unrelated
  // "<Name> Property Management" jobs inside each other).
  let nlParent = "";
  async function refreshFolderPlan() {
    const card = $$("#nl-folder-card");
    const insured = ($$("#nl-insured_name")?.value || "").trim();
    if (!insured) { card.style.display = "none"; nlPlan = null; return; }
    const child = ($$("#nl-child-name")?.value || "").trim();
    const second = !!$$("#nl-second-claim")?.checked;
    let p;
    try { p = await pywebview.api.plan_new_loss_folder({ insured_name: insured }, child, second, nlParent); }
    catch (e) { card.style.display = "none"; return; }
    nlPlan = p;
    if (!p?.ok) {
      card.style.display = "block";
      card.style.borderLeftColor = "var(--amber)";
      card.innerHTML = `<b>No folder will be created</b><br>
        <span class="muted">${escapeHtml(p?.error || "?")}</span>`;
      return;
    }
    card.style.display = "block";
    const ctx = p.context || {};
    if (p.mode === "new_client") {
      card.style.borderLeftColor = "var(--green)";
      const prior = ctx.suggest_new_claim
        ? `<div style="margin-top:6px;color:var(--amber);">⚠ No folder yet, but this customer already has
             ${ctx.cards?.length ? `${ctx.cards.length} Trello card${ctx.cards.length === 1 ? "" : "s"}` : ""}
             ${ctx.companycam ? " and a CompanyCam project" : ""} —
             they may be filed under a different spelling.</div>`
        : "";
      card.innerHTML = `<b>📁 New customer folder</b><br>
        <code style="font-size:11.5px;">${escapeHtml(p.path)}</code>${prior}
        ${parentPickerHTML()}`;
      wireParentPicker();
      return;
    }
    // Existing customer → this becomes a child inside their folder.
    card.style.borderLeftColor = "var(--blue, #4a9eff)";
    const kids = (p.children || []);
    const promo = p.promote_first_claim || {};
    card.innerHTML = `
      <b>📁 ${escapeHtml(p.client)} already exists — filing as a sub-folder</b>
      <div style="margin-top:6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <input type="text" id="nl-child-name" value="${escapeHtml(p.child || "")}"
               placeholder="Sub-folder name"
               style="flex:1;min-width:180px;font:inherit;font-size:12px;
                      background:var(--surface);color:var(--text);
                      border:1px solid var(--border);border-radius:5px;padding:5px 8px;" />
        <label style="display:flex;align-items:center;gap:5px;white-space:nowrap;">
          <input type="checkbox" id="nl-second-claim" ${second ? "checked" : ""} />
          <span>New claim (auto-number)</span>
        </label>
      </div>
      <div style="margin-top:6px;"><code style="font-size:11.5px;">${escapeHtml(p.path)}</code></div>
      ${kids.length ? `<div class="muted" style="margin-top:6px;">Already inside: ${kids.map(escapeHtml).join(" · ")}</div>` : ""}
      ${promo.eligible ? `
        <label style="display:flex;align-items:center;gap:6px;margin-top:8px;color:var(--amber);">
          <input type="checkbox" id="nl-promote" />
          <span>Move the existing loose photos into <b>1st Claim</b> first
                (${(promo.moves || []).join(", ")})</span>
        </label>` : ""}
      ${parentPickerHTML()}`;
    // Re-bind: the panel was just replaced.
    $$("#nl-child-name")?.addEventListener("change", refreshFolderPlan);
    $$("#nl-second-claim")?.addEventListener("change", refreshFolderPlan);
    wireParentPicker();
  }

  // ── "File under an existing client" ─────────────────────────────
  // Offered on BOTH branches: a brand-new name is the usual case (the
  // school that belongs to a district), but a name that happens to match
  // an existing folder can still belong somewhere else entirely.
  function parentPickerHTML() {
    if (nlParent) {
      return `
        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <span>📂 Filing under <b>${escapeHtml(nlParent)}</b></span>
          <button class="btn" id="nl-parent-clear" style="font-size:11px;padding:2px 8px;">Use its own folder</button>
        </div>`;
    }
    return `
      <div style="margin-top:8px;">
        <button class="btn" id="nl-parent-open" style="font-size:11px;padding:2px 8px;"
                title="For a job whose name doesn't say who it belongs to — a school under its district, a tenant under a property manager">📂 File under an existing client…</button>
        <div id="nl-parent-box" style="display:none;margin-top:6px;">
          <input type="search" id="nl-parent-q" placeholder="Search client folders…"
                 style="width:100%;box-sizing:border-box;font:inherit;font-size:12px;
                        background:var(--surface);color:var(--text);
                        border:1px solid var(--border);border-radius:5px;padding:5px 8px;" />
          <div id="nl-parent-hits" style="max-height:170px;overflow-y:auto;margin-top:4px;"></div>
        </div>
      </div>`;
  }

  function wireParentPicker() {
    $$("#nl-parent-clear")?.addEventListener("click", () => {
      nlParent = "";
      refreshFolderPlan();
    });
    const open = $$("#nl-parent-open");
    if (!open) return;
    open.addEventListener("click", () => {
      const box = $$("#nl-parent-box");
      if (!box) return;
      box.style.display = "block";
      open.style.display = "none";
      $$("#nl-parent-q")?.focus();
      runParentSearch("");
    });
    let t = null;
    $$("#nl-parent-q")?.addEventListener("input", (e) => {
      clearTimeout(t);
      const q = e.currentTarget.value;
      t = setTimeout(() => runParentSearch(q), 180);
    });
  }

  async function runParentSearch(q) {
    const hits = $$("#nl-parent-hits");
    if (!hits) return;
    hits.innerHTML = `<div class="muted" style="font-size:11px;">Searching…</div>`;
    let res;
    try { res = await pywebview.api.search_client_folders(q || "", 40); }
    catch (e) { res = null; }
    if (!$$("#nl-parent-hits")) return;          // panel was replaced
    const rows = (res && res.clients) || [];
    if (!rows.length) {
      hits.innerHTML = `<div class="muted" style="font-size:11px;">No client folder matches.</div>`;
      return;
    }
    hits.innerHTML = rows.map((r) => `
      <button class="btn nl-parent-pick" data-name="${escapeHtml(r.name)}"
              style="display:block;width:100%;text-align:left;font-size:11.5px;
                     padding:4px 8px;margin-bottom:3px;">
        ${escapeHtml(r.name)}
        ${r.child_count ? `<span class="muted"> · ${r.child_count} inside</span>` : ""}
      </button>`).join("");
    hits.querySelectorAll(".nl-parent-pick").forEach((b) =>
      b.addEventListener("click", () => {
        nlParent = b.dataset.name || "";
        refreshFolderPlan();
      }));
  }

  // Show which board / intake list / templates we'll use.
  (async () => {
    try {
      const t = await pywebview.api.new_loss_templates();
      const line = $$("#nl-board-line");
      if (t?.ok) {
        const avail = ["water", "fire", "property"].filter((k) => t[k]);
        line.innerHTML = `Board: <b>${escapeHtml(t.board || "?")}</b> · Intake: <b>${escapeHtml(t.intake || "?")}</b> · Templates: ${avail.join(", ") || "none"}`;
        // grey unavailable options
        ["water", "fire", "property"].forEach((k) => {
          const opt = overlay.querySelector(`#nl-loss_type option[value="${k}"]`);
          if (opt && !t[k]) { opt.disabled = true; opt.textContent += " (no template)"; }
        });
      } else {
        line.innerHTML = `<span style="color:var(--amber);">⚠ ${escapeHtml(t?.error || "No WIP board found for this department")}</span>`;
      }
    } catch (e) { /* non-fatal */ }
  })();

  // Only offer the CompanyCam option when a token is actually set —
  // otherwise it's a checkbox whose only outcome is an error.
  (async () => {
    try {
      const c = await pywebview.api.companycam_configured();
      if (c?.configured) {
        const row = $$("#nl-cc-row");
        if (row) row.style.display = "flex";
      }
    } catch (e) { /* leave it hidden */ }
  })();

  $$("#nl-parse").addEventListener("click", async () => {
    const text = $$("#nl-paste").value.trim();
    if (!text) { $$("#nl-parse-status").textContent = "Paste the email first"; return; }
    $$("#nl-parse-status").textContent = "Parsing…";
    const res = await pywebview.api.parse_new_loss(text);
    if (!res?.ok) { $$("#nl-parse-status").textContent = res?.error || "Parse failed"; return; }
    const f = res.fields || {};
    NL_FIELD_GROUPS.forEach((g) => g.items.forEach(([key]) => setVal(key, f[key])));
    if (f.loss_type) $$("#nl-loss_type").value = f.loss_type;
    setVal("card_name", f.card_name);
    const got = Object.keys(f).filter((k) => f[k] && k !== "loss_type").length;
    $$("#nl-parse-status").innerHTML = `<span style="color:var(--green);">✓ Parsed ${got} field${got === 1 ? "" : "s"} — review below</span>`;
    refreshFolderPlan();
  });

  // The insured name decides everything about the folder, so re-plan
  // whenever it changes (typed or parsed).
  $$("#nl-insured_name")?.addEventListener("change", refreshFolderPlan);
  $$("#nl-insured_name")?.addEventListener("blur", refreshFolderPlan);

  $$("#nl-create").addEventListener("click", async () => {
    const fields = { loss_type: $$("#nl-loss_type").value };
    NL_FIELD_GROUPS.forEach((g) => g.items.forEach(([key]) => {
      fields[key] = ($$(`#nl-${key}`)?.value || "").trim();
    }));
    fields.card_name = ($$("#nl-card_name")?.value || "").trim();
    if (!fields.card_name && !fields.insured_name) {
      $$("#nl-status").innerHTML = `<span style="color:var(--amber);">Enter a customer name (or card name) first</span>`;
      return;
    }
    const btn = $$("#nl-create");
    btn.disabled = true;
    $$("#nl-status").textContent = "Creating card…";
    const res = await pywebview.api.create_new_loss(
      fields,
      // Folder options come from the panel above. The card and the folder
      // are created independently — a customer with several claims has
      // several cards but ONE folder — and a folder failure never fails
      // the card, which is the part that can't be redone by hand.
      ($$("#nl-child-name")?.value || "").trim(),
      !!$$("#nl-second-claim")?.checked,
      !!$$("#nl-promote")?.checked,
      true,                                   // make_folder
      !!$$("#nl-make-companycam")?.checked,
      nlParent);                              // chosen umbrella, if any
    if (!res?.ok) {
      btn.disabled = false;
      $$("#nl-status").innerHTML = `<span style="color:var(--red);">${escapeHtml(res?.error || "Create failed")}</span>`;
      return;
    }
    closeOverlay();
    const f = res.folder || {};
    const folderNote = f.ok
      ? ` · 📁 ${f.mode === "child" ? f.child : "new folder"}`
      : (f.error ? ` · ⚠ folder: ${f.error}` : "");
    // Distinguish "created it" from "one already existed and we pinned
    // it" — the second is the normal case for a job someone started in
    // the CompanyCam app first, and reads as a no-op otherwise.
    const cc = res.companycam;
    let ccNote = "";
    if (cc) {
      ccNote = cc.ok
        ? (cc.created ? " · 📷 CompanyCam project created + pinned"
                      : " · 📷 CompanyCam project already existed — pinned")
        : ` · ⚠ CompanyCam: ${cc.error || "failed"}`;
    }
    setStatus(`🆕 Created "${res.name}" from ${res.template} → ${res.list} (bottom)${folderNote}${ccNote}. ${res.url || ""}`,
              (f.error || (cc && !cc.ok)) ? "warn" : "ok");
    if (typeof runAudit === "function") { try { runAudit(true); } catch (e) {} }
  });
}

// ── Client Memory modal — every sticky setting in one place ─────
async function openClientMemoryModal(row) {
  const overlay = createOverlay({
    title: "🧠 Client memory — " + row.client,
    sub:   "Every sticky pin + flag the suite remembers for this client",
    body:  `<div id="cm-body"><div class="muted" style="padding:14px;">Loading…</div></div>`,
  });
  const res = await pywebview.api.client_memory(row.client);
  const body = overlay.querySelector("#cm-body");
  if (!res?.ok) {
    body.innerHTML = `<div class="muted" style="padding:14px;color:var(--red);">${escapeHtml(res?.error || "?")}</div>`;
    return;
  }
  const row2 = (label, value, ok) => `
    <div style="display:grid;grid-template-columns:160px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);align-items:start;">
      <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;">${label}</div>
      <div style="font-family:monospace;font-size:12px;word-break:break-all;color:${ok ? "var(--text)" : "var(--text-muted)"};">${value}</div>
    </div>`;
  body.innerHTML = `
    <div style="padding:4px 6px;">
      ${row2("Folder pin",
              res.folder_pin
                ? `${escapeHtml(res.folder_pin)} ${res.folder_exists ? "" : '<span style="color:var(--red);">⚠ missing</span>'}`
                : "<em>none</em>",
              !!res.folder_pin && res.folder_exists)}
      ${row2("Trello card",
              res.trello_pin
                ? `<a href="#" data-open-card="${escapeAttr(res.trello_pin)}">${escapeHtml(res.trello_pin)}</a>`
                : "<em>none</em>",
              !!res.trello_pin)}
      ${(res.trello_pins_all && res.trello_pins_all.length > 1)
        ? row2("All pinned cards", res.trello_pins_all.map(escapeHtml).join("<br>"), true) : ""}
      ${row2("Commercial flag", res.is_commercial ? "✓ Yes" : "<em>no</em>", res.is_commercial)}
      ${row2("Property group",
              res.property_group ? escapeHtml(res.property_group) : "<em>none</em>",
              !!res.property_group)}
      ${row2("Search aliases",
              (res.aliases && res.aliases.length)
                ? res.aliases.map(escapeHtml).join("<br>")
                : "<em>none</em>",
              (res.aliases || []).length > 0)}
      ${row2("Day-pinned units",
              (res.day_units && res.day_units.length)
                ? res.day_units.map(escapeHtml).join("<br>")
                : "<em>none</em>",
              (res.day_units || []).length > 0)}
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;">
      <button class="btn" id="cm-toggle-comm">${res.is_commercial ? "🏢 Unmark commercial" : "🏢 Mark commercial"}</button>
      <button class="btn" id="cm-aliases">🏷 Edit aliases…</button>
      <button class="btn" id="cm-clear-folder" ${res.folder_pin ? "" : "disabled"}>🧹 Clear folder pin</button>
      <button class="btn warn" id="cm-reset-all">♻ Reset all memory</button>
    </div>
    <div class="modal-footer">
      <button class="btn modal-close">Close</button>
    </div>`;
  body.querySelectorAll(".modal-close").forEach((b) =>
    b.addEventListener("click", closeOverlay));
  body.querySelector("[data-open-card]")?.addEventListener("click", (e) => {
    e.preventDefault();
    pywebview.api.open_trello_card(e.target.dataset.openCard);
  });
  body.querySelector("#cm-toggle-comm")?.addEventListener("click", async () => {
    const next = !res.is_commercial;
    await pywebview.api.set_commercial(row.client, next);
    closeOverlay();
    setStatus(next ? `🏢 ${row.client} marked commercial` : `Unmarked commercial`, "ok");
  });
  body.querySelector("#cm-aliases")?.addEventListener("click",
    () => openPropertyStructureModal(row));
  body.querySelector("#cm-clear-folder")?.addEventListener("click", async () => {
    if (!confirm(`Clear the saved folder pin for ${row.client}?`)) return;
    await pywebview.api.clear_folder_path(row.client);
    closeOverlay();
    setStatus(`🧹 Cleared folder pin for ${row.client}`, "ok");
  });
  body.querySelector("#cm-reset-all")?.addEventListener("click", async () => {
    if (!confirm(`Wipe EVERY sticky pin + flag for ${row.client}?\nClears: folder pin, Trello pins, Commercial flag, aliases, day-units.`)) return;
    const rr = await pywebview.api.reset_client_memory(row.client);
    closeOverlay();
    setStatus(rr?.ok ? `♻ Reset memory for ${row.client}` : `Reset failed: ${rr?.error || "?"}`,
              rr?.ok ? "ok" : "error");
  });
}

async function openPropertyStructureModal(row) {
  const overlay = createOverlay({
    title: "🏢 Property structure — " + row.client,
    sub:   "Multi-unit commercial layout, current pins, and search settings",
    body: `<div id="ps-body"><div class="muted" style="padding:14px;">Loading…</div></div>`,
  });
  const res = await pywebview.api.property_structure(row.client);
  const body = overlay.querySelector("#ps-body");
  if (!res?.ok) {
    body.innerHTML = `
      <div style="background:rgba(192,57,43,.10);border:1px solid var(--red);border-radius:6px;padding:10px 14px;margin-bottom:12px;">
        <div style="font-weight:600;color:var(--red);">⚠ ${escapeHtml(res?.error || "?")}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
          Pin the property's umbrella folder first via 🔎 Find folder, then re-open this dialog.
        </div>
      </div>
      <div class="modal-footer"><button class="btn modal-close">Close</button></div>`;
    body.querySelectorAll(".modal-close").forEach((b) =>
      b.addEventListener("click", closeOverlay));
    return;
  }
  const units = res.units || [];
  const s = res.settings || {};
  const renderTree = () => `
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:10px;">
      <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;">Umbrella folder</div>
      <div style="font-family:monospace;font-size:12px;word-break:break-all;color:var(--text);margin-top:2px;">${escapeHtml(res.umbrella)}</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${res.unit_count} unit subfolder${res.unit_count === 1 ? "" : "s"} detected</div>
      <button class="btn" id="ps-open-umbrella" style="margin-top:6px;font-size:11px;padding:4px 8px;">📁 Open umbrella in Explorer</button>
    </div>
    <div style="max-height:340px;overflow:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);">
      ${units.length === 0 ? `<div class="muted" style="padding:14px;">No unit subfolders found — this property may not be multi-unit.</div>`
        : units.map((u) => `
          <div class="ps-unit-row" data-path="${escapeAttr(u.path)}" style="display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);">
            <div>
              <div style="display:flex;gap:8px;align-items:center;">
                <span style="font-weight:600;color:var(--text);">${escapeHtml(u.name)}</span>
                ${u.pinned_today ? `<span style="background:var(--green);color:#FFF;font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;">PINNED TODAY</span>` : ""}
                ${!u.pics_exists ? `<span style="background:rgba(245,166,35,.15);color:var(--amber);font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;">NO PICS</span>` : ""}
                ${!u.docs_exists ? `<span style="background:rgba(245,166,35,.15);color:var(--amber);font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;">NO DOCS</span>` : ""}
              </div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
                📷 ${u.photo_count} photo${u.photo_count === 1 ? "" : "s"}
                ${u.last_modified ? ` · Last activity ${u.last_modified}` : ""}
              </div>
            </div>
            <div style="display:flex;gap:4px;">
              <button class="btn ps-pin" data-path="${escapeAttr(u.path)}" data-pinned="${u.pinned_today}" style="font-size:11px;padding:4px 8px;">${u.pinned_today ? "✕ Unpin today" : "📌 Pin today"}</button>
              <button class="btn ps-open" data-path="${escapeAttr(u.path)}" style="font-size:11px;padding:4px 8px;">📁 Open</button>
            </div>
          </div>`).join("")}
    </div>
    <details style="margin-top:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;">
      <summary style="cursor:pointer;font-weight:600;font-size:12px;color:var(--text);">⚙ Property settings</summary>
      <div style="margin-top:10px;display:flex;flex-direction:column;gap:10px;">
        <label style="display:flex;gap:8px;align-items:center;font-size:12px;cursor:pointer;">
          <input type="checkbox" id="ps-commercial" ${s.is_commercial ? "checked" : ""} />
          <span>Mark as commercial property
            <span style="font-size:10px;color:var(--text-muted);display:block;">Skips the per-job NEW LOSS prompt + sticks across all audits.</span>
          </span>
        </label>
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">Search aliases</div>
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">
            Alternate names this property is filed under. Each line is one alias — useful when the run-doc spells it differently than the OD folder.
          </div>
          <textarea id="ps-aliases" rows="4" style="width:100%;font-family:monospace;font-size:12px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:8px;resize:vertical;" placeholder="e.g.&#10;Avila&#10;Avila Apts&#10;Avila Property Group">${escapeHtml((s.aliases || []).join("\n"))}</textarea>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="btn btn-primary" id="ps-save-settings">💾 Save settings</button>
        </div>
      </div>
    </details>
    <div class="modal-footer">
      <button class="btn modal-close">Close</button>
    </div>`;
  body.innerHTML = renderTree();
  // Wire close + actions
  body.querySelectorAll(".modal-close").forEach((b) =>
    b.addEventListener("click", closeOverlay));
  body.querySelector("#ps-open-umbrella")?.addEventListener("click",
    () => pywebview.api.open_folder(res.umbrella));
  body.querySelectorAll(".ps-open").forEach((b) =>
    b.addEventListener("click", () => pywebview.api.open_folder(b.dataset.path)));
  body.querySelectorAll(".ps-pin").forEach((b) =>
    b.addEventListener("click", async () => {
      // Toggle this unit in the day-pin set.
      const cur = await pywebview.api.list_day_units(row.client);
      const pinnedSet = new Set((cur?.units || []).filter((u) => u.pinned).map((u) => u.path));
      const path = b.dataset.path;
      if (b.dataset.pinned === "true") pinnedSet.delete(path);
      else pinnedSet.add(path);
      await pywebview.api.set_day_units(row.client, Array.from(pinnedSet));
      // Reload structure to refresh the PINNED TODAY chips
      const fresh = await pywebview.api.property_structure(row.client);
      if (fresh?.ok) {
        units.length = 0;
        units.push(...(fresh.units || []));
        body.innerHTML = renderTree();
        // Re-wire (innerHTML wiped event listeners)
        body.querySelectorAll(".modal-close").forEach((bb) =>
          bb.addEventListener("click", closeOverlay));
        body.querySelector("#ps-open-umbrella")?.addEventListener("click",
          () => pywebview.api.open_folder(fresh.umbrella));
        body.querySelectorAll(".ps-open").forEach((bb) =>
          bb.addEventListener("click", () => pywebview.api.open_folder(bb.dataset.path)));
        body.querySelectorAll(".ps-pin").forEach((bb) => bb.addEventListener("click", b.click ? b.click.bind(b) : () => {}));
        bindPropStructure(body, row, fresh);
      }
      setStatus(`📌 ${row.client} unit pins updated`, "ok");
    }));
  bindPropStructure(body, row, res);
}

function bindPropStructure(body, row, payload) {
  // Settings save — commercial flag + aliases.
  const saveBtn = body.querySelector("#ps-save-settings");
  if (!saveBtn) return;
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    const isCommercial = body.querySelector("#ps-commercial")?.checked;
    const aliasesText = body.querySelector("#ps-aliases")?.value || "";
    const aliases = aliasesText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    const res = await pywebview.api.set_property_settings(row.client, !!isCommercial, aliases);
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Save settings";
    if (!res?.ok) {
      setStatus(`Save failed: ${res?.error || "?"}`, "error");
      return;
    }
    setStatus(`💾 Saved settings for ${row.client}`, "ok");
  });
}

async function openDayUnitsModal(row) {
  const res = await pywebview.api.list_day_units(row.client);
  if (!res?.ok) {
    setStatus(`Day-units unavailable: ${res?.error || "?"}`, "warn");
    return;
  }
  const units = res.units || [];
  if (!units.length) {
    setStatus(`No unit subfolders under ${row.folder || "this folder"} — single-unit job`, "warn");
    return;
  }
  const overlay = createOverlay({
    title: "🏠 Pick units for " + row.client,
    sub: "Check every unit this row covers today. Multi-pin replicates the row — one card per unit. Day-only: tomorrow re-derives from scratch.",
    body: `
      <div class="muted" style="font-size:11px;margin-bottom:8px;">
        Umbrella folder: <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">${escapeHtml(res.umbrella || "")}</code>
      </div>
      <div id="du-list" style="display:flex;flex-direction:column;gap:4px;max-height:340px;overflow-y:auto;">
        ${units.map((u) => `
          <label class="du-row" style="display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);cursor:pointer;">
            <input type="checkbox" class="du-cb" data-path="${escapeAttr(u.path)}" ${u.pinned ? "checked" : ""} />
            <div style="flex:1;min-width:0;">
              <div style="font-weight:600;font-size:13px;">${escapeHtml(u.name)}</div>
              <div class="muted" style="font-size:10px;font-family:monospace;word-break:break-all;">${escapeHtml(u.path)}</div>
            </div>
          </label>`).join("")}
      </div>
      <div class="modal-footer">
        <button class="btn" id="du-clear" title="Drop every day-pin for this row — returns to the umbrella folder">✕ Clear all</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="du-save">💾 Apply</button>
      </div>`,
  });

  async function applyAndReaudit(paths) {
    const save = await pywebview.api.set_day_units(row.client, paths);
    if (!save?.ok) { setStatus(`Save failed: ${save?.error || "?"}`, "error"); return; }
    closeOverlay();
    const msg = paths.length
      ? `🏠 Pinned ${paths.length} unit${paths.length !== 1 ? "s" : ""} for today`
      : `🏠 Cleared day-pins for ${row.client}`;
    setStatus(msg, "ok");
    // Force a re-audit so the row replicates per pinned unit (or
    // collapses back to one).
    const re = await pywebview.api.reaudit_one(row.client);
    if (re?.ok) {
      applyRow(re.row);
      renderAll();
    }
  }

  document.getElementById("du-save").addEventListener("click", async () => {
    const picked = [...document.querySelectorAll(".du-cb:checked")]
      .map((cb) => cb.dataset.path);
    await applyAndReaudit(picked);
  });
  document.getElementById("du-clear").addEventListener("click", async () => {
    if (!confirm(`Clear all day-pins for ${row.client}?`)) return;
    await applyAndReaudit([]);
  });
}

async function openMatchDiagnostic(row) {
  const res = await pywebview.api.match_diagnostic(row.client);
  if (!res?.ok) {
    setStatus(`Diagnostic failed: ${res?.error || "?"}`, "error");
    return;
  }
  const overlay = createOverlay({
    title: "🔎 Match diagnostic — " + row.client,
    sub:   `Normalized: "${res.norm_query}" · tokens: [${(res.norm_tokens || []).join(", ")}]`,
    body: `
      <div class="muted" style="margin-bottom:10px;font-size:11px;">
        ${res.candidates.length} candidate folder${res.candidates.length !== 1 ? "s" : ""}
        across ${res.year_count} year${res.year_count !== 1 ? "s" : ""}.
        ${res.override ? `<br>📌 Override pinned: <code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;">${escapeHtml(res.override)}</code>` : ""}
        ${res.trello_pin ? `<br>🔗 Trello pin: <code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;">${escapeHtml(res.trello_pin)}</code>` : ""}
      </div>
      <div class="target-list" style="max-height:380px;overflow-y:auto;">
        ${res.candidates.length ? res.candidates.map((c) => `
          <div class="target-row" data-path="${escapeAttr(c.path)}"
               style="grid-template-columns:auto 1fr auto auto;gap:8px;">
            <span title="Year ${c.year}">${c.year}</span>
            <div>
              <div class="name">${escapeHtml(c.folder)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${escapeHtml(c.why)}</div>
            </div>
            <span class="miss" title="Match score">${c.score}</span>
            <button class="action-btn" data-act="pin">📌 Pin</button>
          </div>`).join("")
        : `<div class="muted" style="padding:20px;text-align:center;">No matching folders found. Check spelling or pin manually via Find Folder.</div>`}
      </div>
      <div class="modal-footer">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  overlay.querySelectorAll(".action-btn[data-act='pin']").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const path = b.closest(".target-row").dataset.path;
      const res2 = await pinFolderGuarded(row.client, path);
      if (res2?.cancelled) { setStatus("Pin cancelled", "warn"); return; }
      if (res2?.ok) {
        setStatus(`📌 Pinned ${path}`, "ok");
        closeOverlay();
        const re = await pywebview.api.reaudit_one(row.client);
        if (re?.ok) {
          applyRow(re.row);
          renderAll();
        }
      }
    }));
}

// ── Trello card hover popover (Tk parity) ───────────────────────
// Mirrors the pinned-card tooltip from the Tk audit. Hovering the
// Trello button for ~400ms fires a backend lookup; the popover
// shows card name / lane / board / last-activity / labels. Cached
// by the backend so re-hovers within a minute don't re-fetch.
