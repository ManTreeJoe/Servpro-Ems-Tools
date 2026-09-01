"use strict";
const state = { notes: [], selected: null, search: "" };
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

window.addEventListener("pywebviewready", async () => {
  await PanelState.init("job_notes");
  state.search = PanelState.get("search", "");
  const _sb = $("#search-box"); if (_sb) _sb.value = state.search;

  $("#refresh-btn").addEventListener("click", load);
  $("#compose-btn").addEventListener("click", () => openComposeModal());
  $("#open-folder-btn").addEventListener("click",
    () => pywebview.api.open_notes_folder());
  $("#search-box").addEventListener("input", (e) => {
    state.search = e.target.value;
    PanelState.set({ search: state.search });
    renderList();
  });
  document.addEventListener("keydown", (e) => {
    // Shared guard: typing anywhere, or any dialog open, means these
    // shortcuts are not for us. TEXTAREA used to fall straight through.
    if (window.shouldIgnoreKey
          ? window.shouldIgnoreKey(e)
          : (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    if (e.key === "/") { $("#search-box").focus(); e.preventDefault(); return; }
    if (e.key === "ArrowDown" || e.key === "j") stepSel(+1);
    if (e.key === "ArrowUp"   || e.key === "k") stepSel(-1);
  });
  await load();
});

async function load() {
  state.notes = await pywebview.api.list_notes();
  if (state.notes.length && !state.selected) {
    state.selected = state.notes[0];
  }
  renderList();
  renderDetail();
}

function filtered() {
  const q = state.search.trim().toLowerCase();
  if (!q) return state.notes;
  return state.notes.filter((n) =>
    n.client.toLowerCase().includes(q) || n.year.toLowerCase().includes(q));
}

function renderList() {
  const rows = filtered();
  $("#list-count").textContent = `${rows.length} / ${state.notes.length} notes`;
  $("#status-counts").textContent = `${rows.length} shown · ${state.notes.length} total`;
  $("#list-body").innerHTML = rows.map((n) => {
    const isActive = state.selected
      && n.client === state.selected.client && n.year === state.selected.year;
    return `<div class="list-row ${isActive ? "active" : ""}"
                  data-year="${esc(n.year)}" data-client="${esc(n.client)}">
              <div class="list-name">${esc(n.client)}</div>
              <div class="list-meta">${esc(n.year)} · ${esc(n.mtime)}</div>
            </div>`;
  }).join("");
  $$(".list-row").forEach((r) => r.addEventListener("click", async () => {
    state.selected = { year: r.dataset.year, client: r.dataset.client };
    renderList();
    await renderDetail();
  }));
}

async function renderDetail() {
  const empty = $("#detail-empty");
  const view = $("#detail");
  if (!state.selected) { empty.classList.remove("hidden"); view.classList.add("hidden"); return; }
  empty.classList.add("hidden"); view.classList.remove("hidden");
  const res = await pywebview.api.load_note(state.selected.year, state.selected.client);
  const text = res?.ok ? (res.text || "(empty note)") : `Error loading note: ${res?.error || "unknown"}`;
  const note = state.notes.find((n) =>
    n.client === state.selected.client && n.year === state.selected.year);
  // Parse timeline + expected files for the side panels. Backend
  // returns the canonical stage order + the union of expected files;
  // we render them as compact cards next to the note text. Mirrors
  // the Tk panel's left-rail timeline + expected-files card.
  let stagesDetected = [], allStages = [], expected = [];
  try {
    [stagesDetected, allStages, expected] = await Promise.all([
      pywebview.api.parse_timeline(text),
      pywebview.api.all_stages(),
      pywebview.api.expected_files_for(text),
    ]);
  } catch (_) {}
  const stagesSet = new Set(stagesDetected || []);
  const timelineHtml = (allStages || []).map((s) => `
    <li class="tl-stage ${stagesSet.has(s) ? "hit" : ""}">
      <span class="tl-dot"></span>${esc(s)}
    </li>`).join("");
  const expectedHtml = (expected || []).length
    ? `<ul class="ef-list">${expected.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
    : `<div class="muted" style="font-size:11px;">No expected files yet — paste Trello text to detect stages.</div>`;

  view.innerHTML = `
    <header class="detail-head">
      <div class="detail-client">${esc(state.selected.client)}</div>
      <div class="detail-meta">${esc(state.selected.year)} · ${esc(note?.mtime || "")}</div>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-primary" id="edit-btn">✏ Edit</button>
        <button class="btn" id="compose-btn-detail" title="Add a job comment">💬 Add comment</button>
        <details class="note-more"><summary class="btn">More ▾</summary><div>
          <button class="btn" id="post-btn" title="Post the entire note as a temporary Trello comment">💬 Post entire note</button>
          <button class="btn" id="trello-btn"><img src="../web_shared/trello.png" alt="" style="width:13px;height:13px;vertical-align:middle;margin-right:4px;" />Open Trello</button>
          <button class="btn" id="pin-btn" title="Change the temporary Trello card link">📌 Change Trello link…</button>
          <button class="btn" id="refresh-trello-btn" title="Re-pull live activity from Trello">↻ Refresh Trello</button>
          <button class="btn" id="aliases-btn">🏷 Job aliases…</button>
          <button class="btn" id="notepad-btn">📝 Open in Notepad</button>
        </div></details>
      </div>
      <div style="margin-top:8px;display:flex;gap:6px;align-items:center;">
        <input id="find-box" class="search" type="search"
               placeholder="🔎 Find in note…" style="width:280px;font-size:12px;" />
        <span id="find-count" class="muted" style="font-size:11px;"></span>
      </div>
    </header>
    <div id="jn-trello-tabs" style="display:none;margin-top:8px;flex-wrap:wrap;gap:4px;align-items:center;"></div>
    <div class="detail-body" style="display:grid;grid-template-columns:1fr 240px;gap:14px;align-items:start;">
      <pre class="note-text" id="note-text">${renderMarkdown(text)}</pre>
      <aside class="side-rail">
        <div class="rail-card">
          <div class="rail-title">📈 Timeline</div>
          <ul class="tl-list">${timelineHtml}</ul>
        </div>
        <div class="rail-card" style="margin-top:10px;">
          <div class="rail-title">📋 Expected files</div>
          ${expectedHtml}
        </div>
      </aside>
    </div>`;
  $("#edit-btn").addEventListener("click",
    () => openComposeModal(state.selected.client, state.selected.year, text));
  $("#aliases-btn").addEventListener("click",
    () => openAliasesModal(state.selected.client));
  // Find-in-note — live highlight as the user types
  const noteEl = document.getElementById("note-text");
  const findBox = document.getElementById("find-box");
  const findCount = document.getElementById("find-count");
  const rawText = text;
  let findTimer = null;
  findBox.addEventListener("input", () => {
    if (findTimer) clearTimeout(findTimer);
    findTimer = setTimeout(() => {
      const q = findBox.value.trim();
      if (!q) {
        // No search — restore the formatted markdown rendering
        noteEl.innerHTML = renderMarkdown(rawText);
        findCount.textContent = "";
        return;
      }
      // Search active: render as plain-with-highlights so marks
      // don't fight with the markdown HTML structure.
      const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      let count = 0;
      const html = esc(rawText).replace(re, (m) => { count++; return `<mark>${m}</mark>`; });
      noteEl.innerHTML = html;
      findCount.textContent = count
        ? `${count} match${count !== 1 ? "es" : ""}`
        : "No matches";
    }, 120);
  });
  $("#post-btn").addEventListener("click", async () => {
    const res = await pywebview.api.post_note_to_trello(state.selected.client, text);
    setStatus(res?.ok ? "💬 Posted to Trello" : `Post failed: ${res?.error || "?"}`,
              res?.ok ? "ok" : "error");
  });
  // 💬 New comment — opens compose modal (mirrors Tk job_notes_gui.py:2014
  // _open_compose_dialog). Posts a one-off comment to the pinned card,
  // separate from "Post note" which posts the entire note body.
  $("#compose-btn-detail").addEventListener("click",
    () => openTrelloComposeModal(state.selected.client));
  $("#pin-btn").addEventListener("click",
    () => openTrelloPinModal(state.selected.client));
  $("#refresh-trello-btn").addEventListener("click", () => refreshTrelloFeed(true));
  // Kick off the 60s auto-refresh tick (mirrors Tk job_notes_gui.py:2155
  // _refresh_from_trello — Tk's view re-fetches on every panel refresh;
  // the web equivalent ticks while the panel is visible). The
  // interval is panel-wide so changing the active note resets it.
  startTrelloAutoRefresh();
  $("#trello-btn").addEventListener("click",
    () => pywebview.api.open_trello_for(state.selected.client));
  $("#notepad-btn").addEventListener("click",
    () => pywebview.api.open_in_notepad(state.selected.year, state.selected.client));
  // Trello hover popover on the detail-head client name — uses the
  // shared web_shared/trello_hover.js helper. Resolves the pin async
  // via persistence; no popover when nothing pinned.
  const trelloBtn = document.getElementById("trello-btn");
  if (trelloBtn && window.attachTrelloHover) {
    pywebview.api.get_pinned_card_for_item?.(state.selected.client)
      .then((p) => {
        if (p?.card_id) window.attachTrelloHover(trelloBtn, p.card_id);
      }).catch(() => {});
  }
  // Render the multi-card tab strip (mirrors Tk _rebuild_trello_tabs).
  // Hidden when 0–1 cards pinned. Clicking a tab swaps which card's
  // activity feed shows + which card the compose modal posts to.
  renderTrelloTabs();
}

async function renderTrelloTabs() {
  const bar = $("#jn-trello-tabs");
  if (!bar || !state.selected) return;
  const cards = await pywebview.api.list_pinned_cards_meta(state.selected.client) || [];
  if (cards.length < 2) { bar.style.display = "none"; bar.innerHTML = ""; return; }
  // Default active to first card if not set or stale
  if (!state._activeCardId || !cards.find((c) => c.card_id === state._activeCardId)) {
    state._activeCardId = cards[0].card_id;
  }
  bar.innerHTML = `
    <span class="muted" style="font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--green);">Trello:</span>
    ${cards.map((c) => {
      const active = c.card_id === state._activeCardId;
      const label = [c.board || "?", c.lane].filter(Boolean).join("  ·  ");
      return `<button class="jn-trello-tab" data-cid="${esc(c.card_id)}"
                 title="${esc(c.name)}${c.archived ? " (archived)" : ""}"
                 style="font:inherit;font-size:11px;font-weight:${active ? "700" : "500"};
                        padding:3px 10px;border-radius:4px;cursor:pointer;
                        background:${active ? "var(--green)" : "var(--surface)"};
                        color:${active ? "#FFF" : "var(--text)"};
                        border:1px solid ${active ? "var(--green)" : "var(--border)"};">
        ${esc(label)}${c.archived ? " 📦" : ""}
      </button>`;
    }).join("")}`;
  bar.style.display = "flex";
  bar.querySelectorAll(".jn-trello-tab").forEach((b) =>
    b.addEventListener("click", () => {
      state._activeCardId = b.dataset.cid;
      renderTrelloTabs();         // re-render so the active style updates
      refreshTrelloFeed(false);   // pull this card's feed into the note view
    }));
  // First render also pulls the active card's feed so the note
  // body shows live data right away. setTimeout=0 so we don't fire
  // before the rest of the detail finishes painting.
  setTimeout(() => refreshTrelloFeed(false), 0);
}

let _stTimer = null;
function setStatus(msg, kind = "") {
  // Job notes panel doesn't have a status bar — toast via floating div
  const el = document.createElement("div");
  el.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:200;padding:10px 16px;background:var(--surface);border:1px solid " +
    (kind === "ok" ? "var(--green)" : kind === "error" ? "var(--red)" : "var(--border)") +
    ";border-radius:6px;font-size:13px;color:var(--text);";
  el.textContent = msg;
  document.body.appendChild(el);
  if (_stTimer) clearTimeout(_stTimer);
  _stTimer = setTimeout(() => el.remove(), 3000);
}

// ── Compose / edit note modal (P2) ──────────────────────────────
function openComposeModal(prefillClient = "", prefillYear = "", prefillText = "") {
  const yearNow = String(new Date().getFullYear());
  const w = document.createElement("div");
  w.id = "jn-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(720px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">✏ ${prefillClient ? "Edit" : "New"} job note</div>
      </header>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;">
        <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px;">
          <label style="display:flex;flex-direction:column;gap:4px;">
            <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">Client *</span>
            <input id="jn-client" class="search" type="text" value="${esc(prefillClient)}" />
          </label>
          <label style="display:flex;flex-direction:column;gap:4px;">
            <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">Year</span>
            <input id="jn-year" class="search" type="text" value="${esc(prefillYear || yearNow)}" />
          </label>
        </div>
        <label style="display:flex;flex-direction:column;gap:4px;">
          <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);">Note text (Markdown OK)</span>
          <textarea id="jn-text" rows="14" style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-family:'Cascadia Mono','Consolas',monospace;font-size:13px;outline:none;resize:vertical;">${esc(prefillText)}</textarea>
        </label>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="jn-cancel">Cancel</button>
        <button class="btn" id="jn-clean" title="Clean a pasted Trello comments dump (•/Reply lines, run-together headers)">✂ Clean Trello paste</button>
        <button class="btn" id="jn-post">💬 Save + post to Trello</button>
        <button class="btn btn-primary" id="jn-save">💾 Save</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  $("#jn-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  async function saveOnly() {
    const c = $("#jn-client").value.trim();
    const y = $("#jn-year").value.trim() || yearNow;
    const t = $("#jn-text").value;
    if (!c) return null;
    const res = await pywebview.api.save_note(y, c, t);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return null; }
    return { client: c, year: y, text: t };
  }
  $("#jn-clean").addEventListener("click", async () => {
    const ta = $("#jn-text");
    const raw = ta.value;
    if (!raw.trim()) { setStatus("Nothing to clean", "warn"); return; }
    const res = await pywebview.api.clean_trello_paste(raw);
    if (res?.ok) {
      ta.value = res.text;
      setStatus("✂ Cleaned Trello paste — review then save", "ok");
    } else {
      setStatus(`Clean failed: ${res?.error || "?"}`, "error");
    }
  });
  $("#jn-save").addEventListener("click", async () => {
    const r = await saveOnly();
    if (r) { close(); setStatus("💾 Note saved", "ok"); await load(); }
  });
  $("#jn-post").addEventListener("click", async () => {
    const r = await saveOnly();
    if (!r) return;
    const pr = await pywebview.api.post_note_to_trello(r.client, r.text);
    close();
    setStatus(pr?.ok ? "💾 Saved + posted to Trello" : `Saved · ${pr?.error || "Trello failed"}`,
              pr?.ok ? "ok" : "warn");
    await load();
  });
  $("#jn-client").focus();
}

function stepSel(delta) {
  const rows = filtered();
  if (!rows.length) return;
  const ix = rows.findIndex((n) =>
    state.selected && n.client === state.selected.client && n.year === state.selected.year);
  const next = Math.max(0, Math.min(rows.length - 1, ix + delta));
  state.selected = rows[next];
  renderList();
  renderDetail();
  document.querySelector(".list-row.active")?.scrollIntoView({ block: "nearest" });
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// ── Lightweight markdown renderer (Tk parity) ──────────────────
// Mirrors the in-place markers job_notes_gui hides: headers (#/##/###),
// **bold**, *italic*, `code`, "- bullets". HTML-escapes first so the
// note text can't inject markup, then re-runs the patterns on the
// escaped output. Trello comment headers (`Author · Date`) get the
// same green-band styling the Tk panel uses.
const _MD_HEADER_RE  = /^(#{1,3})\s+(.+)$/gm;
const _MD_BOLD_RE    = /\*\*([^*\n]+?)\*\*/g;
const _MD_ITALIC_RE  = /(?<![*\w])\*([^*\n]+?)\*(?!\w)/g;
const _MD_CODE_RE    = /`([^`\n]+?)`/g;
const _MD_BULLET_RE  = /^([-*])(\s+)(.+)$/gm;
const _TRELLO_HEADER_RE = /^([A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*)*\s*·\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s*[AP]M(?:\s+\(edited\))?)\s*$/gm;
function renderMarkdown(raw) {
  let s = esc(raw);
  // Trello "Author · Date" headers — green banded
  s = s.replace(_TRELLO_HEADER_RE,
    '<span class="md-trello-header">$1</span>');
  // Headers — # / ## / ### with size + weight by depth
  s = s.replace(_MD_HEADER_RE, (_m, hashes, text) => {
    const lvl = hashes.length;
    return `<span class="md-h${lvl}">${text}</span>`;
  });
  // Bullets — leading "- " or "* "
  s = s.replace(_MD_BULLET_RE,
    (_m, _bullet, _ws, body) => `<span class="md-bullet">• ${body}</span>`);
  // Inline: bold then italic then code (order matters — bold first
  // so *foo* inside **foo** isn't double-rendered)
  s = s.replace(_MD_BOLD_RE,   '<span class="md-bold">$1</span>');
  s = s.replace(_MD_ITALIC_RE, '<span class="md-italic">$1</span>');
  s = s.replace(_MD_CODE_RE,   '<span class="md-code">$1</span>');
  return s;
}

// ── Aliases dialog (Tk parity) ─────────────────────────────────
// Alternate names every note lookup will also try. Useful for
// commercial jobs filed under the business name vs the contact's
// personal name, or for nickname cases ("Bob" / "Robert").
async function openAliasesModal(client) {
  if (!client) return;
  const current = await pywebview.api.get_aliases(client) || [];
  const w = document.createElement("div");
  w.id = "jn-aliases-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(520px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">🏷 Search aliases — ${esc(client)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">One per line. Note + audit lookups will also try these names.</div>
      </header>
      <div style="padding:18px 20px;">
        <textarea id="al-text" rows="10"
                  style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;outline:none;resize:vertical;">${esc(current.join("\n"))}</textarea>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="al-cancel">Cancel</button>
        <button class="btn btn-primary" id="al-save">💾 Save</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  $("#al-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  $("#al-save").addEventListener("click", async () => {
    const lines = $("#al-text").value.split("\n").map((s) => s.trim()).filter(Boolean);
    const res = await pywebview.api.set_aliases(client, lines);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    close();
    setStatus(`🏷 Saved ${lines.length} alias${lines.length !== 1 ? "es" : ""}`, "ok");
  });
}

// ── Trello comment compose modal ────────────────────────────────
// Mirrors Tk job_notes_gui.py:2014 _open_compose_dialog. Posts a
// one-off comment to the active Trello card (uses the multi-card
// active selection if present, falls back to the pinned card).
// Ctrl+Enter posts.
async function openTrelloComposeModal(client) {
  // Resolve the active card_id. state._activeCardId is set by the
  // multi-card tab strip (when present); falls back to the pinned
  // card via the backend.
  let cardId = state._activeCardId || "";
  if (!cardId) {
    const p = await pywebview.api.get_pinned_card_for_item?.(client);
    cardId = p?.card_id || "";
  }
  if (!cardId) {
    setStatus(`${client} has no pinned Trello card — pin one first`, "warn");
    return;
  }
  const w = document.createElement("div");
  w.id = "jn-compose-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:14px 20px;background:var(--green,#58B77D);color:#101713;border-bottom:1px solid var(--border);">
        <div style="font-size:14px;font-weight:700;">Add comment to ${esc(client)}</div>
        <div style="font-size:11px;opacity:.85;margin-top:4px;">
          Posting to Trello card ${esc(cardId)} · Ctrl+Enter to post
        </div>
      </header>
      <div style="padding:14px 20px;">
        <textarea id="jn-cmp-body" rows="8" placeholder="Type your comment…"
                  style="width:100%;background:var(--surface-2);color:var(--text);
                         border:1px solid var(--border);border-radius:6px;
                         padding:10px 12px;font:inherit;font-size:13px;
                         resize:vertical;"></textarea>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <span style="flex:1;color:var(--text-muted);font-size:11px;align-self:center;">Ctrl+Enter to post</span>
        <button class="btn" id="jn-cmp-cancel">Cancel</button>
        <button class="btn btn-primary" id="jn-cmp-post">💬 Post comment</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  $("#jn-cmp-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });

  const ta = $("#jn-cmp-body");
  const postBtn = $("#jn-cmp-post");
  async function doPost() {
    const text = ta.value.trim();
    if (!text) { ta.focus(); return; }
    postBtn.disabled = true; postBtn.textContent = "Posting…";
    const res = await pywebview.api.post_trello_comment(cardId, text);
    if (!res?.ok) {
      setStatus(`Post failed: ${res?.error || "?"}`, "error");
      postBtn.disabled = false; postBtn.textContent = "💬 Post comment";
      return;
    }
    close();
    setStatus("💬 Comment posted to Trello", "ok");
    // Refresh the note so the new comment shows up (auto-refresh
    // task #6 will make this implicit; for now do it on demand).
    try {
      if (typeof load === "function") await load();
      else if (state.selected) renderDetail();
    } catch (_) {}
  }
  ta.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      doPost();
    }
    if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  postBtn.addEventListener("click", doPost);
  ta.focus();
}

// ── Pin Trello card modal ──────────────────────────────────────
// Mirrors Tk job_notes_gui.py:2130 _pin_to_trello → opens the
// shared open_trello_pin_dialog. Lists currently-pinned cards (so
// multi-card jobs can manage all pins) + lets user search Trello
// + add a card.
async function openTrelloPinModal(client) {
  const pinned = await pywebview.api.get_pinned_card_ids(client) || [];
  const w = document.createElement("div");
  w.id = "jn-pin-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(620px,92vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:14px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:14px;font-weight:700;">📌 Pin Trello cards for ${esc(client)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
          Search by name + click a result to pin. Multiple cards are supported (job with siblings, dispute card, etc.).
        </div>
      </header>
      <div style="padding:14px 20px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;">
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">Currently pinned (${pinned.length})</div>
          <div id="jn-pinned-list" style="display:flex;flex-direction:column;gap:4px;">
            ${pinned.length
              ? pinned.map((cid) => `
                <div data-cid="${esc(cid)}" style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;">
                  <code style="font-size:11px;">${esc(cid)}</code>
                  <button class="btn jn-unpin" style="font-size:10px;padding:2px 8px;">✕ Unpin</button>
                </div>`).join("")
              : `<div class="muted" style="font-size:12px;">None yet — search below.</div>`}
          </div>
        </div>
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">Search Trello cards</div>
          <input id="jn-pin-q" class="search" type="search" placeholder="Type 2+ characters…" style="width:100%;" value="${esc(client)}" />
          <div id="jn-pin-hits" style="margin-top:8px;max-height:240px;overflow-y:auto;display:flex;flex-direction:column;gap:4px;"></div>
        </div>
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">Or paste a Trello URL</div>
          <div style="display:flex;gap:6px;">
            <input id="jn-pin-url" class="search" type="text" placeholder="https://trello.com/c/..." style="flex:1;" />
            <button class="btn btn-primary" id="jn-pin-url-add">Add</button>
          </div>
        </div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="jn-pin-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  $("#jn-pin-close").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });

  // Live state — manipulate the list in-place so multiple add/unpin
  // operations chain without re-fetching.
  let current = pinned.slice();

  function reRenderPinned() {
    const box = document.getElementById("jn-pinned-list");
    if (!current.length) {
      box.innerHTML = `<div class="muted" style="font-size:12px;">None yet — search below.</div>`;
      return;
    }
    box.innerHTML = current.map((cid) => `
      <div data-cid="${esc(cid)}" style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;">
        <code style="font-size:11px;">${esc(cid)}</code>
        <button class="btn jn-unpin" style="font-size:10px;padding:2px 8px;">✕ Unpin</button>
      </div>`).join("");
    box.querySelectorAll(".jn-unpin").forEach((b) =>
      b.addEventListener("click", async (e) => {
        const cid = e.target.closest("[data-cid]").dataset.cid;
        const next = current.filter((x) => x !== cid);
        const res = await pywebview.api.set_pinned_card_ids(client, next);
        if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
        current = res.card_ids || next;
        reRenderPinned();
        setStatus(`✕ Unpinned ${cid}`, "ok");
      }));
  }
  reRenderPinned();

  async function addCard(cardId) {
    if (!cardId || current.includes(cardId)) return;
    const next = [...current, cardId];
    const res = await pywebview.api.set_pinned_card_ids(client, next);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    current = res.card_ids || next;
    reRenderPinned();
    setStatus(`📌 Pinned ${cardId}`, "ok");
    // Refresh detail so multi-card tabs (task #4) re-render.
    if (typeof load === "function") await load();
    else if (state.selected) renderDetail();
  }

  let qTimer = null;
  const qIn = $("#jn-pin-q");
  qIn.addEventListener("input", () => {
    if (qTimer) clearTimeout(qTimer);
    qTimer = setTimeout(async () => {
      const q = qIn.value.trim();
      const hitsBox = document.getElementById("jn-pin-hits");
      if (q.length < 2) { hitsBox.innerHTML = ""; return; }
      const hits = await pywebview.api.search_trello_cards(q) || [];
      hitsBox.innerHTML = hits.length
        ? hits.map((h) => `
          <div class="jn-hit" data-cid="${esc(h.card_id)}"
               style="padding:8px 10px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;">
            <div style="font-weight:600;font-size:13px;">${esc(h.name)}</div>
            <div class="muted" style="font-size:11px;">${esc(h.lane || "")} · ${esc(h.board || "")}</div>
          </div>`).join("")
        : `<div class="muted" style="font-size:12px;">No matches.</div>`;
      hitsBox.querySelectorAll(".jn-hit").forEach((el) =>
        el.addEventListener("click", () => addCard(el.dataset.cid)));
    }, 250);
  });
  // Auto-search the client name on open
  qIn.dispatchEvent(new Event("input"));

  $("#jn-pin-url-add").addEventListener("click", () => {
    const url = $("#jn-pin-url").value.trim();
    const m = url.match(/trello\.com\/c\/([A-Za-z0-9]+)/);
    if (!m) { setStatus("Not a Trello card URL", "warn"); return; }
    addCard(m[1]);
    $("#jn-pin-url").value = "";
  });
}

// ── Auto-refresh Trello stream (mirrors Tk _refresh_from_trello) ──
// Re-pulls the active card's formatted activity feed every 60s
// while the Job Notes panel is visible + on demand from the ↻
// Refresh Trello button. Renders into the note view so the user
// sees fresh comments without manually re-pasting / reloading.
let _trelloAutoTimer = null;
async function refreshTrelloFeed(showToast = false) {
  if (!state.selected) return;
  // Find the active card_id — prefer multi-card active tab, fall
  // back to pinned card.
  let cardId = state._activeCardId || "";
  if (!cardId) {
    const p = await pywebview.api.get_pinned_card_for_item?.(state.selected.client);
    cardId = p?.card_id || "";
  }
  if (!cardId) {
    if (showToast) setStatus("No pinned Trello card", "warn");
    return;
  }
  const btn = document.getElementById("refresh-trello-btn");
  if (btn) { btn.disabled = true; btn.textContent = "↻ Refreshing…"; }
  const res = await pywebview.api.refresh_trello_feed(cardId);
  if (btn) { btn.disabled = false; btn.textContent = "↻ Refresh Trello"; }
  if (!res?.ok) {
    if (showToast) setStatus(`Refresh failed: ${res?.error || "?"}`, "warn");
    return;
  }
  // Replace the note-text rendering with the live Trello feed so
  // the user sees the freshest stream. Stash the original markdown
  // on the element so the find-in-note search still works.
  const noteEl = document.getElementById("note-text");
  if (noteEl && res.text) {
    state._trelloFeedText = res.text;
    noteEl.innerHTML = renderMarkdown(res.text);
  }
  if (showToast) {
    const when = res.last_activity ? res.last_activity.split("T")[0] : "now";
    setStatus(`↻ Trello refreshed · last activity ${when}${res.archived ? " · ARCHIVED" : ""}`, "ok");
  }
}

function startTrelloAutoRefresh() {
  if (_trelloAutoTimer) clearInterval(_trelloAutoTimer);
  _trelloAutoTimer = setInterval(() => {
    // Only fire when the panel is visible and a note is selected.
    if (document.visibilityState !== "visible") return;
    if (!state.selected) return;
    refreshTrelloFeed(false);
  }, 60_000);
}
