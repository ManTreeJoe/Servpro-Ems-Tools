"use strict";
const state = { rows: [], lanes: [], lane: "all", search: "", selected: null, loading: false, importBtn: null };
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// Live HEIC→JPEG conversion progress from the backend (do_import emits
// `import:progress` per file). Updates the running import button so a
// big photo dump shows "Converting N/M…" instead of a frozen
// "Extracting…". No-op if no import is active or the count is 0.
window.addEventListener("import:progress", (e) => {
  const d = (e && e.detail) || {};
  if (state.importBtn && d.total) {
    state.importBtn.textContent = `Converting ${d.done}/${d.total}…`;
  }
});

window.addEventListener("pywebviewready", async () => {
  $("#refresh-btn").addEventListener("click", refresh);
  $("#add-manual-btn").addEventListener("click", openAddManualModal);
  $("#search-box").addEventListener("input", (e) => { state.search = e.target.value; render(); });
  $("#show-dismissed").addEventListener("change", async (e) => {
    const r = await pywebview.api.set_show_dismissed(e.target.checked);
    applyIuqRows(r);
  });
  window.addEventListener("iuq:done", onDone);
  document.addEventListener("keydown", onKey);

  const cached = await pywebview.api.last_cards();
  state.rows = cached.rows || [];
  state.lanes = cached.lanes || [];
  state.show_dismissed = !!cached.show_dismissed;
  const sd = $("#show-dismissed"); if (sd) sd.checked = state.show_dismissed;
  if (!state.rows.length) await refresh();
  else { autoSelect(); render(); }
  // Deep-link focus from a cross-tool "Open in → Initial Uploads":
  // pre-fill the search so the matching card filters into view.
  const _focus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";
  if (_focus) {
    state.lane = "all";   // a lane chip must not hide the focused card
    const box = $("#search-box");
    if (box) { box.value = _focus; box.dispatchEvent(new Event("input")); }
  }
});

function _releaseLoading() {
  if (state._loadTimer) { clearTimeout(state._loadTimer); state._loadTimer = null; }
  state.loading = false;
  $("#loading-state").classList.add("hidden");
  $("#refresh-btn").disabled = false;
}

// Apply a dismiss / undismiss / show-dismissed backend response: swap in
// the freshly-filtered rows + sync the toggle, then re-render. Avoids a
// full Trello re-fetch.
function applyIuqRows(res) {
  if (!res || !res.ok) { setStatus(`Failed: ${res?.error || "?"}`, "error"); return; }
  if (Array.isArray(res.rows)) state.rows = res.rows;
  if (typeof res.show_dismissed === "boolean") {
    state.show_dismissed = res.show_dismissed;
    const sd = $("#show-dismissed"); if (sd) sd.checked = state.show_dismissed;
  }
  autoSelect();
  render();
}

// `quiet` skips the blocking spinner (used after a manual add — the new
// row is already shown optimistically, so the background enrichment
// shouldn't gate the UI).
async function refresh(quiet = false) {
  if (state.loading) return;
  state.loading = true;
  if (!quiet) {
    $("#loading-state").classList.remove("hidden");
    $("#refresh-btn").disabled = true;
  }
  // Safety net: the backend signals completion via an `iuq:done` event,
  // not the return value. If that never arrives — the backend declined
  // because one was already running, or a slow/blocked SharePoint walk
  // stalls the fetch — don't pin the spinner (and don't wedge state.loading
  // so future refreshes still fire). Releases after 30s.
  if (state._loadTimer) clearTimeout(state._loadTimer);
  state._loadTimer = setTimeout(() => {
    if (state.loading) {
      _releaseLoading();
      setStatus("Still enriching in the background — showing what's loaded", "warn");
    }
  }, 30000);
  try {
    const r = await pywebview.api.refresh();
    // Backend already refreshing → no fresh iuq:done is coming for THIS
    // call, so release now (the in-flight one will update rows when done).
    if (r && r.started === false) _releaseLoading();
  } catch (ex) {
    _releaseLoading();
    setStatus(`Refresh error: ${ex}`, "error");
  }
}

function onDone(ev) {
  if (state._loadTimer) { clearTimeout(state._loadTimer); state._loadTimer = null; }
  state.loading = false;
  $("#loading-state").classList.add("hidden");
  $("#refresh-btn").disabled = false;
  const { ok, rows, lanes, error, show_dismissed } = ev.detail || {};
  if (!ok) { setStatus(`Refresh failed: ${error || "?"}`, "error"); return; }
  state.rows = rows || [];
  state.lanes = lanes || [];
  state.show_dismissed = !!show_dismissed;
  const _sd = $("#show-dismissed"); if (_sd) _sd.checked = state.show_dismissed;
  // Keep a just-added manual row selected after the refresh re-fetch
  // (which lists manual rows at a different position than the optimistic
  // unshift). Without this the selection would jump back to row 0.
  if (state.justAdded) {
    const m = state.rows.find((r) =>
      (r.client || "").toLowerCase() === state.justAdded);
    if (m) state.selected = m.card_id || m.client;
    state.justAdded = null;
  }
  autoSelect();
  render();
  setStatus(`Loaded ${state.rows.length} cards`, "ok");
}

function autoSelect() {
  if (!state.selected && state.rows.length) state.selected = state.rows[0].card_id;
}

function filtered() {
  const q = state.search.trim().toLowerCase();
  const rows = state.rows.filter((r) => {
    if (state.lane !== "all" && r.lane !== state.lane) return false;
    if (!q) return true;
    return [r.client, r.name, r.lane].join(" ").toLowerCase().includes(q);
  });
  // Manual rows first — they're the user's own additions, and a freshly
  // added one should land at the top of the list rather than the bottom
  // (where the Trello re-fetch appends merged manual rows).
  return rows.sort((a, b) => (b.manual ? 1 : 0) - (a.manual ? 1 : 0));
}

function render() {
  renderLaneChips();
  renderList();
  renderDetail();
}

function renderLaneChips() {
  const counts = { all: state.rows.length };
  for (const r of state.rows) counts[r.lane] = (counts[r.lane] || 0) + 1;
  const chips = [{ key: "all", label: "All" }, ...state.lanes.map((l) => ({ key: l, label: l }))];
  $("#lane-chips").innerHTML = chips.map((c) =>
    `<button class="filter ${c.key === state.lane ? "active" : ""}" data-lane="${esc(c.key)}">${esc(c.label)} <span class="muted">${counts[c.key] || 0}</span></button>`
  ).join("");
  $$(".filter").forEach((b) => b.addEventListener("click", () => {
    state.lane = b.dataset.lane; renderLaneChips(); renderList(); renderDetail();
  }));
}

