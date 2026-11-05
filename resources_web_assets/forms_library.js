"use strict";
window.formsLibraryActive = true;
let formLibraryRows = null;
window.renderFormsLibrary = async function () {
  $('#hint').textContent = 'Your uploaded PDFs · saved on this computer';
  $('#rows').textContent = 'Loading forms…';
  try {
    if (!formLibraryRows) {
      const res = await pywebview.api.forms_library();
      if (!res?.ok) throw Error(res?.error || 'Could not load forms');
      formLibraryRows = res.rows;
    }
    if (!window.formsLibraryActive) return;
    const q = $('#q').value.trim().toLowerCase();
    const rows = formLibraryRows.filter(r => `${r.title} ${r.group}`.toLowerCase().includes(q));
    $('#rows').innerHTML = rows.length ? rows.map((r, i) => `<article class="row">
      <div class="mid"><div class="name">${esc(r.title)}</div><div class="meta">${esc(r.group)}</div>
      <p class="where">${esc(r.note)}</p></div><div class="acts">${r.available ?
      `<button class="btn" data-preview-form="${i}">Preview</button><button class="btn" data-download-form="${i}">Download</button>${r.custom?`<button class="btn" data-build-form="${i}">Build fields</button>`:`<button class="btn" data-source-form="${i}">Source</button>`}` : '<span>Template needed</span>'}</div></article>`).join('') : (q ? '<p>No PDFs match your search.</p>' : '<div class="library-empty"><h2>No PDFs uploaded yet</h2><p>Upload a blank, unsigned PDF to start your library.</p><button class="btn" data-empty-upload>+ Upload PDF</button></div>');
    $('#rows').querySelector('[data-empty-upload]')?.addEventListener('click', () => $('#upload-form').click());
    $('#rows').querySelectorAll('[data-build-form]').forEach(b=>b.onclick=()=>window.openFormBuilder(rows[+b.dataset.buildForm].id));
    $('#rows').querySelectorAll('article.row').forEach((article,i)=>{
      if(!rows[i].can_map)return;
      const b=document.createElement('button');b.className='btn';b.textContent='Map a copy';
      article.querySelector('.acts').append(b);
      b.onclick=async()=>{
        b.disabled=true;
        try{const r=await pywebview.api.form_builder_copy_builtin(rows[i].id);if(!r.ok)throw Error(r.error);
          formLibraryRows=null;await window.openFormBuilder(r.id);
        }catch(e){setStatus(e.message,'error');}finally{b.disabled=false;}
      };
    });
    $('#rows').querySelectorAll('[data-preview-form]').forEach(b => b.onclick = () => previewLibraryForm(rows[+b.dataset.previewForm]));
    $('#rows').querySelectorAll('[data-download-form]').forEach(b => b.onclick = async () => {
      b.disabled = true;
      try { const r = await pywebview.api.job_forms_export(rows[+b.dataset.downloadForm].id, {});
        setStatus(r.ok ? (r.cancelled ? 'Download cancelled' : 'Unsigned copy saved') : r.error, r.ok ? 'ok' : 'error');
      } catch(e) { setStatus(String(e), 'error'); } finally { b.disabled = false; }
    });
    $('#rows').querySelectorAll('[data-source-form]').forEach(b => b.onclick = async () => {
      try { const r = await pywebview.api.open_folder(rows[+b.dataset.sourceForm].path);
        if (!r.ok) setStatus(r.error, 'error'); } catch(e) { setStatus(String(e), 'error'); }
    });
  } catch(e) { $('#rows').textContent = 'Forms could not load. Click Forms Library to retry.'; setStatus(String(e), 'error'); }
};
async function previewLibraryForm(row) {
  const previous = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'library-preview';
  dialog.innerHTML = `<button class="btn" aria-label="Close preview">Close</button><h2>${esc(row.title)}</h2><p>${esc(row.note)}</p><div data-pages>Loading preview…</div>`;
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.onclose = () => { dialog.remove(); previous?.focus(); };
  document.body.append(dialog); dialog.showModal();
  try {
    const r = await pywebview.api.job_forms_preview(row.id, {});
    if (!r.ok) throw Error(r.error);
    dialog.querySelector('[data-pages]').innerHTML = r.pages.map((p,i) => `<img alt="Page ${i+1}" src="data:image/png;base64,${p}">`).join('');
  } catch(e) { dialog.querySelector('[data-pages]').textContent = String(e); }
}
document.querySelector('#forms-library').onclick = () => {
  setResourceView(true);
  $('#forms-library').setAttribute('aria-pressed', 'true');
  window.formsLibraryActive = true; $('#ext').disabled = true; $('#q').value = '';
  window.renderFormsLibrary();
};

function setResourceView(library) {
  window.formsLibraryActive = library;
  $('#forms-library').setAttribute('aria-pressed', String(library));
  $('#shared-files').setAttribute('aria-pressed', String(!library));
  for (const selector of ['#ext', '#rebuild', '#areas', '.areas-head']) $(selector).hidden = library;
  $('#upload-form').hidden = !library;
  $('#q').placeholder = library ? 'Search uploaded PDFs…' : 'Search shared files…';
  $('#q').value = '';
}
$('#shared-files').onclick = () => {
  setResourceView(false); $('#ext').disabled = false; loadAreas(); run();
};
function startPdfLibrary() {
  if (window.formsLibraryActive) window.renderFormsLibrary();
}
window.addEventListener('pywebviewready', startPdfLibrary);
if (window.pywebview?.api) startPdfLibrary();
