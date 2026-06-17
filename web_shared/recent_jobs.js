/* EMS Tools — recently-opened jobs tracker.
 *
 * Stored in localStorage so it survives panel reopens + window
 * crashes. Capped at 10 entries. Each entry: {client, source, ts}
 * where source is the panel that touched the row (audit, iuq, etc.).
 *
 *   recordRecent({client: "Smith, John", source: "audit"})
 *   listRecent()           // [{client, source, ts, ago}, ...]
 *   clearRecent()
 */
(function () {
  "use strict";
  const KEY = "ems_recent_jobs";
  const MAX = 10;

  function read() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (_) { return []; }
  }

  function write(arr) {
    try { localStorage.setItem(KEY, JSON.stringify(arr.slice(0, MAX))); }
    catch (_) {}
  }

  function recordRecent(entry) {
    if (!entry || !entry.client) return;
    const client = String(entry.client).trim();
    if (!client) return;
    const cur = read().filter((r) =>
      (r.client || "").trim().toLowerCase() !== client.toLowerCase());
    cur.unshift({
      client, source: entry.source || "", ts: Date.now(),
    });
    write(cur);
  }

  function listRecent() {
    const now = Date.now();
    return read().map((r) => ({
      client: r.client || "",
      source: r.source || "",
      ts:     r.ts || 0,
      ago:    fmtAgo(now - (r.ts || 0)),
    }));
  }

  function clearRecent() {
    try { localStorage.removeItem(KEY); } catch (_) {}
  }

  function fmtAgo(ms) {
    if (!ms || ms < 0) return "";
    const m = Math.floor(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  window.recordRecent = recordRecent;
  window.listRecent   = listRecent;
  window.clearRecent  = clearRecent;
})();
