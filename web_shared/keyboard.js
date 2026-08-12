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

  // A dialog is open. Single-key shortcuts belong to the LIST behind it,
  // and firing them from a dialog moves a selection you cannot see —
  // or worse, acts on it.
  function isModalOpen() {
    const sel = ".overlay, #ad-modal, #apa-place-modal, #apa-add-modal," +
                " #cc-missing-modal, [data-modal]";
    let nodes;
    try { nodes = document.querySelectorAll(sel); } catch (_) { return false; }
    for (const n of nodes) {
      // offsetParent is null for display:none — a modal element left in
      // the DOM but hidden must not suppress every shortcut on the page.
      if (n.offsetParent !== null || n.getClientRects().length) return true;
    }
    return false;
  }

  // The one guard every panel's global keydown should ask.
  //
  // Each panel used to test `ev.target.tagName === "INPUT"` on its own,
  // which let every single-key shortcut through while typing in a
  // TEXTAREA: Enter opened a folder, "r" kicked off a full re-audit, j/k
  // moved the selection — all from inside a note or comment box.
  function shouldIgnoreKey(ev) {
    if (!ev) return false;
    if (isTyping(ev.target)) return true;
    if (isTyping(document.activeElement)) return true;
    return isModalOpen();
  }

  window.isTypingTarget = isTyping;
  window.isModalOpen = isModalOpen;
  window.shouldIgnoreKey = shouldIgnoreKey;

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
