"use strict";
const state = { rows: [], statuses: [], status: "all", search: "",
  sort_key: "_status", sort_dir: "asc" };
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

window.addEventListener("pywebviewready", async () => {
  // Restore the view you left: status chip, search text and sort.
  await PanelState.init("disputes");
  state.status   = PanelState.get("status", state.status);
  state.search   = PanelState.get("search", "");
  state.sort_key = PanelState.get("sort_key", state.sort_key);
  state.sort_dir = PanelState.get("sort_dir", state.sort_dir);
  const _sb = $("#search-box"); if (_sb) _sb.value = state.search;

  $("#refresh-btn").addEventListener("click", load);
  $("#open-excel-btn").addEventListener("click", () => pywebview.api.open_workbook());
  $("#location-btn").addEventListener("click", openLocationModal);
  $("#new-btn").addEventListener("click", () => openDisputeModal(null));
  $("#paste-btn").addEventListener("click", openPasteDisputeModal);
  $("#sync-trello-btn").addEventListener("click", async () => {
    const r = await pywebview.api.sync_from_trello();
    if (!r?.started) setStatus(`Sync busy: ${r?.reason || "?"}`, "warn");
    else setStatus("🔄 Syncing from Trello…");
  });
  $("#export-pdf-btn").addEventListener("click", async () => {
    const btn = $("#export-pdf-btn");
    btn.disabled = true; const orig = btn.textContent;
    btn.textContent = "Generating…";
    const r = await pywebview.api.export_pdf();
    btn.disabled = false; btn.textContent = orig;
    if (!r?.ok) { setStatus(`Export failed: ${r?.error || "?"}`, "error"); return; }
    setStatus(`📄 PDF saved · ${r.rows} rows · ${r.path}`, "ok");
  });
  window.addEventListener("disputes:sync-progress", (ev) => {
    const d = ev.detail || {};
    setStatus(`🔄 Syncing ${d.i || 0}/${d.n || "?"} · ${d.name || "…"}`);
  });
  window.addEventListener("disputes:sync-done", async (ev) => {
    const d = ev.detail || {};
    if (d.ok) {
      const r = d.result || {};
      setStatus(`✓ Sync complete — ${r.added || 0} new · ${r.updated || 0} updated`, "ok");
      await load();
    } else {
      setStatus(`Sync failed: ${d.error || "?"}`, "error");
    }
  });
  $("#search-box").addEventListener("input", (e) => {
    state.search = e.target.value;
    PanelState.set({ search: state.search });
    render();
  });
  $$("#tbl thead th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => sortBy(th.dataset.sort))
  );
  await load();
  // Auto-refresh every 5 minutes when visible — Excel mtime read is cheap
  setInterval(() => { if (document.visibilityState === "visible") load(); }, 300_000);
});

async function load() {
  const data = await pywebview.api.all_disputes();
  state.rows = data.rows || [];
  state.statuses = data.statuses || [];
  state.workbook = data.workbook || "";
  const wp = $("#workbook-path");
  if (wp) wp.textContent = state.workbook ? `📁 ${state.workbook}` : "";
  renderChips();
  render();
}

function renderChips() {
  const counts = { all: state.rows.length };
  for (const r of state.rows) counts[r._status] = (counts[r._status] || 0) + 1;
  const chips = [{ key: "all", label: "All" }, ...state.statuses.map((s) => ({ key: s, label: s }))];
  $("#status-chips").innerHTML = chips.map((c) =>
    `<button class="filter ${c.key === state.status ? "active" : ""}" data-status="${esc(c.key)}">${esc(c.label)} <span class="muted">${counts[c.key] || 0}</span></button>`
  ).join("");
  $$(".filter").forEach((b) => b.addEventListener("click", () => {
    state.status = b.dataset.status;
    PanelState.set({ status: state.status });
    renderChips();
    render();
  }));
}

function filtered() {
  const q = state.search.trim().toLowerCase();
  return state.rows.filter((r) => {
    if (state.status !== "all" && r._status !== state.status) return false;
    if (!q) return true;
    return [r._claim, r._insured, r._franchise, r._status].join(" ").toLowerCase().includes(q);
  }).sort((a, b) => {
    const av = a[state.sort_key] ?? "", bv = b[state.sort_key] ?? "";
    const dir = state.sort_dir === "asc" ? 1 : -1;
    return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
  });
}

