/* EMS Tools — shared modal/overlay builder.
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

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function openModal({ title, sub, body, width, id, onClose } = {}) {
    const overlayId = id || DEFAULT_ID;
    closeModal(overlayId);
    const w = width || 620;
    const wrap = document.createElement("div");
    wrap.className = "overlay";
    wrap.id = overlayId;
    wrap.innerHTML = `
      <div class="overlay-backdrop"></div>
      <div class="overlay-panel" style="width:min(${w}px,92vw);">
        <header class="overlay-head">
          <div class="overlay-title">
            <div>
              <div class="overlay-name">${esc(title || "")}</div>
              ${sub ? `<div class="overlay-sub">${esc(sub)}</div>` : ""}
            </div>
          </div>
          <div class="overlay-actions">
            <button class="btn modal-close modal-close-icon">✕</button>
          </div>
        </header>
        <div class="overlay-body">
          ${body || ""}
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const close = () => closeModal(overlayId);
    wrap.querySelector(".overlay-backdrop").addEventListener("click", close);
    wrap.querySelectorAll(".modal-close").forEach((b) =>
      b.addEventListener("click", close));
    if (onClose) wrap._onClose = onClose;
    _openIds.push(overlayId);
    return wrap;
  }

  function closeModal(id) {
    const target = id || _openIds[_openIds.length - 1] || DEFAULT_ID;
    const el = document.getElementById(target);
    if (el) {
      try { el._onClose?.(); } catch (_) {}
      el.remove();
    }
    const idx = _openIds.indexOf(target);
    if (idx >= 0) _openIds.splice(idx, 1);
  }

  window.openModal = openModal;
  window.closeModal = closeModal;
})();
