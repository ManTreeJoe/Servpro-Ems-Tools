/* APA Monitor — Pywebview spike frontend.
 *
 * Kanban-style read-only viewer for the daily APA doc. Loads the
 * parsed sections from Python, renders one column per section, lets
 * the user step through past working days and filter the display.
 *
 * Phase 1: READ-ONLY. No item editing, no save, no drag-drop yet.
 * Phase 2 will add those + Teams messaging buttons per item.
 */
"use strict";

const state = {
  doc:          null,    // current payload from Api.today_doc / doc_for_date
  nav_dates:    [],      // recent working days for the chip strip
  active_date:  null,    // ISO string
  search:       "",
  toggle:       "all",   // "all" / "estimator" / "builtin" / "nonempty"
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  $("#refresh-btn").addEventListener("click", () => loadDate(state.active_date));
  $("#create-doc-btn").addEventListener("click", createTodayDoc);
  $("#refresh-lanes-btn").addEventListener("click", refreshLanesFromTrello);
  attachApaTrelloSearch();
  attachFranchiseFilter();
  attachMoreMenu();
  $("#manage-sections-btn").addEventListener("click", openManageSectionsModal);
  $("#manage-franchises-btn").addEventListener("click", openManageFranchisesModal);
  $("#open-word-btn").addEventListener("click", openInWord);
  $("#reveal-btn").addEventListener("click", revealInExplorer);
  $("#clear-all-btn").addEventListener("click", clearAllItems);
  $("#prev-date").addEventListener("click", () => stepDate(-1));
  $("#next-date").addEventListener("click", () => stepDate(+1));
  $("#today-btn").addEventListener("click", () => loadToday());
  $("#search-box").addEventListener("input", onSearchInput);
  $$(".toggle-btn").forEach((b) =>
    b.addEventListener("click", () => setToggle(b.dataset.toggle))
  );
  $("#teams-all-btn").addEventListener("click", sendTeamsAll);
  $("#eod-btn").addEventListener("click", sendEodEmail);
  // Right-click EOD button → recipients dialog. Mirror of Tk's
  // apa_monitor_gui.py:2222 power-user shortcut: opens the contacts
  // modal directly to the EOD recipients section.
  $("#eod-btn").addEventListener("contextmenu", (e) => {
    e.preventDefault();
    openContactsModal();
    // After the modal renders, scroll the EOD textarea into view +
    // focus it so the user lands on the field they likely want to
    // edit. setTimeout because openContactsModal is async-built.
    setTimeout(() => {
      const ta = document.getElementById("cn-eod");
      if (ta) { ta.scrollIntoView({ block: "center" }); ta.focus(); }
    }, 50);
  });
  // Long-tooltip hint so users discover the right-click shortcut.
  $("#eod-btn").title = "Send the EOD email · Right-click to edit recipients";
  $("#bulk-paste-btn").addEventListener("click", openBulkPasteModal);
  $("#contacts-btn").addEventListener("click", openContactsModal);
  document.addEventListener("keydown", onKeyDown);

  await loadInitialData();
});

// ── Teams messaging ────────────────────────────────────────────
async function sendTeamsAll() {
  // Plan first WITHOUT opening anything, then walk the list one chat at
  // a time. The old version fired every chat at once ("spazzed through"
  // the messages); now the user confirms + verifies each one before it
  // opens and hits Send themselves. Mirrors the Tk _send_teams_to_all
  // confirm-between-each flow.
  const plan = await pywebview.api.teams_collect_targets();
  if (!plan?.ok) {
    setStatus(`Send-all failed: ${plan?.error || "?"}`, "error");
    return;
  }
  const targets = plan.targets || [];

  // Surface audit rejection/dispute items that couldn't be routed so they
  // don't silently drop out of the sweep.
  if ((plan.unresolved || []).length) {
    alert(
      "These rejection/dispute items will be skipped — set the Sub or add "
      + "an email for that estimator:\n\n• " + plan.unresolved.join("\n• "));
  }
  if ((plan.missing_email || []).length) {
    if (!confirm(
        `Skipping (no email saved): ${plan.missing_email.join(", ")}.\n\n`
        + `Continue with the ${targets.length} estimator(s) that have email?`))
      return;
  }
  if (!targets.length) {
    setStatus("Nothing to send — no estimators have outstanding jobs.", "warn");
    return;
  }

  let handled = 0;
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    const remaining = (i < targets.length - 1)
      ? `${targets.length - i - 1} more after this` : "last one";
    const action = await teamsComposeModal({
      title: `${t.first}  (${i + 1}/${targets.length})`,
      sub:   `${t.email} · ${remaining}`,
      message: t.message, email: t.email, loop: true,
    });
    if (action === "stop") break;
    if (action === "skip") continue;
    handled++;   // "next"
  }
  setStatus(`✉ Done — ${handled} of ${targets.length} handled`, "ok");
}

async function sendTeamsForEstimator(estimator) {
  const res = await pywebview.api.teams_per_estimator(estimator);
  if (res?.needs_email) { await promptForEmail(estimator); return; }
  if (!res?.ok) {
    setStatus(`Teams: ${res?.error || "no items / Teams not available"}`,
              res?.error === "no outstanding items" ? "warn" : "error");
    return;
  }
  await teamsComposeModal({
    title: estimator, sub: `${res.email} · ${res.count} item(s)`,
    message: res.message, email: res.email, loop: false,
  });
}

async function sendTeamsForItem(estimator, itemText, section) {
  const res = await pywebview.api.teams_per_item(estimator, itemText, section || "");
  if (res?.needs_email) { await promptForEmail(estimator); return; }
  if (!res?.ok) { setStatus(`Teams failed: ${res?.error || "?"}`, "error"); return; }
  await teamsComposeModal({
    title: estimator, sub: itemText, message: res.message,
    email: res.email, loop: false,
  });
}

