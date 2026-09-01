"use strict";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let data = null, active = "all";

window.addEventListener("pywebviewready", load, {once:true});
async function load(){
  try { data = await pywebview.api.inventory(); renderTabs(); renderRules(); }
  catch(e){ document.querySelector("#rules").innerHTML = `<div class="empty error">Could not load automations: ${esc(e)}</div>`; }
}
function renderTabs(){
  const cats = [{id:"all",label:"All",count:data.rules.length}, ...Object.entries(data.catalog.categories).map(([id,label])=>({id,label,count:data.counts[id]||0}))];
  document.querySelector("#tabs").innerHTML = cats.map(x=>`<button class="tab ${active===x.id?'active':''}" data-id="${x.id}">${esc(x.label)} <span>${x.count}</span></button>`).join("");
  document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{active=b.dataset.id;renderTabs();renderRules();}));
}
function actionText(action){ return `${data.catalog.actions[action.type] || action.type}${action.value ? ` · ${String(action.value).replaceAll("_"," ")}` : ""}`; }
function renderRules(){
  const rows=data.rules.filter(r=>active==="all"||r.category===active);
  document.querySelector("#rules").innerHTML=rows.map(r=>`<article class="rule-card">
    <div class="rule-state"><span class="state-dot"></span><span>Draft</span></div>
    <div class="rule-body"><div class="rule-title"><h2>${esc(r.name)}</h2><span class="type">${esc(r.category_label)}</span></div>
      <p>${esc(summaryFor(r))}</p><div class="flow"><span class="trigger">When · ${esc(r.trigger_label)}</span><b>→</b>${r.actions.map(a=>`<span>${esc(actionText(a))}</span>`).join("")}</div></div>
    <button class="more" title="Editing arrives after Trello review" disabled>Review</button>
  </article>`).join("") || '<div class="empty">No automation drafts in this category.</div>';
}
function summaryFor(r){
  const starter = {
    "Prepare the next stage requirements":"When a job changes stage, add that stage’s requirements and carry unfinished work forward.",
    "Flag overdue assigned work":"Notify the assigned person first, then escalate after the configured delay.",
    "Request division closeout":"Users request closeout; an admin confirms Closeout or Closed.",
    "Daily stalled-job review":"Create one weekday review of active jobs with no recent progress.",
    "Mirror reviewed changes to Trello":"Mirror approved Linguar changes while Trello remains connected."
  }; return starter[r.name] || `${r.trigger_label} automation in review.`;
}
