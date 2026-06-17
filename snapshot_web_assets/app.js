/* EMS Tools — Snapshot web frontend.
 *
 * Two views in one page:
 *  • LIST view (default): candidates (closeout + run-doc) + recent PDFs
 *  • GENERATE view: form to fill out + write the snapshot PDF
 *
 * Generation runs entirely in the web — same backend (fill_pdf,
 * append_overflow_pages) but no Tk involvement.
 */
"use strict";
const state = { view: "list", current: null, importBtn: null };

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const pad2 = (n) => String(n).padStart(2, "0");

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
  $("#view-list-btn").addEventListener("click", () => switchTo("list"));
  $("#view-gen-btn").addEventListener("click", () => startNew());
  $("#refresh-btn").addEventListener("click", loadList);
  attachTopbarTrelloSearch();
  $("#gen-cancel").addEventListener("click", () => switchTo("list"));
  $("#gen-go").addEventListener("click", generate);
  $("#gen-find").addEventListener("click", openFindCardModal);
  $("#gen-audit").addEventListener("click", runSnapshotAudit);
  $("#parse-comments-btn").addEventListener("click", parseTrelloComments);
  $("#audit-run-btn").addEventListener("click", runSnapshotAudit);
  $("#gen-scope").addEventListener("click", openScopeModal);
  $("#gen-docusign-email").addEventListener("click", copyDocusignEmail);
  // After-generate buttons (post-actions panel)
  $("#post-trello-btn").addEventListener("click", postToTrello);
  $("#mark-drafted-btn").addEventListener("click", markDrafted);
  $("#open-pdf-btn").addEventListener("click",
    () => state.lastPdfPath && pywebview.api.open_pdf(state.lastPdfPath));
  document.querySelectorAll(".add-row-btn").forEach((b) =>
    b.addEventListener("click", () => addRow(b.dataset.tbl, {})));
  // Snapshot list-view tabs (Today vs Tracked)
  document.querySelectorAll("#snap-tabs .tab-btn").forEach((b) =>
    b.addEventListener("click", () => snapshotShowTab(b.dataset.tab)));
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
  // Deep-link from another tool's "Open in → Snapshot": open the
  // Tracked tab filtered to that client.
  const _focus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";
  if (_focus) {
    state._trackedLoaded = true;       // suppress snapshotShowTab's own load
    snapshotShowTab("tracked");
    await loadTrackedSnapshots();
    const tb = $("#tracked-search");
    if (tb) tb.value = _focus;
    trackedState.search = _focus;
    renderTracked();
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

async function loadList() {
  const cands = await pywebview.api.candidate_jobs() || [];
  const candsEl = $("#candidates");
  // One-click flow: clicking ANYWHERE on the row opens the form with
  // the Trello card already parsed in (carrier/claim/DOL/cause/
  // first-visit/subs/logs/scope). User was complaining about having
  // to click 3 different buttons — Snapshot, then Find Trello, then
  // a result — to get the form filled. Now the row click does it all.
  candsEl.innerHTML = cands.length
    ? cands.map((r) => `
        <div class="closeout-row snap-cand" data-client="${esc(r.client)}" data-card="${esc(r.card_id || "")}" style="cursor:pointer;">
          <div>
            <div class="name">${esc(r.client)}</div>
            <div class="sub">
              <span class="candidate-pill ${r.source === "estimating" ? "rundoc" : (r.source === "run-doc" ? "rundoc" : "closeout")}">${esc(r.lane || r.source)}</span>
              ${r.board ? `<span class="muted" style="font-size:10px;">${esc(r.board)}</span>` : ""}
              ${r.card_id ? "· Pinned" : ""}
            </div>
          </div>
          ${r.card_id ? `<button class="btn snap-trello-btn" data-url="https://trello.com/c/${esc(r.card_id)}" style="font-size:11px;">🔗</button>` : "<span></span>"}
          <button class="btn btn-primary" data-new="${esc(r.client)}" data-card="${esc(r.card_id || "")}">📸 Snapshot</button>
        </div>`).join("")
    : `<div class="empty-inline">No cards in the Estimating board's SNAPSHOT lane. Click ＋ New snapshot in the top bar to type a name manually, or search Trello via the search box above.</div>`;
  // Whole-row click → open form with Trello prefill (when card_id present)
  candsEl.querySelectorAll(".snap-cand").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-url]") || e.target.closest("[data-new]")) return;
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

  const data = await pywebview.api.recent_snapshots(50);
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
  $("#status-counts").textContent = `${cands.length} queued · ${data.rows.length} recent PDFs`;
  // Refresh the tracked-tab badge in parallel (cheap)
  refreshTrackedCountBadge();
}

