/*
 * web_shared/audit_detail.js — SINGLE SOURCE for the per-job audit
 * DETAIL card (chips + missing forms/photos + misfiled + meta + action
 * footer + the Trello-info / Initial / In-Progress checklist sections +
 * per-issue resolved checkboxes + the action dispatch).
 *
 * BOTH the Audit tool (audit_web_assets/app.js) and the Snapshot tool
 * (snapshot_web_assets/app.js) render their per-job detail through this
 * module, so the two surfaces can never drift — add a feature here once
 * and both tools get it. This is what "make the snapshot audit EXACTLY
 * the same as the regular audit" means: identical code, not a copy.
 *
 * The two tools differ only in (a) which modals they open and (b) how
 * they re-render after a mutation. Those differences are injected via a
 * `ctx` object; everything user-visible is shared. `ctx` shape:
 *   {
 *     modals: {                       // each: (row) => void
 *       openFindFolder, openSpImport, openJobImport, openScope,
 *       openCopyPicsToXa, openDayUnits, openPin, openAttachments,
 *       showClaimFolders(row, folders), showOdContents(row, path),
 *       showWorkLog(row),
 *     },
 *     rerender(row),                  // light re-render of THIS card
 *     reauditAndRerender(client),     // re-audit one job then re-render
 *     attachTrelloHover(btn, cardId), // tool's hover-popover helper
 *     showCtxMenu(ev, row),           // tool's right-click menu (optional)
 *     helpers: { escapeHtml, escapeAttr, titleCase, copyText, setStatus },
 *   }
 * Backend calls go straight through the window's `pywebview.api` — the
 * Snapshot window proxies every method used here to audit_web.Api, so the
 * same method names resolve in both. Keep it that way: if you add an
 * api.* call here, add the matching proxy in snapshot_web.py.
 */