function render() {
  const rows = filtered();
  $("#empty").classList.toggle("hidden", rows.length > 0);
  $("#tbody").innerHTML = rows.map((r) => `
    <tr>
      <td><span class="status-pill" data-status="${esc(r._status)}">${esc(r._status || "—")}</span></td>
      <td>${esc(r._claim)}</td>
      <td>${esc(r._insured)}</td>
      <td>${esc(r._franchise)}</td>
      <td class="num">${esc(r._amount)}</td>
      <td style="white-space:nowrap;">
        ${r._card_id ? `<span class="row-act" data-card="${esc(r._card_id)}"><img src="../web_shared/trello.png" alt="" style="width:13px;height:13px;vertical-align:middle;margin-right:4px;" />Trello</span>` : ""}
        ${r._card_id ? `<span class="row-act xa-link" data-card="${esc(r._card_id)}" title="Open the XactAnalysis link attached to this Trello card" style="margin-left:6px;"><img src="../web_shared/xactanalysis.png" alt="XA" style="width:13px;height:13px;vertical-align:middle;margin-right:4px;" onerror="this.remove()" />XA</span>` : ""}
      </td>
    </tr>`).join("");
  $$(".row-act").forEach((s) => s.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (s.classList.contains("xa-link")) {
      // Resolve the XA link via the Trello card's attachments —
      // not all dispute cards have one, but tc.card_xa_link returns
      // "" gracefully when not found.
      const url = await pywebview.api.xa_link_for(s.dataset.card);
      if (url) pywebview.api.open_url(url);
      else setStatus("No XA link on this card", "warn");
    } else {
      pywebview.api.open_url(`https://trello.com/c/${s.dataset.card}`);
    }
  }));
  // Double-click any row → open edit dialog with the row pre-filled.
  // Right-click → context menu with quick status / ack / delete
  // (mirrors Tk dispute_tracker_gui.py:580 _on_row_right_click).
  // Also attach the shared Trello hover popover so the user can
  // peek at the linked card without opening Trello.
  $$("#tbody tr").forEach((tr, ix) => {
    const row = filtered()[ix];
    tr.addEventListener("dblclick", () => {
      if (row) openDisputeModal(row);
    });
    tr.addEventListener("contextmenu", (e) => {
      if (row) showDisputeCtxMenu(e, row);
    });
    tr.style.cursor = "pointer";
    if (row?._card_id && window.attachTrelloHover) {
      window.attachTrelloHover(tr, row._card_id);
    }
  });
  $("#status-counts").textContent = `${rows.length} shown · ${state.rows.length} total`;
  $$("#tbl thead th").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === state.sort_key)
      th.classList.add(state.sort_dir === "asc" ? "sort-asc" : "sort-desc");
  });
}