function renderList() {
  const rows = filtered();
  if (rows.length && !rows.find((r) => r.card_id === state.selected)) {
    state.selected = rows[0].card_id;
  } else if (!rows.length) {
    state.selected = null;
  }
  $("#list-count").textContent = `${rows.length} / ${state.rows.length} cards`;
  $("#status-counts").textContent = `${rows.length} shown · ${state.rows.length} total`;
  $("#list-body").innerHTML = rows.map((r) => {
    const isActive = r.card_id === state.selected;
    const progClass = r.total > 0 && r.done === r.total ? "progress done"
      : r.done > 0 ? "progress partial" : "progress";
    // Inline 📌 chip for rows that don't have a card pinned yet
    // (typically APA-synthesized rows). Click → opens the search
    // modal seeded with this row's client name. Right-click any row
    // → context menu with Pin / Re-pin / Open / etc.
    const needsPin = !r.card_id;
    return `
      <div class="list-row ${isActive ? "active" : ""} ${r.dismissed ? "dismissed" : ""}" data-card="${esc(r.card_id)}" data-client="${esc(r.client)}">
        <span class="list-status">${r.dismissed ? "✕" : (needsPin ? "📌" : "📥")}</span>
        <div class="list-main">
          <div class="list-name">${esc(r.client || r.name)}</div>
          <div class="list-sub">
            <span class="lane-pill" data-lane="${esc(r.lane)}">${esc(r.lane)}</span>
            ${r.time_slot ? `<span class="lane-pill" style="background:var(--act-monitor);color:#fff;" title="Run-doc appointment">🕒 ${esc(r.time_slot)}</span>` : ""}
            ${r.from_apa ? `<span class="lane-pill" style="background:#5A7FB8;color:#fff;" title="Synthesized from APA Monitor Initial Uploads">📋 APA</span>` : ""}
            ${needsPin ? `<span class="lane-pill iuq-pin-chip" style="background:var(--amber);color:#fff;cursor:pointer;" title="No Trello card attached — click to search and pin one">📌 Pin card</span>` : ""}
            ${needsPin ? `<span class="lane-pill iuq-create-chip" style="background:var(--green);color:#fff;cursor:pointer;" title="Create a brand-new Trello card for this client in the Initial Inspections lane">➕ Create card</span>` : ""}
            ${(r.requested_days != null) ? `<span class="lane-pill" style="background:${r.requested_days >= 5 ? "var(--red)" : r.requested_days >= 2 ? "var(--amber)" : "var(--text-muted)"};color:#fff;" title="Initial Photo Report requested on ${esc(r.requested_at)}">📨 Requested ${r.requested_days}d ago</span>` : ""}
            ${r.audit_total_missing > 0 ? `<span class="lane-pill" style="background:var(--red);color:#fff;" title="Audit flagged ${r.audit_total_missing} missing item${r.audit_total_missing !== 1 ? "s" : ""}">🔎 ${r.audit_total_missing} missing</span>` : ""}
            ${(r.sharepoint_new || 0) > 0 ? `<span class="lane-pill iuq-sp-chip" style="background:var(--act-monitor);color:#fff;cursor:pointer;" title="${r.sharepoint_new} file${r.sharepoint_new !== 1 ? "s" : ""} on SharePoint not yet in OneDrive — click to import">📥 SP +${r.sharepoint_new}</span>` : ""}
          </div>
        </div>
        <div class="list-end">
          <span class="${progClass}">${esc(r.progress)}</span>
        </div>
      </div>`;
  }).join("");
  $$(".list-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      // 📌 Pin chip click — open the pin modal seeded with this row
      if (e.target.closest(".iuq-pin-chip")) {
        e.stopPropagation();
        const client = row.dataset.client;
        const fakeRow = filtered().find((x) => x.client === client) || { client };
        openIuqPin(fakeRow);
        return;
      }
      // 📥 SP chip click — open the SharePoint import modal for this row
      if (e.target.closest(".iuq-sp-chip")) {
        e.stopPropagation();
        const client = row.dataset.client;
        const r2 = filtered().find((x) => x.client === client);
        if (r2) openIuqSpImport(r2);
        return;
      }
      // ➕ Create Trello card chip — for rows without a card.
      // Confirms first to avoid accidental spam.
      if (e.target.closest(".iuq-create-chip")) {
        e.stopPropagation();
        const client = row.dataset.client;
        createTrelloCardForIuq(client);
        return;
      }
      state.selected = row.dataset.card || row.dataset.client;
      renderList(); renderDetail();
    });
    // Right-click context menu for pin / open / etc.
    row.addEventListener("contextmenu", (e) => {
      const client = row.dataset.client;
      const r = filtered().find((x) => x.client === client);
      if (r) showIuqCtxMenu(e, r);
    });
    if (row.dataset.card && window.attachTrelloHover) {
      window.attachTrelloHover(row, row.dataset.card);
    }
  });
}

