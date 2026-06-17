/* EMS Tools — horizontal scroll helper.
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
      "button, a, input, textarea, select, [contenteditable], [data-no-drag]");
  }

  function attachDragScroll(el) {
    if (el.dataset.hdragInit) return;
    el.dataset.hdragInit = "1";

    let isDown = false;
    let startX = 0;
    let scrollLeft = 0;
    let moved = false;

    el.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;            // left button only
      if (isInteractive(e.target)) return;
      isDown = true;
      moved = false;
      el.classList.add("hdrag-active");
      startX = e.pageX - el.offsetLeft;
      scrollLeft = el.scrollLeft;
    });

    function endDrag() {
      isDown = false;
      el.classList.remove("hdrag-active");
    }
    el.addEventListener("mouseleave", endDrag);
    el.addEventListener("mouseup", endDrag);
    window.addEventListener("mouseup", endDrag);

    el.addEventListener("mousemove", (e) => {
      if (!isDown) return;
      e.preventDefault();
      const x = e.pageX - el.offsetLeft;
      const walk = x - startX;
      if (Math.abs(walk) > 4) moved = true;
      el.scrollLeft = scrollLeft - walk;
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
    // [data-hdrag-nowheel] (e.g. the Pipeline board, where a vertical
    // wheel should scroll the cards inside a lane, not pan the row).
    // Shift+wheel still pans horizontally since it's an explicit gesture.
    el.addEventListener("wheel", (e) => {
      const hasHScroll = el.scrollWidth > el.clientWidth + 1;
      if (!hasHScroll) return;
      const noAuto = el.hasAttribute("data-hdrag-nowheel");
      const vertical = Math.abs(e.deltaY) > Math.abs(e.deltaX);
      if (e.shiftKey || (!noAuto && vertical && Math.abs(e.deltaX) < 5)) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
      }
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
      const obs = new MutationObserver(scan);
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (_) { /* no MutationObserver — give up gracefully */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
