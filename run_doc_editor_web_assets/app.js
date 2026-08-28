"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { dayOffset: 0, model: null, dirty: false, saving: false, drag: null, undo: [], activeSection: "work", composing: null };
const DATED_SECTIONS = new Set(["upcoming", "tbs_new_loss", "tbs_mitigation", "tbs_contents", "pending_testing", "pending_insurance", "pending_property", "on_hold", "marketing"]);

window.addEventListener("pywebviewready", async () => {
  await PanelState.init("run_doc_editor");
  state.dayOffset = Number(PanelState.get("dayOffset", 0)) || 0;
  state.activeSection = PanelState.get("activeSection", "work") || "work";
  $("#day-prev").addEventListener("click", () => walkDay(-1));
  $("#day-today").addEventListener("click", () => walkDay(0));
  $("#day-next").addEventListener("click", () => walkDay(1));
  $("#open-word").addEventListener("click", () => pywebview.api.open_word(state.dayOffset));
  $("#save-btn").addEventListener("click", save);
  $("#undo-btn").addEventListener("click", undo);
  $("#add-row").addEventListener("click", () => openComposer(state.activeSection, null));
  $("#composer-close").addEventListener("click", closeComposer);
  $("#composer-cancel").addEventListener("click", closeComposer);
  $("#composer-apply").addEventListener("click", applyComposer);
  $("#item-composer").addEventListener("click", (event) => { if (event.target.id === "item-composer") closeComposer(); });
  document.querySelectorAll("#item-composer input").forEach((input) => input.addEventListener("input", renderComposerPreview));
  document.addEventListener("keydown", onKeyDown);
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault(); event.returnValue = "";
  });
  await loadDay();
});

function snapshot() { return JSON.parse(JSON.stringify(state.model?.sections || { monitor: [], work: [] })); }
function pushUndo() {
  state.undo.push(snapshot());
  if (state.undo.length > 20) state.undo.shift();
  $("#undo-btn").disabled = false;
}
function undo() {
  if (!state.undo.length || !state.model) return;
  state.model.sections = state.undo.pop();
  $("#undo-btn").disabled = !state.undo.length;
  markDirty(); renderRows();
}
function setSaveState(kind, label) {
  const badge = $("#save-state");
  badge.className = `save-state ${kind}`;
  badge.innerHTML = `<span></span>${escapeHtml(label)}`;
}
function markDirty() {
  state.dirty = true;
  $("#save-btn").disabled = false;
  setSaveState("dirty", "Unsaved changes");
  $("#status-msg").textContent = "Changes stay local until you save";
}
function confirmDiscard() { return !state.dirty || window.confirm("Discard your unsaved run-doc changes?"); }

async function walkDay(delta) {
  if (!confirmDiscard()) return;
  state.dayOffset = delta === 0 ? 0 : state.dayOffset + delta;
  PanelState.set({ dayOffset: state.dayOffset });
  state.dirty = false; state.undo = [];
  await loadDay();
}

async function loadDay() {
  $("#day-title").textContent = "Loading run document…";
  $("#run-board").classList.add("hidden");
  $("#empty").classList.add("hidden");
  hideNotice();
  let result;
  try { result = await pywebview.api.load_day(state.dayOffset); }
  catch (error) { result = { ok: false, error: String(error) }; }
  state.model = result; state.dirty = false; state.saving = false; state.undo = [];
  $("#undo-btn").disabled = true; $("#save-btn").disabled = true;
  $("#department").textContent = result?.department || "Run document";
  $("#day-title").textContent = result?.date_label || "Run document";
  $("#open-word").disabled = !result?.exists;
  if (!result?.ok || !result?.editable) {
    const empty = $("#empty");
    empty.innerHTML = `<h2>${result?.exists ? "This run format is not editable yet" : "No run document found"}</h2><p>${escapeHtml(result?.error || "Choose another day or verify the department’s run folder in Settings.")}</p>`;
    empty.classList.remove("hidden");
    $("#file-meta").textContent = result?.filename || "";
    setSaveState(result?.ok ? "clean" : "error", result?.ok ? "Nothing to edit" : "Load failed");
    return;
  }
  $("#file-meta").textContent = `${result.filename} · Last changed ${formatTime(result.modified)}`;
  $("#run-board").classList.remove("hidden");
  setSaveState("clean", "Saved");
  $("#status-msg").textContent = "Ctrl+S saves";
  renderRows();
}

