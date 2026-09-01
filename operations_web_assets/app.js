const state={data:null,view:"home",board:"wip",jobFilter:"all",query:"",selectedClient:"",selectedJob:null,jobContext:null,accessKey:""};
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=(v)=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const attr=esc;

document.addEventListener("DOMContentLoaded",()=>{bind();tick();setInterval(tick,30000);boot();});

function bind(){
  $$("[data-view]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));
  $("[data-refresh]").addEventListener("click",()=>boot(true));
  $("[data-go-jobs]").addEventListener("click",()=>showView("jobs"));
  $("[data-go-dispatch]").addEventListener("click",()=>showView("dispatch"));
  $("[data-job-filter]").addEventListener("change",e=>{state.jobFilter=e.target.value;renderJobs();});
  $(".global-search input").addEventListener("input",e=>{state.query=e.target.value.trim().toLowerCase();if(state.view==="clients")renderClientList();else{showView("jobs");renderJobs();}});
  $("[data-client-search]").addEventListener("input",e=>{state.query=e.target.value.trim().toLowerCase();renderClientList();});
  $$("[data-filter-job]").forEach(b=>b.addEventListener("click",()=>{state.jobFilter=b.dataset.filterJob;showView("jobs");renderJobs();}));
  $("[data-job-drawer]").addEventListener("click",e=>{if(e.target.closest("[data-drawer-close]"))closeDrawer();});
  $("[data-tools-toggle]").addEventListener("click",e=>{e.stopPropagation();toggleTools();});
  $$('[data-tool]').forEach(button=>button.addEventListener("click",()=>launchTool(button.dataset.tool,button)));
  document.addEventListener("click",e=>{if(!e.target.closest(".tools-anchor"))closeTools();});
  document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$(".global-search input").focus();}if(e.key==="Escape"){closeTools();closeDrawer();}});
  $(".new-loss").addEventListener("click",e=>launchTool("new_job",e.currentTarget));
  const queryKey=new URLSearchParams(location.search).get("key")||sessionStorage.getItem("operations-key")||"";
  if(queryKey){state.accessKey=queryKey;sessionStorage.setItem("operations-key",queryKey);}
}

async function transport(method,...args){
  if(window.pywebview?.api?.[method])return window.pywebview.api[method](...args);
  if(!["bootstrap","client_account","job_context"].includes(method))return {ok:false,error:"This action is available in the desktop app."};
  const headers=state.accessKey?{"X-Operations-Key":state.accessKey}:{};
  let url=method==="bootstrap"?`/api/bootstrap?force=${args[0]?1:0}`:method==="job_context"?`/api/job?client=${encodeURIComponent(args[0]||"")}&card_id=${encodeURIComponent(args[1]||"")}&division=${encodeURIComponent(args[2]||"EMS")}`:`/api/client?name=${encodeURIComponent(args[0]||"")}`;
  const response=await fetch(url,{headers});
  if(response.status===401&&!state.accessKey){const key=prompt("Enter the Operations Hub access key");if(key){state.accessKey=key;sessionStorage.setItem("operations-key",key);return transport(method,...args);}}
  return response.json();
}

async function boot(force=false){
  const button=$("[data-refresh]");button.disabled=true;button.textContent="↻";setStatus(force?"Refreshing live operations…":"Loading the operating picture…");
  try{
    const data=await transport("bootstrap",force);
    if(!data?.ok)throw new Error(data?.error||data?.warnings?.join(" · ")||"Operations data unavailable");
    state.data=data;renderAll();
    $(".connection-dot").classList.add("ok");$("[data-connection]").textContent=data.source==="trello"?"Trello connected":"Shared data connected";
    setStatus((data.warnings||[]).join(" · ")||`${data.overview.active_jobs} live jobs loaded`);
    $("[data-load-time]").textContent=`${data.load_ms||0} ms${data.cached?" · cached":""}`;
  }catch(error){setStatus(String(error),true);$("[data-connection]").textContent="Needs attention";toast(`Operations data could not load: ${error}`);}
  finally{button.disabled=false;}
}