// ── Tab switching ───────────────────────────────────────────────
function snapshotShowTab(tab) {
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
      <td>${yesNo(r.inspection)}</td>
      <td>${yesNo(r.scope)}</td>
      <td>${yesNo(r.final_photos)}</td>
      <td>${fmtDate(r.closing)}</td>
      <td style="text-align:right;"><button class="btn tracked-edit" data-name="${esc(r.name)}" title="Edit values / move to another sheet" style="padding:2px 8px;font-size:12px;">✎</button></td>
    </tr>`).join("");
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
  { key: "inspection",     col: "Inspection",     label: "Inspection" },
  { key: "scope",          col: "Scope",          label: "Scope" },
  { key: "final_photos",   col: "Final Photos",   label: "Final Photos" },
  { key: "initial_photos", col: "Initial Photos", label: "Initial Photos" },
  { key: "demo_start",     col: "Demo Start",     label: "Demo Start" },
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

async function startNew(client = "", cardId = "") {
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

  if (client) {
    // When we have a card_id (search result picked) use the full
    // Trello parser — pulls carrier/claim/DOL/first-visit/cause
    // from card desc + paged comments. Falls back to plain run-doc
    // prefill when the user typed a name without picking a card.
    setStatus(cardId ? "Parsing Trello card + comments…" : "Loading prefill…");
    const fill = cardId
      ? await pywebview.api.prefill_from_trello_card(cardId, client)
      : await pywebview.api.prefill_for(client);
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
  } else {
    $("#f-insured").focus();
  }

  // Ensure at least one empty row in each table so the user can start typing
  if (!$("#subs-body").children.length) addRow("subs", {});
  if (!$("#logs-body").children.length) addRow("logs", {});
}

function addRow(tableKey, prefill) {
  const tr = document.createElement("tr");
  // Drag is gated behind the ⠿ handle — only mousedown on the
  // col-drag cell sets draggable=true. Otherwise typing inside an
  // input would accidentally start a drag and steal text selection.
  tr.draggable = false;
  tr.innerHTML = `
    <td class="col-drag" title="Drag this handle to reorder" style="cursor:grab;user-select:none;">⋮⋮</td>
    <td><input type="text" data-k="date"     value="${esc(prefill.date || "")}"     placeholder="5/22/26" /></td>
    <td><input type="text" data-k="weekday"  value="${esc(prefill.weekday || "")}"  placeholder="Fri" /></td>
    <td><input type="text" data-k="activity" value="${esc(prefill.activity || "")}" placeholder="Demo / Monitor / etc." /></td>
    <td><input type="text" data-k="techs"    value="${esc(prefill.techs || "")}"    placeholder="ME, JG" /></td>
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
    return out;
  }).filter((r) => r.date || r.activity || r.techs);  // skip blank rows
}

async function generate() {
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
      if (picked && picked !== insured) {
        insured = picked;
        $("#f-insured").value = picked;      // rewrite for clarity
      }
    }
  } catch (_) { /* fall through — degrade to single-unit generate */ }
  const payload = {
    insured,
    carrier:     $("#f-carrier").value,
    dol:         $("#f-dol").value,
    first_visit: $("#f-first").value,
    cause:       $("#f-cause").value,
    subs: collectRows("subs"),
    logs: collectRows("logs"),
  };
  const btn = $("#gen-go");
  btn.disabled = true; btn.textContent = "Generating…";
  $("#gen-status").textContent = "Writing PDF…";
  $("#gen-status").className = "";
  try {
    const res = await pywebview.api.generate(payload);
    if (!res?.ok) {
      $("#gen-status").textContent = "Failed: " + (res?.error || "?");
      $("#gen-status").className = "error";
      return;
    }
    $("#gen-status").innerHTML =
      `✓ Saved to <code>${esc(res.path)}</code> · ${res.rows_logs} log rows, ${res.rows_subs} subs`;
    $("#gen-status").className = "ok";
    state.lastPdfPath = res.path;
    state.lastClient = insured;
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
    setStatus(`Post failed: ${res?.error || "?"}`, "error");
    btn.textContent = "Attach PDF + post comment to Trello";
    return;
  }
  const bits = [];
  if (res.attached) bits.push("PDF attached");
  if (res.posted)   bits.push("comment posted");
  btn.textContent = "✓ " + bits.join(" + ");
  setStatus("✓ Posted to Trello", "ok");
}