(function () {
  "use strict";

  // ── Default helpers (a tool may override via ctx.helpers) ──────────
  function _escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function _escapeAttr(s) { return _escapeHtml(s); }
  function _titleCase(s) {
    return String(s == null ? "" : s).replace(/\w\S*/g,
      (t) => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase());
  }
  // "Last, First" → "First Last" when the name is clearly a personal
  // Last,First (strips a trailing " - Carrier" / " (Unit …)" off the first
  // part). No comma → returned unchanged (already First Last, or a
  // business name). Keeps hyphenated first names (Anne-Marie) intact.
  function _firstLast(name) {
    const raw = String(name == null ? "" : name).trim();
    const ci = raw.indexOf(",");
    if (ci < 0) return raw;
    const last = raw.slice(0, ci).trim();
    let first = raw.slice(ci + 1).trim()
      .replace(/\s+[-–—]\s+.*$/, "")   // drop " - Carrier"
      .replace(/\s*\(.*$/, "")          // drop " (Unit 5)"
      .trim();
    return (first && last) ? `${first} ${last}` : raw;
  }
  async function _copyText(t) {
    try {
      if (window.pywebview && pywebview.api && pywebview.api.set_clipboard) {
        const r = await pywebview.api.set_clipboard(String(t || ""));
        return !!(r && (r.ok || r === true));
      }
    } catch (_) { /* fall through */ }
    try { await navigator.clipboard.writeText(String(t || "")); return true; }
    catch (_) { return false; }
  }
  function _setStatus() { /* no-op default */ }

  function H(ctx)  { return (ctx && ctx.helpers) || {}; }
  function esc(ctx, s)  { return (H(ctx).escapeHtml || _escapeHtml)(s); }
  function escA(ctx, s) { return (H(ctx).escapeAttr || _escapeAttr)(s); }
  function tc(ctx, s)   { return (H(ctx).titleCase  || _titleCase)(s); }
  function copyText(ctx, t) { return (H(ctx).copyText || _copyText)(t); }
  function setStatus(ctx, m, k) { return (H(ctx).setStatus || _setStatus)(m, k); }

  // ── Build the detail card innerHTML for ONE (non-parent) job ───────
  // Verbatim port of audit_web_assets/app.js renderDetail() body.
  // Misfiled detection is OFF. It flags items that are correctly filed,
  // and a wrong warning is worse than no warning — see the note at the
  // chip below. Flip to true once the detection is trustworthy.
  const MISFILED_ENABLED = false;

  function buildDetailBodyHTML(r, ctx) {
    const techs = (r.techs || []).join(" · ");
    const misplacedForms  = r.misplaced_forms  || [];
    const misplacedPhotos = r.misplaced_photos || [];
    const misplacedCount  = misplacedForms.length + misplacedPhotos.length;
    const chips = [];
    // Who's paying, first — it frames everything else on the job. Colour
    // comes from the shared carrier table so the row chip and this one
    // can't drift apart. Nothing shown when the carrier is unknown.
    const carrierChip = (window.AuditDetail && window.AuditDetail.carrierChip)
      ? window.AuditDetail.carrierChip(r.carrier) : "";
    if (carrierChip) chips.push(carrierChip);
    // Category / Class sits WITH the carrier, because it is the same kind
    // of fact — what this loss IS — not an action. It was a button that
    // had to be pressed to find out, which meant nobody knew the CAT
    // without asking. Filled in by loadCatClass once the card is read.
    chips.push(`<span class="detail-chip cat-chip hidden" id="cat-class-chip"
                      title="Category / Class from the initial-inspection notes — click to copy"></span>`);
    if (r.total_missing > 0) {
      chips.push(`<span class="detail-chip missing">${r.total_missing} missing</span>`);
    } else if (!r.flagged) {
      chips.push(`<span class="detail-chip ok">✓ clean</span>`);
    }
    // Misfiled chip suppressed on multi-unit parents/units — files under a
    // unit subfolder aren't actually misfiled (false positive).
    // HIDDEN 2026-08-14 — "all the misfiled is wrong". The detection
    // reports items as misfiled that aren't, so the chip and the section
    // below are both suppressed until it can be fixed. Showing a wrong
    // answer is worse than showing none: people either chase files that
    // are already filed correctly, or learn to ignore the whole panel.
    // The data still rides along on the row, so re-enabling is deleting
    // this flag.
    if (MISFILED_ENABLED && misplacedCount > 0 && !r.subjob && !r.is_parent) {
      chips.push(`<span class="detail-chip misplaced" title="Found in the wrong folder under the parent — needs re-filing">⚠ ${misplacedCount} misfiled</span>`);
    }
    if (r.aging_days >= 3) {
      const hot = r.aging_days >= 7 ? "hot" : "";
      chips.push(`<span class="detail-chip aging ${hot}">⏰ ${r.aging_days}d aging</span>`);
    }
    if (!r.found) {
      chips.push(`<span class="detail-chip not-found">⚠ Folder not found</span>`);
    }
    if (r.new_loss) {
      chips.push(`<span class="detail-chip new-loss">🆕 New loss</span>`);
    }
    // Which work shells the job has. "Does this one have a recon side?"
    // otherwise means opening the folder. An umbrella has none at its own
    // root — its shells sit inside each unit — so those are shown too,
    // marked, rather than reporting nothing.
    const sh = r.shells || {};
    const shOwn = sh.own || [], shKids = sh.from_children || [];
    (shOwn.length ? shOwn : shKids).forEach((name) => {
      const viaKids = !shOwn.length;
      chips.push(`<span class="detail-chip shell" title="${viaKids
        ? "Comes from this client's units/claims, not the top folder"
        : "Work shell in this job's folder"}">${esc(ctx, name)}${viaKids ? " ↓" : ""}</span>`);
    });
    if ((r.sharepoint_new || 0) > 0) {
      chips.push(`<span class="detail-chip sp-new" style="background:var(--act-monitor);color:#fff;cursor:pointer;" title="Click to import — ${r.sharepoint_new} files on SharePoint not in OneDrive yet">📥 SP +${r.sharepoint_new} new</span>`);
    }
    chips.push(`<span class="detail-chip commercial-chip ${r.is_commercial ? "on" : ""}"
                  data-commercial-client="${escA(ctx, r.client)}"
                  title="Toggle commercial — auto-resolves ATP/CIF/CER/CoS">
                  🏢 ${r.is_commercial ? "Commercial" : "Mark commercial"}
                </span>`);
    // The mirror of the commercial chip, and NOT symmetric with it:
    // commercial drops the four insurance forms, self-pay ADDS the home
    // improvement contract + 3-day right to cancel.
    chips.push(`<span class="detail-chip selfpay-chip ${r.is_self_pay ? "on" : ""}"
                  data-selfpay-client="${escA(ctx, r.client)}"
                  title="Toggle self-pay — requires Home Improvement Contract + 3 Day Right to Cancel">
                  💵 ${r.is_self_pay ? "Self-pay" : "Mark self-pay"}
                </span>`);
    for (const a of r.activity || []) {
      chips.push(`<span class="detail-chip activity" data-act="${escA(ctx, a)}">${esc(ctx, a)}</span>`);
    }

    const formsSection = r.form_issues.length ? `
      <section class="detail-section">
        <h3>📋 Missing forms (${r.form_issues.length})</h3>
        <ul class="issue-list">
          ${r.form_issues.map((it) => `<li>${esc(ctx, it)}</li>`).join("")}
        </ul>
      </section>` : "";

    const photosSection = r.photo_issues.length ? `
      <section class="detail-section">
        <h3>📷 Missing photos (${r.photo_issues.length})</h3>
        <ul class="issue-list photos">
          ${r.photo_issues.map((it) => `<li>${esc(ctx, it)}</li>`).join("")}
        </ul>
      </section>` : "";

    const reqs = r.requirements || [];
    const reqSection = reqs.length ? `
      <section class="detail-section">
        <h3>📸 Photo requirements by day (${reqs.length})</h3>
        <ul class="issue-list photos">
          ${reqs.map((q) => `<li>${esc(ctx, q.label)}${q.date ? ` <span class="muted">(${esc(ctx, q.date)})</span>` : ""}</li>`).join("")}
        </ul>
      </section>` : "";

    const misItems = [
      ...misplacedForms.map((m) => ({ ...m, icon: "📋" })),
      ...misplacedPhotos.map((m) => ({ ...m, icon: "📷" })),
    ];
    const misplacedSection = (MISFILED_ENABLED && misItems.length) ? `
      <section class="detail-section">
        <h3>⚠ Misfiled — found in the wrong folder (${misItems.length})</h3>
        <p class="muted" style="margin:2px 0 6px;">Exists under the parent insured, just not in this campus's folder. Move it here.</p>
        <ul class="issue-list misplaced">
          ${misItems.map((m) => `<li>${m.icon} ${esc(ctx, m.label)} <span class="muted">— in <code>${esc(ctx, m.where || "parent")}</code></span></li>`).join("")}
        </ul>
      </section>` : "";

    const cleanSection = (!r.form_issues.length && !r.photo_issues.length
                          && !reqs.length && r.found
                          && !(MISFILED_ENABLED && misItems.length)) ? `
      <section class="detail-section">
        <div class="detail-clean">
          ✓ All required forms + photos present.
        </div>
      </section>` : "";

    // Job Details section removed in the 2026-07 streamline.
    const metaSection = "";

    const hasPath = !!r.path;
    const hasPin = !!r.trello_card_id;

    return `
      <header class="detail-head">
        <div class="detail-name">${esc(ctx, _firstLast(r.display_name || tc(ctx, r.client)))}</div>
        ${techs ? `<div class="detail-techs">${esc(ctx, techs)}</div>` : ""}
      </header>
      <div class="detail-chip-row">${chips.join(" ")}</div>
      ${formsSection}
      ${photosSection}
      ${reqSection}
      ${misplacedSection}
      ${cleanSection}
      ${metaSection}
      <div id="od-summary" class="od-summary" style="display:none;"></div>
      <footer class="detail-actions">
        <div class="action-row" data-group="open">
          <span class="action-group-label">Open</span>
          <div class="action-buttons">
          <button class="action-btn primary" data-action="open-folder"
                  ${hasPath ? "" : "disabled"}>📁 OD folder</button>
          <button class="action-btn" data-action="open-trello"
                  ${hasPin ? "" : "disabled"}><img class="btn-icon" src="../web_shared/trello.png" alt=""/>Trello</button>
          <button class="action-btn" data-action="open-xa"
                  ${hasPin ? "" : "disabled"}><img class="btn-icon" src="../web_shared/xactanalysis.png" alt="" onerror="this.remove()"/>XA</button>
          <button class="action-btn" data-action="xa-note"
                  ${hasPin ? "" : "disabled"}
                  title="Write a note → posts to Trello (dated + @tag), opens XactAnalysis, and copies the note so you can paste it in">🗒 XA note</button>
          <button class="action-btn" data-action="open-companycam"
                  title="Open this job's CompanyCam project (reads the CompanyCam link from the Trello card)"
                  ${hasPin ? "" : "disabled"}><img class="btn-icon" src="../web_shared/companycam.png" alt="" onerror="this.remove()"/>CompanyCam</button>
          <button class="action-btn" data-action="open-workcenter"
                  title="Open WorkCenter in your browser">↗ WorkCenter</button>
          </div>
        </div>
        <div class="action-row" data-group="import">
          <span class="action-group-label">Import</span>
          <div class="action-buttons">
          <button class="action-btn primary" data-action="job-import"
                  title="Import photos/forms into this job's OD folder (WC zip, DocuSign packet, etc.)">📥 Import</button>
          <button class="action-btn" data-action="sp-import"
                  title="Import matching files from SharePoint into the OD job folder">📥 Import SP</button>
          <button class="action-btn" data-action="cc-pull"
                  ${hasPath ? "" : "disabled"}
                  title="Pull this job's NEW CompanyCam photos into its PICS folder&#10;Right-click: change which CompanyCam project this job pulls from"><img class="btn-icon" src="../web_shared/companycam.png" alt="" onerror="this.remove()"/>Pull CompanyCam</button>
          <button class="action-btn" data-action="attachments"
                  ${hasPin ? "" : "disabled"}
                  title="Browse + download the Trello card's photos/files"><img class="btn-icon" src="../web_shared/trello.png" alt=""/>Trello Attachments</button>
          </div>
        </div>
        <div class="action-row" data-group="details">
          <span class="action-group-label">Job details</span>
          <div class="action-buttons">
          <button class="action-btn primary" data-action="job-info"
                  title="Carrier, claim number, adjuster, date of loss — edit here and it syncs with the Trello card">⚙ Job info</button>
          <button class="action-btn" data-action="copy-client">📋 Copy name</button>
          <button class="action-btn" data-action="copy-path"
                  title="Copy this job's OD folder path to the clipboard"
                  ${hasPath ? "" : "disabled"}>📋 Copy path</button>
          <button class="action-btn" data-action="copy-claim"
                  title="Copy the claim number from this job's Trello card"
                  ${hasPin ? "" : "disabled"}>📋 Copy claim #</button>
          <button class="action-btn" data-action="copy-email" id="copy-email-btn"
                  title="Choose a customer, property contact, tenant, or adjuster email">📧 Choose email</button>
          <button class="action-btn" data-action="copy-address"
                  title="Copy the loss address from this Trello card"
                  ${hasPin ? "" : "disabled"}>📋 Copy address</button>
          <button class="action-btn" data-action="copy-job-summary" data-track="copy_job_summary"
                  title="Preview and copy the essential job facts">📋 Copy job summary</button>
          <button class="action-btn" data-action="copy-pics"
                  title="Stage every image in a PICS subfolder into a TEMP folder + open it in Explorer — drag into XactAnalysis from there. Auto-deletes after 1 min."
                  ${hasPath ? "" : "disabled"}>📂 Stage for XA…</button>
          </div>
        </div>
        <div class="action-row" data-group="update">
          <span class="action-group-label">Update</span>
          <div class="action-buttons">
          <button class="action-btn primary-action" data-action="add-update" ${hasPin ? "" : "disabled"}
                  title="Choose the kind of update, preview it, then post">＋ Add update</button>
          <button class="action-btn" data-action="comment" ${hasPin ? "" : "disabled"}>💬 Comment</button>
          <button class="action-btn" data-action="initial-email" ${hasPin ? "" : "disabled"}
                  title="Draft the Initial Inspection email from the card's notes, copy it, open XactAnalysis, then log it on the card">✉ Initial email</button>
          <button class="action-btn" data-action="job-log-comment" ${hasPin ? "" : "disabled"}
                  title="Post the dated job-log comment — pick what happened and who was there">🗒 Job log comment</button>
          <button class="action-btn" data-action="activity-comment" ${hasPin ? "" : "disabled"}
                  title="Post the dated visit comment — pick the stage and who was there">📆 Activity comment</button>
          <button class="action-btn" data-action="call-note" ${hasPin ? "" : "disabled"}
                  title="Log a call or contact on the card, timestamped">📞 Call note</button>
          <button class="action-btn" data-action="request-items">📨 Request items</button>
          <button class="action-btn" data-action="add-child"
                  ${hasPath ? "" : "disabled"}
                  title="Add another claim or unit under this client - finds the existing folder/card first">➕ Claim / Unit</button>
          <button class="action-btn" data-action="add-note" title="Add a tracked to-do note for this job">📝 Note</button>
          ${r.section === "sp_recent" ? `
            <button class="action-btn" data-action="sp-rundoc"
                    title="Open the run-doc for this SP folder's date (parsed from name, e.g. '3-19-26' → 3/19)">📄 Run-doc</button>` : ""}
          <button class="action-btn" type="button" id="detail-more-btn"
                  title="Less-used actions">⋯ More</button>
          </div>
        </div>
        ${ctx && ctx.openSnapshot ? `
        <div class="action-row closeout-row" data-group="closeout">
          <span class="action-group-label">Finish</span>
          <div class="action-buttons">
            <button class="action-btn closeout-btn" data-action="snapshot-closeout"
                    title="Open the close-out snapshot for this job">📸 Close Out Job</button>
            <span class="action-hint">Review the job and prepare its final snapshot.</span>
          </div>
        </div>` : ""}
        <div class="action-row detail-more" id="detail-more" data-group="tools" style="display:none;">
          <span class="action-group-label">Tools</span>
          <div class="action-buttons">
          <button class="action-btn" data-action="find-folder">${r.found ? "🔀 Change folder" : "🔎 Find folder"}</button>
          <button class="action-btn" data-action="pin-card">📌 ${hasPin ? "Re-pin" : "Pin"} Trello</button>
          <button class="action-btn" data-action="scope"
                  title="Paste a scope block → preview rooms → save Scope.pdf to the job's DOCS folder">📋 Scope</button>
          <button class="action-btn" data-action="xa-prep" title="Xactimate 'new estimate from scratch' prep — carrier price list + copy-paste fields">🧮 Xactimate prep</button>
          <button class="action-btn" data-action="match-diag">🔎 Match diagnostic</button>
          <button class="action-btn" data-action="reaudit">↻ Re-audit</button>
          <button class="action-btn" data-action="manage-job"
                  title="Merge a duplicate job or remove a mistaken Hub record">⚖ Merge / delete…</button>
          </div>
        </div>
      </footer>
      ${hasPin ? `<section class="detail-section" id="all-cl">
        <h3>✅ Checklists <span class="muted" id="all-cl-status">loading…</span>
          <button class="action-btn" data-action="import-notes"
                  style="float:right;margin:-2px 6px 0 0;"
                  title="Parse the full initial-inspection field template from the card's Trello comments and copy it">📋 Import notes</button>
          <button class="action-btn" data-action="job-log"
                  style="float:right;margin:-2px 6px 0 0;"
                  title="Build a clean dated job log from the card's comments (strips email noise) + flag equipment left on site">🗒 Job log</button>
</h3>
        <div id="all-cl-body"></div>
      </section>` : ""}
    `;
  }

  // ── Wire the rendered card: buttons, chips, hover, right-click,
  //    then kick off the async sections. `container` is the element the
  //    detail HTML was written into. ──────────────────────────────────
  // ── folder contents, inline ─────────────────────────────────────────
  //
  // The whole point is not having to open Explorer to find out whether
  // the photos are actually there. Two levels, counts only; clicking a
  // group opens the browser at that folder.
  async function loadOdSummary(container, r, ctx) {
    const box = container.querySelector("#od-summary");
    if (!box) return;
    const path = r.path || "";
    if (!path) return;
    box.style.display = "";
    box.innerHTML = '<div class="muted" style="font-size:11px;">Reading folder…</div>';
    let res;
    try { res = await pywebview.api.od_summary(path); }
    catch (e) { res = { ok: false, error: String(e) }; }
    if (!res || !res.ok) {
      box.innerHTML = `<div class="muted" style="font-size:11px;">` +
        `Folder not readable — ${esc(ctx, (res && res.error) || "unknown")}</div>`;
      return;
    }
    const groups = res.groups || [];
    if (!groups.length && !res.files) {
      box.innerHTML = '<div class="muted" style="font-size:11px;">Folder is empty</div>';
      return;
    }
    const total = groups.reduce((n, g) =>
      n + g.files + g.subs.reduce((m, s) => m + s.files, 0), res.files || 0);
    box.innerHTML =
      `<div class="muted" style="font-size:10px;letter-spacing:.05em;
            text-transform:uppercase;margin:10px 0 6px;">
         In the folder · ${total} file${total === 1 ? "" : "s"}</div>` +
      groups.map((g) => {
        const subs = (g.subs || []).filter((x) => x.files > 0);
        const empty = (g.subs || []).filter((x) => !x.files);
        return `<div style="display:flex;gap:8px;align-items:baseline;
                     padding:3px 0;font-size:12px;">
          <button class="od-jump" data-path="${escA(ctx, g.path)}"
                  style="background:none;border:none;padding:0;cursor:pointer;
                         color:var(--text);font:inherit;font-weight:600;">
            📁 ${esc(ctx, g.name)}</button>
          <span class="muted" style="font-size:11.5px;">` +
          (subs.length
            ? subs.map((x) => `${esc(ctx, x.name)} (${x.files})`).join(" · ")
            : (g.files ? `${g.files} file${g.files === 1 ? "" : "s"}` : "")) +
          // Naming the EMPTY ones is the useful half: "PICS (0)" is the
          // answer to "are the photos in yet?", and a row that simply
          // omitted it would read as though nothing were missing.
          (empty.length
            ? `<span style="opacity:.65;"> · ${empty.map((x) =>
                 esc(ctx, x.name) + " (0)").join(" · ")}</span>`
            : "") +
          `</span></div>`;
      }).join("") +
      (res.files ? `<div class="muted" style="font-size:11.5px;padding:3px 0;">
          ${res.files} loose file${res.files === 1 ? "" : "s"} at the top</div>` : "");

    box.querySelectorAll(".od-jump").forEach((b) =>
      b.addEventListener("click", () => {
        const M = (ctx && ctx.modals) || {};
        (M.showOdContents || ((row, pth) => defaultOdContents(ctx, row, pth)))(
          r, b.dataset.path);
      }));
  }

  function wireDetail(container, r, ctx) {
    // What is in the folder, without opening the folder. Loaded per
    // SELECTED job, never per row: it costs ~700ms on the share, which
    // is fine once and unaffordable times fifty.
    loadOdSummary(container, r, ctx);
    container.querySelectorAll(".action-btn[data-action]").forEach((b) => {
      b.addEventListener("click", () => detailAction(b.dataset.action, r, ctx));
      // Changing the CompanyCam project is a correction, not a routine
      // step — it had its own caret button next to Pull, which spent
      // permanent space on something used rarely. Right-click keeps it
      // one gesture away without the clutter.
      if (b.dataset.action === "cc-pull") {
        b.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          // The container has its own contextmenu handler (the row menu).
          // Without this, right-clicking here opens BOTH.
          e.stopPropagation();
          if (b.disabled) return;
          detailAction("cc-relink", r, ctx);
        });
      }
    });
    // Inject the collapse styles once (checklists + ⋯ More).
    if (!document.getElementById("detail-collapse-css")) {
      const st = document.createElement("style");
      st.id = "detail-collapse-css";
      st.textContent =
        ".cl-collapsible > h3{cursor:pointer;user-select:none;}" +
        ".cl-collapsible > h3::before{content:'\\25B8 ';font-size:11px;opacity:.7;}" +
        ".cl-collapsible:not(.cl-collapsed) > h3::before{content:'\\25BE ';}" +
        ".cl-collapsible.cl-collapsed > *:not(h3){display:none !important;}" +
        ".cl-group.cl-collapsed .cl-items{display:none;}" +
        ".cl-group-name{font-weight:600;padding:4px 0;}" +
        // Role tabs over the card's checklists, and a Trello-like
        // progress bar under each checklist title.
        ".cl-tabs{display:flex;gap:2px;flex-wrap:wrap;margin:2px 0 8px;" +
        "border-bottom:1px solid var(--border);}" +
        ".cl-tab{background:transparent;border:none;border-bottom:2px solid transparent;" +
        "color:var(--text-muted);font:inherit;font-size:11.5px;font-weight:600;" +
        "padding:5px 9px;cursor:pointer;border-radius:4px 4px 0 0;white-space:nowrap;}" +
        ".cl-tab:hover{background:var(--surface-2);color:var(--text);}" +
        ".cl-tab.active{color:var(--text);border-bottom-color:var(--accent,#4c9aff);}" +
        ".cl-tab .cl-tab-count{opacity:.65;font-weight:500;margin-left:4px;}" +
        ".cl-tab.cl-tab-done .cl-tab-count{color:var(--green,#3fb950);opacity:1;}" +
        ".cl-pane[hidden]{display:none;}" +
        ".cl-bar{height:4px;border-radius:2px;background:var(--surface-2);" +
        "overflow:hidden;margin:2px 0 4px;}" +
        ".cl-bar > i{display:block;height:100%;background:var(--accent,#4c9aff);" +
        "transition:width .15s ease;}" +
        ".cl-bar.cl-bar-done > i{background:var(--green,#3fb950);}" +
        ".detail-more{display:flex;flex-direction:row;flex-wrap:wrap;gap:4px;}" +
        ".detail-more .action-btn{flex:0 0 auto;}" +
        // Sticky job-name header that shrinks as you scroll (Trello-style).
        ".detail-head{position:sticky;top:0;z-index:6;background:var(--bg,#1b1b1b);" +
        "border-bottom:1px solid transparent;transition:padding .12s ease,border-color .12s ease;}" +
        ".detail-head.shrunk{padding-top:4px;padding-bottom:4px;border-bottom-color:var(--border);}" +
        ".detail-head .detail-name{transition:font-size .12s ease;}" +
        ".detail-head.shrunk .detail-name{font-size:15px;}" +
        ".detail-head.shrunk .detail-techs{display:none;}";
      document.head.appendChild(st);
    }
    // ⋯ More — reveal the less-used row of actions.
    container.querySelector("#detail-more-btn")?.addEventListener("click", () => {
      const m = container.querySelector("#detail-more");
      if (m) m.style.display = (m.style.display === "none" ? "flex" : "none");
    });
    // Trello checklists — each section collapsible, collapsed by default.
    // Trello info section collapsible (each checklist collapses individually
    // inside #all-cl — handled in loadAllChecklists).
    ["trello-info"].forEach((id) => {
      const sec = container.querySelector("#" + id);
      if (!sec) return;
      sec.classList.add("cl-collapsible", "cl-collapsed");
      const h = sec.querySelector("h3");
      if (h) h.addEventListener("click", (e) => {
        if (e.target.closest(".action-btn")) return;
        sec.classList.toggle("cl-collapsed");
      });
    });
    // Sticky job-name header shrinks once you scroll the detail pane.
    const head = container.querySelector(".detail-head");
    if (head) {
      let scroller = container;
      while (scroller && scroller !== document.body) {
        const oy = getComputedStyle(scroller).overflowY;
        if ((oy === "auto" || oy === "scroll") && scroller.scrollHeight > scroller.clientHeight) break;
        scroller = scroller.parentElement;
      }
      scroller = scroller || container;
      // Hysteresis, not a single threshold. Shrinking hides the tech row
      // and tightens the padding, which SHORTENS the content — that drops
      // scrollTop back under a one-value threshold, which un-shrinks the
      // header, which lengthens the content again. Parking the scroll
      // anywhere near that point made the header flip between the two
      // states forever. Growing back now happens far below the point it
      // shrinks at, so the dead band is wider than the height the toggle
      // itself removes and no resting position can satisfy both.
      const SHRINK_AT = 48;
      const GROW_AT = 8;
      let shrunk = false;
      let ticking = false;
      const apply = () => {
        ticking = false;
        const y = scroller.scrollTop || 0;
        if (!shrunk && y > SHRINK_AT) shrunk = true;
        else if (shrunk && y < GROW_AT) shrunk = false;
        else return;                    // inside the band — leave it be
        head.classList.toggle("shrunk", shrunk);
      };
      // Coalesce to one write per frame; a scroll event per pixel doing
      // layout-affecting class writes is its own source of jitter.
      const onScroll = () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(apply);
      };
      scroller.addEventListener("scroll", onScroll, { passive: true });
      apply();
    }
    const hasPin = !!r.trello_card_id;
    if (hasPin) loadTrelloInfo(r, ctx);
    if (hasPin) loadAllChecklists(r, ctx);   // every checklist on the card
    if (hasPin) loadCatClass(r, ctx);        // fills the CAT / Class chip
    // An open comments drawer follows the selection. Costs nothing when
    // it's closed, which is the default — no extra call per job opened.
    syncCommentsDrawer(r, ctx);
    // Activity comment is a BUTTON now — loaded on demand, so opening a
    // job no longer costs two API calls for a thing posted occasionally.
    decorateIssueListsWithCheckboxes(r, ctx);

    const trelloBtn = container.querySelector('.action-btn[data-action="open-trello"]');
    if (trelloBtn && r.trello_card_id && ctx.attachTrelloHover) {
      ctx.attachTrelloHover(trelloBtn, r.trello_card_id);
    }
    if (trelloBtn) {
      trelloBtn.addEventListener("contextmenu", (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        if (ctx.modals && ctx.modals.openPin) ctx.modals.openPin(r);
      });
    }
    const folderBtn = container.querySelector('.action-btn[data-action="open-folder"]');
    if (folderBtn) {
      folderBtn.addEventListener("contextmenu", (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        if (ctx.modals && ctx.modals.openFindFolder) ctx.modals.openFindFolder(r);
      });
    }
    const spChip = container.querySelector(".detail-chip.sp-new");
    if (spChip) {
      spChip.addEventListener("click", (e) => {
        e.stopPropagation();
        if (ctx.modals && ctx.modals.openSpImport) ctx.modals.openSpImport(r);
      });
    }
    const selfPayChip = container.querySelector(".selfpay-chip");
    if (selfPayChip) {
      selfPayChip.style.cursor = "pointer";
      selfPayChip.addEventListener("click", async (e) => {
        e.stopPropagation();
        const cur = !!r.is_self_pay;
        const label = (on) => (on ? "💵 Self-pay" : "💵 Mark self-pay");
        selfPayChip.textContent = "Working…";
        const res = await pywebview.api.set_self_pay(r.client, !cur);
        if (!res || !res.ok) {
          setStatus(ctx, `Toggle failed: ${(res && res.error) || "?"}`, "error");
          selfPayChip.textContent = label(cur);
          return;
        }
        r.is_self_pay = res.self_pay;
        selfPayChip.classList.toggle("on", !!res.self_pay);
        selfPayChip.textContent = label(!!res.self_pay);
        // Turning it ON adds requirements, so name them — otherwise the
        // row just goes red and the user has to work out what appeared.
        setStatus(ctx, res.self_pay
          ? `💵 Self-pay · now needs ${(res.forms || []).join(" + ")}`
          : "Unmarked self-pay", "ok");
        if (ctx.reauditAndRerender) ctx.reauditAndRerender(r.client);
      });
    }
    const commChip = container.querySelector(".commercial-chip");
    if (commChip) {
      commChip.style.cursor = "pointer";
      commChip.addEventListener("click", async (e) => {
        e.stopPropagation();
        const cur = !!r.is_commercial;
        commChip.textContent = "Working…";
        const res = await pywebview.api.set_commercial(r.client, !cur);
        if (!res || !res.ok) {
          setStatus(ctx, `Toggle failed: ${(res && res.error) || "?"}`, "error");
          commChip.textContent = (cur ? "🏢 Commercial" : "🏢 Mark commercial");
          return;
        }
        r.is_commercial = res.on;
        if (res.resolved_count) {
          setStatus(ctx, `🏢 Marked commercial · ${res.resolved_count} forms auto-resolved`, "ok");
        } else {
          setStatus(ctx, res.on ? "🏢 Marked commercial" : "Unmarked commercial", "ok");
        }
        if (ctx.reauditAndRerender) ctx.reauditAndRerender(r.client);
      });
    }
    if (ctx.showCtxMenu) {
      container.addEventListener("contextmenu", (ev) => ctx.showCtxMenu(ev, r));
    }
  }

  // ── The action switch (verbatim port of onDetailAction) ────────────
  // 🗒 XA note — one dialog that posts the note to Trello (dated + optional
  // @tag), opens XactAnalysis, and copies the note so it can be pasted into XA.
  async function openXaNoteModal(row, ctx) {
    if (!window.openModal) { setStatus(ctx, "Note dialog unavailable", "warn"); return; }
    let members = [];
    try {
      const mr = await pywebview.api.xa_note_members(row.client);
      members = (mr && mr.members) || [];
    } catch (e) {}
    let lastTag = "";
    try { lastTag = localStorage.getItem("xa_note_tag") || ""; } catch (e) {}
    const overlay = window.openModal({
      title: "🗒 XA note — " + _firstLast(row.display_name || tc(ctx, row.client)),
      sub: "Posts to Trello (dated + tag) · opens XactAnalysis · copies the note to paste in",
      body: `
        <textarea id="xan-text" rows="5" placeholder="Type your XA note…"
                  style="width:100%;box-sizing:border-box;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px 11px;font:inherit;font-size:13px;"></textarea>
        <div style="display:flex;gap:8px;align-items:center;margin-top:10px;">
          <label style="font-size:11px;font-weight:700;color:var(--text-muted);">Tag</label>
          <select id="xan-tag" style="flex:1;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:7px 9px;font:inherit;font-size:12px;">
            <option value="">— no tag —</option>
            ${members.map((m) => `<option value="${escA(ctx, m.username)}" ${m.username === lastTag ? "selected" : ""}>${esc(ctx, m.name)} (@${esc(ctx, m.username)})</option>`).join("")}
          </select>
        </div>
        <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="xan-go">🗒 Post + open XA</button>
        </div>`,
    });
    const ta = overlay.querySelector("#xan-text");
    if (ta) ta.focus();
    overlay.querySelector("#xan-go").addEventListener("click", async () => {
      const note = (overlay.querySelector("#xan-text").value || "").trim();
      if (!note) { setStatus(ctx, "Type a note first", "warn"); return; }
      const tag = overlay.querySelector("#xan-tag").value || "";
      try { localStorage.setItem("xa_note_tag", tag); } catch (e) {}
      const btn = overlay.querySelector("#xan-go");
      btn.disabled = true;
      const res = await pywebview.api.post_xa_note(row.client, note, tag, row.trello_card_id || "");
      if (!res || !res.ok) { btn.disabled = false; setStatus(ctx, "Post failed: " + ((res && res.error) || "?"), "error"); return; }
      const copied = await copyText(ctx, res.comment || note); // exact posted text
      const xaOpened = !!res.xa_opened;
      try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); }
      setStatus(ctx, `🗒 Posted to Trello${copied ? " + copied" : " · copy failed"}${xaOpened ? " · XA opened" : " · no XA link on card"}`, copied ? "ok" : "warn");
    });
  }

  // Manual CompanyCam project picker — used when auto-match fails (the
  // run-doc name is junk / the project is named by the insured). Resolves
  // to the picked {id, name} (and pins it) or null if cancelled.
  // Folder-vs-CompanyCam reconciliation. Shows WHAT is missing and where
  // each photo would land, so the operator can sanity-check the list
  // before anything downloads. Reached when the watermark says "nothing
  // new" but the folder is actually short — a cleared folder, a failed
  // download, or photos removed by hand.
  // A shoot spanning several rooms lands in a subfolder PER ROOM —
  // route_photo builds <stage>\<tech date>\<room>. Showing only the
  // shared prefix would imply one folder, so the split is spelled out.
  // (The prefix itself used to be one arbitrary room, which was worse:
  // it named a folder most of the photos were not going to.)
  function roomSplit(ctx, g) {
    const rooms = (g.rooms || []).filter(([r]) => r && r !== "(no room tag)");
    if (rooms.length < 2) return "";
    return `<div style="margin-top:2px;">` + rooms.map(([r, n]) =>
      `<div>└ ${esc(ctx, r)} <span style="opacity:.7;">${n}</span></div>`
    ).join("") + `</div>`;
  }

  function ccMissingModal(row, ctx, v) {
    return new Promise((resolve) => {
      if (!window.openModal) { resolve(null); return; }
      const who = _firstLast(row.display_name || tc(ctx, row.client));
      // One row per SHOOT — day + what was done + how many — each with a
      // tick box. A flat "40 missing" can't be acted on: it is usually
      // several visits, and you may want yesterday's demo but not a
      // re-shoot of the initial. `groups` comes from plan_pull, which
      // routes photos through the SAME code the download uses, so the
      // "goes to" column is what will actually happen.
      const groups = v.groups || [];
      const STAGES = window.PICS_STAGES || [];
      const rows = groups.map((g, i) => {
        const rooms = (g.rooms || []).slice(0, 3)
          .map(([r, n]) => `${esc(ctx, r)} ${n}`).join(" · ");
        // A shoot CompanyCam already tagged routes itself. One with no
        // stage tag gets its own dropdown — asking once for all of them
        // was the original complaint: Gary Mongue's 181 photos are eight
        // separate visits by six techs, and they are not all "Initial".
        const tagged = g.stage && g.stage !== "(no stage tag)";
        return `<tr>
          <td style="padding:6px 8px 6px 0;vertical-align:top;">
            <input type="checkbox" class="ccm-g" data-i="${i}" checked /></td>
          <td style="padding:6px 10px 6px 0;white-space:nowrap;vertical-align:top;">
            <b>${esc(ctx, g.date || "—")}</b></td>
          <td style="padding:6px 10px 6px 0;vertical-align:top;">
            ${tagged
              ? `<b>${esc(ctx, g.stage)}</b>`
              : `<select class="ccm-stage" data-i="${i}"
                         style="background:var(--surface-2);color:var(--text);
                                border:1px solid var(--border);border-radius:5px;
                                padding:3px 6px;font:inherit;font-size:12px;">
                   <option value="">— pick a stage —</option>
                   ${STAGES.map((st) => `<option value="${escA(ctx, st)}"${
                     st === g.suggested_stage ? " selected" : ""}>${esc(ctx, st)}</option>`).join("")}
                 </select>${g.suggested_stage ? `
                 <span title="Suggested from the run doc for ${escA(ctx, g.date || "that day")} — change it if the visit was something else"
                       style="font-size:10px;color:var(--accent,#4c9aff);margin-left:5px;white-space:nowrap;">
                   from run doc</span>` : ""}`}
            <input class="ccm-tech" data-i="${i}" type="text"
                   value="${escA(ctx, g.tech || "")}" placeholder="tech"
                   title="Who this gets filed under. Defaults to whoever CompanyCam says took it."
                   style="width:62px;background:var(--surface-2);color:var(--text);
                          border:1px solid var(--border);border-radius:5px;
                          padding:3px 6px;font:inherit;font-size:12px;margin-left:6px;" />
            ${rooms ? `<div style="color:var(--text-muted);font-size:11px;margin-top:2px;">${rooms}</div>` : ""}</td>
          <td style="padding:6px 10px 6px 0;white-space:nowrap;vertical-align:top;">
            <b>${g.count}</b> photo${g.count === 1 ? "" : "s"}</td>
          <td class="ccm-dest" data-i="${i}"
              style="padding:6px 0;color:var(--text-muted);font-size:11px;vertical-align:top;">
            ${esc(ctx, g.target || "(top level)")}${roomSplit(ctx, g)}</td>
        </tr>`;
      }).join("");
      const extraNote = v.extra_files
        ? `<div class="muted" style="margin-top:10px;font-size:11.5px;">
             ${v.extra_files} file${v.extra_files === 1 ? "" : "s"} in the folder
             ${v.extra_files === 1 ? "is" : "are"} not in CompanyCam any more —
             deleted there after being pulled. Nothing here removes them.
           </div>` : "";
      const overlay = window.openModal({
        title: "📷 Pull from CompanyCam — " + who,
        sub: `${v.present} of ${v.total} already in the folder · `
             + `${v.missing} to pull, across ${(v.groups || []).length} `
             + `shoot${(v.groups || []).length === 1 ? "" : "s"}`,
        body: `
          <table style="width:100%;border-collapse:collapse;font-size:12.5px;">
            <thead><tr style="text-align:left;color:var(--text-muted);font-size:11px;
                              text-transform:uppercase;letter-spacing:.04em;">
              <th style="padding-bottom:6px;"><input type="checkbox" id="ccm-all" checked /></th>
              <th>Day</th><th>What we did</th><th>Photos</th><th>Goes to</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
          ${extraNote}
          <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
            <button class="btn modal-close">Cancel</button>
            <button class="btn btn-primary" id="ccm-pull">⬇ Pull ${v.missing} missing</button>
          </div>`,
      });
      let done = false;
      const finish = (val) => {
        if (done) return;
        done = true;
        try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); }
        resolve(val);
      };
      overlay.querySelector(".modal-close")?.addEventListener("click", () => finish(null));

      const boxes = () => [...overlay.querySelectorAll(".ccm-g")];
      const stageOf = (i) => {
        const sel = overlay.querySelector(`.ccm-stage[data-i="${i}"]`);
        return sel ? sel.value : "";        // tagged rows have no dropdown
      };
      // One assignment per ticked shoot, each with its OWN stage, so a
      // day of demo and a day of monitor land in different folders.
      const assignments = () => boxes().filter((b) => b.checked).map((b) => {
        const i = +b.dataset.i;
        const t = overlay.querySelector(`.ccm-tech[data-i="${i}"]`);
        return {photo_ids: (groups[i] || {}).photo_ids || [],
                stage: stageOf(i),
                tech: t ? t.value.trim() : ""};
      });
      const needStage = () => boxes().filter((b) => b.checked)
        .some((b) => overlay.querySelector(`.ccm-stage[data-i="${b.dataset.i}"]`)
                     && !stageOf(+b.dataset.i));
      const refreshCount = () => {
        const picked = assignments();
        const n = picked.reduce((t, a) => t + a.photo_ids.length, 0);
        // Keep the "goes to" column truthful as stages are chosen.
        boxes().forEach((b) => {
          const i = +b.dataset.i, g = groups[i] || {};
          const cell = overlay.querySelector(`.ccm-dest[data-i="${i}"]`);
          if (!cell) return;
          const st = stageOf(i);
          const tEl = overlay.querySelector(`.ccm-tech[data-i="${i}"]`);
          const t = tEl ? tEl.value.trim() : "";
          // Rebuild the box from the typed tech so the preview follows it.
          const base = t ? [t, g.date].filter(Boolean).join(" ") : (g.box || "");
          cell.textContent = st ? [st, base].filter(Boolean).join("\\")
                                : (g.target || base || "(top level)");
        });
        const btn = overlay.querySelector("#ccm-pull");
        if (!btn) return;
        if (needStage()) {
          btn.disabled = true;
          btn.textContent = "⬇ Pick a stage for each shoot";
          return;
        }
        btn.disabled = n === 0;
        btn.textContent = n ? `⬇ Pull ${n} photo${n === 1 ? "" : "s"}`
                            : "⬇ Nothing selected";
      };
      overlay.querySelectorAll(".ccm-stage").forEach(
        (sel) => sel.addEventListener("change", refreshCount));
      overlay.querySelectorAll(".ccm-tech").forEach(
        (inp) => inp.addEventListener("input", refreshCount));
      overlay.querySelector("#ccm-all")?.addEventListener("change", (e) => {
        boxes().forEach((b) => { b.checked = e.target.checked; });
        refreshCount();
      });
      boxes().forEach((b) => b.addEventListener("change", refreshCount));
      refreshCount();

      overlay.querySelector("#ccm-pull")?.addEventListener("click", async (ev) => {
        const btn = ev.currentTarget;
        btn.disabled = true;
        btn.textContent = "⬇ Pulling…";
        // No tech prompt here. Each shoot carries its OWN tech box,
        // pre-filled from whoever CompanyCam says took it — asking again
        // for ONE name would both repeat the question and contradict the
        // per-row answers, since a day can have two techs on one job.
        const tech = "";
        // Downloading is minutes of someone else's API. Hand it to a
        // background thread and give the panel back straight away — the
        // result arrives as an event, so nothing is lost by not waiting.
        let started;
        // Indeterminate until the first per-shoot event arrives — the
        // download starts with a folder walk and an API call before it
        // can say "3 of 40", and that gap is exactly where a bar is
        // wanted most.
        if (window.Progress) window.Progress.start();
        try {
          started = await pywebview.api.companycam_pull_assigned_bg(
            row.client, assignments(), tech || "", row.trello_card_id || "");
        } catch (e) {
          if (window.Progress) window.Progress.fail();
          setStatus(ctx, "CompanyCam pull failed: " + e, "error");
          finish(null); return;
        }
        if (!started || !started.ok) {
          if (window.Progress) window.Progress.fail();
          setStatus(ctx, "CompanyCam: " + ((started && started.error) || "?"), "warn");
          finish(null); return;
        }
        finish(started);   // closes the modal
        const n = started.total || 0;
        setStatus(ctx, `⬇ Pulling ${n} photo${n === 1 ? "" : "s"} in the background…`, "");
        watchCcPull(row.client, ctx);
      });
    });
  }

  // ── Background CompanyCam pull — progress + result ────────────────
  // The pull runs on a thread now, so the outcome arrives as an event
  // rather than a return value. Reporting is deliberately identical to
  // the old inline path: same messages, same re-audit, just not blocking.
  const _ccWatching = new Set();

  function watchCcPull(client, ctx) {
    // One listener per job. Pulling two jobs at once is fine — each has
    // its own watcher and ignores the other's events.
    if (_ccWatching.has(client)) return;
    _ccWatching.add(client);

    const onProgress = (e) => {
      const d = (e && e.detail) || {};
      if (d.client !== client) return;
      // Photos when we have a count, shoots otherwise — a pull can know
      // how many shoots it has long before it knows the photo total.
      if (window.Progress) {
        if (d.total) window.Progress.set(d.done, d.total);
        else if (d.n) window.Progress.set(d.i, d.n);
        else window.Progress.start();
      }
      setStatus(ctx, `⬇ Pulling ${d.stage || "photos"} — shoot ${d.i}/${d.n}`
                     + (d.total ? ` (${d.done}/${d.total} photos)` : ""), "");
    };
    const onDone = (e) => {
      const res = (e && e.detail) || {};
      if (res.client !== client) return;
      window.removeEventListener("companycam:pull-progress", onProgress);
      window.removeEventListener("companycam:pull-done", onDone);
      _ccWatching.delete(client);

      if (!res.ok) {
        if (window.Progress) window.Progress.fail();
        setStatus(ctx, "CompanyCam: " + (res.error || "?"), "warn");
        return;
      }
      const p = res.pulled || 0;
      // res.error is set when a group partly or wholly failed. Ignoring
      // it reported a clean "✓ Pulled 0" for a pull that had actually
      // errored — folders created, no photos, no explanation.
      if (res.error) {
        if (window.Progress) window.Progress.fail();
        setStatus(ctx, p ? `Pulled ${p}, but some failed — ${res.error}`
                         : `Pull failed — ${res.error}`, "warn");
      } else {
        if (window.Progress) window.Progress.done();
        setStatus(ctx, p ? `✓ Pulled ${p} photo${p === 1 ? "" : "s"}`
                         : "Nothing pulled — everything was already there",
                  p ? "ok" : "");
      }
      if (ctx.reauditAndRerender) ctx.reauditAndRerender(client);
    };

    window.addEventListener("companycam:pull-progress", onProgress);
    window.addEventListener("companycam:pull-done", onDone);
  }

  // The matched project is empty but a project at the SAME ADDRESS has
  // photos. Resolves true (switched), false (keep this one) or null
  // (cancelled). The photo counts are the whole point — they are the
  // evidence for which project is really this job.
  function ccOfferAlternate(row, ctx, pr) {
    return new Promise((resolve) => {
      if (!window.openModal) { resolve(false); return; }
      const alts = pr.alternates || [];
      const who = tc(ctx, row.display_name || row.client || "");
      const overlay = window.openModal({
        title: "📷 No photos on the matched project",
        sub: `“${esc(ctx, pr.matched_name || who)}” has none — but another `
           + `project at the same address does. Which one is this job?`,
        body: `
          <div id="cc-alt-list">
            ${alts.map((a, i) => `
              <button class="action-btn cc-alt" data-i="${i}"
                      style="display:block;width:100%;text-align:left;margin-bottom:6px;">
                <b>${esc(ctx, a.name)}</b>
                <span class="muted"> · ${a.count}${a.approx ? "+" : ""} photo${
                  a.count === 1 ? "" : "s"}</span>
                ${a.address ? `<div class="muted" style="font-size:11px;">${
                  esc(ctx, a.address)}</div>` : ""}
              </button>`).join("")}
          </div>
          <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">
            <button class="btn" id="cc-alt-keep">Keep the matched project</button>
            <button class="btn modal-close">Cancel</button>
          </div>`,
      });
      let done = false;
      const finish = (v) => {
        if (done) return;
        done = true;
        try { window.closeModal("modal-overlay"); }
        catch (e) { try { overlay.remove(); } catch (_) {} }
        resolve(v);
      };
      overlay.querySelector(".modal-close")
        ?.addEventListener("click", () => finish(null));
      overlay.querySelectorAll(".cc-alt").forEach((b) =>
        b.addEventListener("click", async () => {
          const a = alts[+b.dataset.i];
          if (!a) return;
          b.disabled = true;
          try {
            const res = await pywebview.api.companycam_pin(row.client, a.id);
            if (res && res.ok === false) {
              setStatus(ctx, `Couldn't pin: ${res.error || "?"}`, "warn");
              b.disabled = false;
              return;
            }
            setStatus(ctx, `📷 Using “${a.name}”`, "ok");
            finish(true);
          } catch (ex) {
            setStatus(ctx, `Couldn't pin: ${ex}`, "warn");
            b.disabled = false;
          }
        }));
      overlay.querySelector("#cc-alt-keep")
        ?.addEventListener("click", () => finish(false));
    });
  }

  function ccManualPick(row, ctx, defaultQuery, opts) {
    return new Promise((resolve) => {
      if (!window.openModal) { resolve(null); return; }
      const o = opts || {};
      const who = _firstLast(row.display_name || tc(ctx, row.client));
      const overlay = window.openModal({
        title: (o.title || "📷 Find CompanyCam project — ") + who,
        sub: o.sub || "No auto-match. Search CompanyCam (projects are named by the insured) and pick the right one — it'll be remembered.",
        body: `
          <div style="display:flex;gap:8px;">
            <input id="ccp-q" type="text" value="${escA(ctx, defaultQuery || "")}" placeholder="Search by insured name…"
                   style="flex:1;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;" />
            <button class="btn" id="ccp-go">Search</button>
          </div>
          <div id="ccp-list" style="margin-top:10px;max-height:280px;overflow:auto;"></div>
          <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">
            <button class="btn modal-close">Cancel</button>
          </div>`,
      });
      let done = false;
      const finish = (val) => { if (done) return; done = true; try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); } resolve(val); };
      overlay.querySelector(".modal-close")?.addEventListener("click", () => finish(null));
      const listEl = overlay.querySelector("#ccp-list");
      const qEl = overlay.querySelector("#ccp-q");
      const run = async () => {
        const q = (qEl.value || "").trim();
        if (!q) { listEl.innerHTML = `<div class="muted" style="padding:8px;">Type a name to search.</div>`; return; }
        listEl.innerHTML = `<div class="muted" style="padding:8px;">Searching…</div>`;
        let r;
        try { r = await pywebview.api.companycam_search(q); }
        catch (e) { listEl.innerHTML = `<div style="padding:8px;color:var(--amber);">Search failed: ${esc(ctx, String(e))}</div>`; return; }
        if (!r || !r.ok) { listEl.innerHTML = `<div style="padding:8px;color:var(--amber);">${esc(ctx, (r && r.error) || "search error")}</div>`; return; }
        const cands = r.candidates || [];
        if (!cands.length) { listEl.innerHTML = `<div class="muted" style="padding:8px;">No CompanyCam projects match “${esc(ctx, q)}”.</div>`; return; }
        listEl.innerHTML = cands.map((c, i) => `
          <div class="ccp-row" data-i="${i}" style="display:flex;justify-content:space-between;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:6px;margin-bottom:6px;cursor:pointer;">
            <div style="min-width:0;">
              <div style="font-weight:600;">${esc(ctx, c.name || "(unnamed)")}</div>
              <div style="font-size:11px;color:var(--text-muted);">${esc(ctx, c.address || "")}</div>
            </div>
            <span style="font-size:11px;color:var(--text-muted);text-align:right;flex:none;">${
              c.unavailable
                ? '<b style="color:var(--amber);">unavailable</b>'
                : (c.photo_count != null
                    ? `<b>${c.photo_count}${c.approx ? "+" : ""}</b> photo${
                        c.photo_count === 1 ? "" : "s"}` : "")
              }${c.score != null ? `<br>${c.score}% name match` : ""}</span>
          </div>`).join("");
        listEl.querySelectorAll(".ccp-row").forEach((el) => {
          el.addEventListener("click", async () => {
            const c = cands[+el.dataset.i];
            if (!c || !c.id) return;
            // Deleted projects keep showing up in search results. Linking
            // one points the job at something that 404s on every pull.
            if (c.unavailable) {
              setStatus(ctx, "That project can't be opened — it looks "
                             + "deleted. Pick another.", "warn");
              return;
            }
            try { await pywebview.api.companycam_pin(row.client, c.id, row.trello_card_id || ""); } catch (e) {}
            finish({ id: c.id, name: c.name });
          });
        });
      };
      overlay.querySelector("#ccp-go")?.addEventListener("click", run);
      qEl?.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
      if (qEl) qEl.focus();
      run();                                    // auto-search the default term
    });
  }

  async function openContactPicker(row, ctx) {
    const btn = document.getElementById("copy-email-btn");
    const old = btn?.textContent || "📧 Choose email";
    if (btn) { btn.disabled = true; btn.textContent = "Getting contacts…"; }
    let res;
    try {
      res = await pywebview.api.get_job_contacts(
        row.client, row.trello_card_id || "");
    } catch (ex) { res = {ok:false, error:String(ex)}; }
    if (btn) { btn.disabled = false; btn.textContent = old; }
    if (!res?.ok) {
      setStatus(ctx, res?.error || "Contacts could not be loaded", "warn"); return;
    }
    const contacts = res.contacts || [];
    const customerSide = contacts.filter(c => c.kind !== "Adjuster");
    const adjusters = contacts.filter(c => c.kind === "Adjuster");
    const contactRows = (items, adjuster=false) => items.map(c => `
      <button class="btn email-choice" data-email="${escA(ctx,c.email)}"
              data-kind="${escA(ctx,c.kind)}"
              style="display:flex;width:100%;align-items:center;text-align:left;gap:10px;
                     padding:9px 10px;margin-top:6px;${adjuster ? "border-color:color-mix(in srgb,var(--amber,#b7791f) 50%,var(--border));" : ""}">
        <span style="min-width:128px;font-size:11px;font-weight:700;">${esc(ctx,c.kind)}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;">${esc(ctx,c.email)}</span>
        <span class="muted" style="font-size:10px;">Copy</span>
      </button>`).join("");
    const wrap = mkModal({
      title: "📧 Choose an email",
      sub: _firstLast(row.display_name || tc(ctx,row.client)),
      width: 590,
      body: `
        ${customerSide.length ? contactRows(customerSide) : `
          <div style="padding:10px 12px;border-left:3px solid var(--amber,#b7791f);
                      background:var(--surface-2);font-size:12px;">
            <b>Customer email missing.</b><br>
            Add the customer, property manager/POC, or tenant email in Job info or Trello.
          </div>`}
        ${adjusters.length ? `<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border);">
          <div style="font-size:10.5px;font-weight:750;text-transform:uppercase;
                      letter-spacing:.05em;color:var(--amber,#b7791f);">
            Adjuster - choose only when the email is meant for them
          </div>${contactRows(adjusters,true)}</div>` : ""}
        ${!contacts.length ? `<div class="muted" style="font-size:12px;margin-top:10px;">No email addresses are saved for this job.</div>` : ""}
        <div class="modal-footer"><button class="btn modal-close">Cancel</button></div>`,
    });
    wrap.querySelectorAll(".email-choice").forEach(choice =>
      choice.addEventListener("click", async () => {
        const ok = await copyText(ctx, choice.dataset.email);
        if (ok) wrap.remove();
        setStatus(ctx, ok
          ? `📧 Copied ${choice.dataset.kind.toLowerCase()} email: ${choice.dataset.email}`
          : "Couldn't copy", ok ? "ok" : "warn");
      }));
  }

  async function detailAction(action, row, ctx) {
    const M = (ctx && ctx.modals) || {};
    if (action === "cc-menu") {
      // The caret button is gone — right-clicking Pull CompanyCam is the
      // gesture now. Kept as an alias so any older caller still lands on
      // the picker rather than silently doing nothing.
      return detailAction("cc-relink", row, ctx);
    }
    if (action === "cc-relink") {
      // Auto-matching by name is right most of the time and wrong often
      // enough to matter — two projects for one loss, or a near-name on
      // another job. There was no way to correct it once it had matched:
      // the manual picker only ever appeared when auto-match FAILED.
      //
      // A pick REPLACES the stored link (companycam_pin drops the
      // others) and find_project_id consults that link before it
      // consults names, so choosing once sticks and auto-matching
      // continues for every job you have not corrected.
      setStatus(ctx, "📷 Reading the current link…", "");
      let cur = null;
      try { cur = await pywebview.api.companycam_probe(row.client,
                                                       row.trello_card_id || ""); }
      catch (_) { /* offline — the picker still works */ }
      const now = (cur && cur.matched && cur.matched_name)
        ? `Currently linked to “${esc(ctx, cur.matched_name)}”`
          + (cur.count != null ? ` (${cur.count} new photo${
              cur.count === 1 ? "" : "s"})` : "")
        : "Nothing is linked yet.";
      const picked = await ccManualPick(
        row, ctx, _firstLast(row.display_name || tc(ctx, row.client)),
        { title: "📷 Change CompanyCam project — ",
          sub: now + " Search below and pick the right one — it is "
             + "remembered for this job and used by every later pull." });
      if (!picked) { setStatus(ctx, "Left as it was", ""); return; }
      setStatus(ctx, `📷 Now linked to “${picked.name}”`, "ok");
      return;
    }
    if (action === "comments") {
      toggleCommentsDrawer(row, ctx);
      return;
    }
    if (action === "request-items") {
      if (window.RequestItems) {
        window.RequestItems.open({
          api: pywebview.api,
          cardId: row.trello_card_id || "",
          canon: "",                       // backend resolves from client
          job: row.display_name || row.client,
          client: row.display_name || row.client,
          onDone: (res) => {
            if (res && res.ok) {
              setStatus(ctx, `📨 Requested — Teams text ${res._copied ? "copied" : "ready"}${res.posted ? " · Trello posted" : ""}`, "ok");
            } else if (res) {
              setStatus(ctx, `Request failed: ${res.error || "?"}`, "error");
            }
          },
        });
      }
      return;
    }
    if (action === "xa-prep") {
      if (window.XactimatePrep) {
        window.XactimatePrep.open({
          api: pywebview.api,
          client: row.display_name || row.client,
        });
      }
      return;
    }
    if (action === "add-note") {
      openAddUpdateModal(row, ctx, "note");
      return;
    }
    if (action === "open-folder") {
      const res = await pywebview.api.open_od_for_client(
        row.client, row.path || "");
      if (res && res.ok) {
        if (res.refreshed && res.path && res.path !== row.path) {
          row.path = res.path;
          row.found = true;
          if (ctx.rerender) ctx.rerender(row);
          setStatus(ctx, `Opened ${row.client} · path refreshed`, "ok");
        } else {
          setStatus(ctx, `Opened ${row.client}`, "ok");
        }
      } else if (res && res.needs_find) {
        if (confirm(`Couldn't open ${row.client}:\n${res.error || "no folder"}\n\nOpen Find Folder to pick one?`)) {
          if (M.openFindFolder) M.openFindFolder(row);
        } else {
          setStatus(ctx, res.error || "No folder", "warn");
        }
      } else {
        setStatus(ctx, (res && res.error) || "Couldn't open folder", "warn");
      }
    } else if (action === "claim-folders") {
      const r = await pywebview.api.claim_folders(row.path || "");
      const folders = (r && r.folders) || [];
      if (!folders.length) {
        setStatus(ctx, "No past claim / date folders in this job's directory", "warn");
        return;
      }
      if (M.showClaimFolders) M.showClaimFolders(row, folders);
    } else if (action === "od-contents") {
      (M.showOdContents || ((r, p) => defaultOdContents(ctx, r, p)))(row, row.path || "");
    } else if (action === "work-log") {
      (M.showWorkLog || ((r) => defaultWorkLog(ctx, r)))(row);
    } else if (action === "open-trello") {
      await pywebview.api.open_trello_card(row.trello_card_id);
    } else if (action === "open-xa") {
      // Pass the card_id the row already holds (name re-lookup is fragile).
      const ok = await pywebview.api.open_xa_link(row.client, row.trello_card_id || "");
      if (!ok) setStatus(ctx, "No XactAnalysis link on this card yet — add an 'EMS Xactanalysis Link' line to the Trello card's LINKS section.", "warn");
    } else if (action === "open-companycam") {
      const ok = await pywebview.api.open_companycam_link(row.client);
      if (!ok) setStatus(ctx, "No CompanyCam link on this card yet — add a 'CompanyCam Link' line to the Trello card's LINKS section.", "warn");
    } else if (action === "open-workcenter") {
      const res = await pywebview.api.open_workcenter();
      if (!res?.ok) setStatus(ctx, `Couldn't open WorkCenter: ${res?.error || "unknown error"}`, "warn");
    } else if (action === "xa-note") {
      openXaNoteModal(row, ctx);
    } else if (action === "attachments") {
      // Already falls back to the shared trello_attachments.js module,
      // which both panels load — so this one is NOT renderer-specific.
      // The argument is an OBJECT; the modal destructures {cardId,
      // client, onAfter}, and passing positionally silently opens with
      // no card.
      if (M.openAttachments) M.openAttachments(row);
      else window.openTrelloAttachmentsModal({ cardId: row.trello_card_id, client: row.client });
    } else if (action === "sp-import") {
      if (M.openSpImport) M.openSpImport(row);
    } else if (action === "cc-pull") {
      setStatus(ctx, "📷 Checking CompanyCam…", "");
      const cardId = row.trello_card_id || "";
      let pr;
      try { pr = await pywebview.api.companycam_probe(row.client, cardId); }
      catch (e) { setStatus(ctx, "CompanyCam check failed: " + e, "error"); return; }
      if (!pr || !pr.ok) { setStatus(ctx, "CompanyCam: " + ((pr && pr.error) || "?"), "warn"); return; }
      if (!pr.matched) {
        // Auto-match failed — let the user find & pin the project by hand.
        const picked = await ccManualPick(row, ctx, _firstLast(row.display_name || tc(ctx, row.client)));
        if (!picked) { setStatus(ctx, "No CompanyCam project matched this job", "warn"); return; }
        setStatus(ctx, "📷 Re-checking CompanyCam…", "");
        try { pr = await pywebview.api.companycam_probe(row.client, cardId); }
        catch (e) { setStatus(ctx, "CompanyCam check failed: " + e, "error"); return; }
        if (!pr || !pr.ok || !pr.matched) { setStatus(ctx, "Pinned, but couldn't read that project — try the pull again", "warn"); return; }
      }
      // Matched a project with NOTHING on it, while another project at the
      // same address has photos. One job with two CompanyCam projects
      // under different names is common enough to handle: the name match
      // was exact and correct, it just landed on the empty one, and
      // reporting "no photos" for a job that plainly has them is the
      // wrong answer. Offer the switch; never make it silently.
      if (!pr.count && (pr.alternates || []).length) {
        const switched = await ccOfferAlternate(row, ctx, pr);
        if (switched === null) { setStatus(ctx, "Pull cancelled", "warn"); return; }
        if (switched) {
          setStatus(ctx, "📷 Re-checking CompanyCam…", "");
          try { pr = await pywebview.api.companycam_probe(row.client, cardId); }
          catch (e) { setStatus(ctx, "CompanyCam check failed: " + e, "error"); return; }
        }
      }
      // The per-shoot preview is the MAIN path, not a fallback.
      //
      // It used to run only when the watermark said "nothing new", so a
      // job with 181 new photos skipped it and went straight to the
      // single-stage picker — forcing ONE stage for every shoot, which is
      // wrong the moment a job has an initial AND a demo AND a monitor.
      // The watermark also can't tell you whether the folder still HAS
      // what it already saw, so planning against the folder is the more
      // honest question in both cases.
      const who = _firstLast(row.display_name || tc(ctx, row.client));
      setStatus(ctx, "📷 Working out what's missing…", "");
      // Start the bar HERE, not when the first progress event lands. This
      // check is the long part — it walks the folder and fetches a tag
      // per photo — and showing nothing until the download begins meant
      // the bar appeared only after the wait everyone was watching.
      if (window.Progress) window.Progress.start();
      let v;
      try { v = await pywebview.api.companycam_plan_pull(row.client, "", cardId); }
      catch (e) {
        if (window.Progress) window.Progress.fail();
        setStatus(ctx, "CompanyCam check failed: " + e, "error"); return;
      }
      if (!v || !v.ok) {
        if (window.Progress) window.Progress.fail();
        setStatus(ctx, "CompanyCam: " + ((v && v.error) || "?"), "warn"); return;
      }
      // Planning is done — the download has its own progress from here,
      // and if there's nothing to pull this is where it ends.
      if (window.Progress) window.Progress.done();
      if (!v.missing) {
        setStatus(ctx, `📷 All ${v.total} photo${v.total === 1 ? "" : "s"} already in the folder`
          + (v.extra_files ? ` · ${v.extra_files} not in CompanyCam any more` : ""), "ok");
        return;
      }
      // No up-front stage prompt. Asking once for a whole project is the
      // bug this replaced: Gary Mongue's 181 untagged photos are eight
      // separate visits by six techs, and they are not all one stage.
      // Each shoot picks its own stage in the list instead.
      await ccMissingModal(row, ctx, v);
    } else if (action === "job-info") {
      await openJobInfoModal(row, ctx);
    } else if (action === "copy-client") {
      // Always copy as "First Last" when it's a Last,First personal name.
      const nm = _firstLast(row.client);
      const ok = await copyText(ctx, nm);
      setStatus(ctx, ok ? `📋 Copied: ${nm}` : "Couldn't copy", ok ? "ok" : "error");
    } else if (action === "copy-path") {
      if (!row.path) { setStatus(ctx, "No folder path for this job", "warn"); return; }
      const ok = await copyText(ctx, row.path);
      setStatus(ctx, ok ? `📋 Copied path: ${row.path}` : "Couldn't copy", ok ? "ok" : "error");
    } else if (action === "copy-claim") {
      const res = await pywebview.api.get_claim_number(row.client);
      if (res && res.ok && res.claim) {
        const ok = await copyText(ctx, res.claim);
        setStatus(ctx, ok ? `📋 Copied claim #: ${res.claim}` : "Couldn't copy", ok ? "ok" : "error");
      } else {
        setStatus(ctx, (res && res.error) || "No claim # found", "warn");
      }
    } else if (action === "copy-address") {
      const res = await pywebview.api.get_address(row.client);
      if (res && res.ok && res.address) {
        const ok = await copyText(ctx, res.address);
        setStatus(ctx, ok ? `📋 Copied address: ${res.address}` : "Couldn't copy",
                  ok ? "ok" : "error");
      } else {
        setStatus(ctx, (res && res.error) || "No address found", "warn");
      }
    } else if (action === "copy-email") {
      await openContactPicker(row, ctx);
    } else if (action === "copy-job-summary") {
      await openCopyJobSummaryModal(row, ctx);
    } else if (action === "grab-cat-class") {
      setStatus(ctx, "Reading initial notes from Trello comments…", "info");
      const res = await pywebview.api.get_initial_cat_class(
        row.client, row.trello_card_id || "");
      const out = document.getElementById("cat-class-chip");
      if (res && res.ok && res.text) {
        if (out) { out.textContent = res.text; out.classList.remove("hidden"); }
        const ok = await copyText(ctx, res.text);
        setStatus(ctx, ok ? `🔢 ${res.text} — copied` : `🔢 ${res.text}`, "ok");
      } else {
        if (out) out.classList.add("hidden");
        setStatus(ctx, (res && res.error) || "No Category/Class in the initial notes", "warn");
      }
    } else if (action === "import-notes") {
      setStatus(ctx, "Parsing initial-inspection template…", "info");
      const res = await pywebview.api.import_initial_notes(
        row.client, row.trello_card_id || "");
      if (res && res.ok && res.summary) {
        const ok = await copyText(ctx, res.summary);
        setStatus(ctx, ok ? "📋 Initial notes copied — paste into the snapshot/notes"
                          : "📋 Parsed (clipboard blocked)", "ok");
      } else {
        setStatus(ctx, (res && res.error) || "No initial-inspection notes on the card", "warn");
      }
    } else if (action === "job-log") {
      setStatus(ctx, "Building job log from comments…", "info");
      const res = await pywebview.api.get_job_log(
        row.client, row.trello_card_id || "");
      const body = document.getElementById("initial-cl-body");
      if (res && res.ok) {
        if (body) {
          const rows = (res.rows || []).map((r) =>
            `<tr><td style="white-space:nowrap;padding-right:10px;">${esc(ctx, r.date)} ${esc(ctx, r.weekday || "")}</td>`
            + `<td style="padding-right:10px;">${esc(ctx, r.activity)}</td>`
            + `<td class="muted">${esc(ctx, r.who || "")}</td></tr>`).join("");
          body.innerHTML =
            (res.eq_warn ? `<div style="color:var(--amber);font-weight:600;margin-bottom:6px;">${esc(ctx, res.eq_warn)}</div>` : "")
            + (rows ? `<table style="font-size:12px;border-collapse:collapse;">${rows}</table>`
                    : `<div class="muted">No datable field events.</div>`);
        }
        await copyText(ctx, res.text || "");
        setStatus(ctx, `🗒 Job log — ${res.count} event(s)${res.eq_warn ? " · ⚠ EQ on site" : ""} (copied)`, "ok");
      } else {
        setStatus(ctx, (res && res.error) || "No job-log events in comments", "warn");
      }
    } else if (action === "job-import") {
      if (M.openJobImport) M.openJobImport(row);
    } else if (action === "day-units") {
      if (M.openDayUnits) M.openDayUnits(row);
    } else if (action === "copy-pics") {
      openCopyPicsToXaModal(row, ctx);           // shared — works in both tools
    } else if (action === "scope") {
      if (M.openScope) M.openScope(row);
    } else if (action === "match-diag") {
      if (M.openMatchDiag) M.openMatchDiag(row);
    } else if (action === "reaudit") {
      if (ctx.reauditAndRerender) ctx.reauditAndRerender(row.client);
    } else if (action === "manage-job") {
      await openManageJobModal(row, ctx);
    } else if (action === "snapshot-closeout") {
      if (ctx && ctx.openSnapshot) ctx.openSnapshot(row);
    } else if (action === "find-folder") {
      if (M.openFindFolder) M.openFindFolder(row);
    } else if (action === "pin-card") {
      openPinModal(row, ctx);                     // shared — real persisted pin
    } else if (action === "initial-email") {
      openInitialEmailModal(row, ctx);
    } else if (action === "add-update") {
      openAddUpdateModal(row, ctx, "general");
    } else if (action === "job-log-comment") {
      openAddUpdateModal(row, ctx, "job_log");
    } else if (action === "activity-comment") {
      openAddUpdateModal(row, ctx, "activity");
    } else if (action === "call-note") {
      openAddUpdateModal(row, ctx, "call");
    } else if (action === "comment") {
      openAddUpdateModal(row, ctx, "general");
    } else if (action === "add-child") {
      await openAddChildModal(row, ctx);
    } else if (action === "closeout") {
      openCloseoutModal(row, ctx);                // shared CLOSE OUT checklist
    } else if (action === "sp-rundoc") {
      const res = await pywebview.api.open_rundoc_for_sp_match(row.path);
      if (res && res.ok) {
        const back = res.days_back > 0 ? ` · ${res.days_back}d back` : "";
        const tail = res.source && res.source !== "today" ? ` (from ${res.source})` : "";
        setStatus(ctx, `📄 Opening ${res.date_label}${tail}${back}`, "ok");
      } else {
        setStatus(ctx, `Couldn't open: ${(res && res.error) || "no run-doc"}`, "warn");
      }
    }
  }

  // ── Async section: 🎴 Trello info (verbatim port) ──────────────────
  // The CAT / Class chip. Reads the same initial-inspection notes the
  // old button read, but on open rather than on demand — the number is
  // part of what the job IS, and a button meant it stayed unknown until
  // somebody thought to ask. Silent when the notes don't carry one:
  // most jobs have no CAT, and an empty chip on every card is noise.
  async function loadCatClass(row, ctx) {
    const chip = document.getElementById("cat-class-chip");
    if (!chip) return;
    let res;
    try {
      res = await pywebview.api.get_initial_cat_class(
        row.client, row.trello_card_id || "");
    } catch (_) {
      return;                       // offline is not worth a banner here
    }
    // The card may have been re-rendered while we were awaiting.
    if (document.getElementById("cat-class-chip") !== chip) return;
    if (!res || !res.ok || !res.text) return;
    chip.textContent = res.text;
    chip.classList.remove("hidden");
    chip.style.cursor = "pointer";
    chip.addEventListener("click", async () => {
      const ok = await copyText(ctx, res.text);
      setStatus(ctx, ok ? `🔢 ${res.text} — copied` : `🔢 ${res.text}`, "ok");
    });
  }

  async function loadTrelloInfo(row, ctx) {
    // The 🎴 Trello block is gone from the card — the comments drawer
    // covers it and the rest was duplicated by the chips. This call
    // stays because it is ALSO what fills the footer's 📧 Copy email
    // button; dropping it silently disabled that.
    const statusEl = document.getElementById("trello-info-status");
    const bodyEl = document.getElementById("trello-info-body");
    let r;
    try { r = await pywebview.api.trello_enrichment(row.client, row.trello_card_id || ""); }
    catch (e) { if (statusEl) statusEl.textContent = "error"; return; }
    if (bodyEl && document.getElementById("trello-info-body") !== bodyEl) return;
    if (!r || !r.ok) { if (statusEl) statusEl.textContent = r && r.error ? "error" : ""; return; }
    if (!r.has_card) { const s = document.getElementById("trello-info"); if (s) s.remove(); return; }
    if (statusEl) statusEl.textContent = "";
    const chip = (txt, color) => `<span style="display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;background:${color || "var(--surface-2)"};color:var(--text);margin:0 4px 4px 0;">${esc(ctx, txt)}</span>`;
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
    const emails = (r.contacts || []).map(c => [c.kind, c.email]);
    if (!emails.length && r.customer_email) emails.push(["Customer", r.customer_email]);
    if (!emails.length && r.adjuster_email) emails.push(["Adjuster", r.adjuster_email]);
    if (emails.length) {
      html += `<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">${emails.map(([k, v]) => `${k}: <a href="#" class="tr-email" data-email="${escA(ctx, v)}" style="color:var(--text);">${esc(ctx, v)}</a>`).join(" &nbsp;·&nbsp; ")}</div>`;
    }
    if ((r.comments || []).length) {
      // Collapsed by default — recent comments are handy but bulky; a
      // <details> keeps the Trello card compact until the user expands.
      const cmts = r.comments.map((c) => `
        <div style="border-left:2px solid var(--border);padding:2px 0 2px 8px;margin-bottom:4px;">
          <div style="font-size:10px;color:var(--text-muted);">${esc(ctx, c.author || "")}${c.date ? " · " + esc(ctx, c.date) : ""}</div>
          <div style="font-size:12px;white-space:pre-wrap;">${esc(ctx, (c.text || "").slice(0, 400))}</div>
        </div>`).join("");
      html += `<details class="tr-comments" style="margin-top:6px;">
        <summary style="cursor:pointer;font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;list-style:revert;">Recent comments (${r.comments.length})</summary>
        <div style="margin-top:4px;">${cmts}</div>
      </details>`;
    }
    if (!html) html = '<div class="muted" style="font-size:11px;">Card pinned, but no extra info filled in yet.</div>';
    if (bodyEl) bodyEl.innerHTML = html;
    (bodyEl ? [...bodyEl.querySelectorAll(".tr-email")] : []).forEach((a) =>
      a.addEventListener("click", async (e) => {
        e.preventDefault();
        const ok = await copyText(ctx, a.dataset.email);
        setStatus(ctx, ok ? `📧 Copied ${a.dataset.email}` : "Couldn't copy", ok ? "ok" : "warn");
      }));
  }

  // ── Checklist role grouping ────────────────────────────────────────
  // The card carries eight checklists belonging to different people, and
  // showing them as one flat run made it impossible to see what was
  // yours. Split by role, in the order the office asked for.
  //
  // Matching is by SUFFIX ("INITIAL - ADMIN" → Admin) so a new checklist
  // added to the card template lands in the right tab without a code
  // change. Older cards carry un-suffixed names (INITIAL, CONTENTS…);
  // those map to the same tab as their suffixed twin so an old card
  // reads like a new one. Anything unrecognised falls to Misc rather
  // than being hidden.
  // Intake first — it's where a job starts, so it's where you look first.
  const CL_ROLES = [
    { key: "intake", label: "Intake" },
    { key: "admin",  label: "Admin" },
    { key: "coord",  label: "Coordinator" },
    { key: "field",  label: "Field" },
    { key: "est",    label: "Estimating" },
    { key: "misc",   label: "Misc" },
  ];

  // Un-suffixed legacy names → the tab their suffixed twin uses.
  const CL_LEGACY = {
    "initial":     "admin",
    "in progress": "admin",
    "close out":   "admin",
    "closeout":    "admin",
    "contents":    "coord",
  };

  function checklistRole(name) {
    const n = String(name || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (!n) return "misc";
    if (n === "intake") return "intake";
    if (n === "estimating") return "est";
    // Suffix wins: it's the current convention and the most specific.
    if (/\s-\s*admin$/.test(n))       return "admin";
    if (/\s-\s*coordinator$/.test(n)) return "coord";
    if (/\s-\s*estimating$/.test(n))  return "est";
    // "FIELD" and "FIELD LEAD" are the same people — match the whole
    // family rather than the one exact spelling, so a checklist added as
    // "INITIAL - FIELD LEADS" doesn't quietly land in Misc.
    if (/\s-\s*field(\s+leads?)?$/.test(n)) return "field";
    if (/\bfield\s+leads?\b/.test(n))       return "field";
    if (Object.prototype.hasOwnProperty.call(CL_LEGACY, n)) return CL_LEGACY[n];
    return "misc";   // SUBS, and anything new
  }

  // Recompute every checklist bar + tab count from the checkboxes on
  // screen. Cheap, and it keeps one source of truth (the DOM) rather
  // than trying to patch counts item by item.
  function refreshChecklistProgress(root) {
    if (!root) return;
    root.querySelectorAll(".cl-group").forEach((g) => {
      const boxes = g.querySelectorAll('.cl-item input[type="checkbox"]');
      const done = [...boxes].filter((b) => b.checked).length;
      const pct = boxes.length ? Math.round((done / boxes.length) * 100) : 0;
      const bar = g.querySelector(".cl-bar");
      if (bar) {
        bar.classList.toggle("cl-bar-done", boxes.length > 0 && done === boxes.length);
        const fill = bar.querySelector("i");
        if (fill) fill.style.width = pct + "%";
      }
      const lbl = g.querySelector(".cl-group-name .muted");
      if (lbl) lbl.textContent = `(${done}/${boxes.length})`;
    });
    root.querySelectorAll(".cl-pane").forEach((p) => {
      const boxes = p.querySelectorAll('.cl-item input[type="checkbox"]');
      const done = [...boxes].filter((b) => b.checked).length;
      const tab = root.querySelector(`.cl-tab[data-cltab="${p.dataset.clpane}"]`);
      if (!tab) return;
      tab.classList.toggle("cl-tab-done", boxes.length > 0 && done === boxes.length);
      const c = tab.querySelector(".cl-tab-count");
      if (c) c.textContent = `${done}/${boxes.length}`;
    });
  }

  function groupChecklistsByRole(checklists) {
    const by = {};
    CL_ROLES.forEach((r) => { by[r.key] = []; });
    (checklists || []).forEach((cl) => {
      (by[checklistRole(cl && cl.name)] || by.misc).push(cl);
    });
    return CL_ROLES.map((r) => ({ ...r, checklists: by[r.key] }));
  }

  // ── Async section: 🗂 In Progress checklist (verbatim port) ────────
  // Every checklist on the card, each collapsible (collapsed by default).
  // Right-click menu for the checklist sections. Add is always offered;
  // Remove only when the click landed on an item.
  function showChecklistCtx(ev, o) {
    document.getElementById("cl-ctx")?.remove();
    const m = document.createElement("div");
    m.id = "cl-ctx";
    m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
      background:var(--surface);border:1px solid var(--border);border-radius:6px;
      box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:300;min-width:220px;padding:4px 0;`;
    const mkBtn = (label, color) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.style.cssText = "display:block;width:100%;text-align:left;"
        + `background:transparent;color:${color};border:0;padding:8px 14px;`
        + "cursor:pointer;font:inherit;font-size:13px;";
      b.addEventListener("mouseenter", () => {
        b.style.background = "var(--row-hover)";
      });
      b.addEventListener("mouseleave", () => { b.style.background = "transparent"; });
      m.appendChild(b);
      return b;
    };

    mkBtn(`+ Add item to "${o.clName || "checklist"}"`, "var(--text)")
      .addEventListener("click", async () => {
        m.remove();
        const name = (prompt(`New item for "${o.clName}":`) || "").trim();
        if (!name) return;                       // cancelled or empty
        setStatus(o.ctx, `Adding "${name}"…`, "info");
        let res;
        try { res = await pywebview.api.add_checklist_item(o.clId, name); }
        catch (ex) { res = { ok: false, error: String(ex) }; }
        if (!res || !res.ok) {
          setStatus(o.ctx, `Add failed: ${(res && res.error) || "?"}`, "error");
          return;
        }
        setStatus(o.ctx, `＋ Added "${name}"`, "ok");
        // The checklist payload is cached 45s, so a plain reload would
        // redraw the list without the item and read as a failed add.
        try { await pywebview.api.invalidate_checklist_cache(); } catch (_) {}
        o.reload();
      });

    if (o.itemId) {
      mkBtn(`✕ Remove "${o.itemName}"`, "var(--red)")
        .addEventListener("click", async () => {
          m.remove();
          if (!confirm(`Remove "${o.itemName}" from the checklist on Trello?`
                       + `\n\nThis deletes it for everyone on the card.`)) return;
          setStatus(o.ctx, `Removing "${o.itemName}"…`, "info");
          let res;
          try {
            res = await pywebview.api.delete_checklist_item(o.clId, o.itemId);
          } catch (ex) { res = { ok: false, error: String(ex) }; }
          if (!res || !res.ok) {
            setStatus(o.ctx, `Remove failed: ${(res && res.error) || "?"}`, "error");
            return;
          }
          setStatus(o.ctx, `✕ Removed "${o.itemName}"`, "ok");
          try { await pywebview.api.invalidate_checklist_cache(); } catch (_) {}
          o.reload();
        });
    }

    document.body.appendChild(m);
    const closer = (e) => {
      if (!m.contains(e.target)) {
        m.remove();
        document.removeEventListener("click", closer);
      }
    };
    setTimeout(() => document.addEventListener("click", closer), 0);
  }

  async function loadAllChecklists(row, ctx) {
    const sec = document.getElementById("all-cl");
    const statusEl = document.getElementById("all-cl-status");
    const bodyEl = document.getElementById("all-cl-body");
    if (!sec || !bodyEl) return;
    let res;
    try { res = await pywebview.api.get_all_checklists(row.client); }
    catch (_) { if (statusEl) statusEl.textContent = "(load failed)"; return; }
    if (document.getElementById("all-cl-body") !== bodyEl) return;
    const cardId = res && res.card_id;
    if (!cardId) { sec.remove(); return; }
    const checklists = (res.ok && res.checklists) || [];
    const total = checklists.reduce((n, cl) => n + (cl.items || []).length, 0);
    const done = checklists.reduce((n, cl) =>
      n + (cl.items || []).filter((i) => i.complete).length, 0);
    if (statusEl) statusEl.textContent = checklists.length ? `(${done}/${total})` : "";

    const groupHtml = (cl) => {
      const items = cl.items || [];
      const cdone = items.filter((i) => i.complete).length;
      const pct = items.length ? Math.round((cdone / items.length) * 100) : 0;
      const full = items.length > 0 && cdone === items.length;
      return `
      <div class="cl-group" data-cl="${escA(ctx, cl.id || "")}"
           data-cl-name="${escA(ctx, cl.name || "")}">
        <div class="cl-group-name" style="cursor:pointer;"
             title="Right-click for add / remove">▾ ${esc(ctx, cl.name)} <span class="muted">(${cdone}/${items.length})</span></div>
        <div class="cl-bar${full ? " cl-bar-done" : ""}"><i style="width:${pct}%;"></i></div>
        <ul class="issue-list cl-items">
          ${items.map((it) => `
            <li class="cl-item" data-item="${escA(ctx, it.id)}"
                data-item-name="${escA(ctx, it.name)}"><label>
              <input type="checkbox" data-id="${escA(ctx, it.id)}" ${it.complete ? "checked" : ""}/>
              <span class="${it.complete ? "cl-done" : ""}">${esc(ctx, it.name)}</span>
            </label></li>`).join("")}
        </ul>
      </div>`;
    };

    // Group the card's checklists by whose job they are. Checklists keep
    // Trello's own order inside each tab — trello_client sorts by `pos`,
    // so this mirrors the board rather than inventing an order.
    const buckets = window.AuditDetail.groupChecklistsByRole(checklists);
    // A tab with nothing behind it is just a dead end. Field has no
    // checklists on the current card template and only appears once a
    // "- FIELD" checklist exists.
    const shown = buckets.filter((b) => b.checklists.length);
    const clHtml = shown.length ? `
      <div class="cl-tabs" role="tablist">
        ${shown.map((b, i) => {
          const its = b.checklists.reduce((n, c) => n + (c.items || []).length, 0);
          const dn = b.checklists.reduce((n, c) =>
            n + (c.items || []).filter((x) => x.complete).length, 0);
          const full = its > 0 && dn === its;
          return `<button class="cl-tab${i === 0 ? " active" : ""}${full ? " cl-tab-done" : ""}"
                    role="tab" data-cltab="${escA(ctx, b.key)}">${esc(ctx, b.label)}<span
                    class="cl-tab-count">${dn}/${its}</span></button>`;
        }).join("")}
      </div>
      ${shown.map((b, i) => `
        <div class="cl-pane" data-clpane="${escA(ctx, b.key)}"${i === 0 ? "" : " hidden"}>
          ${b.checklists.map(groupHtml).join("")}
        </div>`).join("")}` : "";
    // The canned-comment buttons are gone: ticking the checklist item
    // posts the comment now (INITIAL PHOTOS/PHOTO REPORT, INITIAL
    // UPLOAD, ORDER DOCUSKETCH). Two ways to record one fact meant the
    // tick and the comment could disagree, and the comment was the half
    // that got forgotten.
    const cannedHtml = "";
    bodyEl.innerHTML =
      (clHtml || `<div class="muted" style="padding:4px 0 2px;">No checklists on this card.</div>`)
      + cannedHtml;

    bodyEl.querySelectorAll(".cl-group").forEach((g) => {
      const nm = g.querySelector(".cl-group-name");
      if (nm) nm.addEventListener("click", () => {
        g.classList.toggle("cl-collapsed");
        nm.firstChild.nodeValue = g.classList.contains("cl-collapsed") ? "▸ " : "▾ ";
      });
    });
    // Right-click a checklist — add or remove items without opening the
    // card in Trello. On an item both options show; on the title only Add,
    // since there's no item under the cursor to remove.
    bodyEl.addEventListener("contextmenu", (ev) => {
      const group = ev.target.closest && ev.target.closest(".cl-group");
      if (!group || !bodyEl.contains(group)) return;
      const clId = group.dataset.cl || "";
      if (!clId) return;                  // nothing actionable without it
      const li = ev.target.closest(".cl-item");
      ev.preventDefault();
      showChecklistCtx(ev, {
        ctx, clId,
        clName: group.dataset.clName || "",
        itemId: li ? (li.dataset.item || "") : "",
        itemName: li ? (li.dataset.itemName || "") : "",
        reload: () => loadAllChecklists(r, ctx),
      });
    });
    // Role tabs. Remembered per panel so flipping between jobs keeps you
    // on your own tab instead of resetting to the first one every time.
    const tabs = bodyEl.querySelectorAll(".cl-tab");
    const showTab = (key) => {
      let matched = false;
      tabs.forEach((t) => {
        const on = t.dataset.cltab === key;
        t.classList.toggle("active", on);
        if (on) matched = true;
      });
      bodyEl.querySelectorAll(".cl-pane").forEach((p) => {
        p.hidden = p.dataset.clpane !== key;
      });
      return matched;
    };
    if (tabs.length) {
      // The remembered tab may not exist on this card (no Coordinator
      // checklist, say) — fall back to the first rather than showing
      // nothing at all.
      const want = window.AuditDetail._clTab;
      if (!want || !showTab(want)) showTab(tabs[0].dataset.cltab);
      tabs.forEach((t) => t.addEventListener("click", () => {
        window.AuditDetail._clTab = t.dataset.cltab;
        showTab(t.dataset.cltab);
      }));
    }
    // Ticking an item has to move the bar and the tab's count, or the
    // progress you just made is invisible until the next reload. Runs
    // after the per-item handler above has (or hasn't) reverted the box,
    // so it always reflects what actually stuck.
    bodyEl.addEventListener("change", (e) => {
      if (e.target && e.target.matches('.cl-item input[type="checkbox"]')) {
        setTimeout(() => refreshChecklistProgress(bodyEl), 0);
      }
    });
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
        if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
        const span = cb.parentElement.querySelector("span");
        if (span) span.className = want ? "cl-done" : "";
        setStatus(ctx, want ? "Ticked ✓" : "Un-ticked", "ok");
      });
    });
  }

  async function loadInProgressChecklist(row, ctx) {
    const statusEl = document.getElementById("inprog-cl-status");
    const listEl = document.getElementById("inprog-cl-items");
    if (!listEl) return;
    let res;
    try { res = await pywebview.api.get_inprogress_checklist(row.client); }
    catch (ex) { if (statusEl) statusEl.textContent = "(load failed)"; return; }
    const stillHere = document.getElementById("inprog-cl-items");
    if (stillHere !== listEl) return;
    if (!res || !res.ok || !(res.items || []).length) {
      const sec = document.getElementById("inprog-cl");
      if (sec) sec.remove();
      return;
    }
    const cardId = res.card_id;
    if (statusEl) statusEl.textContent = `(${res.items.length})`;
    listEl.innerHTML = res.items.map((it, i) => `
      <li class="cl-item">
        <label>
          <input type="checkbox" data-i="${i}" data-id="${escA(ctx, it.id)}"
                 ${it.complete ? "checked" : ""}/>
          <span class="${it.complete ? "cl-done" : ""}">${esc(ctx, it.name)}</span>
        </label>
      </li>`).join("");
    listEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
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
        if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
        const span = cb.parentElement.querySelector("span");
        if (span) span.className = want ? "cl-done" : "";
        setStatus(ctx, want ? "Ticked ✓" : "Un-ticked", "ok");
      });
    });
  }

  // ── Async section: 📆 Activity comment ────────────────────────────
  // The dated visit comment the office already writes by hand:
  //
  //     Saturday 08/01
  //
  //     Monitor - ME
  //
  // The TEXT is built by the backend (`activity_comment_text`), never
  // here — the preview and the thing that actually gets posted have to
  // be the same string, and a second formatter in JS is how they drift.
  // So the preview is a real round-trip, not a local guess.

  // Local YYYY-MM-DD. `toISOString()` is UTC, which reads as yesterday
  // for anyone west of Greenwich after 4pm — the whole point of this
  // comment is the date, so it can't be off by one.
  function _todayIso() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  function _lastUsed(key, fallback) {
    try { return localStorage.getItem("activityLog." + key) || fallback; }
    catch (_) { return fallback; }
  }
  function _rememberUsed(key, val) {
    try { localStorage.setItem("activityLog." + key, String(val || "")); }
    catch (_) { /* private mode — the picker just won't be sticky */ }
  }

  // ── 📞 Call note ───────────────────────────────────────────────────
  // The timestamped contact note the office already writes by hand:
  //
  //     11:05 8/12/2026
  //     Called Insured to collect email.
  //     LVM
  //
  // The string is built by the backend (`call_note_text`), never here —
  // the preview and the thing that actually posts have to be the same
  // string, and a second formatter in JS is how they drift.
  async function openCallNoteModal(row, ctx) {
    if (!row || !row.trello_card_id) return;
    let phrases = [];
    try {
      const r = await pywebview.api.call_note_phrases();
      phrases = (r && r.phrases) || [];
    } catch (_) { /* chips are a convenience, not a requirement */ }

    mkModal({
      title: "📞 Call note",
      sub: _firstLast(row.display_name || tc(ctx, row.client)),
      width: 560,
      body: `
        <div style="display:flex;gap:8px;align-items:flex-end;margin-bottom:10px;">
          <label style="flex:0 0 110px;font-size:11px;color:var(--text-muted);">
            Time
            <input id="cn-time" class="search" type="text" placeholder="now"
                   style="width:100%;margin-top:3px;" />
          </label>
          <label style="flex:0 0 150px;font-size:11px;color:var(--text-muted);">
            Date
            <input id="cn-date" class="search" type="date"
                   style="width:100%;margin-top:3px;" />
          </label>
          <div style="flex:1;font-size:10.5px;color:var(--text-muted);padding-bottom:6px;">
            Leave blank for right now
          </div>
        </div>
        <label style="font-size:11px;color:var(--text-muted);">What happened
          <textarea id="cn-body" rows="4" class="search"
                    placeholder="Called Insured to collect email."
                    style="width:100%;margin-top:3px;resize:vertical;"></textarea>
        </label>
        ${phrases.length ? `
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:8px;">
            ${phrases.map((p) =>
              `<button class="action-btn cn-chip" type="button"
                       data-p="${escA(ctx, p)}">${esc(ctx, p)}</button>`).join("")}
          </div>` : ""}
        <div style="margin-top:12px;font-size:11px;color:var(--text-muted);">Preview</div>
        <pre id="cn-preview" style="margin:4px 0 0;padding:8px 10px;background:var(--surface-2);
             border-radius:6px;font-size:12px;white-space:pre-wrap;min-height:38px;"></pre>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">
          <span id="cn-msg" style="margin-right:auto;font-size:11.5px;
                color:var(--text-muted);align-self:center;"></span>
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="cn-post">Post to Trello</button>
        </div>`,
    });

    const bodyEl = document.getElementById("cn-body");
    const timeEl = document.getElementById("cn-time");
    const dateEl = document.getElementById("cn-date");
    const prevEl = document.getElementById("cn-preview");
    const msgEl = document.getElementById("cn-msg");

    // Preview is a real round-trip to the builder, so what you read is
    // literally what will be posted.
    let timer = null;
    const refresh = async () => {
      const text = (bodyEl.value || "").trim();
      if (!text) { prevEl.textContent = ""; return; }
      let r;
      try {
        r = await pywebview.api.call_note_text(
          text, timeEl.value || "", dateEl.value || "");
      } catch (e) { return; }
      prevEl.textContent = (r && r.ok) ? r.text : ((r && r.error) || "");
    };
    const queue = () => { clearTimeout(timer); timer = setTimeout(refresh, 150); };
    [bodyEl, timeEl, dateEl].forEach((el) => el.addEventListener("input", queue));

    document.querySelectorAll(".cn-chip").forEach((b) => {
      b.addEventListener("click", () => {
        // Append on its own line — these are usually the outcome ("LVM")
        // sitting under what was attempted.
        const cur = bodyEl.value.replace(/\s+$/, "");
        bodyEl.value = (cur ? cur + "\n" : "") + b.dataset.p;
        bodyEl.focus();
        refresh();
      });
    });

    document.getElementById("cn-post").addEventListener("click", async (ev) => {
      const btn = ev.currentTarget;
      const text = (bodyEl.value || "").trim();
      if (!text) { msgEl.textContent = "Nothing to log yet"; return; }
      btn.disabled = true; msgEl.textContent = "Posting…";
      let r;
      try {
        r = await pywebview.api.post_call_note(
          row.trello_card_id, text, timeEl.value || "", dateEl.value || "");
      } catch (e) { r = { ok: false, error: String(e) }; }
      if (!r || !r.ok) {
        btn.disabled = false;
        msgEl.textContent = "Failed: " + ((r && r.error) || "?");
        return;
      }
      document.getElementById("ad-modal")?.remove();
      setStatus(ctx, "📞 Call note posted", "ok");
    });

    bodyEl.focus();
  }

  // It used to be a permanent collapsible section at the foot of every
  // pinned job, which meant two API calls on every card you looked at for
  // a thing you post occasionally. Now it's a button like every other
  // action, and the same builder fills the modal — `loadActivityLog` only
  // needs `#activity-log` and `#activity-log-body` to exist, so nothing
  // about how the comment is built or posted changed.
  function openActivityCommentModal(row, ctx) {
    if (!row || !row.trello_card_id) return;
    mkModal({
      title: "📆 Activity comment",
      sub: _firstLast(row.display_name || tc(ctx, row.client)),
      width: 560,
      body: `<div id="activity-log">
               <span class="muted" id="activity-log-status"></span>
               <div id="activity-log-body">
                 <div class="muted" style="padding:8px 0;">Loading…</div>
               </div>
             </div>`,
    });
    loadActivityLog(row, ctx);
  }

  async function loadActivityLog(row, ctx) {
    const sec = document.getElementById("activity-log");
    const bodyEl = document.getElementById("activity-log-body");
    if (!sec || !bodyEl) return;
    const cardId = row.trello_card_id || "";
    if (!cardId) { sec.remove(); return; }

    let stages = [], techs = [];
    try {
      const r = await pywebview.api.list_activity_stages();
      stages = (r && r.stages) || [];
    } catch (_) { /* fall through to the empty-stage guard below */ }
    try {
      const r = await pywebview.api.list_techs();
      techs = (r && r.techs) || [];
    } catch (_) { /* tech is optional — the comment is valid without it */ }
    // The card may have been re-rendered while we were awaiting.
    if (document.getElementById("activity-log-body") !== bodyEl) return;
    if (!stages.length) {
      bodyEl.innerHTML =
        `<div class="muted">Couldn't read the stage list.</div>`;
      return;
    }

    const lastStage = _lastUsed("stage", "Monitor");
    const lastTech = _lastUsed("tech", "");
    bodyEl.innerHTML = `
      <div class="activity-row">
        <label class="modal-lbl" for="act-stage">Stage</label>
        <select id="act-stage" class="search">
          ${stages.map((s) => `<option value="${escA(ctx, s)}"${
            s === lastStage ? " selected" : ""}>${esc(ctx, s)}</option>`).join("")}
        </select>
        <label class="modal-lbl" for="act-tech">Tech</label>
        <select id="act-tech" class="search">
          <option value="">(none)</option>
          ${techs.map((t) => `<option value="${escA(ctx, t)}"${
            t === lastTech ? " selected" : ""}>${esc(ctx, t)}</option>`).join("")}
        </select>
        <label class="modal-lbl" for="act-date">Date</label>
        <input type="date" id="act-date" class="search" value="${escA(ctx, _todayIso())}"/>
      </div>
      <pre id="act-preview" class="activity-preview">…</pre>
      <div class="canned-comments">
        <button class="action-btn" id="act-post"
                title="Post this comment to the pinned Trello card">💬 Post to Trello</button>
        <button class="action-btn" id="act-copy"
                title="Copy the comment text instead of posting it">📋 Copy</button>
      </div>`;

    if (!document.getElementById("activity-log-css")) {
      const st = document.createElement("style");
      st.id = "activity-log-css";
      st.textContent =
        "#activity-log .activity-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;}" +
        "#activity-log .activity-row .modal-lbl{margin:0 0 0 4px;}" +
        "#activity-log .activity-row select,#activity-log .activity-row input{" +
        "width:auto;min-width:120px;}" +
        "#activity-log .activity-preview{white-space:pre-wrap;margin:8px 0 6px;" +
        "padding:8px 10px;border:1px solid var(--border);border-radius:6px;" +
        "background:var(--bg,#1b1b1b);font-size:12px;line-height:1.45;}";
      document.head.appendChild(st);
    }

    const stageEl = bodyEl.querySelector("#act-stage");
    const techEl = bodyEl.querySelector("#act-tech");
    const dateEl = bodyEl.querySelector("#act-date");
    const prevEl = bodyEl.querySelector("#act-preview");
    const postEl = bodyEl.querySelector("#act-post");
    const copyEl = bodyEl.querySelector("#act-copy");
    // Dropdowns inside a scrolling detail pane: scrolling with one open
    // otherwise silently changes the value (see the UI-preferences note).
    [stageEl, techEl].forEach((el) => {
      el.addEventListener("wheel", (e) => { e.preventDefault(); }, { passive: false });
    });

    let current = "";
    async function refresh() {
      let r;
      try {
        r = await pywebview.api.activity_comment_text(
          stageEl.value, techEl.value, dateEl.value);
      } catch (_) { r = null; }
      if (document.getElementById("act-preview") !== prevEl) return;
      current = (r && r.ok) ? r.text : "";
      prevEl.textContent = current || `(${(r && r.error) || "couldn't build"})`;
      postEl.disabled = !current;
      copyEl.disabled = !current;
    }
    [stageEl, techEl, dateEl].forEach((el) =>
      el.addEventListener("change", () => {
        _rememberUsed("stage", stageEl.value);
        _rememberUsed("tech", techEl.value);
        refresh();
      }));
    await refresh();

    postEl.addEventListener("click", async () => {
      postEl.disabled = true;
      let r;
      try {
        r = await pywebview.api.post_activity_comment(
          cardId, stageEl.value, techEl.value, dateEl.value);
      } catch (ex) { r = { ok: false, error: String(ex) }; }
      postEl.disabled = false;
      setStatus(ctx, (r && r.ok)
        ? `💬 Posted: ${String(r.text || "").replace(/\n+/g, " · ")}`
        : `Post failed: ${(r && r.error) || "?"}`, (r && r.ok) ? "ok" : "error");
    });
    copyEl.addEventListener("click", async () => {
      const ok = await copyText(ctx, current);
      setStatus(ctx, ok ? "📋 Copied" : "Copy failed", ok ? "ok" : "error");
    });
  }

  // ── Async section: 📥 Initial checklist + canned comments (port) ───
  async function loadInitialChecklists(row, ctx) {
    const sec = document.getElementById("initial-cl");
    const statusEl = document.getElementById("initial-cl-status");
    const bodyEl = document.getElementById("initial-cl-body");
    if (!sec || !bodyEl) return;
    let res;
    try { res = await pywebview.api.get_initial_checklists(row.client); }
    catch (_) { if (statusEl) statusEl.textContent = "(load failed)"; return; }
    if (document.getElementById("initial-cl-body") !== bodyEl) return;
    const cardId = res && res.card_id;
    if (!cardId) { sec.remove(); return; }
    const checklists = (res.ok && res.checklists) || [];
    const total = checklists.reduce((n, cl) => n + (cl.items || []).length, 0);
    if (statusEl) statusEl.textContent = total ? `(${total})` : "";

    const clHtml = checklists.map((cl) => `
      <div class="cl-group">
        <div class="cl-group-name">${esc(ctx, cl.name)}</div>
        <ul class="issue-list">
          ${(cl.items || []).map((it) => `
            <li class="cl-item"><label>
              <input type="checkbox" data-id="${escA(ctx, it.id)}" ${it.complete ? "checked" : ""}/>
              <span class="${it.complete ? "cl-done" : ""}">${esc(ctx, it.name)}</span>
            </label></li>`).join("")}
        </ul>
      </div>`).join("");
    // The canned-comment buttons are gone: ticking the checklist item
    // posts the comment now (INITIAL PHOTOS/PHOTO REPORT, INITIAL
    // UPLOAD, ORDER DOCUSKETCH). Two ways to record one fact meant the
    // tick and the comment could disagree, and the comment was the half
    // that got forgotten.
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
        if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
        const span = cb.parentElement.querySelector("span");
        if (span) span.className = want ? "cl-done" : "";
        setStatus(ctx, want ? "Ticked ✓" : "Un-ticked", "ok");
      });
    });
  }

  // ── Async section: 📋 CLOSE OUT checklist (inline, like the Initial
  //    + In-Progress sections). Left-click toggles, right-click removes
  //    the item from Trello. Backend is single-sourced on audit_web.Api
  //    (Snapshot proxies it). ─────────────────────────────────────────
  async function loadCloseoutChecklist(row, ctx) {
    const statusEl = document.getElementById("closeout-cl-status");
    const listEl = document.getElementById("closeout-cl-items");
    if (!listEl) return;
    let res;
    try {
      res = await pywebview.api.load_closeout_checklist(
        row.client, row.trello_card_id || "");
    } catch (ex) { if (statusEl) statusEl.textContent = "(load failed)"; return; }
    if (document.getElementById("closeout-cl-items") !== listEl) return;
    if (!res || !res.ok) {
      const sec = document.getElementById("closeout-cl");
      if (sec) sec.remove();
      return;
    }
    const cardId = res.card_id;
    const checklistId = res.checklist_id || "";
    const items = res.items || [];
    if (res.missing_checklist || !items.length) {
      if (statusEl) statusEl.textContent = "";
      listEl.innerHTML =
        `<li class="cl-item" style="list-style:none;"><span class="muted">No CLOSE OUT checklist on this card yet — add one named “CLOSE OUT” on Trello.</span></li>`;
      return;
    }
    if (statusEl) statusEl.textContent = `(${items.length})`;
    function render() {
      listEl.innerHTML = items.map((it, i) => {
        if (it.missing) {
          return `<li class="cl-item"><label><span class="muted">❓ ${esc(ctx, it.name)} — add on Trello</span></label></li>`;
        }
        return `<li class="cl-item" data-i="${i}"
                  title="Click to toggle · Right-click to remove from Trello">
          <label>
            <input type="checkbox" data-id="${escA(ctx, it.id)}" ${it.complete ? "checked" : ""}/>
            <span class="${it.complete ? "cl-done" : ""}">${esc(ctx, it.name)}</span>
          </label>
        </li>`;
      }).join("");
      wire();
    }
    function wire() {
      listEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
        cb.addEventListener("change", async () => {
          const li = cb.closest(".cl-item");
          const it = items[+li.dataset.i];
          if (!it || !it.id) return;
          const want = cb.checked;
          cb.disabled = true;
          let ok = false;
          try {
            const r = await pywebview.api.toggle_closeout_item(cardId, it.id, want);
            ok = !!(r && r.ok);
          } catch (_) { ok = false; }
          cb.disabled = false;
          if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
          it.complete = want;
          const span = cb.parentElement.querySelector("span");
          if (span) span.className = want ? "cl-done" : "";
          setStatus(ctx, want ? `☑ ${it.name}` : `☐ Re-opened ${it.name}`, "ok");
        });
      });
      listEl.querySelectorAll(".cl-item[data-i]").forEach((li) => {
        li.addEventListener("contextmenu", async (ev) => {
          ev.preventDefault();
          const it = items[+li.dataset.i];
          if (!it || !it.id) return;
          if (!confirm(`Remove "${it.name}" from the CLOSE OUT checklist on Trello?`)) return;
          const r = await pywebview.api.delete_closeout_item(checklistId, it.id);
          if (!r || !r.ok) { setStatus(ctx, `Remove failed: ${(r && r.error) || "?"}`, "error"); return; }
          const idx = items.indexOf(it);
          if (idx >= 0) items.splice(idx, 1);
          render();
          setStatus(ctx, `✕ Removed "${it.name}"`, "ok");
        });
      });
    }
    render();
  }

  // ── Per-issue "resolved" checkboxes (verbatim port) ────────────────
  async function decorateIssueListsWithCheckboxes(r, ctx) {
    if (!r.form_issues.length && !r.photo_issues.length) return;
    const resolvedMap = await pywebview.api.get_resolved_map(r.client) || {};
    document.querySelectorAll(".issue-list li:not(.cl-item)").forEach((li) => {
      const text = li.textContent.trim();
      if (li.querySelector(".resolved-box")) return;
      const isResolved = !!resolvedMap[text];
      const box = document.createElement("span");
      box.className = "resolved-box" + (isResolved ? " checked" : "");
      box.title = "Mark resolved";
      if (isResolved) li.classList.add("is-resolved");
      box.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const next = !box.classList.contains("checked");
        box.classList.toggle("checked", next);
        li.classList.toggle("is-resolved", next);
        const res = await pywebview.api.toggle_resolved(r.client, text, next);
        if (!res || !res.ok) {
          box.classList.toggle("checked", !next);
          li.classList.toggle("is-resolved", !next);
          setStatus(ctx, `Couldn't persist: ${(res && res.error) || "?"}`, "error");
        } else {
          setStatus(ctx, next ? `✓ Marked resolved: ${text}` : `Re-opened: ${text}`, "ok");
        }
      });
      li.insertBefore(box, li.firstChild);
    });
  }

  // ── Shared modal chrome (pure DOM — same look in both tools) ───────
  // ── ⚙ Job info ───────────────────────────────────────────────────────
  // One editable record per job. Values are merged per FIELD against the
  // Trello card, so a colleague's edit to a different field is kept rather
  // than overwritten. Only fields that actually differ from the card get
  // written back — which is what stops an unchanged value having its
  // hand-typed markdown flattened.

  async function openJobInfoModal(row, ctx) {
    const child = row.subjob_name || row.child_name || "";
    setStatus(ctx, "⚙ Loading job info…", "");
    let sch = null, data = null;
    try {
      sch  = await pywebview.api.job_settings_schema();
      data = await pywebview.api.job_settings_load(row.client, child);
    } catch (ex) {
      setStatus(ctx, "Job info failed: " + ex, "error");
      return;
    }
    if (!data || !data.ok) {
      setStatus(ctx, "Job info: " + ((data && data.error) || "?"), "warn");
      return;
    }
    const fields = (sch && sch.fields) || [];
    const vals = data.values || {};
    const inherited = new Set(data.inherited || []);

    const group = (list) => {
      const bySec = {};
      list.forEach((f) => { (bySec[f.section] = bySec[f.section] || []).push(f); });
      return Object.entries(bySec).map(([sec, fs]) => `
        <div style="margin-bottom:14px;">
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;
                      letter-spacing:.04em;color:var(--text-muted);
                      margin-bottom:6px;">${_escapeHtml(sec)}</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;">
            ${fs.map((f) => {
              // An inherited value comes from the client, not this unit.
              // Showing it plain would read as "this unit says Mercury",
              // and the user couldn't tell what typing here would override.
              const inh = inherited.has(f.id);
              // Suggestions, never a whitelist — a datalist keeps the
              // field free text, so a carrier nobody has seen before
              // still types straight through. `group` shows as the
              // secondary label, which is how a TPA is told apart from
              // an insurer without a second field.
              const listId = f.options?.length ? `ji-list-${f.id}` : "";
              const datalist = listId ? `
                <datalist id="${_escapeAttr(listId)}">
                  ${f.options.map((o) => `<option value="${_escapeAttr(o.value)}"${
                    o.group ? ` label="${_escapeAttr(o.group)}"` : ""}></option>`).join("")}
                </datalist>` : "";
              return `
              <label style="display:block;font-size:11px;color:var(--text-muted);">
                ${_escapeHtml(f.label)}${inh
                  ? ` <span style="font-size:9.5px;opacity:.75;">· from client</span>`
                  : ""}
                <input class="ji-f" data-fid="${_escapeAttr(f.id)}" type="text"
                       value="${_escapeAttr(vals[f.id] || "")}"
                       ${listId ? `list="${_escapeAttr(listId)}"` : ""}
                       style="width:100%;margin-top:3px;background:var(--surface-2);
                              color:${inh ? "var(--text-muted)" : "var(--text)"};
                              border:1px solid ${inh ? "transparent" : "var(--border)"};
                              border-radius:6px;padding:6px 8px;font-size:12.5px;" />
                ${datalist}
              </label>`; }).join("")}
          </div>
        </div>`).join("");
    };

    // A same-field clash is the only thing that needs a human. Shown at the
    // top because it's the one thing you must look at before saving.
    const conflicts = (data.conflicts || []).length ? `
      <div style="margin-bottom:14px;padding:10px 12px;border-radius:8px;
                  border-left:3px solid var(--amber);background:var(--surface-2);">
        <div style="font-size:12px;font-weight:600;margin-bottom:6px;">
          ⚠ Changed here AND on the card since the last sync</div>
        ${data.conflicts.map((c) => `
          <div style="font-size:11.5px;margin-bottom:5px;">
            <b>${_escapeHtml(c.label)}</b> —
            yours <code>${_escapeHtml(c.mine || "(blank)")}</code>,
            card <code>${_escapeHtml(c.theirs || "(blank)")}</code>
            <button class="btn ji-take" data-fid="${_escapeAttr(c.id)}"
                    data-val="${_escapeAttr(c.theirs)}"
                    style="margin-left:6px;">Take the card's</button>
          </div>`).join("")}
      </div>` : "";

    const note = !data.card_id
      ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px;">
           No Trello card linked — this is stored in Linguar Hub only.</div>`
      : (data.error
        ? `<div style="font-size:11px;color:var(--amber);margin-bottom:12px;">
             ${_escapeHtml(data.error)}</div>`
        : "");

    const core = fields.filter((f) => f.core);
    const more = fields.filter((f) => !f.core);
    mkModal({
      title: `⚙ ${_firstLast(row.display_name || row.client)}`
             + (child ? ` / ${child}` : ""),
      sub: child
        ? (inherited.size
            ? `${inherited.size} field${inherited.size === 1 ? "" : "s"} shown from the client — type to override just this one`
            : "Stored in Linguar Hub")
        : (data.card_id ? "Saving updates the Trello card too"
                        : "Stored in Linguar Hub"),
      width: 720,
      body: `
        ${conflicts}${note}
        <div id="ji-names"></div>
        ${group(core)}
        <details style="margin-top:4px;">
          <summary style="cursor:pointer;font-size:11.5px;color:var(--text-muted);">
            More fields (${more.length})</summary>
          <div style="margin-top:10px;">${group(more)}</div>
        </details>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
          <span id="ji-msg" style="margin-right:auto;font-size:11.5px;
                                   color:var(--text-muted);align-self:center;"></span>
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="ji-save">Save</button>
        </div>`,
    });

    document.querySelectorAll(".ji-take").forEach((b) => {
      b.addEventListener("click", () => {
        const inp = document.querySelector(`.ji-f[data-fid="${b.dataset.fid}"]`);
        if (inp) { inp.value = b.dataset.val || ""; inp.focus(); }
        b.closest("div").style.opacity = ".5";
      });
    });

    // Former names, fetched after the modal paints so the rename lookup
    // never delays the fields the user came here to edit. Silent when the
    // job has only ever had one name — which is most of them.
    (async () => {
      let hist = [];
      try {
        const r = await pywebview.api.job_settings_name_history(row.client);
        hist = (r && r.ok && r.history) || [];
      } catch (e) { return; }
      if (!hist.length) return;
      const slot = document.getElementById("ji-names");
      if (!slot) return;   // modal closed while we were fetching
      // Oldest first, so the chain reads the way it happened. Each `from`
      // is a name this job has been filed under at some point.
      const names = hist.map((h) => h.from).filter(Boolean);
      slot.innerHTML = `
        <div style="font-size:11.5px;color:var(--text-muted);
                    margin-bottom:12px;padding:6px 8px;
                    border-left:2px solid var(--border);">
          Previously filed as ${names.map((n) =>
            `<b>${_escapeHtml(n)}</b>`).join(" → ")}
          <span style="opacity:.7;"> → now</span>
        </div>`;
    })();

    document.getElementById("ji-save").addEventListener("click", async () => {
      const out = {};
      document.querySelectorAll(".ji-f").forEach((i) => {
        out[i.dataset.fid] = i.value;
      });
      const msg = document.getElementById("ji-msg");
      msg.textContent = "Saving…";
      let res = null;
      try {
        // card_desc is the description this edit was based on. Passing it
        // back avoids a second fetch and keeps the diff honest.
        res = await pywebview.api.job_settings_save(
          row.client, out, child, data.card_desc || "");
      } catch (ex) {
        msg.textContent = "Failed: " + ex;
        return;
      }
      if (!res || !res.ok) {
        msg.textContent = (res && res.error) || "failed";
        return;
      }
      document.getElementById("ad-modal")?.remove();
      const n = (res.wrote_to_card || []).length;
      // Somebody had changed these on the card since our last sync, and
      // the Hub just overwrote them. The Hub winning is the intended
      // rule — it is the source of truth — but doing it silently is not:
      // you cannot put back what you never knew you replaced.
      const clob = res.clobbered || [];
      if (clob.length) {
        setStatus(ctx,
          `✓ Saved · ⚠ overwrote ${clob.length} field${clob.length === 1 ? "" : "s"} `
          + `changed on the card: ${clob.map((c) => esc(ctx, c.label)).join(", ")}`,
          "warn");
        return;
      }
      setStatus(ctx,
        res.pending_push
          ? `Saved here — ${n} field${n === 1 ? "" : "s"} still to reach Trello`
          : (n ? `✓ Saved · ${n} field${n === 1 ? "" : "s"} updated on the card`
               : "✓ Saved"),
        res.pending_push ? "warn" : "ok");
    });
  }

  function mkModal({ title, sub, body, width }) {
    document.getElementById("ad-modal")?.remove();
    const w = document.createElement("div");
    w.id = "ad-modal";
    w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
    const widthPx = Math.max(320, parseInt(width || 640, 10));
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(${widthPx}px,96vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">${_escapeHtml(title)}</div>
          ${sub ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${_escapeHtml(sub)}</div>` : ""}
        </header>
        <div style="padding:18px 20px;overflow-y:auto;">${body}</div>
      </div>`;
    document.body.appendChild(w);
    // Delegated — see modal.js. Several of these dialogs replace their
    // body once the async content lands, and a Close button wired at
    // creation is gone by then, leaving a button that does nothing.
    w.addEventListener("click", (e) => {
      if (e.target === w) { w.remove(); return; }
      const btn = e.target && e.target.closest
        ? e.target.closest(".modal-close") : null;
      if (btn && w.contains(btn)) w.remove();
    });
    return w;
  }

  function openAddUpdateModal(row, ctx, initialType) {
    if (!row || !row.trello_card_id) {
      setStatus(ctx, "Pin a Trello card first", "warn");
      return;
    }
    const types = [
      ["general", "General comment", "A free-form update posted to the Trello card."],
      ["job_log", "Job log / work performed", "What happened, who was there, and the work date."],
      ["activity", "Site visit / activity", "Stage, technician, date, and a posting preview."],
      ["long_contract", "Long-form contract payment", "Split the balance after the deductible/deposit between the first and final day."],
      ["call", "Call or contact", "A timestamped contact note with reusable phrases."],
      ["note", "Internal reminder / note", "A tracked internal to-do that is not posted as a Trello comment."],
    ];
    const chosen = types.some(t => t[0] === initialType) ? initialType : "general";
    const wrap = mkModal({
      title: "＋ Add update",
      sub: _firstLast(row.display_name || tc(ctx, row.client)),
      width: 590,
      body: `
        <label class="modal-lbl" for="au-type">Update type</label>
        <select id="au-type" class="search" style="width:100%;margin-bottom:12px;">
          ${types.map(t => `<option value="${t[0]}"${t[0] === chosen ? " selected" : ""}>${t[1]}</option>`).join("")}
        </select>
        <div id="au-preview" class="activity-preview"></div>
        <div class="modal-footer">
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="au-continue">Continue</button>
        </div>`,
    });
    const select = wrap.querySelector("#au-type");
    const preview = wrap.querySelector("#au-preview");
    const refresh = () => {
      const found = types.find(t => t[0] === select.value);
      preview.textContent = found ? found[2] : "";
    };
    select.addEventListener("change", refresh);
    refresh();
    wrap.querySelector("#au-continue").addEventListener("click", () => {
      const type = select.value;
      wrap.remove();
      if (type === "job_log") openJobLogModal(row, ctx);
      else if (type === "activity") openActivityCommentModal(row, ctx);
      else if (type === "long_contract") openLongContractModal(row, ctx);
      else if (type === "call") openCallNoteModal(row, ctx);
      else if (type === "note") {
        if (window.openAuditNotes) window.openAuditNotes(row.client);
      } else if (M.openComment) M.openComment(row);
    });
    select.focus();
  }

  function openLongContractModal(row, ctx) {
    if (!row || !row.trello_card_id) return;
    const wrap = mkModal({
      title: "Long-form contract payment",
      sub: _firstLast(row.display_name || tc(ctx, row.client)),
      width: 520,
      body: `
        <div class="activity-row">
          <label class="modal-lbl" for="lf-total">Contract total</label>
          <input id="lf-total" class="search" inputmode="decimal" placeholder="4,928.11" />
          <label class="modal-lbl" for="lf-deposit">Deductible / deposit</label>
          <input id="lf-deposit" class="search" inputmode="decimal" value="1,000.00" />
        </div>
        <label class="modal-lbl" for="lf-preview" style="display:block;margin-top:12px;">Comment — editable before posting</label>
        <textarea id="lf-preview" class="activity-preview" rows="10"
          style="display:block;width:100%;box-sizing:border-box;resize:vertical;"
          placeholder="Enter the contract total above."></textarea>
        <div class="canned-comments">
          <button class="action-btn" id="lf-post" disabled>💬 Post + open XA</button>
          <button class="action-btn" id="lf-copy" disabled>📋 Copy</button>
        </div>`,
    });
    const total = wrap.querySelector("#lf-total");
    const deposit = wrap.querySelector("#lf-deposit");
    const preview = wrap.querySelector("#lf-preview");
    const post = wrap.querySelector("#lf-post");
    const copy = wrap.querySelector("#lf-copy");
    let current = "", timer = 0;
    async function refresh() {
      let r;
      try { r = await pywebview.api.long_form_contract_comment_text(total.value, deposit.value); }
      catch (ex) { r = { ok: false, error: String(ex) }; }
      current = r && r.ok ? r.text : "";
      preview.value = current || ((r && r.error) || "");
      post.disabled = copy.disabled = !current;
    }
    const queue = () => { clearTimeout(timer); timer = setTimeout(refresh, 100); };
    [total, deposit].forEach((el) => el.addEventListener("input", queue));
    preview.addEventListener("input", () => {
      current = preview.value.trim();
      post.disabled = copy.disabled = !current;
    });
    post.addEventListener("click", async () => {
      post.disabled = true;
      let r;
      try { r = await pywebview.api.post_long_form_contract_comment(
        row.trello_card_id, total.value, deposit.value, preview.value); }
      catch (ex) { r = { ok: false, error: String(ex) }; }
      post.disabled = !current;
      if (r && r.ok) {
        const copied = await copyText(ctx, r.text || current);
        wrap.remove();
        setStatus(ctx, `Contract payment posted${copied ? " + copied" : " · copy failed"}${r.xa_opened ? " · XA opened" : " · no XA link on card"}`, copied ? "ok" : "warn");
      } else setStatus(ctx, `Post failed: ${(r && r.error) || "?"}`, "error");
    });
    copy.addEventListener("click", async () => {
      const ok = await copyText(ctx, preview.value.trim());
      setStatus(ctx, ok ? "Contract payment copied" : "Copy failed", ok ? "ok" : "error");
    });
    total.focus();
  }

  async function openCopyJobSummaryModal(row, ctx) {
    let saved;
    try {
      saved = await pywebview.api.job_summary_data(
        row.client, row.trello_card_id || "");
    } catch (ex) { saved = { ok: false, error: String(ex) }; }
    if (!saved || !saved.ok) {
      setStatus(ctx, `Couldn't build summary: ${(saved && saved.error) || "?"}`, "error");
      return;
    }
    const techs = Array.isArray(row.techs) ? row.techs.join(", ") : (row.techs || "");
    const missing = [...(row.form_issues || []), ...(row.photo_issues || [])].join(", ");
    const values = [
      ["job", "Job", saved.job || row.client, true],
      ["carrier", "Carrier", saved.carrier, true],
      ["claim", "Claim #", saved.claim_number, true],
      ["address", "Loss address", saved.address, true],
      ["customer_email", "Customer email", saved.customer_email, false],
      ["adjuster", "Adjuster", [saved.adjuster_name, saved.adjuster_email].filter(Boolean).join(" — "), false],
      ["techs", "Technicians", techs, false],
      ["stage", "Current stage", row.activity || row.stage || "", true],
      ["missing", "Missing", missing, true],
      ["folder", "OD folder", row.path || "", false],
      ["trello", "Trello", saved.trello, false],
      ["companycam", "CompanyCam", saved.companycam, false],
      ["xa", "XactAnalysis", saved.xactanalysis, false],
    ].filter(v => v[2]);
    const wrap = mkModal({
      title: "📋 Copy job summary",
      sub: "Choose what to include. The preview is copied exactly as shown.",
      width: 650,
      body: `
        <div class="summary-options">
          ${values.map(v => `<label><input type="checkbox" data-summary-key="${v[0]}" ${v[3] ? "checked" : ""}> ${esc(ctx, v[1])}</label>`).join("")}
        </div>
        <pre id="job-summary-preview" class="activity-preview"></pre>
        <div class="modal-footer">
          <button class="btn modal-close">Cancel</button>
          <button class="btn btn-primary" id="job-summary-copy" data-track="copy_job_summary_confirm">Copy summary</button>
        </div>`,
    });
    const preview = wrap.querySelector("#job-summary-preview");
    const refresh = () => {
      const selected = new Set(Array.from(wrap.querySelectorAll("[data-summary-key]:checked"))
        .map(el => el.dataset.summaryKey));
      preview.textContent = values.filter(v => selected.has(v[0]))
        .map(v => `${v[1]}: ${v[2]}`).join("\n");
    };
    wrap.querySelectorAll("[data-summary-key]").forEach(el =>
      el.addEventListener("change", refresh));
    refresh();
    wrap.querySelector("#job-summary-copy").addEventListener("click", async () => {
      if (!preview.textContent) {
        setStatus(ctx, "Choose at least one field", "warn"); return;
      }
      const ok = await copyText(ctx, preview.textContent);
      if (ok) wrap.remove();
      setStatus(ctx, ok ? "📋 Job summary copied" : "Copy failed",
                ok ? "ok" : "error");
    });
  }

  // ── ⚖ Merge / delete job ──────────────────────────────────────────
  // Both operations are preview-first. External systems are deliberately
  // out of scope: this manages the Hub's identity graph, never a folder or
  // a Trello/CompanyCam/WorkCenter record.
  async function openManageJobModal(row, ctx) {
    const currentRef = row.display_name || row.client;
    let current = null;
    try { current = await pywebview.api.job_delete_preview(currentRef); }
    catch (ex) { current = { ok: false, error: String(ex) }; }
    if (!current?.ok) {
      setStatus(ctx, `Job management: ${current?.error || "job not found"}`, "warn");
      return;
    }
    const job = current.job || {};
    const key = job.canon_key || "";
    const name = job.display_name || currentRef;
    const countLine = (p) => {
      const t = p || {};
      return `${t.aliases || 0} aliases · ${t.links || 0} links · ${t.children || 0} claims/units`;
    };
    const w = mkModal({
      title: "Merge or delete job",
      sub: name,
      width: 700,
      body: `
        <section style="padding:12px;border:1px solid var(--border);border-radius:8px;">
          <div style="font-weight:650;margin-bottom:3px;">Merge a duplicate into this job</div>
          <div class="muted" style="font-size:11px;margin-bottom:10px;">
            Search for the other job, then choose which name survives.</div>
          <input id="jm-search" class="search" type="text" autocomplete="off"
                 placeholder="Search for the duplicate job" style="width:100%;" />
          <div id="jm-results" style="margin-top:6px;"></div>
          <div id="jm-merge-plan" style="margin-top:10px;"></div>
        </section>
        <details id="jm-delete" style="margin-top:12px;padding:12px;
                 border:1px solid color-mix(in srgb,var(--red) 45%,var(--border));
                 border-radius:8px;">
          <summary style="cursor:pointer;color:var(--red);font-weight:650;">
            Delete this mistaken Hub record</summary>
          <div style="font-size:12px;margin-top:10px;">
            This removes <b>${esc(ctx, name)}</b> from Linguar Hub, including
            ${current.aliases.length} aliases, ${current.links.length} links, and
            ${current.children.length} claims/units.
          </div>
          <div style="margin:9px 0;padding:8px 10px;border-radius:6px;
                      background:color-mix(in srgb,var(--amber,#b7791f) 14%,transparent);
                      font-size:11px;line-height:1.45;">
            OD folders, Trello cards, CompanyCam projects, and WorkCenter jobs
            are not deleted. If one is still active, a later sync may find the job again.
          </div>
          <label style="display:block;font-size:11px;color:var(--text-muted);">
            Type the full job name to confirm</label>
          <input id="jm-delete-confirm" class="search" type="text"
                 placeholder="${escA(ctx, name)}" style="width:100%;margin:5px 0 9px;" />
          <button id="jm-delete-go" class="action-btn" disabled
                  style="border-color:var(--red);color:var(--red);">Delete Hub record</button>
        </details>
        <footer style="display:flex;justify-content:flex-end;margin-top:14px;">
          <button class="action-btn modal-close">Close</button>
        </footer>`,
    });

    const search = w.querySelector("#jm-search");
    const results = w.querySelector("#jm-results");
    const planEl = w.querySelector("#jm-merge-plan");
    let timer = null, other = null;

    async function showMergePlan() {
      if (!other) return;
      planEl.innerHTML = `<div class="muted">Building merge preview…</div>`;
      const keepCurrent = w.querySelector('input[name="jm-keep"]:checked')?.value !== "other";
      const keepKey = keepCurrent ? key : other.canon_key;
      const dropKey = keepCurrent ? other.canon_key : key;
      let p;
      try { p = await pywebview.api.job_merge_preview(keepKey, dropKey); }
      catch (ex) { p = { ok: false, error: String(ex) }; }
      if (!p?.ok) {
        planEl.innerHTML = `<div style="color:var(--red);font-size:12px;">${esc(ctx, p?.error || "Preview failed")}</div>`;
        return;
      }
      const dropName = p.drop.display_name;
      const conflicts = p.conflicts || [];
      const blocked = (p.preview?.department_conflicts || []).length > 0;
      planEl.innerHTML = `
        <div style="padding:9px 10px;background:var(--surface-2);border-radius:6px;font-size:12px;line-height:1.5;">
          <b>${esc(ctx, dropName)}</b> will fold into <b>${esc(ctx, p.keep.display_name)}</b><br/>
          <span class="muted">${esc(ctx, countLine(p.preview?.totals))}</span>
          ${(p.carried || []).length ? `<br/>Fills empty fields: ${esc(ctx, p.carried.join(", "))}` : ""}
          ${conflicts.length ? `<br/><span style="color:var(--amber,#b7791f);">Keeps survivor values where these differ: ${esc(ctx, conflicts.join(", "))}</span>` : ""}
          ${blocked ? `<br/><span style="color:var(--red);">These jobs belong to different departments and cannot be merged.</span>` : ""}
        </div>
        <label style="display:block;font-size:11px;color:var(--text-muted);margin-top:9px;">
          Type the folded job’s full name to confirm</label>
        <input id="jm-merge-confirm" class="search" type="text"
               placeholder="${escA(ctx, dropName)}" style="width:100%;margin:5px 0 9px;" />
        <button id="jm-merge-go" class="action-btn primary" ${blocked ? "disabled" : ""}>Merge jobs</button>`;
      const conf = planEl.querySelector("#jm-merge-confirm");
      const go = planEl.querySelector("#jm-merge-go");
      if (!blocked) {
        conf.addEventListener("input", () => { go.disabled = conf.value.trim() !== dropName; });
        go.disabled = true;
        go.addEventListener("click", async () => {
          go.disabled = true; go.textContent = "Merging…";
          let res;
          try { res = await pywebview.api.job_merge_apply(keepKey, dropKey, conf.value); }
          catch (ex) { res = { ok: false, error: String(ex) }; }
          if (!res?.ok) {
            setStatus(ctx, `Merge failed: ${res?.error || "?"}`, "error");
            go.disabled = false; go.textContent = "Merge jobs"; return;
          }
          w.remove();
          setStatus(ctx, `Merged into ${res.keep_name}${res.undo_id ? " · undo saved" : ""}`, "ok");
          if (ctx.reauditAndRerender) ctx.reauditAndRerender(res.keep_name);
        });
      }
    }

    search.addEventListener("input", () => {
      clearTimeout(timer); other = null; planEl.innerHTML = "";
      const q = search.value.trim();
      if (q.length < 2) { results.innerHTML = ""; return; }
      timer = setTimeout(async () => {
        let res;
        try { res = await pywebview.api.job_admin_suggest(q, key, 8); }
        catch (ex) { res = { ok: false, error: String(ex), rows: [] }; }
        if (!res?.ok) { results.innerHTML = `<div style="color:var(--red);">${esc(ctx, res?.error || "Search failed")}</div>`; return; }
        results.innerHTML = (res.rows || []).map((r, i) => `
          <button class="action-btn jm-result" data-i="${i}" style="width:100%;text-align:left;margin:2px 0;">
            ${esc(ctx, r.display_name)} <span class="muted">${esc(ctx, r.department || "")}</span>
          </button>`).join("") || `<div class="muted" style="font-size:11px;">No other jobs found.</div>`;
        results.querySelectorAll(".jm-result").forEach((b) => b.addEventListener("click", () => {
          other = res.rows[+b.dataset.i];
          results.innerHTML = `
            <div style="font-size:12px;margin:7px 0 5px;">Duplicate: <b>${esc(ctx, other.display_name)}</b></div>
            <label style="display:block;padding:5px 0;"><input type="radio" name="jm-keep" value="current" checked/> Keep <b>${esc(ctx, name)}</b></label>
            <label style="display:block;padding:5px 0;"><input type="radio" name="jm-keep" value="other"/> Keep <b>${esc(ctx, other.display_name)}</b></label>`;
          results.querySelectorAll('input[name="jm-keep"]').forEach((r) => r.addEventListener("change", showMergePlan));
          showMergePlan();
        }));
      }, 250);
    });

    const delConfirm = w.querySelector("#jm-delete-confirm");
    const delGo = w.querySelector("#jm-delete-go");
    delConfirm.addEventListener("input", () => { delGo.disabled = delConfirm.value.trim() !== name; });
    delGo.addEventListener("click", async () => {
      delGo.disabled = true; delGo.textContent = "Deleting…";
      let res;
      try { res = await pywebview.api.job_delete_apply(key, delConfirm.value); }
      catch (ex) { res = { ok: false, error: String(ex) }; }
      if (!res?.ok) {
        setStatus(ctx, `Delete failed: ${res?.error || "?"}`, "error");
        delGo.disabled = false; delGo.textContent = "Delete Hub record"; return;
      }
      w.remove();
      setStatus(ctx, `Deleted ${name} from Linguar Hub${res.undo_id ? " · undo saved" : ""}. External jobs were untouched.`, "ok");
    });
    search.focus();
  }

  // ── ➕ Add claim / unit (shared) ────────────────────────────────────
  //
  // Adopt-first. Work starts in Trello here, so the dialog SHOWS what
  // already exists — the folder on disk, cards that look like this job,
  // a CompanyCam project — before it offers to make anything. A
  // provision-everything flow would create a second card beside the one
  // somebody already made, which is the duplicate-identity problem this
  // whole effort has been unwinding.
  async function openAddChildModal(row, ctx) {
    const w = mkModal({
      title: "Add a claim or unit",
      sub: row.client,
      width: 660,
      body: `
        <label style="display:block;font-size:11px;text-transform:uppercase;
                      letter-spacing:.08em;color:var(--text-muted);">
          Name it as the folder should read</label>
        <input id="ac-name" type="text" spellcheck="false"
               placeholder="Tres Lagos - Unit 6204 - 8.17.26"
               style="width:100%;margin:6px 0 4px;padding:8px 10px;
                      background:var(--surface);color:var(--text);
                      border:1px solid var(--border);border-radius:6px;
                      font-family:ui-monospace,Consolas,monospace;"/>
        <div id="ac-levels" style="font-size:11px;color:var(--text-muted);
                                   min-height:16px;"></div>
        <div id="ac-found" style="margin-top:14px;"></div>
        <footer style="display:flex;gap:8px;justify-content:flex-end;
                       margin-top:18px;">
          <button class="action-btn modal-close">Cancel</button>
          <button class="action-btn" id="ac-go" disabled>Check first…</button>
        </footer>`,
    });

    const nameEl = w.querySelector("#ac-name");
    const levelsEl = w.querySelector("#ac-levels");
    const foundEl = w.querySelector("#ac-found");
    const goEl = w.querySelector("#ac-go");
    let plan = null, timer = null;

    function chosenCard() {
      const el = w.querySelector('input[name="ac-card"]:checked');
      return el && el.value !== "__none__" ? el.value : "";
    }

    async function preview() {
      const name = nameEl.value.trim();
      plan = null;
      goEl.disabled = true;
      if (!name) { levelsEl.textContent = ""; foundEl.innerHTML = ""; return; }
      goEl.textContent = "Checking…";
      let res;
      try {
        res = await pywebview.api.plan_child(row.client, name, "");
      } catch (err) { res = { ok: false, error: String(err) }; }
      if (!res || !res.ok) {
        foundEl.innerHTML =
          `<div style="color:var(--red);font-size:12px;">${
            _escapeHtml((res && res.error) || "Lookup failed")}</div>`;
        goEl.textContent = "Add";
        return;
      }
      plan = res;
      const lv = res.levels || {};
      levelsEl.textContent =
        [lv.property && `property ${lv.property}`,
         lv.unit && `unit ${lv.unit}`,
         lv.claim_date && `date ${lv.claim_date}`]
          .filter(Boolean).join("  ·  ") || "no property/unit/date detected";

      const parts = [];
      if (res.existing_child) {
        parts.push(`<div style="padding:8px 10px;border-radius:6px;
             background:var(--surface-2);border:1px solid var(--amber,#B4562A);
             font-size:12px;margin-bottom:10px;">
             This claim/unit already exists — adding it will UPDATE it,
             not create a second one.</div>`);
      }
      parts.push(`<div style="font-size:12px;margin-bottom:4px;">
          <b>Folder</b> — ${res.folder.exists
            ? "already there, will be adopted"
            : "will be created"}<br/>
          <span style="font-family:ui-monospace,Consolas,monospace;
                       font-size:11px;color:var(--text-muted);">${
            _escapeHtml(res.folder.path)}</span></div>`);

      const cards = res.cards || [];
      parts.push('<div style="font-size:12px;margin-top:12px;"><b>Trello</b>');
      if (!cards.length) {
        parts.push(`<div style="font-size:11px;color:var(--text-muted);">
            No matching card. You can pin one later — a unit often exists
            before its card does.</div>`);
      } else {
        cards.forEach((c, i) => {
          parts.push(`<label style="display:flex;gap:8px;align-items:center;
               padding:5px 0;font-size:12px;cursor:pointer;">
               <input type="radio" name="ac-card" value="${_escapeAttr(c.id)}"
                      ${i === 0 ? "checked" : ""}/>
               <span style="font-family:ui-monospace,Consolas,monospace;
                            font-size:11px;">${_escapeHtml(c.name)}</span>
               <span style="color:var(--text-muted);font-size:10px;">${
                 _escapeHtml(c.board || "")}</span></label>`);
        });
        parts.push(`<label style="display:flex;gap:8px;align-items:center;
             padding:5px 0;font-size:12px;cursor:pointer;">
             <input type="radio" name="ac-card" value="__none__"/>
             <span style="color:var(--text-muted);">None of these</span>
             </label>`);
      }
      parts.push("</div>");

      const proj = res.project;
      parts.push(`<div style="font-size:12px;margin-top:12px;"><b>CompanyCam</b>
        ${proj
          ? `<div style="font-size:11px;color:var(--text-muted);">
               ${_escapeHtml(proj.name)} — will be adopted</div>`
          : `<label style="display:flex;gap:8px;align-items:center;
                 padding:5px 0;font-size:12px;cursor:pointer;">
               <input type="checkbox" id="ac-mkproj"/>
               <span>No project found — create one</span></label>`}
        </div>`);
      foundEl.innerHTML = parts.join("");
      goEl.disabled = false;
      goEl.textContent = res.existing_child ? "Update" : "Add";
    }

    nameEl.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(preview, 350);   // it hits Trello — don't per-key
    });
    nameEl.focus();

    goEl.addEventListener("click", async () => {
      if (!plan) return;
      const name = nameEl.value.trim();
      const mk = w.querySelector("#ac-mkproj");
      goEl.disabled = true;
      goEl.textContent = "Working…";
      let res;
      try {
        res = await pywebview.api.add_child(
          row.client, name, chosenCard(),
          (plan.project && plan.project.id) || "",
          true, !!(mk && mk.checked), "");
      } catch (err) { res = { ok: false, error: String(err) }; }

      // Per-step, always. A child whose folder was made but whose
      // CompanyCam project failed has to SAY so — reporting success
      // because something worked is the half-provisioned lie.
      const steps = (res && res.steps) || {};
      const line = Object.keys(steps).map((k) => {
        const s = steps[k];
        return `${s.ok ? "✓" : "✕"} ${k}${
          s.error ? ` (${s.error})` : s.action ? ` — ${s.action}` : ""}`;
      }).join("   ");
      if (res && res.ok) {
        setStatus(ctx, `➕ ${name}   ${line}`, "ok");
        w.remove();
        if (ctx.reauditAndRerender) ctx.reauditAndRerender(row.client);
      } else {
        goEl.disabled = false;
        goEl.textContent = "Retry";
        foundEl.innerHTML =
          `<div style="color:var(--red);font-size:12px;">${
            _escapeHtml((res && res.error) || "Failed")}<br/>${
            _escapeHtml(line)}</div>` + foundEl.innerHTML;
      }
    });
  }

  // ── 📋 CLOSE OUT checklist modal (shared) ──────────────────────────
  async function openCloseoutModal(row, ctx) {
    const res = await pywebview.api.load_closeout_checklist(
      row.client, row.trello_card_id || "");
    if (!res || !res.ok) {
      setStatus(ctx, `CLOSE OUT failed: ${(res && res.error) || "?"}`, "error");
      return;
    }
    const cardId = res.card_id;
    const checklistId = res.checklist_id || "";
    const items = res.items || [];
    function renderRows() {
      return items.map((it, i) => {
        if (it.missing) {
          return `<div data-i="${i}" class="co-row missing" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--surface-2);border:1px dashed var(--red);border-radius:6px;margin-bottom:4px;">
            <span style="color:var(--red);font-weight:700;font-size:16px;">❓</span>
            <div style="flex:1;">
              <div style="font-weight:600;">${esc(ctx, it.name)}</div>
              <div class="muted" style="font-size:11px;">Missing on the Trello card. Add it back from Trello, then ↻ Refresh.</div>
            </div>
          </div>`;
        }
        const checkChar = it.complete ? "☑" : "☐";
        const color = it.complete ? "var(--green)" : "var(--text-muted)";
        const weight = it.complete ? "600" : "500";
        const bg = it.complete ? "rgba(46,139,87,.08)" : "var(--surface-2)";
        const extraTag = it.extra
          ? `<span style="background:var(--act-monitor);color:#FFF;font-size:9px;font-weight:700;padding:1px 6px;border-radius:3px;text-transform:uppercase;letter-spacing:.04em;">extra</span>`
          : "";
        return `<button class="co-row" data-i="${i}" data-iid="${esc(ctx, it.id)}"
                  title="Click to toggle · Right-click to remove from Trello"
                  style="display:flex;align-items:center;gap:12px;width:100%;
                         padding:10px 14px;background:${bg};border:1px solid var(--border);
                         border-radius:6px;margin-bottom:4px;cursor:pointer;
                         font:inherit;text-align:left;">
          <span style="font-size:18px;color:${color};font-weight:${weight};">${checkChar}</span>
          <span style="flex:1;font-weight:${weight};${it.complete ? "text-decoration:line-through;color:var(--text-muted);" : ""}">${esc(ctx, it.name)}</span>
          ${extraTag}
        </button>`;
      }).join("");
    }
    const otherList = (res.card_checklists || []).filter((n) => n.trim());
    const missingBody = res.missing_checklist
      ? `<div style="background:rgba(192,57,43,.08);border:1px solid var(--red);border-radius:6px;padding:14px 16px;margin-bottom:10px;">
           <div style="color:var(--red);font-weight:700;margin-bottom:6px;">⚠ No CLOSE OUT checklist on this card</div>
           <div class="muted" style="font-size:12px;line-height:1.5;">
             Add a checklist named <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">CLOSE OUT</code> or <code style="background:var(--surface-2);padding:1px 6px;border-radius:3px;">CLOSE OUT - ADMIN</code> on the Trello card, then ↻ Refresh.
           </div>
           ${otherList.length ? `
             <div class="muted" style="font-size:11px;margin-top:10px;">
               <strong>Checklists found on card:</strong> ${otherList.map((n) => `<code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;">${esc(ctx, n)}</code>`).join(" · ")}
             </div>` : ""}
         </div>`
      : "";
    const wrap = mkModal({
      title: "📋 CLOSE OUT — " + (res.card_name || row.client),
      body: `
        ${missingBody}
        <div class="muted" style="font-size:11px;margin-bottom:10px;">
          ${res.missing_checklist ? ""
            : `Checklist: <strong>${esc(ctx, res.checklist_name || "")}</strong> · Click to toggle · Right-click to remove · syncs to Trello`}
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
        b.addEventListener("click", async () => {
          if (!it.id) return;
          const next = !it.complete;
          b.disabled = true;
          const r2 = await pywebview.api.toggle_closeout_item(cardId, it.id, next);
          if (!r2 || !r2.ok) {
            setStatus(ctx, `Toggle failed: ${(r2 && r2.error) || "?"}`, "error");
            b.disabled = false; return;
          }
          it.complete = next;
          wrap.querySelector("#co-list").innerHTML = renderRows();
          wireRows();
          setStatus(ctx, next ? `☑ ${it.name}` : `☐ Re-opened ${it.name}`, "ok");
        });
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
      remove.addEventListener("click", async () => {
        m.remove();
        if (!confirm(`Remove "${it.name}" from the checklist on Trello?\n\nThis can't be undone from here — re-add it from Trello if needed.`)) return;
        btnEl.disabled = true;
        const r2 = await pywebview.api.delete_closeout_item(checklistId, it.id);
        if (!r2 || !r2.ok) {
          setStatus(ctx, `Remove failed: ${(r2 && r2.error) || "?"}`, "error");
          btnEl.disabled = false; return;
        }
        const idx = items.indexOf(it);
        if (idx >= 0) items.splice(idx, 1);
        wrap.querySelector("#co-list").innerHTML = renderRows();
        wireRows();
        setStatus(ctx, `✕ Removed "${it.name}" from Trello`, "ok");
      });
      m.appendChild(remove);
      document.body.appendChild(m);
      const closer = (e) => {
        if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", closer); }
      };
      setTimeout(() => document.addEventListener("click", closer), 0);
    }
    wireRows();
    wrap.querySelector("#co-refresh").addEventListener("click", () => {
      wrap.remove();
      openCloseoutModal(row, ctx);
    });
  }

  // Board filter is remembered per user — the office searches the same
  // few boards all day, and re-ticking them every time is the kind of
  // friction that makes people stop using the filter at all.
  function _loadExcludedBoards() {
    try {
      const raw = localStorage.getItem("pinSearch.excludedBoards");
      return new Set(raw ? JSON.parse(raw) : []);
    } catch (_) { return new Set(); }
  }
  function _saveExcludedBoards(set) {
    try {
      localStorage.setItem("pinSearch.excludedBoards",
                           JSON.stringify([...set]));
    } catch (_) { /* private mode — filter just won't be sticky */ }
  }

  // ── Shared fallbacks for three viewers that used to live only in the
  //    Audit panel. They were reachable from the shared card but only
  //    Audit injected them, so 📎 Attachments, 📁 OD contents and
  //    📖 Job tracker were DEAD BUTTONS in Snapshot. Nothing about them
  //    is audit-specific — they call api methods both windows have — so
  //    they belong here, where neither renderer has to remember to wire
  //    them and the gap cannot come back.

  function defaultOdContents(ctx, row, startPath) {
    if (!startPath) {
      setStatus(ctx, "No OD folder resolved yet — use Find/Change folder first", "warn");
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
          <div style="font-size:14px;font-weight:600;">📁 OD contents · ${esc(ctx, row.client)}</div>
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
      setStatus(ctx, ok ? `📁 Opened ${curPath}` : "Couldn't open folder", ok ? "ok" : "warn");
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
        <button class="od-folder" data-path="${esc(ctx, f.path)}"
          style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:8px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font:inherit;color:var(--text);">
          <span>📁</span><span style="flex:1;">${esc(ctx, f.name)}</span>
          <span class="muted" style="font-size:11px;">Open ↘</span>
        </button>`).join("");
      const filesHtml = files.map((f) => `
        <button class="od-file" data-path="${esc(ctx, f.path)}"
          style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:8px 10px;background:transparent;border:1px solid transparent;border-radius:6px;cursor:pointer;font:inherit;color:var(--text);">
          <span>📄</span><span style="flex:1;">${esc(ctx, f.name)}</span>
          <span class="muted" style="font-size:11px;">${fmtSize(f.size)}</span>
          <span title="${f.cloud_only ? "Online-only (not downloaded)" : "Downloaded to this PC"}" style="font-size:12px;">${f.cloud_only ? "☁" : "✓"}</span>
        </button>`).join("");
      listEl.innerHTML =
        (folders.length ? `<div class="muted" style="font-size:10px;letter-spacing:.05em;">FOLDERS · ${folders.length}</div>${foldersHtml}` : "") +
        (files.length ? `<div class="muted" style="font-size:10px;letter-spacing:.05em;margin-top:8px;">FILES · ${files.length}</div>${filesHtml}` : "");
      listEl.querySelectorAll(".od-folder").forEach((b) =>
        b.addEventListener("click", () => { stack.push(curPath); curPath = b.dataset.path; load(); }));
      // Files open IN the app. Shelling out to the system handler meant
      // leaving the audit to look at one photo, and coming back to a
      // panel that had lost its place.
      listEl.querySelectorAll(".od-file").forEach((b) =>
        b.addEventListener("click", () =>
          openFileViewer(ctx, files.map((f) => f.path), b.dataset.path)));
    }
    load();
  }

  // ── file viewer ─────────────────────────────────────────────────────
  //
  // Renders what it can (images, PDFs, text) and hands everything else to
  // the system handler rather than showing an empty frame. Arrow keys and
  // the on-screen arrows step through the SAME folder listing the user was
  // looking at, so flicking through a day's photos does not mean closing
  // and reopening for each one.
  async function openFileViewer(ctx, paths, startPath) {
    document.getElementById("fv-modal")?.remove();
    let i = Math.max(0, paths.indexOf(startPath));

    const wrap = document.createElement("div");
    wrap.id = "fv-modal";
    wrap.style.cssText = "position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.82);" +
      "display:flex;flex-direction:column;";
    wrap.innerHTML = `
      <header style="display:flex;align-items:center;gap:12px;padding:10px 16px;
                     background:var(--surface);border-bottom:1px solid var(--border);">
        <span id="fv-name" style="font-size:13px;font-weight:600;flex:1;
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
        <span class="muted" id="fv-pos" style="font-size:11px;"></span>
        <button class="btn" id="fv-prev" title="Previous (←)" aria-label="Previous file">‹</button>
        <button class="btn" id="fv-next" title="Next (→)" aria-label="Next file">›</button>
        <button class="btn" id="fv-open" title="Open in the default app">Open ↗</button>
        <button class="btn" id="fv-close" title="Close (Esc)" aria-label="Close file viewer">✕</button>
      </header>
      <div id="fv-body" style="flex:1;display:flex;align-items:center;
           justify-content:center;overflow:auto;padding:14px;"></div>`;
    document.body.appendChild(wrap);

    const body = wrap.querySelector("#fv-body");
    const close = () => { document.removeEventListener("keydown", onKey); wrap.remove(); };
    function onKey(e) {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    }
    document.addEventListener("keydown", onKey);
    wrap.querySelector("#fv-close").addEventListener("click", close);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
    wrap.querySelector("#fv-prev").addEventListener("click", () => step(-1));
    wrap.querySelector("#fv-next").addEventListener("click", () => step(1));
    wrap.querySelector("#fv-open").addEventListener("click", async () => {
      const ok = await pywebview.api.open_file(paths[i]);
      if (!ok) setStatus(ctx, "Couldn't open file", "warn");
    });

    function step(d) {
      if (!paths.length) return;
      i = (i + d + paths.length) % paths.length;
      render();
    }

    async function render() {
      const path = paths[i];
      wrap.querySelector("#fv-name").textContent =
        path.split(/[\/]/).pop() || path;
      wrap.querySelector("#fv-pos").textContent =
        paths.length > 1 ? `${i + 1} / ${paths.length}` : "";
      body.innerHTML = '<div class="muted">Loading…</div>';
      let r;
      try { r = await pywebview.api.file_preview(path); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (!r || !r.ok) {
        body.innerHTML = `<div class="muted">${esc(ctx, (r && r.error) || "Couldn't read that file")}</div>`;
        return;
      }
      if (r.kind === "image") {
        body.innerHTML =
          `<img src="${r.data}" alt="${escA(ctx, r.name)}"
                style="max-width:100%;max-height:100%;object-fit:contain;
                       border-radius:6px;"/>`;
      } else if (r.kind === "pdf") {
        body.innerHTML =
          `<iframe src="${r.data}" title="${escA(ctx, r.name)}"
                   style="width:100%;height:100%;border:none;background:#fff;
                          border-radius:6px;"></iframe>`;
      } else if (r.kind === "text") {
        body.innerHTML =
          `<pre style="width:100%;height:100%;overflow:auto;margin:0;padding:14px;
                       background:var(--surface);border-radius:6px;
                       font:12.5px/1.5 ui-monospace,Consolas,monospace;
                       white-space:pre-wrap;">${esc(ctx, r.text || "")}</pre>`;
      } else {
        // Say WHY there is no preview, and offer the thing that works.
        body.innerHTML =
          `<div style="text-align:center;">
             <div class="muted" style="margin-bottom:10px;">
               ${esc(ctx, r.reason || "No in-app preview for this file type")}</div>
             <button class="btn" id="fv-ext">Open in the default app</button>
           </div>`;
        body.querySelector("#fv-ext").addEventListener("click", async () => {
          const ok = await pywebview.api.open_file(path);
          if (!ok) setStatus(ctx, "Couldn't open file", "warn");
        });
      }
    }
    render();
  }

  function defaultWorkLog(ctx, row) {
    if (!row.client) { setStatus(ctx, "No client on this row", "warn"); return; }
    document.getElementById("worklog-modal")?.remove();
    const wrap = document.createElement("div");
    wrap.id = "worklog-modal";
    wrap.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;";
    wrap.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(600px,94vw);max-height:82vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:14px;font-weight:600;">📖 Job tracker · ${esc(ctx, tc(ctx, row.client))}</div>
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
        setStatus(ctx, "📖 Job tracker saved & opened", "ok");
      } else {
        setStatus(ctx, (r && r.error) || "Couldn't save tracker", "warn");
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
          const who = h.uploader ? `<span style="color:var(--green);">${esc(ctx, h.uploader)}</span>` : '<span class="muted">unknown</span>';
          return `
            <div style="display:flex;gap:10px;align-items:baseline;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:transparent;" title="${esc(ctx, h.file || "")}">
              <span style="min-width:58px;font-variant-numeric:tabular-nums;font-weight:600;font-size:12px;">${esc(ctx, h.date_str || "—")}</span>
              <span style="flex:1;font-size:13px;">${h.is_image ? "📷" : "📎"} ${esc(ctx, h.file || "(file)")}</span>
              <span style="font-size:11px;">⬆ ${who}</span>
            </div>`;
        }
        const techs = (h.techs || []).length
          ? `<span style="font-size:11px;color:var(--act-monitor,#4A9EFF);">👷 ${esc(ctx, h.techs.join(", "))}</span>`
          : "";
        const slot = h.time_slot ? `<span class="muted" style="font-size:10px;">${esc(ctx, h.time_slot)}</span>` : "";
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
              <span style="min-width:52px;font-variant-numeric:tabular-nums;font-weight:600;font-size:12px;">${esc(ctx, h.date_str || "—")}</span>
              <span style="flex:1;font-size:13px;">🔧 ${esc(ctx, h.work || "—")} ${slot}</span>
              ${techs}
            </div>
            ${hasNote ? `<div class="wl-note" style="display:none;font-size:12px;color:var(--text-muted);white-space:pre-wrap;padding:6px 10px 8px 30px;">📝 ${esc(ctx, noteText)}</div>` : ""}
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

  // ── 🗒 Job log comment ─────────────────────────────────────────────
  //     Monday 5/4/26
  //
  //     Contents/Demo - Wendy/Priscilla/Vince
  //
  // Pick what happened and who was there. Leads render as initials and
  // everyone else as their first name — the backend decides that from
  // the roster, so the dialog never has to know who is a lead.
  async function openJobLogModal(row, ctx) {
    const cardId = row.trello_card_id || "";
    if (!cardId) {
      setStatus(ctx, "Pin a Trello card first", "warn");
      openPinModal(row, ctx);
      return;
    }
    const wrap = mkModal({
      title: "🗒 Job log comment",
      sub:   `Client: ${row.client}`,
      body: `<div id="jl-body" class="muted" style="padding:12px 0;">Loading…</div>`,
    });
    let opts;
    try { opts = await pywebview.api.job_log_options(row.client); }
    catch (ex) { opts = { ok: false, error: String(ex) }; }
    const bodyEl = wrap.querySelector("#jl-body");
    if (!bodyEl) return;
    if (!opts || !opts.ok) {
      bodyEl.innerHTML = `<div style="color:var(--red);">${esc(ctx, (opts && opts.error) || "Couldn't load")}</div>`;
      return;
    }
    const acts = opts.activities || [];
    const techs = opts.techs || [];
    const leads = techs.filter((t) => t.lead);
    const today = _todayIso();

    bodyEl.className = "";
    bodyEl.innerHTML = `
      <label class="modal-lbl">What happened</label>
      <div id="jl-acts" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;">
        ${acts.map((a) => `<button type="button" class="action-btn jl-act"
             data-act="${escA(ctx, a)}">${esc(ctx, a)}</button>`).join("")}
        <button type="button" class="action-btn jl-custom-toggle" id="jl-act-custom-toggle"
                aria-expanded="false">＋ Custom…</button>
      </div>
      <div id="jl-act-custom-row" style="display:none;margin:-4px 0 10px;">
        <input id="jl-act-custom" class="search" type="text"
               placeholder="What happened? e.g. Set containment"
               aria-label="Custom job activity" style="width:100%;" />
      </div>
      <label class="modal-lbl">Who was there
        <span class="muted" style="font-weight:400;">— leads show as initials</span></label>
      <div id="jl-techs" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;">
        ${techs.map((t) => `<button type="button" class="action-btn jl-tech${t.on_today ? " on" : ""}"
             data-name="${escA(ctx, t.name)}" title="${t.lead ? "Lead" : "Helper"}${t.on_today ? " · on today's run doc" : ""}"
             >${esc(ctx, t.label)}${t.on_today ? " •" : ""}</button>`).join("")}
        <button type="button" class="action-btn jl-custom-toggle" id="jl-tech-custom-toggle"
                aria-expanded="false">＋ Custom…</button>
      </div>
      <div id="jl-tech-custom-row" style="display:none;margin:-4px 0 10px;">
        <input id="jl-tech-custom" class="search" type="text"
               placeholder="Who was there? Enter a name"
               aria-label="Custom technician name" style="width:100%;" />
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
        <label class="modal-lbl" for="jl-date">Date</label>
        <input type="date" id="jl-date" class="search" style="width:auto;" value="${escA(ctx, today)}"/>
        <label class="modal-lbl" for="jl-lead" title="Adds a second 'Monitor - <lead>' line. Ignored on a Monitor day.">Lead also monitored</label>
        <select id="jl-lead" class="search" style="width:auto;">
          <option value="">— no —</option>
          ${leads.map((t) => `<option value="${escA(ctx, t.name)}">${esc(ctx, t.label)}</option>`).join("")}
        </select>
      </div>
      <pre id="jl-preview" class="activity-preview">…</pre>
      <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn" id="jl-copy">📋 Copy</button>
        <button class="btn btn-primary" id="jl-post">💬 Post to Trello</button>
      </div>`;
    if (!document.getElementById("jl-css")) {
      const st = document.createElement("style");
      st.id = "jl-css";
      st.textContent =
        ".jl-act.on,.jl-tech.on,.jl-custom-toggle.on{background:var(--green);color:#FFF;border-color:var(--green);}";
      document.head.appendChild(st);
    }

    const sel = (q) => Array.from(wrap.querySelectorAll(q));
    const customValue = (id) => (wrap.querySelector(id)?.value || "").trim();
    const chosenActs = () => {
      const picked = sel(".jl-act.on").map((b) => b.dataset.act);
      const custom = customValue("#jl-act-custom");
      return custom ? picked.concat([custom]) : picked;
    };
    const chosenTechs = () => {
      const picked = sel(".jl-tech.on").map((b) => b.dataset.name);
      const custom = customValue("#jl-tech-custom");
      return custom ? picked.concat([custom]) : picked;
    };
    const prev = wrap.querySelector("#jl-preview");
    let current = "";

    async function refresh() {
      const a = chosenActs();
      if (!a.length) {
        current = "";
        prev.textContent = "Pick what happened…";
        return;
      }
      let r;
      try {
        r = await pywebview.api.job_log_comment_text(
          a, chosenTechs(), wrap.querySelector("#jl-date").value,
          wrap.querySelector("#jl-lead").value);
      } catch (_) { r = null; }
      current = (r && r.ok) ? r.text : "";
      prev.textContent = current || `(${(r && r.error) || "couldn't build"})`;
    }
    // Toggle buttons rather than checkboxes: picking three techs is two
    // taps each otherwise, and this is a several-times-a-day job.
    sel(".jl-act, .jl-tech").forEach((b) =>
      b.addEventListener("click", () => { b.classList.toggle("on"); refresh(); }));
    // "Custom…" opens one inline field in the exact section it belongs
    // to. Typing makes the custom choice live immediately in the preview;
    // clearing the field removes it again. Presets stay multi-select.
    [
      ["act", "#jl-act-custom"],
      ["tech", "#jl-tech-custom"],
    ].forEach(([kind, inputSel]) => {
      const toggle = wrap.querySelector(`#jl-${kind}-custom-toggle`);
      const rowEl = wrap.querySelector(`#jl-${kind}-custom-row`);
      const input = wrap.querySelector(inputSel);
      toggle.addEventListener("click", () => {
        rowEl.style.display = "";
        toggle.setAttribute("aria-expanded", "true");
        input.focus();
      });
      input.addEventListener("input", () => {
        toggle.classList.toggle("on", !!input.value.trim());
        refresh();
      });
    });
    ["#jl-date", "#jl-lead"].forEach((q) =>
      wrap.querySelector(q).addEventListener("change", refresh));
    await refresh();

    wrap.querySelector("#jl-copy").addEventListener("click", async () => {
      if (!current) { setStatus(ctx, "Nothing to copy yet", "warn"); return; }
      const ok = await copyText(ctx, current);
      setStatus(ctx, ok ? "📋 Copied" : "Copy failed", ok ? "ok" : "error");
    });
    wrap.querySelector("#jl-post").addEventListener("click", async () => {
      const a = chosenActs();
      if (!a.length) { setStatus(ctx, "Pick what happened first", "warn"); return; }
      const btn = wrap.querySelector("#jl-post");
      btn.disabled = true;
      let r;
      try {
        r = await pywebview.api.post_job_log_comment(
          cardId, a, chosenTechs(), wrap.querySelector("#jl-date").value,
          wrap.querySelector("#jl-lead").value);
      } catch (ex) { r = { ok: false, error: String(ex) }; }
      btn.disabled = false;
      if (r && r.ok) {
        wrap.remove();
        setStatus(ctx, `💬 Posted: ${String(r.text || "").replace(/\n+/g, " · ")}`, "ok");
      } else {
        setStatus(ctx, `Post failed: ${(r && r.error) || "?"}`, "error");
      }
    });
  }

  // ── ✉ Initial Inspection email ────────────────────────────────────
  // Drafted from the tech's notes on the card, edited here, copied, then
  // XactAnalysis opens and the send is logged back to Trello.
  //
  // The TEXT is composed in Python on every change, never assembled in
  // JS. The office sends these sentences to adjusters verbatim on every
  // claim; a second renderer here would eventually word one of them
  // differently from the other, and nobody would notice which was which.
  async function openInitialEmailModal(row, ctx) {
    const cardId = row.trello_card_id || "";
    if (!cardId) {
      setStatus(ctx, "Pin a Trello card first", "warn");
      openPinModal(row, ctx);
      return;
    }
    const wrap = mkModal({
      title: "✉ Initial Inspection email",
      sub:   `Client: ${row.client}`,
      body: `<div id="ie-body" class="muted" style="padding:14px 0;">Reading the card's notes…</div>`,
    });

    let draft;
    try { draft = await pywebview.api.initial_email_draft(row.client, cardId); }
    catch (ex) { draft = { ok: false, error: String(ex) }; }
    const bodyEl = wrap.querySelector("#ie-body");
    if (!bodyEl) return;                       // closed while loading
    if (!draft || !draft.ok) {
      bodyEl.innerHTML = `<div style="color:var(--red);">${esc(ctx, (draft && draft.error) || "Couldn't draft")}</div>`;
      return;
    }

    const opt = (id, label, checked) => `
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;">
        <input type="checkbox" id="${id}" ${checked ? "checked" : ""}/> ${label}
      </label>`;
    bodyEl.className = "";
    bodyEl.innerHTML = `
      ${draft.found_notes ? "" : `<div style="color:var(--amber);font-size:12px;margin-bottom:8px;">
        No initial-inspection notes found on this card — the draft is a blank template.</div>`}
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;">
        <label class="modal-lbl" for="ie-greeting">Greeting</label>
        <select id="ie-greeting" class="search" style="width:auto;">
          <option>Good Morning,</option><option>Good Afternoon,</option>
        </select>
        <label class="modal-lbl" for="ie-sup">Supervisor</label>
        <input id="ie-sup" class="search" style="width:150px;" value="${escA(ctx, draft.supervisor || "")}"/>
        <label class="modal-lbl" for="ie-rate">Equip $/day</label>
        <input id="ie-rate" class="search" style="width:90px;" placeholder="$85.26"/>
        <label class="modal-lbl" for="ie-crews">Crews start</label>
        <input id="ie-crews" class="search" style="width:110px;" placeholder="6/30/26"/>
        <label class="modal-lbl" for="ie-sketch">DocuSketch</label>
        <input id="ie-sketch" class="search" style="width:230px;"
               value="${escA(ctx, draft.docusketch_url || "")}"
               placeholder="https://app.docusketch.com/player/…"/>
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <label class="modal-lbl" for="ie-sla" style="white-space:nowrap;">SLA line</label>
        <input id="ie-sla" class="search" style="flex:1;"
               value="${escA(ctx, draft.default_sla_line || "")}"
               title="Sent as-is on most claims. Replace it with the real figure when you have one — e.g. &quot;1.5 hours of CON LAB will be exceeded&quot;. Only used when Pack out applies."/>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
        ${opt("ie-tl", "TL inventory", true)}
        ${opt("ie-pod", "POD required", false)}
        ${opt("ie-dry", "3-day dry time exceeded", true)}
        ${opt("ie-esl", "ESL exceeded", true)}
        ${opt("ie-cln", "CLN affected areas", false)}
        ${opt("ie-amp", "Anti-microbial", false)}
      </div>
      <div id="ie-missing" class="muted" style="font-size:11px;margin-bottom:4px;"></div>
      <textarea id="ie-text" class="modal-textarea" rows="18"
                style="width:100%;font-family:'Cascadia Mono',Consolas,monospace;font-size:12px;"></textarea>
      <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
        <button class="btn" id="ie-copy">📋 Copy</button>
        <button class="btn btn-primary" id="ie-go">📋 Copy + open XA</button>
      </div>`;

    const ta = wrap.querySelector("#ie-text");
    const missEl = wrap.querySelector("#ie-missing");
    let dirty = false;                          // user typed — stop re-rendering
    ta.addEventListener("input", () => { dirty = true; });

    function currentOpts() {
      const services = [];
      if (wrap.querySelector("#ie-cln").checked) services.push("CLN of the affected areas");
      if (wrap.querySelector("#ie-amp").checked) services.push("Application of Anti-microbial to the affected areas");
      return {
        greeting: wrap.querySelector("#ie-greeting").value,
        supervisor: wrap.querySelector("#ie-sup").value,
        equipment_rate: wrap.querySelector("#ie-rate").value,
        crews_date: wrap.querySelector("#ie-crews").value,
        docusketch_url: wrap.querySelector("#ie-sketch").value,
        sla_text: wrap.querySelector("#ie-sla").value,
        extras: {
          tl_inventory: wrap.querySelector("#ie-tl").checked,
          pod: wrap.querySelector("#ie-pod").checked,
          dry_time_exceeded: wrap.querySelector("#ie-dry").checked,
          esl_exceeded: wrap.querySelector("#ie-esl").checked,
          services,
        },
      };
    }
    function paint(text, placeholders) {
      ta.value = text || "";
      const miss = placeholders || [];
      missEl.innerHTML = miss.length
        ? `⚠ still to fill in: ${miss.map((m) => esc(ctx, m)).join(", ")}`
        : "✓ nothing left bracketed";
      missEl.style.color = miss.length ? "var(--amber)" : "var(--text-muted)";
    }
    async function rerender() {
      if (dirty) return;      // never clobber the operator's own edits
      let r;
      try {
        r = await pywebview.api.compose_initial_email(draft.fields, currentOpts());
      } catch (_) { return; }
      if (r && r.ok) paint(r.text, r.placeholders);
    }
    paint(draft.text, draft.placeholders);
    // The draft came back without the operator's options applied; run
    // once so the checkbox defaults are reflected before they touch it.
    rerender();
    wrap.querySelectorAll("#ie-body input, #ie-body select").forEach((el) => {
      if (el === ta) return;
      el.addEventListener("change", rerender);
      el.addEventListener("input", rerender);
    });

    async function copyAndLog(openXa) {
      const text = ta.value;
      const ok = await copyText(ctx, text);
      if (!ok) { setStatus(ctx, "Copy failed", "error"); return; }
      if (!openXa) { setStatus(ctx, "📋 Copied", "ok"); return; }
      let opened = false;
      try { opened = await pywebview.api.open_xa_link(row.client, cardId); }
      catch (_) { opened = false; }
      // Log only once XA actually opened — that's the point the email is
      // genuinely on its way, and a comment claiming otherwise is worse
      // than no comment.
      if (!opened) {
        setStatus(ctx, "📋 Copied — no XA link on this card, nothing logged", "warn");
        return;
      }
      let res;
      try { res = await pywebview.api.post_initial_email_comment(cardId, "XactAnalysis"); }
      catch (ex) { res = { ok: false, error: String(ex) }; }
      wrap.remove();
      setStatus(ctx, (res && res.ok)
        ? "📋 Copied · XA opened · logged on the card"
        : `📋 Copied · XA opened · log failed: ${(res && res.error) || "?"}`,
        (res && res.ok) ? "ok" : "warn");
    }
    wrap.querySelector("#ie-copy").addEventListener("click", () => copyAndLog(false));
    wrap.querySelector("#ie-go").addEventListener("click", () => copyAndLog(true));
  }

  // ── 📌 Pin Trello card modal (shared — real persisted pin) ─────────
  function openPinModal(row, ctx) {
    const wrap = mkModal({
      title: row.trello_card_id ? "Re-pin Trello card" : "Pin Trello card",
      sub:   `Client: ${row.client}`,
      body: `
        <input id="pin-q" class="search" type="search" autocomplete="off"
               placeholder="🔎 Search Trello cards by name…"
               value="${escA(ctx, row.client)}" style="width:100%;" />
        <div style="margin-top:6px;">
          <button class="action-btn" id="pin-filter-toggle"
                  title="Choose which Trello boards to search">▸ Boards</button>
          <span class="muted" id="pin-filter-summary" style="font-size:11px;margin-left:6px;"></span>
        </div>
        <div id="pin-filter" style="display:none;margin-top:6px;padding:8px 10px;
             border:1px solid var(--border);border-radius:6px;"></div>
        <div id="pin-results" class="target-list" style="margin-top:10px;"></div>
        ${row.trello_card_id ? `
          <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">
            <button class="btn" id="pin-clear">✕ Unpin current card</button>
          </div>` : ""}
        <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:12px;">
          <button class="btn modal-close">Close</button>
        </div>`,
    });
    const q = wrap.querySelector("#pin-q");
    const results = wrap.querySelector("#pin-results");
    const filterBox = wrap.querySelector("#pin-filter");
    const filterBtn = wrap.querySelector("#pin-filter-toggle");
    const filterSum = wrap.querySelector("#pin-filter-summary");
    let timer = null;
    let allBoards = [];      // [{name, tier, active}]
    let excluded = _loadExcludedBoards();

    function selectedBoards() {
      // [] means "everything" — don't send a list the backend would
      // treat as a filter when nothing is actually unticked.
      const on = allBoards.filter((b) => !excluded.has(b.name));
      return on.length === allBoards.length ? [] : on.map((b) => b.name);
    }
    function paintSummary() {
      if (!allBoards.length) { filterSum.textContent = ""; return; }
      const off = allBoards.filter((b) => excluded.has(b.name)).length;
      filterSum.textContent = off ? `${allBoards.length - off} of ${allBoards.length} boards`
                                  : "all boards";
    }
    function paintFilter() {
      const group = (tier, label) => {
        const rows = allBoards.filter((b) => b.tier === tier);
        if (!rows.length) return "";
        return `
          <div style="margin-bottom:6px;">
            <div class="muted" style="font-size:11px;text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:3px;">${label}</div>
            ${rows.map((b) => `
              <label style="display:flex;align-items:center;gap:6px;padding:2px 0;">
                <input type="checkbox" data-board="${escA(ctx, b.name)}"
                       ${excluded.has(b.name) ? "" : "checked"} />
                <span>${esc(ctx, b.name)}</span>
              </label>`).join("")}
          </div>`;
      };
      filterBox.innerHTML =
        group("active", "Active work") +
        group("archive", "Logs &amp; AR") +
        `<div style="margin-top:6px;display:flex;gap:6px;">
           <button class="action-btn" data-preset="active">Active only</button>
           <button class="action-btn" data-preset="all">All</button>
         </div>`;
      filterBox.querySelectorAll("input[data-board]").forEach((cb) =>
        cb.addEventListener("change", () => {
          if (cb.checked) excluded.delete(cb.dataset.board);
          else excluded.add(cb.dataset.board);
          _saveExcludedBoards(excluded);
          paintSummary(); doSearch();
        }));
      filterBox.querySelectorAll("button[data-preset]").forEach((b) =>
        b.addEventListener("click", () => {
          excluded = b.dataset.preset === "active"
            ? new Set(allBoards.filter((x) => x.tier === "archive").map((x) => x.name))
            : new Set();
          _saveExcludedBoards(excluded);
          paintFilter(); paintSummary(); doSearch();
        }));
    }
    filterBtn.addEventListener("click", () => {
      const open = filterBox.style.display !== "none";
      filterBox.style.display = open ? "none" : "block";
      filterBtn.textContent = open ? "▸ Boards" : "▾ Boards";
    });
    (async () => {
      try {
        const r = await pywebview.api.list_search_boards();
        allBoards = (r && r.boards) || [];
      } catch (_) { allBoards = []; }
      // Drop remembered names for boards that no longer exist, or the
      // summary counts a board the user can't see.
      const live = new Set(allBoards.map((b) => b.name));
      [...excluded].forEach((n) => { if (!live.has(n)) excluded.delete(n); });
      paintFilter(); paintSummary();
    })();

    async function doSearch() {
      const text = q.value.trim();
      if (text.length < 2) { results.innerHTML = ""; return; }
      results.innerHTML = `<div class="target-row" style="opacity:.6;padding:6px 10px;">Searching…</div>`;
      const hits = await pywebview.api.search_trello(text, selectedBoards()) || [];
      if (!hits.length) {
        results.innerHTML = `<div class="target-row" style="opacity:.6;padding:6px 10px;">No matches</div>`;
        return;
      }
      // Backend already ordered active-first; mark where archive starts
      // so it reads as two groups rather than one flat list.
      let seenArchive = false;
      results.innerHTML = hits.map((h) => {
        let divider = "";
        if (h.tier === "archive" && !seenArchive) {
          seenArchive = true;
          divider = `<div class="muted" style="font-size:11px;text-transform:uppercase;
                      letter-spacing:.04em;margin:8px 0 4px;">Logs &amp; AR</div>`;
        }
        return divider + `
        <div class="target-row" data-card="${escA(ctx, h.card_id)}"
             style="display:flex;gap:8px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;cursor:pointer;${h.tier === "archive" ? "opacity:.72;" : ""}">
          <span>📌</span>
          <span class="name" style="flex:1;font-weight:600;">${esc(ctx, h.name)}</span>
          <span class="miss muted" style="font-size:11px;">${esc(ctx, h.board || "")}${h.lane ? " · " + esc(ctx, h.lane) : ""}</span>
        </div>`;
      }).join("");
      results.querySelectorAll(".target-row[data-card]").forEach((r2) =>
        r2.addEventListener("click", async () => {
          const res = await pywebview.api.pin_trello(row.client, r2.dataset.card);
          if (!res || !res.ok) { setStatus(ctx, `Pin failed: ${(res && res.error) || "?"}`, "error"); return; }
          row.trello_card_id = res.card_id;
          setStatus(ctx, `📌 Pinned ${row.client}`, "ok");
          wrap.remove();
          if (ctx.rerender) ctx.rerender(row);
          if (ctx.rerenderList) ctx.rerenderList();
        }));
    }
    q.addEventListener("input", () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(doSearch, 220);
    });
    q.focus(); q.select(); doSearch();
    const clearBtn = wrap.querySelector("#pin-clear");
    if (clearBtn) clearBtn.addEventListener("click", async () => {
      await pywebview.api.unpin_trello(row.client);
      row.trello_card_id = "";
      setStatus(ctx, "Unpinned", "ok");
      wrap.remove();
      if (ctx.rerender) ctx.rerender(row);
      if (ctx.rerenderList) ctx.rerenderList();
    });
  }

  // ── 📂 Stage PICS for XA modal (shared) ────────────────────────────
  async function openCopyPicsToXaModal(row, ctx) {
    const info = await pywebview.api.list_pics_stages(row.client);
    if (!info || !info.ok) {
      setStatus(ctx, `Stage list failed: ${(info && info.error) || "no folder pinned"}`, "warn");
      return;
    }
    const stages = info.stages || [];
    if (!stages.length) {
      setStatus(ctx, `No PICS subfolders with images for ${row.client}`, "warn");
      return;
    }
    const wrap = mkModal({
      title: "📂 Stage PICS for XA — " + row.client,
      sub: "Pick a PICS subfolder. Every image is hardlinked into a TEMP folder + Explorer opens on it. Drag the files into XactAnalysis from there. Folder auto-deletes after 1 min.",
      body: `
        <div style="display:flex;flex-direction:column;gap:6px;max-height:50vh;overflow-y:auto;">
          ${stages.map((s) => `
            <button class="action-btn xa-stage" data-stage="${escA(ctx, s.name)}"
                    style="text-align:left;justify-content:flex-start;display:flex;align-items:center;gap:8px;">
              <span style="flex:1;">📁 ${esc(ctx, s.name)}</span>
              <span class="muted" style="font-size:11px;">${s.count} image${s.count !== 1 ? "s" : ""}</span>
            </button>`).join("")}
        </div>
        <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:12px;">
          <button class="btn modal-close">Cancel</button>
        </div>`,
    });
    wrap.querySelectorAll(".xa-stage").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const stage = btn.dataset.stage;
        btn.disabled = true; btn.textContent = "Copying…";
        const res = await pywebview.api.copy_pics_to_clipboard(row.client, stage);
        if (!res || !res.ok) {
          setStatus(ctx, `Copy failed: ${(res && res.error) || "?"}`, "error");
          btn.disabled = false; return;
        }
        wrap.remove();
        const matched = res.matched_stage || stage;
        setStatus(ctx, `📂 Staged ${res.count} image${res.count !== 1 ? "s" : ""} from ${matched} → ${res.folder} · drag into XA · auto-deletes at ${res.deletes_at}`, "ok");
      }));
  }

  // Minimal text escape — this module's `esc` needs a ctx, and the
  // carrier chip is called from render paths that don't carry one.
  function _escText(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Carrier chip ──────────────────────────────────────────────────────
  // Roughly the carriers' own brand colours, so the ones you see all day
  // are recognisable without reading the word — AAA alone is a quarter of
  // the book, Mercury and Farmers most of the rest. Anything not listed
  // gets a stable colour derived from its name, so the long tail (21
  // carriers with one or two jobs each) still reads as distinct rather
  // than collapsing into one grey.
  //
  // These are approximations by eye, not brand assets. Edit freely — one
  // place, and the key is matched loosely so "AAA " / "aaa" both hit.
  const CARRIER_COLORS = {
    "aaa":             "#D0202E",   // red oval
    "mercury":         "#C8102E",
    "farmers":         "#00587C",
    "state farm":      "#E31837",
    "usaa":            "#00305E",
    "allstate":        "#0033A0",
    "liberty mutual":  "#FFD200",
    "american family": "#0C2340",
    "safeco":          "#0072CE",
    "nationwide":      "#00539B",
    "travelers":       "#E01719",
    "lemonade":        "#FF4FA0",
    "the hartford":    "#0A5640",
    "sedgwick":        "#F0B323",   // TPA, not a carrier
    "self pay":        "#2E9E5B",   // no carrier at all — paid direct
  };

  // Stable per-name colour for carriers not in the table, so the same one
  // always looks the same without needing an entry.
  function carrierFallbackColor(key) {
    let h = 0;
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 360;
    return `hsl(${h}, 55%, 42%)`;
  }

  // White text on light chips is unreadable; pick by perceived brightness
  // rather than maintaining a second table of text colours.
  function carrierTextColor(bg) {
    const m = /^#([0-9a-f]{6})$/i.exec(bg || "");
    if (!m) return "#FFFFFF";
    const n = parseInt(m[1], 16);
    const lum = (((n >> 16) & 255) * 299 + ((n >> 8) & 255) * 587
                 + (n & 255) * 114) / 1000;
    return lum > 150 ? "#1A1A1A" : "#FFFFFF";
  }

  // `cls` is the host's chip class — the compact "mini-chip" on a list
  // row, the roomier "detail-chip" in the header. The COLOUR logic is
  // what has to be shared; the sizing belongs to whoever is drawing it.
  function carrierChip(carrier, cls) {
    const raw = (carrier || "").trim();
    if (!raw) return "";                       // unknown — say nothing
    const key = raw.toLowerCase();
    const bg = CARRIER_COLORS[key] || carrierFallbackColor(key);
    const fg = carrierTextColor(bg);
    return `<span class="${cls || "detail-chip"} carrier-chip"
                  style="background:${bg};color:${fg};border-color:${bg};"
                  title="Carrier: ${String(raw).replace(/"/g, '&quot;')}">${_escText(raw)}</span>`;
  }


  // ── 💬 Trello comments drawer ────────────────────────────────────────
  //
  // The Trello section already lists five comments, truncated to 400
  // characters and collapsed inside a <details> — enough to notice a
  // thread exists, useless for reading it, so following a job's running
  // commentary still meant opening the card in a browser.
  //
  // This is the whole thread, docked to the right edge, and it STAYS open
  // as you move between jobs: the point is to read the card while working
  // the audit, and a drawer that closed on every selection would be worse
  // than the browser tab it replaces. Open state and width persist, per
  // the house rule that panels remember where you left them.
  const CMT_OPEN_KEY  = "auditCommentsOpen";
  const CMT_WIDTH_KEY = "auditCommentsWidth";
  const CMT_MIN_W = 260, CMT_MAX_W = 720, CMT_DEF_W = 380;

  function _lsGet(k, dflt) {
    try { const v = localStorage.getItem(k); return v === null ? dflt : v; }
    catch (_) { return dflt; }
  }
  function _lsSet(k, v) { try { localStorage.setItem(k, String(v)); } catch (_) {} }

  function commentsDrawerIsOpen() {
    const el = document.getElementById("cmt-drawer");
    return !!(el && el.classList.contains("cmt-open"));
  }

  function _cmtWidth() {
    const n = parseInt(_lsGet(CMT_WIDTH_KEY, CMT_DEF_W), 10);
    if (!isFinite(n)) return CMT_DEF_W;
    return Math.min(CMT_MAX_W, Math.max(CMT_MIN_W, n));
  }

  function _injectCommentsCss() {
    if (document.getElementById("cmt-drawer-css")) return;
    const st = document.createElement("style");
    st.id = "cmt-drawer-css";
    // Colours are all tokens so the drawer follows the app's theme; a
    // hard-coded background here reads as a foreign window in dark mode.
    st.textContent =
      ".cmt-drawer{position:fixed;top:0;right:0;height:100vh;z-index:9000;" +
      "display:flex;flex-direction:column;background:var(--panel,#1e1e1e);" +
      "border-left:1px solid var(--border,#333);box-shadow:-6px 0 18px rgba(0,0,0,.35);" +
      "transform:translateX(100%);transition:transform .16s ease-out;}" +
      ".cmt-drawer.cmt-open{transform:translateX(0);}" +
      ".cmt-head{display:flex;align-items:center;gap:8px;padding:10px 12px;" +
      "border-bottom:1px solid var(--border,#333);flex:0 0 auto;}" +
      ".cmt-title{font-weight:700;font-size:13px;flex:1 1 auto;overflow:hidden;" +
      "text-overflow:ellipsis;white-space:nowrap;}" +
      ".cmt-sub{font-size:11px;color:var(--text-muted,#999);font-weight:400;}" +
      ".cmt-actions{display:flex;gap:4px;flex:0 0 auto;}" +
      ".cmt-body{flex:1 1 auto;overflow-y:auto;overflow-x:hidden;padding:10px 12px;}" +
      // Gap between messages instead of a hairline: separation is what
      // makes a thread scannable, and a 1px rule reads as one block.
      ".cmt-item{display:flex;gap:9px;padding:0 0 14px;}" +
      ".cmt-av{flex:0 0 auto;width:28px;height:28px;border-radius:50%;" +
      "display:flex;align-items:center;justify-content:center;font-size:10.5px;" +
      "font-weight:700;color:#fff;margin-top:1px;letter-spacing:.02em;}" +
      ".cmt-main{flex:1 1 auto;min-width:0;}" +
      ".cmt-who{display:flex;align-items:baseline;gap:7px;margin-bottom:4px;" +
      "flex-wrap:wrap;}" +
      // The NAME is what the eye looks for, so it gets the readable
      // colour and the weight; the time steps back out of the way.
      ".cmt-name{font-size:12px;font-weight:700;color:var(--text,#eee);}" +
      ".cmt-when{font-size:10.5px;color:var(--text-dim,#888);}" +
      ".cmt-bubble{background:var(--surface,#262626);border:1px solid var(--border,#333);" +
      "border-radius:8px;padding:8px 10px;}" +
      ".cmt-txt{font-size:12px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;" +
      "overflow-wrap:anywhere;}" +
      ".cmt-txt a{color:var(--accent,#4aa3ff);}" +
      // A tagged person is not the person speaking. Undecorated, an
      // @name in the body looked exactly like the author line above it.
      ".cmt-at{background:var(--chip-bg,#33405a);color:var(--accent,#7db9ff);" +
      "border-radius:4px;padding:0 4px;font-weight:600;white-space:nowrap;}" +
      // The drag handle sits ON the left border, hence the negative inset.
      ".cmt-grip{position:absolute;left:-3px;top:0;width:6px;height:100%;" +
      "cursor:col-resize;z-index:1;}" +
      ".cmt-grip:hover{background:var(--accent,#4aa3ff);opacity:.35;}" +
      // The handle hangs OFF the drawer's left edge, so when the
      // drawer is parked off-screen this is the part still showing —
      // tab and panel are one object, not a button that summons one.
      ".cmt-tab{position:absolute;width:30px;padding:14px 0;border:1px solid var(--border,#333);border-right:0;border-radius:8px 0 0 8px;background:var(--surface,#262626);color:var(--text,#eee);font:inherit;font-size:11.5px;font-weight:700;letter-spacing:.04em;cursor:pointer;writing-mode:vertical-rl;text-orientation:mixed;box-shadow:-3px 0 8px rgba(0,0,0,.28);}" +
      ".cmt-tab:hover{background:var(--surface-2,#2e2e2e);color:var(--accent,#4aa3ff);}" +
      ".cmt-empty{color:var(--text-muted,#999);font-size:12px;padding:12px 0;}" +
      // search
      ".cmt-filter{display:flex;align-items:center;gap:8px;padding:6px 12px;" +
      "border-bottom:1px solid var(--border,#333);flex:0 0 auto;}" +
      ".cmt-filter input{flex:1 1 auto;min-width:0;}" +
      ".cmt-hits{font-size:11px;color:var(--text-muted,#999);white-space:nowrap;}" +
      ".cmt-txt mark{background:var(--accent,#4aa3ff);color:#fff;border-radius:2px;}" +
      // attachments
      ".cmt-file{font-size:12px;color:var(--text-muted,#999);margin-bottom:4px;" +
      "word-wrap:break-word;overflow-wrap:anywhere;}" +
      ".cmt-thumb-wrap{min-height:24px;}" +
      ".cmt-thumb{max-width:100%;border-radius:4px;cursor:zoom-in;display:block;" +
      "border:1px solid var(--border,#333);}" +
      ".cmt-lightbox{position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,.85);" +
      "display:flex;align-items:center;justify-content:center;cursor:zoom-out;}" +
      ".cmt-lightbox img{max-width:94vw;max-height:94vh;object-fit:contain;}" +
      ".cmt-lb-msg{color:#eee;font-size:13px;}" +
      // compose
      ".cmt-compose{flex:0 0 auto;border-top:1px solid var(--border,#333);padding:8px 12px;}" +
      ".cmt-compose textarea{width:100%;box-sizing:border-box;resize:vertical;" +
      "font:inherit;font-size:12px;line-height:1.4;padding:6px 8px;border-radius:6px;" +
      "border:1px solid var(--border,#333);background:var(--bg,#151515);" +
      "color:var(--text,#eee);}" +
      ".cmt-btns{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;}" +
      ".cmt-compose{position:relative;}" +
      ".cmt-at-pop{position:absolute;left:12px;right:12px;bottom:100%;margin-bottom:4px;background:var(--surface,#262626);border:1px solid var(--border,#333);border-radius:7px;box-shadow:0 -4px 14px rgba(0,0,0,.4);max-height:190px;overflow-y:auto;z-index:2;}" +
      ".cmt-at-item{padding:6px 10px;font-size:12px;cursor:pointer;}" +
      ".cmt-at-item.on,.cmt-at-item:hover{background:var(--surface-2,#2e2e2e);}" +
      // Snapshot is a working form, so its comments are a true second
      // pane rather than an overlay. Jobs keeps the existing overlay.
      "body.snapshot-panel{transition:padding-right .16s ease-out;}" +
      "body.snapshot-panel.cmt-docked{padding-right:var(--cmt-dock-width,380px);}" +
      "@media(max-width:820px){" +
      "body.snapshot-panel{transition:padding-bottom .16s ease-out;}" +
      "body.snapshot-panel.cmt-docked{padding-right:0;padding-bottom:min(46vh,420px);}" +
      "body.snapshot-panel .cmt-drawer{top:auto;bottom:0;width:100%!important;height:min(46vh,420px);border-left:0;border-top:1px solid var(--border,#333);transform:translateY(100%);}" +
      "body.snapshot-panel .cmt-drawer.cmt-open{transform:translateY(0);}" +
      "body.snapshot-panel .cmt-grip{display:none;}" +
      "body.snapshot-panel .cmt-tab{display:none;}" +
      "}";
    document.head.appendChild(st);
  }

  function _ensureCommentsDrawer() {
    let el = document.getElementById("cmt-drawer");
    if (el) return el;
    _injectCommentsCss();
    el = document.createElement("aside");
    el.id = "cmt-drawer";
    el.className = "cmt-drawer";
    el.style.width = _cmtWidth() + "px";
    el.innerHTML =
      '<button class="cmt-tab" id="cmt-tab" type="button" ' +
      'title="Comment thread for this job">Open Comments</button>' +
      '<div class="cmt-grip" id="cmt-grip" title="Drag to resize"></div>' +
      '<header class="cmt-head">' +
      '  <div class="cmt-title" id="cmt-title">Comments</div>' +
      '  <div class="cmt-actions">' +
      '    <button class="action-btn" id="cmt-refresh" title="Re-read the thread from Trello" aria-label="Refresh Trello thread">↻</button>' +
      '    <button class="action-btn" id="cmt-close" title="Close (Esc)" aria-label="Close comments">✕</button>' +
      '  </div>' +
      '</header>' +
      '<div class="cmt-filter">' +
      '  <input type="search" id="cmt-q" class="search" placeholder="Search this thread…"/>' +
      '  <span class="cmt-hits" id="cmt-hits"></span>' +
      '</div>' +
      '<div class="cmt-body" id="cmt-body"></div>' +
      '<footer class="cmt-compose">' +
      '  <textarea id="cmt-new" rows="2" placeholder="Write a comment…  (Ctrl+Enter posts)"></textarea>' +
      '  <div class="cmt-btns">' +
      '    <button class="action-btn" id="cmt-post" title="Post to the pinned Trello card">💬 Post</button>' +
      '  </div>' +
      '</footer>';
    document.body.appendChild(el);

    el.querySelector("#cmt-close").addEventListener("click", closeCommentsDrawer);
    el.querySelector("#cmt-tab").addEventListener("click", () => {
      const row = el._row, ctx = el._ctx;
      if (commentsDrawerIsOpen()) closeCommentsDrawer();
      else if (row) openCommentsDrawer(row, ctx);
    });

    // Search filters what is already loaded — no round trip per keystroke.
    el.querySelector("#cmt-q").addEventListener("input", () => renderEntries(el));

    // Posting from the drawer. The thread is re-read afterwards rather
    // than optimistically appended: what Trello stored (mention
    // expansion, its own timestamp) is the truth worth showing.
    async function post(text, btn) {
      const row = el._row, ctx = el._ctx;
      if (!row || !(text || "").trim()) return;
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "…";
      try {
        const res = await pywebview.api.post_comment(row.client, text.trim());
        if (res && res.ok) {
          const box = el.querySelector("#cmt-new");
          if (box) box.value = "";
          setStatus(ctx, "💬 Posted to Trello", "ok");
          await loadCommentsInto(row, ctx, false);
        } else {
          setStatus(ctx, `Post failed: ${(res && res.error) || "?"}`, "error");
        }
      } catch (ex) {
        setStatus(ctx, `Post failed: ${ex}`, "error");
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    }
    el.querySelector("#cmt-post").addEventListener("click", (e) =>
      post(el.querySelector("#cmt-new").value, e.currentTarget));
    // The canned IPR / Upload buttons lived here too. Ticking the
    // checklist item posts those phrases now, so the drawer keeps only
    // free-text posting — one place records the fact, one way.
    el.querySelector("#cmt-new").addEventListener("keydown", (e) => {
      if (_mentionKey(el, e)) return;          // the picker owns this key
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        post(e.currentTarget.value, el.querySelector("#cmt-post"));
      }
    });
    // The @ picker is an enhancement; the drawer has to work without it.
    // Unguarded, anything wrong in there takes the whole detail render
    // down with a "Failed to load" and you get no comments at all.
    try { _wireMentions(el); } catch (_) { /* no picker, still a drawer */ }
    el.querySelector("#cmt-refresh").addEventListener("click", async () => {
      const row = el._row, ctx = el._ctx;
      if (!row) return;
      // Drop the 45s server cache too, or ↻ just re-serves what is
      // already on screen and looks broken.
      try { await pywebview.api.invalidate_comments_cache(row.client); } catch (_) {}
      loadCommentsInto(row, ctx, true);
    });

    // Drag-resize from the left edge.
    let dragging = false;
    el.querySelector("#cmt-grip").addEventListener("mousedown", (e) => {
      dragging = true;
      e.preventDefault();
      document.body.style.userSelect = "none";
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const w = Math.min(CMT_MAX_W,
                         Math.max(CMT_MIN_W, window.innerWidth - e.clientX));
      el.style.width = w + "px";
      _syncCommentsDock(el);
    });
    window.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      document.body.style.userSelect = "";
      _lsSet(CMT_WIDTH_KEY, parseInt(el.style.width, 10) || CMT_DEF_W);
    });

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && commentsDrawerIsOpen()) closeCommentsDrawer();
    });
    _placeTab();
    window.addEventListener("resize", _placeTab);
    return el;
  }

  // ── @mention picker for the composer ─────────────────────────────
  //
  // Typing @ offers the people on the card's BOARD. The names are the
  // same ones the XA-note modal already offers (xa_note_members), so a
  // person is spelled one way everywhere — and Trello only notifies on
  // an exact @username, so a typed guess reaches nobody. That is the
  // whole point: a mention that looks right but notifies no one is worse
  // than not tagging at all.
  function _mentionState(el) {
    const box = el.querySelector("#cmt-new");
    if (!box) return null;
    const upto = box.value.slice(0, box.selectionStart);
    const m = /(^|[\s(\[])@([A-Za-z0-9._-]*)$/.exec(upto);
    return m ? { box, start: box.selectionStart - m[2].length - 1,
                 term: m[2].toLowerCase() } : null;
  }

  async function _members(el) {
    const row = el._row;
    if (!row) return [];
    if (el._memberFor === row.client) return el._memberList || [];
    el._memberFor = row.client;
    el._memberList = [];
    try {
      const r = await pywebview.api.xa_note_members(row.client);
      el._memberList = (r && r.members) || [];
    } catch (_) { /* offline — the picker just stays empty */ }
    return el._memberList;
  }

  function _mentionPop(el) {
    let pop = el.querySelector("#cmt-at-pop");
    if (!pop) {
      pop = document.createElement("div");
      pop.id = "cmt-at-pop";
      pop.className = "cmt-at-pop hidden";
      el.querySelector(".cmt-compose").appendChild(pop);
    }
    return pop;
  }

  function _hideMentions(el) {
    const pop = el.querySelector("#cmt-at-pop");
    if (pop) pop.classList.add("hidden");
    el._atRows = null;
  }

  function _insertMention(el, username) {
    const st = _mentionState(el);
    if (!st) return;
    const v = st.box.value;
    const before = v.slice(0, st.start);
    const after = v.slice(st.box.selectionStart);
    st.box.value = `${before}@${username} ${after}`;
    const caret = before.length + username.length + 2;
    st.box.setSelectionRange(caret, caret);
    st.box.focus();
    _hideMentions(el);
  }

  async function _showMentions(el) {
    const st = _mentionState(el);
    if (!st) { _hideMentions(el); return; }
    const all = await _members(el);
    if (!_mentionState(el)) { _hideMentions(el); return; }   // caret moved
    const hits = all.filter((m) =>
      !st.term
      || (m.username || "").toLowerCase().includes(st.term)
      || (m.name || "").toLowerCase().includes(st.term)).slice(0, 8);
    const pop = _mentionPop(el);
    if (!hits.length) { _hideMentions(el); return; }
    el._atRows = hits;
    el._atIndex = 0;
    pop.innerHTML = hits.map((m, i) => `
      <div class="cmt-at-item${i ? "" : " on"}" data-i="${i}">
        <b>@${esc(el._ctx, m.username)}</b>
        <span class="muted"> ${esc(el._ctx, m.name || "")}</span>
      </div>`).join("");
    pop.classList.remove("hidden");
    pop.querySelectorAll(".cmt-at-item").forEach((d) =>
      d.addEventListener("mousedown", (ev) => {
        ev.preventDefault();                 // keep focus in the textarea
        _insertMention(el, hits[+d.dataset.i].username);
      }));
  }

  // Returns true when the picker consumed the key, so the composer's own
  // Ctrl+Enter handler doesn't also fire.
  function _mentionKey(el, e) {
    const rows = el._atRows;
    const pop = el.querySelector("#cmt-at-pop");
    if (!rows || !pop || pop.classList.contains("hidden")) return false;
    if (e.key === "Escape") { _hideMentions(el); e.preventDefault(); return true; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      el._atIndex = (el._atIndex + (e.key === "ArrowDown" ? 1 : rows.length - 1))
        % rows.length;
      pop.querySelectorAll(".cmt-at-item").forEach((d, i) =>
        d.classList.toggle("on", i === el._atIndex));
      return true;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      _insertMention(el, rows[el._atIndex].username);
      return true;
    }
    return false;
  }

  function _wireMentions(el) {
    const box = el.querySelector("#cmt-new");
    if (!box) return;
    box.addEventListener("input", () => _showMentions(el));
    box.addEventListener("blur", () => setTimeout(() => _hideMentions(el), 120));
  }

  // Put the tab clear of the scrollbar and under the panel's top bar.
  // Both are measured, not assumed: a fixed drawer sits at the viewport
  // edge where the scrollbar also lives, and the top bar is a different
  // height in Audit than in Snapshot.
  function _placeTab() {
    const el = document.getElementById("cmt-drawer");
    const tab = document.getElementById("cmt-tab");
    if (!el || !tab) return;
    // Clear of the scrollbar — but the scrollbar in question is usually
    // NOT the document's. Inside the shell's iframe the page itself
    // rarely scrolls; what scrolls is a PANE (the detail pane here, the
    // results list elsewhere), and its scrollbar sits at the same right
    // edge the fixed drawer is pinned to. Measuring only
    // innerWidth-clientWidth gave 0 and the tab sat on top of it.
    let sb = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
    const edge = window.innerWidth;
    for (const node of document.querySelectorAll("main, main > *, .results")) {
      const r = node.getBoundingClientRect();
      if (Math.abs(r.right - edge) >= 40) continue;     // not on this edge
      const w = node.offsetWidth - node.clientWidth;    // classic scrollbar
      if (w > 0 && w <= 40) { sb = Math.max(sb, w); continue; }
      // An OVERLAY scrollbar takes no layout width — offsetWidth equals
      // clientWidth while a bar is still painted over the content. It
      // cannot be measured, only inferred from the pane being
      // scrollable, so assume a normal one rather than sit under it.
      if (node.scrollHeight - node.clientHeight > 2) sb = Math.max(sb, 12);
    }
    // OPEN, the drawer is on screen and covers that scrollbar itself, so
    // the same offset becomes a gap between the tab and the panel — the
    // tab has to hug the drawer's edge to read as one object. CLOSED,
    // the drawer is parked off-screen and the tab is all that shows, so
    // it needs the clearance.
    tab.style.left = commentsDrawerIsOpen() ? "-30px" : `-${30 + sb}px`;
    // Below ALL the chrome, not just the top bar. The audit panel stacks
    // a topbar, a mode row and a toolbar, so anchoring to `.topbar`
    // alone parked the tab on top of the filter chips. The main content
    // element is the honest answer to "where does the page start".
    let top = 0;
    const main = document.querySelector("main");
    if (main) top = main.getBoundingClientRect().top;
    if (!top) {
      for (const sel of [".mode-row", ".audit-toolbar", ".stats-bar",
                         ".topbar", "header"]) {
        for (const node of document.querySelectorAll(sel)) {
          const r = node.getBoundingClientRect();
          if (r.height) top = Math.max(top, r.bottom);
        }
      }
    }
    tab.style.top = `${Math.round(top) + 10}px`;
  }

  function closeCommentsDrawer() {
    const el = document.getElementById("cmt-drawer");
    if (el) el.classList.remove("cmt-open");
    document.body.classList.remove("cmt-docked");
    _lsSet(CMT_OPEN_KEY, "0");
    _setTabLabel(false);
    // The offset differs by state — flush when open, clear of the pane's
    // scrollbar when closed — so closing must re-place it too, or the tab
    // stays hugged to a drawer that is no longer there and lands back on
    // top of the scrollbar.
    _placeTab();
  }

  function openCommentsDrawer(row, ctx) {
    if (!row) return;
    const el = _ensureCommentsDrawer();
    el.classList.add("cmt-open");
    _syncCommentsDock(el);
    _lsSet(CMT_OPEN_KEY, "1");
    _setTabLabel(true);
    _placeTab();
    loadCommentsInto(row, ctx, false);
  }

  function _syncCommentsDock(el) {
    if (!document.body.classList.contains("snapshot-panel")) return;
    const width = Math.min(CMT_MAX_W, Math.max(CMT_MIN_W,
      parseInt(el?.style.width, 10) || _cmtWidth()));
    document.body.style.setProperty("--cmt-dock-width", width + "px");
    document.body.classList.toggle("cmt-docked", !!(el && el.classList.contains("cmt-open")));
  }

  function toggleCommentsDrawer(row, ctx) {
    if (commentsDrawerIsOpen()) closeCommentsDrawer();
    else openCommentsDrawer(row, ctx);
  }

  // Called on every detail render so the open drawer follows the
  // selection instead of showing the last job's thread.
  function syncCommentsDrawer(row, ctx) {
    // Build it even when closed: the TAB is part of the drawer, and the
    // tab is the only way in now that the Trello section is gone.
    const el = _ensureCommentsDrawer();
    el._row = row;
    el._ctx = ctx;
    // Nothing to read without a card, and a tab that opens an empty
    // panel is worse than no tab.
    el.style.display = (row && row.trello_card_id) ? "" : "none";
    _placeTab();          // the top bar's height changes with the toolbar
    if (!commentsDrawerIsOpen()) return;
    if (!row || !row.trello_card_id) {
      closeCommentsDrawer();
      return;
    }
    openCommentsDrawer(row, ctx);
  }

  function _setTabLabel(open) {
    const tab = document.getElementById("cmt-tab");
    if (tab) tab.textContent = open ? "Close Comments" : "Open Comments";
  }

  function _relTime(iso) {
    const t = Date.parse(iso || "");
    if (!isFinite(t)) return "";
    const mins = Math.floor((Date.now() - t) / 60000);
    if (mins < 1)   return "just now";
    if (mins < 60)  return mins + "m ago";
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)   return hrs + "h ago";
    const days = Math.floor(hrs / 24);
    if (days < 30)  return days + "d ago";
    const mos = Math.floor(days / 30);
    return mos < 12 ? mos + "mo ago" : Math.floor(mos / 12) + "y ago";
  }

  function _avatarColor(seed) {
    let h = 0;
    const s = String(seed || "?");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return `hsl(${h}, 45%, 40%)`;
  }

  // Comments are full of pasted links (Workcenter, CompanyCam, DocuSign).
  // Escape FIRST, then linkify, so the text can never inject markup.
  function _linkify(ctx, text) {
    const safe = esc(ctx, text || "");
    return safe.replace(/(https?:\/\/[^\s<]+)/g, (m) => {
      const href = m.replace(/[.,;:)]+$/, "");
      const tail = m.slice(href.length);
      return `<a href="${href}" target="_blank" rel="noreferrer">${href}</a>${tail}`;
    });
  }

  async function loadCommentsInto(row, ctx, forced) {
    const el = _ensureCommentsDrawer();
    el._row = row;
    el._ctx = ctx;
    const body  = document.getElementById("cmt-body");
    const title = document.getElementById("cmt-title");
    if (!body) return;
    const who = tc(ctx, row.display_name || row.client || "");
    if (title) title.innerHTML = `💬 ${esc(ctx, who)}`;
    body.innerHTML = '<div class="cmt-empty">Reading the thread…</div>';
    // Stamp the request so a slow reply for a job you already left can't
    // overwrite the one you are looking at now.
    const token = (el._token = (el._token || 0) + 1);
    let res;
    try {
      res = await pywebview.api.get_card_comments(row.client, 200);
    } catch (ex) {
      res = { ok: false, error: String(ex) };
    }
    if (el._token !== token) return;
    if (!res || !res.ok) {
      const msg = (res && res.error) || "Couldn't read the comments";
      body.innerHTML = `<div class="cmt-empty">${esc(ctx, msg)}</div>`;
      return;
    }
    const list = res.comments || [];
    el._entries = list;
    const nCmt = list.filter((e) => e.kind !== "attachment").length;
    const nAtt = list.length - nCmt;
    if (title) {
      title.innerHTML = `💬 ${esc(ctx, who)} <span class="cmt-sub">${nCmt} comment${
        nCmt === 1 ? "" : "s"}${nAtt ? ` · ${nAtt} file${nAtt === 1 ? "" : "s"}` : ""
        }</span>`;
    }
    renderEntries(el);
    body.scrollTop = 0;
    if (forced) setStatus(ctx, `💬 Reloaded ${nCmt} comment${
      nCmt === 1 ? "" : "s"}`, "ok");
  }

  // Draw whatever survives the search box. Kept separate from the fetch
  // so typing filters instantly instead of re-reading Trello per key.
  function renderEntries(el) {
    const ctx  = el._ctx || {};
    const body = el.querySelector("#cmt-body");
    const hits = el.querySelector("#cmt-hits");
    const all  = el._entries || [];
    const q = ((el.querySelector("#cmt-q") || {}).value || "")
      .trim().toLowerCase();
    const list = !q ? all : all.filter((e) =>
      (e.text || "").toLowerCase().includes(q) ||
      (e.author || "").toLowerCase().includes(q) ||
      (e.name || "").toLowerCase().includes(q) ||
      (e.date || "").includes(q));
    if (hits) {
      hits.textContent = q
        ? `${list.length} of ${all.length}`
        : "";
    }
    if (!body) return;
    if (!all.length) {
      body.innerHTML = '<div class="cmt-empty">Nothing on this card yet.</div>';
      return;
    }
    if (!list.length) {
      body.innerHTML = `<div class="cmt-empty">No match for “${esc(ctx, q)}”.</div>`;
      return;
    }
    body.innerHTML = list.map((c) => {
      const head = `
        <div class="cmt-av" style="background:${_avatarColor(c.author || c.initials)};"
             title="${escA(ctx, c.author || "")}">${esc(ctx, c.initials || "?")}</div>`;
      // Author and timestamp are separate elements, not one muted run:
      // the NAME is what you scan for, so it gets the readable colour
      // and the weight, and the time steps back.
      const meta = `
        <div class="cmt-who">
          <span class="cmt-name">${esc(ctx, c.author || "Someone")}</span>
          <span class="cmt-when">${esc(ctx, _relTime(c.when))}${
            c.date ? ` · ${esc(ctx, c.date)}` : ""}</span>
        </div>`;
      if (c.kind === "attachment") {
        const size = c.bytes ? ` · ${Math.round(c.bytes / 1024)} KB` : "";
        // The <img> has no src: Trello 401s without an OAuth header, so
        // the bytes arrive from comment_image once it scrolls into view.
        const thumb = c.is_image
          ? `<div class="cmt-thumb-wrap"><img class="cmt-thumb" data-att="${
              escA(ctx, c.id)}" alt="${escA(ctx, c.name || "")}"
              title="Click to enlarge"/></div>`
          : "";
        return `
          <div class="cmt-item cmt-att">
            ${head}
            <div class="cmt-main">
              ${meta}
              <div class="cmt-bubble">
                <div class="cmt-file">📎 ${esc(ctx, c.name || "attachment")}${
                  esc(ctx, size)}</div>
                ${thumb}
              </div>
            </div>
          </div>`;
      }
      // The body sits in its own bubble, the way a comment does on the
      // card. Runs of text separated only by a hairline all read as one
      // long block, which is what "hard to tell the messages apart" was.
      return `
        <div class="cmt-item">
          ${head}
          <div class="cmt-main">
            ${meta}
            <div class="cmt-bubble">
              <div class="cmt-txt">${_hilite(ctx, c.text || "", q)}</div>
            </div>
          </div>
        </div>`;
    }).join("");
    _wireThumbs(el);
  }

  // Escape, then linkify, then mark the search term — in that order, so
  // neither the comment nor the query can inject markup.
  // Apply `re` to the TEXT between tags only, never inside one. A
  // replacement landing in an href would corrupt the link, and marking
  // up a class name would corrupt the markup.
  function _inTextNodes(html, re, wrap) {
    return String(html).replace(/(^|>)([^<]+)/g, (m, lead, text) =>
      lead + text.replace(re, wrap));
  }

  // @nathan_bupte is a PERSON being tagged, not the person speaking.
  // Undecorated it sat in the body looking exactly like the author line
  // above it, which is what made a thread hard to read at a glance.
  function _mentions(html) {
    // Whole anchors are stepped over: a URL like ".../c/aB1?x=@y" has an
    // @ in its visible TEXT, and chipping that reads as a person being
    // tagged inside a link.
    return String(html).split(/(<a\b[^>]*>[\s\S]*?<\/a>)/gi)
      .map((part) => /^<a\b/i.test(part) ? part
        // The @ must START a word. These comments are mostly pasted
        // email threads, and "aaron@servpro10100.com" is an address, not
        // a tag — chipping its domain was worse than not chipping at all.
        : _inTextNodes(part, /(^|[\s(\[,;:])@([A-Za-z0-9._-]+)/g,
                       (m, lead, name) =>
                         `${lead}<span class="cmt-at">@${name}</span>`))
      .join("");
  }

  function _hilite(ctx, text, q) {
    const html = _mentions(_linkify(ctx, text));
    if (!q) return html;
    const needle = esc(ctx, q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return _inTextNodes(html, new RegExp(needle, "gi"),
                        (hit) => `<mark>${hit}</mark>`);
  }

  // Thumbnails load as they scroll into view. A photo-heavy card can
  // carry 180+ attachments; fetching them all to draw a list would cost
  // a camera roll per job opened.
  function _wireThumbs(el) {
    const ctx = el._ctx || {};
    const imgs = [...el.querySelectorAll("img.cmt-thumb[data-att]")];
    if (!imgs.length) return;
    const load = async (img) => {
      if (img.dataset.loaded) return;
      img.dataset.loaded = "1";
      const row = el._row;
      if (!row) return;
      try {
        const r = await pywebview.api.comment_image(row.client, img.dataset.att, false);
        if (r && r.ok && r.data_uri) img.src = r.data_uri;
        else img.replaceWith(Object.assign(document.createElement("div"), {
          className: "cmt-empty", textContent: "(preview unavailable)" }));
      } catch (_) { /* a missing thumbnail is not worth an error banner */ }
    };
    if (window.IntersectionObserver) {
      const io = new IntersectionObserver((ents) => {
        ents.forEach((e) => {
          if (e.isIntersecting) { load(e.target); io.unobserve(e.target); }
        });
      }, { root: el.querySelector("#cmt-body"), rootMargin: "200px" });
      imgs.forEach((i) => io.observe(i));
    } else {
      imgs.slice(0, 12).forEach(load);
    }
    imgs.forEach((img) => img.addEventListener("click", () =>
      _openFullImage(el, img.dataset.att, ctx)));
  }

  async function _openFullImage(el, attId, ctx) {
    const row = el._row;
    if (!row) return;
    const over = document.createElement("div");
    over.className = "cmt-lightbox";
    over.innerHTML = '<div class="cmt-lb-msg">Loading…</div>';
    over.addEventListener("click", () => over.remove());
    document.body.appendChild(over);
    const esc2 = (e) => {
      if (e.key === "Escape") { over.remove(); window.removeEventListener("keydown", esc2); }
    };
    window.addEventListener("keydown", esc2);
    try {
      const r = await pywebview.api.comment_image(row.client, attId, true);
      if (!document.body.contains(over)) return;
      if (r && r.ok && r.data_uri) {
        over.innerHTML = `<img src="${r.data_uri}" alt="${escA(ctx, r.name || "")}"/>`;
      } else {
        over.innerHTML = `<div class="cmt-lb-msg">${
          esc(ctx, (r && r.error) || "Couldn't load the image")}</div>`;
      }
    } catch (ex) {
      over.innerHTML = `<div class="cmt-lb-msg">${esc(ctx, String(ex))}</div>`;
    }
  }

  window.AuditDetail = {
    carrierChip,
    openCommentsDrawer,
    closeCommentsDrawer,
    toggleCommentsDrawer,
    syncCommentsDrawer,
    commentsDrawerIsOpen,
    groupChecklistsByRole,
    buildDetailBodyHTML,
    wireDetail,
    detailAction,
    loadTrelloInfo,
    loadActivityLog,
    openActivityCommentModal,
    openAddUpdateModal,
    openCopyJobSummaryModal,
    loadInProgressChecklist,
    loadInitialChecklists,
    loadCloseoutChecklist,
    decorateIssueListsWithCheckboxes,
    mkModal,
    openCloseoutModal,
    openAddChildModal,
    openPinModal,
    openCopyPicsToXaModal,
  };
})();
