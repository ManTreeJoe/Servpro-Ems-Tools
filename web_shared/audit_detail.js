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
  function buildDetailBodyHTML(r, ctx) {
    const techs = (r.techs || []).join(" · ");
    const misplacedForms  = r.misplaced_forms  || [];
    const misplacedPhotos = r.misplaced_photos || [];
    const misplacedCount  = misplacedForms.length + misplacedPhotos.length;
    const chips = [];
    if (r.total_missing > 0) {
      chips.push(`<span class="detail-chip missing">${r.total_missing} missing</span>`);
    } else if (!r.flagged) {
      chips.push(`<span class="detail-chip ok">✓ clean</span>`);
    }
    // Misfiled chip suppressed on multi-unit parents/units — files under a
    // unit subfolder aren't actually misfiled (false positive).
    if (misplacedCount > 0 && !r.subjob && !r.is_parent) {
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
    if ((r.sharepoint_new || 0) > 0) {
      chips.push(`<span class="detail-chip sp-new" style="background:var(--act-monitor);color:#fff;cursor:pointer;" title="Click to import — ${r.sharepoint_new} files on SharePoint not in OneDrive yet">📥 SP +${r.sharepoint_new} new</span>`);
    }
    chips.push(`<span class="detail-chip commercial-chip ${r.is_commercial ? "on" : ""}"
                  data-commercial-client="${escA(ctx, r.client)}"
                  title="Toggle commercial — auto-resolves ATP/CIF/CER/CoS">
                  🏢 ${r.is_commercial ? "Commercial" : "Mark commercial"}
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
    const misplacedSection = misItems.length ? `
      <section class="detail-section">
        <h3>⚠ Misfiled — found in the wrong folder (${misItems.length})</h3>
        <p class="muted" style="margin:2px 0 6px;">Exists under the parent insured, just not in this campus's folder. Move it here.</p>
        <ul class="issue-list misplaced">
          ${misItems.map((m) => `<li>${m.icon} ${esc(ctx, m.label)} <span class="muted">— in <code>${esc(ctx, m.where || "parent")}</code></span></li>`).join("")}
        </ul>
      </section>` : "";

    const cleanSection = (!r.form_issues.length && !r.photo_issues.length
                          && !reqs.length && !misItems.length && r.found) ? `
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
      <footer class="detail-actions">
        <div class="action-row">
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
        </div>
        <div class="action-row">
          <button class="action-btn primary" data-action="job-import"
                  title="Import photos/forms into this job's OD folder (WC zip, DocuSign packet, etc.)">📥 Import</button>
          <button class="action-btn" data-action="sp-import"
                  title="Import matching files from SharePoint into the OD job folder">📥 Import SP</button>
          <button class="action-btn" data-action="cc-pull"
                  ${hasPath ? "" : "disabled"}
                  title="Pull this job's NEW CompanyCam photos into its PICS folder"><img class="btn-icon" src="../web_shared/companycam.png" alt="" onerror="this.remove()"/>Pull CompanyCam</button>
          <button class="action-btn" data-action="attachments"
                  ${hasPin ? "" : "disabled"}
                  title="Browse + download the Trello card's photos/files"><img class="btn-icon" src="../web_shared/trello.png" alt=""/>Trello Attachments</button>
        </div>
        <div class="action-row">
          <button class="action-btn primary" data-action="job-info"
                  title="Carrier, claim number, adjuster, date of loss — edit here and it syncs with the Trello card">⚙ Job info</button>
          <button class="action-btn" data-action="copy-client">📋 Copy name</button>
          <button class="action-btn" data-action="copy-path"
                  title="Copy this job's OD folder path to the clipboard"
                  ${hasPath ? "" : "disabled"}>📋 Copy path</button>
          <button class="action-btn" data-action="copy-claim"
                  title="Copy the claim number from this job's Trello card"
                  ${hasPin ? "" : "disabled"}>📋 Copy claim #</button>
          <button class="action-btn" data-action="copy-email" id="copy-email-btn" disabled
                  title="Copy the customer / adjuster email from this Trello card">📧 Copy email</button>
          <button class="action-btn" data-action="copy-pics"
                  title="Stage every image in a PICS subfolder into a TEMP folder + open it in Explorer — drag into XactAnalysis from there. Auto-deletes after 1 min."
                  ${hasPath ? "" : "disabled"}>📂 Stage for XA…</button>
        </div>
        <div class="action-row">
          <button class="action-btn" data-action="comment" ${hasPin ? "" : "disabled"}>💬 Comment</button>
          <button class="action-btn" data-action="docusketch" ${hasPin ? "" : "disabled"}>📐 Docusketch</button>
          <button class="action-btn" data-action="request-items">📨 Request items</button>
          <button class="action-btn" data-action="add-note" title="Add a tracked to-do note for this job">📝 Note</button>
          ${r.section === "sp_recent" ? `
            <button class="action-btn" data-action="sp-rundoc"
                    title="Open the run-doc for this SP folder's date (parsed from name, e.g. '3-19-26' → 3/19)">📄 Run-doc</button>` : ""}
          <button class="action-btn" type="button" id="detail-more-btn"
                  title="Less-used actions">⋯ More</button>
        </div>
        <div class="action-row detail-more" id="detail-more" style="display:none;">
          <button class="action-btn" data-action="find-folder">${r.found ? "🔀 Change folder" : "🔎 Find folder"}</button>
          <button class="action-btn" data-action="pin-card">📌 ${hasPin ? "Re-pin" : "Pin"} Trello</button>
          <button class="action-btn" data-action="scope"
                  title="Paste a scope block → preview rooms → save Scope.pdf to the job's DOCS folder">📋 Scope</button>
          <button class="action-btn" data-action="xa-prep" title="Xactimate 'new estimate from scratch' prep — carrier price list + copy-paste fields">🧮 Xactimate prep</button>
          <button class="action-btn" data-action="match-diag">🔎 Match diagnostic</button>
          <button class="action-btn" data-action="reaudit">↻ Re-audit</button>
        </div>
      </footer>
      ${hasPin ? `<section class="detail-section" id="trello-info">
        <h3>🎴 Trello <span class="muted" id="trello-info-status">loading…</span></h3>
        <div id="trello-info-body"></div>
      </section>` : ""}
      ${hasPin ? `<section class="detail-section" id="all-cl">
        <h3>✅ Checklists <span class="muted" id="all-cl-status">loading…</span>
          <button class="action-btn" data-action="grab-cat-class"
                  style="float:right;margin-top:-2px;"
                  title="Read the initial-inspection notes in the card's Trello comments and copy the Category + Class">🔢 Cat / Class</button>
          <button class="action-btn" data-action="import-notes"
                  style="float:right;margin:-2px 6px 0 0;"
                  title="Parse the full initial-inspection field template from the card's Trello comments and copy it">📋 Import notes</button>
          <button class="action-btn" data-action="job-log"
                  style="float:right;margin:-2px 6px 0 0;"
                  title="Build a clean dated job log from the card's comments (strips email noise) + flag equipment left on site">🗒 Job log</button>
          <span id="cat-class-out" class="muted" style="float:right;margin:2px 8px 0 0;font-weight:600;"></span></h3>
        <div id="all-cl-body"></div>
      </section>` : ""}
    `;
  }

  // ── Wire the rendered card: buttons, chips, hover, right-click,
  //    then kick off the async sections. `container` is the element the
  //    detail HTML was written into. ──────────────────────────────────
  function wireDetail(container, r, ctx) {
    container.querySelectorAll(".action-btn[data-action]").forEach((b) => {
      b.addEventListener("click", () => detailAction(b.dataset.action, r, ctx));
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
      const onScroll = () => head.classList.toggle("shrunk", (scroller.scrollTop || 0) > 24);
      scroller.addEventListener("scroll", onScroll);
      onScroll();
    }
    const hasPin = !!r.trello_card_id;
    if (hasPin) loadTrelloInfo(r, ctx);
    if (hasPin) loadAllChecklists(r, ctx);   // every checklist on the card
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
      await copyText(ctx, note);                              // for pasting into XA
      let xaOpened = false;
      try { xaOpened = await pywebview.api.open_xa_link(row.client, row.trello_card_id || ""); } catch (e) {}
      try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); }
      setStatus(ctx, `🗒 Posted to Trello + copied${xaOpened ? " · XA opened" : " · no XA link on card"}`, "ok");
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
                   ${STAGES.map((st) => `<option value="${escA(ctx, st)}">${esc(ctx, st)}</option>`).join("")}
                 </select>`}
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
            ${esc(ctx, g.target || "(top level)")}</td>
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
        let res;
        try {
          // Only the ticked shoots, each into the stage chosen for IT.
          res = await pywebview.api.companycam_pull_assigned(
            row.client, assignments(), tech || "", row.trello_card_id || "");
        } catch (e) {
          setStatus(ctx, "CompanyCam pull failed: " + e, "error");
          finish(null); return;
        }
        finish(res);
        if (!res || !res.ok) { setStatus(ctx, "CompanyCam: " + ((res && res.error) || "?"), "warn"); return; }
        const p = res.pulled || 0;
        setStatus(ctx, p ? `✓ Pulled ${p} missing photo${p === 1 ? "" : "s"}` : "Nothing pulled", p ? "ok" : "warn");
        if (ctx.reauditAndRerender) ctx.reauditAndRerender(row.client);
      });
    });
  }

  function ccManualPick(row, ctx, defaultQuery) {
    return new Promise((resolve) => {
      if (!window.openModal) { resolve(null); return; }
      const who = _firstLast(row.display_name || tc(ctx, row.client));
      const overlay = window.openModal({
        title: "📷 Find CompanyCam project — " + who,
        sub: "No auto-match. Search CompanyCam (projects are named by the insured) and pick the right one — it'll be remembered.",
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
            <span style="font-size:11px;color:var(--text-muted);">${c.score != null ? c.score + "%" : ""}</span>
          </div>`).join("");
        listEl.querySelectorAll(".ccp-row").forEach((el) => {
          el.addEventListener("click", async () => {
            const c = cands[+el.dataset.i];
            if (!c || !c.id) return;
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

  async function detailAction(action, row, ctx) {
    const M = (ctx && ctx.modals) || {};
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
      if (window.openAuditNotes) window.openAuditNotes(row.client);
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
      if (M.showOdContents) M.showOdContents(row, row.path || "");
    } else if (action === "work-log") {
      if (M.showWorkLog) M.showWorkLog(row);
    } else if (action === "open-trello") {
      await pywebview.api.open_trello_card(row.trello_card_id);
    } else if (action === "open-xa") {
      // Pass the card_id the row already holds (name re-lookup is fragile).
      const ok = await pywebview.api.open_xa_link(row.client, row.trello_card_id || "");
      if (!ok) setStatus(ctx, "No XactAnalysis link on this card yet — add an 'EMS Xactanalysis Link' line to the Trello card's LINKS section.", "warn");
    } else if (action === "open-companycam") {
      const ok = await pywebview.api.open_companycam_link(row.client);
      if (!ok) setStatus(ctx, "No CompanyCam link on this card yet — add a 'CompanyCam Link' line to the Trello card's LINKS section.", "warn");
    } else if (action === "xa-note") {
      openXaNoteModal(row, ctx);
    } else if (action === "attachments") {
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
      let v;
      try { v = await pywebview.api.companycam_plan_pull(row.client, "", cardId); }
      catch (e) { setStatus(ctx, "CompanyCam check failed: " + e, "error"); return; }
      if (!v || !v.ok) { setStatus(ctx, "CompanyCam: " + ((v && v.error) || "?"), "warn"); return; }
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
    } else if (action === "copy-email") {
      const btn = document.getElementById("copy-email-btn");
      const email = btn ? (btn.dataset.email || "") : "";
      if (!email) { setStatus(ctx, "No email on this card yet", "warn"); return; }
      const ok = await copyText(ctx, email);
      setStatus(ctx, ok ? `📧 Copied ${email}` : "Couldn't copy", ok ? "ok" : "warn");
    } else if (action === "grab-cat-class") {
      setStatus(ctx, "Reading initial notes from Trello comments…", "info");
      const res = await pywebview.api.get_initial_cat_class(
        row.client, row.trello_card_id || "");
      const out = document.getElementById("cat-class-out");
      if (res && res.ok && res.text) {
        if (out) out.textContent = res.text;
        const ok = await copyText(ctx, res.text);
        setStatus(ctx, ok ? `🔢 ${res.text} — copied` : `🔢 ${res.text}`, "ok");
      } else {
        if (out) out.textContent = "";
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
    } else if (action === "find-folder") {
      if (M.openFindFolder) M.openFindFolder(row);
    } else if (action === "pin-card") {
      openPinModal(row, ctx);                     // shared — real persisted pin
    } else if (action === "comment") {
      if (M.openComment) M.openComment(row);
    } else if (action === "docusketch") {
      const res = await pywebview.api.request_docusketch(
        row.client, row.trello_card_id || "");
      setStatus(ctx, (res && res.ok) ? "📐 Docusketch requested" :
        `Docusketch failed: ${(res && res.error) || "?"}`, (res && res.ok) ? "ok" : "error");
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
  async function loadTrelloInfo(row, ctx) {
    const statusEl = document.getElementById("trello-info-status");
    const bodyEl = document.getElementById("trello-info-body");
    if (!bodyEl) return;
    let r;
    try { r = await pywebview.api.trello_enrichment(row.client, row.trello_card_id || ""); }
    catch (e) { if (statusEl) statusEl.textContent = "error"; return; }
    const still = document.getElementById("trello-info-body");
    if (!still || still !== bodyEl) return;
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
    const emails = [];
    if (r.customer_email) emails.push(["Customer", r.customer_email]);
    if (r.adjuster_email) emails.push(["Adjuster", r.adjuster_email]);
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
    bodyEl.innerHTML = html;
    // Email now lives on the footer's 📧 Copy email button (next to the
    // other copy buttons). Enable it + stash the address once known.
    const email = r.customer_email || r.adjuster_email || "";
    const emailBtn = document.getElementById("copy-email-btn");
    if (emailBtn && email) {
      emailBtn.disabled = false;
      emailBtn.dataset.email = email;
    }
    bodyEl.querySelectorAll(".tr-email").forEach((a) =>
      a.addEventListener("click", async (e) => {
        e.preventDefault();
        const ok = await copyText(ctx, a.dataset.email);
        setStatus(ctx, ok ? `📧 Copied ${a.dataset.email}` : "Couldn't copy", ok ? "ok" : "warn");
      }));
  }

  // ── Async section: 🗂 In Progress checklist (verbatim port) ────────
  // Every checklist on the card, each collapsible (collapsed by default).
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

    const clHtml = checklists.map((cl) => {
      const items = cl.items || [];
      const cdone = items.filter((i) => i.complete).length;
      return `
      <div class="cl-group cl-collapsed">
        <div class="cl-group-name" style="cursor:pointer;">▸ ${esc(ctx, cl.name)} <span class="muted">(${cdone}/${items.length})</span></div>
        <ul class="issue-list cl-items">
          ${items.map((it) => `
            <li class="cl-item"><label>
              <input type="checkbox" data-id="${escA(ctx, it.id)}" ${it.complete ? "checked" : ""}/>
              <span class="${it.complete ? "cl-done" : ""}">${esc(ctx, it.name)}</span>
            </label></li>`).join("")}
        </ul>
      </div>`;
    }).join("");
    const cannedHtml = `
      <div class="canned-comments">
        <button class="action-btn" data-canned="ipr"
                title="Post comment: Initial Photo Report Created and Uploaded to OD.">📷 IPR → comment</button>
        <button class="action-btn" data-canned="upload"
                title="Post comment: Initial Upload submitted To WC.">📤 Initial Upload → comment</button>
      </div>`;
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
    bodyEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener("change", async () => {
        const itemId = cb.dataset.id;
        const want = cb.checked;
        cb.disabled = true;
        let ok = false;
        try {
          const r = await pywebview.api.toggle_checklist_item(cardId, itemId, want);
          ok = !!(r && r.ok);
        } catch (_) { ok = false; }
        cb.disabled = false;
        if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
        const span = cb.parentElement.querySelector("span");
        if (span) span.className = want ? "cl-done" : "";
        setStatus(ctx, want ? "Ticked ✓" : "Un-ticked", "ok");
      });
    });
    bodyEl.querySelectorAll("button[data-canned]").forEach((b) => {
      b.addEventListener("click", async () => {
        b.disabled = true;
        const r = await pywebview.api.post_canned(cardId, b.dataset.canned);
        b.disabled = false;
        setStatus(ctx, (r && r.ok) ? `💬 Posted: ${r.text}` : `Post failed: ${(r && r.error) || "?"}`,
                  (r && r.ok) ? "ok" : "error");
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
          const r = await pywebview.api.toggle_checklist_item(cardId, itemId, want);
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
    const cannedHtml = `
      <div class="canned-comments">
        <button class="action-btn" data-canned="ipr"
                title="Post comment: Initial Photo Report Created and Uploaded to OD.">📷 IPR → comment</button>
        <button class="action-btn" data-canned="upload"
                title="Post comment: Initial Upload submitted To WC.">📤 Initial Upload → comment</button>
      </div>`;
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
          const r = await pywebview.api.toggle_checklist_item(cardId, itemId, want);
          ok = !!(r && r.ok);
        } catch (_) { ok = false; }
        cb.disabled = false;
        if (!ok) { cb.checked = !want; setStatus(ctx, "Trello update failed", "error"); return; }
        const span = cb.parentElement.querySelector("span");
        if (span) span.className = want ? "cl-done" : "";
        setStatus(ctx, want ? "Ticked ✓" : "Un-ticked", "ok");
      });
    });
    bodyEl.querySelectorAll("button[data-canned]").forEach((b) => {
      b.addEventListener("click", async () => {
        b.disabled = true;
        const r = await pywebview.api.post_canned(cardId, b.dataset.canned);
        b.disabled = false;
        setStatus(ctx, (r && r.ok) ? `💬 Posted: ${r.text}` : `Post failed: ${(r && r.error) || "?"}`,
                  (r && r.ok) ? "ok" : "error");
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
              return `
              <label style="display:block;font-size:11px;color:var(--text-muted);">
                ${_escapeHtml(f.label)}${inh
                  ? ` <span style="font-size:9.5px;opacity:.75;">· from client</span>`
                  : ""}
                <input class="ji-f" data-fid="${_escapeAttr(f.id)}" type="text"
                       value="${_escapeAttr(vals[f.id] || "")}"
                       style="width:100%;margin-top:3px;background:var(--surface-2);
                              color:${inh ? "var(--text-muted)" : "var(--text)"};
                              border:1px solid ${inh ? "transparent" : "var(--border)"};
                              border-radius:6px;padding:6px 8px;font-size:12.5px;" />
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
    w.addEventListener("click", (e) => { if (e.target === w) w.remove(); });
    w.querySelectorAll(".modal-close").forEach((b) =>
      b.addEventListener("click", () => w.remove()));
    return w;
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

  // ── 📌 Pin Trello card modal (shared — real persisted pin) ─────────
  function openPinModal(row, ctx) {
    const wrap = mkModal({
      title: row.trello_card_id ? "Re-pin Trello card" : "Pin Trello card",
      sub:   `Client: ${row.client}`,
      body: `
        <input id="pin-q" class="search" type="search" autocomplete="off"
               placeholder="🔎 Search Trello cards by name…"
               value="${escA(ctx, row.client)}" style="width:100%;" />
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
    let timer = null;
    async function doSearch() {
      const text = q.value.trim();
      if (text.length < 2) { results.innerHTML = ""; return; }
      results.innerHTML = `<div class="target-row" style="opacity:.6;padding:6px 10px;">Searching…</div>`;
      const hits = await pywebview.api.search_trello(text) || [];
      if (!hits.length) {
        results.innerHTML = `<div class="target-row" style="opacity:.6;padding:6px 10px;">No matches</div>`;
        return;
      }
      results.innerHTML = hits.map((h) => `
        <div class="target-row" data-card="${escA(ctx, h.card_id)}"
             style="display:flex;gap:8px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;cursor:pointer;">
          <span>📌</span>
          <span class="name" style="flex:1;font-weight:600;">${esc(ctx, h.name)}</span>
          <span class="miss muted" style="font-size:11px;">${esc(ctx, h.lane || h.board || "")}</span>
        </div>`).join("");
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

  window.AuditDetail = {
    buildDetailBodyHTML,
    wireDetail,
    detailAction,
    loadTrelloInfo,
    loadInProgressChecklist,
    loadInitialChecklists,
    loadCloseoutChecklist,
    decorateIssueListsWithCheckboxes,
    mkModal,
    openCloseoutModal,
    openPinModal,
    openCopyPicsToXaModal,
  };
})();