// Editable Teams compose dialog. The msteams: deep link's `message=`
// param is unreliable in the current Teams client (the chat opens empty),
// so instead of trusting auto-fill we give the user the message in an
// editable box + a 📋 Copy button to paste it themselves, and a 🟣 Open
// Teams button. For Send-all (`loop:true`) the footer offers Skip / Stop /
// Next. Resolves to "next" | "skip" | "stop".
function teamsComposeModal({ title, sub, message, email, loop }) {
  return new Promise((resolve) => {
    const w = document.createElement("div");
    w.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
    const stopBtn = loop ? `<button class="btn" data-act="stop">Stop all</button>` : "";
    const skipBtn = loop ? `<button class="btn" data-act="skip">Skip</button>` : "";
    const doneLabel = loop ? "Next ▸" : "Done";
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(640px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">✉ ${esc(title)}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${esc(sub || "")}</div>
        </header>
        <div style="padding:14px 18px;display:flex;flex-direction:column;gap:8px;overflow-y:auto;">
          <textarea id="tc-text" spellcheck="false"
            style="width:100%;min-height:180px;resize:vertical;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;line-height:1.5;">${esc(message || "")}</textarea>
          <div style="font-size:11px;color:var(--text-muted);">Edit if needed → <b>📋 Copy</b>, then <b>🟣 Open Teams</b> and paste with <b>Ctrl+V</b>. (Teams won't auto-fill the message.)</div>
        </div>
        <footer style="padding:12px 18px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;">
          ${stopBtn}${skipBtn}
          <button class="btn" data-act="copy">📋 Copy</button>
          <button class="btn" data-act="open">🟣 Open Teams</button>
          <button class="btn btn-primary" data-act="done">${doneLabel}</button>
        </footer>
      </div>`;
    document.body.appendChild(w);
    const ta = w.querySelector("#tc-text");
    const fin = (v) => { w.remove(); resolve(v); };
    const copy = async () => {
      let ok = false;
      try {
        ok = window.emsCopyText ? await window.emsCopyText(ta.value)
           : await navigator.clipboard.writeText(ta.value).then(() => true);
      } catch (_) { ok = false; }
      setStatus(ok ? "📋 Copied — paste into Teams with Ctrl+V" : "Copy failed",
                ok ? "ok" : "error");
      return ok;
    };
    w.querySelector('[data-act="copy"]').addEventListener("click", copy);
    w.querySelector('[data-act="open"]').addEventListener("click", async () => {
      await copy();   // ensure clipboard is loaded before Teams steals focus
      const res = await pywebview.api.teams_open_chat(email, ta.value);
      if (!res?.ok) setStatus(`Could not open Teams: ${res?.error || "?"}`, "error");
      else setStatus("🟣 Teams opened — paste with Ctrl+V, then Send", "ok");
    });
    w.querySelector('[data-act="done"]').addEventListener("click", () => fin("next"));
    if (loop) {
      w.querySelector('[data-act="skip"]').addEventListener("click", () => fin("skip"));
      w.querySelector('[data-act="stop"]').addEventListener("click", () => fin("stop"));
    }
    w.addEventListener("click", (e) => { if (e.target === w) fin(loop ? "skip" : "next"); });
    setTimeout(() => ta.focus(), 30);
  });
}

async function promptForEmail(estimator) {
  const email = prompt(`Enter Teams email for ${estimator}:`, "");
  if (!email) return;
  const res = await pywebview.api.set_estimator_email(estimator, email.trim());
  if (res?.ok) setStatus(`Saved email for ${estimator}`, "ok");
}

// ── Clear all items ────────────────────────────────────────────
async function clearAllItems() {
  const n = (state.doc?.sections || [])
    .reduce((s, sec) => s + (sec.items || []).length, 0);
  if (!n) { setStatus("Already empty — nothing to clear.", "warn"); return; }
  if (!confirm(
      `Clear ALL ${n} item(s) from every section of this APA doc?\n\n`
      + `The section headers / categories stay — only the jobs are removed. `
      + `This saves to the .docx.`))
    return;
  const res = await pywebview.api.clear_all_items(state.active_date || "");
  if (!res?.ok) { setStatus(`Clear failed: ${res?.error || "?"}`, "error"); return; }
  state.doc = res.doc;
  renderAll();
  setStatus(`🧹 Cleared ${n} item(s)`, "ok");
}

// ── EOD email ──────────────────────────────────────────────────
async function sendEodEmail() {
  // Pass the in-view sections + date so the backend builds the
  // email from what the user is currently looking at — matches Tk's
  // `self.sections` semantics. Works even before today's APA doc
  // has been saved to disk.
  const sectionsPayload = (state.doc?.sections || []).map((s) => ({
    name:  s.name,
    items: (s.items || []).map((it) => ({
      text: it.text, highlighted: !!it.highlighted,
    })),
  }));
  const dateIso = state.doc?.date_iso || "";
  const res = await pywebview.api.send_eod_email(dateIso, sectionsPayload);
  if (res?.needs_recipients) {
    const list = prompt(
      "EOD email has no recipients yet. Enter comma-separated emails:", "");
    if (!list) return;
    const arr = list.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
    await pywebview.api.set_eod_recipients(arr);
    setStatus(`Saved ${arr.length} EOD recipients — click again to send`, "ok");
    return;
  }
  if (!res?.ok) {
    setStatus(`EOD failed: ${res?.error || "?"}`, "error");
    return;
  }
  // Copy body to clipboard as fallback (long emails can hit URL caps)
  try { await navigator.clipboard.writeText(res.body || ""); } catch (_) {}
  pywebview.api.open_url(res.url);
  setStatus(`📧 EOD email opened in Outlook web · body also copied to clipboard`, "ok");
}

async function loadInitialData() {
  setStatus("Loading APA doc…");
  try {
    state.nav_dates = await pywebview.api.nav_dates();
    await loadToday();
  } catch (ex) {
    setStatus(`Failed to load: ${ex}`, "error");
  }
}

async function loadToday() {
  setStatus("Loading…");
  state.doc = await pywebview.api.today_doc();
  state.active_date = state.doc.date_iso;
  renderAll();
  setStatus("");
}

async function loadDate(iso) {
  if (!iso) return;
  setStatus("Loading…");
  state.doc = await pywebview.api.doc_for_date(iso);
  state.active_date = state.doc.date_iso;
  renderAll();
  setStatus("");
}

function stepDate(delta) {
  // Walk the nav_dates list by `delta` positions. The list is
  // newest-first, so delta=-1 = older, delta=+1 = newer.
  const ix = state.nav_dates.findIndex((d) => d.iso === state.active_date);
  if (ix === -1) return;
  const target_ix = ix - delta;   // newest-first → invert
  if (target_ix < 0 || target_ix >= state.nav_dates.length) return;
  loadDate(state.nav_dates[target_ix].iso);
}

// ── Render ───────────────────────────────────────────────────────
function renderAll() {
  renderDateNav();
  renderBoard();
}

function renderDateNav() {
  const doc = state.doc;
  if (!doc) return;
  $("#date-label").textContent = doc.date_label;
  $("#date-meta").textContent = doc.doc_exists
    ? `${doc.total_items} items · ${doc.sections.length} sections`
    : "No doc found for this date";
  // Show the topbar "Create APA" button whenever the active date
  // has no doc — including past days. Backend's create_doc is a no-op
  // on existing docs, so even retroactive clicks are safe.
  const createBtn = document.getElementById("create-doc-btn");
  const isToday = doc.date_iso === new Date().toISOString().slice(0, 10);
  if (createBtn) {
    createBtn.style.display = doc.doc_exists ? "none" : "";
    createBtn.textContent = isToday
      ? "＋ Create today's APA"
      : `＋ Create APA for ${doc.date_label || "this day"}`;
  }
  // 🔄 Refresh lanes — only for TODAY's existing doc (the new-day
  // cleanup: carried-forward items get re-routed to match each job's
  // current Trello lane). Hidden on past days + before the doc exists.
  const refreshLanesBtn = document.getElementById("refresh-lanes-btn");
  if (refreshLanesBtn) {
    refreshLanesBtn.style.display = (doc.doc_exists && isToday) ? "" : "none";
  }
  // Wire the empty-state "Create" button (rendered inside the
  // empty-state div, so it's only present when doc_exists is false).
  const emptyCreate = document.getElementById("empty-create-btn");
  if (emptyCreate && !emptyCreate._wired) {
    emptyCreate._wired = true;
    emptyCreate.addEventListener("click", createTodayDoc);
  }
  const strip = $("#date-strip");
  strip.innerHTML = state.nav_dates.map((d) => {
    const classes = ["date-chip"];
    if (d.iso === state.active_date) classes.push("active");
    if (!d.exists) classes.push("no-doc");
    if (d.is_today) classes.push("today");
    return `<button class="${classes.join(" ")}" data-iso="${d.iso}">${escapeHtml(d.short)}</button>`;
  }).join("");
  strip.querySelectorAll(".date-chip").forEach((c) =>
    c.addEventListener("click", () => loadDate(c.dataset.iso))
  );
}

// ── Name filter ────────────────────────────────────────────────────
// The filter used to be `it.text.includes(q)` on the STORED string,
// which is "Base-Sub-Status" — so "aaa" matched every AAA job, "pending"
// matched every pending one, and "brian brew" matched nothing at all
// because a substring cannot reorder words.
//
// Match the NAME (`it.base`, sub + status peeled server-side) token by
// token, each as a prefix, in any order. "brew" finds Brew, "brian brew"
// finds "Brew, Brian", "garcia var" finds Garcia-Vargas. EVERY token has
// to land, so "brian brew" doesn't drag in every other Brian.
function nameMatches(name, query) {
  const norm = (x) => String(x || "").toLowerCase()
    .replace(/[^a-z0-9]+/g, " ").trim();
  const qt = norm(query).split(" ").filter(Boolean);
  const nt = norm(name).split(" ").filter(Boolean);
  if (!qt.length || !nt.length) return false;
  return qt.every((t) => nt.some((n) => n.startsWith(t)));
}

// Falls back to the full stored text so a deliberate search for a status
// or sub ("extended", "Testing/Clearance") still works — it just no
// longer drowns out a name search.
function itemMatches(it, query) {
  return nameMatches(it.base || it.text, query)
      || String(it.text || "").toLowerCase().includes(query);
}

function renderBoard() {
  const board = $("#board");
  const doc = state.doc;
  const empty = $("#empty-state");

  if (!doc || !doc.doc_exists) {
    board.innerHTML = "";
    empty.classList.remove("hidden");
    $("#status-counts").textContent = "no doc";
    return;
  }
  empty.classList.add("hidden");

  const q = state.search.trim().toLowerCase();
  let shownItems = 0;
  let shownSections = 0;

  const html = doc.sections.map((s) => {
    const filtered = q ? s.items.filter((it) => itemMatches(it, q)) : s.items;
    if (q && filtered.length === 0) {
      return `<section class="section hidden-by-filter"></section>`;
    }

    // Toggle filtering
    if (state.toggle === "estimator" && !s.is_estimator) {
      return `<section class="section hidden-by-filter"></section>`;
    }
    if (state.toggle === "builtin" && !s.is_builtin) {
      return `<section class="section hidden-by-filter"></section>`;
    }
    if (state.toggle === "nonempty" && filtered.length === 0) {
      return `<section class="section hidden-by-filter"></section>`;
    }

    shownSections++;
    shownItems += filtered.length;

    const headClasses = ["section"];
    if (s.is_estimator) headClasses.push("is-estimator");
    if (s.is_builtin)   headClasses.push("is-builtin");
    if (filtered.length === 0) headClasses.push("is-empty");

    const itemsHtml = filtered.length
      ? filtered.map((it, i) => renderItem(it, s.name, i)).join("")
      : `<div class="item-empty">empty</div>`;

    const cntClasses = filtered.length ? "section-count has-items" : "section-count";

    // Estimator sections get a ✉ Teams button next to the count
    const teamsBtn = s.is_estimator
      ? `<button class="section-teams-btn" data-est="${escapeAttr(s.name)}" title="Send Teams to ${escapeAttr(s.name)} with all their items">✉</button>`
      : "";
    return `
      <section class="${headClasses.join(" ")}">
        <header class="section-head">
          <span class="section-name" title="${escapeAttr(s.name)}">${escapeHtml(s.name)}</span>
          ${teamsBtn}
          <span class="${cntClasses}">${filtered.length}</span>
        </header>
        <div class="section-body" data-section="${escapeAttr(s.name)}">
          ${itemsHtml}
          <button class="add-item-btn" data-section="${escapeAttr(s.name)}">+ Add item</button>
        </div>
      </section>
    `;
  }).join("");
  document.querySelectorAll(".section-teams-btn").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      sendTeamsForEstimator(b.dataset.est);
    }));

  board.innerHTML = html;
  // 🔁 Extended badge + 📝 Note button — bind BEFORE the item
  // click so stopPropagation prevents the edit popover.
  document.querySelectorAll(".ext-badge").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const r = await pywebview.api.bump_extended(b.dataset.extClient);
      if (r?.ok) {
        b.textContent = `🔁 ${r.count}×`;
        b.title = `${r.count}× extended`;
        setStatus(`🔁 Bumped extended count to ${r.count}×`, "ok");
      }
    }));
  document.querySelectorAll(".note-btn").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      openItemNoteModal(b.dataset.noteClient, b.dataset.noteSection, b);
    }));
  // Wire up click-to-edit on every item + add-item buttons + the
  // right-click context menu for inline status/sub/section changes
  // (no full popover needed for routine edits). Also attaches the
  // shared Trello hover popover when the row has a pinned card.
  document.querySelectorAll(".item[data-section]").forEach((el) => {
    el.addEventListener("click", () => openEditPopover(el));
    el.addEventListener("contextmenu", (e) => openApaItemCtxMenu(e, el));
    attachApaItemDrag(el);
    // Look up the pin async — fire-and-forget; the helper caches so
    // re-renders don't re-fetch. Anchored to the item element.
    pywebview.api.get_pinned_card_for_item(el.querySelector(".item-text")?.textContent || "")
      .then((p) => {
        if (p?.card_id && window.attachTrelloHover) {
          window.attachTrelloHover(el, p.card_id);
        }
      }).catch(() => {});
  });
  // Document-level click closer is wired ONCE on first render via
  // _apaCtxCloserBound — was being re-added every renderBoard()
  // call, stacking dozens of duplicate listeners over a session.
  if (!window._apaCtxCloserBound) {
    document.addEventListener("click", (e) => {
      // Don't close the menu when clicking inside it or its submenu.
      if (e.target.closest("#apa-ctx-menu") || e.target.closest(".apa-ctx-submenu")) return;
      document.getElementById("apa-ctx-menu")?.remove();
      document.querySelectorAll(".apa-ctx-submenu").forEach((s) => s.remove());
    });
    window._apaCtxCloserBound = true;
  }
  document.querySelectorAll(".section-body").forEach((body) =>
    attachApaSectionDrop(body));
  document.querySelectorAll(".add-item-btn").forEach((b) =>
    b.addEventListener("click", () => openAddPopover(b.dataset.section)));
  $("#status-counts").textContent =
    `${shownSections} sections · ${shownItems} items`
    + (q ? ` (filtered from ${doc.total_items})` : "");
}

function renderItem(item, sectionName, itemIndex) {
  const classes = ["item"];
  if (item.highlighted) classes.push("highlighted");
  if (item.extended)    classes.push("extended");
  // 🔁 extended counter — only renders when count > 0. Stops at
  // the right edge, click toggles the +1 (bumps a fresh extend).
  const extBadge = (item.ext_count || 0) > 0
    ? `<button class="ext-badge" title="${item.ext_count}× extended"
              data-ext-client="${escapeAttr(item.text)}">🔁 ${item.ext_count}×</button>`
    : "";
  // 📝 note button — yellow when there's note text, gray when not.
  // Click opens the note popover.
  const noteBtn = `<button class="note-btn ${item.has_note ? "has-text" : ""}"
                          data-note-client="${escapeAttr(item.text)}"
                          data-note-section="${escapeAttr(sectionName)}"
                          title="${item.has_note ? "Edit note" : "Add note"}">📝</button>`;
  return `
    <div class="${classes.join(" ")}"
         data-section="${escapeAttr(sectionName)}"
         data-index="${itemIndex}"
         title="Click to edit">
      <div class="item-text">${escapeHtml(item.text)}</div>
      <div class="item-extras">
        ${extBadge}${noteBtn}
      </div>
    </div>
  `;
}

// ── Editing ─────────────────────────────────────────────────────
// Click an item → opens a small popover where the user can edit
// the text, toggle highlight, toggle -extended suffix, or delete.
// + Add item at section bottom adds a new entry. All edits auto-
// save the .docx via apa.save_doc.

function openEditPopover(el) {
  const sectionName = el.dataset.section;
  const idx = parseInt(el.dataset.index, 10);
  const section = state.doc.sections.find((s) => s.name === sectionName);
  if (!section) return;
  const item = section.items[idx];
  if (!item) return;
  showItemPopover({
    title: "Edit item",
    section: sectionName,
    allowMove: true,
    text: item.text,
    highlighted: item.highlighted,
    extended: item.extended,
    onSave: async (newText, newHL, newExt, targetSection) => {
      let finalText = newText.trim();
      if (newExt && !finalText.toLowerCase().endsWith("-extended")) {
        finalText += "-extended";
      } else if (!newExt && finalText.toLowerCase().endsWith("-extended")) {
        finalText = finalText.slice(0, -"-extended".length);
      }
      const moved = targetSection && targetSection !== sectionName;
      if (moved) {
        // Splice out of old section + push into new section.
        section.items.splice(idx, 1);
        section.count = section.items.length;
        const dest = state.doc.sections.find((s) => s.name === targetSection);
        if (dest) {
          dest.items.push({ text: finalText, highlighted: newHL, extended: newExt });
          dest.count = dest.items.length;
        }
      } else {
        section.items[idx] = { text: finalText, highlighted: newHL, extended: newExt };
      }
      await saveDoc();
    },
    onDelete: async () => {
      section.items.splice(idx, 1);
      section.count = section.items.length;
      await saveDoc();
    },
  });
}

function openAddPopover(sectionName) {
  const section = state.doc.sections.find((s) => s.name === sectionName);
  if (!section) return;
  showItemPopover({
    title: "Add to " + sectionName,
    section: sectionName,
    text: "",
    highlighted: false,
    extended: false,
    onSave: async (newText, newHL, newExt) => {
      let finalText = newText.trim();
      if (!finalText) return;
      if (newExt && !finalText.toLowerCase().endsWith("-extended")) {
        finalText += "-extended";
      }
      section.items.push({ text: finalText, highlighted: newHL, extended: newExt });
      section.count = section.items.length;
      await saveDoc();
    },
  });
}

async function showItemPopover({ title, section, text, highlighted, extended, onSave, onDelete, allowMove }) {
  closeEditPopover();
  // Fetch the section-specific dropdown options + franchise roster
  // + the current franchise tag for this item, all in parallel.
  let opts = { statuses: [""], subs: null, highlight: [] };
  let franchiseList = [];
  let currentFranchise = "";
  try {
    const [o, fl, cf] = await Promise.all([
      pywebview.api.status_options(section),
      pywebview.api.get_franchise_list(),
      text ? pywebview.api.get_item_franchise(text) : Promise.resolve(""),
    ]);
    if (o) opts = o;
    if (Array.isArray(fl)) franchiseList = fl;
    if (typeof cf === "string") currentFranchise = cf;
  } catch (_) {}
  // Pre-parse current text into bare + status + sub so dropdowns
  // start on the right value when editing an existing row.
  let bareText = text;
  let curStatus = "";
  let curSub = "";
  try {
    // Strip status suffix: look for any "-{status}" at end
    for (const s of (opts.statuses || []).filter(Boolean)) {
      const suf = "-" + s;
      if (bareText.toLowerCase().endsWith(suf.toLowerCase())) {
        curStatus = s;
        bareText = bareText.slice(0, -suf.length);
        break;
      }
    }
    // Strip sub suffix
    if (opts.subs) {
      for (const s of opts.subs.filter(Boolean)) {
        const suf = "-" + s;
        if (bareText.toLowerCase().endsWith(suf.toLowerCase())) {
          curSub = s;
          bareText = bareText.slice(0, -suf.length);
          break;
        }
      }
    }
  } catch (_) {}

  const statusOpts = (opts.statuses || [""]).map(
    (s) => `<option value="${escapeAttr(s)}" ${s === curStatus ? "selected" : ""}>${escapeHtml(s || "(none)")}</option>`
  ).join("");
  const subOpts = opts.subs ? (opts.subs || [""]).map(
    (s) => `<option value="${escapeAttr(s)}" ${s === curSub ? "selected" : ""}>${escapeHtml(s || "(none)")}</option>`
  ).join("") : "";

  const wrap = document.createElement("div");
  wrap.id = "apa-popover";
  wrap.className = "apa-popover-backdrop";
  wrap.innerHTML = `
    <div class="apa-popover">
      <header class="apa-pop-head">
        <div>
          <div class="apa-pop-title">${escapeHtml(title)}</div>
          <div class="apa-pop-sub">${escapeHtml(section)}</div>
        </div>
        <button class="apa-pop-close" id="apa-pop-close">✕</button>
      </header>
      <div class="apa-pop-body">
        ${allowMove ? `
          <label class="apa-pop-lbl">📂 Section (move with dropdown)</label>
          <select id="apa-edit-section" class="apa-pop-select">
            ${(state.doc?.sections || []).map((s) =>
              `<option value="${escapeAttr(s.name)}" ${s.name === section ? "selected" : ""}>${escapeHtml(s.name)}</option>`).join("")}
          </select>
        ` : ""}
        <label class="apa-pop-lbl"${allowMove ? ` style="margin-top:10px;"` : ""}>Text</label>
        <textarea id="apa-edit-text" rows="3"
                  placeholder="Client name, claim#…">${escapeHtml(bareText)}</textarea>
        ${opts.subs ? `
          <label class="apa-pop-lbl" style="margin-top:10px;">Sub-category</label>
          <select id="apa-edit-sub" class="apa-pop-select">${subOpts}</select>
        ` : ""}
        <label class="apa-pop-lbl" style="margin-top:10px;">Status</label>
        <select id="apa-edit-status" class="apa-pop-select">${statusOpts}</select>
        <label class="apa-pop-lbl" style="margin-top:10px;">🏢 Franchise</label>
        <select id="apa-edit-franchise" class="apa-pop-select">
          <option value="" ${!currentFranchise ? "selected" : ""}>(none)</option>
          ${franchiseList.map((f) =>
            `<option value="${escapeAttr(f)}" ${f === currentFranchise ? "selected" : ""}>${escapeHtml(f)}</option>`).join("")}
        </select>
        <div class="apa-pop-hint">
          Stored per client — survives across days + status changes.
        </div>
        <div class="apa-pop-toggles" style="margin-top:14px;">
          <label class="apa-pop-toggle">
            <!-- Pre-check ONLY when the highlight was MANUALLY forced
                 (highlighted=true AND current status isn't in
                 HIGHLIGHT_STATUSES). When a pending row's yellow comes
                 from the auto-rule, leave this off so switching status
                 to "uploaded" drops the yellow instead of leaving it
                 forced-on. -->
            <input type="checkbox" id="apa-edit-hl"
                   ${(highlighted && !(opts.highlight || []).map((s) => s.toLowerCase()).includes((curStatus || "").toLowerCase())) ? "checked" : ""} />
            <span class="apa-pop-toggle-lbl">🟡 Force highlight</span>
          </label>
        </div>
        <div class="apa-pop-hint">
          Yellow auto-applies when status is ${escapeHtml((opts.highlight || []).join(" / ") || "—")}
        </div>
      </div>
      <footer class="apa-pop-foot">
        ${onDelete ? `<button class="apa-pop-btn apa-pop-del" id="apa-pop-del">🗑 Delete</button>` : ""}
        <div class="apa-pop-spacer"></div>
        <button class="apa-pop-btn" id="apa-pop-cancel">Cancel</button>
        <button class="apa-pop-btn apa-pop-save" id="apa-pop-save">💾 Save</button>
      </footer>
    </div>`;
  document.body.appendChild(wrap);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) closeEditPopover(); });
  const close = () => closeEditPopover();
  document.getElementById("apa-pop-close").addEventListener("click", close);
  document.getElementById("apa-pop-cancel").addEventListener("click", close);
  document.getElementById("apa-pop-save").addEventListener("click", async () => {
    const baseText = document.getElementById("apa-edit-text").value.trim();
    const status = document.getElementById("apa-edit-status").value;
    const subEl = document.getElementById("apa-edit-sub");
    const sub = subEl ? subEl.value : "";
    const franchise = document.getElementById("apa-edit-franchise")?.value || "";
    let finalText = baseText;
    if (sub)    finalText += "-" + sub;
    if (status) finalText += "-" + status;
    // Highlight auto-applies for status in opts.highlight; user can
    // also force it on via the checkbox.
    const forceHL = document.getElementById("apa-edit-hl").checked;
    const autoHL = (opts.highlight || []).map((s) => s.toLowerCase()).includes(status.toLowerCase());
    const hl = forceHL || autoHL;
    // Extended is now derived purely from the status suffix — "-extended"
    const ext = status === "extended" || baseText.toLowerCase().endsWith("-extended");
    const targetSection = document.getElementById("apa-edit-section")?.value || section;
    close();
    await onSave(finalText, hl, ext, targetSection);
    // Persist franchise tag against the saved text. Runs after the
    // doc save so the tag is keyed against the final shape (with
    // status / sub suffixes), and apa._franchise_key strips them
    // back to the canonical key.
    if (franchise !== currentFranchise) {
      try {
        await pywebview.api.set_item_franchise(finalText, franchise);
      } catch (_) { /* non-fatal */ }
    }
  });
  if (onDelete) {
    document.getElementById("apa-pop-del").addEventListener("click", async () => {
      if (!confirm("Delete this item?")) return;
      close();
      await onDelete();
    });
  }
  document.getElementById("apa-edit-text").focus();
}

function closeEditPopover() {
  document.getElementById("apa-popover")?.remove();
}

let saveTimer = null;
async function saveDoc() {
  if (!state.doc) return;
  if (saveTimer) clearTimeout(saveTimer);
  setStatus("Saving…");
  // Re-render immediately so the user sees their change, then
  // persist in the background.
  renderBoard();
  const sectionsPayload = state.doc.sections.map((s) => ({
    name:  s.name,
    items: s.items.map((it) => ({
      text: it.text, highlighted: !!it.highlighted,
    })),
  }));
  const res = await pywebview.api.save_doc(state.doc.date_iso, sectionsPayload);
  if (!res?.ok) {
    setStatus(`Save failed: ${res?.error || "?"}`, "error");
    return;
  }
  // Re-sync local state from the freshly-parsed doc on disk
  state.doc = res.doc;
  renderBoard();
  setStatus("✓ Saved", "ok");
}

// ── Search / toggle ─────────────────────────────────────────────
let searchTimer = null;
function onSearchInput(ev) {
  state.search = ev.target.value;
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(renderBoard, 120);
}

function setToggle(value) {
  state.toggle = value;
  $$(".toggle-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.toggle === value);
  });
  renderBoard();
}

// ── Actions ──────────────────────────────────────────────────────
async function openInWord() {
  if (!state.doc?.doc_path) return;
  const ok = await pywebview.api.open_doc_in_word(state.doc.doc_path);
  setStatus(ok ? "Opened in Word" : "Couldn't open Word", ok ? "ok" : "error");
}

async function revealInExplorer() {
  if (!state.doc?.doc_path) return;
  await pywebview.api.reveal_in_explorer(state.doc.doc_path);
}

function onKeyDown(ev) {
  // Ctrl+S / Cmd+S → save immediately + show a toast. APA already
  // auto-saves on every edit, but the user expected the keyboard
  // shortcut to work (Tk apa_monitor_gui.py:744 had the same).
  // Don't intercept while typing in an input — except when the
  // target is the search box, where Ctrl+S would otherwise trigger
  // the browser's "Save Page As" dialog.
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey &&
      (ev.key === "s" || ev.key === "S")) {
    ev.preventDefault();
    ev.stopPropagation();
    forceSave();
    return;
  }
  if (ev.target.tagName === "INPUT") return;
  if (ev.key === "ArrowLeft" && ev.altKey)  stepDate(-1);
  else if (ev.key === "ArrowRight" && ev.altKey) stepDate(+1);
  else if (ev.key === "Home" && ev.altKey)  loadToday();
  else if (ev.key === "/" && !ev.ctrlKey)   {
    $("#search-box").focus(); ev.preventDefault();
  }
}

// Explicit user-triggered save (Ctrl+S). Same backend the auto-
// save flow uses but always surfaces a visible "✓ Saved" toast +
// briefly flashes the dirty-flag indicator so the user knows the
// shortcut registered.
async function forceSave() {
  if (!state.doc?.date_iso) return;
  state.savingViaShortcut = true;
  setDirty(true);
  setStatus("💾 Saving…");
  try {
    await saveDoc();  // saveDoc handles its own toast on failure
  } finally {
    state.savingViaShortcut = false;
    setDirty(false);
  }
}

// Dirty-flag indicator — shows a yellow ● next to the date label
// while edits are in flight. Cleared on save success. Light-touch
// since APA auto-saves continuously; mostly here so Ctrl+S has
// visible feedback during the round-trip.
function setDirty(on) {
  state.dirty = !!on;
  const lbl = document.getElementById("date-label");
  if (!lbl) return;
  let marker = document.getElementById("dirty-marker");
  if (on) {
    if (!marker) {
      marker = document.createElement("span");
      marker.id = "dirty-marker";
      marker.textContent = " ●";
      marker.title = "Unsaved edits — saving…";
      marker.style.cssText = "color:var(--amber);font-weight:700;";
      lbl.appendChild(marker);
    }
  } else if (marker) {
    marker.remove();
  }
}

// ── Status helpers ───────────────────────────────────────────────
let statusTimer = null;
function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
  if (statusTimer) clearTimeout(statusTimer);
  if (msg && kind === "ok") {
    statusTimer = setTimeout(() => {
      el.textContent = "";
      el.className = "status-msg";
    }, 2500);
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function escapeAttr(s) { return escapeHtml(s); }

// ── Contacts modal — manage estimator emails + EOD recipients ───
async function openContactsModal() {
  const estimators = await pywebview.api.get_estimators() || [];
  const eodRecipients = await pywebview.api.get_eod_recipients() || [];
  // Per-estimator emails — fetch each
  const emails = {};
  for (const est of estimators) {
    emails[est] = await pywebview.api.get_estimator_email(est) || "";
  }
  const w = document.createElement("div");
  w.id = "apa-contacts-modal";
  w.className = "apa-popover-backdrop";
  w.innerHTML = `
    <div class="apa-popover" style="width:min(640px,92vw);">
      <header class="apa-pop-head">
        <div>
          <div class="apa-pop-title">👥 APA Contacts</div>
          <div class="apa-pop-sub">Estimator Teams emails + EOD email recipients</div>
        </div>
        <button class="apa-pop-close" id="cn-close">✕</button>
      </header>
      <div class="apa-pop-body" style="max-height:60vh;overflow-y:auto;">
        <h3 style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px;">Estimator emails (Teams)</h3>
        ${estimators.map((est) => `
          <div style="display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;margin-bottom:6px;">
            <span style="font-weight:600;font-size:12px;">${escapeHtml(est)}</span>
            <input class="apa-pop-select cn-est-email"
                   data-estimator="${escapeAttr(est)}"
                   type="text" value="${escapeAttr(emails[est] || "")}"
                   placeholder="name@servpro10100.com" />
          </div>`).join("")}
        <h3 style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin:16px 0 8px;">EOD email recipients</h3>
        <textarea id="cn-eod" rows="4" style="width:100%;"
          placeholder="One email per line (or comma-separated).">${escapeHtml((eodRecipients || []).join("\n"))}</textarea>
      </div>
      <footer class="apa-pop-foot">
        <div class="apa-pop-spacer"></div>
        <button class="apa-pop-btn" id="cn-cancel">Cancel</button>
        <button class="apa-pop-btn apa-pop-save" id="cn-save">💾 Save all</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  w.addEventListener("click", (e) => { if (e.target === w) w.remove(); });
  document.getElementById("cn-close").addEventListener("click", () => w.remove());
  document.getElementById("cn-cancel").addEventListener("click", () => w.remove());
  document.getElementById("cn-save").addEventListener("click", async () => {
    // Save every estimator email
    const inputs = w.querySelectorAll(".cn-est-email");
    for (const inp of inputs) {
      await pywebview.api.set_estimator_email(
        inp.dataset.estimator, inp.value.trim());
    }
    // Save EOD recipients (split on commas / semicolons / newlines)
    const eodText = document.getElementById("cn-eod").value;
    const emails = eodText.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
    await pywebview.api.set_eod_recipients(emails);
    w.remove();
    setStatus("💾 Contacts saved", "ok");
  });
}

// ── Bulk paste modal (P1) ───────────────────────────────────────
async function openBulkPasteModal() {
  const sections = (state.doc?.sections || []).map((s) => s.name);
  const w = document.createElement("div");
  w.id = "apa-bulk-modal";
  w.className = "apa-popover-backdrop";
  w.innerHTML = `
    <div class="apa-popover">
      <header class="apa-pop-head">
        <div>
          <div class="apa-pop-title">📋 Bulk paste items</div>
          <div class="apa-pop-sub">Paste one item per line — each line becomes its own APA row</div>
        </div>
        <button class="apa-pop-close" id="bp-close">✕</button>
      </header>
      <div class="apa-pop-body">
        <label class="apa-pop-lbl">Target section</label>
        <select id="bp-section" class="apa-pop-select">
          ${sections.map((s) =>
            `<option value="${escapeAttr(s)}">${escapeHtml(s)}</option>`).join("")}
        </select>
        <label class="apa-pop-lbl" style="margin-top:10px;">Lines (one item per line)</label>
        <textarea id="bp-text" rows="10"
          placeholder="Smith, John - AAA-pending&#10;Doe, Jane - Mercury-uploading&#10;Brown, Bob - Farmers"></textarea>
        <div class="apa-pop-hint">Existing duplicates are auto-skipped.</div>
      </div>
      <footer class="apa-pop-foot">
        <div class="apa-pop-spacer"></div>
        <button class="apa-pop-btn" id="bp-cancel">Cancel</button>
        <button class="apa-pop-btn apa-pop-save" id="bp-add">📋 Add to section</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  w.addEventListener("click", (e) => { if (e.target === w) w.remove(); });
  document.getElementById("bp-close").addEventListener("click", () => w.remove());
  document.getElementById("bp-cancel").addEventListener("click", () => w.remove());
  document.getElementById("bp-add").addEventListener("click", async () => {
    const section = document.getElementById("bp-section").value;
    const lines = document.getElementById("bp-text").value.split("\n");
    const res = await pywebview.api.bulk_add_items(section, lines);
    if (!res?.ok) {
      setStatus(`Bulk add failed: ${res?.error || "?"}`, "error");
      return;
    }
    w.remove();
    setStatus(
      `📋 Added ${res.added.length} items`
      + (res.skipped_dupes ? ` · skipped ${res.skipped_dupes} dupes` : ""),
      "ok");
    await loadDate(state.active_date);
  });
  document.getElementById("bp-text").focus();
}

// ── Topbar Trello search → auto-add with section routing ────────
function attachApaTrelloSearch() {
  const input = document.getElementById("apa-trello-search");
  const results = document.getElementById("apa-trello-results");
  if (!input || !results) return;
  let timer = null;
  const hide = () => { results.style.display = "none"; };
  const show = () => { results.style.display = "block"; };
  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { hide(); return; }
    results.innerHTML =
      `<div style="padding:12px;color:var(--text-muted);">Searching Trello…</div>`;
    show();
    timer = setTimeout(async () => {
      const hits = await pywebview.api.trello_search(q) || [];
      if (!hits.length) {
        results.innerHTML =
          `<div style="padding:12px;color:var(--text-muted);">No matches for "${escapeHtml(q)}"</div>`;
        return;
      }
      // For each match, also load the lane-suggested section so the
      // user sees where it'll land before clicking.
      results.innerHTML = hits.map((h) => `
        <div class="apa-ts-row" data-card="${escapeAttr(h.card_id)}" data-lane="${escapeAttr(h.lane || "")}"
             style="padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;">
          <div style="font-weight:600;color:var(--text);">${escapeHtml(h.name)}</div>
          <div style="font-size:11px;color:var(--text-muted);">
            ${escapeHtml(h.lane || "—")} · ${escapeHtml(h.board || "")}
          </div>
        </div>`).join("");
      results.querySelectorAll(".apa-ts-row").forEach((row) => {
        row.addEventListener("mouseenter",
          () => row.style.background = "var(--row-hover)");
        row.addEventListener("mouseleave",
          () => row.style.background = "transparent");
        row.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          hide();
          input.value = "";
          setStatus("Fetching Trello card details…");
          // Capture lane + name from the search row up-front so they
          // can be passed to the backend even if get_card fails. The
          // backend now derives section/sub from the lane FIRST so
          // partial Trello failures don't drop us on Initial Uploads.
          const rowName = row.querySelector("div")?.textContent || "";
          const rowLane = row.dataset.lane || "";
          let sug = null;
          try {
            sug = await pywebview.api.suggest_apa_routing(
              row.dataset.card, rowLane, rowName);
          } catch (e) {
            setStatus(`Routing error: ${e}`, "error");
          }
          // Even when something partial fails the backend now always
          // returns ok=true with whatever it could derive. This local
          // fallback is just for hard JS-side errors (network, etc.).
          const fallback = {
            ok:                true,
            card_id:           row.dataset.card,
            name:              rowName,
            lane:              rowLane,
            suggested_section: "",  // empty → curated list[0] wins,
                                    //          not hardcoded "Initial Uploads"
            suggested_sub:     rowLane,
            carrier:           "",
            claim:             "",
            base_text:         rowName,
          };
          const finalSug = (sug && sug.ok) ? sug : fallback;
          if (finalSug.notes?.length) {
            console.warn("APA suggest_apa_routing partial:", finalSug.notes);
          }
          await openAddToApaConfirmModal(finalSug);
        });
      });
    }, 240);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#apa-trello-wrap")) hide();
  });
}

// ── Add-to-APA confirmation modal ───────────────────────────────
// Opens after the user picks a Trello card from the topbar search.
// Shows every field that's about to be written so they can verify /
// edit before committing. Defaults are populated from the Trello
// card's lane (section/sub) and description (carrier/claim).
async function openAddToApaConfirmModal(sug) {
  // Pull dropdown data — each call wrapped so one failing doesn't
  // block the modal from opening. Falls back to sensible defaults.
  // CURATED section list mirrors Tk's add-dialog choices (no PENDING
  // REVIEW; includes estimators) with a has_subs flag per section
  // driving whether the Sub field shows.
  let sectionInfo = [];
  let opts = { statuses: ["pending"], subs: null };
  try {
    const sl = await pywebview.api.add_dialog_sections();
    if (Array.isArray(sl) && sl.length) sectionInfo = sl;
  } catch (_) { /* fall through */ }
  if (!sectionInfo.length) {
    sectionInfo = [
      { name: "Initial Uploads", has_subs: true },
      { name: "Final Uploads",   has_subs: true },
      { name: "ESTIMATING MISSING/ADDITIONAL ITEMS", has_subs: false },
      { name: "ESTIMATING SERVICE CALL", has_subs: false },
      { name: "ESTIMATING TBA",      has_subs: false },
      { name: "ESTIMATING SNAPSHOT", has_subs: false },
      { name: "Audit Rejection", has_subs: true },
      { name: "Audit Dispute",   has_subs: true },
    ];
  }
  const sectionOptions = sectionInfo.map((s) => s.name);
  const sectionHasSubs = Object.fromEntries(
    sectionInfo.map((s) => [s.name, !!s.has_subs]));
  let currentSection = sug.suggested_section || sectionOptions[0];
  // If the lane-suggested section isn't in our curated list, fall back
  // so the dropdown selection stays consistent.
  if (!sectionOptions.includes(currentSection)) {
    currentSection = sectionOptions[0];
  }
  try {
    const so = await pywebview.api.status_options(currentSection);
    if (so) opts = so;
  } catch (_) { /* fall through */ }
  setStatus("");  // clear the "fetching…" toast from the click handler

  const w = document.createElement("div");
  w.id = "apa-add-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(640px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📥 Add to APA from Trello</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
          From lane <b>${escapeHtml(sug.lane || "—")}</b> · verify + edit before adding
        </div>
      </header>
      <div style="padding:18px 20px;display:grid;grid-template-columns:1fr 1fr;gap:12px;overflow-y:auto;">
        <label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;">
          <span class="lbl">Insured *</span>
          <input id="aa-insured" class="search" type="text" value="${escapeAttr(sug.name || "")}" />
        </label>
        <label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;">
          <span class="lbl">Carrier</span>
          <input id="aa-carrier" class="search" type="text" value="${escapeAttr(sug.carrier || "")}" placeholder="Mercury, AAA, …" />
        </label>
        <label style="display:flex;flex-direction:column;gap:4px;">
          <span class="lbl">Section *</span>
          <select id="aa-section" class="search">
            ${sectionOptions.map((s) =>
              `<option value="${escapeAttr(s)}" ${s === currentSection ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}
          </select>
        </label>
        <label id="aa-sub-wrap" style="display:flex;flex-direction:column;gap:4px;">
          <span class="lbl">Sub</span>
          <select id="aa-sub" class="search"></select>
        </label>
        <label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;">
          <span class="lbl">Status</span>
          <select id="aa-status" class="search"></select>
        </label>
        <div style="grid-column:1/-1;font-size:11px;color:var(--text-muted);padding:8px 10px;background:var(--surface-2);border-radius:6px;">
          <b>Preview:</b> <span id="aa-preview" style="color:var(--text);">—</span>
        </div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;align-items:center;">
        <span style="font-size:11px;color:var(--text-muted);margin-right:auto;">
          Will be pinned to this Trello card too
        </span>
        <button class="btn" id="aa-cancel">Cancel</button>
        <button class="btn btn-primary" id="aa-go">📥 Add to APA</button>
      </footer>
    </div>
    <style>
      #apa-add-modal .lbl { font-size:10px;font-weight:700;text-transform:uppercase;
        letter-spacing:.04em;color:var(--text-muted); }
    </style>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#aa-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });

  // Repopulate sub + status dropdowns whenever section changes.
  // Hides the entire Sub row when the section is an estimator
  // (JUAN/KIM/ZAC/etc.) or an Estimating-* bucket — matches Tk's
  // _refresh_sub_status which pack_forget's the sub widgets when
  // _sub_options_for_section returns None.
  function fillStatusSub() {
    const subWrap = w.querySelector("#aa-sub-wrap");
    const subSel  = w.querySelector("#aa-sub");
    const statSel = w.querySelector("#aa-status");
    const hasSubs = sectionHasSubs[currentSection];
    const subs = (hasSubs && Array.isArray(opts.subs)) ? opts.subs : null;

    if (subs && subs.length) {
      // Suggested sub — for sections WITH subs, defaults to either a
      // canonical SUB_OPTIONS value (lane fuzzy-matched on the
      // backend) or the raw lane name when no match.
      const suggested = (sug.suggested_sub || "").trim();
      const subsList = suggested && !subs.includes(suggested)
        ? [suggested, ...subs]
        : subs;
      subSel.innerHTML = `<option value="">(none)</option>`
        + subsList.map((s) => {
            const isCustom = s === suggested && !subs.includes(s);
            const label = isCustom ? `${s}  (from lane)` : s;
            return `<option value="${escapeAttr(s)}" ${s === suggested ? "selected" : ""}>${escapeHtml(label)}</option>`;
          }).join("");
      subSel.disabled = false;
      // Explicit "flex" — clearing the inline style would revert
      // <label>'s default display:inline and float the "Sub" text
      // to the left of the select instead of stacking above it.
      subWrap.style.display = "flex";
    } else {
      // Estimator / Estimating-* / Pending Review — no sub field.
      // Hide the row entirely to match the Tk "this section doesn't
      // use a sub" UX.
      subWrap.style.display = "none";
      subSel.innerHTML = "";
    }

    const statuses = opts.statuses || ["pending"];
    statSel.innerHTML = `<option value="">(no status)</option>`
      + statuses.map((s) => `<option value="${escapeAttr(s)}" ${s === "pending" ? "selected" : ""}>${escapeHtml(s)}</option>`).join("");
    refreshPreview();
  }
  function refreshPreview() {
    const insured = w.querySelector("#aa-insured").value.trim();
    const carrier = w.querySelector("#aa-carrier").value.trim();
    const sub     = w.querySelector("#aa-sub").value.trim();
    const stat    = w.querySelector("#aa-status").value.trim();
    let preview = insured || "(insured?)";
    if (carrier) preview += " - " + carrier;
    if (sub)     preview += "-" + sub;
    if (stat)    preview += "-" + stat;
    w.querySelector("#aa-preview").textContent = preview;
  }
  w.querySelector("#aa-section").addEventListener("change", async (e) => {
    currentSection = e.target.value;
    try {
      opts = await pywebview.api.status_options(currentSection) || {};
    } catch (_) { opts = {}; }
    fillStatusSub();
  });
  ["aa-insured", "aa-carrier"].forEach((id) =>
    w.querySelector("#" + id).addEventListener("input", refreshPreview));
  w.querySelector("#aa-sub").addEventListener("change", refreshPreview);
  w.querySelector("#aa-status").addEventListener("change", refreshPreview);
  fillStatusSub();

  w.querySelector("#aa-go").addEventListener("click", async () => {
    const insured = w.querySelector("#aa-insured").value.trim();
    if (!insured) { setStatus("Insured is required", "warn"); return; }
    const carrier = w.querySelector("#aa-carrier").value.trim();
    const section = w.querySelector("#aa-section").value;
    // Sub field is hidden for estimator/Estimating-* sections — read
    // empty string in that case so no spurious sub gets appended.
    const sub     = sectionHasSubs[section]
                      ? (w.querySelector("#aa-sub").value || "")
                      : "";
    const stat    = w.querySelector("#aa-status").value;
    let text = insured;
    if (carrier) text += " - " + carrier;
    const btn = w.querySelector("#aa-go");
    btn.disabled = true; btn.textContent = "Adding…";
    // If the user is viewing a different day, jump to today first so
    // they can see the new row land.
    const todayISO = new Date().toISOString().slice(0, 10);
    if (state.active_date !== todayISO) {
      await loadDate(todayISO);
    }
    const res = await pywebview.api.add_item_to_section(
      section, text, stat, sub, false);
    btn.disabled = false; btn.textContent = "📥 Add to APA";
    if (!res?.ok) {
      setStatus(`Add failed: ${res?.error || "?"}`, "error");
      return;
    }
    // Pin the Trello card to this client too (so audit/snapshot share)
    try {
      await pywebview.api.pin_trello_for_item(text, sug.card_id);
    } catch (_) {}
    close();
    state.doc = res.doc;
    renderBoard();
    setStatus(`📥 Added "${text}" → ${section}${sub ? " (" + sub + ")" : ""}`, "ok");
    // Scroll to the section so the user sees the new row land
    setTimeout(() => {
      const btn = document.querySelector(
        `.add-item-btn[data-section="${section.replace(/"/g, '\\"')}"]`);
      const card = btn?.closest("section");
      if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  });
  w.querySelector("#aa-insured").focus();
}

// ── Drag-and-drop items between sections ────────────────────────
// Native HTML5 drag: pick up an APA item with the mouse, drop it on
// any section's body to move it across columns. Single backend save
// fires after the drop completes.
let _apaDragRef = null;  // { section, index, item }

function attachApaItemDrag(el) {
  // Gate `draggable=true` behind a LEFT mousedown so right-click
  // still fires contextmenu reliably. With unconditional
  // draggable=true, WebView2 / Chromium suppressed the
  // contextmenu event on items, breaking the per-item right-click
  // menu (Status / Sub / Move / Open Trello / Delete).
  el.draggable = false;
  el.addEventListener("mousedown", (e) => {
    if (e.button === 0) el.draggable = true;
  });
  // Reset after either a drag completes or any mouseup outside a
  // started drag, so subsequent right-clicks always fire ctx menu.
  el.addEventListener("dragstart", (e) => {
    const sectionName = el.dataset.section;
    const idx = parseInt(el.dataset.index, 10);
    const sec = state.doc?.sections?.find((s) => s.name === sectionName);
    if (!sec) return;
    _apaDragRef = {
      section: sectionName,
      index:   idx,
      item:    sec.items[idx],
    };
    el.classList.add("dragging");
    try { e.dataTransfer.setData("text/plain", "apa-item"); } catch (_) {}
    e.dataTransfer.effectAllowed = "move";
  });
  el.addEventListener("dragend", () => {
    el.classList.remove("dragging");
    el.draggable = false;
    document.querySelectorAll(".section-body.drop-target")
      .forEach((s) => s.classList.remove("drop-target"));
    _apaDragRef = null;
  });
  el.addEventListener("mouseup", () => {
    // If no drag started, reset draggable immediately. dragend
    // handles the drag-completed case.
    setTimeout(() => { el.draggable = false; }, 0);
  });
}

function attachApaSectionDrop(body) {
  body.addEventListener("dragover", (e) => {
    if (!_apaDragRef) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    body.classList.add("drop-target");
  });
  body.addEventListener("dragleave", (e) => {
    // Only clear when leaving the body element itself, not its
    // children (dragleave fires on every child boundary).
    if (e.target === body) body.classList.remove("drop-target");
  });
  body.addEventListener("drop", async (e) => {
    e.preventDefault();
    body.classList.remove("drop-target");
    if (!_apaDragRef) return;
    const targetSection = body.dataset.section;
    if (!targetSection) return;
    const src = state.doc.sections.find((s) => s.name === _apaDragRef.section);
    const dst = state.doc.sections.find((s) => s.name === targetSection);
    if (!src || !dst) return;
    // Figure out the insert position from the cursor's Y within the
    // target body. Find the .item beneath/closest to the drop point
    // and insert before it (or at end if past the last row).
    const items = Array.from(body.querySelectorAll(".item[data-section]"));
    let insertIdx = items.length;
    for (let i = 0; i < items.length; i++) {
      const rect = items[i].getBoundingClientRect();
      if (e.clientY < rect.top + rect.height / 2) {
        insertIdx = parseInt(items[i].dataset.index, 10);
        break;
      }
    }
    const moved = src.items.splice(_apaDragRef.index, 1)[0];
    if (!moved) return;
    src.count = src.items.length;
    // When dragging WITHIN the same section, the splice shifts later
    // indices down by 1. Compensate so dropping into "the slot right
    // after the source" doesn't no-op.
    if (src === dst && insertIdx > _apaDragRef.index) insertIdx -= 1;
    dst.items.splice(insertIdx, 0, moved);
    dst.count = dst.items.length;
    _apaDragRef = null;
    await saveDoc();
    setStatus(
      src === dst
        ? `↕ Reordered in ${targetSection}`
        : `📂 Moved → ${targetSection}`,
      "ok");
  });
}

// ── Franchise picker popover (per-item tag) ─────────────────────
async function openFranchisePicker(anchor, sectionName, itemIndex) {
  const sec = state.doc?.sections?.find((s) => s.name === sectionName);
  const item = sec?.items?.[itemIndex];
  if (!item) return;
  let roster = [];
  try { roster = await pywebview.api.get_franchise_list() || []; } catch (_) {}
  // Position the popover next to the chip
  const rect = anchor.getBoundingClientRect();
  const pop = document.createElement("div");
  pop.className = "franchise-picker";
  pop.style.cssText =
    `position:fixed;z-index:300;
     background:var(--surface);border:1px solid var(--border);
     border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.4);
     min-width:200px;max-height:340px;overflow-y:auto;
     top:${rect.bottom + 4}px;left:${Math.max(8, rect.right - 200)}px;`;
  const cur = item.franchise || "";
  pop.innerHTML = `
    <div style="padding:8px 12px;border-bottom:1px solid var(--border);
                font-size:10px;text-transform:uppercase;letter-spacing:.04em;
                color:var(--text-muted);font-weight:700;">
      Assign franchise
    </div>
    <button class="fp-item" data-fr="" style="display:block;width:100%;text-align:left;
            background:transparent;color:var(--text-muted);border:none;padding:8px 14px;
            cursor:pointer;font:inherit;font-size:13px;
            ${cur === "" ? "background:var(--surface-2);" : ""}">
      ✕ Clear tag
    </button>
    ${roster.map((f) => `
      <button class="fp-item" data-fr="${escapeAttr(f)}"
              style="display:block;width:100%;text-align:left;
                     background:transparent;color:var(--text);border:none;
                     border-top:1px solid var(--border);padding:8px 14px;
                     cursor:pointer;font:inherit;font-size:13px;
                     ${cur === f ? "background:var(--surface-2);font-weight:600;" : ""}">
        ${cur === f ? "✓ " : ""}${escapeHtml(f)}
      </button>`).join("")}
    <div style="border-top:1px solid var(--border);padding:8px;">
      <div style="display:flex;gap:6px;">
        <input id="fp-new" class="search" type="text"
               placeholder="+ Add new franchise"
               style="flex:1;font-size:12px;padding:5px 8px;" />
        <button class="btn" id="fp-add-save" style="font-size:11px;padding:4px 8px;">Save</button>
      </div>
    </div>
  `;
  document.body.appendChild(pop);
  const close = () => pop.remove();
  // Close on outside click
  const outside = (e) => {
    if (!pop.contains(e.target)) { close(); document.removeEventListener("click", outside); }
  };
  setTimeout(() => document.addEventListener("click", outside), 0);
  pop.querySelectorAll(".fp-item").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const newFr = b.dataset.fr;
      const res = await pywebview.api.set_item_franchise(item.text, newFr);
      if (!res?.ok) { setStatus(`Tag failed: ${res?.error || "?"}`, "error"); return; }
      item.franchise = newFr;
      close();
      document.removeEventListener("click", outside);
      renderBoard();
      setStatus(newFr
        ? `🏢 Tagged "${item.text}" → ${newFr}`
        : `Cleared franchise tag`, "ok");
    }));
  pop.querySelector("#fp-add-save").addEventListener("click", async () => {
    const newName = pop.querySelector("#fp-new").value.trim();
    if (!newName) return;
    const list = (await pywebview.api.get_franchise_list()) || [];
    if (!list.includes(newName)) list.push(newName);
    await pywebview.api.set_franchise_list(list);
    // Apply this new franchise to the current item too
    const res = await pywebview.api.set_item_franchise(item.text, newName);
    if (res?.ok) {
      item.franchise = newName;
      close();
      document.removeEventListener("click", outside);
      renderBoard();
      await attachFranchiseFilter();  // refresh filter dropdown
      setStatus(`🏢 Added franchise "${newName}" + tagged this item`, "ok");
    }
  });
  pop.querySelector("#fp-new").addEventListener("keydown", (e) => {
    if (e.key === "Enter") pop.querySelector("#fp-add-save").click();
  });
}

// ── Franchise filter + per-item tag display ─────────────────────
async function attachFranchiseFilter() {
  const sel = document.getElementById("franchise-filter");
  if (!sel) return;
  const list = await pywebview.api.get_franchise_list() || [];
  const current = await pywebview.api.get_franchise_filter() || "";
  sel.innerHTML = `<option value="">All franchises</option>`
    + list.map((f) => `<option value="${escapeAttr(f)}" ${f === current ? "selected" : ""}>${escapeHtml(f)}</option>`).join("");
  sel.addEventListener("change", async () => {
    await pywebview.api.set_franchise_filter(sel.value || "");
    await loadDate(state.active_date);
  });
}

// ── More menu (consolidated: Open in Word / Explorer / Contacts) ──
function attachMoreMenu() {
  const btn = document.getElementById("more-btn");
  const menu = document.getElementById("more-menu");
  if (!btn || !menu) return;
  const hide = () => { menu.style.display = "none"; };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.style.display = menu.style.display === "block" ? "none" : "block";
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#more-wrap")) hide();
  });
  // Close the menu after any item click (the existing click handlers
  // on open-word-btn / reveal-btn / contacts-btn fire first because
  // they're attached at boot — this just collapses the dropdown).
  menu.querySelectorAll(".more-item").forEach((el) =>
    el.addEventListener("click", () => setTimeout(hide, 0)));
}