function renderAll(){renderSignals();renderHome();renderBoardTabs();renderJobs();renderDispatch();renderClientList();renderReports();}
function renderSignals(){
  const d=state.data, o=d.overview;
  ["EMS","CONTENTS","RECON"].forEach(x=>$( `[data-signal="${x}"]`).textContent=o.divisions[x]||0);
  $$('[data-metric]').forEach(el=>el.textContent=o[el.dataset.metric]??0);
  $("[data-job-count]").textContent=o.active_jobs;$("[data-updated]").textContent=`Updated ${fmtTime(d.generated_at)} · ${d.source}`;$("[data-source]").textContent=`${o.active_jobs} active · ${o.clients} clients`;
}

function renderHome(){
  const d=state.data,o=d.overview;
  const priority=d.jobs.filter(j=>j.overdue||j.stall==="bad"||j.stall==="warn").sort((a,b)=>Number(b.overdue)-Number(a.overdue)||b.days_in_lane-a.days_in_lane).slice(0,7);
  $("[data-priority-feed]").innerHTML=priority.length?priority.map(j=>`<div class="priority-row" data-open-job="${attr(j.card_id)}"><i></i><div><strong>${esc(j.client)}</strong><small>${esc(j.board)} · ${esc(j.lane)}</small></div><b>${j.overdue?"OVERDUE":j.days_in_lane+"D"}</b></div>`).join(""):`<div class="dispatch-empty">No jobs currently need escalation.</div>`;
  wireJobs($("[data-priority-feed]"));
  const today=d.dispatch.days[0]?.jobs||[];$("[data-today-scheduled]").textContent=today.length;$("[data-unscheduled]").textContent=d.dispatch.unscheduled_count;$("[data-today]").textContent=new Date().toLocaleDateString([], {month:"short",day:"numeric"});
  $("[data-day-meter]").style.width=`${Math.min(100,Math.round(today.length/Math.max(1,today.length+d.dispatch.unscheduled_count)*100))}%`;
  const top=d.reports.lane_counts.slice(0,8), max=Math.max(1,...top.map(x=>x.value));
  $("[data-lane-summary]").innerHTML=top.map(x=>`<div class="lane-summary-card"><strong>${x.value}</strong><span>${esc(x.label)}</span><small>${Math.round(x.value/max*100)}% of busiest lane</small></div>`).join("");
}

function renderBoardTabs(){
  const boards=state.data.boards.filter(b=>b.key!=="logs");if(!boards.some(b=>b.key===state.board))state.board=boards[0]?.key||"";
  $("[data-board-tabs]").innerHTML=boards.map(b=>`<button class="${b.key===state.board?"active":""}" data-board-tab="${attr(b.key)}">${esc(shortBoard(b.name))}</button>`).join("");
  $$('[data-board-tab]').forEach(b=>b.addEventListener("click",()=>{state.board=b.dataset.boardTab;renderBoardTabs();renderJobs();}));
}

function renderJobs(){
  if(!state.data)return;const board=state.data.boards.find(b=>b.key===state.board);const host=$("[data-jobs-board]");if(!board){host.innerHTML="<div class='dispatch-empty'>No board available.</div>";return;}
  host.innerHTML=(board.lanes||[]).map(l=>{let cards=(l.cards||[]).filter(jobMatches);return `<section class="job-lane"><header><strong>${esc(l.name)}</strong><b>${cards.length}</b><span>•••</span></header><div class="job-cards">${cards.map(c=>jobCard(c,board.key)).join("")||"<div class='dispatch-empty'>No matching jobs</div>"}</div></section>`}).join("");wireJobs(host);
}
function jobMatches(j){const q=state.query, matchQ=!q||`${j.client} ${(j.loss_types||[]).join(" ")}`.toLowerCase().includes(q);const f=state.jobFilter;return matchQ&&(f==="all"||f==="attention"&&(j.overdue||j.stall==="warn"||j.stall==="bad")||f==="overdue"&&j.overdue||f==="stalled"&&(j.stall==="warn"||j.stall==="bad")||f==="today"&&j.due===todayIso());}
function jobCard(j,boardKey=j.board_key){const division=boardKey==="contents"?"CONTENTS":"EMS";return `<article class="job-card ${j.overdue||j.stall==="bad"?"attention":""}" data-open-job="${attr(j.card_id)}"><strong>${esc(j.client)}</strong><div class="job-card-meta"><span class="pill ${division.toLowerCase()}">${division}</span>${j.overdue?"<span class='pill overdue'>Overdue</span>":""}${j.days_in_lane?`<span class="pill stall">${j.days_in_lane}d in lane</span>`:""}${(j.loss_types||[]).slice(0,1).map(x=>`<span class="pill">${esc(x)}</span>`).join("")}</div></article>`;}

