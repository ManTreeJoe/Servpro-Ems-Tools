/* Normal text editing menu for the web/desktop surfaces.
 * Object-specific menus may preventDefault first; this handler then leaves
 * them alone. Text fields and selected copyable text retain familiar desktop
 * Cut / Copy / Paste / Select all behavior inside pywebview.
 */
(function () {
  "use strict";
  if (window.__linguarTextContextMenuInstalled) return;
  window.__linguarTextContextMenuInstalled = true;

  const MENU_ID = "linguar-text-context-menu";
  const proseSelector = 'textarea, input[type="text"], input[type="search"], input:not([type]), [contenteditable="true"]';
  function enableSpelling(field) {
    if (!field || field.getAttribute('spellcheck') === 'false') return;
    field.spellcheck = true;
    // Native dictionaries need a language even inside dynamically loaded panels.
    if (!field.closest('[lang]')) field.lang = 'en-US';
    // Suggestions, not silent substitutions of names or claim information.
    if (!field.hasAttribute('autocorrect')) field.setAttribute('autocorrect', 'off');
  }
  document.querySelectorAll(proseSelector).forEach(enableSpelling);
  document.addEventListener('focusin', event => enableSpelling(event.target.closest?.(proseSelector)));
  const isField = (node) => Boolean(node?.closest?.("input, textarea, [contenteditable='true']"));
  const fieldFor = (node) => node?.closest?.("input, textarea, [contenteditable='true'], [contenteditable=''], [contenteditable='plaintext-only']") || null;
  const selectionText = (field) => {
    if (field && typeof field.selectionStart === "number") {
      return String(field.value || "").slice(field.selectionStart, field.selectionEnd);
    }
    return String(window.getSelection?.() || "");
  };
  const close = () => document.getElementById(MENU_ID)?.remove();
  const dispatchInput = (field) => field?.dispatchEvent(new InputEvent("input", {
    bubbles: true, inputType: "insertText",
  }));
  const insertText = (field, text) => {
    field?.focus?.();
    if (field && typeof field.setRangeText === "function") {
      field.setRangeText(text, field.selectionStart, field.selectionEnd, "end");
      dispatchInput(field);
      return;
    }
    document.execCommand("insertText", false, text);
  };
  const copyText = async (field) => {
    const value = selectionText(field);
    if (!value) return;
    try { await navigator.clipboard.writeText(value); }
    catch (_) { document.execCommand("copy"); }
  };
  const pasteText = async (field) => {
    field?.focus?.();
    try { insertText(field, await navigator.clipboard.readText()); }
    catch (_) { document.execCommand("paste"); }
  };
  const selectAll = (field) => {
    field?.focus?.();
    if (field?.select) field.select();
    else document.execCommand("selectAll");
  };

  function show(event, field, selected, actions = []) {
    close();
    window.closeContextMenu?.();
    const editable = Boolean(field && !field.readOnly && !field.disabled);
    const range = window.getSelection()?.rangeCount ? window.getSelection().getRangeAt(0).cloneRange() : null;
    const start = field?.selectionStart, end = field?.selectionEnd;
    function restore() {
      field?.focus();
      if (field && typeof start === 'number') field.setSelectionRange(start, end);
      else if (range) { const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); }
    }
    const items = [
      ["Cut", editable && selected, () => document.execCommand("cut")],
      ["Copy", Boolean(selected), () => copyText(field)],
      ["Paste", editable, () => pasteText(field)],
      ["Select all", Boolean(field) || Boolean(document.body.innerText), () => selectAll(field)],
    ];
    if(actions.length){items.splice(0,items.length,items[1],items[0],items[2],...actions);}
    const menu = document.createElement("div");
    menu.id = MENU_ID;
    menu.setAttribute("role", "menu");
    Object.assign(menu.style, {
      position: "fixed", zIndex: "10000", minWidth: "172px", padding: "5px",
      border: "1px solid var(--border, #3b433f)", borderRadius: "8px",
      background: "var(--surface, #1b211e)", boxShadow: "0 12px 34px rgba(0,0,0,.46)",
    });
    items.forEach(([label, enabled, action], index) => {
      if (index === 3) {
        const rule = document.createElement("div");
        rule.style.cssText = "height:1px;margin:4px;background:var(--border,#3b433f)";
        menu.appendChild(rule);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.role = "menuitem";
      button.disabled = !enabled;
      button.textContent = label;
      button.style.cssText = "display:block;width:100%;padding:8px 10px;border:0;border-radius:6px;background:transparent;color:var(--text,#f3f5f2);font:inherit;font-size:13px;text-align:left;cursor:pointer";
      if (!enabled) button.style.opacity = ".38";
      button.addEventListener("pointerenter", () => { if (enabled) button.style.background = "var(--row-hover,var(--surface-2,#29302c))"; });
      button.addEventListener("pointerleave", () => { button.style.background = "transparent"; });
      button.addEventListener("mousedown", event => event.preventDefault());
      button.addEventListener("click", async () => { close(); if (enabled) { restore(); await action(); } });
      menu.appendChild(button);
    });
    (event.target.closest('dialog[open]') || document.body).appendChild(menu);
    const bounds = menu.getBoundingClientRect();
    menu.style.left = Math.max(6, Math.min(event.clientX, innerWidth - bounds.width - 6)) + "px";
    menu.style.top = Math.max(6, Math.min(event.clientY, innerHeight - bounds.height - 6)) + "px";
  }

  window.TextContextMenu = {show(event, actions = []) {
    event.preventDefault();event.stopPropagation();
    const field=fieldFor(event.target);
    show(event,field,selectionText(field).trim(),actions);
  }};

  document.addEventListener("contextmenu", (event) => {
    if (event.defaultPrevented || event.target?.closest?.(".ems-ctx-menu,.ems-ctx-submenu")) return;
    const field = fieldFor(event.target);
    // Editable prose uses the native menu, including spelling suggestions.
    // Keep the app's copy/search menu for non-editable selected text.
    let nativeReady = false;
    try { nativeReady = window.__oneLossNativeEditingMenu === true || window.top.__oneLossNativeEditingMenu === true || window.top.__LINGUAR_BROWSER_TOOLS__ === true; } catch (_) {}
    if (field && (nativeReady || field.type === 'password')) return;
    const selected = selectionText(field).trim();
    if (!field && !selected) return;
    event.preventDefault();
    event.stopPropagation();
    show(event, field, selected);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!event.target?.closest?.(`#${MENU_ID}`)) close();
  }, true);
  window.addEventListener("blur", close);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.getElementById(MENU_ID)) {
      event.preventDefault();event.stopPropagation();close();
    }
  });
})();