// ── Create APA file for the currently-viewed date ───────────────
async function createTodayDoc() {
  // Callable from either the topbar button or the empty-state
  // button — find whichever is visible so we can disable it during
  // the call. Default to the topbar.
  const btn = document.getElementById("create-doc-btn")
            || document.getElementById("empty-create-btn");
  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Creating…"; }
  // Use the currently-active date so the user can create a doc for
  // any day (today, yesterday, or further back). create_doc is a
  // no-op when the doc already exists, so this is safe everywhere.
  const targetIso = state.active_date || "";
  // Default to carry-forward — matches Tk behavior; the user can
  // delete carried-forward rows after creation if they want a fresh
  // start.
  const res = await pywebview.api.create_doc(targetIso, true);
  if (btn) { btn.disabled = false; btn.textContent = orig; }
  if (!res?.ok) {
    setStatus(`Create failed: ${res?.error || "?"}`, "error");
    return;
  }
  if (res.created) {
    setStatus(
      `＋ Created today's APA${res.carried ? ` · carried ${res.carried} items from prior day` : ""}`,
      "ok");
  } else {
    setStatus(res.note || "Doc already existed", "warn");
  }
  await loadDate(state.active_date);
  // Review the carried jobs — after loadDate, so state.doc is the doc
  // the modal will be editing. Every carried job is listed with what the
  // Trello check decided, not just the ones it couldn't place: an
  // automatic move is still a decision worth a glance.
  if (res.created) {
    const rows = res.reviewed?.length ? res.reviewed : (res.unrouted || []);
    if (rows.length) await openCarryPlacementModal(rows);
  }
}

