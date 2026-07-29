/* EMS Tools — shared "Request items" dialog.
 *
 * Tick the forms / scope / docusketch you need from the lead → posts a
 * Trello comment @mentioning them + copies the Teams message for you to
 * paste + tracks the request (📨 Requested Nd ago). Used by the Hygiene
 * board and the audit detail, so both fire identical requests.
 *
 *   RequestItems.open({ api, cardId, canon, job, client, onDone });
 * Backend: api.request_item_options() -> {items:[[key,label]], handles:[]}
 *          api.request_items_send(cardId, canon, keys, other, handle, client)
 *              -> { ok, posted, teams, trello }
 */
(function () {
  "use strict";

  const FALLBACK_ITEMS = [
    ["atp", "ATP (Auth to Perform)"], ["cif", "CIF (Customer Info Form)"],
    ["cer", "CER (Customer Equip Resp)"], ["cos", "COS (Cert of Satisfaction)"],
    ["scope", "Scope"], ["docusketch", "Docusketch scan"],
    ["moisture", "Moisture map"],
  ];

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; }
    catch (_) {
      try {
        const ta = document.createElement("textarea");
        ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove(); return true;
      } catch (e) { return false; }
    }
  }

  async function open(opts) {
    const { api, cardId, canon, job, client, onDone } = opts || {};
    if (!api) return;
    const jobName = job || client || canon || "this job";
    let items = FALLBACK_ITEMS, handles = [];
    try {
      const o = await api.request_item_options();
      if (o && o.items && o.items.length) items = o.items;
      handles = (o && o.handles) || [];
    } catch (_) {}

    const w = document.createElement("div");
    w.style.cssText = "position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;";
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(520px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">📨 Request items — ${esc(jobName)}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Posts a Trello comment @the lead + copies the Teams message to paste.</div>
        </header>
        <div style="padding:14px 18px;overflow-y:auto;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;">
            ${items.map(([k, label]) => `
              <label style="display:flex;gap:8px;align-items:center;font-size:13px;cursor:pointer;">
                <input type="checkbox" class="ri-item" value="${esc(k)}" /> ${esc(label)}
              </label>`).join("")}
          </div>
          <label style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin:14px 0 4px;">Other</label>
          <input id="ri-other" type="text" placeholder="Anything else…" autocomplete="off"
                 style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;outline:none;" />
          <label style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);margin:12px 0 4px;">Lead's Trello @handle</label>
          <input id="ri-handle" type="text" placeholder="@fernandob" autocomplete="off" list="ri-handles"
                 style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;outline:none;" />
          <datalist id="ri-handles">${handles.map((h) => `<option value="${esc(h)}"></option>`).join("")}</datalist>
        </div>
        <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;">
          <button id="ri-cancel" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;">Cancel</button>
          <button id="ri-go" style="background:var(--green,#3D6549);color:#fff;border:1px solid var(--green,#3D6549);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">📨 Post &amp; copy</button>
        </footer>
      </div>`;
    document.body.appendChild(w);
    const fin = (v) => { w.remove(); if (onDone) onDone(v); };
    w.querySelector("#ri-cancel").addEventListener("click", () => fin(null));
    w.addEventListener("click", (e) => { if (e.target === w) fin(null); });
    if (handles.length) w.querySelector("#ri-handle").value = handles[0];
    setTimeout(() => w.querySelector(".ri-item")?.focus(), 30);

    w.querySelector("#ri-go").addEventListener("click", async () => {
      const keys = Array.from(w.querySelectorAll(".ri-item:checked")).map((c) => c.value);
      const other = (w.querySelector("#ri-other").value || "").trim();
      const handle = (w.querySelector("#ri-handle").value || "").trim();
      if (!keys.length && !other) { w.querySelector(".ri-item")?.focus(); return; }
      const go = w.querySelector("#ri-go");
      go.disabled = true; go.textContent = "Posting…";
      let res;
      try {
        res = await api.request_items_send(cardId || "", canon || "",
          keys, other, handle, client || job || "");
      } catch (ex) { res = { ok: false, error: String(ex) }; }
      if (res && res.ok) {
        const copied = await copyText(res.teams || "");
        res._copied = copied;
        res._teams = res.teams;
      }
      fin(res);
    });
  }

  window.RequestItems = { open, copyText };
})();
