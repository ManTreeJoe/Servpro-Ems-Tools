/* Linguar Hub — shared keyboard shortcuts.
 *
 * Auto-wires the most common cross-panel hotkeys when the page
 * loads:
 *
 *   Ctrl+F  → focus + select #search-box (matches Tk's panel-wide
 *             "find" shortcut on every panel that has a search box)
 *   /       → same, when the user isn't already typing in an input
 *             (mirrors the Slack/Github single-key search idiom)
 *   Escape  → clear + blur #search-box (when it's focused) so a
 *             quick Esc bails out of an in-progress filter
 *
 * Each panel just needs to <script src="../web_shared/keyboard.js">
 * and have an element with id="search-box" on the page. The script
 * looks the element up lazily on every keystroke, so search boxes
 * that get rendered after page load (e.g. inside an iframe panel
 * that booted late) still get the binding.
 */
(function () {
  "use strict";

  function isTyping(el) {
    if (!el) return false;
    const tag = (el.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function focusSearch() {
    const box = document.getElementById("search-box");
    if (!box) return false;
    box.focus();
    try { box.select(); } catch (_) {}
    return true;
  }

  document.addEventListener("keydown", (e) => {
    // Ctrl+F / Cmd+F — focus search box if one is on the page.
    // Falls through to the browser's native find when there's no
    // search-box element (preserves the default behavior on read-
    // only panels like Cheat Sheet).
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey &&
        (e.key === "f" || e.key === "F")) {
      if (focusSearch()) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    // "/" focuses search when the user isn't already typing in an
    // input. Don't fire from inside modal text inputs, comment
    // boxes, etc.
    if (e.key === "/" && !isTyping(e.target) &&
        !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (focusSearch()) {
        e.preventDefault();
      }
      return;
    }
    // Escape inside the search box clears it (a fast way to bail
    // out of an in-progress filter). The "input" event listener the
    // panel already has fires automatically, so the filter resets.
    if (e.key === "Escape") {
      const box = document.getElementById("search-box");
      if (box && document.activeElement === box && box.value) {
        box.value = "";
        box.dispatchEvent(new Event("input", { bubbles: true }));
        e.preventDefault();
      }
    }
  });
})();