// ── Refresh lanes from Trello (new-day cleanup) ─────────────────
// After create_doc carries yesterday's extended/pending jobs forward in
// their OLD sections, this re-routes each item into the section matching
// its pinned Trello card's CURRENT lane — so the new doc mirrors where
// each job sits in Trello today. Items with no pin / unmapped lane stay.
async function refreshLanesFromTrello() {
  const btn = document.getElementById("refresh-lanes-btn");
  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "🔄 Checking Trello…"; }
  const res = await pywebview.api.refresh_doc_lanes(state.active_date || "");
  if (btn) { btn.disabled = false; btn.textContent = orig; }
  if (!res?.ok) {
    setStatus(`Refresh failed: ${res?.error || "?"}`, "error");
    return;
  }
  if (res.doc) { state.doc = res.doc; renderBoard(); }
  const stuck = res.unrouted?.length || 0;
  setStatus(
    (res.moved
      ? `🔄 Moved ${res.moved} item${res.moved !== 1 ? "s" : ""} to match Trello lanes (${res.checked} pinned checked)`
      : `🔄 All ${res.checked} pinned items already in the right section`)
    + (stuck ? ` · ${stuck} couldn't be placed` : ""),
    "ok");
  // Manual refresh: same review, so the user can see what the check did
  // and disagree with any of it — not just hunt for the failures.
  const rows = res.reviewed?.length ? res.reviewed : (res.unrouted || []);
  if (rows.length) await openCarryPlacementModal(rows);
}