async function markDrafted() {
  if (!state.lastClient) return;
  const btn = $("#mark-drafted-btn");
  btn.disabled = true; btn.textContent = "Marking…";
  const res = await pywebview.api.mark_closeout_drafted(state.lastClient);
  btn.disabled = false;
  if (!res?.ok) {
    setStatus(`Mark drafted failed: ${res?.error || "?"}`, "error");
    btn.textContent = "🏁 Mark drafted (clear from closeout queue)";
    return;
  }
  btn.textContent = "✓ Marked drafted";
  setStatus("🏁 Marked as drafted — cleared from closeout queue", "ok");
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
  const chips = [];
  if (row.flagged) chips.push(`<span class="detail-chip missing">${row.total_missing} missing</span>`);
  else chips.push(`<span class="detail-chip ok">✓ clean</span>`);
  if (row.aging_days >= 3) {
    const hot = row.aging_days >= 7 ? "hot" : "";
    chips.push(`<span class="detail-chip aging ${hot}">⏰ ${row.aging_days}d aging</span>`);
  }
  if (!row.found) chips.push(`<span class="detail-chip not-found">⚠ Folder not found</span>`);
  if (row.new_loss) chips.push(`<span class="detail-chip new-loss">🆕 New loss</span>`);
  if ((row.sharepoint_new || 0) > 0) {
    chips.push(`<span class="detail-chip sp-new" data-act="sp-import"
                title="Click to import — ${row.sharepoint_new} files on SharePoint">📥 SP +${row.sharepoint_new} new</span>`);
  }
  chips.push(`<span class="detail-chip commercial-chip ${row.is_commercial ? "on" : ""}" data-act="commercial">
              🏢 ${row.is_commercial ? "Commercial" : "Mark commercial"}
            </span>`);
  for (const a of row.activity || []) {
    chips.push(`<span class="detail-chip activity" data-act-name="${esc(a)}">${esc(a)}</span>`);
  }

  const forms = row.form_issues?.length ? `
    <div class="audit-issue-group">
      <div class="audit-issue-lbl">📋 Missing forms (${row.form_issues.length})</div>
      <ul class="audit-issue-list">
        ${row.form_issues.map((x) => `<li>${esc(x)}</li>`).join("")}
      </ul>
    </div>` : "";
  const photos = row.photo_issues?.length ? `
    <div class="audit-issue-group">
      <div class="audit-issue-lbl">📷 Missing photos (${row.photo_issues.length})</div>
      <ul class="audit-issue-list photos">
        ${row.photo_issues.map((x) => `<li>${esc(x)}</li>`).join("")}
      </ul>
    </div>` : "";
  // Misfiled — present elsewhere in the parent tree (wrong folder), not
  // missing. The campus folder is checked first; these only show when a
  // sibling/parent folder had the item. Fix is to MOVE it here.
  const misItems = [
    ...(row.misplaced_forms  || []).map((m) => ({ ...m, icon: "📋" })),
    ...(row.misplaced_photos || []).map((m) => ({ ...m, icon: "📷" })),
  ];
  const misplaced = misItems.length ? `
    <div class="audit-issue-group">
      <div class="audit-issue-lbl">⚠ Misfiled — wrong folder (${misItems.length})</div>
      <ul class="audit-issue-list misplaced">
        ${misItems.map((m) => `<li>${m.icon} ${esc(m.label)} — <span class="muted">in <code>${esc(m.where || "parent")}</code></span></li>`).join("")}
      </ul>
    </div>` : "";
  const meta = `
    <div class="audit-meta">
      <span class="label">Folder</span>
      <span class="value">${esc(row.folder || "—")}</span>
      <span class="label">Path</span>
      <span class="value">${esc(row.path || "—")}</span>
      ${row.last_seen ? `
        <span class="label">Last activity</span>
        <span class="value">${esc(row.last_seen)}</span>` : ""}
      ${row.trello_card_id ? `
        <span class="label">Trello card</span>
        <span class="value">${esc(row.trello_card_id)}</span>` : ""}
    </div>`;
  const hasPath = !!row.path;
  const hasPin  = !!row.trello_card_id;
  const hasSP   = (row.sharepoint_new || 0) > 0;
  const actions = `
    <footer class="detail-actions">
      <button class="action-btn primary" data-act="open-folder" ${hasPath ? "" : "disabled"}>📁 OD folder</button>
      <button class="action-btn" data-act="open-trello" ${hasPin ? "" : "disabled"}>
        <img src="../web_shared/trello.png" alt=""/>Trello</button>
      <button class="action-btn" data-act="open-xa" ${hasPin ? "" : "disabled"}>
        <img src="../web_shared/xactanalysis.png" alt="" onerror="this.remove()"/>XA</button>
      <button class="action-btn" data-act="open-companycam" ${hasPin ? "" : "disabled"}
              title="Open this job's CompanyCam project (reads the CompanyCam link from the Trello card)">
        <img src="../web_shared/companycam.png" alt="" onerror="this.remove()"/>CompanyCam</button>
      <button class="action-btn" data-act="attachments" ${hasPin ? "" : "disabled"} title="Browse + download the Trello card's photos/files">📎 Attachments</button>
      <button class="action-btn" data-act="sp-import">📥 Import SP${hasSP ? ` +${row.sharepoint_new}` : ""}</button>
      <button class="action-btn" data-act="wc-import" title="Import from Downloads — WorkCenter, DocuSign, DocuSketch, or pick any file (outside SharePoint)">🗂 Import</button>
      <button class="action-btn" data-act="find-folder">${row.found ? "🔀 Change folder" : "🔎 Find folder"}</button>
      <button class="action-btn" data-act="pin-card">📌 Pin Trello</button>
      <button class="action-btn" data-act="comment" ${hasPin ? "" : "disabled"}>💬 Comment</button>
      <button class="action-btn" data-act="docusketch" ${hasPin ? "" : "disabled"}>📐 Docusketch</button>
      <button class="action-btn" data-act="match-diag">🔎 Match diagnostic</button>
      <button class="action-btn" data-act="reaudit">↻ Re-audit</button>
      <button class="action-btn" data-act="closeout"
              title="Open the CLOSE OUT checklist for this client's Trello card — toggle items inline, syncs to Trello"
              style="background:var(--amber);color:#FFF;border-color:var(--amber);">📋 CLOSE OUT</button>
    </footer>`;
  const cleanBlock = (row.found && !row.flagged && !misItems.length) ?
    `<div class="audit-clean">✓ All required forms + photos present.</div>` : "";

  result.innerHTML =
    `<div class="detail-chip-row">${chips.join(" ")}</div>` +
    meta + forms + photos + misplaced + cleanBlock + actions;

  // Wire chips + buttons
  result.querySelectorAll("[data-act]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      onAuditAction(el.dataset.act, row);
    });
  });
  // Right-click anywhere in the audit result → full context menu
  result.addEventListener("contextmenu", (e) => showSnapshotAuditCtxMenu(e, row));
  // Hover the Trello button → shared popover (same 60s cache as audit)
  const trelloBtn = result.querySelector('[data-act="open-trello"]');
  if (trelloBtn && row.trello_card_id && window.attachTrelloHover) {
    window.attachTrelloHover(trelloBtn, row.trello_card_id);
  }
  // Right-click the Trello button → 📌 Pin/Change pinned card.
  // Mirrors the OD-folder right-click pattern. Works even when the
  // button is disabled (no card pinned yet) — that's exactly when
  // "Pin Trello card" is the most useful action.
  if (trelloBtn) {
    trelloBtn.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onAuditAction("pin-card", row);
    });
  }
  // Mirror the same pattern on the OD folder button — "Find folder"
  // when not resolved, "Change folder" when resolved.
  const folderBtn = result.querySelector('[data-act="open-folder"]');
  if (folderBtn) {
    folderBtn.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onAuditAction("find-folder", row);
    });
  }
}