function sortBy(k) {
  if (state.sort_key === k) state.sort_dir = state.sort_dir === "asc" ? "desc" : "asc";
  else { state.sort_key = k; state.sort_dir = "asc"; }
  PanelState.set({ sort_key: state.sort_key, sort_dir: state.sort_dir });
  render();
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// ── Right-click context menu (mirrors Tk dispute_tracker_gui.py:580) ──
// Items: ✎ Edit row · per-status quick transition · ✓/↶ Ack toggle
// · 🗑 Delete (with confirm). Each calls a backend quick_* helper so
// Excel-locked writes are queued the same way Tk handles them.
async function showDisputeCtxMenu(ev, row) {
  // Uses the shared web_shared/ctx_menu.js builder. The Status →
  // X transitions are split into a hover-expand submenu so the
  // base menu stays short.
  const statuses = await pywebview.api.status_choices() || [];
  const curStatus = (row._status || "").trim();
  const ackVal = (row.Ack || row.ack || row._ack || "").trim().toLowerCase();
  const claim = row._claim || "";
  const insured = row._insured || "";

  const statusItems = statuses.filter((s) => s !== curStatus).map((s) => ({
    label: `→ ${s}`,
    action: async () => {
      const r = await pywebview.api.quick_set_status(claim, insured, s);
      if (!r?.ok) setStatus(`Update failed: ${r?.error || "?"}`, "error");
      else { setStatus(`✓ Status → ${s}`, "ok"); await load(); }
    },
  }));

  showContextMenu(ev, [
    { label: "✎ Edit row…", action: () => openDisputeModal(row) },
    { sep: true },
    { label: "Status", submenu: statusItems.length ? statusItems
      : [{ label: "(no other statuses)", disabled: true, action: () => {} }] },
    ackVal === "yes"
      ? { label: "↶ Un-mark Ack",
          action: async () => {
            const r = await pywebview.api.quick_set_ack(claim, insured, "No");
            if (!r?.ok) setStatus(`Update failed: ${r?.error || "?"}`, "error");
            else { setStatus("↶ Un-marked Ack", "ok"); await load(); }
          } }
      : { label: "✓ Mark Ack Email Sent",
          action: async () => {
            const r = await pywebview.api.quick_set_ack(claim, insured, "Yes");
            if (!r?.ok) setStatus(`Update failed: ${r?.error || "?"}`, "error");
            else { setStatus("✓ Marked Ack", "ok"); await load(); }
          } },
    { sep: true },
    { label: "🗑 Delete row",
      color: "var(--red)",
      action: async () => {
        const name = insured || claim || "(blank)";
        if (!confirm(`Permanently blank the row for:\n\n${name}\n\nThis clears the row in the workbook — undo isn't automatic.`)) return;
        const r = await pywebview.api.delete_dispute(claim, insured);
        if (!r?.ok) setStatus(`Delete failed: ${r?.error || "?"}`, "error");
        else { setStatus("🗑 Row deleted", "ok"); await load(); }
      } },
  ]);
}

// ── New / Edit dispute modal (P1) ──────────────────────────────
// Paste a carrier billing-dispute email → live-parse line adjustments +
// totals → add to the tracker. Backed by preview_dispute_email /
// add_dispute_from_email.
async function openPasteDisputeModal() {
  const lbl = "font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);";
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(640px,94vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📋 Paste dispute email</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Paste the carrier's billing-dispute email — line adjustments + totals parse automatically.</div>
      </header>
      <div style="padding:16px 20px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;">
        <textarea id="pd-text" rows="8" placeholder="Paste the email here…" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px;font-family:monospace;font-size:12px;resize:vertical;"></textarea>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <label style="display:flex;flex-direction:column;gap:4px;"><span style="${lbl}">Insured *</span><input id="pd-insured" class="search" type="text" placeholder="Last, First" /></label>
          <label style="display:flex;flex-direction:column;gap:4px;"><span style="${lbl}">Claim #</span><input id="pd-claim" class="search" type="text" /></label>
        </div>
        <div id="pd-preview" style="font-size:12px;color:var(--text-muted);white-space:pre-wrap;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:10px;min-height:40px;">Preview appears here…</div>
      </div>
      <footer style="padding:12px 20px;border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="pd-cancel">Cancel</button>
        <button class="btn btn-primary" id="pd-add" disabled>➕ Add to tracker</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  wrap.querySelector("#pd-cancel").addEventListener("click", close);
  const txt = wrap.querySelector("#pd-text");
  const insEl = wrap.querySelector("#pd-insured");
  const clmEl = wrap.querySelector("#pd-claim");
  const prev = wrap.querySelector("#pd-preview");
  const addBtn = wrap.querySelector("#pd-add");
  let timer = null;
  const doPreview = async () => {
    const t = txt.value.trim();
    if (!t) { prev.textContent = "Preview appears here…"; addBtn.disabled = true; return; }
    const r = await pywebview.api.preview_dispute_email(t);
    if (!r?.ok) { prev.textContent = r?.error || "Couldn't parse."; addBtn.disabled = true; return; }
    const p = r.parsed;
    if (p.claim && !clmEl.value) clmEl.value = p.claim;
    prev.textContent = `${p.lines.length} line adjustment(s) · disputed $${p.amount}\n\n${p.summary}`;
    addBtn.disabled = false;
  };
  txt.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(doPreview, 300); });
  addBtn.addEventListener("click", async () => {
    addBtn.disabled = true; addBtn.textContent = "Adding…";
    const r = await pywebview.api.add_dispute_from_email(txt.value, insEl.value, clmEl.value);
    if (r?.need_insured) {
      setStatus("Add an insured name or claim # first", "warn");
      insEl.focus(); addBtn.disabled = false; addBtn.textContent = "➕ Add to tracker"; return;
    }
    if (!r?.ok) {
      setStatus(`Add failed: ${r?.error || "?"}`, "error");
      addBtn.disabled = false; addBtn.textContent = "➕ Add to tracker"; return;
    }
    setStatus(`✓ Dispute added${r.was_new ? "" : " (updated)"} · $${r.parsed?.amount || ""}`, "ok");
    close();
    await load();
  });
  setTimeout(() => txt.focus(), 50);
}