// ── "Where should these go?" — carry-forward placement ──────────
// Trello lanes place most carried jobs on their own. The rest — no
// pinned card, no readable lane, or a lane that maps to no section —
// used to stay silently in yesterday's section, which nobody notices
// until the job is filed wrong. Ask instead, once, at the moment the
// day rolls over.
// How each carried job fared against Trello. The two "checked" outcomes
// read as reassurance; the three failures read as "you decide".
const CARRY_STATUS = {
  confirmed:     { chip: "✓ Trello",   tone: "var(--green,#3fb950)",
                   note: (r) => `already in the right section${r.lane ? " · " + r.lane : ""}` },
  moved:         { chip: "→ Moved",    tone: "var(--accent,#4c9aff)",
                   note: (r) => `${r.section} → ${r.dest}${r.lane ? " · " + r.lane : ""}` },
  no_card:       { chip: "? No card",  tone: "var(--amber,#d29922)",
                   note: () => "no Trello card pinned — couldn't check" },
  no_lane:       { chip: "? No lane",  tone: "var(--amber,#d29922)",
                   note: () => "card pinned, but Trello gave no lane" },
  unmapped_lane: { chip: "? Unmapped", tone: "var(--amber,#d29922)",
                   note: (r) => `lane "${r.lane}" maps to no APA section` },
};

