/* Linguar Hub — Xactimate "new estimate from scratch" prep dialog.
 *
 * Can't build the .esx (Verisk proprietary) — this kills the manual work
 * around it: shows the price list you use for this carrier (remembered per
 * carrier) and gives you copy-to-clipboard fields to paste into Xactimate's
 * New Estimate dialog.
 *
 *   XactimatePrep.open({ api, client });
 * Backend: api.xa_prep_resolve(client) -> {ok, fields}
 *          api.xa_set_pricelist(carrier, pricelist) -> {ok}
 */
(function () {
  "use strict";

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

  // Fields in the copy-block order (matches xactimate_prep._BLOCK_ORDER).
  const FIELDS = [
    ["insured", "Insured"], ["address", "Property address"],
    ["carrier", "Carrier"], ["claim", "Claim #"],
    ["date_of_loss", "Date of loss"], ["loss_type", "Type of loss"],
  ];

  function fieldRow(key, label, val) {
    return `
      <div class="xp-row">
        <label class="xp-label">${esc(label)}</label>
        <input class="xp-in" data-key="${key}" type="text" value="${esc(val || "")}" autocomplete="off" />
        <button class="xp-copy" data-key="${key}" title="Copy ${esc(label)}">📋</button>
      </div>`;
  }

  async function open(opts) {
    const { api, client } = opts || {};
    if (!api) return;
    let f = { insured: client || "", claim: "", carrier: "", pricelist: "",
              loss_type: "", date_of_loss: "", address: "" };
    try {
      const r = await api.xa_prep_resolve(client || "");
      if (r && r.ok && r.fields) f = Object.assign(f, r.fields);
    } catch (_) {}

    const w = document.createElement("div");
    w.style.cssText = "position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;";
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(540px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">🧮 Xactimate prep — ${esc(f.insured || "new estimate")}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Pick the price list, then 📋 each field into Xactimate's New Estimate.</div>
        </header>
        <div style="padding:14px 18px;overflow-y:auto;">
          <div class="xp-pl">
            <label class="xp-label" style="font-weight:700;">Price list for this carrier</label>
            <div style="display:flex;gap:8px;align-items:center;">
              <input id="xp-pricelist" class="xp-in" type="text" value="${esc(f.pricelist || "")}"
                     placeholder="e.g. your Xactimate price list code" autocomplete="off" style="flex:1;" />
              <button id="xp-save-pl" class="xp-copy" title="Remember this price list for ${esc(f.carrier || "this carrier")}">💾</button>
            </div>
            <div id="xp-pl-note" style="font-size:11px;color:var(--text-muted);margin-top:4px;">
              ${f.carrier ? (f.pricelist ? `Saved for ${esc(f.carrier)}.` : `No price list saved for ${esc(f.carrier)} yet — set it once and it sticks.`) : "Enter a carrier below, then save its price list."}
            </div>
          </div>
          <hr style="border:none;border-top:1px solid var(--border);margin:12px 0;" />
          ${FIELDS.map(([k, l]) => fieldRow(k, l, f[k])).join("")}
        </div>
        <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;">
          <button id="xp-copyall" style="background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;">📋 Copy all fields</button>
          <button id="xp-close" style="background:var(--green,#3D6549);color:#fff;border:1px solid var(--green,#3D6549);border-radius:6px;padding:8px 14px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;">Done</button>
        </footer>
      </div>`;
    document.body.appendChild(w);
    const fin = () => w.remove();
    const val = (k) => (w.querySelector(`.xp-in[data-key="${k}"]`) || {}).value || "";
    const flash = (btn, ok) => {
      const t = btn.textContent; btn.textContent = ok ? "✓" : "✕";
      setTimeout(() => { btn.textContent = t; }, 900);
    };

    w.querySelectorAll(".xp-copy[data-key]").forEach((b) => {
      b.addEventListener("click", async () => flash(b, await copyText(val(b.dataset.key))));
    });
    w.querySelector("#xp-copyall").addEventListener("click", async () => {
      const block = FIELDS.map(([k, l]) => {
        const v = (val(k) || "").trim();
        return v ? `${l}: ${v}` : "";
      }).filter(Boolean).join("\n");
      const ok = await copyText(block);
      const btn = w.querySelector("#xp-copyall");
      btn.textContent = ok ? "✓ Copied" : "✕ Failed";
      setTimeout(() => { btn.textContent = "📋 Copy all fields"; }, 1200);
    });
    w.querySelector("#xp-save-pl").addEventListener("click", async () => {
      const carrier = val("carrier").trim();
      const pl = (w.querySelector("#xp-pricelist").value || "").trim();
      if (!carrier) {
        w.querySelector("#xp-pl-note").textContent = "Enter the carrier first, then save.";
        return;
      }
      const btn = w.querySelector("#xp-save-pl");
      try { await api.xa_set_pricelist(carrier, pl); flash(btn, true);
        w.querySelector("#xp-pl-note").textContent = pl
          ? `Saved “${pl}” for ${carrier}.` : `Cleared price list for ${carrier}.`;
      } catch (_) { flash(btn, false); }
    });
    w.querySelector("#xp-close").addEventListener("click", fin);
    w.addEventListener("click", (e) => { if (e.target === w) fin(); });
  }

  window.XactimatePrep = { open };
})();
