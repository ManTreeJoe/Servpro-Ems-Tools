"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

window.addEventListener("pywebviewready", () => {
  $("#health-refresh").addEventListener("click", () => load(true));
  $("#health-backup").addEventListener("click", runBackup);
  load(false);
}, {once:true});

function row(name, ok, detail, optional=false) {
  const state = ok ? "" : (optional ? "warn" : "bad");
  return `<div class="check ${state}"><span class="check-dot"></span><span class="check-name">${esc(name)}</span><span class="check-detail">${esc(detail)}</span></div>`;
}

async function load(force) {
  $("#health-status").textContent = "Checking…";
  const st = await pywebview.api.status(!!force);
  const requiredProblems = (st.problems || []).length;
  const ready = $("#readiness");
  ready.className = `readiness ${requiredProblems ? "problem" : "ready"}`;
  ready.querySelector(".readiness-title").textContent = requiredProblems ? "Needs attention" : "Ready for work";
  ready.querySelector(".readiness-detail").textContent = requiredProblems
    ? `${requiredProblems} issue${requiredProblems === 1 ? "" : "s"} has a recovery step below.`
    : "Required folders, connections, synchronization, and backups are available.";
  $("#connections").innerHTML = (st.checks || []).map((c) => row(
    c.label, c.ok, c.ok ? "Available" : (c.required ? c.action : `Optional · ${c.action}`), !c.required)).join("");
  const backups = st.backup?.checks || [];
  $("#backups").innerHTML = backups.length ? backups.map((b) => row(
    b.name, b.ok || st.backup?.pending, st.backup?.pending ? "Backing up now…" :
      (b.last_success ? `${b.state} · ${b.age_hours} hours old` : "No verified backup yet"))).join("")
    : row("Backup verification", false, "Run a backup to establish recovery history");
  $("#health-status").textContent = requiredProblems ? "Review the highlighted items" : "All required checks passed";
}

async function runBackup() {
  const btn = $("#health-backup");
  btn.disabled = true; btn.textContent = "Backing up…";
  try { const result = await pywebview.api.run_backup(); await load(true); $("#health-status").textContent = result.ok ? "Backup completed" : "Backup finished with an error"; }
  catch (e) { $("#health-status").textContent = `Backup failed: ${e}`; }
  finally { btn.disabled = false; btn.textContent = "Run backup now"; }
}