async function renderDetail() {
  const r = state.rows.find((x) => x.card_id === state.selected);
  const empty = $("#detail-empty");
  const view = $("#detail-view");
  if (!r) { empty.classList.remove("hidden"); view.classList.add("hidden"); view.innerHTML = ""; return; }
  empty.classList.add("hidden"); view.classList.remove("hidden");
  // On-demand checklist fetch when the row has a pinned card but
  // the bulk scan didn't populate checklists (APA-synthesized rows,
  // post-scan pins). Reach out to Trello once + cache on the row so
  // subsequent re-renders don't refetch.
  if (r.card_id && !r._cl_fetched) {
    const allEmpty = !(r.checklists?.length) ||
                      r.checklists.every((cl) => !cl.present);
    if (allEmpty) {
      r._cl_fetched = true;  // mark before await so we don't double-fire
      try {
        const fresh = await pywebview.api.fetch_card_checklists(r.card_id);
        if (fresh?.ok) {
          r.checklists = fresh.checklists || [];
          r.items = (r.checklists || []).flatMap((cl) => cl.items || []);
          r.done  = fresh.done || 0;
          r.total = fresh.total || 0;
          r.progress = r.total ? `${r.done}/${r.total}` : "—";
          // Refresh list row's progress chip too
          renderList();
        }
      } catch (_) { /* fall through — keep showing whatever we had */ }
    }
  }
  // Render one section per tracked checklist (INITIAL - ADMIN +
  // INITIAL) so the user sees both. Falls back to a single section
  // if the card has no checklists (e.g. APA-synthesized rows).
  const cls = (r.checklists && r.checklists.length) ? r.checklists : null;
  const checklist = cls
    ? cls.map((cl) => {
        const doneN = cl.items.filter((it) => it.done).length;
        const totN  = cl.items.length;
        const presentNote = cl.present
          ? ""
          : `<span style="font-size:10px;color:var(--amber);font-weight:600;margin-left:6px;">⚠ not on card</span>`;
        return `<section class="detail-section">
          <h3>📋 ${esc(cl.name)} <span style="font-weight:400;color:var(--text-muted);">(${doneN}/${totN})</span>${presentNote}</h3>
          <ul class="checklist">
            ${cl.items.map((it) => `
              <li class="${it.done ? "done" : ""}${it.state === "missing" ? " missing" : ""}" data-iid="${esc(it.id || '')}">
                <span class="cl-toggle" data-iid="${esc(it.id || '')}"></span>
                <span class="cl-name">${esc(it.name)}${it.state === "missing" ? " <span style='color:var(--amber);font-size:10px;'>(missing on card)</span>" : ""}</span>
              </li>`).join("")}
          </ul>
        </section>`;
      }).join("")
    : `<section class="detail-section"><h3>No checklist on card</h3>
         <div class="muted" style="font-size:12px;padding:8px 0;">
           This card doesn't have an INITIAL - ADMIN or INITIAL checklist yet.
           Add them on Trello first, then ↻ Refresh.
         </div>
       </section>`;
  // 🔎 Audit-side missing items — pulled fresh in the background
  // refresh via audit_logic.audit_jobs. Surfaces what the Audit
  // panel would flag for this same client, right next to the
  // checklist gaps. Same look as the audit panel's missing-forms
  // and missing-photos sections.
  const audForms = r.audit_form_issues || [];
  const audPhotos = r.audit_photo_issues || [];
  // Misfiled — present in the parent tree (wrong folder), not missing.
  // Mirrors the audit + snapshot "misfiled" treatment for commercial
  // sub-jobs. Each: {label, where}.
  const audMisplaced = [
    ...(r.audit_misplaced_forms  || []).map((m) => ({ ...m, icon: "📋" })),
    ...(r.audit_misplaced_photos || []).map((m) => ({ ...m, icon: "📷" })),
  ];
  const auditSection = (audForms.length || audPhotos.length || audMisplaced.length) ? `
    <section class="detail-section">
      <h3>🔎 Audit-flagged missing items
        <span style="font-weight:400;color:var(--text-muted);">(${audForms.length + audPhotos.length})</span>
      </h3>
      ${audForms.length ? `
        <div class="audit-issue-group">
          <div class="audit-issue-lbl">📋 Forms (${audForms.length})</div>
          <ul class="audit-issue-list">
            ${audForms.map((x) => `<li>${esc(x)}</li>`).join("")}
          </ul>
        </div>` : ""}
      ${audPhotos.length ? `
        <div class="audit-issue-group">
          <div class="audit-issue-lbl">📷 Photos (${audPhotos.length})</div>
          <ul class="audit-issue-list photos">
            ${audPhotos.map((x) => `<li>${esc(x)}</li>`).join("")}
          </ul>
        </div>` : ""}
      ${audMisplaced.length ? `
        <div class="audit-issue-group">
          <div class="audit-issue-lbl">⚠ Misfiled — wrong folder (${audMisplaced.length})</div>
          <ul class="audit-issue-list misplaced">
            ${audMisplaced.map((m) => `<li>${m.icon} ${esc(m.label)} — <span class="muted">in <code>${esc(m.where || "parent")}</code></span></li>`).join("")}
          </ul>
        </div>` : ""}
      <!-- Import action row inside the audit section — same SP/WC
           flows the audit panel exposes, so the user can fill the
           gaps without leaving the IUQ. -->
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);">
        <button class="action-btn primary" id="iuq-audit-sp"
                title="Walk SharePoint for files that match this client and copy them into the OD job folder">📥 Import from SharePoint…</button>
        <button class="action-btn" id="iuq-audit-wc"
                title="Extract a WorkCenter zip + DocuSign download from your Downloads folder">🗂 Import from WorkCenter…</button>
        <button class="action-btn" id="iuq-audit-reaudit" title="Re-run the audit for this client after importing">↻ Re-audit</button>
      </div>
    </section>` :
    (r.audit_found ? `
      <section class="detail-section">
        <div class="audit-clean">✓ Audit clean — no missing forms or photos.</div>
      </section>` : "");

  // Compact summary chip in the chip row so the user sees the
  // count without scrolling to the section.
  const auditChip = (audForms.length || audPhotos.length)
    ? `<span class="detail-chip missing" title="Audit flagged ${audForms.length + audPhotos.length} missing item${audForms.length + audPhotos.length !== 1 ? "s" : ""}">🔎 ${audForms.length + audPhotos.length} missing</span>`
    : (r.audit_found ? `<span class="detail-chip ok" title="Audit found the folder + nothing missing">🔎 audit clean</span>` : "");
  // 📥 SP chip — clickable, opens the SP import modal. Same chip
  // the audit panel shows in its detail header.
  const spChipDetail = (r.sharepoint_new || 0) > 0
    ? `<span class="detail-chip iuq-detail-sp" style="background:var(--act-monitor);color:#fff;cursor:pointer;" title="${r.sharepoint_new} files on SharePoint not yet in OD — click to import">📥 SP +${r.sharepoint_new} new</span>`
    : "";

  view.innerHTML = `
    <header class="detail-head">
      <div class="detail-name">${esc(r.client || r.name)}</div>
      <div class="detail-techs">${esc(r.name)}</div>
    </header>
    <div class="detail-chip-row">
      <span class="lane-pill" data-lane="${esc(r.lane)}">${esc(r.lane)}</span>
      ${r.time_slot ? `<span class="detail-chip" style="background:var(--act-monitor);color:#fff;font-weight:600;" title="Today's appointment time">🕒 ${esc(r.time_slot)}</span>` : ""}
      ${auditChip}
      ${spChipDetail}
      ${r.labels.map((l) => `<span class="detail-chip">${esc(l)}</span>`).join("")}
    </div>
    ${checklist}
    ${auditSection}
    <section class="detail-section">
      <h3>📥 Canned comments</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="action-btn" id="iuq-canned-ipr">📷 Initial Photo Report Created and Uploaded to OD.</button>
        <button class="action-btn" id="iuq-canned-upload">📤 Initial Upload submitted To WC.</button>
      </div>
    </section>
    <footer class="detail-actions">
      <!-- Compact bottom row mirrors the daily-run audit footer:
           Open OD + Trello + Import + Stage XA + Notes + More. Every
           less-common action moves into the ⋯ More menu so the row
           doesn't wrap on narrow windows. Buttons shown inline are
           SKIPPED in the More menu (no duplication). -->
      <button class="action-btn primary" id="iuq-od">📁 Open OD</button>
      <button class="action-btn" id="open-card">
        <img src="../web_shared/trello.png" alt="" style="width:13px;height:13px;vertical-align:middle;margin-right:4px;" />Trello</button>
      <button class="action-btn" id="iuq-xa" ${r.card_id ? "" : "disabled"}>
        <img src="../web_shared/xactanalysis.png" alt="" onerror="this.remove()" style="width:13px;height:13px;vertical-align:middle;margin-right:4px;" />XA</button>
      <button class="action-btn" id="iuq-attach" ${r.card_id ? "" : "disabled"}
              title="Browse + download the Trello card's photos/files">📎 Attachments</button>
      <button class="action-btn" id="iuq-sp"
              title="Import matching files from SharePoint into the OD job folder">📥 Import SP</button>
      <button class="action-btn primary" id="iuq-import">📥 Import</button>
      <button class="action-btn" id="iuq-copy-initial"
              title="Stage every image in EMS/PICS/Initial/ (recursive) into a TEMP folder + open in Explorer — drag into XactAnalysis. Auto-deletes after 1 min.">📂 Stage Initial</button>
      <button class="action-btn" id="iuq-note">🗒 Notes</button>
      <button class="action-btn" id="iuq-more">⋯ More actions</button>
    </footer>`;
  // Wire checklist toggle clicks
  view.querySelectorAll(".cl-toggle").forEach((box) => {
    box.addEventListener("click", async (e) => {
      e.stopPropagation();
      const iid = box.dataset.iid;
      if (!iid) return;
      const li = box.closest("li");
      const wasDone = li.classList.contains("done");
      const next = !wasDone;
      li.classList.toggle("done", next);
      const res = await pywebview.api.toggle_check_item(r.card_id, iid, next);
      if (!res?.ok) {
        li.classList.toggle("done", wasDone);
        setStatus(`Toggle failed: ${res?.error || "?"}`, "error");
      } else {
        setStatus(next ? "✓ Marked complete" : "Re-opened", "ok");
      }
    });
  });
  // 📥 SP chip in chip row → opens the SP import modal
  view.querySelector(".iuq-detail-sp")?.addEventListener("click", (e) => {
    e.stopPropagation();
    openIuqSpImport(r);
  });
  $("#iuq-canned-ipr").addEventListener("click", async () => {
    const res = await pywebview.api.post_canned(r.card_id, "ipr");
    setStatus(res?.ok ? "💬 Posted IPR comment" : `Failed: ${res?.error}`,
              res?.ok ? "ok" : "error");
  });
  $("#iuq-canned-upload").addEventListener("click", async () => {
    const res = await pywebview.api.post_canned(r.card_id, "upload");
    setStatus(res?.ok ? "💬 Posted Initial Upload comment" : `Failed: ${res?.error}`,
              res?.ok ? "ok" : "error");
  });
  $("#open-card").addEventListener("click", () => {
    if (r.card_url) {
      pywebview.api.open_url(r.card_url);
    } else {
      // No URL pinned yet — fall through to pin dialog as a friendlier
      // affordance than a dead click.
      openIuqPin(r);
    }
  });
  // Parity buttons (Open XA · 📎 Attachments · Import SP) so the IUQ
  // audit row carries the same core tools as the Daily Run + Snapshot
  // audits. open_xa_for_client is the shared HomeApi resolver (IUQ has
  // no XA backend of its own).
  $("#iuq-xa")?.addEventListener("click", async () => {
    const res = await pywebview.api.open_xa_for_client(r.client);
    if (res && res.ok === false)
      setStatus(`XA: ${res.error || "no link on the pinned card"}`, "warn");
  });
  $("#iuq-attach")?.addEventListener("click", () =>
    window.openTrelloAttachmentsModal({ cardId: r.card_id, client: r.client }));
  $("#iuq-sp")?.addEventListener("click", () => openIuqSpImport(r));
  // Right-click the Trello button → 📌 Pin/Change. Mirrors the OD
  // folder right-click affordance so users get the same shape of
  // action on both pin types.
  $("#open-card").addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    openIuqPin(r);
  });
  $("#iuq-import").addEventListener("click", () => openIuqImport(r));
  $("#iuq-od").addEventListener("click", async () => {
    // Smart open: backend re-resolves via the validated chain when
    // the cached path is stale (folder renamed since the audit).
    const res = await pywebview.api.open_od_for_client(
      r.client, r.path || r.od_path || "");
    if (res?.ok) {
      if (res.refreshed) {
        r.path = res.path;
        setStatus(`Opened ${r.client} · path refreshed`, "ok");
      } else {
        setStatus(`Opened ${r.client}`, "ok");
      }
    } else if (res?.needs_find) {
      if (confirm(`No folder found for ${r.client}:\n${res.error || ""}\n\nOpen the IUQ pin dialog now?`)) {
        openIuqFolderPin(r);
      } else {
        setStatus(res.error || "No folder", "warn");
      }
    } else {
      setStatus(res?.error || "Couldn't open folder", "warn");
    }
  });
  // 📂 Stage Initial — kept inline as a common per-job action.
  $("#iuq-copy-initial").addEventListener("click", async () => {
    const btn = $("#iuq-copy-initial");
    btn.disabled = true; btn.textContent = "Staging…";
    const res = await pywebview.api.copy_pics_to_clipboard(r.client, "Initial");
    btn.disabled = false; btn.textContent = "📂 Stage Initial";
    if (!res?.ok) {
      setStatus(`Stage failed: ${res?.error || "?"}`, "error");
      return;
    }
    const matched = res.matched_stage ? ` from ${res.matched_stage}` : "";
    setStatus(`📂 Staged ${res.count} image${res.count !== 1 ? "s" : ""}${matched} → ${res.folder} · drag into XA · auto-deletes at ${res.deletes_at}`, "ok");
  });
  $("#iuq-note").addEventListener("click", () => openIuqNote(r));
  // ⋯ More actions — opens the same ctx menu the right-click does,
  // pinned to the More button's screen position so the user gets the
  // full action set without right-clicking. Inline actions (📁 OD,
  // Trello, 📥 Import, 📂 Stage Initial, 🗒 Notes) are filtered out
  // of the menu so we don't double-present them.
  $("#iuq-more").addEventListener("click", (ev) => {
    showIuqCtxMenu(ev, r, { excludeInline: true });
  });
  // Audit-subview import buttons — only present when the audit
  // section rendered (i.e. there were flagged items). Optional
  // chaining keeps it safe when the buttons aren't on the page.
  $("#iuq-audit-sp")?.addEventListener("click", () => openIuqSpImport(r));
  $("#iuq-audit-wc")?.addEventListener("click", () => openIuqImport(r));
  $("#iuq-audit-reaudit")?.addEventListener("click", async () => {
    setStatus("Re-auditing…");
    const re = await pywebview.api.reaudit_one(r.client);
    if (!re?.ok) { setStatus(`Re-audit failed: ${re?.error || "?"}`, "error"); return; }
    // Merge fresh audit data onto the row in state.rows so re-render
    // picks it up without a full panel refresh.
    const ix = state.rows.findIndex((x) => x.card_id === r.card_id);
    if (ix >= 0 && re.row) {
      state.rows[ix].audit_form_issues  = re.row.form_issues || [];
      state.rows[ix].audit_photo_issues = re.row.photo_issues || [];
      state.rows[ix].audit_misplaced_forms  = re.row.misplaced_forms  || [];
      state.rows[ix].audit_misplaced_photos = re.row.misplaced_photos || [];
      state.rows[ix].audit_flagged      = !!re.row.flagged;
      state.rows[ix].audit_found        = !!re.row.found;
      state.rows[ix].audit_path         = re.row.path || "";
      state.rows[ix].audit_total_missing =
        (re.row.form_issues || []).length + (re.row.photo_issues || []).length;
    }
    renderList(); renderDetail();
    setStatus("↻ Re-audited", "ok");
  });
}

