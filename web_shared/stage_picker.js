/* Linguar Hub — shared PICS stage-folder picker.
 *
 * Before any PHOTO import (CompanyCam / WorkCenter photos / hand-picked
 * images) the panel calls:
 *
 *   const dest = await window.pickPicsStage({ client, count, allowAuto });
 *
 * and passes `dest` to do_import / pick_and_import_file. Return value:
 *   - a stage folder name ("Demo", "Mold Prep", "Monitor", …) → put the
 *     photos in PICS/<that>
 *   - "AUTO"  → let the backend auto-route (run-doc activity for WC,
 *               per-photo tag for CompanyCam) — only offered when allowAuto
 *   - null    → user cancelled; the caller should abort the import
 *
 * The stage names match exactly what audit_logic.check_photos looks for,
 * so a photo dropped in the right folder auto-resolves that audit row.
 */
(function () {
  "use strict";

  // Canonical PICS subfolders, in workflow order. Edit here once and the
  // picker on every panel follows.
  // Contents is on this list because audit_logic routes the run-doc's
  // Contents / Pack-out / Pack-in activities to PICS/Contents and always
  // has. The picker not offering it meant a hand-picked contents photo
  // could only be filed somewhere it didn't belong.
  const STAGES = [
    "Initial", "Reinspection", "Demo", "Mold Prep", "Post Mold Prep",
    "Mold", "Abatement", "Monitor", "Post", "Contents", "Equipment",
  ];
  window.PICS_STAGES = STAGES;

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  window.pickPicsStage = function ({ client, count, suggested,
                                     allowAuto = true, allowDocs = false } = {}) {
    return new Promise((resolve) => {
      const w = document.createElement("div");
      w.style.cssText = "position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;";
      const sub = count
        ? `${count} photo${count !== 1 ? "s" : ""}${client ? " · " + esc(client) : ""}`
        : (client ? esc(client) : "");
      const grid = STAGES.map((s) =>
        `<button class="sp-stage" data-stage="${esc(s)}"
                 style="text-align:left;background:${suggested === s ? "var(--chip-active,#3D6549)" : "var(--surface-2)"};
                        color:var(--text);border:1px solid ${suggested === s ? "var(--green)" : "var(--border)"};
                        border-radius:7px;padding:9px 12px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">
           📁 ${esc(s)}</button>`).join("");
      w.innerHTML = `
        <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
          <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
            <div style="font-size:15px;font-weight:600;">📁 Which folder should these photos go in?</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${sub}</div>
          </header>
          <div style="padding:14px 18px;overflow-y:auto;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">${grid}</div>
            ${allowDocs ? `<button class="sp-stage" data-stage="DOCS"
              style="width:100%;margin-top:8px;text-align:left;background:var(--surface-2);
                     color:var(--text);border:1px solid var(--border);border-radius:7px;
                     padding:9px 12px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">
              🧾 DOCS — documents folder (invoices / paperwork)</button>` : ""}
            <div style="display:flex;gap:8px;margin-top:12px;align-items:center;">
              <input id="sp-custom" type="text" placeholder="Custom folder name…" autocomplete="off"
                     style="flex:1;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;outline:none;" />
              <button id="sp-custom-use" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;cursor:pointer;font:inherit;font-size:13px;">Use</button>
            </div>
          </div>
          <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;">
            ${allowAuto ? `<button id="sp-auto" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;" title="Let the app decide (WorkCenter: run-doc activity · CompanyCam: each photo's tag)">🤖 Auto-detect</button>` : ""}
            <button id="sp-cancel" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;">Cancel</button>
          </footer>
        </div>`;
      document.body.appendChild(w);
      const fin = (v) => { w.remove(); resolve(v); };
      w.querySelectorAll(".sp-stage").forEach((b) =>
        b.addEventListener("click", () => fin(b.dataset.stage)));
      const useCustom = () => {
        const v = w.querySelector("#sp-custom").value.trim();
        if (v) fin(v);
      };
      w.querySelector("#sp-custom-use").addEventListener("click", useCustom);
      w.querySelector("#sp-custom").addEventListener("keydown", (e) => {
        if (e.key === "Enter") useCustom();
      });
      w.querySelector("#sp-auto")?.addEventListener("click", () => fin("AUTO"));
      w.querySelector("#sp-cancel").addEventListener("click", () => fin(null));
      w.addEventListener("click", (e) => { if (e.target === w) fin(null); });
      setTimeout(() => w.querySelector("#sp-custom")?.focus(), 30);
    });
  };

  /* Shared import tech-picker.
   *
   * Every PHOTO import must be attributed to a tech (CompanyCam exports
   * carry no photographer; WorkCenter attachments are field photos). After
   * pickPicsStage resolves to a PICS stage, the panel calls:
   *
   *   const tech = await window.pickImportTech({ client, techs });
   *
   * and passes `tech` to do_import / pick_and_import_file. Return value:
   *   - a tech name → attribute the import to that tech
   *   - null        → user cancelled; the caller should abort the import
   *
   * `techs` (optional) are the row's own techs, floated to the top of the
   * list and pre-selected. The full roster comes from list_techs. The
   * backend rejects a photo import with need_tech when this is empty, so
   * this picker is the guarantee — mirrors the same guard on every surface.
   */
  window.pickImportTech = async function ({ client, techs } = {}) {
    const rowTechs = Array.isArray(techs) ? techs.filter(Boolean) : [];
    let roster = [];
    try {
      const res = await window.pywebview.api.list_techs();
      roster = (res && res.techs) || [];
    } catch (_) { roster = []; }
    const seen = new Set();
    const ordered = [];
    for (const t of [...rowTechs, ...roster]) {
      const k = (t || "").toLowerCase();
      if (t && !seen.has(k)) { seen.add(k); ordered.push(t); }
    }
    const def = rowTechs[0] || "";
    return new Promise((resolve) => {
      const w = document.createElement("div");
      w.style.cssText = "position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;";
      w.innerHTML = `
        <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(460px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
          <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
            <div style="font-size:15px;font-weight:600;">📷 Who took these photos?</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Every photo import is filed under a tech — pick the one who shot these${client ? " · " + esc(client) : ""}.</div>
          </header>
          <div style="padding:16px 18px;overflow-y:auto;">
            <label style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin-bottom:6px;">Tech <span style="color:var(--red,#E5534B);">*</span></label>
            <select id="pt-tech" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px 10px;font:inherit;font-size:13px;outline:none;">
              ${ordered.map((t) => `<option value="${esc(t)}" ${t === def ? "selected" : ""}>${esc(t)}</option>`).join("")}
              <option value="__other__">＋ Other (type a name)…</option>
            </select>
            <input id="pt-other" type="text" placeholder="Tech name"
                   style="width:100%;margin-top:8px;display:none;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px 10px;font:inherit;font-size:13px;outline:none;" />
          </div>
          <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;">
            <button id="pt-cancel" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;">Cancel</button>
            <button id="pt-go" style="background:var(--green,#3D6549);color:#fff;border:1px solid var(--green,#3D6549);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">📥 Use this tech</button>
          </footer>
        </div>`;
      document.body.appendChild(w);
      const fin = (v) => { w.remove(); resolve(v); };
      const sel = w.querySelector("#pt-tech");
      const other = w.querySelector("#pt-other");
      sel.addEventListener("change", () => {
        const isOther = sel.value === "__other__";
        other.style.display = isOther ? "block" : "none";
        if (isOther) other.focus();
      });
      w.querySelector("#pt-cancel").addEventListener("click", () => fin(null));
      w.addEventListener("click", (e) => { if (e.target === w) fin(null); });
      const go = () => {
        let v = sel.value;
        if (v === "__other__") v = (other.value || "").trim();
        if (!v) {                       // tech is required — don't finish empty
          other.style.display = "block";
          other.focus();
          return;
        }
        fin(v);
      };
      w.querySelector("#pt-go").addEventListener("click", go);
      other.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      // No roster + no row techs → the select is empty; jump straight to
      // the free-type field so the user isn't stuck on an empty dropdown.
      if (!ordered.length) {
        sel.value = "__other__";
        other.style.display = "block";
        setTimeout(() => other.focus(), 30);
      }
    });
  };

  /* Multi-stage / multi-day import review panel.
   *
   * When a download spans more than one stage or day (detect_import_groups
   * → multi=true), the caller shows this instead of pickPicsStage +
   * pickImportTech. Each detected (day, stage) group gets a folder dropdown
   * (auto-filled from the detected stage; blank + "— pick —" for photos with
   * no stage word) and a tech dropdown (one tech per day+stage). Resolves to
   * an assignments array [{date_key, stage, folder, tech}] or null (cancel).
   */
  window.pickImportGroups = async function ({ client, techs, detection } = {}) {
    const groups = (detection && detection.groups) || [];
    const rowTechs = Array.isArray(techs) ? techs.filter(Boolean) : [];
    let roster = [];
    try {
      const res = await window.pywebview.api.list_techs();
      roster = (res && res.techs) || [];
    } catch (_) { roster = []; }
    const seen = new Set();
    const ordered = [];
    for (const t of [...rowTechs, ...roster]) {
      const k = (t || "").toLowerCase();
      if (t && !seen.has(k)) { seen.add(k); ordered.push(t); }
    }
    const def = rowTechs[0] || "";
    const stageOpts = window.PICS_STAGES || [];
    return new Promise((resolve) => {
      const w = document.createElement("div");
      w.style.cssText = "position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;";
      const selCss = "background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:7px 9px;font:inherit;font-size:12px;outline:none;";
      const rowsHtml = groups.map((g, i) => {
        const title = `${g.date_label || "(no date)"} · ${g.stage || "❓ no stage — pick a folder"}`;
        const folderSel = `<select class="ig-folder" data-i="${i}" style="width:100%;${selCss}">
            ${g.stage ? "" : `<option value="">— pick —</option>`}
            ${stageOpts.map((s) => `<option value="${esc(s)}" ${s === g.folder ? "selected" : ""}>${esc(s)}</option>`).join("")}
          </select>`;
        const techSel = `<select class="ig-tech" data-i="${i}" style="width:100%;${selCss}">
            ${ordered.map((t) => `<option value="${esc(t)}" ${t === def ? "selected" : ""}>${esc(t)}</option>`).join("")}
            <option value="__other__">＋ Other…</option>
          </select>
          <input class="ig-other" data-i="${i}" type="text" placeholder="Tech name" style="display:none;width:100%;margin-top:5px;${selCss}" />`;
        return `<div style="display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="flex:1;min-width:0;">
              <div style="font-weight:600;font-size:13px;">${esc(title)}</div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${g.count} photo${g.count !== 1 ? "s" : ""}</div>
            </div>
            <div style="width:150px;"><div style="font-size:10px;color:var(--text-muted);margin-bottom:3px;">Folder</div>${folderSel}</div>
            <div style="width:150px;"><div style="font-size:10px;color:var(--text-muted);margin-bottom:3px;">Tech</div>${techSel}</div>
          </div>`;
      }).join("");
      w.innerHTML = `
        <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(680px,95vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
          <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
            <div style="font-size:15px;font-weight:600;">📦 Multiple stages/days detected — assign each</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Each group routes to its own PICS folder; pick the tech per day+stage${client ? " · " + esc(client) : ""}.</div>
          </header>
          <div style="padding:8px 18px;overflow-y:auto;">${rowsHtml}</div>
          <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;">
            <button id="ig-cancel" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;">Cancel</button>
            <button id="ig-go" style="background:var(--green,#3D6549);color:#fff;border:1px solid var(--green,#3D6549);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">📥 Import all groups</button>
          </footer>
        </div>`;
      document.body.appendChild(w);
      const fin = (v) => { w.remove(); resolve(v); };
      w.querySelectorAll(".ig-tech").forEach((sel) => {
        sel.addEventListener("change", () => {
          const o = w.querySelector(`.ig-other[data-i="${sel.dataset.i}"]`);
          const isOther = sel.value === "__other__";
          o.style.display = isOther ? "block" : "none";
          if (isOther) o.focus();
        });
      });
      w.querySelector("#ig-cancel").addEventListener("click", () => fin(null));
      w.addEventListener("click", (e) => { if (e.target === w) fin(null); });
      w.querySelector("#ig-go").addEventListener("click", () => {
        const out = [];
        for (let i = 0; i < groups.length; i++) {
          const folder = (w.querySelector(`.ig-folder[data-i="${i}"]`).value || "").trim();
          const tsel = w.querySelector(`.ig-tech[data-i="${i}"]`);
          let tech = tsel.value;
          if (tech === "__other__") tech = (w.querySelector(`.ig-other[data-i="${i}"]`).value || "").trim();
          if (!folder) { alert("Pick a folder for every group before importing."); return; }
          if (!tech) { alert("Pick a tech for every group before importing."); return; }
          out.push({ date_key: groups[i].date_key, stage: groups[i].stage, folder, tech });
        }
        fin(out);
      });
    });
  };
})();
