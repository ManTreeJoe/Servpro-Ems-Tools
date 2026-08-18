/* 📚 Resources — the reading end of resources_index.
 *
 * Search is a round trip to SQLite, not a walk of the share, so it can
 * run on keystrokes behind a short debounce. The REBUILD is the slow one
 * (~47s) and is polled rather than awaited, or the window looks hung.
 */
"use strict";

const $ = (s) => document.querySelector(s);
const state = { area: "", rows: [], timer: null };

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function setStatus(msg, kind) {
  const el = $("#status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = kind || "";
}

const ICONS = {
  ".pdf": "📕", ".doc": "📘", ".docx": "📘", ".xls": "📗", ".xlsx": "📗",
  ".ppt": "📙", ".pptx": "📙", ".jpg": "🖼", ".jpeg": "🖼", ".png": "🖼",
  ".zip": "🗜", ".msg": "✉", ".eml": "✉", ".txt": "📄", ".csv": "📗",
};
const icon = (ext) => ICONS[String(ext || "").toLowerCase()] || "📄";

// Highlight the search words in the name, so a hit in a list of similar
// filenames says WHY it matched.
function hilite(text, q) {
  let html = esc(text);
  for (const tok of String(q || "").split(/\s+/).filter(Boolean)) {
    const safe = esc(tok).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(`(^|>)([^<]*)(${safe})`, "gi"),
                        (m, a, b, hit) => `${a}${b}<mark>${hit}</mark>`);
  }
  return html;
}

async function loadAreas() {
  let s;
  try { s = await pywebview.api.stats(); } catch (e) { return; }
  const areas = (s && s.areas) || [];
  const total = (s && s.files) || 0;
  const age = s && s.age_hours;
  $("#areas").innerHTML =
    `<div class="area${state.area ? "" : " on"}" data-top="">
       <span>All</span><span class="n">${total.toLocaleString()}</span></div>`
    + areas.map((a) => `
      <div class="area${state.area === a.top ? " on" : ""}" data-top="${esc(a.top)}">
        <span>${esc(a.top)}</span><span class="n">${a.n.toLocaleString()}</span>
      </div>`).join("");
  $("#areas").querySelectorAll(".area").forEach((el) =>
    el.addEventListener("click", () => {
      state.area = el.dataset.top || "";
      loadAreas();
      run();
    }));
  if (!total) {
    $("#hint").innerHTML =
      "The index is empty. Hit <b>↻ Rebuild</b> to walk the share — "
      + "about a minute.";
  } else {
    $("#hint").innerHTML =
      `${total.toLocaleString()} files indexed`
      + (age != null ? ` · rebuilt ${age < 1 ? "just now"
                                             : age.toFixed(0) + "h ago"}` : "")
      + (state.area ? ` · in <b>${esc(state.area)}</b>` : "");
  }
}

function render(rows, q) {
  if (!rows.length) {
    $("#rows").innerHTML = `<div class="hint">${
      q ? `Nothing matches “${esc(q)}”` : "Nothing here"}${
      state.area ? ` in ${esc(state.area)}` : ""}.</div>`;
    return;
  }
  $("#rows").innerHTML = rows.map((r, i) => `
    <div class="row" data-i="${i}">
      <div class="ico">${icon(r.ext)}</div>
      <div class="mid">
        <div class="name">${hilite(r.name, q)}</div>
        <div class="where">${esc(r.folder)}</div>
        <div class="meta">${r.size_kb ? r.size_kb.toLocaleString() + " KB" : ""}</div>
      </div>
      <div class="acts">
        <button class="btn" data-act="open" title="Open the file">Open</button>
        <button class="btn" data-act="folder" title="Show it in Explorer">📁</button>
        <button class="btn" data-act="copy" title="Copy the full path">⧉</button>
      </div>
    </div>`).join("");
  $("#rows").querySelectorAll(".row").forEach((el) => {
    const r = rows[+el.dataset.i];
    el.querySelectorAll("[data-act]").forEach((b) =>
      b.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const act = b.dataset.act;
        try {
          if (act === "open") {
            const res = await pywebview.api.open_file(r.path);
            setStatus(res && res.ok ? `Opened ${r.name}`
                                    : (res && res.error) || "Couldn't open it",
                      res && res.ok ? "ok" : "warn");
          } else if (act === "folder") {
            const res = await pywebview.api.open_folder(r.path);
            if (res && !res.ok) setStatus(res.error || "Couldn't open it", "warn");
          } else {
            const res = await pywebview.api.copy_path(r.path);
            if (res && res.ok) setStatus("Path copied", "ok");
            else {
              await navigator.clipboard.writeText((res && res.text) || r.path);
              setStatus("Path copied", "ok");
            }
          }
        } catch (ex) { setStatus(String(ex), "error"); }
      }));
    // Double-click the row is the same as Open — the obvious gesture.
    el.addEventListener("dblclick", () => pywebview.api.open_file(r.path));
  });
}

