"use strict";
document.querySelector('#upload-form').onclick=async()=>{
  if(!confirm('Choose a blank, unsigned PDF with no customer data. Scanned or flattened signatures cannot be detected automatically. Confirm you have checked every page.'))return;
  try{
    const r=await pywebview.api.form_builder_upload(true);
    if(!r.ok)throw Error(r.error);
    if(r.cancelled)return;
    formLibraryRows=null;window.formsLibraryActive=true;
    await window.renderFormsLibrary(); await window.openFormBuilder(r.id);
  }catch(e){setStatus(e.message,'error');}
};
window.openFormBuilder=async function(id){
  const previous=document.activeElement, d=document.createElement('dialog');
  d.className='form-builder';
  d.innerHTML=`<header><h2>Form field builder</h2><button data-close class="btn">Close</button></header>
    <p>Draw a box on the PDF, then choose what belongs there. Coordinates are PDF points, measured from the top left. This computer only.</p>
    <div class="builder-layout"><aside>
      <label>Page<select data-page></select></label>
      <label>Zoom<select data-zoom><option value="100">Fit width</option><option value="125">125%</option><option value="150">150%</option><option value="200">200%</option></select></label>
      <label>Information source<select data-source></select></label>
      <button data-add class="btn">+ Add field</button>
      <p>Choose the information source, then Add field or draw directly on the page. Drag the box into place.</p>
      <p>No signature, initials, consent or signing-date automation. Only place factual fields.</p>
      <label>Selected field<select data-selected><option value="">Draw a box to begin</option></select></label>
      <div class="builder-numbers">${[['x','Left'],['y','Top'],['width','Width'],['height','Height'],['font_size','Text size']].map(([k,l])=>`<label>${l}<input type="number" step="1" data-number="${k}" aria-label="${l}"></label>`).join('')}</div>
      <label><input type="checkbox" data-multiline> Multiline text</label>
      <button data-delete class="btn">Remove selected field</button>
      <button data-duplicate class="btn">Duplicate field</button>
      <button data-undo class="btn">Undo last change</button>
      <p>Drag the bottom-right corner to resize. Focus a field and use arrow keys to nudge; Shift moves 10 points.</p>
      <p data-status role="status">Loading template…</p>
      <button data-preview class="btn">Preview sample text</button>
      <button data-save class="btn">Save field map</button>
    </aside><section class="builder-scroll"><div class="builder-page"><img alt="Blank PDF page" draggable="false"><div class="builder-boxes"></div></div></section></div>`;
  document.body.append(d);d.showModal();
  const q=s=>d.querySelector(s), status=q('[data-status]');
  let data, page=0, selected='', dirty=false, busy=false;
  const history=[];
  function remember(){history.push({fields:structuredClone(data.fields),selected,page});if(history.length>40)history.shift();}
  const close=()=>{if(!busy&&(!dirty||confirm('Discard unsaved field positions?')))d.close();};
  q('[data-close]').onclick=close;d.oncancel=e=>{e.preventDefault();close();};
  d.onclose=()=>{d.remove();previous?.focus();if(window.formsLibraryActive)window.renderFormsLibrary();};
  const chosen=()=>data.fields.find(f=>f.id===selected);
  function editor(){
    const f=chosen();
    q('[data-selected]').innerHTML='<option value="">Draw a new box</option>'+data.fields.filter(f=>f.page===page).map(f=>`<option value="${esc(f.id)}">${esc(f.existing_name || data.sources[f.source])}</option>`).join('');
    q('[data-selected]').value=selected;
    d.querySelectorAll('[data-number]').forEach(i=>{i.disabled=!f||!!f.existing_name;i.value=f?Math.round(f[i.dataset.number]*10)/10:'';});
    q('[data-multiline]').disabled=!f||!!f.existing_name;q('[data-delete]').disabled=!f;
    q('[data-delete]').textContent=f?.existing_name?'Remove mapping (keep PDF field)':'Remove selected field';
    q('[data-duplicate]').disabled=!f||!!f.existing_name;q('[data-undo]').disabled=!history.length;
    q('[data-multiline]').checked=!!f?.multiline;
    if(f)q('[data-source]').value=f.source;
  }
  function paint(){
    const [w,h]=data.sizes[page];
    q('.builder-page').style.aspectRatio=`${w}/${h}`;
    q('.builder-page img').src='data:image/png;base64,'+data.pages[page];
    q('.builder-boxes').innerHTML=data.fields.filter(f=>f.page===page).map(f=>`<button type="button" class="builder-field ${selected===f.id?'selected':''}" data-field="${f.id}" title="${esc((f.existing_name?f.existing_name+' → ':'')+data.sources[f.source])}" style="left:${100*f.x/w}%;top:${100*f.y/h}%;width:${100*f.width/w}%;height:${100*f.height/h}%">${esc(f.existing_name || data.sources[f.source])}${f.existing_name?'':'<span class="builder-resize" data-resize aria-hidden="true"></span>'}</button>`).join('');
    editor();
  }
  function change(){dirty=true;status.textContent='Unsaved field positions';paint();}
  try{
    data=await pywebview.api.form_builder_load(id);if(!data.ok)throw Error(data.error);
    q('h2').textContent=data.title+' · Field builder';
    q('[data-page]').innerHTML=data.pages.map((_,i)=>`<option value="${i}">Page ${i+1}</option>`).join('');
    q('[data-source]').innerHTML=Object.entries(data.sources).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');
    paint();const count=data.fields.filter(f=>f.existing_name).length;
    status.textContent=count?`${count} existing text fields detected. Select a highlighted field and choose its information source. Original signing fields and checkboxes are preserved.`:'Draw a box, or select an existing field to move it.';
  }catch(e){status.textContent=e.message;d.querySelectorAll('aside button,aside input,aside select').forEach(e=>e.disabled=true);return;}
  q('[data-page]').onchange=e=>{page=+e.target.value;selected='';paint();};
  q('[data-zoom]').onchange=e=>{q('.builder-page').style.width=e.target.value+'%';};
  q('[data-selected]').onchange=e=>{selected=e.target.value;paint();};
  q('[data-source]').onchange=e=>{if(chosen()){remember();chosen().source=e.target.value;change();}};
  q('[data-add]').onclick=()=>{
    if(busy)return;
    remember();const [w,h]=data.sizes[page];
    const count=data.fields.filter(f=>f.page===page).length;
    selected='f_'+crypto.randomUUID().replaceAll('-','');
    data.fields.push({id:selected,page,source:q('[data-source]').value,x:Math.min(36,w-24),y:Math.min(48+count*30,h-24),width:Math.min(240,w-36),height:24,font_size:10,multiline:false});
    change();q(`[data-field="${selected}"]`)?.focus({preventScroll:true});
  };
  d.querySelectorAll('[data-number]').forEach(i=>i.onchange=()=>{if(chosen()){remember();chosen()[i.dataset.number]=Number(i.value);change();}});
  q('[data-multiline]').onchange=e=>{if(chosen()){remember();chosen().multiline=e.target.checked;change();}};
  q('[data-delete]').onclick=()=>{remember();data.fields=data.fields.filter(f=>f.id!==selected);selected='';change();};
  q('[data-duplicate]').onclick=()=>{const f=chosen();if(!f)return;remember();const [w,h]=data.sizes[page];const copy={...f,id:'f_'+crypto.randomUUID().replaceAll('-',''),x:Math.min(w-f.width,f.x+12),y:Math.min(h-f.height,f.y+24)};data.fields.push(copy);selected=copy.id;change();};
  q('[data-undo]').onclick=()=>{const old=history.pop();if(!old)return;data.fields=old.fields;selected=old.selected;page=old.page;q('[data-page]').value=String(page);change();};
  const surface=q('.builder-page');
  let drag;
  function point(e){const r=surface.getBoundingClientRect(),[w,h]=data.sizes[page];return {x:Math.max(0,Math.min(w,(e.clientX-r.left)*w/r.width)),y:Math.max(0,Math.min(h,(e.clientY-r.top)*h/r.height))};}
  surface.onpointerdown=e=>{
    if(busy||e.button!==0)return;
    remember();
    const p=point(e), field=e.target.closest('[data-field]');
    if(field && data.fields.find(f=>f.id===field.dataset.field)?.existing_name){selected=field.dataset.field;paint();return;}
    if(field){selected=field.dataset.field;drag={start:p,original:{...chosen()},moving:true,resizing:!!e.target.closest('[data-resize]')};}
    else{selected='f_'+crypto.randomUUID().replaceAll('-','');data.fields.push({id:selected,page,source:q('[data-source]').value,x:p.x,y:p.y,width:24,height:20,font_size:10,multiline:false});drag={start:p,moving:false};}
    surface.setPointerCapture(e.pointerId);e.preventDefault();paint();
  };
  surface.onpointermove=e=>{
    if(!drag)return;const p=point(e),f=chosen(),[w,h]=data.sizes[page];
    if(drag.resizing){f.width=Math.max(24,Math.min(w-f.x,drag.original.width+p.x-drag.start.x));f.height=Math.max(14,Math.min(h-f.y,drag.original.height+p.y-drag.start.y));}
    else if(drag.moving){f.x=Math.max(0,Math.min(w-f.width,drag.original.x+p.x-drag.start.x));f.y=Math.max(0,Math.min(h-f.height,drag.original.y+p.y-drag.start.y));}
    else{f.x=Math.min(p.x,drag.start.x);f.y=Math.min(p.y,drag.start.y);f.width=Math.max(24,Math.abs(p.x-drag.start.x));f.height=Math.max(20,Math.abs(p.y-drag.start.y));}
    f.x=Math.min(f.x,w-f.width);f.y=Math.min(f.y,h-f.height);change();
  };
  surface.onpointerup=()=>{if(drag){drag=null;change();q(`[data-field="${selected}"]`)?.focus({preventScroll:true});}};
  surface.onpointercancel=()=>{drag=null;};
  surface.onkeydown=e=>{
    const target=e.target.closest('[data-field]');if(!target||busy||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
    if(data.fields.find(f=>f.id===target.dataset.field)?.existing_name)return;
    e.preventDefault();selected=target.dataset.field;remember();const f=chosen(),[w,h]=data.sizes[page],step=e.shiftKey?10:1;
    f.x=Math.max(0,Math.min(w-f.width,f.x+(e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0)));
    f.y=Math.max(0,Math.min(h-f.height,f.y+(e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0)));
    change();q(`[data-field="${selected}"]`)?.focus({preventScroll:true});
  };
  async function perform(kind){
    busy=true;d.querySelectorAll('aside button,aside input,aside select').forEach(b=>b.disabled=true);status.textContent=kind==='save'?'Saving field map…':'Rendering sample…';
    try{
      if(kind==='save'){
        const r=await pywebview.api.form_builder_save(id,data.fields,data.revision);if(!r.ok)throw Error(r.error);
        data.revision=r.revision;dirty=false;formLibraryRows=null;status.textContent='Saved. Available in the job’s Forms picker on this computer.';
      }else{
        const r=await pywebview.api.form_builder_preview(id,data.fields);if(!r.ok)throw Error(r.error);
        const preview=document.createElement('dialog');preview.className='library-preview';
        preview.innerHTML='<button class="btn">Close sample</button><h2>Sample only — not a job document</h2>'+r.pages.map((p,i)=>`<img alt="Sample page ${i+1}" src="data:image/png;base64,${p}">`).join('');
        document.body.append(preview);preview.querySelector('button').onclick=()=>preview.close();preview.onclose=()=>preview.remove();preview.showModal();
        status.textContent='Sample rendered. Review every page, then save the map.';
      }
    }catch(e){status.textContent=e.message;}finally{busy=false;d.querySelectorAll('aside button,aside input,aside select').forEach(b=>b.disabled=false);editor();}
  }
  q('[data-save]').onclick=()=>perform('save');q('[data-preview]').onclick=()=>perform('preview');
};
