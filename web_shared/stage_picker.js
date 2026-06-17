/* EMS Tools — shared PICS stage-folder picker.
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
  const STAGES = [
    "Initial", "Reinspection", "Demo", "Mold Prep", "Post Mold Prep",
    "Mold", "Post Mold", "Abatement", "Monitor", "Post",
    "Contents", "Equipment",
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
})();
