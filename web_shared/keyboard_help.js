/* EMS Tools — shared "?" keyboard shortcut overlay.
 *
 * Each panel registers its own shortcut list with
 * `registerKeyboardHelp([{ keys: "?", desc: "Show this help" }, ...])`.
 * Pressing `?` (or Shift-/) anywhere outside a text input shows the
 * combined overlay. Esc closes it.
 *
 * Auto-includes the built-in shortcuts (?/Esc) so callers don't have
 * to add them every time.
 */
(function () {
  "use strict";
  const _shortcuts = [];

  function registerKeyboardHelp(list) {
    if (Array.isArray(list)) {
      for (const s of list) {
        if (s && s.keys && s.desc) _shortcuts.push(s);
      }
    }
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function open() {
    const existing = document.getElementById("ems-kb-help");
    if (existing) return;
    const builtIns = [
      { keys: "?", desc: "Show this help" },
      { keys: "Esc", desc: "Close any modal or this help" },
    ];
    const all = [...builtIns, ..._shortcuts];
    const o = document.createElement("div");
    o.id = "ems-kb-help";
    o.style.cssText = `
      position:fixed;inset:0;background:rgba(0,0,0,.66);z-index:500;
      display:flex;align-items:center;justify-content:center;`;
    o.innerHTML = `
      <div style="background:#1A1A1A;color:#FFF;border:1px solid #2A2A2A;
                  border-radius:10px;padding:20px 24px;
                  width:min(540px,92vw);max-height:80vh;overflow:auto;
                  box-shadow:0 10px 30px rgba(0,0,0,.55);font-size:13px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
          <span style="font-size:18px;">⌨</span>
          <strong style="font-size:15px;">Keyboard shortcuts</strong>
          <span style="flex:1;"></span>
          <button id="ems-kb-close" style="
            background:transparent;border:1px solid #444;color:#FFF;
            border-radius:5px;padding:3px 9px;cursor:pointer;font:inherit;
            font-size:12px;">Esc</button>
        </div>
        <div style="display:grid;grid-template-columns:auto 1fr;gap:8px 16px;">
          ${all.map((s) => `
            <kbd style="background:#2A2A2A;border:1px solid #444;
                        border-radius:4px;padding:2px 8px;font-family:monospace;
                        font-size:12px;justify-self:start;">${esc(s.keys)}</kbd>
            <span style="color:#CCC;">${esc(s.desc)}</span>`).join("")}
        </div>
      </div>`;
    document.body.appendChild(o);
    const close = () => o.remove();
    o.addEventListener("click", (e) => { if (e.target === o) close(); });
    o.querySelector("#ems-kb-close").addEventListener("click", close);
  }

  if (!window._emsKbHelpBound) {
    window._emsKbHelpBound = true;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        document.getElementById("ems-kb-help")?.remove();
        return;
      }
      // Ignore inside text inputs / textareas / contentEditable.
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                || t.isContentEditable)) return;
      if (e.key === "?" || (e.shiftKey && e.key === "/")) {
        e.preventDefault();
        const existing = document.getElementById("ems-kb-help");
        if (existing) existing.remove(); else open();
      }
    });
  }

  window.registerKeyboardHelp = registerKeyboardHelp;
  window.openKeyboardHelp = open;
})();