async function openIuqNote(r) {
  const cur = await pywebview.api.get_card_note(r.card_id);
  const ov = mkModal({
    title: "🗒 Notes for " + (r.client || r.name),
    sub:   "Per-card freeform notes (persisted across refreshes).",
    body: `
      <textarea id="note-text" rows="10" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;outline:none;resize:vertical;"
                placeholder="Type notes about this card…">${esc(cur || "")}</textarea>
      <div class="modal-footer" style="margin-top:14px;display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="note-save">💾 Save</button>
      </div>`,
  });
  ov.querySelector("#note-save").addEventListener("click", async () => {
    const text = ov.querySelector("#note-text").value;
    const res = await pywebview.api.set_card_note(r.card_id, text);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    closeModal();
    setStatus("💾 Note saved", "ok");
  });
  ov.querySelector("#note-text").focus();
}

// ── IUQ Phase 2 modals ───────────────────────────────────────────
// ── ➕ Create Trello card for a manual / APA-synthesized IUQ row ──
// Mirrors Tk initial_upload_queue.py:3066 _create_trello_card_for.
// Adds a card on the Initial Inspections lane + pins it to the
// client so the audit/snapshot/hygiene panels all recognize it.
async function createTrelloCardForIuq(client) {
  if (!client) return;
  if (!confirm(`Create a new Trello card for "${client}" in the Initial Inspections lane?\n\nThe new card will be pinned to this client automatically so the audit + snapshot find it.`)) return;
  setStatus("➕ Creating Trello card…");
  const res = await pywebview.api.create_trello_card_for(client, "");
  if (!res?.ok) {
    setStatus(`Create failed: ${res?.error || "?"}`, "error");
    return;
  }
  setStatus(`➕ Created card ${res.card_id} in ${res.lane} · pinned to ${client}`, "ok");
  // Re-fetch so the row shows its new card_id + checklist progress.
  await refresh();
}