async function openDisputeModal(existing) {
  const isEdit = !!existing;
  const statuses = await pywebview.api.status_choices() || [];
  const fields = [
    ["insured",   "Insured *"],
    ["claim",     "Claim #"],
    ["carrier",   "Carrier"],
    ["franchise", "Franchise"],
    ["amount",    "Amount"],
    ["summary",   "Summary"],
    ["estimator", "Estimator"],
  ];
  // Map existing row's _foo keys into the plain keys the dialog uses
  const vals = {};
  if (existing) {
    vals.insured   = existing._insured;
    vals.claim     = existing._claim;
    vals.carrier   = ""; // workbook column not surfaced in read_rows
    vals.franchise = existing._franchise;
    vals.amount    = existing._amount;
    vals.summary   = existing.Summary || existing.summary || "";
    vals.estimator = existing.Estimator || existing.estimator || "";
    vals.status    = existing._status;
  }
  const wrap = document.createElement("div");
  wrap.id = "disp-modal";
  wrap.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">${isEdit ? "✏ Edit dispute" : "➕ New dispute"}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
          ${isEdit ? esc(vals.insured || "(no insured)") : "Fill in at least Insured or Claim#"}
        </div>
      </header>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;">
        ${fields.map(([k, label]) => `
          <label style="display:flex;flex-direction:column;gap:4px;">
            <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">${esc(label)}</span>
            <input class="search" type="text" data-key="${esc(k)}"
                   value="${esc(vals[k] || "")}"
                   ${k === "summary" ? "" : ""} />
          </label>`).join("")}
        <label style="display:flex;flex-direction:column;gap:4px;">
          <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">Status</span>
          <select class="search" data-key="status" style="width:100%;">
            ${statuses.map((s) =>
              `<option value="${esc(s)}" ${s === vals.status ? "selected" : ""}>${esc(s)}</option>`).join("")}
          </select>
        </label>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="disp-cancel">Cancel</button>
        <button class="btn btn-primary" id="disp-save">💾 ${isEdit ? "Save" : "Add"}</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  $("#disp-cancel").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  $("#disp-save").addEventListener("click", async () => {
    const payload = {};
    wrap.querySelectorAll("[data-key]").forEach((el) => {
      payload[el.dataset.key] = el.value.trim();
    });
    if (!payload.insured && !payload.claim) {
      alert("Insured or Claim # required."); return;
    }
    const btn = $("#disp-save");
    btn.disabled = true; btn.textContent = "Saving…";
    let res;
    if (isEdit) {
      res = await pywebview.api.update_dispute(
        existing._claim || "", existing._insured || "", payload);
    } else {
      res = await pywebview.api.add_dispute(payload);
    }
    if (!res?.ok) {
      alert("Save failed: " + (res?.error || "?"));
      btn.disabled = false; btn.textContent = "💾 " + (isEdit ? "Save" : "Add");
      return;
    }
    close();
    await load();
  });
  wrap.querySelector("[data-key='insured']")?.focus();
}

// ── 📁 Workbook location (move / repoint) ──────────────────────────
// Lets the user relocate the shared Dispute Tracker.xlsx without a code
// edit. Two paths: MOVE the file into a folder you pick, or POINT at a
// workbook that already lives elsewhere (e.g. mirrored to X:\IE_Public).
async function openLocationModal() {
  const cur = state.workbook || "(not set)";
  const wrap = document.createElement("div");
  wrap.id = "loc-modal";
  wrap.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  wrap.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(620px,94vw);overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📁 Dispute Tracker location</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Where the shared <b>Dispute Tracker.xlsx</b> lives</div>
      </header>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">
        <div>
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:4px;">Current file</div>
          <div style="font-size:12px;word-break:break-all;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 10px;">${esc(cur)}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;">
          <button class="btn btn-primary" id="loc-move">📦 Move to another folder…</button>
          <div style="font-size:11px;color:var(--text-muted);">Moves the existing workbook into a folder you pick, then points the tool there. If that folder already has a Dispute Tracker, it just switches to it (nothing overwritten).</div>
          <button class="btn" id="loc-point" style="margin-top:8px;">🔗 Point to an existing file…</button>
          <div style="font-size:11px;color:var(--text-muted);">Use a workbook that already lives elsewhere. Nothing is moved.</div>
        </div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:flex-end;">
        <button class="btn" id="loc-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  $("#loc-close").addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  $("#loc-move").addEventListener("click", async () => {
    setStatus("Opening folder picker…");
    const r = await pywebview.api.relocate_workbook();
    if (r?.canceled) { setStatus(""); return; }
    if (!r?.ok) { setStatus(`Move failed: ${r?.error || "?"}`, "error"); return; }
    close();
    setStatus(r.moved ? `📦 Moved · now at ${r.path}`
                      : `✓ Location set · ${r.path}`, "ok");
    await load();
  });
  $("#loc-point").addEventListener("click", async () => {
    setStatus("Opening file picker…");
    const r = await pywebview.api.point_to_workbook();
    if (r?.canceled) { setStatus(""); return; }
    if (!r?.ok) { setStatus(`Repoint failed: ${r?.error || "?"}`, "error"); return; }
    close();
    setStatus(`🔗 Now using ${r.path}`, "ok");
    await load();
  });
}

// Minimal status helper (the disputes panel didn't have one — sync
// flow surfaces progress + completion via the status bar at the
// bottom of the page).
let _st = null;
function setStatus(msg, kind = "") {
  const el = document.getElementById("status-msg");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
  if (_st) clearTimeout(_st);
  if (kind === "ok") _st = setTimeout(() => {
    el.textContent = ""; el.className = "status-msg";
  }, 4000);
}
