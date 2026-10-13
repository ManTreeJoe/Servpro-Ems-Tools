/* Review-only draft values: never saved back to the job. */
function jobFormId(label) {
  const name = String(label || '').toLowerCase();
  if (/auth.*repair|\batr\b/.test(name)) return '';
  if (/state\s*farm|authorization to pay/.test(name)) return /\batp\b|auth.*pay/.test(name) ? 'statefarm_atp' : '';
  if (/auth.*perform|\batp\b/.test(name)) return 'atp';
  if (/customer.*info|\bcif\b/.test(name)) return 'cif';
  if (/customer.*equip|equip.*resp|\bcer\b/.test(name)) return 'cer';
  if (/cert.*satisf|\bcos\b/.test(name)) return 'cos';
  return '';
}
function jobFormAction(label, status) {
  const id = jobFormId(label);
  return id && ['missing', 'unsigned', 'todo', 'required_now', 'in_progress'].includes(status)
    ? `<button type="button" class="btn compact" data-prepare-form="${id}">Preview / edit / download</button>` : '';
}
async function openJobForms(client, cardId, selectedForm = '') {
  const previous = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'job-members-dialog job-forms-dialog';
  dialog.innerHTML = `<header><h2>Prepare a form</h2><button type="button" data-close aria-label="Close forms">×</button></header>
    <p>Review saved job details, then download an editable, unsigned PDF for DocuSign. Changes here affect this draft only.</p>
    <label>Form<select data-form disabled aria-label="Form"></select></label>
    <p data-source-notice hidden></p>
    <p>Signatures, initials, signing dates and customer answers stay blank. Confirm the address, franchise and form edition before sending.</p>
    <div data-fields class="job-form-fields"></div>
    <div data-preview hidden aria-label="PDF preview"></div>
    <p>State Farm Authorization to Repair needs an unsigned template; the supplied signed example is not reused.</p>
    <p data-status role="status">Loading saved job details…</p>
    <footer><button type="button" data-retry hidden>Retry</button><button type="button" data-preview-button disabled>Preview PDF</button><button type="button" data-save disabled>Download PDF…</button></footer>`;
  document.body.append(dialog);
  const status = dialog.querySelector('[data-status]');
  const select = dialog.querySelector('[data-form]');
  const save = dialog.querySelector('[data-save]');
  const retry = dialog.querySelector('[data-retry]');
  const previewButton = dialog.querySelector('[data-preview-button]');
  const preview = dialog.querySelector('[data-preview]');
  const clearPreview = () => { preview.hidden = true; preview.replaceChildren(); };
  let forms = [], busy = false;
  dialog.querySelector('[data-close]').onclick = () => { if (!busy) dialog.close(); };
  dialog.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
  dialog.addEventListener('close', () => { dialog.remove(); previous?.focus(); });
  function render() {
    clearPreview();
    const host = dialog.querySelector('[data-fields]'); host.replaceChildren();
    const form = forms.find(f => f.id === select.value);
    for (const field of form.fields) {
      const label = document.createElement('label'), input = document.createElement('input');
      label.textContent = field.label; input.value = field.value; input.maxLength = 2000;
      input.placeholder = 'Not recorded — review or leave blank';
      input.oninput = () => { field.value = input.value; clearPreview(); };
      label.append(input); host.append(label);
    }
    status.textContent = form.id === 'statefarm_atp'
      ? 'English fields are editable; the Spanish translation page is preserved as supplied and has no fillable fields.'
      : 'Review every field. Missing facts remain blank; no dates or answers are guessed.';
  }
  async function load() {
    retry.hidden = true; select.disabled = save.disabled = true;
    try {
      const result = await pywebview.api.job_forms_load(client, cardId);
      if (!dialog.isConnected) return;
      if (!result?.ok) throw Error(result?.error || 'Forms could not load.');
      forms = result.forms; select.replaceChildren();
      const notice = dialog.querySelector('[data-source-notice]');
      notice.textContent = result.notice || ''; notice.hidden = !result.notice;
      for (const form of forms) { const option = document.createElement('option'); option.value = form.id; option.textContent = form.title; select.append(option); }
      if (forms.some(f => f.id === selectedForm)) select.value = selectedForm;
      select.disabled = save.disabled = previewButton.disabled = false; render();
    } catch (e) { status.textContent = e.message; retry.hidden = false; }
  }
  select.onchange = render; retry.onclick = load;
  previewButton.onclick = async () => {
    busy = true; select.disabled = save.disabled = previewButton.disabled = true;
    const inputs = [...dialog.querySelectorAll('input')]; inputs.forEach(i => i.disabled = true);
    status.textContent = 'Rendering preview…'; clearPreview();
    try {
      const form = forms.find(f => f.id === select.value);
      const result = await pywebview.api.job_forms_preview(form.id, Object.fromEntries(form.fields.map(f => [f.id, f.value])));
      if (!result?.ok) throw Error(result?.error || 'Preview unavailable. You can still download the PDF.');
      for (const [index, data] of result.pages.entries()) {
        const image = document.createElement('img'); image.alt = `PDF page ${index + 1}`;
        image.src = 'data:image/png;base64,' + data; preview.append(image);
      }
      preview.hidden = false; preview.scrollIntoView({block:'start'});
      status.textContent = 'Preview of your current draft. Edit details above to revise; then preview again or download.';
    } catch (e) { status.textContent = e.message; }
    finally { busy = false; select.disabled = save.disabled = previewButton.disabled = false; inputs.forEach(i => i.disabled = false); }
  };
  save.onclick = async () => {
    busy = true; select.disabled = save.disabled = previewButton.disabled = true;
    const inputs = [...dialog.querySelectorAll('input')]; inputs.forEach(i => i.disabled = true);
    status.textContent = 'Preparing PDF…';
    try {
      const form = forms.find(f => f.id === select.value);
      const result = await pywebview.api.job_forms_export(form.id, Object.fromEntries(form.fields.map(f => [f.id, f.value])));
      if (!result?.ok) throw Error(result?.error || 'PDF could not be saved.');
      status.textContent = result.cancelled ? 'Save cancelled. Your draft is still here.' : `Saved: ${result.path}. Ready for review and manual upload to DocuSign.`;
    } catch (e) { status.textContent = e.message; }
    finally { busy = false; select.disabled = save.disabled = previewButton.disabled = false; inputs.forEach(i => i.disabled = false); }
  };
  dialog.showModal(); await load();
}