// ── 📥 SharePoint import (parity with audit panel's per-row flow) ─
// Same backend (sp_find_matches → sp_copy_to_pics) so files land in
// the same place — EMS/PICS/<stage>/. After copying, re-audits so
// the audit-flagged section refreshes its count.
async function openIuqSpImport(r) {
  const ov = mkModal({
    title: "📥 Import from SharePoint",
    sub:   `Client: ${r.client || r.name}`,
    width: 960,
    body: `<div id="iuq-sp-status" class="muted">🔎 Searching SharePoint…</div>
      <div id="iuq-sp-list" style="margin-top:10px;max-height:540px;overflow-y:auto;"></div>
      <div class="modal-footer" style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn" id="iuq-sp-pin">📎 Pin SP folder…</button>
        <button class="btn" id="iuq-sp-rescan">↻ Re-scan</button>
        <span style="flex:1;"></span>
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  function renderMatches(matches) {
    const status = ov.querySelector("#iuq-sp-status");
    status.textContent = matches.length
      ? `${matches.length} SharePoint folder${matches.length !== 1 ? "s" : ""} match`
      : "No SharePoint folders match. Use 📎 Pin SP folder… below to attach one manually.";
    ov.querySelector("#iuq-sp-list").innerHTML = matches.map((m, i) => `
      <div class="iuq-sp-row" data-i="${i}" data-path="${esc(m.path)}"
           style="display:grid;grid-template-columns:auto 1fr auto auto auto auto;gap:8px;
                  align-items:center;padding:8px 10px;border:1px solid var(--border);
                  border-radius:6px;margin-bottom:4px;background:var(--surface);">
        <span title="${m.matches_date ? 'Matches run date' : ''}">${m.matches_date ? "✓" : "📁"}</span>
        <div style="min-width:0;">
          <div style="font-weight:600;font-size:13px;">${esc(m.name)}</div>
          <div class="muted" style="font-size:11px;word-break:break-all;">
            ${esc(m.tech || "—")} · ${m.img_count} files · ${m.new_count} new
            <span class="iuq-sp-cloud" data-i="${i}" style="margin-left:6px;"></span>
          </div>
        </div>
        <button class="action-btn" data-act="open" title="Open in Explorer">📁</button>
        <button class="action-btn" data-act="mark_od" title="These are already in OD — don't flag as new again" ${m.img_count > 0 ? "" : "disabled"}>✓ In OD</button>
        <button class="action-btn primary" data-act="copy" ${m.new_count > 0 ? "" : "disabled"}>📥 Copy +${m.new_count}</button>
        <button class="action-btn warn" data-act="reject" title="Hide from future scans">✕</button>
      </div>`).join("");
    // Cloud-only tags per row (async, fires in parallel)
    matches.forEach(async (m, i) => {
      try {
        const cr = await pywebview.api.sp_cloud_only_count(m.path);
        const chip = ov.querySelector(`.iuq-sp-cloud[data-i="${i}"]`);
        if (chip && cr?.ok && cr.count > 0) {
          chip.innerHTML = `<span style="background:var(--amber);color:#FFF;padding:1px 6px;border-radius:3px;font-weight:700;font-size:10px;" title="${cr.count} cloud-only placeholders">☁ ${cr.count} cloud-only</span>`;
        }
      } catch (_) {}
    });
    wireRows(matches);
  }

  function wireRows(matches) {
    ov.querySelectorAll(".iuq-sp-row").forEach((rowEl) => {
      const m = matches[+rowEl.dataset.i];
      rowEl.querySelectorAll(".action-btn[data-act]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const act = btn.dataset.act;
          if (act === "open") {
            await pywebview.api.sp_open_folder(m.path);
          } else if (act === "mark_od") {
            btn.disabled = true; btn.textContent = "Marking…";
            const res = await pywebview.api.sp_mark_in_od(r.client, m.path);
            if (!res?.ok) { setStatus(`Mark failed: ${res?.error || "?"}`, "error"); btn.disabled = false; btn.textContent = "✓ In OD"; return; }
            btn.textContent = `✓ ${res.marked} marked`;
            setStatus(`✓ ${res.marked} files marked already-in-OD`, "ok");
          } else if (act === "copy") {
            btn.disabled = true; btn.textContent = "Copying…";
            const res = await pywebview.api.sp_copy_to_pics(r.client, m.path, "", "");
            if (!res?.ok) {
              const err = res?.error || "?";
              const needsFolder = /PICS folder|Pin the OD folder/i.test(err);
              if (needsFolder) {
                btn.disabled = false; btn.textContent = "📥 Copy";
                if (confirm(`No OD folder found for ${r.client}.\n\n${err}\n\nOpen the Pin folder dialog now?`)) {
                  closeModal();
                  openIuqFolderPin(r);
                } else { setStatus(err, "warn"); }
                return;
              }
              setStatus(`Copy failed: ${err}`, "error"); btn.disabled = false; btn.textContent = "📥 Copy"; return;
            }
            btn.textContent = `✓ ${res.copied} copied`;
            setStatus(`✓ ${res.copied} files copied · ${res.skipped} skipped${res.pulled ? ` · ☁ ${res.pulled} pulled` : ""}`, "ok");
            // Re-audit so the section's counts refresh
            const re = await pywebview.api.reaudit_one(r.client);
            if (re?.ok) {
              const ix = state.rows.findIndex((x) => x.card_id === r.card_id);
              if (ix >= 0 && re.row) {
                state.rows[ix].audit_form_issues  = re.row.form_issues || [];
                state.rows[ix].audit_photo_issues = re.row.photo_issues || [];
                state.rows[ix].audit_misplaced_forms  = re.row.misplaced_forms  || [];
                state.rows[ix].audit_misplaced_photos = re.row.misplaced_photos || [];
                state.rows[ix].audit_total_missing =
                  (re.row.form_issues || []).length + (re.row.photo_issues || []).length;
              }
              renderList(); renderDetail();
            }
          } else if (act === "reject") {
            await pywebview.api.sp_reject_match(r.client, m.path);
            rowEl.style.display = "none";
            setStatus("Match rejected — won't show again", "ok");
          }
        });
      });
    });
  }

  async function scan() {
    ov.querySelector("#iuq-sp-status").textContent = "🔎 Scanning…";
    ov.querySelector("#iuq-sp-list").innerHTML = "";
    const res = await pywebview.api.sp_find_matches(r.client, "");
    if (!res?.ok) {
      ov.querySelector("#iuq-sp-status").textContent = "Error: " + (res?.error || "?");
      return;
    }
    renderMatches(res.matches || []);
  }

  ov.querySelector("#iuq-sp-rescan").addEventListener("click", scan);
  ov.querySelector("#iuq-sp-pin").addEventListener("click", async () => {
    setStatus("Pick a SharePoint folder…");
    const picked = await pywebview.api.sp_browse_for_folder();
    if (!picked) { setStatus("Pin canceled", "warn"); return; }
    const res = await pywebview.api.sp_pin_folder(r.client, picked);
    if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
    setStatus(`📎 Pinned ${res.match?.name || picked}`, "ok");
    await scan();
  });
  // Render cached matches FIRST (from the audit's SP enrich pass) so
  // the dialog opens instantly. Then kick off a live re-scan if the
  // user wants fresh data via the ↻ Re-scan button. Same trick the
  // audit panel uses.
  if ((r.sharepoint_matches || []).length) {
    renderMatches(r.sharepoint_matches);
    ov.querySelector("#iuq-sp-status").textContent =
      `${r.sharepoint_matches.length} SharePoint folder${r.sharepoint_matches.length !== 1 ? "s" : ""} match · from last audit (↻ Re-scan for fresh)`;
  } else {
    scan();
  }
}

async function openIuqImport(r) {
  const data = await pywebview.api.scan_downloads_for_card(r.client);
  const cands = data.candidates || [];
  const candsHtml = cands.length ? cands.map((c, i) => `
    <div class="candidate" data-i="${i}">
      <span class="candidate-icon">${esc(c.icon)}</span>
      <div class="candidate-meta">
        <div class="candidate-kind">${esc(c.kind_label)}</div>
        <div class="candidate-label">${esc(c.label)}</div>
      </div>
      <button class="candidate-btn" data-i="${i}">Extract</button>
    </div>`).join("") :
    `<div class="empty-inline">
       <p>Nothing importable in Downloads.</p>
       <p class="muted">Open Workcenter / DocuSign and download, then ↻ re-scan.</p>
     </div>`;
  const ov = mkModal({
    title: "📥 Import Center",
    sub:   `Target: ${r.client || r.name}`,
    body:  `<div class="muted" style="margin-bottom:8px;">Scanning: ${esc(data.downloads || "")}</div>
            <div class="candidates">${candsHtml}</div>
            <div class="modal-footer">
              <button class="btn" id="iuq-rescan">↻ Re-scan</button>
              <button class="btn modal-close">Close</button>
            </div>`,
  });
  ov.querySelectorAll(".candidate-btn").forEach((b) =>
    b.addEventListener("click", async () => {
      const c = cands[+b.dataset.i];
      // Photo imports → ask which PICS stage folder first.
      let dest = "";
      if (c.kind === "companycam" || c.kind === "wc_attachments") {
        const choice = await window.pickPicsStage({ client: r.client, allowAuto: true });
        if (choice === null) return;                 // cancelled
        dest = choice === "AUTO" ? "" : choice;
      }
      b.disabled = true; b.textContent = "Extracting…";
      state.importBtn = b;
      try {
        const res = await pywebview.api.do_import(r.client, c.kind, c.paths, dest);
        if (!res?.ok) {
          b.textContent = "Failed";
          setStatus(`Import failed: ${res?.error || "?"}`, "error");
          return;
        }
        b.textContent = "✓ Done";
        const bits = [];
        if (res.pics_count) bits.push(`${res.pics_count} → PICS/${res.subfolder || "Initial"}`);
        if (res.docs_count) bits.push(`${res.docs_count} → DOCS`);
        setStatus(`✓ Extracted: ${bits.join(" · ")}`, "ok");
      } finally {
        if (state.importBtn === b) state.importBtn = null;
      }
    }));
  ov.querySelector("#iuq-rescan").addEventListener("click", () => { closeModal(); openIuqImport(r); });
}

function openIuqPin(r) {
  const ov = mkModal({
    title: "📌 Pin Trello card",
    sub:   `Client: ${r.client || r.name}`,
    body: `<input id="pin-q" class="search" type="search" placeholder="🔎 Search…" style="width:100%;" value="${esc(r.client || r.name)}" />
           <div id="pin-results" class="target-list" style="margin-top:10px;"></div>
           <div class="modal-footer">
             <button class="btn modal-close">Close</button>
           </div>`,
  });
  const q = ov.querySelector("#pin-q");
  const results = ov.querySelector("#pin-results");
  let t = null;
  async function doSearch() {
    if (q.value.trim().length < 2) { results.innerHTML = ""; return; }
    results.innerHTML = `<div class="target-row" style="opacity:.6;">Searching…</div>`;
    const hits = await pywebview.api.search_trello(q.value.trim());
    if (!hits.length) { results.innerHTML = `<div class="target-row" style="opacity:.6;">No matches</div>`; return; }
    results.innerHTML = hits.map((h) => `
      <div class="target-row" data-card="${esc(h.card_id)}">
        <span>📌</span>
        <span class="name">${esc(h.name)}</span>
        <span class="miss">${esc(h.lane || h.board || "")}</span>
      </div>`).join("");
    results.querySelectorAll(".target-row[data-card]").forEach((row) =>
      row.addEventListener("click", async () => {
        const res = await pywebview.api.pin_trello(r.client, row.dataset.card);
        if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
        setStatus(`📌 Pinned ${r.client}`, "ok");
        closeModal();
      }));
  }
  q.addEventListener("input", () => { if (t) clearTimeout(t); t = setTimeout(doSearch, 220); });
  q.focus(); q.select(); doSearch();
}

function openIuqDS(r) {
  const ov = mkModal({
    title: "✍ Send DocuSign via Trello",
    sub:   `Client: ${r.client || r.name}`,
    body: `<p style="font-size:13px;">Posts a DS request comment on this client's Trello card and queues a Hygiene reminder.</p>
           <div class="modal-footer">
             <button class="btn modal-close">Cancel</button>
             <button class="btn btn-primary" id="ds-go">✍ Send request</button>
           </div>`,
  });
  ov.querySelector("#ds-go").addEventListener("click", async () => {
    const btn = ov.querySelector("#ds-go");
    btn.disabled = true; btn.textContent = "Sending…";
    const res = await pywebview.api.request_docusign(r.client);
    if (!res?.ok) { setStatus(`DS request failed: ${res?.error || "?"}`, "error"); btn.disabled = false; btn.textContent = "✍ Send request"; return; }
    closeModal();
    setStatus(`✍ Requested DocuSign${res.email ? " → " + res.email : ""}`, "ok");
  });
}

function openAddManualModal() {
  const ov = mkModal({
    title: "＋ Add manual IUQ row",
    sub:   "Persists across sessions. Trello URL is optional — type a client name to search instead.",
    body: `
      <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">Client name *</label>
      <input id="am-client" class="search" type="text" style="width:100%;margin-bottom:6px;" placeholder="Type 2+ characters to search Trello…" />
      <div id="am-hits" style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:10px;display:none;background:var(--surface);"></div>
      <label class="modal-lbl" style="display:block;font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">Trello card URL (optional)</label>
      <input id="am-url" class="search" type="text" style="width:100%;" placeholder="https://trello.com/c/..." />
      <div id="am-card-info" class="muted" style="font-size:11px;margin-top:4px;"></div>
      <div class="modal-footer" style="margin-top:14px;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="am-go">＋ Add</button>
      </div>`,
  });
  const clientIn = ov.querySelector("#am-client");
  const urlIn    = ov.querySelector("#am-url");
  const hitsBox  = ov.querySelector("#am-hits");
  const infoEl   = ov.querySelector("#am-card-info");

  // Live Trello search — type 2+ chars and pick a card (auto-fills
  // the URL field). Mirrors how the snapshot pin-card flow lets you
  // discover the Trello card without having to paste the URL.
  let searchTimer = null;
  clientIn.addEventListener("input", () => {
    if (searchTimer) clearTimeout(searchTimer);
    const q = clientIn.value.trim();
    if (q.length < 2) { hitsBox.style.display = "none"; hitsBox.innerHTML = ""; return; }
    searchTimer = setTimeout(async () => {
      const hits = await pywebview.api.search_trello(q) || [];
      if (!hits.length) { hitsBox.style.display = "none"; return; }
      hitsBox.innerHTML = hits.slice(0, 8).map((h) => `
        <div class="am-hit" data-card="${esc(h.card_id || "")}" data-name="${esc(h.name || "")}"
             style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:13px;">
          <div style="font-weight:600;">${esc(h.name || "")}</div>
          <div class="muted" style="font-size:11px;">${esc(h.lane || "")} · ${esc(h.board || "")}</div>
        </div>`).join("");
      hitsBox.style.display = "block";
      hitsBox.querySelectorAll(".am-hit").forEach((el) =>
        el.addEventListener("click", () => {
          const cid = el.dataset.card;
          urlIn.value = cid ? `https://trello.com/c/${cid}` : "";
          clientIn.value = el.dataset.name;
          infoEl.textContent = cid ? `Linked to Trello card ${cid}` : "";
          hitsBox.style.display = "none";
        }));
    }, 250);
  });

  ov.querySelector("#am-go").addEventListener("click", async () => {
    const btn = ov.querySelector("#am-go");
    const client = clientIn.value.trim();
    const url = urlIn.value.trim();
    if (!client) { clientIn.focus(); return; }
    btn.disabled = true; btn.textContent = "Adding…";
    const res = await pywebview.api.add_manual_row(client, url);
    if (!res?.ok) {
      setStatus(`Add failed: ${res?.error || "?"}`, "error");
      btn.disabled = false; btn.textContent = "＋ Add";
      return;
    }
    closeModal();
    setStatus(`＋ Added ${client}${res.card_id ? " · linked to Trello" : ""}`, "ok");
    // A lane chip or search box would otherwise HIDE the new row — manual
    // rows live in the "Manual" lane, so if the user is viewing a specific
    // lane the add looks like it did nothing. Clear both filters and pin
    // the new row as selected so it's actually visible.
    state.lane = "all";
    state.search = "";
    const sb = $("#search-box"); if (sb) sb.value = "";
    state.justAdded = (client || "").toLowerCase();
    // Show the new row immediately — don't wait on (or depend on) the
    // background Trello re-fetch, which can be slow or fail offline.
    if (res.row && !state.rows.some((r) =>
        (r.client || "").toLowerCase() === client.toLowerCase())) {
      state.rows.unshift(res.row);
      if (res.row.lane && !state.lanes.includes(res.row.lane)) {
        state.lanes.push(res.row.lane);
      }
      state.selected = res.row.card_id || client;
    }
    render();
    // Do NOT auto-refresh after an add. The new row is already shown
    // (optimistic unshift) AND persists in `manual_iuq_cards`, so it
    // re-appears — enriched — on the next ↻ Refresh / fetch. The old
    // auto-refresh re-ran the FULL audit + SharePoint enrichment for
    // every row, which could stall on a slow/blocked share and made the
    // add look "stuck loading". The user added a row; show it and stop.
    setStatus(`＋ Added ${client} · ↻ Refresh to pull audit/checklist details`, "ok");
  });
  clientIn.focus();
}

