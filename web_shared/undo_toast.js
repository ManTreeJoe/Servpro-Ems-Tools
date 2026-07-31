/* Linguar Hub — shared undo toast.
 *
 * Optimistic action pattern: UI updates immediately + user sees a
 * "Item dismissed · Undo" toast at the bottom of the screen. After
 * the timeout the actual backend mutation fires. Click Undo before
 * the timeout and the mutation is cancelled.
 *
 *   showUndoToast({
 *     message:    "🤫 Snoozed Jones, John for 24h",
 *     durationMs: 5000,
 *     onCommit:   async () => await pywebview.api.dismiss(cardId, rule),
 *     onUndo:     () => restoreRowInState(),
 *   });
 *
 * Multiple toasts stack vertically (newest on top). Each toast is
 * keyed by an internal id so you can dismiss them programmatically
 * via closeUndoToast(id) if needed.
 */
(function () {
  "use strict";
  let _seq = 0;
  const _active = new Map();   // id -> { el, timer, committed }

  function ensureContainer() {
    let c = document.getElementById("ems-undo-toasts");
    if (!c) {
      c = document.createElement("div");
      c.id = "ems-undo-toasts";
      c.style.cssText = `
        position:fixed;left:50%;bottom:18px;transform:translateX(-50%);
        z-index:400;display:flex;flex-direction:column-reverse;gap:8px;
        pointer-events:none;`;
      document.body.appendChild(c);
    }
    return c;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }

  function showUndoToast({ message, durationMs, onCommit, onUndo }) {
    const id = ++_seq;
    const dur = Math.max(1500, parseInt(durationMs || 5000, 10));
    const c = ensureContainer();
    const el = document.createElement("div");
    el.style.cssText = `
      pointer-events:auto;
      background:#202020;color:#FFF;border:1px solid #2A2A2A;border-radius:8px;
      padding:10px 14px;display:flex;align-items:center;gap:14px;
      box-shadow:0 6px 22px rgba(0,0,0,.55);font-size:13px;
      opacity:0;transform:translateY(8px);transition:opacity 160ms,transform 160ms;
      max-width:520px;`;
    el.innerHTML = `
      <span style="flex:1;">${esc(message || "Action queued")}</span>
      <span style="font-variant-numeric:tabular-nums;color:#888;font-size:11px;"
            data-role="countdown">${Math.ceil(dur/1000)}s</span>
      <button data-role="undo" style="
        background:transparent;border:1px solid #555;color:#FFF;
        border-radius:5px;padding:4px 10px;cursor:pointer;font:inherit;
        font-size:12px;font-weight:700;">Undo</button>`;
    c.appendChild(el);
    requestAnimationFrame(() => {
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    });

    const entry = { el, committed: false, timer: null, countdownTimer: null };
    _active.set(id, entry);

    const commit = async () => {
      if (entry.committed) return;
      entry.committed = true;
      dismiss();
      try { await onCommit?.(); } catch (err) { console.error(err); }
    };
    const undo = () => {
      if (entry.committed) return;
      entry.committed = true;
      dismiss();
      try { onUndo?.(); } catch (err) { console.error(err); }
    };
    const dismiss = () => {
      clearTimeout(entry.timer);
      clearInterval(entry.countdownTimer);
      el.style.opacity = "0";
      el.style.transform = "translateY(8px)";
      setTimeout(() => { el.remove(); _active.delete(id); }, 180);
    };

    el.querySelector('[data-role="undo"]').addEventListener("click", undo);
    entry.timer = setTimeout(commit, dur);
    // Live countdown so the user can see how much time is left.
    let remaining = dur;
    const cdEl = el.querySelector('[data-role="countdown"]');
    entry.countdownTimer = setInterval(() => {
      remaining -= 500;
      if (cdEl) cdEl.textContent = Math.max(0, Math.ceil(remaining / 1000)) + "s";
    }, 500);
    return id;
  }

  function closeUndoToast(id) {
    const e = _active.get(id);
    if (!e) return;
    clearTimeout(e.timer); clearInterval(e.countdownTimer);
    e.el.remove(); _active.delete(id);
  }

  window.showUndoToast = showUndoToast;
  window.closeUndoToast = closeUndoToast;
})();