function renderRows() {
  if (!state.model?.sections) return;
  const order = state.model.section_order || Object.keys(state.model.sections);
  if (!order.includes(state.activeSection)) state.activeSection = order[0] || "work";
  const labels = state.model.section_labels || {};
  $("#section-rail").innerHTML = order.map((section, i) => {
    const count = (state.model.sections[section] || []).length;
    return `<button class="section-nav ${section === state.activeSection ? "active" : ""}" data-section="${escapeHtml(section)}">
      <span class="section-index">${String(i + 1).padStart(2, "0")}</span>
      <span class="section-nav-label">${escapeHtml(labels[section] || section)}</span>
      <span class="section-nav-count">${count}</span>
    </button>`;
  }).join("");
  document.querySelectorAll(".section-nav").forEach(button =>
    button.addEventListener("click", () => {
      state.activeSection = button.dataset.section;
      PanelState.set({ activeSection: state.activeSection });
      renderRows();
    }));
  const section = state.activeSection;
  const rows = state.model.sections[section] || [];
  $("#section-title").textContent = labels[section] || section;
  $("#section-kicker").textContent = section === "work" ? "Today’s field plan" : section === "monitor" ? "Keep eyes on" : "Queue and follow-up";
  $("#section-count").textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  $("#section-rows").innerHTML = rows.map((row, index) => rowHtml(section, row, index)).join("");
  $("#add-row").textContent = `＋ Add row to ${labels[section] || section}`;
  bindRows();
}
function rowHtml(section, row, index) {
  return `<div class="run-row ${row.struck ? "struck" : ""}" data-section="${section}" data-index="${index}">
    <button class="row-tab" draggable="true" title="Drag this row" aria-label="Drag row ${index + 1}"><span class="grip-lines" aria-hidden="true">☰</span><span>${index + 1}</span></button>
    <div class="row-main"><textarea class="row-text" rows="1" spellcheck="true" aria-label="${section} row ${index + 1}">${escapeHtml(row.text || "")}</textarea></div>
    <div class="row-tools"><button class="row-tool format" title="Format item" aria-label="Format item">▤</button><button class="row-tool done ${row.struck ? "active" : ""}" title="Mark complete" aria-label="Mark complete">✓</button><button class="row-tool delete" title="Remove row" aria-label="Remove row">×</button></div>
  </div>`;
}

function bindRows() {
  document.querySelectorAll(".run-row").forEach((element) => {
    const ref = () => ({ section: element.dataset.section, index: Number(element.dataset.index) });
    const textarea = element.querySelector(".row-text");
    autoHeight(textarea);
    textarea.addEventListener("keydown", (event) => {
      // One card maps to one Word paragraph. Enter would create a hidden
      // second line inside that paragraph instead of a new dispatch row.
      if (event.key === "Enter") { event.preventDefault(); }
    });
    textarea.addEventListener("input", () => {
      const at = ref(); state.model.sections[at.section][at.index].text = textarea.value;
      autoHeight(textarea); markDirty();
    });
    element.querySelector(".format").addEventListener("click", () => openComposer(ref().section, ref().index));
    element.querySelector(".done").addEventListener("click", () => {
      pushUndo(); const at = ref();
      state.model.sections[at.section][at.index].struck = !state.model.sections[at.section][at.index].struck;
      markDirty(); renderRows();
    });
    element.querySelector(".delete").addEventListener("click", () => removeRow(ref()));
    const grip = element.querySelector(".row-tab");
    grip.addEventListener("dragstart", (event) => {
      state.drag = ref(); element.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", `${state.drag.section}:${state.drag.index}`);
    });
    grip.addEventListener("dragend", () => {
      state.drag = null;
      document.querySelectorAll(".run-row").forEach((row) => row.classList.remove("dragging", "drag-before", "drag-after"));
    });
    element.addEventListener("dragover", (event) => {
      event.preventDefault();
      const before = event.clientY < element.getBoundingClientRect().top + element.offsetHeight / 2;
      element.classList.toggle("drag-before", before);
      element.classList.toggle("drag-after", !before);
      event.dataTransfer.dropEffect = "move";
    });
    element.addEventListener("dragleave", () => element.classList.remove("drag-before", "drag-after"));
    element.addEventListener("drop", (event) => {
      event.preventDefault();
      const before = element.classList.contains("drag-before");
      element.classList.remove("drag-before", "drag-after");
      if (state.drag) dropRow(state.drag, ref(), before);
    });
  });
}