// Thin wrappers around the shared web_shared/modal.js helper. Keeps
// the existing IUQ call sites (mkModal({...}) / closeModal()) unchanged.
function mkModal(opts) { return window.openModal({ ...opts, id: "iuq-modal" }); }
function closeModal() { window.closeModal("iuq-modal"); }

function onKey(e) {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "/") { $("#search-box").focus(); e.preventDefault(); return; }
  if (e.key === "ArrowDown" || e.key === "j") step(+1);
  if (e.key === "ArrowUp"   || e.key === "k") step(-1);
  if (e.key === "r" || e.key === "R") refresh();
}

function step(d) {
  const rows = filtered();
  if (!rows.length) return;
  const ix = rows.findIndex((r) => r.card_id === state.selected);
  state.selected = rows[Math.max(0, Math.min(rows.length - 1, ix + d))].card_id;
  renderList(); renderDetail();
  document.querySelector(".list-row.active")?.scrollIntoView({ block: "nearest" });
}

let st = null;
function setStatus(msg, kind="") {
  const el = $("#status-msg");
  el.textContent = msg || ""; el.className = "status-msg" + (kind ? " "+kind : "");
  if (st) clearTimeout(st);
  if (msg && kind === "ok") st = setTimeout(() => { el.textContent = ""; el.className = "status-msg"; }, 3000);
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// ── Right-click context menu (Tk parity) ─────────────────────────
function showIuqCtxMenu(ev, row, opts = {}) {
  ev.preventDefault();
  ev.stopPropagation();
  // When opened from the ⋯ More button (excludeInline:true), the
  // five actions already shown inline in the footer are skipped so
  // we don't present duplicates. Right-click on a list row uses
  // the FULL menu so a quick right-click still shows everything.
  const excl = !!opts.excludeInline;
  document.getElementById("iuq-ctx-menu")?.remove();
  const m = document.createElement("div");
  m.id = "iuq-ctx-menu";
  m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
    z-index:300;background:var(--surface);border:1px solid var(--border);
    border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.5);
    min-width:200px;font-size:12px;visibility:hidden;`;
  function btn(label, onClick, opts = {}) {
    const b = document.createElement("button");
    b.style.cssText = `display:flex;align-items:center;gap:6px;width:100%;text-align:left;background:transparent;
      color:${opts.color || "var(--text)"};border:none;padding:7px 12px;
      cursor:pointer;font:inherit;${opts.disabled ? "opacity:0.5;cursor:not-allowed;" : ""}`;
    if (opts.iconImg) {
      const img = document.createElement("img");
      img.src = opts.iconImg; img.alt = "";
      img.style.cssText = "width:13px;height:13px;vertical-align:middle;flex-shrink:0;";
      b.appendChild(img);
      const span = document.createElement("span");
      span.textContent = label;
      b.appendChild(span);
    } else {
      b.textContent = label;
    }
    if (!opts.disabled) {
      b.addEventListener("mouseenter", () => b.style.background = "var(--row-hover)");
      b.addEventListener("mouseleave", () => b.style.background = "transparent");
      b.addEventListener("click", (e) => { e.stopPropagation(); m.remove(); onClick(); });
    }
    m.appendChild(b);
  }
  function sep() {
    const d = document.createElement("div");
    d.style.cssText = "height:1px;background:var(--border);margin:3px 0;";
    m.appendChild(d);
  }
  // Cross-tool jump (IUQ excluded — we're already here). Switches the
  // shell's view to the target tool, focused on this client.
  btn("🔎 Open in Audit",
      () => window.emsNavigateTo?.("audit", row.client || row.name || ""));
  btn("📸 Open in Snapshot",
      () => window.emsNavigateTo?.("snapshot", row.client || row.name || ""));
  sep();
  // Trello actions — "Open Trello card" is inline as a button, so
  // skip it in the ⋯ More menu but keep the other Trello entries.
  if (row.card_id) {
    if (!excl) {
      btn("Open Trello card",
          () => pywebview.api.open_url(row.card_url || `https://trello.com/c/${row.card_id}`),
          { iconImg: "../web_shared/trello.png" });
    }
    btn("📎 Trello attachments…",
        () => window.openTrelloAttachmentsModal({ cardId: row.card_id, client: row.client }));
    btn("🔄 Re-pin Trello card…", () => openIuqPin(row));
  } else {
    btn("📌 Pin existing Trello card…", () => openIuqPin(row));
    btn("➕ Create new Trello card", () => createTrelloCardForIuq(row.client));
  }
  sep();
  btn("📎 Pin folder…", () => openIuqFolderPin(row));
  // 📁 Open OD folder — inline button on the detail view, but keep
  // it in the row right-click menu (where there's no inline button).
  if (!excl) {
    btn("📁 Open OD folder", async () => {
      const res = await pywebview.api.open_od_for_client(
        row.client, row.path || row.od_path || "");
      if (res?.ok) {
        setStatus(`Opened ${row.client}` + (res.refreshed ? " · path refreshed" : ""), "ok");
      } else {
        setStatus(res?.error || `No folder for ${row.client}`, "warn");
      }
    });
  }
  btn("📂 Make folders", async () => {
    const res = await pywebview.api.make_folders(row.client);
    setStatus(res?.ok ? `📂 Scaffolded ${row.client}` : `Failed: ${res?.error || "?"}`,
              res?.ok ? "ok" : "error");
  });
  sep();
  btn("📐 Request Docusketch", async () => {
    if (!confirm(`Post Docusketch request comment on ${row.client}'s Trello card?`)) return;
    // Pass row.card_id — IUQ scan rows have a real Trello card_id
    // that often isn't persisted as the "pinned" card. Backend
    // accepts the explicit id and skips the persistence lookup.
    const r = await pywebview.api.request_docusketch(row.client, row.card_id || "");
    if (!r?.ok) { setStatus(`Docusketch failed: ${r?.error || "?"}`, "error"); return; }
    setStatus(r.posted ? "📐 Docusketch request posted" : "📐 Recorded — comment failed, post manually", "ok");
  }, { disabled: !row.card_id });
  // 📥 Import and 🗒 Notes are inline buttons — skip in the More menu.
  if (!excl) {
    btn("📥 Import…", () => openIuqImport(row), { disabled: !row.card_id });
  }
  if (!excl) {
    btn("🗒 Notes", () => openIuqNote(row));
  }
  // ✍ Send DocuSign was inline before; now in the More menu for both
  // entry points (it's a less-frequent action than the staged Initial
  // upload flow).
  btn("✍ Send DocuSign", () => openIuqDS(row));
  // 📂 Stage other PICS folder (Demo, Mold Prep, Post, etc.) — keep
  // out of the inline row to avoid two near-identical Stage buttons.
  btn("📂 Stage other PICS…", () => openCopyStagePicker(row));
  sep();
  // Per-client memory items — mirror the audit panel's right-click
  // (Tk job_widgets canonical menu). User preference: every row
  // workflow that exists in one panel mirrors in every other panel.
  btn("🏷 Edit search aliases…", () => openIuqSearchAliases(row));
  btn("🏢 Add to property…", () => openIuqAddToProperty(row));
  btn("🧹 Clear saved folder path", async () => {
    if (!confirm(`Clear the sticky folder pin for ${row.client}?`)) return;
    const r = await pywebview.api.clear_folder_path(row.client);
    setStatus(r?.ok ? `🧹 Cleared folder pin` : `Failed: ${r?.error || "?"}`,
              r?.ok ? "ok" : "error");
  });
  btn(`♻ Reset all memory for ${row.client}`, async () => {
    if (!confirm(`Wipe every sticky pin + flag for ${row.client}?\n` +
                 `Clears: folder pin, Trello pins, Commercial flag, aliases.`)) return;
    const r = await pywebview.api.reset_client_memory(row.client);
    setStatus(r?.ok ? `♻ Reset: ${(r.cleared || []).join(", ")}` : `Failed: ${r?.error || "?"}`,
              r?.ok ? "ok" : "error");
  });
  // ── Remove from the queue (auto-pulled rows; manual rows have their
  // own ✕ Remove). Dismiss persists by card_id; "Show dismissed" + this
  // menu's ↩ Restore brings it back.
  sep();
  if (row.dismissed) {
    btn("↩ Restore to queue", async () => {
      const r = await pywebview.api.undismiss(row.card_id);
      applyIuqRows(r);
      if (r?.ok) setStatus(`↩ Restored ${row.client}`, "ok");
    }, { disabled: !row.card_id });
  } else if (!row.manual) {
    btn("✕ Dismiss from queue", async () => {
      const r = await pywebview.api.dismiss(row.card_id);
      applyIuqRows(r);
      if (r?.ok) setStatus(`✕ Dismissed ${row.client} — “Show dismissed” to restore`, "ok");
    }, { disabled: !row.card_id });
  }
  document.body.appendChild(m);
  // Viewport clamp
  const r2 = m.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight, pad = 6;
  let l = ev.clientX, t = ev.clientY;
  if (l + r2.width + pad > vw)  l = Math.max(pad, vw - r2.width - pad);
  if (t + r2.height + pad > vh) t = Math.max(pad, vh - r2.height - pad);
  m.style.left = l + "px"; m.style.top = t + "px";
  m.style.visibility = "visible";
}
document.addEventListener("click", () => document.getElementById("iuq-ctx-menu")?.remove());

