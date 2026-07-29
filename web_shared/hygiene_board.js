/* EMS Tools — shared Hygiene job-board renderer.
 *
 * One at-a-glance table: a row per active job with four admin milestones
 * (DocuSign requested · Initial sent · Final sent · Weekly check-in).
 * Auto-filled where the data exists; empty chips are one-click to stamp
 * today. Used by BOTH the simplified Hygiene page and the audit Overview,
 * so the two never drift.
 *
 * Usage:
 *   HygieneBoard.render(containerEl, { api: pywebview.api, setStatus });
 * Backend contract:
 *   api.hygiene_board_rows() -> { ok, rows:[{canon,card_id,job,ds_requested,
 *       ds_state, initial_sent, final_sent, last_checkin, checkin_overdue}] }
 *   api.hygiene_mark(canon, milestone, card_id) -> { ok, date }
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  // Days since a YYYY-MM-DD date (local), or null.
  function daysSince(d) {
    if (!d) return null;
    const t = Date.parse(d + "T00:00:00");
    if (isNaN(t)) return null;
    return Math.floor((Date.now() - t) / 86400000);
  }

  // One milestone chip. Filled → green with the date; empty → dashed,
  // clickable "mark today"; weekly overdue → amber.
  function chip(row, key, milestone, icon, label) {
    const date = row[key] || "";
    const overdue = milestone === "weekly_checkin" && row.checkin_overdue;
    let cls = "hb-chip", text;
    if (date) {
      const n = daysSince(date);
      text = `${icon} ${label}: ${date}${n != null && milestone === "weekly_checkin" ? ` (${n}d)` : ""}`;
      cls += overdue ? " hb-overdue" : " hb-done";
    } else {
      text = `${icon} ${label}: —`;
      cls += overdue ? " hb-overdue" : " hb-empty";
    }
    // Weekly is always clickable (check in again); others clickable when empty.
    const clickable = milestone === "weekly_checkin" || !date;
    return `<button class="${cls}" ${clickable ? "" : "disabled"}
              data-canon="${esc(row.canon)}" data-card="${esc(row.card_id)}"
              data-ms="${milestone}" title="${clickable ? "Click to stamp today" : "Recorded"}">${esc(text)}</button>`;
  }

  // 📨 Requested chip — color escalates with age (grey → amber → red@5d).
  function requestedChip(r) {
    if (!r.requested_at) return "";
    const n = r.requested_days;
    let cls = "hb-reqchip";
    if (n != null && n >= 5) cls += " hb-req-red";
    else if (n != null && n >= 2) cls += " hb-req-amber";
    const items = (r.requested_items || []).join(", ");
    return `<span class="${cls}" title="Requested: ${esc(items || "—")}">📨 Requested${n != null ? " " + n + "d ago" : ""}</span>`;
  }

  function cardHtml(r) {
    // Weekly check-in only applies to Estimating-board jobs.
    const weekly = r.weekly_applies
      ? chip(r, "last_checkin", "weekly_checkin", "🔁", "Weekly") : "";
    return `
      <div class="hb-card" data-canon="${esc(r.canon)}" data-card="${esc(r.card_id)}" data-job="${esc(r.job)}">
        <div class="hb-card-head">
          <span class="hb-card-name" title="${esc(r.job)}">${esc(r.job)}</span>
          ${r.checkin_overdue ? `<span class="hb-flag">🔁 check-in overdue</span>` : ""}
        </div>
        <div class="hb-chips">
          ${chip(r, "ds_requested", "ds_requested", "📝", "DocuSign")}
          ${chip(r, "initial_sent", "initial_sent", "✉", "Initial")}
          ${chip(r, "final_sent",   "final_sent",   "✅", "Final")}
          ${weekly}
        </div>
        <div class="hb-card-foot">
          ${requestedChip(r)}
          <span style="flex:1;"></span>
          <button class="hb-req-btn" title="Request forms / scope / docusketch from the lead">📨 Request</button>
        </div>
      </div>`;
  }

  async function render(container, ctx) {
    const api = ctx && ctx.api;
    const setStatus = (ctx && ctx.setStatus) || function () {};
    if (!container || !api) return;
    container.innerHTML = `<div class="hb-loading" style="padding:14px;color:var(--text-muted);">Loading job board…</div>`;
    let rows = [];
    try {
      const res = await api.hygiene_board_rows();
      rows = (res && res.rows) || [];
    } catch (ex) {
      container.innerHTML = `<div style="padding:14px;color:var(--red,#E5534B);">Failed: ${esc(ex)}</div>`;
      return;
    }
    if (!rows.length) {
      container.innerHTML = `<div style="padding:14px;color:var(--text-muted);">No active jobs with a Trello card yet.</div>`;
      return;
    }
    const overdue = rows.filter((r) => r.checkin_overdue).length;
    container.innerHTML = `
      <div class="hb-head">
        <span>${rows.length} active job${rows.length === 1 ? "" : "s"}</span>
        ${overdue ? `<span class="hb-overdue-count">🔁 ${overdue} weekly check-in${overdue === 1 ? "" : "s"} overdue</span>` : ""}
      </div>
      <div class="hb-list">${rows.map(cardHtml).join("")}</div>`;

    container.querySelectorAll(".hb-req-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".hb-card");
        if (!card || !window.RequestItems) return;
        window.RequestItems.open({
          api,
          cardId: card.dataset.card,
          canon:  card.dataset.canon,
          job:    card.dataset.job,
          client: card.dataset.job,
          onDone: (res) => {
            if (res && res.ok) {
              setStatus(`📨 Requested — Teams text ${res._copied ? "copied" : "ready"}${res.posted ? " · Trello comment posted" : ""}`, "ok");
              render(container, ctx);         // show the new Requested chip
            } else if (res) {
              setStatus(`Request failed: ${res.error || "?"}`, "error");
            }
          },
        });
      });
    });

    container.querySelectorAll(".hb-chip:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const { canon, card, ms } = btn.dataset;
        btn.disabled = true;
        try {
          const res = await api.hygiene_mark(canon, ms, card || "");
          if (res && res.ok) {
            setStatus(`✓ Marked ${ms.replace("_", " ")} today`, "ok");
            render(container, ctx);            // refresh so sorting/dates update
          } else {
            btn.disabled = false;
            setStatus(`Couldn't mark: ${(res && res.error) || "?"}`, "error");
          }
        } catch (ex) {
          btn.disabled = false;
          setStatus(`Error: ${ex}`, "error");
        }
      });
    });
  }

  window.HygieneBoard = { render };
})();