function renderDispatch(){const d=state.data.dispatch;$("[data-dispatch-grid]").innerHTML=d.days.map((day,i)=>`<section class="dispatch-day ${i===0?"today":""}"><header><strong>${esc(day.label)}</strong><small>${fmtDate(day.date)}</small></header><div class="dispatch-day-list">${day.jobs.map(j=>`<div class="dispatch-job ${j.division==="CONTENTS"?"contents":""}" data-open-job="${attr(j.card_id)}"><strong>${esc(j.client)}</strong><small>${esc(j.lane)}</small></div>`).join("")||"<div class='dispatch-empty'>Open capacity</div>"}</div></section>`).join("");$("[data-unscheduled-count]").textContent=d.unscheduled_count;$("[data-unscheduled-list]").innerHTML=d.unscheduled.slice(0,20).map(j=>jobCard(j,j.board_key)).join("");wireJobs($("[data-panel='dispatch']"));}

function renderClientList(){if(!state.data)return;const q=state.query;const rows=state.data.clients.filter(c=>!q||c.name.toLowerCase().includes(q)).slice(0,300);$("[data-client-list]").innerHTML=rows.map(c=>`<button class="client-row ${state.selectedClient===c.name?"active":""}" data-client="${attr(c.name)}"><span class="client-initial">${esc(initials(c.name))}</span><div><strong>${esc(c.name)}</strong><small>${c.job_count||0} job${c.job_count===1?"":"s"} · ${(c.divisions||[]).map(shortDivision).join(" · ")||"Unclassified"}</small></div></button>`).join("")||"<div class='dispatch-empty'>No clients found.</div>";$$('[data-client]').forEach(b=>b.addEventListener("click",()=>openClient(b.dataset.client)));}
async function openClient(name){state.selectedClient=name;renderClientList();const host=$("[data-client-record]");host.innerHTML="<div class='empty-record'><span>◌</span><h2>Opening client…</h2></div>";try{const r=await transport("client_account",name);if(!r?.ok)throw new Error(r?.error||"Client unavailable");host.innerHTML=clientRecord(r);$$('[data-open-folder]',host).forEach(b=>b.addEventListener("click",()=>desktopAction("open_folder",b.dataset.openFolder)));}catch(e){host.innerHTML=`<div class="empty-record"><span>!</span><h2>Client could not open</h2><p>${esc(e)}</p></div>`;}}
function clientRecord(r){return `<header class="record-head"><span class="record-monogram">${esc(initials(r.client||r.display_name))}</span><div class="record-head-copy"><h2>${esc(r.display_name||r.client)}</h2><p>${r.job_count||0} claims/jobs · ${(r.divisions||[]).map(shortDivision).join(" · ")||"Division details below"}</p></div><div class="record-actions">${r.folder?`<button class="quiet-button" data-open-folder="${attr(r.folder)}">Open folder</button>`:""}<button class="primary-action">Add job</button></div></header><div class="record-jobs">${(r.jobs||[]).map(j=>`<article class="claim-card"><header><div><h3>${esc(j.name)}</h3><small>${esc(j.kind||"Job")}${j.date_received?` · Received ${esc(j.date_received)}`:""}</small></div><span class="division-badges">${(j.divisions||[]).map(d=>`<b class="${d==="CONTENTS"?"contents":""}">${esc(shortDivision(d))}</b>`).join("")}</span></header><div class="claim-facts">${fact("Claim",j.claim_number)}${fact("Carrier",j.carrier)}${fact("Loss date",j.date_of_loss)}${fact("Status",j.status||"Recorded")}</div></article>`).join("")||"<div class='dispatch-empty'>No claim folders found for this client.</div>"}</div>`;}
function fact(label,value){return `<div><small>${esc(label)}</small><strong>${esc(value||"—")}</strong></div>`;}

