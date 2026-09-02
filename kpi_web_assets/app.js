/* Linguar Hub KPI — Pywebview spike frontend.
 *
 * Same patterns as pipeline_web's app.js: vanilla JS, single
 * state object, bridge calls via pywebview.api. The dashboard
 * is read-only so there's no sort / filter / edit complexity —
 * just fetch + render four sections.
 */
"use strict";

const state = {
  weekly:           [],
  right_now:        {},
  cycle_time:       {},
  repeat_offenders: [],
  job_performance:  {},
  operational_groups: {},
  last_refresh:     null,
};

// Metric labels + the "up is bad" inversion flag for each.
// Audits-run, snapshots, adjuster receipts: up = good.
// Flagged, escalations, xa apologies: up = bad.
// Resolved counts as good (more resolved = good).
const WEEKLY_ROWS = [
  { key: "audits_run",        label: "Audits run",         invert: false },
  { key: "flagged",           label: "Flagged",            invert: true  },
  { key: "resolved",          label: "Resolved",           invert: false },
  { key: "escalations",       label: "Escalations",        invert: true  },
  { key: "xa_apologies",      label: "XA apologies",       invert: true  },
  { key: "snapshots_drafted", label: "Snapshots drafted",  invert: false },
  { key: "adjuster_receipts", label: "Adjuster receipts",  invert: false },
];

const RIGHT_NOW_TILES = [
  { key: "concerns",   label: "Concerns",        hot_at: 1, warn_at: 1 },
  { key: "xa_apology", label: "XA apology",      hot_at: 1, warn_at: 1 },
  { key: "hygiene",    label: "Hygiene flags",   hot_at: 10, warn_at: 5 },
  { key: "handoff",    label: "Handoff misses",  hot_at: 1, warn_at: 1 },
  { key: "closeout",   label: "Closeout queue",  hot_at: 10, warn_at: 5 },
];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  // KPI has no tabs or filters — the only "where I was" it has is
  // how far down the tables you had scrolled.
  await PanelState.init("kpi");
  PanelState.bindScroll(document.scrollingElement);

  $("#refresh-btn").addEventListener("click", () => refresh(true));
  await refresh(false);
});

