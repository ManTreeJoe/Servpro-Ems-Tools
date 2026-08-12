/* Shared Trello hover popover — Tk parity for the pinned-card
 * tooltip the audit / IUQ / APA / job-notes panels all use.
 *
 * Usage from any panel:
 *   import via:  <script src="../web_shared/trello_hover.js"></script>
 *   attach:      attachTrelloHover(buttonEl, cardId)
 *
 * Backend dependency: any panel that uses this must expose a
 * `trello_card_hover(card_id)` method on its Api. The audit panel
 * has the canonical implementation — others can either expose
 * their own or call into audit's via the iframe shim.
 */
"use strict";

(function () {
  // Hover popover cache so re-hovers within 60s don't re-fetch
  const _cache = new Map();
  const _CACHE_TTL = 60000;

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function _fetchCard(cardId) {
    const now = Date.now();
    const cached = _cache.get(cardId);
    if (cached && (now - cached.t) < _CACHE_TTL) return cached.data;
    let data = null;
    try {
      data = await pywebview.api.trello_card_hover(cardId);
    } catch (_) { data = null; }
    if (data?.ok) _cache.set(cardId, { t: now, data });
    return data;
  }

  function _buildPopover(data) {
    const el = document.createElement("div");
    el.className = "trello-hover-popover";
    el.style.cssText = `
      position:fixed; z-index:400; background:var(--surface);
      border:1px solid var(--border); border-radius:6px;
      padding:10px 14px; font-size:12px; max-width:340px;
      box-shadow:0 6px 20px rgba(0,0,0,.5); pointer-events:none;`;
    el.innerHTML = `
      <div style="font-weight:600;font-size:13px;margin-bottom:4px;">
        ${escapeHtml(data.name || "(no name)")}
      </div>
      <div style="font-size:11px;color:var(--text-muted);">
        ${escapeHtml(data.lane || "—")}${data.board ? " · " + escapeHtml(data.board) : ""}
      </div>
      ${data.last_activity
        ? `<div style="font-size:11px;color:var(--text-muted);margin-top:3px;">Last activity: ${escapeHtml(data.last_activity)}</div>`
        : ""}
      ${(data.labels || []).filter(Boolean).length
        ? `<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">
             ${data.labels.filter(Boolean).map((l) =>
               `<span style="background:var(--chip-bg);color:var(--text-muted);padding:1px 7px;border-radius:3px;font-size:10px;">${escapeHtml(l)}</span>`).join("")}
           </div>` : ""}
    `;
    return el;
  }

  function _position(popover, anchor) {
    const rect = anchor.getBoundingClientRect();
    document.body.appendChild(popover);
    const ph = popover.offsetHeight, pw = popover.offsetWidth;
    let top = rect.top - ph - 6;
    if (top < 8) top = rect.bottom + 6;  // flip below if off-screen
    let left = rect.left;
    if (left + pw > window.innerWidth - 8) {
      left = window.innerWidth - pw - 8;
    }
    popover.style.top = top + "px";
    popover.style.left = Math.max(8, left) + "px";
  }

  // Track every active popover so we can hide them globally when
  // events fire that should clear hover state (scroll, blur, click,
  // any new hover starting on a different anchor). Without this the
  // popover sometimes stays visible when the cursor moves quickly
  // off the anchor before mouseleave fires.
  // Holds each visible popover's OWN hide() — not the element. Removing
  // the element here instead left the owning closure still holding a
  // reference to a detached node, so its `popover` stayed truthy: the
  // stale value then made the next hover return early and that anchor
  // never showed a popover again.
  const _active = new Set();
  function _hideAll() {
    for (const h of [..._active]) {
      try { h(); } catch (_) {}
    }
    _active.clear();
  }
  // Document-wide hooks — one-time wiring per page load
  if (!window.__trelloHoverWired) {
    window.__trelloHoverWired = true;
    document.addEventListener("scroll",   _hideAll, true);
    document.addEventListener("wheel",    _hideAll, true);
    document.addEventListener("click",    _hideAll, true);
    document.addEventListener("keydown",  _hideAll);
    window.addEventListener("blur",       _hideAll);
    // Catch the iframe scroll case too — content area sits inside
    // a separate scroller; "scroll" capture catches that.
  }

  window.attachTrelloHover = function (anchor, cardId) {
    if (!anchor || !cardId) return;
    let timer = null, popover = null, liveness = null;
    function hide() {
      if (timer) { clearTimeout(timer); timer = null; }
      if (liveness) { clearInterval(liveness); liveness = null; }
      if (popover) {
        try { popover.remove(); } catch (_) {}
        popover = null;
      }
      _active.delete(hide);
    }
    anchor.addEventListener("mouseenter", () => {
      // Hide any popover from a previous anchor — moving between
      // rows now closes the old before opening the new.
      _hideAll();
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        const data = await _fetchCard(cardId);
        // The fetch is awaited, so the anchor may well be gone by now —
        // a list re-render during those few hundred ms would otherwise
        // strand a popover pointing at a row that no longer exists.
        if (!data?.ok || popover || !anchor.isConnected) return;
        popover = _buildPopover(data);
        _position(popover, anchor);
        _active.add(hide);
        // mouseleave is NOT guaranteed. A re-render can detach the anchor
        // mid-hover and a fast exit can skip the event entirely — in
        // either case nothing was left to take the popover down, so it
        // sat over the panel until something else happened to clear it.
        // Rather than add more events to miss, poll the two conditions
        // that actually define "should still be showing": the anchor is
        // still in the document, and the cursor is still on it.
        liveness = setInterval(() => {
          let alive = false;
          try { alive = anchor.isConnected && anchor.matches(":hover"); }
          catch (_) { alive = false; }
          if (!alive) hide();
        }, 250);
      }, 400);
    });
    anchor.addEventListener("mouseleave", hide);
  };
})();
