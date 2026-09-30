/* Trello Notifications panel — grouped by board, unread-first, click a
 * row to open the card, mark-read writes back to Trello. */
"use strict";

const $ = (s) => document.querySelector(s);
const state = { groups: [], unreadOnly: false, collapsed: new Set() };

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function setStatus(msg, kind = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.style.color = kind === "error" ? "var(--red)"
    : kind === "ok" ? "var(--green)" : "var(--text-muted)";
}

// "2026-06-25T14:03:00.000Z" → "Jun 25 · 2:03p" (relative-ish, compact).
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .replace(" ", "").toLowerCase().replace(/m$/, "");
  if (sameDay) return "today · " + time;
  const md = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return md + " · " + time;
}

function render() {
  const feed = $("#feed");
  const groups = state.groups;
  const totalUnread = groups.reduce((n, g) => n + g.unread, 0);
  const pill = $("#unread-pill");
  pill.textContent = totalUnread;
  pill.classList.toggle("zero", totalUnread === 0);

  if (!groups.length) {
    feed.innerHTML = `<div class="empty"><span class="big">✓</span>${
      state.unreadOnly ? "No unread notifications." : "No notifications."}</div>`;
    return;
  }

  feed.innerHTML = groups.map((g) => {
    const collapsed = state.collapsed.has(g.board);
    const rows = g.items.map((it) => `
      <li class="notif ${it.unread ? "unread" : "read"}"
          data-id="${esc(it.id)}" data-url="${esc(it.card_url)}">
        <span class="notif-icon" title="${esc(it.type_label)}">${it.icon}</span>
        <div class="notif-body">
          <div class="notif-card"><button type="button" data-open-notification>${esc(it.card_name || it.type_label)}</button></div>
          <div class="notif-meta">${esc(it.type_label)}${it.by ? " · " + esc(it.by) : ""}${it.list ? " · " + esc(it.list) : ""}</div>
          ${it.snippet ? `<div class="notif-snippet">${window.NotificationReader?.markdown(it.snippet)||esc(it.snippet)}</div>` : ""}
        </div>
        <div class="notif-side">
          <span class="notif-date">${esc(fmtDate(it.date))}</span>
          <button class="notif-preview" type="button" data-preview>Read message</button>
          ${it.unread ? `<button class="mark-btn" data-mark="${esc(it.id)}">✓ Mark read</button>` : ""}
        </div>
      </li>`).join("");
    return `
      <section class="board-group ${collapsed ? "collapsed" : ""}" data-board="${esc(g.board)}">
        <div class="board-head" data-toggle="${esc(g.board)}">
          <span class="caret">▾</span>
          <span class="board-name">${esc(g.board)}</span>
          <span class="board-count">${g.unread ? `${g.unread} unread · ` : ""}${g.total} total</span>
        </div>
        <ul class="notif-list">${rows}</ul>
      </section>`;
  }).join("");

  wire();
}

function wire() {
  // Collapse/expand a board group.
  document.querySelectorAll(".board-head[data-toggle]").forEach((el) => {
    el.addEventListener("click", () => {
      const b = el.dataset.toggle;
      if (state.collapsed.has(b)) state.collapsed.delete(b);
      else state.collapsed.add(b);
      // Set isn't JSON-serialisable — store the array.
      PanelState.set({ collapsed: [...state.collapsed] });
      el.closest(".board-group").classList.toggle("collapsed");
    });
  });
  // Exact card/action routing. No customer-name match and no silent fallback.
  document.querySelectorAll(".notif").forEach((row) => {
    const item=state.groups.flatMap(g=>g.items).find(it=>it.id===row.dataset.id);
    async function openJob(){
      if(row.dataset.opening)return false;row.dataset.opening='1';row.setAttribute('aria-busy','true');setStatus('Opening the linked job…');
      try{const result=await pywebview.api.notification_job(item.card_id,item.comment_id||'');
        if(!result?.ok)throw Error(result?.error||'The job link is unavailable.');
        window.parent.postMessage({type:'linguar-open-job',...result},'*');setStatus('');return true;
      }catch(e){setStatus(e.message,'error');window.NotificationReader?.open(item,openJob,e.message);return false;}
      finally{delete row.dataset.opening;row.removeAttribute('aria-busy');}
    }
    row.querySelector('[data-preview]').onclick=()=>window.NotificationReader?.open(item,openJob);
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-mark],[data-preview]")) return;
      if(e.target.closest('a')){e.preventDefault();return;}
      void openJob();
    });
  });
  // Mark one read.
  document.querySelectorAll("[data-mark]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.mark;
      btn.disabled = true; btn.textContent = "…";
      const res = await pywebview.api.mark_read(id, true);
      if (!res?.ok) { btn.disabled = false; btn.textContent = "✓ Mark read"; setStatus("Couldn't mark read", "error"); return; }
      // Update local state without a full refetch.
      for (const g of state.groups) {
        const it = g.items.find((x) => x.id === id);
        if (it) { it.unread = false; g.unread = g.items.filter((x) => x.unread).length; break; }
      }
      render();
      setStatus("Marked read", "ok");
    });
  });
}

let notificationLoad=0;
async function load() {
  const request=++notificationLoad;
  setStatus("Checking notifications…");
  try{
  const res = await pywebview.api.list_notifications(state.unreadOnly, 80);
  if(request!==notificationLoad)return;
  if (!res?.ok) { setStatus(`Load failed: ${res?.error || "?"}`, "error"); return; }
  state.groups = res.groups || [];
  render();
  setStatus(`${res.total} notification${res.total !== 1 ? "s" : ""} · ${res.unread} unread`,
            res.unread ? "" : "ok");
  }catch(e){if(request===notificationLoad)setStatus('Notifications could not refresh. Your previous list is still shown.','error');}
}

window.addEventListener("pywebviewready", async () => {
  await PanelState.init("notifications");
  state.unreadOnly = !!PanelState.get("unreadOnly", false);
  // Stored as an array; the panel works in a Set.
  state.collapsed = new Set(PanelState.get("collapsed", []) || []);
  const _uo = $("#unread-only"); if (_uo) _uo.checked = state.unreadOnly;

  $("#refresh-btn").addEventListener("click", load);
  $("#unread-only").addEventListener("change", (e) => {
    state.unreadOnly = e.target.checked;
    PanelState.set({ unreadOnly: state.unreadOnly });
    load();
  });
  $("#mark-all-btn").addEventListener("click", async () => {
    const btn = $("#mark-all-btn");
    btn.disabled = true; btn.textContent = "Marking…";
    const res = await pywebview.api.mark_all_read();
    btn.disabled = false; btn.textContent = "✓ Mark all read";
    if (!res?.ok) { setStatus("Mark-all failed", "error"); return; }
    setStatus("All marked read", "ok");
    load();
  });
  window.addEventListener('trello-notifications-open', load);
});
