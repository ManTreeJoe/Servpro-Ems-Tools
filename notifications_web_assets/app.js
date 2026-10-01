/* Trello Notifications panel — grouped by board, unread-first, click a
 * row to open the card, mark-read writes back to Trello. */
"use strict";

const $ = (s) => document.querySelector(s);
const state = { groups: [], unreadOnly: false, activeBoard: null };

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
  window.parent.postMessage({type:'oneloss-notifications-changed'},'*');
  const feed = $("#feed");
  const groups = state.groups.map(g => {
    const items = state.unreadOnly ? g.items.filter(it => it.unread) : g.items;
    return {...g, items, total:items.length, unread:items.filter(it => it.unread).length};
  });
  const totalUnread = groups.reduce((n, g) => n + g.unread, 0);
  const pill = $("#unread-pill");
  pill.textContent = totalUnread;
  pill.classList.toggle("zero", totalUnread === 0);
  let tabs = $('#notification-board-tabs');
  if (!tabs) { tabs = document.createElement('div'); tabs.id='notification-board-tabs'; feed.before(tabs); }
  tabs.setAttribute('role','tablist'); tabs.setAttribute('aria-label','Notification boards');
  if (!groups.some(g => g.board === state.activeBoard)) state.activeBoard = groups[0]?.board ?? null;
  const scrollLeft = tabs.scrollLeft;
  tabs.innerHTML = groups.map((g,index) => `<button type="button" role="tab" id="notification-board-${index}" aria-controls="feed" aria-selected="${g.board === state.activeBoard}" tabindex="${g.board === state.activeBoard ? '0' : '-1'}" data-notification-board="${esc(g.board)}" title="${esc(g.board)} · ${g.unread} unread · ${g.total} shown">${esc(g.board)}<span aria-label="${g.unread} unread">${g.unread}</span></button>`).join('');
  tabs.hidden = !groups.length; tabs.scrollLeft = scrollLeft;
  const selectBoard = button => {
    state.activeBoard = button.dataset.notificationBoard;
    window.PanelState?.set({activeBoard:state.activeBoard});
    render(); feed.scrollTop=0;
    const selected=tabs.querySelector('[aria-selected="true"]');
    selected?.focus({preventScroll:true}); selected?.scrollIntoView({block:'nearest',inline:'nearest'});
  };
  tabs.querySelectorAll('button').forEach(button => {
    button.onclick=()=>selectBoard(button);
    button.onkeydown=event=>{
      const buttons=[...tabs.querySelectorAll('button')],index=buttons.indexOf(button);
      const next=event.key==='ArrowRight'?(index+1)%buttons.length:event.key==='ArrowLeft'?(index+buttons.length-1)%buttons.length:event.key==='Home'?0:event.key==='End'?buttons.length-1:null;
      if(next!==null){event.preventDefault();selectBoard(buttons[next]);}
    };
  });
  feed.setAttribute('role','tabpanel'); feed.tabIndex=0;
  const selectedIndex=groups.findIndex(g=>g.board===state.activeBoard);
  if(selectedIndex>=0)feed.setAttribute('aria-labelledby',`notification-board-${selectedIndex}`);
  else feed.removeAttribute('aria-labelledby');

  if (!groups.length) {
    feed.innerHTML = `<div class="empty"><span class="big">✓</span>${
      state.unreadOnly ? "No unread notifications." : "No notifications."}</div>`;
    return;
  }

  feed.innerHTML = groups.filter(g=>g.board===state.activeBoard).map((g) => {
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
      <section class="board-group" data-board="${esc(g.board)}">
        ${g.items.length ? `<ul class="notif-list">${rows}</ul>` : '<div class="empty">No unread notifications for this board.</div>'}
      </section>`;
  }).join("");

  wire();
}

const pendingReads = new Map();
async function readNotification(item) {
  if (!item?.unread) return true;
  if (pendingReads.has(item.id)) return pendingReads.get(item.id);
  const task = (async () => {
    try {
      const result = await pywebview.api.mark_read(item.id, true);
      if (!result?.ok) throw Error(result?.error || 'Opened, but read status could not be saved.');
      for (const group of state.groups) {
        group.items.forEach(it => { if (it.id === item.id) it.unread = false; });
        group.unread = group.items.filter(it => it.unread).length;
      }
      item.unread = false;
      render();
      return true;
    } catch (error) { setStatus(error.message || 'Read status could not be saved.', 'error'); return false; }
  })();
  pendingReads.set(item.id, task);
  try { return await task; } finally { pendingReads.delete(item.id); }
}

function wire() {
  // Exact card/action routing. No customer-name match and no silent fallback.
  document.querySelectorAll(".notif").forEach((row) => {
    const item=state.groups.flatMap(g=>g.items).find(it=>it.id===row.dataset.id);
    async function openJob(){
      if(row.dataset.opening)return false;row.dataset.opening='1';row.setAttribute('aria-busy','true');setStatus('Opening the linked job…');
      try{const result=await pywebview.api.notification_job(item.card_id,item.comment_id||'');
        if(!result?.ok)throw Error(result?.error||'The job link is unavailable.');
        window.parent.postMessage({type:'linguar-open-job',...result},'*');setStatus('');await readNotification(item);return true;
      }catch(e){setStatus(e.message,'error');window.NotificationReader?.open(item,openJob,e.message);return false;}
      finally{delete row.dataset.opening;row.removeAttribute('aria-busy');}
    }
    row.querySelector('[data-preview]').onclick=()=>{
      if (!window.NotificationReader) return;
      window.NotificationReader.open(item,openJob);
      void readNotification(item);
    };
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
      const item = state.groups.flatMap(g => g.items).find(it => it.id === id);
      if (await readNotification(item)) setStatus("Marked read", "ok");
      else { btn.disabled = false; btn.textContent = "✓ Mark read"; }
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
  state.activeBoard = PanelState.get('activeBoard', null);
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
    try {
      const res = await pywebview.api.mark_all_read();
      if (!res?.ok) { setStatus(res?.error || "Read status was not confirmed. Refresh before retrying.", "error"); return; }
      for (const group of state.groups) { group.items.forEach(item => { item.unread = false; }); group.unread = 0; }
      render();
      setStatus("All marked read", "ok");
    } catch (_) {
      setStatus("The app could not confirm the change. Refresh notifications before retrying.", "error");
    } finally { btn.disabled = false; btn.textContent = "✓ Mark all read"; }
  });
  window.addEventListener('trello-notifications-open', load);
});
