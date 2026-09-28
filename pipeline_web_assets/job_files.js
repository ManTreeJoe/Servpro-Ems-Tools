/* Read-only browser: listing and previews never trigger a workspace/Trello audit. */
window.JobFiles = (() => {
  function mount(host, options) {
    if (!host || host._jobFiles) return host?._jobFiles;
    let context = options, rows = [], relative = '', filter = 'photo', source = 'folder';
    let sequence = 0, previewSequence = 0, objectUrl = '', loaded = false;
    const folderKind = name => {
      const clean = String(name).replace(/^\d+[\s._-]*/, '').trim().toLowerCase();
      return /^(pics|pictures|photos)$/.test(clean) ? 'photo' : /^(docs|documents)$/.test(clean) ? 'document' : '';
    };
    const api = () => window.pywebview.api;
    host.innerHTML = `<div class="job-gallery-heading"><div role="group" aria-label="File library"><button type="button" data-library="photo" aria-pressed="true">Photos</button><button type="button" data-library="document" aria-pressed="false">Documents</button></div><button class="btn compact" data-files-refresh aria-label="Refresh files" title="Refresh files">↻</button></div>
      <div class="job-files-path"><nav class="job-file-breadcrumbs" aria-label="Folder location"></nav><button class="btn compact" data-folder-open disabled>Open folder ↗</button></div>
      <p data-files-status role="status">Open Files to load the folder.</p><div class="job-files-list"></div>
      <div class="job-file-preview" hidden><div class="job-file-preview-tools"><strong data-preview-name></strong><button class="btn compact" data-file-previous aria-label="Previous photo">←</button><button class="btn compact" data-file-next aria-label="Next photo">→</button><button class="btn compact" data-file-open>Open in app ↗</button><button class="btn compact" data-preview-close>Close preview</button></div><div data-preview-content></div></div><button type="button" class="text-btn job-attachments-toggle" data-attachments>Trello attachments</button>`;
    const status = host.querySelector('[data-files-status]'), list = host.querySelector('.job-files-list');
    const preview = host.querySelector('.job-file-preview'), content = host.querySelector('[data-preview-content]');
    let selected = null;
    let thumbnailObserver = null, thumbnailQueue = [], thumbnailActive = 0;
    async function pumpThumbnails() {
      while (thumbnailActive < 2 && thumbnailQueue.length) {
        const {row, icon, request, detail} = thumbnailQueue.shift();
        if (request !== sequence || !icon.isConnected) continue;
        thumbnailActive++;
        (async () => {
          try {
            let photo = row;
            if (row.directory) {
              const album = await api().job_files(context.client, row.relative, false);
              if (request !== sequence || !icon.isConnected || !album?.ok) return;
              const photos = (album.files || []).filter(item=>item.kind==='photo');
              const folders = (album.files || []).filter(item=>item.directory);
              detail.textContent = `${photos.length}${album.truncated?'+':''} ${photos.length===1?'photo':'photos'}${folders.length?' · '+folders.length+' folders':''}`;
              photo = photos.find(item=>!item.offline);
              if (!photo) return;
            }
            const result = await api().job_file_preview(context.client, photo.relative, true);
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
    function renderShortcuts() {
      const nav = host.querySelector('.job-file-breadcrumbs'); nav.replaceChildren();
      const root = document.createElement('button'); root.type='button';root.textContent=source==='trello'?'Trello attachments':filter==='photo'?'Photos':'Documents';
      root.onclick=()=>load(''); nav.append(root);
      const parts = relative.split(/[\\/]/).filter(part=>part&&part!=='.');
      parts.forEach((part,index)=>{
        if (folderKind(part)===filter) return;
        const separator=document.createElement('span');separator.textContent='/';nav.append(separator);
        const crumb=document.createElement('button');crumb.type='button';crumb.textContent=part;
        crumb.onclick=()=>load(parts.slice(0,index+1).join('/'),false,false);nav.append(crumb);
      });
      nav.lastElementChild?.setAttribute('aria-current','page');
    }
    function render() {
      renderShortcuts();
      thumbnailObserver?.disconnect(); thumbnailQueue = [];
      thumbnailObserver = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          thumbnailObserver.unobserve(entry.target);
          thumbnailQueue.push({row:entry.target._fileRow, icon:entry.target.firstChild, detail:entry.target.querySelector('small'), request:sequence});
        }
        pumpThumbnails();
      }, {root:list});
      list.replaceChildren();
      list.classList.toggle('is-documents',filter==='document');
      const visible = rows.filter(row => source==='trello' || (row.directory ? !folderKind(row.name)||folderKind(row.name)===filter : row.kind === filter || filter==='document'&&row.kind==='file'));
      for (const row of visible) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'job-file-row';
        if (row.kind === 'photo') button.classList.add('job-file-photo');
        if (row.directory) button.classList.add('job-file-folder');
        const icon = document.createElement('span'); icon.textContent = row.directory ? '▱' : row.kind === 'photo' ? '▧' : '▤'; icon.setAttribute('aria-hidden','true');
        if (row.directory) icon.innerHTML='<svg width="40" height="32" viewBox="0 0 40 32" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 8V5a2 2 0 0 1 2-2h10l4 5h16a2 2 0 0 1 2 2v17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z"/><path d="M3 10h34"/></svg>';
        const name = document.createElement('strong'); name.textContent = row.name;
        const detail = document.createElement('small'); detail.textContent = row.url ? 'Trello attachment · opens in browser' : row.directory ? filter==='photo'?'Open album':'Folder' : row.offline ? 'Online-only' : `${Math.ceil(row.size / 1024)} KB`;
        button.append(icon, name, detail);
        button.addEventListener('click', () => row.directory ? load(row.relative) : show(row));
        list.append(button);
        if ((row.kind === 'photo' || row.directory && filter==='photo') && !row.url && !row.offline) {button._fileRow = row; thumbnailObserver.observe(button);}
      }
      if (!visible.length && !status.textContent) status.textContent = 'No matching files in this location.';
    }
    async function load(path = relative, refresh = false, resolveLibrary = true) {
      const request = ++sequence; closePreview();
      relative = path; loaded = true; rows = []; thumbnailQueue = []; thumbnailObserver?.disconnect(); list.replaceChildren();
      status.textContent = source === 'folder' ? 'Loading folder…' : '';
      list.setAttribute('aria-busy', 'true');
      host.querySelector('[data-files-refresh]').disabled = true;
      host.querySelector('[data-folder-open]').disabled = true;
      try {
        const result = source === 'trello' ? {ok:true,files:attachmentRows()} : await api().job_files(context.client, path, refresh);
        if (request !== sequence || !host.isConnected) return;
        rows = result?.ok ? result.files || [] : [];
        const library = rows.filter(row=>row.directory && folderKind(row.name)===filter);
        if (source==='folder' && result?.ok && resolveLibrary && library.length===1 && library[0].relative!==path) { await load(library[0].relative,refresh);return; }
        host.querySelector('[data-folder-open]').disabled = source !== 'folder' || !result?.ok;
        status.textContent = result?.ok ? result.truncated ? 'Showing the first 2,000 items. Open a subfolder to narrow the list.' : '' : result?.error || 'Files could not be loaded. Retry with Refresh files.';
        host.querySelector('[data-files-refresh]').title = result?.checked_at ? `Refresh files · last checked ${new Date(result.checked_at).toLocaleString()}` : 'Refresh files';
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
      preview.scrollIntoView({block:'nearest'});
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
    host.querySelector('[data-folder-open]').onclick = async event => {
      const button = event.currentTarget, request = sequence; button.disabled = true;
      try {
        const result = await api().job_folder_open(context.client, relative);
        if (request === sequence && !result?.ok) status.textContent = result?.error || 'Folder could not be opened.';
      } catch (_) { if (request === sequence) status.textContent = 'Folder could not be opened. Check OneDrive and retry.'; }
      finally { if (request === sequence) button.disabled = false; }
    };
    host.querySelectorAll('[data-library]').forEach(button=>button.onclick=()=>{
      filter=button.dataset.library;source='folder';
      host.querySelectorAll('[data-library]').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));load('');
    });
    host.querySelector('[data-attachments]').onclick=()=>{source='trello';load('');};
    host.querySelector('[data-preview-close]').onclick = closePreview;
    host.querySelector('[data-file-open]').onclick = openSelected;
    for (const [selector, delta] of [['[data-file-previous]', -1], ['[data-file-next]', 1]]) host.querySelector(selector).onclick = () => {
      const photos = rows.filter(row => row.kind === 'photo'); const row = photos[photos.indexOf(selected) + delta]; if (row) show(row);
    };
    host._jobFiles = {activate() { if (!loaded && host.isConnected) load(); }, update(next) { context = next; if (source === 'trello') { rows = attachmentRows(); status.textContent = ''; render(); } }, dispose() { sequence++; thumbnailQueue=[]; thumbnailObserver?.disconnect(); closePreview(); }};
    return host._jobFiles;
  }
  return {mount};
})();