async function run() {
  const q = ($("#q").value || "").trim();
  const ext = $("#ext").value || "";
  // An AREA (or a type) is a query in its own right — clicking "Vendors"
  // means "show me what's in Vendors". Bailing out whenever the search
  // box was empty is what made the panel show every area and its count
  // and then none of the files in them.
  if (!q && !state.area && !ext) {
    $("#rows").innerHTML =
      `<div class="hint">Pick an area on the left, or search for a `
      + `file — forms, COIs, vendors, templates.</div>`;
    loadAreas();
    return;
  }
  let res;
  try {
    res = await pywebview.api.search(q, ext, state.area, 300);
  } catch (ex) {
    setStatus(String(ex), "error");
    return;
  }
  if (!res || !res.ok) {
    setStatus((res && res.error) || "Search failed", "error");
    return;
  }
  state.rows = res.rows || [];
  render(state.rows, q);
  const what = q ? `${res.count} match${res.count === 1 ? "" : "es"} for “${esc(q)}”`
                 : `${res.count} file${res.count === 1 ? "" : "s"}`;
  $("#hint").innerHTML = what
    + (state.area ? ` in <b>${esc(state.area)}</b>` : "")
    + (ext ? ` · ${esc(ext).toUpperCase()}` : "")
    + (res.count >= 300 ? ` <span class="muted">(showing the newest 300 —
       narrow it with a search)</span>` : "");
}

// The rebuild is polled, not awaited: 47 seconds of a blocked window is
// indistinguishable from a hang.
async function rebuild() {
  const btn = $("#rebuild");
  btn.disabled = true;
  let r;
  try { r = await pywebview.api.rebuild(); }
  catch (ex) {
    btn.disabled = false;
    if (window.Progress) window.Progress.fail();
    setStatus(String(ex), "error");
    return;
  }
  if (!r || !r.ok) {
    btn.disabled = false;
    setStatus((r && r.error) || "Couldn't start", "warn");
    return;
  }
  if (window.Progress) window.Progress.start();   // before the first poll
  const poll = setInterval(async () => {
    let p;
    try { p = await pywebview.api.rebuild_progress(); } catch (e) { return; }
    const d = (p && p.progress) || {};
    if (p && p.building) {
      // This one POLLS rather than emitting events, so it drives the bar
      // directly instead of through Progress.bind. Same bar, same
      // meaning — 47 seconds is exactly long enough to want a position
      // rather than a spinner.
      if (window.Progress) window.Progress.set(d.done, d.total);
      setStatus(`↻ Rebuilding — ${d.done || 0}/${d.total || "?"} folders · `
                + `${(d.files || 0).toLocaleString()} files`, "");
      return;
    }
    clearInterval(poll);
    btn.disabled = false;
    const res = (p && p.result) || {};
    if (window.Progress) { if (res.ok) window.Progress.done(); else window.Progress.fail(); }
    setStatus(res.ok
      ? `✓ Indexed ${(res.files || 0).toLocaleString()} files in ${res.seconds}s`
      : `Rebuild failed: ${res.error || "?"}`, res.ok ? "ok" : "error");
    loadAreas();
    run();
  }, 700);
}

window.addEventListener("DOMContentLoaded", () => {
  $("#q").addEventListener("input", () => {
    clearTimeout(state.timer);
    state.timer = setTimeout(run, 160);
  });
  $("#ext").addEventListener("change", run);
  $("#rebuild").addEventListener("click", rebuild);
  loadAreas();
});