async function onAuditAction(act, row) {
  switch (act) {
    case "open-folder":
      if (row.path) pywebview.api.open_folder(row.path); break;
    case "open-trello":
      if (row.trello_card_id) pywebview.api.open_trello_card(row.trello_card_id); break;
    case "open-xa":
      pywebview.api.open_xa_link(row.client); break;
    case "open-companycam": {
      const ok = await pywebview.api.open_companycam_link(row.client);
      if (!ok) setStatus("No CompanyCam link on this card yet — add a 'CompanyCam Link' to the Trello card.", "warn");
      break;
    }
    case "sp-import":
      openSnapshotSpImport(row); break;
    case "wc-import":
      openSnapshotWcImport(row); break;
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

function showSnapshotAuditCtxMenu(ev, row) {
  ev.preventDefault(); ev.stopPropagation();
  document.getElementById("snap-audit-ctx")?.remove();
  const m = document.createElement("div");
  m.id = "snap-audit-ctx";
  m.className = "ctx-menu";
  m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
    background:var(--surface);border:1px solid var(--border);border-radius:6px;
    box-shadow:0 6px 20px rgba(0,0,0,.4);z-index:200;min-width:240px;overflow:hidden;`;
  const items = [
    { lbl: "📁 Open OD folder", act: "open-folder", off: !row.path },
    { lbl: row.found ? "🔀 Change folder…" : "🔎 Find folder…", act: "find-folder" },
    { lbl: "Pin Trello card", act: "pin-card",
      iconImg: "../web_shared/trello.png" },
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
    { lbl: "💬 Post comment", act: "comment", off: !row.trello_card_id },
    { lbl: "📐 Request Docusketch", act: "docusketch", off: !row.trello_card_id },
    { sep: true },
    { lbl: "📋 CLOSE OUT checklist…", act: "closeout" },
    { lbl: "🔎 Match diagnostic", act: "match-diag" },
    { lbl: "↻ Re-audit this job", act: "reaudit" },
    { sep: true },
    // Per-client memory items — mirror audit panel's right-click
    { lbl: "🏷 Edit search aliases…", act: "aliases" },
    { lbl: "🏢 Add to property…", act: "property",
      off: !row.folder },
    { lbl: "🧹 Clear saved folder path", act: "clear-folder",
      off: !row.path },
    { lbl: "🏢 Clear Commercial flag", act: "clear-commercial",
      off: !row.is_commercial },
    { lbl: `♻ Reset all memory for ${row.client}`, act: "reset-memory" },
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
    b.addEventListener("click", () => { m.remove(); onAuditAction(it.act, row); });
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
      <div id="ff-hits" class="muted">Loading candidates…</div>
      <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
        <button class="btn modal-close">Close</button>
      </div>`,
  });

  async function loadAt(scope) {
    wrap.querySelector("#ff-hits").innerHTML = `<div class="muted">Loading…</div>`;
    const r = await pywebview.api.list_folder_candidates(row.client, scope || "");
    const cands = r?.candidates || [];
    wrap.querySelector("#ff-hits").innerHTML = cands.length
      ? cands.map((c) => `
          <div class="pdf-row" data-path="${esc(c.path)}" style="cursor:pointer;">
            <div class="pdf-name">${c.is_fire ? "🔥 " : ""}${esc(c.name)}</div>
            <div class="pdf-meta">${esc(c.year_folder || "")} · ${esc(c.path)}</div>
          </div>`).join("")
      : `<div class="muted">No candidates found.</div>`;
    wrap.querySelectorAll("[data-path]").forEach((el) =>
      el.addEventListener("click", async () => {
        const res = await pywebview.api.pin_folder(row.client, el.dataset.path);
        if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
        wrap.remove();
        setStatus(`📁 Pinned ${row.client} → ${el.dataset.path}`, "ok");
        await runSnapshotAudit();
      }));
  }
  wrap.querySelector("#ff-scope").addEventListener("change",
    (e) => loadAt(e.target.value));
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
      const bg = it.complete ? "rgba(46,139,87,.08)" : "var(--surface-2)";
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
      <div class="modal-footer" style="display:flex;gap:8px;margin-top:10px;">
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
            const r2 = await pywebview.api.sp_copy_to_pics(row.client, m.path, "", row.path || "");
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
      <div class="modal-footer" style="display:flex;gap:8px;margin-top:14px;">
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
    btn.disabled = true; btn.textContent = "Picking…";
    state.importBtn = btn;
    try {
      const res = await pywebview.api.pick_and_import_file(row.client, dest);
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
      if (c.kind === "companycam" || c.kind === "wc_attachments") {
        const choice = await window.pickPicsStage({ client: row.client, allowAuto: true });
        if (choice === null) return;                 // cancelled
        dest = choice === "AUTO" ? "" : choice;
      }
      b.disabled = true; b.textContent = "Extracting…";
      state.importBtn = b;
      try {
        const res = await pywebview.api.do_import(row.client, c.kind, c.paths, dest);
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
//   • a string (new insured to use) when user picks a unit
//   • the original insured when user picks "roll up the property"
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
      () => close(mu.property_name));
    document.getElementById("mu-units").innerHTML = (mu.units || []).map((u) => `
      <button class="btn mu-unit"
              data-display="${esc(u.display_name || "")}"
              style="text-align:left;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
        <span>${esc(u.display_name || ("Unit " + u.unit_number))}</span>
        <span style="font-size:10px;color:var(--text-muted);font-variant-numeric:tabular-nums;">
          ${esc(u.unit_number || "")}
        </span>
      </button>`).join("");
    document.querySelectorAll(".mu-unit").forEach((b) =>
      b.addEventListener("click", () => close(b.dataset.display)));
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
