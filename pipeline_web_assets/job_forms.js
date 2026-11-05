/* Review-only draft values: never saved back to the job. */
function showMatchedFormPreview(filename, result, returnFocus, options = {}) {
  const dialog = document.createElement('dialog');
  dialog.className = 'job-forms-dialog matched-form-preview';
  dialog.setAttribute('aria-label', 'Matched document preview');
  const header = document.createElement('header');
  const title = document.createElement('h2');
  title.textContent = String(filename).split(/[\\/]/).pop();
  const close = document.createElement('button');
  close.type = 'button'; close.className = 'btn compact'; close.textContent = '×';
  close.setAttribute('aria-label', 'Close preview');
  close.title = 'Close preview';
  const actions = document.createElement('div');
  actions.className = 'matched-form-preview-actions';
  const confirm = document.createElement('button');
  confirm.type = 'button'; confirm.className = 'btn compact primary';
  confirm.textContent = options.confirmed ? 'File confirmed' : 'Confirm this file';
  confirm.disabled = !!options.confirmed;
  if (options.confirm) actions.append(confirm);
  actions.append(close);
  header.append(title, actions);
  const status = document.createElement('div');
  status.setAttribute('role', 'status');
  status.hidden = true;
  let saving = false;
  confirm.onclick = async () => {
    if (saving) return;
    saving = true; confirm.disabled = true; close.disabled = true;
    status.hidden = false; status.textContent = 'Saving file confirmation…';
    try {
      const saved = await options.confirm();
      if (!saved?.ok) throw new Error(saved?.error || 'Confirmation failed. Please retry.');
      dialog.close();
      options.onConfirmed?.(saved);
    } catch (error) {
      status.textContent = error?.message || String(error);
      confirm.disabled = false;
    } finally { saving = false; close.disabled = false; }
  };
  const content = document.createElement('div');
  content.className = 'matched-form-preview-content';
  let url = '';
  if (result.external || result.mime !== 'application/pdf') {
    content.textContent = 'This file type cannot be previewed here yet. No external app was opened.';
  } else {
    const bytes = Uint8Array.from(atob(result.content), c => c.charCodeAt(0));
    url = URL.createObjectURL(new Blob([bytes], {type:'application/pdf'}));
    const frame = document.createElement('iframe');
    frame.title = title.textContent;
    frame.src = url;
    content.append(frame);
  }
  dialog.append(header, status, content);
  dialog.addEventListener('close', () => {
    if (url) URL.revokeObjectURL(url);
    dialog.remove();
    if (returnFocus?.isConnected) returnFocus.focus();
  }, {once:true});
  close.onclick = () => { if (!saving) dialog.close(); };
  dialog.addEventListener('cancel', event => { event.preventDefault(); event.stopPropagation(); if (!saving) dialog.close(); });
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!saving) dialog.close(); }
  });
  dialog.addEventListener('click', event => {
    if (saving || event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  document.body.append(dialog); dialog.showModal(); close.focus();
}

function jobFormId(label) {
  const name = String(label || '').toLowerCase();
  if (/home improvement/.test(name)) return 'selfpay_contract';
  if (/right to cancel/.test(name)) return 'selfpay_cancel';
  if (/auth.*repair|\batr\b/.test(name)) return 'statefarm_atr';
  if (/state\s*farm.*warranty/.test(name)) return 'statefarm_warranty';
  if (/state\s*farm|authorization to pay/.test(name)) return /\batp\b|auth.*pay/.test(name) ? 'statefarm_atp' : '';
  if (/auth.*perform|\batp\b/.test(name)) return 'atp';
  if (/customer.*info|\bcif\b/.test(name)) return 'cif';
  if (/customer.*equip|equip.*resp|\bcer\b/.test(name)) return 'cer';
  if (/cert.*satisf|\bcos\b/.test(name)) return 'cos';
  return '';
}
function jobFormAction(label, status) {
  const id = jobFormId(label);
  return id && ['missing', 'unknown', 'unsigned', 'todo', 'required_now', 'in_progress'].includes(status)
    ? `<button type="button" class="btn compact" data-prepare-form="${id}">Prepare blank form</button>` : '';
}
async function openJobForms(client, cardId, selectedForm = '') {
  const previous = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'job-members-dialog job-forms-dialog';
  dialog.innerHTML = `<header><h2>Prepare a form</h2><button type="button" data-close aria-label="Close forms">×</button></header>
    <p>Review the available job details, then download an unsigned PDF. If this card has no saved job link, customer and loss fields stay blank. Supported fillable forms can be edited here; static originals are download-only. Changes here affect this draft only.</p>
    <label>Form<select data-form disabled aria-label="Form"></select></label>
    <p data-source-notice hidden></p>
    <p>Signatures, initials, signing dates and customer answers stay blank. Confirm the address, franchise and form edition before sending.</p>
    <div data-fields class="job-form-fields"></div>
    <div data-preview hidden aria-label="PDF preview"></div>
    <p>Self-pay contract and cancellation forms are blank originals for preview/download, not automatically filled.</p>
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
      const label = document.createElement('label'), input = document.createElement(field.multiline ? 'textarea' : 'input');
      if(field.multiline)input.rows=4;
      label.textContent = field.label; input.value = field.value; input.maxLength = 2000;
      input.placeholder = 'Not recorded — review or leave blank';
      input.oninput = () => { field.value = input.value; clearPreview(); };
      label.append(input); host.append(label);
    }
    status.textContent = form.fillable === false ? 'Blank original: no automatic filling. Download and prepare it before sending.' : form.id === 'statefarm_atp'
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
    const inputs = [...dialog.querySelectorAll('input,textarea')]; inputs.forEach(i => i.disabled = true);
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
    const inputs = [...dialog.querySelectorAll('input,textarea')]; inputs.forEach(i => i.disabled = true);
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
