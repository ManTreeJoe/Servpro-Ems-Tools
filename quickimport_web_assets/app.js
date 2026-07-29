// Quick Import — search-first mini tool for general office users.
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  let selected = null;
  let searchTimer = null;

  // Surface any runtime error to the status bar (no dev console for users).
  function _showErr(msg) {
    const el = document.getElementById("status");
    if (el) { el.textContent = String(msg || "Unknown error"); el.className = "err"; }
  }
  window.addEventListener("error", (e) => _showErr("JS error: " + (e.message || (e.error && e.error.message) || "")));
  window.addEventListener("unhandledrejection", (e) => _showErr("Error: " + ((e.reason && e.reason.message) || e.reason || "")));

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Global setStatus — the shared audit_detail / attachments modals call it.
  function setStatus(msg, kind) {
    const el = $("#status");
    if (!el) return;
    el.textContent = msg || "";
    el.className = kind || "";
  }
  window.setStatus = setStatus;

  function firstLast(name) {
    const s = String(name || "").trim();
    const m = s.match(/^([^,]+),\s*([^-(]+?)\s*(?:[-(].*)?$/);
    if (m) return `${m[2].trim()} ${m[1].trim()}`;
    return s;
  }

  async function copy(text, label) {
    let ok = false;
    try {
      if (window.pywebview && pywebview.api.set_clipboard)
        ok = await pywebview.api.set_clipboard(String(text || ""));
    } catch (e) {}
    if (!ok) { try { await navigator.clipboard.writeText(String(text || "")); ok = true; } catch (e) {} }
    setStatus(ok ? `📋 Copied ${label}: ${text}` : "Couldn't copy", ok ? "ok" : "err");
  }

  // ── Recent jobs (persisted so you can jump back) ────────────────
  function getRecents() {
    try { return JSON.parse(localStorage.getItem("qi_recents") || "[]"); }
    catch (e) { return []; }
  }
  function pushRecent(job) {
    if (!job || !job.name) return;
    try {
      let r = getRecents().filter((x) => (x.name || "").toLowerCase() !== job.name.toLowerCase());
      r.unshift({ name: job.name, display: job.display || job.name, path: job.path || "" });
      localStorage.setItem("qi_recents", JSON.stringify(r.slice(0, 10)));
    } catch (e) {}
  }
  function removeRecent(name) {
    try {
      const r = getRecents().filter((x) => (x.name || "").toLowerCase() !== (name || "").toLowerCase());
      localStorage.setItem("qi_recents", JSON.stringify(r));
    } catch (e) {}
    renderRecents();
  }
  function renderRecents() {
    const box = $("#results");
    const r = getRecents();
    if (!r.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="grp" style="margin:14px 2px 6px;">Recent</div>` +
      r.map((j) => `
        <div class="job recent" data-name="${esc(j.name)}">
          <span>🕘</span><span class="nm">${esc(j.display || j.name)}</span>
          <button class="btn rec-x" title="Remove from recent" style="padding:2px 9px;">✕</button>
        </div>`).join("");
    box.querySelectorAll(".job.recent").forEach((el) => {
      el.addEventListener("click", (e) => { if (e.target.closest(".rec-x")) return; selectJob(el.dataset.name); });
      el.querySelector(".rec-x").addEventListener("click", (e) => { e.stopPropagation(); removeRecent(el.dataset.name); });
    });
  }

  // ── Search ──────────────────────────────────────────────────────
  function initSearch() {
    $("#search").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      if (q.length < 2) { renderRecents(); return; }
      searchTimer = setTimeout(() => doSearch(q), 220);
    });
  }

  async function doSearch(q) {
    let res;
    try { res = await pywebview.api.search_jobs(q); }
    catch (e) { setStatus("Search failed", "err"); return; }
    renderResults(res || {}, q);
  }

  function renderResults(res, q) {
    const box = $("#results");
    const items = res.results || [];
    if (res.mode === "folders" && items.length) {
      box.innerHTML = items.map((j) => `
        <div class="job" data-name="${esc(j.name)}">
          <span>📁</span><span class="nm">${esc(j.display)}</span>
          ${j.year_folder ? `<span class="tag">${esc(j.year_folder)}</span>` : ""}
        </div>`).join("");
      box.querySelectorAll(".job").forEach((el) =>
        el.addEventListener("click", () => selectJob(el.dataset.name)));
    } else {
      renderNoFolder(items, q);
    }
  }

  function renderNoFolder(cards, q) {
    const box = $("#results");
    let html = `<div class="nofound">No job <b>folder</b> found for "<b>${esc(q)}</b>".`;
    if (cards.length) {
      html += `<div style="margin:10px 0 6px;font-size:12px;">Trello cards with no folder yet — open one, or create the folder:</div>`;
      html += `<div style="display:flex;flex-direction:column;gap:6px;">` + cards.map((c) => `
        <div class="job nofolder" data-card="${esc(c.card_id)}">
          <span>🗂</span><span class="nm">${esc(c.display)}</span><span class="tag">no folder</span>
        </div>`).join("") + `</div>`;
    }
    html += `<div style="margin-top:14px;"><button class="bigbtn" id="create-folder">➕ Create job folder "${esc(q)}"</button></div></div>`;
    box.innerHTML = html;
    $("#create-folder").addEventListener("click", () => createFolder(q));
    box.querySelectorAll(".job.nofolder").forEach((el) =>
      el.addEventListener("click", () => {
        if (el.dataset.card) pywebview.api.open_trello_card(el.dataset.card);
      }));
  }

  async function createFolder(name) {
    setStatus("Creating folder…");
    let r;
    try { r = await pywebview.api.create_job_folder(name); }
    catch (e) { setStatus("Create failed", "err"); return; }
    if (!r.ok) {
      setStatus(r.error || "Couldn't create", r.exists ? "warn" : "err");
      if (r.exists) selectJob(name);
      return;
    }
    setStatus(`➕ Created folder for ${r.name}`, "ok");
    selectJob(r.name);
  }

  // ── Select a job → resolve full row → render panel ──────────────
  async function selectJob(name) {
    setStatus("Loading job…");
    let r;
    try { r = await pywebview.api.select_job(name); }
    catch (e) { setStatus("Couldn't load job", "err"); return; }
    if (!r.ok) {
      // No audit row (e.g. brand-new folder) — synthesize a minimal one.
      selected = { client: name, display_name: name, path: "", trello_card_id: "" };
    } else {
      selected = r.row || { client: name };
      if (!selected.client) selected.client = name;
    }
    pushRecent({
      name: selected.client,
      display: firstLast(selected.display_name || selected.client),
      path: selected.path || "",
    });
    renderPanel();
    setStatus("");
    resolveCard();  // auto-pin the Trello card (or prompt to pick)
  }

  // Auto-pin the job's Trello card; if several match, open a picker.
  async function resolveCard() {
    const r = selected;
    if (!r || r.trello_card_id) return;
    let res;
    try { res = await pywebview.api.resolve_card(r.client); }
    catch (e) { return; }
    if (!res || !res.ok || selected !== r) return;   // job changed meanwhile
    if (res.card_id) {
      selected.trello_card_id = res.card_id;
      if (res.source === "auto") setStatus("📌 Trello card auto-pinned", "ok");
    } else if (res.needs_choice) {
      openCardPicker(res.candidates || []);
    }
  }

  function openCardPicker(cands) {
    if (!cands.length) return;
    const overlay = window.openModal({
      title: "Pick the Trello card",
      body: `
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
          More than one card matched <b>${esc(firstLast(selected.display_name || selected.client))}</b> — pick the right one:
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;max-height:340px;overflow-y:auto;">
          ${cands.map((c) => `
            <div class="job cardpick" data-card="${esc(c.card_id)}" style="cursor:pointer;">
              <span>🗂</span><span class="nm">${esc(c.name)}</span>
              ${c.board || c.lane ? `<span class="tag">${esc(c.board || "")}${c.lane ? " · " + esc(c.lane) : ""}</span>` : ""}
            </div>`).join("")}
        </div>
        <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:12px;">
          <button class="btn modal-close" id="cp-skip">Skip</button>
        </div>`,
    });
    overlay.querySelectorAll(".cardpick").forEach((el) =>
      el.addEventListener("click", async () => {
        const cid = el.dataset.card;
        try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); }
        const res = await pywebview.api.pin_card(selected.client, cid);
        if (res && res.ok === false) { setStatus("Pin failed: " + (res.error || "?"), "warn"); return; }
        selected.trello_card_id = cid;
        setStatus("📌 Trello card pinned", "ok");
      }));
  }

  function renderPanel() {
    const r = selected;
    $("#searchview").hidden = true;
    const panel = $("#panel");
    panel.hidden = false;
    const hasPath = !!r.path;
    panel.innerHTML = `
      <div class="selhead">
        <button class="bigbtn" data-act="back" style="padding:8px 12px;font-size:13px;">← Back</button>
        <div style="flex:1;min-width:0;">
          <div class="big">${esc(firstLast(r.display_name || r.client))}</div>
          <div class="path">${esc(r.path || "(no folder — use Find folder)")}</div>
        </div>
      </div>
      <div class="grp">Photos</div>
      <div class="btns">
        <button class="bigbtn primary" data-act="import" ${hasPath ? "" : "disabled"}>📥 Import</button>
        <button class="bigbtn" data-act="stage" ${hasPath ? "" : "disabled"}>📂 Stage for XA</button>
      </div>
      <div class="grp">Open</div>
      <div class="btns">
        <button class="bigbtn" data-act="folder" ${hasPath ? "" : "disabled"}>📁 Open folder</button>
        <button class="bigbtn" data-act="trello">🗂 Trello</button>
        <button class="bigbtn" data-act="xa">📄 XA</button>
        <button class="bigbtn" data-act="cc">📷 CompanyCam</button>
        <button class="bigbtn" data-act="attach">📎 Attachments</button>
      </div>
      <div class="grp">Copy</div>
      <div class="btns copybtns">
        <button class="bigbtn" data-act="cname">📋 Name</button>
        <button class="bigbtn" data-act="cclaim">📋 Claim #</button>
        <button class="bigbtn" data-act="cemail">📧 Email</button>
        <button class="bigbtn" data-act="cpath" ${hasPath ? "" : "disabled"}>📋 Path</button>
      </div>
      <div class="grp">Folder</div>
      <div class="btns">
        <button class="bigbtn" data-act="find">🔎 ${hasPath ? "Change" : "Find"} folder</button>
        <button class="bigbtn" data-act="reaudit">↻ Re-check</button>
      </div>`;
    // One delegated handler — robust against any single missing element, and
    // surfaces any error to the status bar instead of failing silently.
    panel.onclick = (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn || btn.disabled) return;
      Promise.resolve(runAction(btn.dataset.act, r))
        .catch((err) => setStatus("Error: " + ((err && err.message) || err), "err"));
    };
  }

  async function runAction(act, r) {
    switch (act) {
      case "back": panelBack(); break;
      case "import": await doImport(r); break;
      case "stage":
        if (window.AuditDetail && window.AuditDetail.openCopyPicsToXaModal)
          window.AuditDetail.openCopyPicsToXaModal(r, {});
        else setStatus("Stage-for-XA unavailable", "warn");
        break;
      case "folder": await pywebview.api.open_od_for_client(r.client, r.path || ""); break;
      case "trello":
        if (r.trello_card_id) await pywebview.api.open_trello_card(r.trello_card_id);
        else setStatus("No Trello card pinned for this job", "warn");
        break;
      case "xa": {
        const ok = await pywebview.api.open_xa_link(r.client, r.trello_card_id || "");
        if (!ok) setStatus("No XactAnalysis link on this card yet", "warn");
        break;
      }
      case "cc": {
        const ok = await pywebview.api.open_companycam_link(r.client);
        if (!ok) setStatus("No CompanyCam link on this card yet", "warn");
        break;
      }
      case "attach":
        if (window.openTrelloAttachmentsModal)
          window.openTrelloAttachmentsModal({ cardId: r.trello_card_id || "", client: r.client });
        else setStatus("Attachments unavailable", "warn");
        break;
      case "cname": await copy(firstLast(r.display_name || r.client), "name"); break;
      case "cclaim": {
        const res = await pywebview.api.get_claim_number(r.client);
        if (res && res.ok && res.claim) await copy(res.claim, "claim #");
        else setStatus("No claim # on this card yet", "warn");
        break;
      }
      case "cemail": {
        const res = await pywebview.api.get_job_email(r.client);
        if (res && res.ok && res.email) await copy(res.email, "email");
        else setStatus("No email on this card yet", "warn");
        break;
      }
      case "cpath": await copy(r.path || "", "path"); break;
      case "find": await openFindFolder(r); break;
      case "reaudit": await selectJob(r.client); break;
    }
  }

  function panelBack() {
    $("#panel").hidden = true;
    $("#searchview").hidden = false;
    const s = $("#search");
    const q = s.value.trim();
    if (q.length >= 2) doSearch(q); else renderRecents();
    s.focus();
    setStatus("");
  }

  // ── Import — confirm destination, then native multi-file pick ───
  async function doImport(r) {
    if (!r.path) { setStatus("This job has no folder to import into — use Find folder first", "warn"); return; }
    // Choose the destination folder FIRST — a specific stage (Initial/Demo/
    // Monitor/…), a custom folder name, or Auto-detect. This confirms the
    // destination and lets you override when auto picks wrong.
    const dest = await window.pickPicsStage({
      client: firstLast(r.display_name || r.client),
      allowAuto: true,
    });
    if (dest === null) return;   // cancelled
    setStatus("Opening file picker…");
    let res;
    try { res = await pywebview.api.pick_and_import_file(r.client, dest === "AUTO" ? "" : dest); }
    catch (e) { setStatus("Import failed", "err"); return; }
    if (!res || !res.ok) { setStatus((res && res.error) || "Import cancelled", "warn"); return; }
    const p = res.pics_count || 0, d = res.docs_count || 0;
    if (!p && !d) { setStatus("No files imported", "warn"); return; }
    const where = (dest && dest !== "AUTO") ? ` → ${dest}` : "";
    setStatus(`✓ Imported ${p} photo${p === 1 ? "" : "s"}${d ? ` + ${d} document${d === 1 ? "" : "s"}` : ""} into ${firstLast(r.display_name || r.client)}${where}`, "ok");
  }

  function confirmModal(title, bodyHtml, okLabel) {
    return new Promise((resolve) => {
      const overlay = window.openModal({
        title,
        body: `<div style="font-size:14px;line-height:1.55;">${bodyHtml}</div>
          <div class="modal-footer" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px;">
            <button class="btn" id="cm-cancel">Cancel</button>
            <button class="btn btn-primary" id="cm-ok">${esc(okLabel || "OK")}</button>
          </div>`,
      });
      const close = () => { try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); } };
      overlay.querySelector("#cm-ok").addEventListener("click", () => { close(); resolve(true); });
      overlay.querySelector("#cm-cancel").addEventListener("click", () => { close(); resolve(false); });
    });
  }

  // ── Find / Change folder (drill into subfolders) ────────────────
  async function openFindFolder(row) {
    const overlay = window.openModal({
      title: (row.path ? "🔀 Change folder" : "🔎 Find folder") + " — " + firstLast(row.display_name || row.client),
      body: `
        <input id="ff-search" class="search" placeholder="Filter…" autocomplete="off"
               style="width:100%;padding:8px 10px;margin-bottom:8px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;" />
        <div id="ff-crumb" style="display:none;align-items:center;gap:8px;margin-bottom:8px;font-size:12px;"></div>
        <div id="ff-status" style="font-size:11px;color:var(--text-muted);margin-bottom:6px;"></div>
        <div id="ff-hits" style="max-height:320px;overflow-y:auto;">Loading…</div>
        <div class="modal-footer" style="display:flex;justify-content:flex-end;margin-top:10px;">
          <button class="btn" id="ff-close">Close</button>
        </div>`,
    });
    const closeIt = () => { try { window.closeModal("modal-overlay"); } catch (e) { overlay.remove(); } };
    overlay.querySelector("#ff-close").addEventListener("click", closeIt);

    let all = [], stack = [], subs = [], term = "";
    const clear = () => { term = ""; const el = overlay.querySelector("#ff-search"); if (el) el.value = ""; };

    const pin = async (path, label) => {
      const res = await pywebview.api.pin_folder(row.client, path);
      if (res && res.ok === false) { setStatus(`Pin failed: ${res.error || "?"}`, "err"); return; }
      closeIt();
      setStatus(`📁 Set folder → ${label || path}`, "ok");
      selectJob(row.client);
    };
    const drill = async (f) => {
      const res = await pywebview.api.list_subfolders(f.path);
      if (!res || !res.ok) { setStatus("Couldn't open folder", "err"); return; }
      stack.push({ name: f.name, path: f.path }); subs = res.subfolders || []; clear(); render();
    };
    const goTo = async (depth) => {
      clear();
      if (depth <= 0) { stack = []; subs = []; render(); return; }
      stack = stack.slice(0, depth);
      const cur = stack[stack.length - 1];
      const res = await pywebview.api.list_subfolders(cur.path);
      subs = res && res.ok ? (res.subfolders || []) : []; render();
    };
    const render = () => {
      const crumb = overlay.querySelector("#ff-crumb");
      if (!stack.length) crumb.style.display = "none";
      else {
        crumb.style.display = "flex";
        const cur = stack[stack.length - 1];
        let segs = `<a href="#" data-d="0" style="color:var(--link,#4A9EFF);">Candidates</a>`;
        stack.forEach((s, i) => { segs += ` › <a href="#" data-d="${i + 1}" style="color:${i === stack.length - 1 ? "var(--text)" : "var(--link,#4A9EFF)"};font-weight:${i === stack.length - 1 ? 700 : 400};">${esc(s.name)}</a>`; });
        crumb.innerHTML = `<div style="flex:1;">${segs}</div><button class="btn btn-primary" id="ff-use">✓ Use "${esc(cur.name)}"</button>`;
        crumb.querySelectorAll("a[data-d]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); goTo(parseInt(a.dataset.d, 10)); }));
        crumb.querySelector("#ff-use").addEventListener("click", () => pin(cur.path, cur.name));
      }
      const browsing = stack.length > 0;
      const q = term.toLowerCase();
      const src = browsing ? subs : all;
      const items = q ? src.filter((c) => (c.name || "").toLowerCase().includes(q)) : src;
      const st = overlay.querySelector("#ff-status");
      st.textContent = browsing
        ? (items.length ? `${items.length} subfolder(s) in ${stack[stack.length - 1].name}` : `No subfolders — use "✓ Use" to pin this folder.`)
        : `${items.length} folder(s)`;
      const hits = overlay.querySelector("#ff-hits");
      if (!items.length) { hits.innerHTML = `<div style="padding:14px;text-align:center;color:var(--text-muted);">${browsing ? "No subfolders." : "No matches."}</div>`; return; }
      hits.innerHTML = items.slice(0, 300).map((c) => `
        <div class="job ffrow" data-path="${esc(c.path)}" data-name="${esc(c.name)}" style="cursor:pointer;">
          <span>📁</span><span class="nm" style="font-size:14px;">${esc(c.name)}</span>
          <button class="btn ffopen" title="Open — pick a subfolder inside" style="padding:2px 9px;">›</button>
        </div>`).join("");
      hits.querySelectorAll(".ffrow").forEach((el) => {
        el.addEventListener("click", (e) => { if (e.target.closest(".ffopen")) return; pin(el.dataset.path, el.dataset.name); });
        el.querySelector(".ffopen").addEventListener("click", (e) => { e.stopPropagation(); drill({ name: el.dataset.name, path: el.dataset.path }); });
      });
    };
    overlay.querySelector("#ff-search").addEventListener("input", (e) => { term = e.target.value.trim(); render(); });
    const r = await pywebview.api.list_folder_candidates(row.client, "");
    all = (r && r.candidates) || [];
    render();
  }

  // ── Boot ────────────────────────────────────────────────────────
  function boot() {
    initSearch();
    renderRecents();
    pywebview.api.department().then((d) => {
      const el = $("#dept");
      if (el && d && d.dept) el.textContent = d.dept;
    }).catch(() => {});
    $("#search").focus();
  }

  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener("pywebviewready", boot);
})();
