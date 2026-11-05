/* Trello's adapter for the shared select → destination review → import flow. */
window.TrelloAttachmentGallery = {
  async open({cardId, client, division = 'EMS', onAfter}) {
    const api = window.pywebview.api, origin = document.activeElement;
    const host = document.createElement('div'); host.className = 'modal-scrim ta-gallery';
    host.innerHTML = `<style>
      .ta-gallery{position:fixed;inset:0;z-index:350;background:#000a;display:flex;align-items:center;justify-content:center}
      .ta-gallery-card{width:min(1040px,94vw);max-height:92vh;display:flex;flex-direction:column;background:var(--bg,#202428);color:var(--text);border:1px solid var(--border);border-radius:10px;overflow:hidden}
      .ta-gallery header,.ta-gallery footer,.ta-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px}
      .ta-gallery header strong{flex:1}.ta-gallery footer{border-top:1px solid var(--border)}.ta-gallery footer [role=status]{flex:1}
      .ta-gallery-scroll,.ta-review{overflow:auto;padding:0 16px 16px;min-height:200px}
      .ta-gallery-scroll{max-height:58vh}.ta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
      .ta-tile{position:relative;border:1px solid var(--border);border-radius:8px;padding:8px;display:grid;gap:6px;min-width:0}
      .ta-tile:has(.ta-cb:checked){outline:2px solid var(--accent,#65b58d)}
      .ta-cb{position:absolute;left:14px;top:14px;width:20px;height:20px;z-index:1}
      .ta-preview{width:100%;aspect-ratio:4/3;padding:0;border:0;background:var(--surface);color:var(--text);cursor:zoom-in}
      .ta-preview img{width:100%;height:100%;object-fit:cover}.ta-tile small{overflow-wrap:anywhere}
      .ta-person-label{display:inline-flex;align-items:center;gap:9px;min-height:32px}.ta-person-label input{width:18px;height:18px}
      .ta-day-head{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--border);padding:12px 0}
      .ta-review label{display:grid;gap:6px;margin:14px 0}.ta-review input,.ta-review select{padding:9px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:6px}
      .ta-destination{overflow-wrap:anywhere;padding:12px;background:var(--surface);border-radius:6px;font-size:13px}
      .ta-gallery :focus-visible{outline:2px solid var(--accent,#65b58d);outline-offset:2px}
      .ta-gallery [hidden]{display:none!important}.ta-destination{white-space:pre-line}
    </style><section class="ta-gallery-card" role="dialog" aria-modal="true" aria-label="Trello attachment import">
      <header><strong data-title></strong><button class="btn" data-close>Close</button></header>
      <div class="ta-toolbar"><button class="btn" data-all>Select all</button><button class="btn" data-photos>Select photos only</button><button class="btn" data-clear>Clear selection</button><span data-count>0 selected</span></div>
      <div class="ta-gallery-scroll"><p>Newest first · grouped by upload date and uploader. Select with checkboxes; click images to preview.</p><div data-groups></div><button class="btn" data-more hidden>Load older attachments</button></div>
      <div class="ta-review" hidden><h3>Review destination</h3>
        <label>Section<select data-side><option value="ems">EMS</option><option value="contents">Contents</option></select></label>
        <label>Photo destination<select data-stage>${['Trello attachments','Initial','Monitor','Demo','Reinspection','Abatement','Cleaning','Mold Prep','Walkthroughs','Final'].map(s=>`<option>${s}</option>`).join('')}</select></label>
        <label>Tech / crew override (optional)<input data-crew placeholder="Leave blank to use each uploader’s name"></label>
        <p>Photos and videos go into the chosen photo destination, grouped by crew and upload date. Documents go into DOCS. External links stay in Trello.</p>
        <div class="ta-destination" data-destination></div>
      </div>
      <footer><span role="status" data-status>Loading attachments…</span><button class="btn" data-back hidden>Back to photos</button><button class="btn btn-primary" data-review disabled>Review selected</button><button class="btn btn-primary" data-import hidden disabled>Import selected</button></footer>
    </section>`;
    document.body.append(host);
    if(cardId){const header=host.querySelector('header');header.dataset.popoutTool='pipeline';header.dataset.popoutContext=JSON.stringify({cardId,client,division,jobAction:'trello_attachments'});header.title='Open a fresh attachment window; current selections stay here.';}
    const $ = s => host.querySelector(s), message = text => $('[data-status]').textContent = text;
    $('[data-side]').value = String(division).toUpperCase()==='CONTENTS' ? 'contents' : 'ems';
    $('[data-title]').textContent = `Trello attachments · ${client || cardId}`;
    let items = [], limit = 36, busy = true, closed = false, target = null, revision = 0, thumbBusy = false;
    const selected = new Set(), cache = new Map(), attempted = new Set();
    const day = a => a.date && !isNaN(Date.parse(a.date)) ? new Date(a.date).toLocaleDateString() : 'Unknown date';
    const person = a => a.uploader || 'Unknown uploader';
    function sync() {
      $('[data-count]').textContent = `${selected.size} selected`;
      $('[data-review]').disabled = busy || !selected.size;
      $('[data-import]').disabled = busy || !target || !selected.size;
      host.querySelectorAll('[data-ids]').forEach(box => {
        const ids = JSON.parse(box.dataset.ids), count = ids.filter(id=>selected.has(id)).length;
        box.checked = ids.length > 0 && count === ids.length;
        box.indeterminate = count > 0 && count < ids.length;
      });
      host.querySelectorAll('.ta-cb').forEach(box=>box.checked=selected.has(box.dataset.id));
    }
    function lock(value) {
      busy = value;
      host.querySelectorAll('button,input,select').forEach(el=>el.disabled=value || el.dataset.external==='true');
      sync();
    }
    function groupCheck(ids, label) {
      const box = document.createElement('input'); box.type='checkbox'; box.dataset.ids=JSON.stringify(ids);
      box.setAttribute('aria-label', label);
      box.onchange=()=>{ ids.forEach(id=>box.checked?selected.add(id):selected.delete(id));sync(); };
      return box;
    }
    function render() {
      const position = $('.ta-gallery-scroll').scrollTop, groups = new Map();
      for (const a of items.slice(0,limit)) {
        if (!groups.has(day(a))) groups.set(day(a),new Map());
        const people=groups.get(day(a));
        if (!people.has(person(a))) people.set(person(a),[]);
        people.get(person(a)).push(a);
      }
      $('[data-groups]').replaceChildren();
      for (const [date,people] of groups) {
        const section=document.createElement('section'), heading=document.createElement('div');heading.className='ta-day-head';
        const title=document.createElement('strong');title.textContent=date;
        const label=document.createElement('label');label.className='ta-person-label';label.append('Select whole day ');
        label.append(groupCheck(items.filter(a=>a.is_upload&&day(a)===date).map(a=>a.id),`Select whole day ${date}`));
        heading.append(title,label);section.append(heading);
        for(const [who,photos] of people) {
          const h=document.createElement('h4'), personLabel=document.createElement('label');personLabel.className='ta-person-label';personLabel.append(who);
          personLabel.append(groupCheck(items.filter(a=>a.is_upload&&day(a)===date&&person(a)===who).map(a=>a.id),`Select all attachments by ${who} on ${date}`));h.append(personLabel);
          const grid=document.createElement('div');grid.className='ta-grid';
          for(const a of photos) {
            const tile=document.createElement('div');tile.className='ta-tile';
            const check=document.createElement('input');check.type='checkbox';check.className='ta-cb';check.dataset.id=a.id;check.setAttribute('aria-label',`Select ${a.name}`);
            check.disabled=!a.is_upload;check.dataset.external=String(!a.is_upload);
            check.onchange=()=>{check.checked?selected.add(a.id):selected.delete(a.id);sync();};
            const preview=document.createElement('button');preview.type='button';preview.className='ta-preview';preview.dataset.preview=a.id;
            preview.setAttribute('aria-label',`Preview ${a.name}`);preview.textContent=a.is_video?'▶ Video':a.is_image?'Loading preview…':'📄 Document';
            if(cache.has(a.id)){const img=document.createElement('img');img.src=cache.get(a.id);img.alt=a.name;preview.replaceChildren(img);}
            preview.onclick=()=> {
              if(a.is_image&&!a.is_video) window.openImportImagePreview({title:a.name,source:async()=>{
                const result=await api.fetch_trello_image(a.url);
                if(!result?.ok||!result.data_uri)throw Error('Image unavailable');return result.data_uri;
              }});
              else if(/^https?:\/\//i.test(a.url||''))api.open_url(a.url);
              else message('This attachment does not have a supported web link.');
            };
            const caption=document.createElement('small');caption.textContent=`${a.name}${a.is_upload?'':' · External link (not imported)'}`;
            tile.append(check,preview,caption);grid.append(tile);
          }
          section.append(h,grid);
        }
        $('[data-groups]').append(section);
      }
      if(!items.length)$('[data-groups]').textContent='No attachments on this card.';
      $('[data-more]').hidden=limit>=items.length;sync();$('.ta-gallery-scroll').scrollTop=position;loadThumbs();
    }
    async function loadThumbs() {
      if(thumbBusy)return;thumbBusy=true;
      try {
        while(!closed) {
          const a=items.slice(0,limit).find(a=>a.is_image&&a.preview&&!attempted.has(a.id));
          if(!a)break;attempted.add(a.id);
          let result;try{result=await api.fetch_trello_image(a.preview);}catch(_){}
          if(closed)return;
          const button=[...host.querySelectorAll('[data-preview]')].find(b=>b.dataset.preview===a.id);
          if(result?.ok&&/^data:image\//.test(result.data_uri||'')){
            cache.set(a.id,result.data_uri);
            if(button){const img=document.createElement('img');img.src=result.data_uri;img.alt=a.name;button.replaceChildren(img);}
          } else if(button)button.textContent='Preview unavailable · click to retry';
        }
      } finally {thumbBusy=false;}
    }
    const more=()=>{if(busy)return;limit+=36;render();};
    $('[data-more]').onclick=more;
    $('.ta-gallery-scroll').onscroll=()=>{const el=$('.ta-gallery-scroll');if(limit<items.length&&el.scrollTop+el.clientHeight>=el.scrollHeight-160)more();};
    $('[data-all]').onclick=()=>{items.filter(a=>a.is_upload).forEach(a=>selected.add(a.id));sync();};
    $('[data-photos]').onclick=()=>{items.filter(a=>a.is_upload&&a.is_image).forEach(a=>selected.add(a.id));sync();};
    $('[data-clear]').onclick=()=>{selected.clear();sync();};
    async function destination() {
      const request=++revision;target=null;lock(true);
      $('[data-destination]').textContent='Checking the job folder…';
      try{
        const result=await api.trello_attachment_destinations(client,$('[data-side]').value,$('[data-stage]').value);
        if(closed||request!==revision)return;
        if(!result?.ok)throw Error(result?.error||'Destination unavailable.');
        target=result;$('[data-destination]').textContent=`Photos: ${result.photos}\nDocuments: ${result.documents}`;
      }catch(error){if(!closed)message(error.message);}
      finally{if(!closed&&request===revision)lock(false);}
    }
    $('[data-review]').onclick=async()=>{
      if(busy||!selected.size)return;
      $('.ta-gallery-scroll').hidden=true;$('.ta-toolbar').hidden=true;$('.ta-review').hidden=false;
      $('[data-review]').hidden=true;$('[data-import]').hidden=false;$('[data-back]').hidden=false;
      message(`${selected.size} attachments to review. Nothing imported yet.`);await destination();
    };
    $('[data-side]').onchange=destination;$('[data-stage]').onchange=destination;
    $('[data-back]').onclick=()=>{
      $('.ta-gallery-scroll').hidden=false;$('.ta-toolbar').hidden=false;$('.ta-review').hidden=true;
      $('[data-review]').hidden=false;$('[data-import]').hidden=true;$('[data-back]').hidden=true;sync();
    };
    $('[data-import]').onclick=async()=>{
      if(busy||!target||!selected.size)return;
      lock(true);message('Importing selected attachments…');
      try{
        const result=await api.import_trello_attachments(cardId,client,[...selected],$('[data-side]').value,$('[data-stage]').value,$('[data-crew]').value.trim(),target.root);
        [...(result?.downloaded||[]),...(result?.skipped||[])].forEach(id=>selected.delete(id));
        message(`${result?.downloaded_count||0} imported · ${result?.skipped_count||0} already present${result?.error?' · '+result.error:''}`);
        if(onAfter&&result?.downloaded_count){try{onAfter();}catch(_){}}
      }catch(_){message('Import confirmation was lost. Selection kept. Existing attachment IDs are skipped on retry.');}
      finally{lock(false);}
    };
    function close(){if(busy)return;closed=true;revision++;host.remove();document.removeEventListener('keydown',key,true);origin?.focus();}
    function key(event){
      if(document.querySelector('.import-image-viewer'))return;
      if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();}
      if(event.key==='Tab'){
        const nodes=[...host.querySelectorAll('button,input,select')].filter(el=>!el.disabled&&el.getClientRects().length);
        const first=nodes[0],last=nodes.at(-1);
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
      }
    }
    document.addEventListener('keydown',key,true);$('[data-close]').onclick=close;
    lock(true);
    try{
      if(!cardId)throw Error('No Trello card is linked to this job.');
      const result=await api.list_card_attachments(cardId);
      if(!result?.ok)throw Error(result?.error||'Attachments could not load.');
      items=(result.attachments||[]).sort((a,b)=>(Date.parse(b.date)||0)-(Date.parse(a.date)||0));
      message(`${items.length} attachments · grouped by upload date, not capture date.`);render();
    }catch(error){message(error.message);}
    finally{lock(false);$('[data-close]').focus();}
  }
};