async function openCarryPlacementModal(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  if (!state.doc) return;
  // Accepts the full review list (preferred) or the older unrouted-only
  // list, whose entries carry no dest/status.
  const reviewed = rows.map((r) => ({
    text: r.text,
    section: r.section,
    dest: r.dest || r.section,
    lane: r.lane || "",
    status: r.status || r.reason || "no_card",
  }));
  const unsure = reviewed.filter(
    (r) => !["confirmed", "moved"].includes(r.status)).length;

  // Valid targets: whatever this doc actually has, plus the configured
  // order — a section the user can't see isn't a useful choice.
  let sections = [];
  try {
    const order = await pywebview.api.section_order();
    if (Array.isArray(order)) sections = order.slice();
  } catch (_) { /* fall through to the doc's own sections */ }
  const docSections = (state.doc.sections || []).map((s) => s.name);
  docSections.forEach((n) => { if (!sections.includes(n)) sections.push(n); });
  if (!sections.length) return;

  const w = document.createElement("div");
  w.id = "apa-place-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(720px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📍 Review carried-over jobs</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
          ${reviewed.length} job${reviewed.length === 1 ? "" : "s"} carried from the prior day,
          each checked against its Trello card.
          ${unsure
            ? `<b>${unsure}</b> couldn't be checked — those are sitting where they were yesterday.`
            : `All of them checked out.`}
        </div>
      </header>
      <div style="padding:14px 20px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;">
        ${reviewed.map((r, i) => {
          const st = CARRY_STATUS[r.status] || CARRY_STATUS.no_card;
          return `
          <div style="display:grid;grid-template-columns:1fr 230px;gap:10px;align-items:center;
                      padding:8px 10px;background:var(--surface-2);border-radius:6px;">
            <div style="min-width:0;">
              <div style="font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                   title="${escapeAttr(r.text || "")}">${escapeHtml(r.text || "")}</div>
              <div style="font-size:10.5px;color:var(--text-muted);margin-top:2px;
                          display:flex;align-items:center;gap:6px;">
                <span style="color:${st.tone};font-weight:600;white-space:nowrap;">${escapeHtml(st.chip)}</span>
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(st.note(r))}</span>
              </div>
            </div>
            <select class="search ap-sel" data-ix="${i}">
              ${sections.map((s) =>
                `<option value="${escapeAttr(s)}" ${s === r.dest ? "selected" : ""}>${escapeHtml(s)}</option>`
              ).join("")}
            </select>
          </div>`; }).join("")}
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;align-items:center;">
        <span style="font-size:11px;color:var(--text-muted);margin-right:auto;">
          Each dropdown already holds what the Trello check decided — change any you disagree with
        </span>
        <button class="btn" id="ap-skip">Accept as-is</button>
        <button class="btn btn-primary" id="ap-go">Apply changes</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  document.getElementById("ap-skip").addEventListener("click", close);

  document.getElementById("ap-go").addEventListener("click", async () => {
    const moves = [];
    w.querySelectorAll(".ap-sel").forEach((sel) => {
      const r = reviewed[Number(sel.dataset.ix)];
      // Move FROM `dest` — the Trello check already wrote the doc, so
      // that is where the row actually sits now. Using `section` (where
      // it came from) would look for it in the section it just left.
      if (r && sel.value && sel.value !== r.dest) {
        moves.push({ from: r.dest, to: sel.value, text: r.text });
      }
    });
    close();
    if (!moves.length) { setStatus("Carried jobs left as the Trello check placed them", "ok"); return; }
    // Move in local state, then reuse the normal whole-doc save.
    let applied = 0;
    for (const mv of moves) {
      const src = (state.doc.sections || []).find((s) => s.name === mv.from);
      if (!src) continue;
      const ix = src.items.findIndex((it) => it.text === mv.text);
      if (ix < 0) continue;
      const [item] = src.items.splice(ix, 1);
      let dst = (state.doc.sections || []).find((s) => s.name === mv.to);
      if (!dst) { dst = { name: mv.to, items: [] }; state.doc.sections.push(dst); }
      dst.items.push(item);
      applied += 1;
    }
    if (!applied) { setStatus("Nothing to move — the doc changed underneath", "warn"); return; }
    await saveDoc();
    setStatus(`📍 Placed ${applied} carried job${applied !== 1 ? "s" : ""}`, "ok");
  });
}

