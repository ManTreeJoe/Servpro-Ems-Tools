/* Select -> temporary PDF preview -> explicit save to this section's DOCS. */
window.PhotoReportBuilder = {open(client, jobPath, division, cardId = '') {
  const api=window.pywebview.api, previous=document.activeElement;
  const modal=document.createElement('div'); modal.className='modal-scrim audit-overlay photo-report-builder';
  modal.innerHTML=`<section class="import-workspace-card" role="dialog" aria-modal="true" aria-label="Photo report builder">
    <header><div><h2>Photo report</h2><p data-job></p></div><button class="btn" data-close aria-label="Close report builder">×</button></header>
    <main class="report-builder-body"><p>Cover page + four numbered photos per page. Photos keep their proportions; nothing is cropped.</p>
    <div class="report-builder-fields"><label>Report title<input data-title maxlength="120" value="Photo Report"></label><label>Report date<input data-date type="date"></label><label>Property address<input data-address maxlength="200" placeholder="Confirm the property address"></label></div>
    <div class="import-sources"><button class="btn" data-load>Load photos</button><button class="btn" data-select>Select all</button><button class="btn" data-clear>Clear selection</button><span data-count>0 selected</span></div>
    <div class="import-sources"><label>From<input type="date" data-photo-from></label><label>Through<input type="date" data-photo-through></label><button class="btn" data-reset-dates>Clear dates</button><span data-range-status role="status"></span></div>
    <div class="cc-photo-scroll"><div class="cc-photo-days" data-photos></div><button class="btn" data-more hidden>Load older photos</button></div>
    <details><summary>Selected order & captions</summary><p>Use the arrows to arrange the report. The cover also remains in the numbered photos.</p><div data-order></div></details>
    <label>Final notes (optional)<textarea data-notes maxlength="2500" rows="3"></textarea></label>
    </main><footer><p data-status role="status" aria-live="polite">Select the photos you want. Nothing is saved to the job until you confirm.</p><div class="import-sources"><button class="btn" data-preview disabled>Build PDF preview</button><button class="btn" data-open hidden>Open preview</button><button class="btn btn-primary" data-save disabled>Save to DOCS</button></div></footer>
    </section>`;
  document.body.append(modal); const q=s=>modal.querySelector(s);
  if(cardId){const header=q('header');header.dataset.popoutTool='pipeline';header.dataset.popoutContext=JSON.stringify({cardId,client,division,jobAction:'photo_report'});header.title='Open a fresh report window; current selections stay here.';}
  q('[data-job]').textContent=`${client} · ${division}`;
  const now=new Date(); q('[data-date]').value=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  let photos=[], selected=[], cover='', project='', draft=null, busy=false, closed=false, captions={}, saving=false, dirty=false;
  let visibleCount=36, catalogReady=false;
  const dateOf=p=>p.captured_at?new Date(p.captured_at*1000):new Date(p.date);
  const dayOf=p=>Number.isNaN(dateOf(p).getTime())?'Unknown date':dateOf(p).toLocaleDateString();
  const personOf=p=>p.creator||'Unknown photographer';
  const filtered=()=>photos.filter(p=>{
    const from=q('[data-photo-from]').value,to=q('[data-photo-through]').value;
    if(!from&&!to)return true;
    const d=dateOf(p);if(Number.isNaN(d.getTime()))return false;
    const key=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    return (!from||key>=from)&&(!to||key<=to);
  });
  const message=t=>q('[data-status]').textContent=t;
  const controls=()=>{modal.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=busy);q('[data-close]').disabled=saving;q('[data-preview]').disabled=busy||!selected.length;q('[data-save]').disabled=busy||!draft;modal.setAttribute('aria-busy',String(busy));};
  const changed=()=>{dirty=true;draft=null;q('[data-open]').hidden=true;q('[data-save]').textContent='Save to DOCS'; controls();};
  const button=(text,action)=>{const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=text;b.onclick=action;return b;};
  function render(){
    const list=q('[data-photos]');list.replaceChildren();
    const groups=new Map();
    const toggle=ids=>{const remove=ids.every(id=>selected.includes(id));selected=remove?selected.filter(id=>!ids.includes(id)):[...new Set([...selected,...ids])];if(!selected.includes(cover))cover=selected[0]||'';changed();render();};
    const matching=filtered();
    q('[data-range-status]').textContent=q('[data-photo-from]').value>q('[data-photo-through]').value&&q('[data-photo-through]').value?'From must be on or before Through.':`${matching.length} matching photos · selections are kept when filtering`;
    for(const photo of matching.slice(0,visibleCount)){
      const day=dayOf(photo),person=personOf(photo);
      if(!groups.has(day)){
        const section=document.createElement('section');section.className='cc-photo-day';
        const heading=document.createElement('header'),title=document.createElement('h3');title.textContent=day;
        const ids=photos.filter(p=>dayOf(p)===day).map(p=>p.id),all=ids.every(id=>selected.includes(id));
        const select=button(`${all?'Deselect day':'Select whole day'} (${ids.length})`,()=>toggle(ids));select.setAttribute('aria-pressed',String(all));
        heading.append(title,select);section.append(heading);list.append(section);groups.set(day,{section,people:new Map()});
      }
      const group=groups.get(day);
      if(!group.people.has(person)){
        const section=document.createElement('section');section.className='cc-photo-person';
        const heading=document.createElement('h4'),label=document.createElement('label');label.className='cc-photo-person-select';
        const ids=photos.filter(p=>dayOf(p)===day&&personOf(p)===person).map(p=>p.id),count=ids.filter(id=>selected.includes(id)).length;
        const check=document.createElement('input');check.type='checkbox';check.checked=count===ids.length;check.indeterminate=count>0&&count<ids.length;check.setAttribute('aria-label',`Select all photos by ${person} on ${day}`);check.onchange=()=>toggle(ids);
        label.append(person,check);heading.append(label);const grid=document.createElement('div');grid.className='cc-photo-grid';section.append(heading,grid);group.section.append(section);group.people.set(person,grid);
      }
      const tile=document.createElement('article');tile.className='cc-photo-tile';
      const check=document.createElement('input');check.type='checkbox';check.checked=selected.includes(photo.id);check.setAttribute('aria-label',`Include photo ${photo.id}`);
      check.onchange=()=>{if(check.checked)selected.push(photo.id);else selected=selected.filter(id=>id!==photo.id);if(!selected.includes(cover))cover=selected[0]||'';changed();render();};
      const img=document.createElement('img');img.src=photo.preview_url||photo.url;img.alt='';img.loading='lazy';
      const preview=button('',()=>window.openImportImagePreview?.({title:photo.date||'Photo',source:photo.url}));preview.className='cc-photo-preview';preview.setAttribute('aria-label',`Preview photo ${photo.id}`);preview.append(img);
      const date=document.createElement('small');date.textContent=[photo.date,photo.creator].filter(Boolean).join(' · ');
      const chooseCover=button(cover===photo.id?'✓ Cover':'Use as cover',()=>{if(!selected.includes(photo.id))selected.push(photo.id);cover=photo.id;changed();render();});
      tile.append(check,preview,date,chooseCover);group.people.get(person).append(tile);
    }
    q('[data-count]').textContent=`${selected.length} of ${photos.length} selected`;
    if(catalogReady)q('[data-more]').hidden=visibleCount>=matching.length;
    const order=q('[data-order]');order.replaceChildren();
    selected.forEach((id,index)=>{
      const photo=photos.find(p=>p.id===id),row=document.createElement('div');row.className='report-order-row';
      const title=document.createElement('span');title.textContent=`${index+1}. ${photo.date||id}`;
      const move=delta=>{const dest=index+delta;if(dest<0||dest>=selected.length)return;[selected[index],selected[dest]]=[selected[dest],selected[index]];changed();render();};
      const up=button('↑',()=>move(-1));up.setAttribute('aria-label',`Move photo ${index+1} up`);
      const down=button('↓',()=>move(1));down.setAttribute('aria-label',`Move photo ${index+1} down`);
      const caption=document.createElement('input');caption.maxLength=400;caption.value=captions[id]??photo.description??'';caption.placeholder='Optional caption';caption.setAttribute('aria-label',`Caption for photo ${index+1}`);caption.oninput=()=>{captions[id]=caption.value;changed();};
      row.append(title,up,down,caption);order.append(row);
    });controls();
  }
  async function load(){
    if(catalogReady){visibleCount+=36;render();return;}
    if(busy)return;busy=true;controls();message('Loading CompanyCam photos…');
    try{
      const r=await api.companycam_quick_report_plan(client,jobPath,division,'','','',photos.length,120,cardId);
      if(closed)return;if(!r?.ok)throw Error(r?.error||'Could not load photos.');
      if(project&&project!==String(r.project_id))throw Error('The project changed. Close and reopen the report.');
      project=String(r.project_id); const known=new Set(photos.map(p=>p.id));
      photos.push(...(r.catalog||r.photos||[]).filter(p=>!known.has(p.id)));catalogReady=Array.isArray(r.catalog)||!r.has_more;q('[data-more]').hidden=!r.has_more;q('[data-load]').hidden=true;
      if(!q('[data-address]').value&&r.address)q('[data-address]').value=r.address;
      message(photos.length?'Choose photos and a cover, then build your preview.':'No photos found for this project.');render();
    }catch(e){if(!closed)message(e.message||String(e));}finally{busy=false;if(!closed)controls();}
  }
  q('[data-load]').onclick=load;q('[data-more]').onclick=load;
  q('.cc-photo-scroll').addEventListener('scroll',()=>{const el=q('.cc-photo-scroll');if(!busy&&!q('[data-more]').hidden&&el.scrollTop+el.clientHeight>=el.scrollHeight-200)void load();});
  q('[data-select]').onclick=()=>{selected=[...new Set([...selected,...filtered().map(p=>p.id)])];cover=cover||selected[0]||'';changed();render();};
  const filterChanged=()=>{visibleCount=36;render();};
  q('[data-photo-from]').onchange=filterChanged;q('[data-photo-through]').onchange=filterChanged;
  q('[data-reset-dates]').onclick=()=>{q('[data-photo-from]').value='';q('[data-photo-through]').value='';filterChanged();};
  q('[data-clear]').onclick=()=>{selected=[];cover='';changed();render();};
  modal.querySelectorAll('[data-title],[data-date],[data-address],[data-notes]').forEach(el=>el.oninput=changed);
  q('[data-preview]').onclick=async()=>{
    if(busy||!selected.length)return;changed();busy=true;controls();message(`Building preview from ${selected.length} photos. The job folder is unchanged…`);
    try{
      const r=await api.preview_companycam_photo_report(client,jobPath,division,selected,{project_id:project,title:q('[data-title]').value,date:q('[data-date]').value,address:q('[data-address]').value,notes:q('[data-notes]').value,cover_id:cover,captions},cardId);
      if(closed)return;
      if(!r?.ok)throw Error(r?.error||'Preview failed.');draft=r;q('[data-open]').hidden=false;message(`${r.photos} photos · ${r.pages} pages ready. Open the preview, then save to DOCS.`);
      await api.open_document(r.path);
    }catch(e){if(!closed)message(e.message||String(e));}finally{busy=false;if(!closed)controls();}
  };
  q('[data-open]').onclick=()=>api.open_document(draft.path);
  q('[data-save]').onclick=async()=>{
    if(busy||!draft)return;busy=true;saving=true;controls();message('Saving reviewed report to DOCS…');
    try{const r=await api.save_companycam_photo_report(client,jobPath,division,draft.token,cardId);if(!r?.ok)throw Error(r?.error||'Save failed.');dirty=false;draft.path=r.path;q('[data-save]').textContent='Saved to DOCS';message(`✓ Saved ${r.filename} to ${division} / DOCS.`);}catch(e){message(e.message||String(e));}finally{busy=false;saving=false;controls();}
  };
  function close(){if(saving){message('Finishing the save to DOCS. Please wait before closing.');return;}if(dirty&&!window.confirm('Discard this unsaved photo report? Files already saved to DOCS will not be removed.'))return;closed=true;modal.remove();document.removeEventListener('keydown',key,true);previous?.focus();}
  function key(e){if(document.querySelector('.modal-scrim:last-child')!==modal)return;if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}if(e.key==='Tab'){const nodes=[...modal.querySelectorAll('button,input,textarea,summary')].filter(n=>!n.disabled&&n.getClientRects().length);if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0]?.focus();}}}
  document.addEventListener('keydown',key,true);q('[data-close]').onclick=close;q('[data-load]').focus();void load();
}};
