/* Read-only browser: listing and previews never trigger a workspace/Trello audit. */
window.JobFiles = (() => {
  function mount(host, options) {
    if (!host || host._jobFiles) return host?._jobFiles;
    let context = options, rows = [], relative = '', filter = 'all', source = 'folder';
    let view='list', sort='name', history=[], recursive=false;
    const scrollPositions=new Map(),thumbnailCache=new Map();
    let searchFrame=0;
    const folders=new Map();
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
    host.classList.add('job-explorer');
    const heading=document.createElement('div');heading.className='section-title-row';
    heading.innerHTML='<h3>Files</h3><div><button class="btn compact" data-files-manage>Manage folder link</button> <button class="btn compact" data-files-import>＋ Import files</button></div>';
    host.prepend(heading);
    heading.querySelector('[data-files-import]').onclick=()=>host.closest('.audit-card')?.querySelector('[data-import-files]')?.click();
    heading.querySelector('[data-files-manage]').onclick=()=>host.closest('.audit-card')?.querySelector('[data-repin-job-folder]')?.click();
    const all=document.createElement('button');all.type='button';all.dataset.library='all';all.textContent='All files';all.setAttribute('aria-pressed','true');
    host.querySelector('[data-library="photo"]').setAttribute('aria-pressed','false');
    host.querySelector('[aria-label="File library"]').prepend(all);
    const toolbar=document.createElement('div');toolbar.className='job-explorer-tools';
    toolbar.innerHTML='<button type="button" data-back aria-label="Back to previous folder" disabled>←</button><button type="button" data-up aria-label="Up one folder" disabled>↑</button><input type="search" data-find placeholder="Search this folder" aria-label="Search files"><label><input type="checkbox" data-recursive> Subfolders</label><select data-sort aria-label="Sort files"><option value="name">Name A–Z</option><option value="newest">Newest first</option><option value="size">Largest first</option><option value="type">File type</option></select><button type="button" data-view aria-pressed="false">Thumbnails</button>';
    host.querySelector('.job-files-path').before(toolbar);
    const layout=document.createElement('div');layout.className='job-explorer-layout';
    const sidebar=document.createElement('nav');sidebar.className='job-explorer-folders';sidebar.setAttribute('aria-label','Job folders');
    const center=document.createElement('div');center.className='job-explorer-center';
    list.before(layout);center.append(list);layout.append(sidebar,center,preview);
    const find=toolbar.querySelector('[data-find]');
    const dates=document.createElement('details');dates.className='job-file-dates';
    dates.innerHTML='<summary>Date range</summary><div><label>From <input type="date" data-date-from></label><label>Through <input type="date" data-date-to></label><button type="button" data-clear-dates>Clear dates</button><small>Modified date · folders remain visible</small></div>';
    toolbar.append(dates);
    const dateMatch=row=>{
      const from=dates.querySelector('[data-date-from]').value,to=dates.querySelector('[data-date-to]').value;
      if(row.directory||(!from&&!to))return true;
      if(!row.modified)return false;
      const d=new Date(row.modified*1000),day=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      return (!from||day>=from)&&(!to||day<=to);
    };
    dates.addEventListener('input',()=>render());
    dates.querySelector('[data-clear-dates]').onclick=()=>{dates.querySelectorAll('input').forEach(x=>x.value='');render();};
    function renderFolders(){
      sidebar.replaceChildren();
      for(const [path,name] of [['','Job folder'],...folders]){
        const b=document.createElement('button');b.type='button';b.textContent=name;b.title=path||'Job folder';
        b.style.paddingLeft=`${10+Math.min(3,path.split('/').length-1)*10}px`;
        if(source==='folder'&&path===relative)b.setAttribute('aria-current','page');
        b.onclick=()=>{source='folder';load(path,false,false);};sidebar.append(b);
      }
      toolbar.querySelector('[data-back]').disabled=!history.length;
      toolbar.querySelector('[data-up]').disabled=!relative||source!=='folder';
    }
    const visibleRows=()=>rows.filter(row=>(source==='trello'||filter==='all'||(row.directory?!folderKind(row.name)||folderKind(row.name)===filter:row.kind===filter||filter==='document'&&row.kind==='file'))&&String(row.relative||row.name).toLowerCase().includes(find.value.trim().toLowerCase())).sort((a,b)=>Number(!!b.directory)-Number(!!a.directory)||(sort==='size'?(b.size||0)-(a.size||0):sort==='newest'?(b.modified||0)-(a.modified||0):sort==='type'?String(a.kind).localeCompare(String(b.kind)):0)||a.name.localeCompare(b.name,undefined,{numeric:true}));
    let catalogSequence = 0, disposed = false;
    const catalogButton = document.createElement('button');
    catalogButton.type = 'button'; catalogButton.className = 'text-btn';
    catalogButton.textContent = 'Preview file mapping'; catalogButton.hidden = true;
    const catalog = document.createElement('section'); catalog.className = 'job-file-catalog'; catalog.hidden = true;
    catalog.setAttribute('aria-label', 'File mapping preview');
    host.append(catalogButton, catalog);
    Promise.resolve().then(()=>api().personal_preferences?.()).then(prefs=>{
      if (!disposed && prefs?.job_views_trial) catalogButton.hidden = false;
    }).catch(()=>{});
    catalogButton.onclick = async () => {
      const request = ++catalogSequence;
      catalog.hidden = false; catalog.replaceChildren(); catalog.setAttribute('aria-busy','true');
      catalog.textContent = 'Reading file metadata… No files will be changed.'; catalogButton.disabled = true;
      try {
        const result = await api().job_file_catalog_preview(context.client, context.cardId || '');
        if (request !== catalogSequence || disposed || !host.isConnected) return;
        if (!result?.ok) throw Error(result?.error || 'Mapping preview unavailable.');
        catalog.replaceChildren();
        const heading = document.createElement('strong'); heading.textContent = 'File mapping · Dev preview';
        const note = document.createElement('p'); note.textContent = result.note;
        const identity = document.createElement('p'); identity.textContent = `Saved job: ${result.job_id}`;
        const summary = document.createElement('p');
        summary.textContent = `${result.files.length} files · ${result.issues.length} skipped or unavailable${result.limited?' · Scan limit reached':''}`;
        const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Find a file or folder'; search.setAttribute('aria-label','Search file mapping');
        const rows = document.createElement('div'); rows.className = 'job-file-catalog-rows';
        const renderCatalog = () => {
          rows.replaceChildren(); const query = search.value.trim().toLowerCase();
          for (const file of result.files.filter(file=>file.relative.toLowerCase().includes(query))) {
            const row = document.createElement('div');
            const title = document.createElement('strong'); title.textContent = file.relative;
            const detail = document.createElement('small'); detail.textContent = `${file.category} · ${file.availability} · ${Math.ceil(file.size/1024)} KB`;
            row.append(title, detail); rows.append(row);
          }
          if (!rows.children.length) rows.textContent = 'No files match this preview.';
        };
        search.oninput = renderCatalog; renderCatalog();
        const issues = document.createElement('details');
        const label = document.createElement('summary'); label.textContent = 'Review skipped or unavailable items'; issues.append(label);
        for (const issue of result.issues) { const row = document.createElement('p'); row.textContent = `${issue.relative}: ${issue.reason}`; issues.append(row); }
        const close = document.createElement('button'); close.type = 'button'; close.className = 'btn compact'; close.textContent = 'Close preview'; close.onclick=()=>{catalog.hidden=true;catalogButton.focus();};
        catalog.append(heading,note,identity,summary,search,rows);
        if (result.issues.length) catalog.append(issues);
        catalog.append(close);
      } catch (error) {
        if (request === catalogSequence && !disposed) catalog.textContent = error.message || String(error);
      } finally {
        if (request === catalogSequence && !disposed) {catalogButton.disabled=false;catalog.setAttribute('aria-busy','false');}
      }
    };
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
              const album = await api().job_files(context.client, row.relative, false, context.cardId || '');
              if (request !== sequence || !icon.isConnected || !album?.ok) return;
              const photos = (album.files || []).filter(item=>item.kind==='photo');
              const folders = (album.files || []).filter(item=>item.directory);
              detail.textContent = `${photos.length}${album.truncated?'+':''} ${photos.length===1?'photo':'photos'}${folders.length?' · '+folders.length+' folders':''}`;
              photo = photos.find(item=>!item.offline);
              if (!photo) return;
            }
            const cacheKey=`${photo.relative}:${photo.modified||''}:${photo.size||''}`;
            let result=thumbnailCache.get(cacheKey);
            if(!result){result=await api().job_file_preview(context.client, photo.relative, true, context.cardId || '');if(result?.ok){if(thumbnailCache.size>=200)thumbnailCache.delete(thumbnailCache.keys().next().value);thumbnailCache.set(cacheKey,result);}}
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
      host.classList.remove('has-file-preview');
    }
    function attachmentRows() {
      return (context.attachments || []).map(a => ({name:a.name || 'Attachment', url:a.url,
        kind:/\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(a.name || '') ? 'photo' : 'document'}));
    }
    function renderShortcuts() {
      const nav = host.querySelector('.job-file-breadcrumbs'); nav.replaceChildren();
      const root = document.createElement('button'); root.type='button';root.textContent=source==='trello'?'Trello attachments':'Job folder';
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
      const savedScroll=list.scrollTop;
      renderShortcuts();
      renderFolders();
      thumbnailObserver?.disconnect(); thumbnailQueue = [];
      thumbnailObserver = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          thumbnailObserver.unobserve(entry.target);
          thumbnailQueue.push({row:entry.target._fileRow, icon:entry.target.firstChild, detail:entry.target.querySelector('small'), request:sequence});
        }
        pumpThumbnails();
      }, {root:list});
      const fragment=document.createDocumentFragment();
      list.classList.toggle('is-documents',view==='list');
      list.classList.toggle('is-detail-list',view==='list');
      const visible = visibleRows().filter(dateMatch);
      for (const row of visible) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'job-file-row';
        if (row.kind === 'photo') button.classList.add('job-file-photo');
        if (row.directory) button.classList.add('job-file-folder');
        const icon = document.createElement('span'); icon.textContent = row.directory ? '▱' : row.kind === 'photo' ? '▧' : '▤'; icon.setAttribute('aria-hidden','true');
        if (row.directory) icon.innerHTML='<svg width="40" height="32" viewBox="0 0 40 32" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 8V5a2 2 0 0 1 2-2h10l4 5h16a2 2 0 0 1 2 2v17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z"/><path d="M3 10h34"/></svg>';
        const name = document.createElement('strong'); name.textContent = row.name;
        const detail = document.createElement('small'); detail.textContent = row.url ? 'Trello attachment · opens in browser' : row.directory ? view==='list'?'—':filter==='photo'?'Open album':'Folder' : row.offline ? 'Online-only' : `${Math.ceil(row.size / 1024)} KB`;
        button.append(icon, name, detail);
        button.title=row.relative||row.name;
        const type=document.createElement('small');type.className='file-type';type.textContent=row.directory?'Folder':row.name.split('.').pop().toUpperCase();
        const modified=document.createElement('small');modified.className='file-modified';modified.textContent=row.modified?new Date(row.modified*1000).toLocaleDateString():'—';
        button.append(type,modified);
        button.addEventListener('click', () => row.directory ? load(row.relative) : show(row));
        fragment.append(button);
        if (view==='grid'&&(row.kind === 'photo' || row.directory && filter==='photo') && !row.url && !row.offline) {button._fileRow = row; thumbnailObserver.observe(button);}
      }
      list.replaceChildren(fragment);list.scrollTop=savedScroll;
      let count=center.querySelector('[data-visible-count]');if(!count){count=document.createElement('p');count.dataset.visibleCount='';center.prepend(count);}
      count.textContent=visible.length?`${visible.length} items${find.value?' matching search':''}`:'No matching files in this location.';
    }
    async function load(path = relative, refresh = false, resolveLibrary = true, remember=true) {
      scrollPositions.set(relative,list.scrollTop);
      const sameFolder=path===relative;
      if(remember&&path!==relative)history.push(relative);
      const request = ++sequence;if(!sameFolder)closePreview();
      if(refresh)thumbnailCache.clear();
      relative = path; loaded = true; thumbnailQueue = []; thumbnailObserver?.disconnect();
      if(!sameFolder){rows=[];list.replaceChildren();}
      status.textContent = source === 'folder' ? 'Loading folder…' : '';
      list.setAttribute('aria-busy', 'true');
      host.querySelector('[data-files-refresh]').disabled = true;
      host.querySelector('[data-folder-open]').disabled = true;
      try {
        const result = source === 'trello' ? {ok:true,files:attachmentRows()} : await api().job_files(context.client, path, refresh, context.cardId || '');
        if (request !== sequence || !host.isConnected) return;
        rows = result?.ok ? result.files || [] : [];
        for(const row of rows)if(row.directory)folders.set(row.relative,row.name);
        const library = rows.filter(row=>row.directory && folderKind(row.name)===filter);
        if(source==='folder' && result?.ok && resolveLibrary && !path && filter!=='all' && !library.length){
          const division=String(context.division||'EMS').toUpperCase();
          const section=rows.find(row=>row.directory && row.name.toUpperCase()===division);
          if(section){await load(section.relative,refresh);return;}
        }
        if (source==='folder' && result?.ok && resolveLibrary && library.length===1 && library[0].relative!==path) { await load(library[0].relative,refresh);return; }
        host.querySelector('[data-folder-open]').disabled = source !== 'folder' || !result?.ok;
        status.textContent = result?.ok ? result.truncated ? 'Showing the first 2,000 items. Open a subfolder to narrow the list.' : '' : result?.error || 'Files could not be loaded. Retry with Refresh files.';
        host.querySelector('[data-files-refresh]').title = result?.checked_at ? `Refresh files · last checked ${new Date(result.checked_at).toLocaleString()}` : 'Refresh files';
        if (result?.warning) status.textContent += ' ' + result.warning;
        if(recursive&&source==='folder'&&result?.ok){
          const queue=rows.filter(r=>r.directory).map(r=>r.relative),seen=new Set([path]);let scanned=0,skipped=0;
          while(queue.length&&scanned<100&&rows.length<5000){
            const folder=queue.shift();if(seen.has(folder))continue;seen.add(folder);scanned++;
            status.textContent=`Searching subfolders… ${scanned} folders`;
            const child=await api().job_files(context.client,folder,refresh,context.cardId || '');
            if(request!==sequence||disposed)return;
            if(!child?.ok){skipped++;continue;}
            if(child.truncated)skipped++;
            rows.push(...(child.files||[]).slice(0,5000-rows.length));queue.push(...(child.files||[]).filter(r=>r.directory&&!r.offline).map(r=>r.relative));
          }
          status.textContent=`${queue.length?'Search limit reached. Open a narrower folder. ':''}${skipped?`${skipped} folders incomplete or unavailable. `:''}${result.truncated?'Top folder listing limited. ':''}`;
        }
        render();
        list.scrollTop=scrollPositions.get(path)||0;
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
          const result = await api().job_file_open(context.client, selected.relative, context.cardId || '');
          if (!result?.ok) throw Error(result?.error || 'File could not be opened.');
        }
      } catch (error) { status.textContent = error.message || String(error); }
    }
    async function show(row) {
      closePreview(); selected = row;
      if (row.url) { await openSelected(); return; }
      preview.hidden = false; host.querySelector('[data-preview-name]').textContent = row.name;
      host.classList.add('has-file-preview');
      content.textContent = 'Loading preview…';
      const photos = visibleRows().filter(item => item.kind === 'photo');
      const index = photos.indexOf(row);
      host.querySelector('[data-file-previous]').disabled = index <= 0;
      host.querySelector('[data-file-next]').disabled = index < 0 || index >= photos.length - 1;
      const request = ++previewSequence;
      try {
        const result = await api().job_file_preview(context.client, row.relative, false, context.cardId || '');
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
    find.oninput=()=>{cancelAnimationFrame(searchFrame);searchFrame=requestAnimationFrame(()=>{list.scrollTop=0;render();});};
    toolbar.querySelector('[data-sort]').onchange=e=>{sort=e.target.value;render();};
    toolbar.querySelector('[data-view]').onclick=e=>{view=view==='list'?'grid':'list';e.currentTarget.setAttribute('aria-pressed',String(view==='grid'));render();};
    toolbar.querySelector('[data-recursive]').onchange=e=>{recursive=e.target.checked;load(relative,false,false);};
    toolbar.querySelector('[data-back]').onclick=()=>{if(history.length)load(history.pop(),false,false,false);};
    toolbar.querySelector('[data-up]').onclick=()=>load(relative.split(/[\\/]/).slice(0,-1).join('/'),false,false);
    host.querySelector('[data-folder-open]').onclick = async event => {
      const button = event.currentTarget, request = sequence; button.disabled = true;
      try {
        const result = await api().job_folder_open(context.client, relative, context.cardId || '');
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
      const photos = visibleRows().filter(row => row.kind === 'photo'); const row = photos[photos.indexOf(selected) + delta]; if (row) show(row);
    };
    function resetFolder(){
      sequence++;previewSequence++;closePreview();rows=[];relative='';source='folder';history=[];folders.clear();find.value='';
      scrollPositions.clear();thumbnailCache.clear();thumbnailQueue=[];loaded=false;
      if(host.isConnected)load('',true);
    }
    host._jobFiles = {reset:resetFolder, activate() { if (host.isConnected) load(relative,true); }, update(next) { const changed=context.cardId!==next.cardId||context.division!==next.division;catalogSequence++;catalog.hidden=true;catalog.replaceChildren();catalogButton.disabled=false;context = next; if(changed){resetFolder();return;} if (source === 'trello') { rows = attachmentRows(); status.textContent = ''; render(); } }, dispose() { disposed=true;catalogSequence++;sequence++; thumbnailQueue=[]; thumbnailObserver?.disconnect(); closePreview(); }};
    return host._jobFiles;
  }
  return {mount};
})();