// ── APA right-click context menu (Tk parity) ────────────────────
// Lets the user change Status / Sub / Section / toggle highlight /
// delete without opening the full edit popover. Saves a click on
// every routine update.
async function openApaItemCtxMenu(ev, itemEl) {
  ev.preventDefault();
  ev.stopPropagation();
  document.getElementById("apa-ctx-menu")?.remove();

  const sectionName = itemEl.dataset.section;
  const idx = parseInt(itemEl.dataset.index, 10);
  const section = state.doc.sections.find((s) => s.name === sectionName);
  if (!section) return;
  const item = section.items[idx];
  if (!item) return;

  // Pull status + sub options for this section so the submenus
  // reflect the right list. Also fetch the pinned Trello card so
  // the menu can show either "🔗 Open Trello" or "📌 Pin Trello…"
  // depending on whether the item already has a card pinned.
  let opts = { statuses: ["pending"], subs: null, highlight: [] };
  let pinned = { card_id: "", url: "" };
  try {
    [opts, pinned] = await Promise.all([
      pywebview.api.status_options(sectionName),
      pywebview.api.get_pinned_card_for_item(item.text),
    ]);
    opts = opts || { statuses: ["pending"], subs: null, highlight: [] };
    pinned = pinned || { card_id: "", url: "" };
  } catch (_) {}

  // Strip suffixes to recover current status/sub from the rendered
  // text — same logic showItemPopover uses to pre-fill its selects.
  let bareText = item.text;
  let curStatus = "", curSub = "";
  for (const s of (opts.statuses || []).filter(Boolean)) {
    const suf = "-" + s;
    if (bareText.toLowerCase().endsWith(suf.toLowerCase())) {
      curStatus = s; bareText = bareText.slice(0, -suf.length); break;
    }
  }
  if (opts.subs) {
    for (const s of opts.subs.filter(Boolean)) {
      const suf = "-" + s;
      if (bareText.toLowerCase().endsWith(suf.toLowerCase())) {
        curSub = s; bareText = bareText.slice(0, -suf.length); break;
      }
    }
  }

  // Client name for cross-tool jumps — drop the trailing " - Carrier"
  // so the target tool (audit/IUQ/snapshot) matches "Last, First".
  const focusClient = (bareText.split(" - ")[0] || bareText).trim() || bareText;

  function rebuildText(newSub, newStatus) {
    let t = bareText;
    if (newSub)    t += "-" + newSub;
    if (newStatus) t += "-" + newStatus;
    return t;
  }
  async function applyChange({ status, sub, section: newSec, highlight }) {
    const newStatus = status !== undefined ? status : curStatus;
    const newSub    = sub !== undefined ? sub : curSub;
    let finalText = rebuildText(newSub, newStatus);
    const ext = newStatus === "extended";
    const autoHL = (opts.highlight || []).map((s) => s.toLowerCase())
                     .includes((newStatus || "").toLowerCase());
    // Highlight resolution:
    //  • Explicit toggle (Highlight / Clear menu entries) wins
    //  • Status change → re-derive purely from the new status. If the
    //    new status isn't in HIGHLIGHT_STATUSES (pending / pending
    //    upload), the yellow goes away — even if it was on before.
    //    Without this, a row that was pending stays yellow when you
    //    flip it to "uploaded", which never matches what the Tk
    //    panel does (the docx writer derives the highlight from
    //    status at write time).
    //  • Sub / section change → keep whatever was on, since status
    //    didn't change.
    let hl;
    if (highlight !== undefined) {
      hl = highlight;
    } else if (status !== undefined) {
      hl = autoHL;
    } else {
      hl = item.highlighted || autoHL;
    }
    // Move between sections when requested
    if (newSec && newSec !== sectionName) {
      section.items.splice(idx, 1);
      section.count = section.items.length;
      const dst = state.doc.sections.find((s) => s.name === newSec);
      if (dst) {
        dst.items.push({ text: finalText, highlighted: hl, extended: ext });
        dst.count = dst.items.length;
      }
    } else {
      section.items[idx] = { text: finalText, highlighted: hl, extended: ext };
    }
    await saveDoc();
  }
  async function deleteRow() {
    section.items.splice(idx, 1);
    section.count = section.items.length;
    await saveDoc();
  }

  const m = document.createElement("div");
  m.id = "apa-ctx-menu";
  m.className = "apa-ctx-menu";
  m.style.cssText = `position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;
    z-index:300;background:var(--surface);border:1px solid var(--border);
    border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.5);
    min-width:200px;font-size:12px;visibility:hidden;`;

  function btn(label, onClick, opts2 = {}) {
    const b = document.createElement("button");
    b.className = "apa-ctx-item";
    b.style.cssText = `display:flex;align-items:center;gap:6px;width:100%;text-align:left;
      background:transparent;color:${opts2.color || "var(--text)"};
      border:none;padding:7px 12px;cursor:pointer;font:inherit;
      ${opts2.bold ? "font-weight:600;" : ""}
      ${opts2.muted ? "color:var(--text-muted);" : ""}`;
    if (opts2.iconImg) {
      const img = document.createElement("img");
      img.src = opts2.iconImg; img.alt = "";
      img.style.cssText = "width:13px;height:13px;flex-shrink:0;";
      b.appendChild(img);
      const span = document.createElement("span");
      span.textContent = label;
      b.appendChild(span);
    } else {
      b.textContent = label;
    }
    b.addEventListener("mouseenter", () => b.style.background = "var(--row-hover)");
    b.addEventListener("mouseleave", () => b.style.background = "transparent");
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      m.remove();
      try { await onClick(); } catch (_) {}
    });
    m.appendChild(b);
    return b;
  }
  function sep() {
    const d = document.createElement("div");
    d.style.cssText = "height:1px;background:var(--border);margin:3px 0;";
    m.appendChild(d);
  }
  function header(text) {
    const h = document.createElement("div");
    h.style.cssText = `padding:5px 12px;font-size:10px;font-weight:700;
      letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);`;
    h.textContent = text;
    m.appendChild(h);
  }

  // ── Hover-expand submenu helper ─────────────────────────────────
  // User asked the APA right-click to use proper nested submenus —
  // hover over "Status" → submenu fly-out with the status options.
  // Tracks the active submenu so hovering a different parent closes
  // the previous one. Each submenu element auto-positions to the
  // right of its parent and flips left when the viewport runs out.
  let _activeSub = null;
  function _closeSub() { if (_activeSub) { _activeSub.remove(); _activeSub = null; } }
  function submenu(label, items) {
    const row = document.createElement("button");
    row.className = "apa-ctx-item apa-ctx-sub";
    row.style.cssText = `display:flex;align-items:center;justify-content:space-between;
      gap:6px;width:100%;text-align:left;background:transparent;color:var(--text);
      border:none;padding:7px 12px;cursor:pointer;font:inherit;`;
    row.innerHTML = `<span>${esc(label)}</span><span style="color:var(--text-muted);font-size:11px;">▸</span>`;
    row.addEventListener("mouseenter", () => {
      row.style.background = "var(--row-hover)";
      _closeSub();
      const sub = document.createElement("div");
      sub.className = "apa-ctx-submenu";
      sub.style.cssText = `position:fixed;background:var(--surface);
        border:1px solid var(--border);border-radius:6px;
        box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:301;min-width:200px;
        font-size:12px;padding:4px 0;`;
      items.forEach((it) => {
        if (it === "sep") {
          const d = document.createElement("div");
          d.style.cssText = "height:1px;background:var(--border);margin:3px 0;";
          sub.appendChild(d); return;
        }
        const b = document.createElement("button");
        b.style.cssText = `display:flex;align-items:center;gap:6px;width:100%;
          text-align:left;background:transparent;color:${it.color || "var(--text)"};
          border:none;padding:7px 14px;cursor:pointer;font:inherit;
          ${it.muted ? "color:var(--text-muted);" : ""}`;
        b.textContent = it.label;
        b.addEventListener("mouseenter", () => b.style.background = "var(--row-hover)");
        b.addEventListener("mouseleave", () => b.style.background = "transparent");
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          _closeSub();
          m.remove();
          try { await it.action(); } catch (_) {}
        });
        sub.appendChild(b);
      });
      document.body.appendChild(sub);
      // Position to the right of the parent row by default; flip
      // left when off-screen.
      const parentRect = m.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const subRect = sub.getBoundingClientRect();
      let left = parentRect.right - 2;
      if (left + subRect.width + 8 > window.innerWidth) {
        left = parentRect.left - subRect.width + 2;
      }
      let top = rowRect.top;
      if (top + subRect.height + 8 > window.innerHeight) {
        top = Math.max(8, window.innerHeight - subRect.height - 8);
      }
      sub.style.left = left + "px";
      sub.style.top  = top  + "px";
      _activeSub = sub;
      // Keep the submenu open while the cursor is in EITHER the
      // parent row OR the submenu body. Closing happens when the
      // cursor moves to a different top-level row.
      sub.addEventListener("mouseleave", (ev2) => {
        // If we're leaving INTO the parent row, keep the menu open
        const to = ev2.relatedTarget;
        if (to && (to === row || row.contains(to))) return;
        _closeSub();
      });
    });
    row.addEventListener("mouseleave", (ev2) => {
      row.style.background = "transparent";
      // Don't close if moving INTO the submenu
      const to = ev2.relatedTarget;
      if (to && _activeSub && (_activeSub === to || _activeSub.contains(to))) return;
      _closeSub();
    });
    m.appendChild(row);
  }

  // ── Status submenu ─────────────────────────────────────────────
  const statusItems = (opts.statuses || []).filter(Boolean).map((s) => ({
    label: `${s === curStatus ? "✓ " : "  "}${s}`,
    action: () => applyChange({ status: s }),
  }));
  if (curStatus) statusItems.push({
    label: "  (clear status)",
    action: () => applyChange({ status: "" }),
    muted: true,
  });
  if (statusItems.length) submenu("Status", statusItems);

  // ── Sub submenu (when this section has sub options) ────────────
  if (opts.subs && opts.subs.length) {
    const subItems = opts.subs.filter(Boolean).map((s) => ({
      label: `${s === curSub ? "✓ " : "  "}${s}`,
      action: () => applyChange({ sub: s }),
    }));
    if (curSub) subItems.push({
      label: "  (clear sub)",
      action: () => applyChange({ sub: "" }),
      muted: true,
    });
    if (subItems.length) submenu("Sub", subItems);
  }

  // ── Move to section submenu ─────────────────────────────────────
  const moveItems = state.doc.sections
    .filter((s) => s.name !== sectionName)
    .map((s) => ({
      label: `→ ${s.name}`,
      action: () => applyChange({ section: s.name }),
    }));
  if (moveItems.length) submenu("Move to section", moveItems);

  // Close any open submenu when the cursor enters a non-submenu
  // top-level row.
  m.addEventListener("mouseover", (e) => {
    if (e.target.closest(".apa-ctx-sub")) return;
    if (e.target.closest(".apa-ctx-submenu")) return;
    _closeSub();
  });

  // ── Open this job in another tool (flat buttons — no submenu, so
  // they're click-reliable; cross-tool nav goes via the home shell). ──
  sep();
  btn("🔎 Open in Audit",
      () => window.emsNavigateTo?.("audit", focusClient),
      { bold: true });
  btn("📸 Open in Snapshot",
      () => window.emsNavigateTo?.("snapshot", focusClient));
  btn("📁 Open OD folder",
      () => pywebview.api.open_folder_for_client(focusClient));
  btn("🔗 Open XactAnalysis",
      () => pywebview.api.open_xa_for_client(focusClient));

  // Trello — open the pinned card, or open the pin search dialog
  // when no card is attached yet. Most APA items map one-to-one
  // with a Trello card so this is the most-used right-click action.
  sep();
  if (pinned.card_id) {
    btn("Open Trello card",
        () => pywebview.api.open_trello_card(pinned.card_id),
        { iconImg: "../web_shared/trello.png" });
    btn("🔄 Re-pin Trello card…",
        () => openTrelloPinPicker(item.text, pinned.card_id));
  } else {
    btn("📌 Pin Trello card…",
        () => openTrelloPinPicker(item.text, ""));
  }

  sep();
  btn(item.highlighted ? "✕ Clear yellow highlight" : "🟡 Highlight (force)",
      () => applyChange({ highlight: !item.highlighted }));
  btn("📝 Note…",
      () => openItemNoteModal(item.text, sectionName, null));
  sep();
  btn("🗑 Delete row",
      () => { if (confirm("Delete this item?")) deleteRow(); },
      { color: "var(--red)" });

  document.body.appendChild(m);
  // Viewport clamp
  const rect = m.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight, pad = 6;
  let l = ev.clientX, t = ev.clientY;
  if (l + rect.width + pad > vw)  l = Math.max(pad, vw - rect.width - pad);
  if (t + rect.height + pad > vh) t = Math.max(pad, vh - rect.height - pad);
  m.style.left = l + "px";
  m.style.top  = t + "px";
  m.style.visibility = "visible";
}