// ── 📎 Pin folder modal (find + change OneDrive folder) ─────────
// Mirrors the audit's Find/Change Folder dialog. Lists ranked
// year-folder candidates + lets the user filter by name + click to
// pin. The pin persists via persistence.set_folder_path so audit,
// snapshot, and IUQ all use the same folder for this client.
// ── Search aliases + property group modals (parity with audit) ──
async function openIuqSearchAliases(r) {
  const current = await pywebview.api.get_search_aliases(r.client) || [];
  const ov = mkModal({
    title: "🏷 Search aliases for " + r.client,
    sub:   "One alias per line. Each is matched anywhere the canonical name would be.",
    body: `
      <textarea id="al-text" rows="8" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;">${esc(current.join("\n"))}</textarea>
      <div class="modal-footer" style="margin-top:10px;">
        <button class="btn modal-close">Cancel</button>
        <button class="btn btn-primary" id="al-save">💾 Save aliases</button>
      </div>`,
  });
  ov.querySelector("#al-save").addEventListener("click", async () => {
    const lines = ov.querySelector("#al-text").value
      .split("\n").map((s) => s.trim()).filter(Boolean);
    const res = await pywebview.api.set_search_aliases(r.client, lines);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    closeModal();
    setStatus(`🏷 Saved ${lines.length} alias${lines.length !== 1 ? "es" : ""}`, "ok");
  });
  ov.querySelector("#al-text").focus();
}

