/* Linguar Hub — shared modal/overlay builder.
 *
 * Replaces the panel-local `createOverlay` (audit) and `mkModal` (IUQ)
 * factories. Same overlay-panel/overlay-head/overlay-body class
 * structure so the existing audit_web_assets/app.css styles apply
 * directly. Panels that import audit's app.css get this for free.
 *
 * Usage:
 *
 *   const overlay = openModal({
 *     title: "📥 Import",
 *     sub:   "Scans Downloads for relevant zips",
 *     body:  htmlString,   // raw inner HTML, escape callers' strings
 *     width: 620,          // optional, default 620
 *     id:    "my-modal",   // optional, default "modal-overlay"
 *     onClose: () => {...} // optional
 *   });
 *
 *   closeModal(id?);  // omitting id closes the last-opened modal
 *
 * Every element with class `.modal-close` inside the overlay gets a
 * close handler — header X, footer Cancel/Close, etc. — so the body
 * can include those classes without per-call wiring.
 *
 * Snapshot's `mkSnapModal` is structurally different (no overlay
 * classes, inline styles, no sub) and is NOT covered by this helper.
 */
(function () {
  "use strict";

  const DEFAULT_ID = "modal-overlay";
  const _openIds = [];
  const FOCUSABLE = [
    'button:not([disabled])', '[href]', 'input:not([disabled])',
    'select:not([disabled])', 'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function openModal({ title, sub, body, width, id, onClose } = {}) {
    const overlayId = id || DEFAULT_ID;
    closeModal(overlayId);
    const w = width || 620;
    const invoker = document.activeElement;
    const titleId = `${overlayId}-title`;
    const wrap = document.createElement("div");
    wrap.className = "overlay";
    wrap.id = overlayId;
    wrap.innerHTML = `
      <div class="overlay-backdrop" aria-hidden="true"></div>
      <div class="overlay-panel" style="width:min(${w}px,92vw);"
           role="dialog" aria-modal="true" aria-labelledby="${esc(titleId)}"
           tabindex="-1">
        <header class="overlay-head">
          <div class="overlay-title">
            <div>
              <div class="overlay-name" id="${esc(titleId)}">${esc(title || "Dialog")}</div>
              ${sub ? `<div class="overlay-sub">${esc(sub)}</div>` : ""}
            </div>
          </div>
          <div class="overlay-actions">
            <button type="button" class="btn modal-close modal-close-icon"
                    aria-label="Close dialog">✕</button>
          </div>
        </header>
        <div class="overlay-body">
          ${body || ""}
        </div>
      </div>`;
    document.body.appendChild(wrap);
    wrap._returnFocus = invoker && invoker !== document.body ? invoker : null;
    // Block mouse, keyboard, and assistive-technology interaction with the
    // page behind the dialog. Preserve prior inert state for nested dialogs.
    wrap._inerted = Array.from(document.body.children)
      .filter((el) => el !== wrap)
      .map((el) => ({ el, wasInert: !!el.inert }));
    wrap._inerted.forEach(({el}) => { el.inert = true; });
    if (_openIds.length === 0) {
      wrap._bodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    const close = () => closeModal(overlayId);
    wrap.querySelector(".overlay-backdrop").addEventListener("click", close);
    // DELEGATED, not wired per button. Binding each .modal-close at
    // creation only ever reaches the ones present right then — and most
    // of these dialogs replace their body once async content lands, so
    // every Close/Cancel button in the REPLACED markup came up dead.
    // Callers were expected to re-bind by hand; some remembered, most
    // didn't. `closest` so a click on an icon inside the button counts.
    wrap.addEventListener("click", (e) => {
      const btn = e.target && e.target.closest
        ? e.target.closest(".modal-close") : null;
      if (btn && wrap.contains(btn)) close();
    });
    wrap.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(wrap.querySelectorAll(FOCUSABLE))
        .filter((el) => el.getClientRects().length > 0);
      if (!items.length) {
        e.preventDefault();
        wrap.querySelector(".overlay-panel")?.focus();
        return;
      }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    });
    if (onClose) wrap._onClose = onClose;
    _openIds.push(overlayId);
    // Focus after insertion so WebView2 can determine visibility correctly.
    const initial = wrap.querySelector('[autofocus], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])')
      || wrap.querySelector(".overlay-panel");
    initial?.focus();
    return wrap;
  }

  function closeModal(id) {
    const target = id || _openIds[_openIds.length - 1] || DEFAULT_ID;
    const el = document.getElementById(target);
    if (el) {
      try { el._onClose?.(); } catch (_) {}
      (el._inerted || []).forEach(({el: sibling, wasInert}) => {
        if (sibling?.isConnected) sibling.inert = wasInert;
      });
      const returnFocus = el._returnFocus;
      const oldOverflow = el._bodyOverflow;
      el.remove();
      if (_openIds.length <= 1 && oldOverflow !== undefined) {
        document.body.style.overflow = oldOverflow;
      }
      if (returnFocus?.isConnected && typeof returnFocus.focus === "function") {
        returnFocus.focus();
      }
    }
    const idx = _openIds.indexOf(target);
    if (idx >= 0) _openIds.splice(idx, 1);
  }

  window.openModal = openModal;
  window.closeModal = closeModal;
})();
