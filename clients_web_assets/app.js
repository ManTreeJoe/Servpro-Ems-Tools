"use strict";

const state = { clients: [], selected: "", division: "all", query: "", request: 0 };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

window.addEventListener("pywebviewready", async () => {
  $("#search").addEventListener("input", debounce(() => {
    state.query = $("#search").value.trim();
    loadClients();
  }, 180));
  $("#refresh").addEventListener("click", loadClients);
  document.querySelectorAll("[data-division]").forEach((button) => button.addEventListener("click", () => {
    state.division = button.dataset.division || "all";
    document.querySelectorAll("[data-division]").forEach((item) => item.classList.toggle("active", item === button));
    loadClients();
  }));
  const focus = window.emsDeepLinkFocus ? window.emsDeepLinkFocus() : "";
  if (focus) { state.query = focus; $("#search").value = focus; }
  await loadClients(focus);
});

async function loadClients(preferred = "") {
  const request = ++state.request;
  $("#client-list").innerHTML = `<div class="loading-card"><span class="spinner"></span>Loading clients…</div>`;
  let result;
  try { result = await withTimeout(pywebview.api.list_clients(state.query, state.division, 300), 8000); }
  catch (error) { result = {ok:false, error:String(error), clients:[]}; }
  if (request !== state.request) return;
  state.clients = result?.clients || [];
  $("#result-count").textContent = `${state.clients.length} client${state.clients.length === 1 ? "" : "s"}`;
  if (!result?.ok) {
    $("#client-list").innerHTML = `<div class="error-card"><strong>Clients could not be loaded</strong><span>${escapeHtml(result?.error || "Check the shared job-folder connection.")}</span><button class="btn" data-retry-clients>Retry</button></div>`;
    $("#client-list").querySelector("[data-retry-clients]")?.addEventListener("click", () => loadClients(preferred));
    return;
  }
  renderDirectory();
  const target = preferred || state.selected || state.clients[0]?.name || "";
  const match = state.clients.find((item) => item.name.toLowerCase() === target.toLowerCase()) || state.clients[0];
  if (match) openClient(match.name);
  else $("#account").innerHTML = `<div class="account-empty"><div class="empty-mark">0</div><h2>No clients found</h2><p>Try another name or division.</p></div>`;
}

function withTimeout(promise, milliseconds) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("The client directory took too long to respond. Try again.")), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function renderDirectory() {
  $("#client-list").innerHTML = state.clients.map((client) => `
    <button class="client-row ${client.name === state.selected ? "active" : ""}" data-client="${escapeHtml(client.name)}">
      <span class="client-monogram">${escapeHtml(initials(client.name))}</span>
      <span class="client-row-copy"><strong>${escapeHtml(client.name)}</strong><small>${client.job_count || 0} job${client.job_count === 1 ? "" : "s"}</small></span>
      <span class="mini-divisions">${(client.divisions || []).map((division) => `<i class="${division.toLowerCase()}">${division === "CONTENTS" ? "C" : division === "RECON" ? "R" : "E"}</i>`).join("")}</span>
    </button>`).join("") || `<div class="loading-card">No matching clients.</div>`;
  document.querySelectorAll("[data-client]").forEach((button) => button.addEventListener("click", () => openClient(button.dataset.client)));
}

async function openClient(name) {
  state.selected = name;
  renderDirectory();
  const request = ++state.request;
  $("#account").innerHTML = `<div class="account-loading"><span class="spinner"></span><strong>Opening client…</strong></div>`;
  let result;
  try { result = await pywebview.api.client_account(name); }
  catch (error) { result = {ok:false, error:String(error)}; }
  if (request !== state.request || state.selected !== name) return;
  if (!result?.ok) {
    $("#account").innerHTML = `<div class="account-empty"><div class="empty-mark">!</div><h2>Client unavailable</h2><p>${escapeHtml(result?.error || "The client could not be opened.")}</p></div>`;
    return;
  }
  renderAccount(result);
}

function renderAccount(result) {
  const client = result.client || {};
  const jobs = result.jobs || [];
  const clientLog = result.job_log || [];
  $("#account").innerHTML = `
    <article class="account-shell">
      <header class="account-head">
        <div class="identity"><span class="account-monogram">${escapeHtml(initials(client.name))}</span><div><span class="eyebrow">Client account</span><h2>${escapeHtml(client.name || "Client")}</h2><p>${result.job_count || 0} job${result.job_count === 1 ? "" : "s"}${client.franchise ? ` · ${escapeHtml(client.franchise)}` : ""}</p></div></div>
        <button class="btn" id="open-client-folder" ${client.folder_exists ? "" : "disabled"}>📁 Client folder</button>
      </header>
      <section class="contact-grid">
        ${fact("Phone", client.phone, "Not saved")}${fact("Email", client.email, "Not saved")}${fact("Property / mailing address", client.address, "Not saved")}${fact("Known as", (client.aliases || []).join(" · "), "No aliases")}
      </section>
      <section class="jobs-section">
        <div class="section-heading"><div><span class="eyebrow">History</span><h3>Jobs & claims</h3></div><span class="section-count">${jobs.length}</span></div>
        <nav class="job-tabs" role="tablist">${jobs.map((job, index) => `<button role="tab" aria-selected="${index === 0}" class="${index === 0 ? "active" : ""}" data-job-tab="${index}"><strong>${escapeHtml(job.name)}</strong><small>${divisionText(job.divisions)}</small></button>`).join("")}</nav>
        <div class="job-panels">${jobs.map((job, index) => jobPanel(job, index, clientLog)).join("")}</div>
      </section>
    </article>`;
  $("#open-client-folder")?.addEventListener("click", async () => showResult(await pywebview.api.open_folder(client.folder || "")));
  document.querySelectorAll("[data-job-tab]").forEach((tab) => tab.addEventListener("click", () => selectJob(Number(tab.dataset.jobTab))));
  document.querySelectorAll("[data-open-job]").forEach((button) => button.addEventListener("click", () => {
    const job = jobs[Number(button.dataset.openJob)] || {};
    const name = job.name === "Original claim" ? client.name : job.name;
    window.parent.postMessage({ type: "linguar-open-job", focus: name,
      cardId: job.card_id || "", division: (job.divisions || [])[0] || "EMS" }, "*");
  }));
  document.querySelectorAll("[data-open-folder]").forEach((button) => button.addEventListener("click", async () => showResult(await pywebview.api.open_folder(jobs[Number(button.dataset.openFolder)]?.path || ""))));
}