async function openIuqAddToProperty(r) {
  const folder = await pywebview.api.get_pinned_folder(r.client) || "";
  if (!folder) {
    setStatus(`Pin a folder for ${r.client} first — property groups attach to folders`, "warn");
    return;
  }
  const folderBasename = folder.split(/[\\/]/).pop();
  const [groupsR, currentGroup] = await Promise.all([
    pywebview.api.list_property_groups(),
    pywebview.api.find_property_for_folder(folderBasename),
  ]);
  const existing = (groupsR?.groups || []);
  const ov = mkModal({
    title: currentGroup ? `🏢 Property group for ${r.client}` : `🏢 Add ${r.client} to a property`,
    sub:   currentGroup ? `Currently in: ${currentGroup}` : "Park this job under a multi-unit umbrella.",
    body: `
      ${currentGroup ? `
        <button class="btn" id="pg-remove" style="background:var(--red);color:#FFF;border-color:var(--red);">
          ✕ Remove from "${esc(currentGroup)}"
        </button>
        <hr style="border:none;border-top:1px solid var(--border);margin:14px 0;" />
      ` : ""}
      ${existing.length ? `
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:6px;">Existing</div>
        <div style="display:flex;flex-direction:column;gap:4px;max-height:200px;overflow-y:auto;margin-bottom:14px;">
          ${existing.map((g) => `
            <button class="btn pg-pick" data-name="${esc(g.name)}" style="text-align:left;justify-content:flex-start;">
              ${esc(g.name)} <span class="muted" style="font-size:10px;">(${g.folders.length})</span>
            </button>`).join("")}
        </div>` : ""}
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:6px;">+ New property</div>
      <div style="display:flex;gap:6px;">
        <input id="pg-new" class="search" type="text" placeholder="Property name" style="flex:1;" />
        <button class="btn btn-primary" id="pg-create">Create + add</button>
      </div>
      <div class="modal-footer" style="margin-top:14px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });
  ov.querySelector("#pg-remove")?.addEventListener("click", async () => {
    const res = await pywebview.api.remove_folder_from_property_group(currentGroup, folderBasename);
    if (!res?.ok) { setStatus(`Remove failed: ${res?.error || "?"}`, "error"); return; }
    closeModal();
    setStatus(`Removed from "${currentGroup}"`, "ok");
  });
  ov.querySelectorAll(".pg-pick").forEach((b) =>
    b.addEventListener("click", async () => {
      const res = await pywebview.api.add_folder_to_property_group(b.dataset.name, folderBasename);
      if (!res?.ok) { setStatus(`Add failed: ${res?.error || "?"}`, "error"); return; }
      closeModal();
      setStatus(`🏢 Added to "${b.dataset.name}"`, "ok");
    }));
  ov.querySelector("#pg-create")?.addEventListener("click", async () => {
    const name = ov.querySelector("#pg-new").value.trim();
    if (!name) return;
    const res = await pywebview.api.create_property_group(name, folderBasename);
    if (!res?.ok) { setStatus(`Create failed: ${res?.error || "?"}`, "error"); return; }
    closeModal();
    setStatus(`🏢 Created "${name}"`, "ok");
  });
  ov.querySelector("#pg-new")?.focus();
}

async function openIuqFolderPin(r) {
  const w = document.createElement("div");
  w.id = "iuq-folder-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  const currentPin = await pywebview.api.get_pinned_folder(r.client) || "";
  // Year-scope selector — same options as the audit panel's Find
  // Folder modal. Pre-fetched so the dropdown surfaces every option
  // (current year, older years, fire-job folders) before the modal
  // renders.
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
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(640px,94vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📎 Pin folder — ${esc(r.client)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
          ${currentPin
            ? `Currently pinned: <code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;">${esc(currentPin)}</code>`
            : "No folder pinned yet — pick one below or filter to find it."}
        </div>
      </header>
      <div style="padding:14px 18px;display:flex;flex-direction:column;gap:8px;">
        <div style="display:flex;gap:8px;align-items:center;">
          <label class="muted" style="font-size:11px;white-space:nowrap;">Search in:</label>
          <select id="fp-scope" class="search" style="flex:1;">${scopeOpts.join("")}</select>
        </div>
        <input id="fp-filter" class="search" type="text"
               placeholder="🔎 Filter candidates by name…" style="width:100%;" />
      </div>
      <div id="fp-list" style="padding:0 18px 12px;overflow-y:auto;max-height:50vh;"></div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        ${currentPin ? `<button class="btn" id="fp-clear">✕ Unpin current</button>` : ""}
        <span style="flex:1;"></span>
        <button class="btn" id="fp-cancel">Cancel</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  document.getElementById("fp-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });

  let all = [];
  let currentScope = "";
  async function reload(scope) {
    currentScope = scope || "";
    document.getElementById("fp-list").innerHTML =
      `<div style="color:var(--text-muted);padding:14px;font-size:12px;">Loading…</div>`;
    const res = await pywebview.api.list_folder_candidates(r.client, currentScope);
    if (!res?.ok) {
      document.getElementById("fp-list").innerHTML =
        `<div style="color:var(--red);padding:14px;">Error: ${esc(res?.error || "?")}</div>`;
      all = [];
      return;
    }
    all = res.candidates || [];
    render(document.getElementById("fp-filter").value || "");
  }
  document.getElementById("fp-scope").addEventListener("change", (e) =>
    reload(e.target.value));
  await reload("");
  function render(filter = "") {
    const q = filter.trim().toLowerCase();
    const shown = q ? all.filter((c) => c.name.toLowerCase().includes(q)) : all;
    document.getElementById("fp-list").innerHTML = shown.length
      ? shown.slice(0, 30).map((c) => `
          <div class="fp-row" data-path="${esc(c.path)}"
               style="display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;
                      padding:8px 12px;border-bottom:1px solid var(--border);cursor:pointer;">
            <span style="color:var(--text-muted);font-size:11px;font-variant-numeric:tabular-nums;">${c.year}</span>
            <div>
              <div style="font-weight:500;font-size:13px;">${esc(c.name)}</div>
              <div style="font-size:10px;color:var(--text-dim);font-family:monospace;">${esc(c.path)}</div>
            </div>
            <span style="font-size:11px;color:var(--green);font-weight:700;">${c.score}</span>
          </div>`).join("")
      : `<div style="text-align:center;color:var(--text-muted);padding:18px;font-size:12px;">No matches — try a different filter.</div>`;
    document.querySelectorAll(".fp-row").forEach((row) => {
      row.addEventListener("mouseenter", () => row.style.background = "var(--row-hover)");
      row.addEventListener("mouseleave", () => row.style.background = "transparent");
      row.addEventListener("click", async () => {
        const path = row.dataset.path;
        const r2 = await pywebview.api.pin_folder(r.client, path);
        if (!r2?.ok) { setStatus(`Pin failed: ${r2?.error || "?"}`, "error"); return; }
        close();
        setStatus(`📎 Pinned ${path}`, "ok");
      });
    });
  }
  render();
  document.getElementById("fp-filter").addEventListener("input",
    (e) => render(e.target.value));
  document.getElementById("fp-filter").focus();
  const clearBtn = document.getElementById("fp-clear");
  if (clearBtn) clearBtn.addEventListener("click", async () => {
    await pywebview.api.clear_folder_pin(r.client);
    close();
    setStatus("📎 Unpinned folder", "ok");
  });
}

// ── 📂 Stage PICS for XA — subfolder picker modal ───────────────
// Lets the user pick which PICS subfolder (Initial / Demo / Mold
// Prep / Post / etc.) to stage into a temp folder for XA drag-
// and-drop. Backend resolves the job folder via persistence pin
// + auto-deletes the temp folder after 5 min.
async function openCopyStagePicker(r) {
  const info = await pywebview.api.list_pics_stages(r.client);
  if (!info?.ok) {
    setStatus(`Stage list failed: ${info?.error || "?"}`, "warn");
    return;
  }
  const stages = info.stages || [];
  if (!stages.length) {
    setStatus(`No PICS subfolders with images for ${r.client}`, "warn");
    return;
  }
  const ov = mkModal({
    title: "📂 Stage PICS for XA",
    sub:   `${r.client} · pick a stage — files copy into a TEMP folder + open Explorer · drag into XA · auto-deletes after 1 min`,
    body: `
      <div style="display:flex;flex-direction:column;gap:6px;max-height:50vh;overflow-y:auto;">
        ${stages.map((s) => `
          <button class="action-btn cp-stage" data-stage="${esc(s.name)}"
                  style="text-align:left;justify-content:flex-start;display:flex;">
            <span style="flex:1;">📁 ${esc(s.name)}</span>
            <span class="muted" style="font-size:11px;">${s.count} image${s.count !== 1 ? "s" : ""}</span>
          </button>`).join("")}
      </div>
      <div class="modal-footer" style="margin-top:14px;">
        <button class="btn modal-close">Cancel</button>
      </div>`,
  });
  ov.querySelectorAll(".cp-stage").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const stage = btn.dataset.stage;
      btn.disabled = true; btn.textContent = "Copying…";
      const res = await pywebview.api.copy_pics_to_clipboard(r.client, stage);
      if (!res?.ok) {
        setStatus(`Copy failed: ${res?.error || "?"}`, "error");
        btn.disabled = false;
        return;
      }
      closeModal();
      const matched = res.matched_stage || stage;
      setStatus(`📂 Staged ${res.count} image${res.count !== 1 ? "s" : ""} from ${matched} → ${res.folder} · drag into XA · auto-deletes at ${res.deletes_at}`, "ok");
    }));
}