async function refresh(showSpinner) {
  const btn = $("#refresh-btn");
  if (showSpinner) {
    btn.disabled = true;
    btn.textContent = "↻ Refreshing…";
  }
  setStatus("");
  try {
    const data = await pywebview.api.all_sections();
    state.weekly = data.weekly || [];
    state.right_now = data.right_now || {};
    state.cycle_time = data.cycle_time || {};
    state.repeat_offenders = data.repeat_offenders || [];
    state.job_performance = data.job_performance || {};
    state.operational_groups = data.operational_groups
      || state.job_performance.operational_groups || {};
    state.last_refresh = new Date();
    renderAll();
    setStatus(showSpinner ? "Refreshed" : "", "ok");
  } catch (ex) {
    setStatus(`Refresh failed: ${ex}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "↻ Refresh";
  }
}

function renderAll() {
  renderRightNow();
  renderWeekly();
  renderCycleTime();
  renderRepeatOffenders();
  renderJobPerformance();
  renderOperationalGroups();
  $("#last-refresh").textContent = state.last_refresh
    ? `Refreshed ${fmtTime(state.last_refresh)}`
    : "—";
  // Only meaningful once the tables have height — restoring before the
  // rows exist clamps scrollTop to 0.
  if (!renderAll._restored) {
    renderAll._restored = true;
    try { PanelState.restoreScroll(document.scrollingElement); } catch (_) { /**/ }
  }
}

function renderOperationalGroups() {
  const data = state.operational_groups || {};
  const rows = data.groups || [];
  const quality = $("#operations-quality");
  quality.textContent = data.clock_quality === "estimated_from_stage_history"
    ? "Existing history · pause-adjusted timing starts with new events"
    : "Live ownership clocks";
  $("#operations-groups").innerHTML = rows.length ? rows.map((row) => {
    const active = Number(row.active || 0);
    const overdue = Number(row.overdue || 0);
    const statusClass = overdue ? "is-overdue" : "is-clear";
    return `<article class="operations-group ${statusClass}">
      <div class="operations-group-head">
        <h3>${escapeHtml(row.label || row.key || "Group")}</h3>
        <span>${Number(row.jobs || 0)} tracked</span>
      </div>
      <div class="operations-group-signal">
        <strong>${overdue}</strong><span>overdue</span>
        <strong>${active}</strong><span>active</span>
      </div>
      <dl>
        <div><dt>Median total</dt><dd>${fmtDays(row.median_total_days)}</dd></div>
        <div><dt>Median controllable</dt><dd>${fmtDays(row.median_controllable_days)}</dd></div>
      </dl>
    </article>`;
  }).join("") : `<div class="empty-inline">Department timing appears after jobs enter the Pipeline.</div>`;
}

function renderJobPerformance() {
  const p = state.job_performance || {};
  const completed = Number(p.completed_this_month || 0);
  const quota = Number(p.monthly_quota || 0);
  $("#quota-summary").textContent = quota > 0
    ? `${completed} of ${quota} jobs closed this month · ${p.quota_remaining || 0} remaining`
    : `${completed} jobs closed this month · quota not set`;
  const rail = $("#quota-rail");
  rail.hidden = quota <= 0;
  rail.querySelector("i").style.width = `${Math.min(100, Number(p.quota_percent || 0))}%`;
  const bottlenecks = p.stage_bottlenecks || [];
  $("#stage-bottlenecks").innerHTML = bottlenecks.length ? bottlenecks.slice(0, 6).map((row) => `
    <div class="performance-row"><span>${escapeHtml(String(row.stage || "").replaceAll("_", " "))}</span>
    <strong>${row.avg_days}d avg</strong><small>${row.exits} completed</small></div>`).join("")
    : `<div class="empty-inline">Stage timing will appear after jobs move between stages.</div>`;
  const stalled = p.stalled_jobs || [];
  $("#stalled-jobs").innerHTML = stalled.length ? stalled.slice(0, 6).map((row) => `
    <div class="performance-row stalled"><span>${escapeHtml(row.client || "?")}<small>${escapeHtml(String(row.stage || "").replaceAll("_", " "))}${row.owner ? ` · ${escapeHtml(row.owner)}` : ""}</small></span>
    <strong>${row.days}d</strong></div>`).join("")
    : `<div class="empty-inline">No jobs have been stalled for 3+ days.</div>`;
}

// ── Right now ────────────────────────────────────────────────────
function renderRightNow() {
  const grid = $("#right-now-grid");
  const status = $("#rn-status");
  const data = state.right_now || {};
  if (data.scanned === false) {
    status.textContent = "Hygiene scan hasn't run yet — these will populate after the next scan";
    status.classList.add("warn");
  } else {
    status.textContent = "Live snapshot";
    status.classList.remove("warn");
  }
  grid.innerHTML = RIGHT_NOW_TILES.map((t) => {
    const v = Number(data[t.key] || 0);
    let cls = "cold";
    if (v >= t.hot_at)  cls = "hot";
    else if (v >= t.warn_at) cls = "warn";
    if (v === 0) cls = "cold";
    return `
      <div class="metric-tile">
        <div class="num ${cls}">${v}</div>
        <div class="lbl">${escapeHtml(t.label)}</div>
      </div>`;
  }).join("");
}

// ── Weekly trends ────────────────────────────────────────────────
function renderWeekly() {
  const weeks = state.weekly || [];
  // weeks comes back oldest-first from kpi_metrics (per _week_buckets)
  // — flip so newest reads left-to-right
  const ordered = [...weeks].reverse();
  // Header row: Metric | Week 1 (newest) | Week 2 | ...
  const head = $("#weekly-head");
  head.innerHTML = `<th>Metric</th>` + ordered.map((w, i) => {
    const label = (i === 0) ? "This week" : weekLabel(w.week_start);
    return `<th class="num">${escapeHtml(label)}</th>`;
  }).join("");
  // Body
  const body = $("#weekly-body");
  body.innerHTML = WEEKLY_ROWS.map((row) => {
    const cells = ordered.map((w, i) => {
      const v = Number(w[row.key] || 0);
      let trend = "";
      if (i < ordered.length - 1) {
        const prev = Number(ordered[i + 1][row.key] || 0);
        trend = renderTrend(v, prev, row.invert);
      }
      return `<td class="num">${v}${trend}</td>`;
    }).join("");
    return `<tr><td class="label-cell">${escapeHtml(row.label)}</td>${cells}</tr>`;
  }).join("");
}

function renderTrend(curr, prev, invert) {
  if (curr === prev) return ` <span class="trend flat">→</span>`;
  const cls = curr > prev ? "up" : "down";
  const arrow = curr > prev ? "↑" : "↓";
  const invertClass = invert ? "invert " : "";
  return ` <span class="trend ${invertClass}${cls}">${arrow}</span>`;
}

// ── Cycle time ───────────────────────────────────────────────────
function renderCycleTime() {
  const ct = state.cycle_time || {};
  const tiles = [
    { v: ct.open_count, label: "Open" },
    { v: ct.closed_count, label: "Closed" },
    { v: fmtDays(ct.avg_days_open), label: "Avg open" },
    { v: fmtDays(ct.median_days_open), label: "Median open" },
    { v: fmtDays(ct.p90_days_open), label: "P90 open" },
    { v: fmtDays(ct.avg_days_to_close), label: "Avg to close" },
    { v: fmtDays(ct.median_days_to_close), label: "Median to close" },
  ];
  $("#cycle-stats-grid").innerHTML = tiles.map((t) => {
    const dimClass = (t.v === "—") ? "dim" : "";
    return `
      <div class="metric-tile">
        <div class="num ${dimClass}">${escapeHtml(String(t.v))}</div>
        <div class="lbl">${escapeHtml(t.label)}</div>
      </div>`;
  }).join("");
  $("#cycle-summary").textContent =
    `${ct.open_count || 0} open · ${ct.closed_count || 0} closed`;

  const longest = ct.longest_open || [];
  const ul = $("#longest-open");
  if (!longest.length) {
    ul.innerHTML = `<li class="empty">No long-open jobs.</li>`;
    return;
  }
  ul.innerHTML = longest.map((j) => {
    const cls = (j.days >= 90) ? "days hot" : "days";
    return `
      <li>
        <span class="client">${escapeHtml(j.client || "?")}</span>
        <span class="${cls}">${j.days}d</span>
      </li>`;
  }).join("");
}

// ── Repeat offenders ─────────────────────────────────────────────
function renderRepeatOffenders() {
  const rows = state.repeat_offenders || [];
  const empty = $("#repeat-empty");
  const body = $("#repeat-body");
  if (!rows.length) {
    body.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  body.innerHTML = rows.map((j) => `
    <tr data-client="${escapeAttr(j.client || '')}">
      <td class="label-cell">${escapeHtml(j.client || "?")}</td>
      <td class="num">${j.audit_count || 0}</td>
      <td class="muted">${escapeHtml(j.last_audited || "")}</td>
      <td class="muted">${escapeHtml(j.status || "")}</td>
    </tr>
  `).join("");
}

// ── Helpers ──────────────────────────────────────────────────────
function fmtDays(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isFinite(v) ? `${v.toFixed(1)}d` : "—";
  }
  return String(v);
}

function weekLabel(weekStartIso) {
  // weekStartIso looks like "2026-05-18"; show MM/DD for compactness
  if (!weekStartIso) return "—";
  const parts = weekStartIso.split("-");
  if (parts.length !== 3) return weekStartIso;
  return `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}`;
}

function fmtTime(d) {
  const h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${m} ${ampm}`;
}

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
    }, 2500);
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
