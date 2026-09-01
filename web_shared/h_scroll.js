/* Linguar Hub — horizontal scroll helper.
 *
 * Trello-style click-and-drag scrolling + wheel-to-horizontal on
 * any container marked with [data-hdrag] (or a known class like
 * `.board` used by APA Monitor). Drop the script tag into any
 * tool's index.html — the helper auto-detects containers via
 * MutationObserver so re-rendered scrollers get rewired without
 * the tool needing to know.
 */
(function () {
  "use strict";

  function isInteractive(el) {
    // Clicks on buttons / inputs / links stay as clicks; drag only
    // engages when the mousedown lands on the container itself or
    // inert children.
    return !!el.closest(
      "button, a, input, textarea, select, [contenteditable], " +
      "[draggable=\"true\"], .item, [data-no-drag]");
  }

  function attachDragScroll(el) {
    if (el.dataset.hdragInit) return;
    el.dataset.hdragInit = "1";

    let isDown = false;
    let pointerId = null;
    let startX = 0;
    let scrollLeft = 0;
    let moved = false;
    let dragFrame = 0;
    let pendingX = 0;
    let wheelFrame = 0;
    let wheelTarget = 0;

    function clamp(value) {
      return Math.max(0, Math.min(value, el.scrollWidth - el.clientWidth));
    }

    function paintDrag() {
      dragFrame = 0;
      if (!isDown) return;
      const walk = pendingX - startX;
      if (Math.abs(walk) > 2) moved = true;
      el.scrollLeft = clamp(scrollLeft - walk);
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.pointerType === "touch") return;
      if (isInteractive(e.target)) return;
      isDown = true;
      pointerId = e.pointerId;
      moved = false;
      el.classList.add("hdrag-active");
      startX = e.clientX;
      pendingX = e.clientX;
      scrollLeft = el.scrollLeft;
      e.preventDefault();
      try { el.setPointerCapture(pointerId); } catch (_) { /* optional */ }
    });

    function endDrag(e) {
      if (e && pointerId !== null && e.pointerId !== pointerId) return;
      if (dragFrame) {
        cancelAnimationFrame(dragFrame);
        paintDrag();
      }
      isDown = false;
      if (pointerId !== null) {
        try { el.releasePointerCapture(pointerId); } catch (_) { /* already released */ }
      }
      pointerId = null;
      el.classList.remove("hdrag-active");
    }
    el.addEventListener("pointerup", endDrag);
    el.addEventListener("pointercancel", endDrag);
    el.addEventListener("lostpointercapture", endDrag);

    el.addEventListener("pointermove", (e) => {
      if (!isDown || e.pointerId !== pointerId) return;
      e.preventDefault();
      pendingX = e.clientX;
      if (!dragFrame) dragFrame = requestAnimationFrame(paintDrag);
    });

    // Click swallow: when the user drag-scrolled past a click target,
    // suppress the resulting click so they don't accidentally trigger
    // a button or item open.
    el.addEventListener("click", (e) => {
      if (moved) {
        e.preventDefault();
        e.stopPropagation();
        moved = false;
      }
    }, true);

    // Wheel → horizontal scroll. Triggers when:
    //   - Shift is held (universal "horizontal" gesture)
    //   - OR the container has horizontal overflow + the user is
    //     scrolling primarily vertically (no native trackpad
    //     horizontal-scroll signal)
    // Opt out of the auto vertical→horizontal conversion with
    // [data-hdrag-nowheel]. With [data-hdrag-smartwheel], a lane keeps
    // the wheel while it can scroll in that direction; at its boundary
    // the same wheel gesture pans the board.
    // Shift+wheel still pans horizontally since it's an explicit gesture.
    el.addEventListener("wheel", (e) => {
      const hasHScroll = el.scrollWidth > el.clientWidth + 1;
      if (!hasHScroll) return;
      const noAuto = el.hasAttribute("data-hdrag-nowheel");
      const absX = Math.abs(e.deltaX);
      const absY = Math.abs(e.deltaY);
      const horizontal = absX > 0 && absX >= absY * .65;
      const vertical = absY > absX;
      const smartWheel = el.hasAttribute("data-hdrag-smartwheel");
      const verticalPane = smartWheel ? e.target.closest(".lane-cards") : null;
      const canScrollPane = verticalPane && verticalPane.scrollHeight > verticalPane.clientHeight + 1 && (
        (e.deltaY < 0 && verticalPane.scrollTop > 0) ||
        (e.deltaY > 0 && verticalPane.scrollTop + verticalPane.clientHeight < verticalPane.scrollHeight - 1)
      );
      if (!e.shiftKey && !horizontal && canScrollPane) return;
      // Logitech MX Master thumb wheels arrive as deltaX. WebView2 does not
      // consistently apply that native horizontal delta to nested boards, so
      // consume it explicitly. Vertical wheels are converted only on boards
      // that have not opted out with data-hdrag-nowheel.
      if (!horizontal && !e.shiftKey && (noAuto || !vertical)) return;
      let delta = horizontal ? e.deltaX : e.deltaY;
      if (e.shiftKey && absX > absY) delta = e.deltaX;
      // deltaMode 1 is lines (common in Logitech Options+); pixels are mode 0.
      if (e.deltaMode === 1) delta *= 22;
      else if (e.deltaMode === 2) delta *= el.clientWidth * .85;
      e.preventDefault();
      if (!wheelFrame) wheelTarget = el.scrollLeft;
      wheelTarget = clamp(wheelTarget + delta);
      if (!wheelFrame) wheelFrame = requestAnimationFrame(() => {
        wheelFrame = 0;
        el.scrollLeft = wheelTarget;
      });
    }, { passive: false });
  }

  function scan() {
    document.querySelectorAll(".board, [data-hdrag]").forEach(attachDragScroll);
  }

  function injectStyles() {
    if (document.getElementById("hdrag-styles")) return;
    const s = document.createElement("style");
    s.id = "hdrag-styles";
    s.textContent = `
      .board, [data-hdrag] {
        cursor: grab;
        scroll-behavior: auto;   /* drag-scroll feels broken with smooth */
        overscroll-behavior-inline: contain;
      }
      .board.hdrag-active, [data-hdrag].hdrag-active {
        cursor: grabbing;
        user-select: none;
      }
      .board.hdrag-active *, [data-hdrag].hdrag-active * {
        cursor: grabbing;
      }
    `;
    document.head.appendChild(s);
  }

  function init() {
    injectStyles();
    scan();
    // Re-scan on DOM mutations — APA re-renders the board when the
    // user changes dates, which would otherwise leave the new
    // board element unwired.
    try {
      let scanFrame = 0;
      const obs = new MutationObserver(() => {
        // Large board renders can emit hundreds of mutations. One whole-page
        // query per mutation visibly stalls pointer scrolling, so scan once
        // at the next paint instead.
        if (!scanFrame) scanFrame = requestAnimationFrame(() => {
          scanFrame = 0;
          scan();
        });
      });
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (_) { /* no MutationObserver — give up gracefully */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
