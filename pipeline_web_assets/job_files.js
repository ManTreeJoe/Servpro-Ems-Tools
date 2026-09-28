/* Read-only browser: listing and previews never trigger a workspace/Trello audit. */
window.JobFiles = (() => {
  function mount(host, options) {
    if (!host || host._jobFiles) return host?._jobFiles;
    let context = options, rows = [], relative = '', filter = 'all', source = 'folder';
    let sequence = 0, previewSequence = 0, objectUrl = '', loaded = false;
    const api = () => window.pywebview.api;
    host.innerHTML = `<div class="section-title-row"><div><h3>Job files</h3><small>Browse files without running an audit</small></div><button class="btn compact" data-files-refresh>Refresh files</button></div>
      <div class="job-files-tools"><label>Source <select data-files-source><option value="folder">Job folder</option><option value="trello">Trello attachments</option></select></label>
      <div role="group" aria-label="File type"><button class="btn compact" data-file-filter="all" aria-pressed="true">All files</button><button class="btn compact" data-file-filter="photo" aria-pressed="false">Photos</button><button class="btn compact" data-file-filter="document" aria-pressed="false">Documents</button></div></div>
      <div class="job-files-path"><button class="btn compact" data-files-up disabled>↑ Up</button><span data-files-path>Job folder</span></div>
      <p data-files-status role="status">Open Files to load the folder.</p><div class="job-files-list"></div>
      <div class="job-file-preview" hidden><div class="job-file-preview-tools"><strong data-preview-name></strong><button class="btn compact" data-file-previous aria-label="Previous photo">←</button><button class="btn compact" data-file-next aria-label="Next photo">→</button><button class="btn compact" data-file-open>Open in app ↗</button><button class="btn compact" data-preview-close>Close preview</button></div><div data-preview-content></div></div>`;
    const status = host.querySelector('[data-files-status]'), list = host.querySelector('.job-files-list');
    const preview = host.querySelector('.job-file-preview'), content = host.querySelector('[data-preview-content]');
    let selected = null;
    let thumbnailObserver = null, thumbnailQueue = [], thumbnailActive = 0;
    async function pumpThumbnails() {
      while (thumbnailActive < 2 && thumbnailQueue.length) {
        const {row, icon, request} = thumbnailQueue.shift();
        if (request !== sequence || !icon.isConnected) continue;
        thumbnailActive++;
        (async () => {
          try {
            const result = await api().job_file_preview(context.client, row.relative, true);
            if (request !== sequence || !icon.isConnected || !result?.ok || !result.mime?.startsWith('image/')) return;
            const image = document.createElement('img'); image.alt = ''; image.src = `data:${result.mime};base64,${result.content}`;
            icon.replaceChildren(image);
          } catch (_) { /* A failed thumbnail never hides the file or blocks opening it. */ }
          finally { thumbnailActive--; pumpThumbnails(); }
        })();
      }
    }
    function closePreview() {
      previewSequence++;
      content.replaceChildren(); preview.hidden = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = '';
    }
    function attachmentRows() {
      return (context.attachments || []).map(a => ({name:a.name || 'Attachment', url:a.url,
        kind:/\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(a.name || '') ? 'photo' : 'document'}));
    }
    function render() {
      thumbnailObserver?.disconnect(); thumbnailQueue = [];
      thumbnailObserver = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          thumbnailObserver.unobserve(entry.target);
          thumbnailQueue.push({row:entry.target._fileRow, icon:entry.target.firstChild, request:sequence});
        }
        pumpThumbnails();
      }, {root:list});
      list.replaceChildren();
      const visible = rows.filter(row => row.directory || filter === 'all' || row.kind === filter);
      for (const row of visible) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'job-file-row';
        if (row.kind === 'photo') button.classList.add('job-file-photo');
        const icon = document.createElement('span'); icon.textContent = row.directory ? '▸' : row.kind === 'photo' ? '▧' : '▤'; icon.setAttribute('aria-hidden','true');
        const name = document.createElement('strong'); name.textContent = row.name;
        const detail = document.createElement('small'); detail.textContent = row.url ? 'Trello attachment · opens in browser' : row.directory ? 'Folder' : row.offline ? 'Job folder · online-only' : `Job folder · ${Math.ceil(row.size / 1024)} KB`;
        button.append(icon, name, detail);
        button.addEventListener('click', () => row.directory ? load(row.relative) : show(row));
        list.append(button);
        if (row.kind === 'photo' && !row.url && !row.offline) {button._fileRow = row; thumbnailObserver.observe(button);}
      }
      if (!visible.length && !status.textContent) status.textContent = 'No matching files in this location.';
      host.querySelector('[data-files-path]').textContent = source === 'trello' ? 'Linked card attachments' : relative && relative !== '.' ? relative : 'Job folder';
      host.querySelector('[data-files-up]').disabled = source !== 'folder' || !relative || relative === '.';
    }
    async function load(path = relative, refresh = false) {
      const request = ++sequence; closePreview();
      relative = path; loaded = true; rows = []; thumbnailQueue = []; thumbnailObserver?.disconnect(); list.replaceChildren();
      status.textContent = source === 'folder' ? 'Loading folder…' : '';
      list.setAttribute('aria-busy', 'true');
      host.querySelector('[data-files-refresh]').disabled = true;
      try {
        const result = source === 'trello' ? {ok:true,files:attachmentRows()} : await api().job_files(context.client, path, refresh);
        if (request !== sequence || !host.isConnected) return;
        rows = result?.ok ? result.files || [] : [];
        status.textContent = result?.ok ? result.truncated ? 'Showing the first 2,000 items. Open a subfolder to narrow the list.' : '' : result?.error || 'Files could not be loaded. Retry with Refresh files.';
        if (result?.ok && result.checked_at) status.textContent += `${result.cached ? ' Saved listing' : ' Checked'} ${new Date(result.checked_at).toLocaleString()}. ${result.cached ? 'Use Refresh files to check for changes.' : ''}`;
        if (result?.warning) status.textContent += ' ' + result.warning;
        render();
      } catch (error) { if (request === sequence) status.textContent = `Files could not be loaded: ${error.message || error}`; }
      finally { if (request === sequence) { list.setAttribute('aria-busy','false'); host.querySelector('[data-files-refresh]').disabled = false; } }
    }
    async function openSelected() {
      if (!selected) return;
      try {
        if (selected.url) {
          const url = new URL(selected.url);
          if (!['https:', 'http:'].includes(url.protocol)) throw Error('This attachment link is not supported.');
          await api().open_url(url.href);
        } else {
          const result = await api().job_file_open(context.client, selected.relative);
          if (!result?.ok) throw Error(result?.error || 'File could not be opened.');
        }
      } catch (error) { status.textContent = error.message || String(error); }
    }
    async function show(row) {
      closePreview(); selected = row;
      if (row.url) { await openSelected(); return; }
      preview.hidden = false; host.querySelector('[data-preview-name]').textContent = row.name;
      content.textContent = 'Loading preview…';
      const photos = rows.filter(item => item.kind === 'photo');
      const index = photos.indexOf(row);
      host.querySelector('[data-file-previous]').disabled = index <= 0;
      host.querySelector('[data-file-next]').disabled = index < 0 || index >= photos.length - 1;
      const request = ++previewSequence;
      try {
        const result = await api().job_file_preview(context.client, row.relative);
        if (request !== previewSequence || !host.isConnected) return;
        if (!result?.ok) throw Error(result?.error || 'Preview unavailable.');
        if (result.external) { content.textContent = 'Use Open in app to view this file.'; return; }
        const bytes = Uint8Array.from(atob(result.content), c => c.charCodeAt(0));
        objectUrl = URL.createObjectURL(new Blob([bytes], {type:result.mime}));
        const media = document.createElement(result.mime === 'application/pdf' ? 'iframe' : 'img');
        if (media.tagName === 'IMG') { media.alt = row.name; media.onerror = () => {content.textContent = 'This image could not be displayed. Use Open in app.';}; }
        else media.title = row.name;
        media.src = objectUrl; content.replaceChildren(media);
      } catch (error) { if (request === previewSequence) content.textContent = error.message || String(error); }
    }
    host.querySelector('[data-files-refresh]').onclick = () => load(relative, true);
    host.querySelector('[data-files-source]').onchange = event => { source = event.target.value; load(''); };
    host.querySelector('[data-files-up]').onclick = () => load(relative.split(/[\\/]/).slice(0,-1).join('/'));
    host.querySelector('[data-preview-close]').onclick = closePreview;
    host.querySelector('[data-file-open]').onclick = openSelected;
    for (const [selector, delta] of [['[data-file-previous]', -1], ['[data-file-next]', 1]]) host.querySelector(selector).onclick = () => {
      const photos = rows.filter(row => row.kind === 'photo'); const row = photos[photos.indexOf(selected) + delta]; if (row) show(row);
    };
    host.querySelectorAll('[data-file-filter]').forEach(button => button.onclick = () => {
      filter = button.dataset.fileFilter;
      host.querySelectorAll('[data-file-filter]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
      if (rows.length) status.textContent = ''; render();
    });
    host._jobFiles = {activate() { if (!loaded && host.isConnected) load(); }, update(next) { context = next; if (source === 'trello') { rows = attachmentRows(); status.textContent = ''; render(); } }, dispose() { sequence++; thumbnailQueue=[]; thumbnailObserver?.disconnect(); closePreview(); }};
    return host._jobFiles;
  }
  return {mount};
})();
