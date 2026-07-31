/* Linguar Hub — shared multi-unit (Phase 2: multi-claim) umbrella helpers.
 *
 * Reusable pieces for the "parent property → child unit" experience,
 * shared by Audit, IUQ and Snapshot so the three surfaces stay in
 * lockstep (audit parity rule):
 *   - openCreateChildModal(): the ➕ create-missing-child confirm dialog
 *     (editable name + file-move preview) → api.create_and_route_unit
 *   - createBtnHTML / openParentBtnHTML / looseChipHTML / breadcrumbHTML:
 *     row/header decoration
 *   - groupUnitRows(): cluster run-doc rows that carry a `unit` under
 *     their shared property so a panel can render a collapsible umbrella
 *   - wire(): one delegated click handler for the ➕ / 📁 buttons
 *
 * Depends on window.openModal / window.closeModal (web_shared/modal.js)
 * and a pywebview `api` object passed in by the caller. Publishes
 * window.UmbrellaGroup. Pure view/util — no panel-specific state.
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  // ── Row/header decoration ──────────────────────────────────────────
  // ➕ button for a referenced-but-missing child. `parentPath` is the
  // property root the child gets created under; `suggested` is the
  // inferred (editable) unit name.
  function createBtnHTML(parentPath, suggested, parentName) {
    if (!parentPath) return "";
    return `<button class="umb-create" title="Create the missing unit folder"
              data-parent-path="${esc(parentPath)}"
              data-suggested="${esc(suggested || "")}"
              data-parent-name="${esc(parentName || "")}">➕ Create</button>`;
  }

  function openParentBtnHTML(parentPath) {
    if (!parentPath) return "";
    return `<button class="umb-openparent" title="Open the parent property folder"
              data-parent-path="${esc(parentPath)}">📁</button>`;
  }

  function looseChipHTML(count) {
    if (!count) return "";
    return `<span class="umb-loose" title="${count} photo(s) sit loose in the parent root — they may belong in a unit. Move them in Explorer.">⚠ ${count} loose</span>`;
  }

  function breadcrumbHTML(parentName) {
    if (!parentName) return "";
    return `<span class="umb-crumb" title="Belongs to ${esc(parentName)}">${esc(parentName)} ›</span>`;
  }

  // ── Clustering ─────────────────────────────────────────────────────
  // Group rows that carry a `unit` by their property (`client`). Returns
  // { order: [clientName…], groups: Map(clientName -> [rows]) } preserving
  // first-seen order. Campus sub-jobs (subjob+claim_origin) are left for
  // the caller's existing grouping and skipped here.
  function groupUnitRows(rows) {
    const groups = new Map();
    const order = [];
    for (const r of rows || []) {
      if (r.subjob || r.is_parent) continue;       // campus path owns these
      if (!r.unit && !r.unit_folder) continue;      // not a unit row
      const key = r.client || "";
      if (!groups.has(key)) { groups.set(key, []); order.push(key); }
      groups.get(key).push(r);
    }
    return { order, groups };
  }

  // ── ➕ create-missing-child confirm modal ──────────────────────────
  // opts: {api, parentPath, parentName, suggestedName, files:[abs paths],
  //        onDone(result)}. Reuses window.openModal.
  function openCreateChildModal(opts) {
    const { api, parentPath, parentName, suggestedName,
            files = [], onDone } = opts || {};
    if (!api || !parentPath) return;
    const fileRows = files.length
      ? `<div class="umb-files">Will move ${files.length} file${files.length === 1 ? "" : "s"} into EMS/PICS:
           <ul>${files.slice(0, 30).map((f) =>
             `<li>${esc(f.split(/[\\/]/).pop())}</li>`).join("")}
           ${files.length > 30 ? `<li>… +${files.length - 30} more</li>` : ""}</ul>
         </div>`
      : `<div class="umb-files umb-files-empty">No files staged — this just creates &amp; scaffolds the folder.</div>`;
    openModal({
      title: "➕ Create missing unit",
      sub: parentName ? `Under ${parentName}` : "",
      width: 520,
      id: "umb-create-modal",
      body: `
        <label class="umb-lbl">Unit folder name</label>
        <input id="umb-name" class="umb-name-input" type="text"
               value="${esc(suggestedName || "")}" spellcheck="false" />
        ${fileRows}
        <div class="umb-actions">
          <button class="btn modal-close">Cancel</button>
          <button id="umb-go" class="btn btn-primary">Create${files.length ? " + Move" : ""}</button>
        </div>`,
    });
    const nameInput = document.getElementById("umb-name");
    const go = document.getElementById("umb-go");
    if (nameInput) { nameInput.focus(); nameInput.select(); }
    if (!go) return;
    go.addEventListener("click", async () => {
      const name = (nameInput && nameInput.value || "").trim();
      if (!name) { nameInput && nameInput.focus(); return; }
      go.disabled = true; go.textContent = "Working…";
      let res;
      try {
        res = await api.create_and_route_unit(parentPath, name, files);
      } catch (ex) {
        res = { ok: false, error: String(ex) };
      }
      window.closeModal && window.closeModal("umb-create-modal");
      if (onDone) onDone(res);
    });
  }

  // ── Delegated wiring ───────────────────────────────────────────────
  // Attach ONE listener to `container` handling ➕ (.umb-create) and 📁
  // (.umb-openparent). ctx: {api, setStatus(msg,kind), onCreated(res),
  //   filesFor(parentPath)->[paths] (optional, for import-in-progress)}.
  function wire(container, ctx) {
    if (!container || container._umbWired) return;
    container._umbWired = true;
    const api = ctx && ctx.api;
    container.addEventListener("click", (ev) => {
      const create = ev.target.closest && ev.target.closest(".umb-create");
      if (create && container.contains(create)) {
        ev.preventDefault(); ev.stopPropagation();
        const parentPath = create.dataset.parentPath;
        const files = (ctx.filesFor && ctx.filesFor(parentPath)) || [];
        openCreateChildModal({
          api,
          parentPath,
          parentName: create.dataset.parentName,
          suggestedName: create.dataset.suggested,
          files,
          onDone: (res) => {
            if (res && res.ok) {
              const moved = res.moved ? ` — moved ${res.moved} file(s)` : "";
              const failed = (res.failed && res.failed.length)
                ? ` (⚠ ${res.failed.length} failed)` : "";
              ctx.setStatus && ctx.setStatus(
                `✓ Created ${res.path.split(/[\\/]/).pop()}${moved}${failed}`,
                failed ? "warn" : "ok");
            } else {
              ctx.setStatus && ctx.setStatus(
                `Create failed: ${(res && res.error) || "?"}`, "error");
            }
            ctx.onCreated && ctx.onCreated(res);
          },
        });
        return;
      }
      const openp = ev.target.closest && ev.target.closest(".umb-openparent");
      if (openp && container.contains(openp)) {
        ev.preventDefault(); ev.stopPropagation();
        if (api && api.open_folder) api.open_folder(openp.dataset.parentPath);
      }
    });
  }

  window.UmbrellaGroup = {
    esc,
    createBtnHTML,
    openParentBtnHTML,
    looseChipHTML,
    breadcrumbHTML,
    groupUnitRows,
    openCreateChildModal,
    wire,
  };
})();
