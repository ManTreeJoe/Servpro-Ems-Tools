/* EMS Tools — shared cross-tool "Open in…" right-click menu.
 *
 * One helper every panel reuses so a job can be opened in any other
 * tool from a right-click. Navigation goes UP to the home shell via
 * postMessage ({type:"ems-navigate", key, focus}); the shell switches
 * the content frame to that tool and hands it the `focus` client so
 * the target filters/selects the job on load.
 *
 * Usage:
 *   el.addEventListener("contextmenu", (ev) =>
 *     window.emsOpenInMenu(ev, clientName, {
 *       onTrello: () => pywebview.api.open_trello_for_tracked(clientName),
 *       onFolder: () => pywebview.api.some_open_folder(clientName),
 *       onXA:     () => pywebview.api.some_open_xa(clientName),
 *       extra:    [ {label:"…", action:…}, {sep:true}, … ],  // panel-specific
 *     }));
 *
 * Requires web_shared/ctx_menu.js (window.showContextMenu) to be loaded.
 */
(function () {
  "use strict";

  // Tools the "Open in ▸" submenu can jump to. key = sidebar/nav key
  // the shell understands; label carries the tool's icon.
  const NAV_TARGETS = [
    { key: "audit",    label: "🔎 Audit" },
    { key: "snapshot", label: "📸 Snapshot" },
  ];

  function navTo(key, focus) {
    try {
      window.parent.postMessage(
        { type: "ems-navigate", key: key, focus: focus || "" }, "*");
    } catch (_) { /* standalone (no shell) — no-op */ }
  }

  function api() { return (window.pywebview && window.pywebview.api) || null; }

  // Toast a failed direct-action result (best-effort — toast_log.js may
  // not be loaded in every panel).
  function reportFail(label, res) {
    if (res && res.ok === false && window.toastLog) {
      window.toastLog(`${label}: ${res.error || "not found"}`);
    }
  }

  // Default direct-action handlers — call the SHARED HomeApi resolvers
  // (open_trello_for_client / open_folder_for_client / open_xa_for_client)
  // so any panel gets Trello / Folder / XA with zero extra wiring.
  function defTrello(client) {
    return async () => { const a = api(); if (a)
      reportFail("Open Trello", await a.open_trello_for_client(client)); };
  }
  function defFolder(client) {
    return async () => { const a = api(); if (a)
      reportFail("Open folder", await a.open_folder_for_client(client)); };
  }
  function defXA(client) {
    return async () => { const a = api(); if (a)
      reportFail("Open XA", await a.open_xa_for_client(client)); };
  }
  function defCompanyCam(client) {
    return async () => { const a = api(); if (a)
      reportFail("Open CompanyCam", await a.open_companycam_for_client(client)); };
  }

  // Build the standard "Open in…" items for a job. `client` required.
  // Direct actions (Trello / Folder / XA) are included BY DEFAULT via the
  // shared resolvers; pass `opts.onTrello/onFolder/onXA` to override one,
  // or set it to `false` to drop that row. `opts.exclude` (array of nav
  // keys) drops self-targets; `opts.extra` appends panel-specific items.
  function openInItems(client, opts) {
    opts = opts || {};
    const exclude = new Set(opts.exclude || []);
    const sub = NAV_TARGETS
      .filter((t) => !exclude.has(t.key))
      .map((t) => ({ label: t.label, action: () => navTo(t.key, client) }));
    const items = [{ label: "Open in ▸", submenu: sub }];
    const pick = (o, def) => (o === false ? null : (o || def));
    const onTrello = pick(opts.onTrello, defTrello(client));
    const onFolder = pick(opts.onFolder, defFolder(client));
    const onXA     = pick(opts.onXA,     defXA(client));
    const onCC     = pick(opts.onCompanyCam, defCompanyCam(client));
    const direct = [];
    if (onTrello) direct.push({
      label: "Open Trello card",
      iconImg: "../web_shared/trello.png", action: onTrello });
    if (onFolder) direct.push({
      label: "📁 Open OD folder", action: onFolder });
    if (onXA) direct.push({
      label: "🔗 Open XactAnalysis", action: onXA });
    if (onCC) direct.push({
      label: "📸 Open in CompanyCam", action: onCC });
    if (direct.length) { items.push({ sep: true }); items.push(...direct); }
    if (opts.extra && opts.extra.length) {
      items.push({ sep: true }); items.push(...opts.extra);
    }
    return items;
  }

  function openInMenu(ev, client, opts) {
    if (!window.showContextMenu || !client) return;
    window.showContextMenu(ev, openInItems(client, opts), { minWidth: 210 });
  }

  // ── Deep-link receiver (target side) ──────────────────────────────
  // A panel calls this on boot to pick up a `?focus=<client>` query the
  // shell appended to its iframe src, returning the client name (or "").
  // The panel decides how to focus (usually: set its search box).
  function deepLinkFocus() {
    try {
      return new URLSearchParams(window.location.search).get("focus") || "";
    } catch (_) { return ""; }
  }

  window.emsOpenInItems = openInItems;
  window.emsOpenInMenu = openInMenu;
  window.emsNavigateTo = navTo;
  window.emsDeepLinkFocus = deepLinkFocus;
})();
