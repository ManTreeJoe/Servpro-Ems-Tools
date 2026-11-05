/* Job-bound file workspace. Choosing sources never starts an import. */
window.JobImportWorkspace = {
  open(data, audit, {pullCompanyCam} = {}) {
    const client = data.client || audit.client || '', cardId = data.card_id || '';
    const api = window.pywebview.api, origin = document.activeElement;
    const host = document.createElement('div');
    host.className = 'modal-scrim import-workspace';
    host.innerHTML = `<section role="dialog" aria-modal="true" aria-label="Job files" class="import-workspace-card">
      <header><div><h2>Job files</h2><p data-job></p></div><button class="btn" data-close aria-label="Close job files">×</button></header>
      <nav aria-label="File workspace"><button class="btn" data-tab="import" aria-pressed="true">Import files</button><button class="btn" data-tab="browse" aria-pressed="false">Browse job folder</button></nav>
      <div data-import-pane class="import-workspace-grid"><main>
        <h3>1. Choose a source</h3>
        <div class="import-sources"><button class="btn" data-scan>Scan Downloads</button><button class="btn" data-pick>Choose files…</button><button class="btn import-source-icon" data-cc title="CompanyCam → job folder" aria-label="CompanyCam → job folder"><img src="../web_shared/companycam.png" alt=""></button><button class="btn import-source-icon" data-trello title="Trello attachments" aria-label="Trello attachments"><img src="../web_shared/trello.png" alt=""></button></div>
        <p class="muted import-drop-zone" data-drop-zone>Drop files here, or choose files above. Nothing is imported until you confirm.</p>
        <div data-candidates class="import-source-list"><p>No files selected. Scan Downloads or choose files to get started.</p></div>
      </main><aside>
        <h3>2. Review destination</h3>
        <label>Section<select data-side><option value="ems">EMS</option><option value="contents">Contents</option></select></label>
        <label>Folder<select data-destination><option value="">Auto-sort photos / documents</option><option value="Initial">PICS / Initial</option><option value="Reinspection">PICS / Reinspection</option><option value="Monitor">PICS / Moisture Checks (Monitor)</option><option value="Abatement">PICS / Abatement</option><option value="Cleaning">PICS / Cleaning</option><option value="Demo">PICS / Demo</option><option value="Mold Prep">PICS / Mold Prep</option><option value="Walkthroughs">PICS / Walkthroughs</option><option value="Final">PICS / Final</option><option value="DOCS">DOCS</option></select></label>
        <label>Tech / crew<input data-tech placeholder="Full name or initials" autocomplete="off"></label>
        <p class="muted">Required for photos. Keep the full crew text.</p>
        <div class="import-review" data-review>No batch selected.</div>
        <p class="import-warning">The existing importer routes files by type and may recycle source ZIPs after success. Review the batch before continuing.</p>
        <button class="btn btn-primary" data-confirm disabled>Import reviewed batch</button>
        <p class="muted">CompanyCam and Trello open their own selection and destination review.</p>
      </aside></div>
      <div data-browse-pane class="import-browse-pane" hidden></div>
      <footer><p data-status role="status" aria-live="polite"></p><span>Job-folder storage · database storage is not enabled</span></footer>
    </section>`;
    document.body.append(host);
    if(cardId){const header=host.querySelector('header');header.dataset.popoutTool='pipeline';header.dataset.popoutContext=JSON.stringify({cardId,client,division:data.selected_division||'EMS',jobAction:'import'});header.title='Open a fresh import window; current selections stay here.';}
    host.querySelector('[data-job]').textContent = client;
    const $ = selector => host.querySelector(selector);
    $('[data-side]').value = String(data.selected_division||'EMS').toUpperCase()==='CONTENTS' ? 'contents' : 'ems';
    let selected = null, busy = false, closed = false, viewer = null, revision = 0;
    const message = (text, state = '') => { $('[data-status]').textContent = text; $('[data-status]').dataset.state = state; };
    const dropToken = crypto.randomUUID().replaceAll('-', '');
    host.dataset.dropToken = dropToken;
    let dropReady = false, dropPending = false, dropTimer, registrationTimer, dropRequest = 0;
    const idleDropText = 'Drop files anywhere in this window, or choose files above. Review before importing.';
    const resetDrag = () => { host.classList.remove('is-file-drag'); $('[data-drop-zone]').textContent = dropReady ? idleDropText : 'Use Choose files while drag-and-drop connects.'; };
    const canDrop = () => dropReady && !busy && !dropPending && !$('[data-import-pane]').hidden;
    const hasFiles = event => Array.from(event.dataTransfer?.types || []).includes('Files');
    host.addEventListener('dragover', event => {
      if (!hasFiles(event)) return;
      event.preventDefault(); event.dataTransfer.dropEffect = canDrop() ? 'copy' : 'none';
      host.classList.toggle('is-file-drag', canDrop());
      $('[data-drop-zone]').textContent = canDrop() ? '↓ Drop to add files for review' : 'Finish the current step, or use Choose files.';
    });
    host.addEventListener('dragleave', event => { if (!host.contains(event.relatedTarget)) resetDrag(); });
    host.addEventListener('drop', event => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      const accepted = canDrop(); resetDrag();
      if (!accepted) return;
      dropPending = true;
      const request = ++dropRequest;
      review();
      message('Reading dropped files…', 'loading');
      dropTimer = setTimeout(() => {
        dropPending = false;
        review();
        message('The file drop did not finish. Use Choose files to select the files. Nothing was imported.', 'error');
      }, 12000);
      try {
        const root = window.top, receiver = root.document.getElementById(`import-drop-${dropToken}`);
        if (!receiver) throw Error('File drop is not connected. Use Choose files.');
        const forwarded = new root.DragEvent('drop', {dataTransfer:event.dataTransfer, bubbles:false, cancelable:true});
        forwarded.importRequest = request;
        receiver.dispatchEvent(forwarded);
      } catch (error) {
        clearTimeout(dropTimer); dropPending = false;
        review();
        message(error.message || 'Use Choose files to select these files.', 'error');
      }
    });
    function receiveDrop(event) {
      if (event.detail?.token !== dropToken || event.detail.request !== dropRequest || closed || busy || !dropPending) return;
      clearTimeout(dropTimer); dropPending = false;
      review();
      if (event.detail.error) { message(event.detail.error, 'error'); return; }
      if (!event.detail.paths?.length) { message('No files received. Use Choose files.', 'error'); return; }
      const paths = [...new Set([...(selected?.paths || []), ...(event.detail.paths || [])])];
      render([{kind:'wc_attachments', kind_label:'Dropped files', paths}]);
      $('[data-candidates] button')?.click();
      message(`${event.detail.paths.length} file(s) added for review. Confirm the destination before importing.`, 'ready');
    }
    window.addEventListener('import-files-dropped', receiveDrop);
    registrationTimer = setTimeout(() => { if (!closed && !dropReady) $('[data-drop-zone]').textContent = 'Drag-and-drop is not connected. Use Choose files.'; }, 8000);
    Promise.resolve(api.import_drop_target?.(dropToken, true)).then(result => {
      clearTimeout(registrationTimer);
      if (closed) { api.import_drop_target?.(dropToken, false); return; }
      dropReady = !!result?.ok; resetDrag();
      if (!dropReady) $('[data-drop-zone]').textContent = 'Drag-and-drop is unavailable here. Use Choose files above.';
    }).catch(() => { clearTimeout(registrationTimer); if (!closed) $('[data-drop-zone]').textContent = 'Use Choose files to select a batch.'; });
    function controls(lock) {
      busy = lock;
      host.querySelectorAll('button,select,input').forEach(el => el.disabled = lock);
      $('[data-confirm]').disabled = lock || dropPending || !selected;
      $('[data-trello]').disabled = lock || !cardId;
      $('[data-cc]').disabled = lock || !pullCompanyCam;
      host.setAttribute('aria-busy', String(lock));
    }
    function review() {
      const place = `${$('[data-side]').selectedOptions[0].textContent} / ${$('[data-destination]').selectedOptions[0].textContent}`;
      $('[data-review]').textContent = selected
        ? `${selected.paths.length} source file(s) · ${place} · ${$('[data-tech]').value.trim() || 'Crew not entered'}`
        : 'No batch selected.';
      $('[data-confirm]').disabled = busy || dropPending || !selected;
    }
    function render(candidates) {
      const list = $('[data-candidates]'); list.replaceChildren(); selected = null;
      for (const candidate of candidates) {
        const button = document.createElement('button'); button.className = 'import-source-row'; button.type = 'button';
        const title = document.createElement('strong'); title.textContent = candidate.kind_label || 'Selected files';
        const detail = document.createElement('span');
        detail.textContent = candidate.label || candidate.paths.map(p => p.split(/[\\/]/).pop()).join(', ');
        detail.title = candidate.paths.join('\n');
        button.append(title, detail); button.setAttribute('aria-pressed', 'false');
        button.onclick = () => {
          selected = candidate;
          list.querySelectorAll('button').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
          review();
        };
        list.append(button);
      }
      if (!candidates.length) list.textContent = 'No importable downloads found. Choose files directly or download them and scan again.';
      review();
    }
    async function choose(picker) {
      if (busy) return;
      clearTimeout(dropTimer); dropPending = false;
      const request = ++revision; controls(true); message(picker ? 'Opening file picker…' : 'Scanning Downloads…');
      try {
        const result = await (picker ? api.pick_import_files(client) : api.scan_downloads(client));
        if (closed || request !== revision) return;
        if (result?.cancelled) { message('Selection cancelled. Your previous batch is unchanged.'); return; }
        if (result?.error || (picker && !result?.ok)) throw Error(result?.error || 'Could not select files.');
        const candidates = picker ? [{kind: 'wc_attachments', paths: result.paths || []}] : result.candidates || [];
        render(candidates.filter(row => row.paths?.length));
        message('Choose a batch, then review its destination.');
      } catch (error) { message(error.message || String(error)); }
      finally { if (!closed) controls(false); }
    }
    $('[data-scan]').onclick = () => choose(false);
    $('[data-pick]').onclick = () => choose(true);
    host.querySelectorAll('[data-side],[data-destination],[data-tech]').forEach(el => el.addEventListener('input', review));
    $('[data-confirm]').onclick = async () => {
      if (!selected || busy || dropPending) return;
      const batch = selected, destination = $('[data-destination]').value,
        side = $('[data-side]').value, tech = $('[data-tech]').value.trim();
      controls(true); message('Importing reviewed batch…');
      try {
        const result = await api.do_import(client, batch.kind || '', batch.paths, destination, tech, side, cardId);
        if (!result?.ok) throw Error(result?.error || 'Import did not complete. Check the folder before retrying.');
        message(`✓ Import complete — ${result.pics_count || 0} photos · ${result.docs_count || 0} documents · ${result.sketches_count || 0} sketches.`, 'success');
        selected = null; $('[data-candidates]').replaceChildren();
        $('[data-candidates]').textContent = 'Batch completed. Browse the job folder to check the result, or select another batch.';
        review();
        viewer?.dispose(); viewer = null; $('[data-browse-pane]').replaceChildren(); delete $('[data-browse-pane]')._jobFiles;
      } catch (error) { message(error.message || String(error), 'error'); }
      finally { controls(false); }
    };
    $('[data-cc]').onclick = () => pullCompanyCam?.();
    if(cardId)for(const [selector,jobAction] of [['[data-cc]','companycam'],['[data-trello]','trello_attachments']]){
      const button=$(selector);button.dataset.popoutTool='pipeline';
      button.dataset.popoutContext=JSON.stringify({cardId,client,division:data.selected_division||'EMS',jobAction});
    }
    $('[data-trello]').onclick = async () => {
      try {
        if (!window.openTrelloAttachmentsModal) throw Error('Attachment picker unavailable. Reopen Jobs and try again.');
        await window.openTrelloAttachmentsModal({cardId, client, division:data.selected_division||'EMS', onAfter:()=>{
          viewer?.dispose(); viewer=null; $('[data-browse-pane]').replaceChildren(); delete $('[data-browse-pane]')._jobFiles;
        }});
      } catch (error) { message(error.message); }
    };
    host.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => {
      const browse = button.dataset.tab === 'browse';
      $('[data-import-pane]').hidden = browse; $('[data-browse-pane]').hidden = !browse;
      host.querySelectorAll('[data-tab]').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
      if (browse) {
        if (!window.JobFiles) { message('File viewer unavailable. Reopen Jobs and try again.'); return; }
        viewer ||= window.JobFiles.mount($('[data-browse-pane]'), {client, cardId, division:data.selected_division||'EMS', attachments: data.attachments || []});
        viewer.activate();
      }
    });
    const close = () => {
      if (busy) return;
      closed = true; revision++; viewer?.dispose(); host.remove();
      clearTimeout(dropTimer); clearTimeout(registrationTimer); dropPending = false;
      window.removeEventListener('import-files-dropped', receiveDrop);
      Promise.resolve(api.import_drop_target?.(dropToken, false)).catch(() => {});
      document.removeEventListener('keydown', key, true); origin?.focus();
    };
    function key(event) {
      if (document.querySelector('.modal-scrim:last-child') !== host) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
      if (event.key === 'Tab') {
        const nodes = [...host.querySelectorAll('button,input,select')].filter(el => !el.disabled && el.getClientRects().length);
        const first = nodes[0], last = nodes.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener('keydown', key, true);
    $('[data-close]').onclick = close;
    controls(false); $('[data-scan]').focus();
    return {close};
  }
};