function cleanPart(value) { return String(value || "").trim().replace(/\s+/g, " "); }
function formatRunItem(fields, section) {
  const identity = cleanPart(fields.job);
  const location = [cleanPart(fields.address), cleanPart(fields.phone)].filter(Boolean).join(" — ");
  const details = [cleanPart(fields.task)];
  if (DATED_SECTIONS.has(section)) details.push(cleanPart(fields.date));
  details.push(cleanPart(fields.time), cleanPart(fields.crew), cleanPart(fields.status));
  return [identity, location, ...details].filter(Boolean).join(" | ");
}
function seedComposer(text) {
  const parts = String(text || "").split("|").map(cleanPart);
  return { job: parts[0] || "", address: parts[1] || "", phone: "", task: parts[2] || "", date: "", time: parts[3] || "", crew: parts[4] || "", status: parts.slice(5).join(" | ") };
}
function composerFields() {
  return { job: $("#field-job").value, address: $("#field-address").value, phone: $("#field-phone").value, task: $("#field-task").value, date: $("#field-date").value, time: $("#field-time").value, crew: $("#field-crew").value, status: $("#field-status").value };
}
function openComposer(section, index) {
  const row = index === null ? null : state.model.sections[section][index];
  state.composing = { section, index };
  const seed = seedComposer(row?.text || "");
  for (const key of Object.keys(seed)) $(`#field-${key}`).value = seed[key];
  const dated = DATED_SECTIONS.has(section);
  $("#item-composer").classList.remove("hidden");
  $("#item-composer").classList.toggle("dated", dated);
  $("#composer-help").textContent = dated
    ? "Add a date only when it helps explain a future visit, deadline, or follow-up. Every field is optional."
    : "This item belongs to the selected day, so no date is needed. Every field is optional.";
  renderComposerPreview();
  setTimeout(() => $("#field-job").focus(), 20);
}
function closeComposer() { $("#item-composer").classList.add("hidden"); state.composing = null; }
function renderComposerPreview() {
  if (!state.composing) return;
  $("#composer-preview").textContent = formatRunItem(composerFields(), state.composing.section) || "Start with the job or site name.";
}
function applyComposer() {
  if (!state.composing) return;
  const text = formatRunItem(composerFields(), state.composing.section);
  if (!text) { $("#field-job").focus(); return; }
  pushUndo();
  const { section, index } = state.composing;
  if (index === null) state.model.sections[section].push({ id: `new:${Date.now()}`, text, struck: false });
  else state.model.sections[section][index].text = text;
  closeComposer(); markDirty(); renderRows();
}
function autoHeight(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(150, Math.max(32, textarea.scrollHeight))}px`;
}
function moveWithin(ref, delta) {
  const rows = state.model.sections[ref.section], target = ref.index + delta;
  if (target < 0 || target >= rows.length) return;
  pushUndo(); [rows[ref.index], rows[target]] = [rows[target], rows[ref.index]];
  markDirty(); renderRows();
}
function dropRow(source, target, before=true) {
  pushUndo();
  const [row] = state.model.sections[source.section].splice(source.index, 1);
  let index = target.index + (before ? 0 : 1);
  if (source.section === target.section && source.index < index) index -= 1;
  if (source.section === target.section && source.index === index) {
    state.undo.pop();
    $("#undo-btn").disabled = !state.undo.length;
    state.model.sections[source.section].splice(source.index, 0, row);
    return;
  }
  state.model.sections[target.section].splice(Math.max(0, index), 0, row);
  markDirty(); renderRows();
}
function addRow(section) {
  pushUndo();
  state.model.sections[section].push({ id: `new:${Date.now()}`, text: "", struck: false });
  markDirty(); renderRows();
  $("#section-rows .run-row:last-child .row-text")?.focus();
}
function removeRow(ref) {
  pushUndo(); state.model.sections[ref.section].splice(ref.index, 1);
  markDirty(); renderRows();
}

async function save() {
  if (!state.model?.editable || !state.dirty || state.saving) return;
  state.saving = true; $("#save-btn").disabled = true;
  setSaveState("saving", "Saving…");
  $("#status-msg").textContent = "Backing up and validating Word document…";
  let result;
  try { result = await pywebview.api.save_day(state.dayOffset, state.model.version, state.model.sections); }
  catch (error) { result = { ok: false, error: String(error) }; }
  state.saving = false;
  if (!result?.ok) {
    $("#save-btn").disabled = false;
    setSaveState("error", result?.conflict ? "Newer Word copy found" : "Save failed");
    showNotice(result?.error || "The document could not be saved.", "error");
    $("#status-msg").textContent = result?.conflict ? "Reload before saving" : "Nothing was replaced";
    return;
  }
  state.model = { ...state.model, ...result, editable: true, exists: true };
  state.dirty = false; state.undo = [];
  $("#undo-btn").disabled = true; $("#save-btn").disabled = true;
  hideNotice(); setSaveState("clean", "Saved");
  $("#file-meta").textContent = `${result.filename} · Last changed ${formatTime(result.modified)}`;
  $("#status-msg").textContent = "Saved, backed up, and validated";
  renderRows();
}
function onKeyDown(event) {
  if (event.key === "Escape" && state.composing) { event.preventDefault(); closeComposer(); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
}
function showNotice(message, kind="warn") { const notice=$("#notice"); notice.textContent=message; notice.className=`notice ${kind}`; }
function hideNotice() { $("#notice").className="notice hidden"; }
function formatTime(value) { const date=new Date(value); return Number.isNaN(date.getTime())?value:date.toLocaleString([], {dateStyle:"medium",timeStyle:"short"}); }
function escapeHtml(value) { return String(value??"").replace(/[&<>"']/g,(char)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