function jobPanel(job, index, clientLog = []) {
  const details = [
    ["Date received", job.date_received], ["Date of loss", job.date_of_loss],
    ["Claim number", job.claim_number], ["Carrier", job.carrier],
    ["Insured", job.insured_name], ["Cause of loss", job.cause_of_loss],
    ["Deductible", job.deductible], ["Adjuster", job.adjuster_name],
    ["Adjuster email", job.adjuster_email], ["Status", job.status],
    ["OD location", job.path],
  ];
  const logs = clientLog.slice().reverse().slice(0, 50);
  return `<section class="job-panel ${index ? "hidden" : ""}" data-job-panel="${index}">
    <div class="job-panel-head"><div><span class="job-kind">${escapeHtml(String(job.kind || "job").replaceAll("_", " "))}</span><h4>${escapeHtml(job.name || "Job")}</h4></div><div class="job-actions"><button class="btn" data-open-folder="${index}" ${job.folder_exists ? "" : "disabled"}>Folder</button><button class="btn btn-primary" data-open-job="${index}">Open Job Card</button></div></div>
    <div class="division-cards">${["EMS","CONTENTS","RECON"].map((division) => `<div class="division-card ${job.divisions?.includes(division) ? "present" : "absent"}"><span>${division === "EMS" ? "💧" : division === "CONTENTS" ? "📦" : "🔨"}</span><strong>${division === "CONTENTS" ? "Contents" : division === "RECON" ? "Recon" : "EMS"}</strong><small>${job.divisions?.includes(division) ? "On this job" : "Not linked"}</small></div>`).join("")}</div>
    <div class="job-facts">${details.map(([label, value]) => fact(label, value, label === "OD location" ? "Folder not linked" : "Not saved")).join("")}</div>
    <section class="claim-log"><div class="claim-log-head"><div><span class="eyebrow">Activity</span><h5>Job log</h5></div><span>${logs.length} entr${logs.length === 1 ? "y" : "ies"}</span></div>
      ${logs.length ? `<div class="claim-log-list">${logs.map(logRow).join("")}</div>` : `<div class="claim-log-empty">No saved job-log entries yet. Folder and job information remain available even without a Trello card.</div>`}
      ${logs.length && jobsNeedLogAssignment(clientLog) ? `<p class="claim-log-note">These entries belong to the client account. Claim-specific assignment will appear as Trello and OD links are reconciled.</p>` : ""}
    </section>
  </section>`;
}

function logRow(entry) {
  const date = displayDate(entry.work_date || entry.created_at || "");
  return `<article class="claim-log-row"><time>${escapeHtml(date || "No date")}</time><div><strong>${escapeHtml(entry.work_type || "Update")}</strong><span>${escapeHtml(entry.note || entry.equipment || "No additional note")}</span></div><em>${escapeHtml(entry.status || "completed")}</em></article>`;
}
function jobsNeedLogAssignment(entries) { return entries.some((entry) => !entry.child_id && !entry.trello_card_id); }
function displayDate(value) { const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/); return match ? `${match[2]}-${match[3]}-${match[1].slice(2)}` : String(value || ""); }

function selectJob(index) {
  document.querySelectorAll("[data-job-tab]").forEach((tab) => { const active = Number(tab.dataset.jobTab) === index; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); });
  document.querySelectorAll("[data-job-panel]").forEach((panel) => panel.classList.toggle("hidden", Number(panel.dataset.jobPanel) !== index));
}
function fact(label, value, fallback) { return `<div class="fact"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || fallback)}</strong></div>`; }
function divisionText(divisions = []) { return divisions.length ? divisions.map((d) => d === "CONTENTS" ? "Contents" : d === "RECON" ? "Recon" : "EMS").join(" · ") : "No division linked"; }
function initials(name) { const parts = String(name || "C").replace(/[,()\-]/g, " ").split(/\s+/).filter(Boolean); return ((parts[0]?.[0] || "C") + (parts[1]?.[0] || "")).toUpperCase(); }
function showResult(result) { if (!result?.ok) setStatus(result?.error || "That could not be opened."); }
function setStatus(message) { $("#status").textContent = message || ""; clearTimeout(setStatus.timer); setStatus.timer = setTimeout(() => $("#status").textContent = "", 4500); }
function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }
