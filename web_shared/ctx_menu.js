/* EMS Tools — shared right-click context menu builder.
 *
 * Replaces the panel-local `showCtxMenu` / `openCtxMenu` builders
 * that audit / disputes / snapshot / IUQ / APA all had. One call:
 *
 *   showContextMenu(ev, items, opts?);
 *
 * where:
 *
 *   items = [
 *     { label: "Open Trello", action: () => …, iconImg: "…", disabled?: bool, color?: "var(--red)" },
 *     { sep: true },
 *     { label: "Status", submenu: [...] },         // hover-expand fly-out
 *     ...
 *   ]
 *
 *   opts = {
 *     id:      "audit-ctx",   // explicit element id (default: "ems-ctx-menu")
 *     minWidth: 240,
 *   }
 *
 * Auto-closes on outside click; auto-clamps to viewport; nested
 * submenus stay open while the cursor moves between parent + body.
 */
(function () {
  "use strict";

  const _MENU_ID = "ems-ctx-menu";
  let _activeSub = null;
  let _activeSubOwner = null;   // the parent button the fly-out belongs to
  let _subCloseTimer = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  // Hover-intent close. We DON'T rely on mouseleave's `relatedTarget` to
  // decide whether the cursor moved into the fly-out — in WebView2 it's
  // frequently null when crossing between separately-stacked fixed
  // elements, which closed the submenu before the user could click it.
  // Instead, leaving the parent OR the submenu schedules a short-delay
  // close; entering either one cancels it.
  function cancelSubClose() {
    if (_subCloseTimer) { clearTimeout(_subCloseTimer); _subCloseTimer = null; }
  }
  function scheduleSubClose() {
    cancelSubClose();
    _subCloseTimer = setTimeout(() => {
      _subCloseTimer = null;
      if (_activeSub) { _activeSub.remove(); _activeSub = null; }
      _activeSubOwner = null;
    }, 300);
  }

  function close() {
    cancelSubClose();
    document.getElementById(_MENU_ID)?.remove();
    document.querySelectorAll(".ems-ctx-submenu").forEach((s) => s.remove());
    _activeSub = null;
    _activeSubOwner = null;
  }

  function renderItem(m, it) {
    if (it.sep) {
      const d = document.createElement("div");
      d.style.cssText = "height:1px;background:var(--border);margin:4px 0;";
      m.appendChild(d);
      return;
    }
    const b = document.createElement("button");
    b.className = "ems-ctx-item" + (it.submenu ? " ems-ctx-sub" : "");
    b.style.cssText = `
      display:flex;align-items:center;gap:6px;width:100%;
      text-align:left;background:transparent;border:0;
      padding:7px 12px;cursor:${it.disabled ? "not-allowed" : "pointer"};
      color:${it.color || "var(--text)"};font:inherit;font-size:13px;
      ${it.disabled ? "opacity:.45;" : ""}
      ${it.muted ? "color:var(--text-muted);" : ""}`;
    if (it.iconImg) {
      const img = document.createElement("img");
      img.src = it.iconImg; img.alt = "";
      img.style.cssText = "width:13px;height:13px;flex-shrink:0;";
      img.onerror = () => img.remove();
      b.appendChild(img);
    }
    const span = document.createElement("span");
    span.style.cssText = "flex:1;white-space:nowrap;";
    span.textContent = it.label;
    b.appendChild(span);
    if (it.submenu) {
      const arrow = document.createElement("span");
      arrow.style.cssText = "color:var(--text-muted);font-size:11px;";
      arrow.textContent = "▸";
      b.appendChild(arrow);
    }
    if (!it.disabled) {
      b.addEventListener("mouseenter", () => {
        b.style.background = "var(--row-hover, var(--border))";
        cancelSubClose();
        if (it.submenu) {
          // Open this fly-out (reuse the existing one if it's already
          // this button's, to avoid a flicker on re-enter).
          if (_activeSubOwner !== b) { openSub(b, it.submenu); _activeSubOwner = b; }
        } else if (_activeSub && !b.closest(".ems-ctx-submenu")) {
          // Hovering a non-submenu row IN THE PARENT menu closes the
          // fly-out (after the grace delay). Items INSIDE the fly-out
          // must NOT trigger this — they'd close their own menu.
          scheduleSubClose();
        }
      });
      b.addEventListener("mouseleave", () => {
        b.style.background = "transparent";
        if (it.submenu) scheduleSubClose();
      });
      if (!it.submenu) {
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          close();
          try { await it.action?.(); } catch (_) {}
        });
      }
    }
    m.appendChild(b);
  }

  function openSub(parentBtn, items) {
    if (_activeSub) { _activeSub.remove(); _activeSub = null; }
    const sub = document.createElement("div");
    sub.className = "ems-ctx-submenu";
    sub.style.cssText = `
      position:fixed;background:var(--surface);
      border:1px solid var(--border);border-radius:6px;
      box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:301;
      min-width:200px;padding:4px 0;font-size:13px;`;
    items.forEach((it) => renderItem(sub, it));
    document.body.appendChild(sub);
    const parent = document.getElementById(_MENU_ID);
    const pr = parent.getBoundingClientRect();
    const rr = parentBtn.getBoundingClientRect();
    const sr = sub.getBoundingClientRect();
    let left = pr.right - 2;
    if (left + sr.width + 8 > window.innerWidth) {
      left = pr.left - sr.width + 2;
    }
    let top = rr.top;
    if (top + sr.height + 8 > window.innerHeight) {
      top = Math.max(8, window.innerHeight - sr.height - 8);
    }
    sub.style.left = left + "px";
    sub.style.top = top + "px";
    // Entering the fly-out cancels the pending close; leaving it (without
    // re-entering the parent) schedules one. No relatedTarget reliance.
    sub.addEventListener("mouseenter", cancelSubClose);
    sub.addEventListener("mouseleave", scheduleSubClose);
    _activeSub = sub;
  }

  function showContextMenu(ev, items, opts) {
    ev?.preventDefault?.();
    ev?.stopPropagation?.();
    close();
    const o = opts || {};
    const m = document.createElement("div");
    m.id = _MENU_ID;
    m.className = "ems-ctx-menu";
    m.style.cssText = `
      position:fixed;background:var(--surface);
      border:1px solid var(--border);border-radius:6px;
      box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:300;
      min-width:${o.minWidth || 220}px;padding:4px 0;
      visibility:hidden;`;
    items.forEach((it) => renderItem(m, it));
    document.body.appendChild(m);
    // Position at cursor, clamp to viewport
    const r = m.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight, pad = 6;
    let l = ev.clientX, t = ev.clientY;
    if (l + r.width + pad > vw) l = Math.max(pad, vw - r.width - pad);
    if (t + r.height + pad > vh) t = Math.max(pad, vh - r.height - pad);
    m.style.left = l + "px";
    m.style.top = t + "px";
    m.style.visibility = "visible";
  }

  // Outside-click closer — registered once globally.
  if (!window._emsCtxCloserBound) {
    document.addEventListener("click", (e) => {
      if (e.target.closest(`#${_MENU_ID}`) ||
          e.target.closest(".ems-ctx-submenu")) return;
      close();
    });
    // Right-click anywhere closes too — otherwise opening one ctx
    // menu and right-clicking elsewhere leaves the old one open.
    document.addEventListener("contextmenu", (e) => {
      // Only close if the new right-click is OUTSIDE the current menu.
      if (e.target.closest(`#${_MENU_ID}`) ||
          e.target.closest(".ems-ctx-submenu")) return;
      close();
    });
    window._emsCtxCloserBound = true;
  }

  window.showContextMenu = showContextMenu;
  window.closeContextMenu = close;
})();