function renderReports(){const r=state.data.reports;renderBars($("[data-division-chart]"),Object.entries(r.division_counts).map(([label,value])=>({label,value})),true);renderBars($("[data-age-chart]"),r.age_bands);$("[data-lane-report]").innerHTML=r.lane_counts.slice(0,12).map((x,i)=>`<div class="rank-row"><span>${String(i+1).padStart(2,"0")}</span><strong>${esc(x.label)}</strong><b>${x.value}</b></div>`).join("");}
function renderBars(host,rows,division=false){const max=Math.max(1,...rows.map(x=>x.value));host.innerHTML=rows.map(x=>`<div class="bar-row ${division?x.label.toLowerCase():""}"><span>${esc(shortDivision(x.label))}</span><i><b style="width:${Math.round(x.value/max*100)}%"></b></i><strong>${x.value}</strong></div>`).join("");}

function showView(view){state.view=view;$$('[data-view]').forEach(b=>b.classList.toggle("active",b.dataset.view===view));$$('[data-panel]').forEach(p=>p.classList.toggle("active",p.dataset.panel===view));const titles={home:["Front office · Live operations","Operations"],jobs:["Claims in motion","Jobs"],dispatch:["Field capacity · Seven days","Dispatch"],clients:["Account → Property → Claim","Clients"],reports:["Cycle time · Responsibility · Throughput","Reports"]};$("[data-eyebrow]").textContent=titles[view][0];$("[data-title]").textContent=titles[view][1];}
function wireJobs(root){$$('[data-open-job]',root).forEach(el=>el.addEventListener("click",()=>openJob(el.dataset.openJob)));}
function openJob(id){const job=state.data.jobs.find(j=>j.card_id===id);if(!job)return;state.selectedJob=job;state.jobContext=null;renderJobDrawer(job);loadJobContext(job);}
function renderJobDrawer(job,context=state.jobContext){
  const drawer=$("[data-job-drawer]"),progress=context?.progress||{},counts=progress.counts||{},fields=context?.fields||[];
  const copyFields=fields.length?fields:[{id:"job_name",label:"Job name",value:job.client}];
  const copyRows=copyFields.slice(0,18).map(field=>`<button data-copy-value="${attr(field.value)}"><span>${esc(field.label)}</span><small>${esc(field.value)}</small></button>`).join("");
  const loadState=context?`${context.load_ms||0} ms`:`Loading saved Job Info…`;
  drawer.innerHTML=`
    <header class="drawer-head">
      <div><small class="drawer-kicker">${esc(job.division)} · ${esc(job.board)}</small><h2>${esc(job.client)}</h2><div class="drawer-meta">${esc(job.lane)} · ${job.days_in_lane} day(s) in lane</div></div>
      <div class="drawer-head-actions"><button class="client-link" data-client-page>Client page</button><button class="drawer-close" data-drawer-close aria-label="Close">×</button></div>
    </header>
    <div class="job-action-bar" aria-label="Job actions">
      <div class="action-cluster action-primary">
        <button class="job-action primary" data-add-update><i>＋</i>Add update</button>
        <details class="copy-menu"><summary class="job-action"><i>▣</i>Copy <span>⌄</span></summary><div class="copy-panel"><header><strong>Copy job details</strong><small>Uses the saved Job Info record</small></header>${copyRows}<button data-copy-summary><span>Job summary</span><small>All available details</small></button></div></details>
        <button class="job-action" data-job-action="photo_report"><i>▧</i>Photo report</button>
      </div>
      <div class="action-cluster action-destinations" aria-label="Open job in">
        <button class="job-action" data-job-action="folder"><i>▰</i>${context?.path?"Folder":"Find folder"}</button>
        ${job.url?`<button class="job-action destination" data-trello><i class="trello-mark">T</i>Trello</button>`:""}
        <button class="job-action destination" data-job-action="xa"><i class="xa-mark">XA</i>XA</button>
        <button class="job-action destination" data-job-action="companycam"><i class="cc-mark">C</i>CompanyCam</button>
      </div>
    </div>
    <section class="update-composer" data-update-composer hidden></section>
    <div class="drawer-scroll">
      <section class="drawer-section"><div class="drawer-section-title"><h3>Operating status</h3><small>${esc(loadState)}</small></div><div class="drawer-facts">${fact("Division",job.division)}${fact("Current lane",job.lane)}${fact("Due",job.due?fmtDate(job.due):"Not scheduled")}${fact("Last activity",job.last_activity_at?fmtDate(job.last_activity_at):"—")}</div></section>
      ${context?renderProgress(progress,counts):`<section class="drawer-section context-loading"><i></i><div><strong>Loading job workspace</strong><small>Board details are ready; saved Job Info and requirements are loading.</small></div></section>`}
      ${context?renderJobInfo(fields):""}
      ${context?renderJobLog(context.job_log||[]):""}
    </div>`;
  drawer.hidden=false;
  $("[data-client-page]",drawer).addEventListener("click",()=>{closeDrawer();showView("clients");openClient(job.client);});
  $("[data-trello]",drawer)?.addEventListener("click",()=>desktopAction("open_url",context?.trello_url||job.url));
  $$('[data-job-action]',drawer).forEach(button=>button.addEventListener("click",()=>runJobAction(button.dataset.jobAction,button)));
  $("[data-add-update]",drawer).addEventListener("click",()=>showUpdateComposer(job));
  $$('[data-copy-value]',drawer).forEach(button=>button.addEventListener("click",()=>copyValue(button.dataset.copyValue,button)));
  $("[data-copy-summary]",drawer)?.addEventListener("click",()=>copyValue(copyFields.map(field=>`${field.label}: ${field.value}`).join("\n"),$("[data-copy-summary]",drawer)));
}
function renderProgress(progress,counts){const total=(progress.items||[]).filter(item=>["mandatory","required"].includes(item.importance)).length;return `<section class="drawer-section"><div class="drawer-section-title"><h3>Requirements</h3><strong>${progress.percent_complete??0}%</strong></div><div class="progress-track"><i style="width:${Math.max(0,Math.min(100,progress.percent_complete||0))}%"></i></div><div class="progress-meta"><span>${counts.todo||0} to do</span><span>${counts.blocked||0} blocked</span><span>${total} required</span></div></section>`;}
function renderJobInfo(fields){return `<section class="drawer-section"><div class="drawer-section-title"><h3>Job Info</h3><small>${fields.length?`${fields.length} saved details`:"No saved details yet"}</small></div>${fields.length?`<div class="job-info-grid">${fields.slice(0,12).map(field=>fact(field.label,field.value)).join("")}</div>`:`<p class="muted">Job Info has not been filled out for this job.</p>`}</section>`;}
function renderJobLog(entries){return `<section class="drawer-section"><div class="drawer-section-title"><h3>Recent job log</h3><small>${entries.length} update${entries.length===1?"":"s"}</small></div><div class="job-log-preview">${entries.slice(0,4).map(entry=>`<article><header><strong>${esc(entry.work_type||"Job update")}</strong><time>${fmtDate(entry.work_date||entry.created_at)}</time></header><p>${esc(entry.note||entry.status||"Saved update")}</p></article>`).join("")||`<p class="muted">No job-log updates yet. Add the first update above.</p>`}</div></section>`;}
async function loadJobContext(job){try{const result=await transport("job_context",job.client,job.card_id,job.division);if(state.selectedJob?.card_id!==job.card_id)return;if(!result?.ok)throw new Error(result?.error||"Job workspace unavailable");state.jobContext=result;renderJobDrawer(job,result);}catch(error){if(state.selectedJob?.card_id===job.card_id){state.jobContext={fields:[],job_log:[],progress:{},error:String(error)};renderJobDrawer(job,state.jobContext);toast(`Job details: ${error}`);}}}
function showUpdateComposer(job){const host=$("[data-update-composer]");if(!host)return;const today=todayIso();host.hidden=false;host.innerHTML=`<div class="composer-grid"><label>Date<input type="date" data-update-field="work_date" value="${today}"></label><label>Activity<select data-update-field="work_type">${["Initial inspection","Demo","Monitor","Equipment placed","Equipment pickup","Contents","Recon","Final inspection","Other"].map(value=>`<option>${value}</option>`).join("")}</select></label><label>Status<select data-update-field="status">${["completed","scheduled","rescheduled","cancelled","skipped","needs_review"].map(value=>`<option value="${value}">${value.replaceAll("_"," ")}</option>`).join("")}</select></label><label>Crew<input data-update-field="technicians" placeholder="Technician or crew"></label><label class="wide">Work completed / next step<textarea rows="3" data-update-field="note" placeholder="What happened, what was completed, and what comes next"></textarea></label></div><div class="composer-actions"><button class="primary-action" data-save-update>Save update</button><button class="quiet-button" data-cancel-update>Cancel</button><span data-update-status></span></div>`;host.scrollIntoView({behavior:"smooth",block:"nearest"});$("[data-cancel-update]",host).addEventListener("click",()=>{host.hidden=true;});$("[data-save-update]",host).addEventListener("click",()=>saveUpdate(job,host));}
async function saveUpdate(job,host){const button=$("[data-save-update]",host),status=$("[data-update-status]",host),entry={source:"pc"};$$('[data-update-field]',host).forEach(field=>entry[field.dataset.updateField]=field.value);button.disabled=true;button.textContent="Saving…";const result=await transport("save_job_update",job.client,entry);if(!result?.ok){button.disabled=false;button.textContent="Save update";status.textContent=result?.error||"Could not save";return;}status.textContent="Saved";state.jobContext=await transport("job_context",job.client,job.card_id,job.division);renderJobDrawer(job,state.jobContext);toast("Job Log updated");}
async function runJobAction(action,button){const job={...state.selectedJob,...(state.jobContext||{})};if(!window.pywebview?.api?.job_action){toast("This action is available in the desktop app.");return;}const label=button.innerHTML;button.disabled=true;button.textContent="Opening…";try{const result=await transport("job_action",action,job);if(!result?.ok)throw new Error(result?.error||"Action unavailable");toast(action==="photo_report"?"CompanyCam report workspace opened":"Opened");}catch(error){toast(String(error));}finally{button.disabled=false;button.innerHTML=label;}}
async function copyValue(value,button){if(!value)return;let ok=false;if(window.pywebview?.api?.copy_text){const result=await transport("copy_text",value);ok=Boolean(result?.ok);}else{try{await navigator.clipboard.writeText(value);ok=true;}catch(_){}}toast(ok?"Copied":"Could not copy");button.closest("details")?.removeAttribute("open");}
function closeDrawer(){state.selectedJob=null;state.jobContext=null;$("[data-job-drawer]").hidden=true;}
function toggleTools(){const menu=$("[data-tools-menu]"),willOpen=menu.hidden;menu.hidden=!willOpen;$("[data-tools-toggle]").setAttribute("aria-expanded",String(willOpen));}
function closeTools(){$("[data-tools-menu]").hidden=true;$("[data-tools-toggle]").setAttribute("aria-expanded","false");}
async function launchTool(tool,button){closeTools();if(!window.pywebview?.api?.launch_tool){toast("Office tools open from the desktop app.");return;}const label=button.innerHTML;button.disabled=true;try{const result=await transport("launch_tool",tool);if(!result?.ok)throw new Error(result?.error||"Tool could not open");toast("Tool opened in its own window");}catch(error){toast(String(error));}finally{button.disabled=false;button.innerHTML=label;}}
async function desktopAction(method,arg){if(window.pywebview?.api?.[method])return window.pywebview.api[method](arg);if(method==="open_url")window.open(arg,"_blank","noopener");else toast("Folder access is available in the desktop app.");}
function tick(){$("[data-clock]").textContent=new Date().toLocaleTimeString([],{hour:"numeric",minute:"2-digit"});}
function setStatus(text,error=false){$("[data-status]").textContent=text;$("[data-status]").style.color=error?"var(--danger)":"";}
function toast(text){const el=$("[data-toast]");el.textContent=text;el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,3500);}
function fmtDate(v){if(!v)return"—";const d=new Date(`${String(v).slice(0,10)}T12:00:00`);return Number.isNaN(+d)?String(v):d.toLocaleDateString([],{month:"short",day:"numeric",year:"2-digit"});}
function fmtTime(v){const d=new Date(v);return Number.isNaN(+d)?"now":d.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"});}
function todayIso(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;}
function initials(v){return String(v||"?").split(/[\s,()-]+/).filter(Boolean).slice(0,2).map(x=>x[0]).join("").toUpperCase();}
function shortBoard(v){return String(v||"").replace("WORK IN PROGRESS","Work in progress").replace("ESTIMATING","Estimating").replace("CONTENTS","Contents");}
function shortDivision(v){return v==="CONTENTS"?"Contents":v==="RECON"?"Recon":"EMS";}