// ── Trello pin picker (right-click → Pin / Re-pin) ──────────────
async function openTrelloPinPicker(itemText, currentCardId) {
  const w = document.createElement("div");
  w.id = "apa-pin-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(580px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">${currentCardId ? "🔄 Re-pin" : "📌 Pin"} Trello card</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${escapeHtml(itemText)}</div>
      </header>
      <div style="padding:14px 18px;">
        <input id="apa-pin-q" class="search" type="search"
               placeholder="🔎 Search Trello cards by name…"
               style="width:100%;" />
        <div id="apa-pin-results" style="margin-top:10px;max-height:340px;overflow-y:auto;"></div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        ${currentCardId ? `<button class="btn" id="apa-pin-clear">✕ Unpin</button>` : ""}
        <span style="flex:1;"></span>
        <button class="btn" id="apa-pin-cancel">Cancel</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#apa-pin-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  const q = w.querySelector("#apa-pin-q");
  const results = w.querySelector("#apa-pin-results");
  let timer = null;
  async function doSearch() {
    const text = q.value.trim();
    if (text.length < 2) { results.innerHTML = ""; return; }
    results.innerHTML = `<div style="padding:14px;color:var(--text-muted);font-size:12px;">Searching…</div>`;
    const hits = await pywebview.api.trello_search(text) || [];
    if (!hits.length) {
      results.innerHTML = `<div style="padding:14px;color:var(--text-muted);font-size:12px;">No matches</div>`;
      return;
    }
    results.innerHTML = hits.map((h) => `
      <div class="apa-pin-row" data-card="${escapeAttr(h.card_id)}"
           style="padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;">
        <div style="font-weight:600;">${escapeHtml(h.name)}</div>
        <div style="font-size:11px;color:var(--text-muted);">
          ${escapeHtml(h.lane || "")} · ${escapeHtml(h.board || "")}
        </div>
      </div>`).join("");
    results.querySelectorAll(".apa-pin-row").forEach((row) =>
      row.addEventListener("click", async () => {
        const res = await pywebview.api.pin_trello_for_item(itemText, row.dataset.card);
        if (!res?.ok) { setStatus(`Pin failed: ${res?.error || "?"}`, "error"); return; }
        close();
        setStatus(`📌 Pinned card to "${itemText}"`, "ok");
      }));
  }
  q.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(doSearch, 240);
  });
  q.focus();
  const clearBtn = w.querySelector("#apa-pin-clear");
  if (clearBtn) clearBtn.addEventListener("click", async () => {
    await pywebview.api.pin_trello_for_item(itemText, "");
    close();
    setStatus("Unpinned card", "ok");
  });
}

// ── Per-item note modal (📝 button) ─────────────────────────────
async function openItemNoteModal(client, section, anchor) {
  const current = await pywebview.api.get_item_note(client, section) || "";
  const w = document.createElement("div");
  w.id = "apa-note-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📝 Note — ${escapeHtml(client)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Section: ${escapeHtml(section)} · stored locally only (not written to the .docx)</div>
      </header>
      <div style="padding:18px 20px;">
        <textarea id="an-text" rows="10"
                  placeholder="Notes here are private — only visible in this panel."
                  style="width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px 12px;font:inherit;font-size:13px;outline:none;resize:vertical;">${escapeHtml(current)}</textarea>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="an-clear">✕ Clear</button>
        <span style="flex:1;"></span>
        <button class="btn" id="an-cancel">Cancel</button>
        <button class="btn btn-primary" id="an-save">💾 Save</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#an-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  w.querySelector("#an-clear").addEventListener("click", async () => {
    const res = await pywebview.api.set_item_note(client, section, "");
    if (res?.ok && anchor) anchor.classList.remove("has-text");
    close();
    setStatus("📝 Note cleared", "ok");
  });
  w.querySelector("#an-save").addEventListener("click", async () => {
    const text = w.querySelector("#an-text").value;
    const res = await pywebview.api.set_item_note(client, section, text);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    if (anchor) anchor.classList.toggle("has-text", res.has_text);
    close();
    setStatus("📝 Note saved", "ok");
  });
  w.querySelector("#an-text").focus();
}

// ── Manage sections modal (Tk parity) ─────────────────────────
// ── 🏢 Manage franchises modal (mirrors Tk _open_franchise_manager) ──
// Add / remove franchise tags. Removed franchises don't auto-clear
// existing item tags — those keep pointing at the (now-missing) tag
// until manually re-tagged via the per-item franchise popover. This
// matches Tk's behavior (and is sane: a typo'd tag should be remove-
// able without also nuking every item that referenced it).
async function openManageFranchisesModal() {
  const tags = await pywebview.api.get_franchise_list() || [];
  const usage = await pywebview.api.get_all_franchise_tags() || {};
  const w = document.createElement("div");
  w.id = "apa-fr-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  function rowHtml(tag) {
    const count = usage[tag] || 0;
    return `<li data-tag="${escapeAttr(tag)}"
              style="display:flex;align-items:center;gap:10px;padding:8px 12px;
                     margin-bottom:4px;background:var(--surface);border:1px solid var(--border);border-radius:6px;">
      <span style="flex:1;font-size:13px;font-weight:500;">${escapeHtml(tag)}</span>
      <span class="muted" style="font-size:11px;">${count} item${count !== 1 ? "s" : ""}</span>
      <button class="btn mf-rm" style="font-size:11px;padding:3px 8px;color:var(--red);" title="Remove this franchise tag (items keep their tag until re-tagged)">✕</button>
    </li>`;
  }
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(520px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">🏢 Manage franchises</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
          Local labels (never saved to the .docx). Item counts show how many rows are tagged with each.
        </div>
      </header>
      <div style="padding:14px 18px;overflow-y:auto;max-height:60vh;">
        <ul id="mf-list" style="list-style:none;margin:0;padding:0;">
          ${tags.length ? tags.map(rowHtml).join("")
            : `<li class="muted" style="padding:14px;text-align:center;">No franchises yet — add one below.</li>`}
        </ul>
        <div style="display:flex;gap:6px;margin-top:14px;">
          <input id="mf-new" class="search" type="text"
                 placeholder="+ Add franchise (e.g. SP 10100 Burbank)"
                 style="flex:1;font-size:12px;padding:5px 8px;" />
          <button class="btn btn-primary" id="mf-add">+ Add</button>
        </div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="mf-close">Close</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#mf-close").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  // Local in-memory tag list (mutates with add/remove, persisted on
  // each change). Persisting per-action keeps the modal feeling
  // responsive + survives an accidental close.
  let current = tags.slice();
  function reRender() {
    const ul = w.querySelector("#mf-list");
    if (!current.length) {
      ul.innerHTML = `<li class="muted" style="padding:14px;text-align:center;">No franchises yet — add one below.</li>`;
      return;
    }
    ul.innerHTML = current.map(rowHtml).join("");
    ul.querySelectorAll(".mf-rm").forEach((b) =>
      b.addEventListener("click", async () => {
        const li = b.closest("li[data-tag]");
        const tag = li?.dataset.tag;
        if (!tag) return;
        const inUse = usage[tag] || 0;
        const msg = inUse > 0
          ? `Remove "${tag}"?\n\n${inUse} item${inUse !== 1 ? "s are" : " is"} currently tagged with it — those rows keep the tag until manually re-tagged.`
          : `Remove "${tag}"?`;
        if (!confirm(msg)) return;
        const next = current.filter((t) => t !== tag);
        const r = await pywebview.api.set_franchise_list(next);
        if (!r?.ok) { setStatus(`Remove failed: ${r?.error || "?"}`, "error"); return; }
        current = next;
        reRender();
        setStatus(`🏢 Removed franchise "${tag}"`, "ok");
        attachFranchiseFilter();
      }));
  }
  reRender();
  w.querySelector("#mf-add").addEventListener("click", async () => {
    const v = w.querySelector("#mf-new").value.trim();
    if (!v) return;
    if (current.some((t) => t.toLowerCase() === v.toLowerCase())) {
      setStatus(`"${v}" already in list`, "warn");
      return;
    }
    const next = [...current, v];
    const r = await pywebview.api.set_franchise_list(next);
    if (!r?.ok) { setStatus(`Add failed: ${r?.error || "?"}`, "error"); return; }
    current = next;
    w.querySelector("#mf-new").value = "";
    reRender();
    setStatus(`🏢 Added franchise "${v}"`, "ok");
    attachFranchiseFilter();
  });
  w.querySelector("#mf-new").addEventListener("keydown", (e) => {
    if (e.key === "Enter") w.querySelector("#mf-add").click();
  });
}

async function openManageSectionsModal() {
  const order = await pywebview.api.get_section_order() || [];
  const builtin = new Set(await pywebview.api.builtin_sections() || []);
  const w = document.createElement("div");
  w.id = "apa-mgr-modal";
  w.style.cssText = "position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
  w.innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(560px,92vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
      <header style="padding:16px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
        <div style="font-size:15px;font-weight:600;">📋 Manage sections</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Drag ⋮⋮ to reorder · ✕ removes (built-ins can't be removed)</div>
      </header>
      <div style="padding:18px 20px;overflow-y:auto;max-height:60vh;">
        <ul id="ms-list" style="list-style:none;margin:0;padding:0;">
          ${order.map((s) => `
            <li draggable="true" data-section="${escapeAttr(s)}"
                style="display:flex;align-items:center;gap:10px;padding:8px 10px;margin-bottom:4px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:grab;">
              <span style="color:var(--text-muted);">⋮⋮</span>
              <span style="flex:1;font-size:13px;">${escapeHtml(s)}</span>
              ${builtin.has(s) ? `<span style="font-size:10px;color:var(--text-muted);">built-in</span>` : `<button class="btn ms-rm" style="font-size:11px;padding:3px 8px;">✕</button>`}
            </li>`).join("")}
        </ul>
        <div style="display:flex;gap:6px;margin-top:14px;">
          <input id="ms-new" class="search" type="text" placeholder="+ Add estimator (e.g. VICTORIA)" style="flex:1;font-size:12px;padding:5px 8px;" />
          <button class="btn" id="ms-add">+ Add</button>
        </div>
      </div>
      <footer style="padding:12px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn" id="ms-cancel">Cancel</button>
        <button class="btn btn-primary" id="ms-save">💾 Save order</button>
      </footer>
    </div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.querySelector("#ms-cancel").addEventListener("click", close);
  w.addEventListener("click", (e) => { if (e.target === w) close(); });
  // Drag-reorder list items
  let dragLi = null;
  w.querySelectorAll("li[data-section]").forEach((li) => {
    li.addEventListener("dragstart", () => { dragLi = li; li.style.opacity = "0.4"; });
    li.addEventListener("dragend",   () => { if (dragLi) dragLi.style.opacity = "1"; dragLi = null; });
    li.addEventListener("dragover",  (e) => {
      if (!dragLi || dragLi === li) return;
      e.preventDefault();
      const rect = li.getBoundingClientRect();
      const below = (e.clientY - rect.top) > rect.height / 2;
      if (below) li.parentNode.insertBefore(dragLi, li.nextSibling);
      else       li.parentNode.insertBefore(dragLi, li);
    });
  });
  w.querySelectorAll(".ms-rm").forEach((b) =>
    b.addEventListener("click", () => b.closest("li").remove()));
  w.querySelector("#ms-add").addEventListener("click", () => {
    const v = w.querySelector("#ms-new").value.trim();
    if (!v) return;
    const li = document.createElement("li");
    li.draggable = true;
    li.dataset.section = v;
    li.style.cssText = "display:flex;align-items:center;gap:10px;padding:8px 10px;margin-bottom:4px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:grab;";
    li.innerHTML = `<span style="color:var(--text-muted);">⋮⋮</span><span style="flex:1;font-size:13px;">${escapeHtml(v)}</span><button class="btn ms-rm" style="font-size:11px;padding:3px 8px;">✕</button>`;
    w.querySelector("#ms-list").appendChild(li);
    li.querySelector(".ms-rm").addEventListener("click", () => li.remove());
    li.addEventListener("dragstart", () => { dragLi = li; li.style.opacity = "0.4"; });
    li.addEventListener("dragend",   () => { if (dragLi) dragLi.style.opacity = "1"; dragLi = null; });
    li.addEventListener("dragover",  (e) => {
      if (!dragLi || dragLi === li) return;
      e.preventDefault();
      const rect = li.getBoundingClientRect();
      const below = (e.clientY - rect.top) > rect.height / 2;
      if (below) li.parentNode.insertBefore(dragLi, li.nextSibling);
      else       li.parentNode.insertBefore(dragLi, li);
    });
    w.querySelector("#ms-new").value = "";
  });
  w.querySelector("#ms-save").addEventListener("click", async () => {
    const newOrder = Array.from(w.querySelectorAll("li[data-section]")).map((li) => li.dataset.section);
    const res = await pywebview.api.set_section_order(newOrder);
    if (!res?.ok) { setStatus(`Save failed: ${res?.error || "?"}`, "error"); return; }
    close();
    setStatus(`📋 Section order saved (${res.count})`, "ok");
    await loadDate(state.active_date);
  });
}
