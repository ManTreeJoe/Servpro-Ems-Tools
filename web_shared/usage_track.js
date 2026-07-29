/* EMS Tools — lightweight, privacy-safe usage tracker (client side).
 *
 * Drop-in: add <script src="../web_shared/usage_track.js"> to any panel
 * and it auto-records a 'view' on load plus a 'click' for every button
 * pressed (by its label/id — NOT job data). Events batch in memory and
 * flush to pywebview.api.track_events([...]) periodically + on hide, so
 * one delegated listener covers the whole panel with no per-button work.
 *
 * The backend method (usage_tracker.record) is optional — if a panel's
 * Api doesn't expose track_events yet, events simply buffer (capped) and
 * nothing errors.
 */
(function () {
  "use strict";

  // Tool name = the panel's asset folder ("audit_web_assets" → "audit"),
  // so each panel self-identifies without any per-panel config.
  function toolName() {
    try {
      const m = location.pathname.match(/([a-z0-9_]+)_web_assets/i);
      if (m) return m[1].replace(/_web$/, "");
    } catch (_) {}
    return (document.title || "app").split(/[\s—–-]/)[0].toLowerCase() || "app";
  }

  const TOOL = toolName();
  const CAP = 500;              // hard buffer cap so a broken flush can't grow forever
  let buffer = [];
  let flushing = false;

  function nowIso() {
    // Local time, "YYYY-MM-DD HH:MM:SS".
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
         + `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function push(action, label) {
    if (buffer.length >= CAP) buffer.shift();     // drop oldest
    buffer.push({ tool: TOOL, action, label: (label || "").slice(0, 80), ts: nowIso() });
    if (buffer.length >= 12) flush();             // flush on a full-ish batch
  }

  async function flush() {
    if (flushing || !buffer.length) return;
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.track_events) return;         // no backend yet → keep buffering
    flushing = true;
    const batch = buffer;
    buffer = [];
    try {
      await api.track_events(batch);
    } catch (_) {
      // Flush failed — put them back (front) so nothing is lost.
      buffer = batch.concat(buffer).slice(-CAP);
    } finally {
      flushing = false;
    }
  }

  // A readable label for a clicked control: explicit data-track wins, then
  // id, then trimmed text, then title. Emoji/whitespace collapsed.
  function labelFor(el) {
    const raw = el.getAttribute("data-track")
      || el.id
      || (el.textContent || "").trim()
      || el.getAttribute("title")
      || el.getAttribute("aria-label")
      || "";
    return raw.replace(/\s+/g, " ").trim().slice(0, 80);
  }

  document.addEventListener("click", (ev) => {
    try {
      const el = ev.target.closest(
        "button, .btn, [data-track], a[href], .filter, .chip, .tab");
      if (!el) return;
      const label = labelFor(el);
      if (label) push("click", label);
    } catch (_) {}
  }, true);

  // Flush cadence: every 15s, on a full-ish buffer (in push()), and on hide.
  setInterval(flush, 15000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);
  window.addEventListener("beforeunload", flush);

  // Record the panel view once the bridge is ready.
  function onReady() { push("view", ""); flush(); }
  if (window.pywebview && window.pywebview.api) onReady();
  else window.addEventListener("pywebviewready", onReady, { once: true });

  window.EmsUsage = { flush, track: (label) => push("click", label), tool: TOOL };
})();
