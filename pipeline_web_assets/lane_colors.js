window.LaneColors=(()=>{
 const palette=[['Charcoal','#202328'],['Black','#101214'],['Slate','#343941'],['Forest','#243a31'],['Navy','#23364b'],['Plum','#38304b'],['Wine','#493139'],['Bronze','#453b2b']];
 const cache=new Map();let current='',loading=false;
 function paint(){for(const lane of document.querySelectorAll('.lane[data-list-id]'))lane.style.setProperty('--shared-lane-color',cache.get(current)?.[lane.dataset.listId]||'#202328');}
 async function refresh(){if(!current||loading||document.hidden)return;const board=current;loading=true;
  try{const r=await pywebview.api.shared_lane_colors(board);if(r?.ok){cache.set(board,Object.fromEntries(r.colors.map(x=>[x.list_id,x.color])));if(current===board)paint();}}catch(_){}finally{loading=false;}}
 function mount(board){if(current!==board){current=board||'';paint();void refresh();}else paint();}
 function controls(menu,lane,board){
  const box=document.createElement('fieldset');box.className='lane-color-controls';
  const legend=document.createElement('legend');legend.textContent='Lane color · shared with everyone';box.append(legend);
  const status=document.createElement('small');status.setAttribute('role','status');
  for(const [name,color] of palette){const button=document.createElement('button');button.type='button';button.title=name;button.setAttribute('aria-label',name);button.style.background=color;button.textContent=name;
   button.setAttribute('aria-pressed',String((cache.get(board)?.[lane.dataset.listId]||'#202328')===color));
   button.onclick=async()=>{box.querySelectorAll('button').forEach(b=>b.disabled=true);status.textContent='Saving for everyone…';
    try{const r=await pywebview.api.save_shared_lane_color(board,lane.dataset.listId,color);if(!r?.ok)throw Error(r?.error||'Save not confirmed');cache.set(board,{...cache.get(board),[lane.dataset.listId]:color});paint();box.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));status.textContent='Saved for everyone on this board.';}
    catch(e){status.textContent='Not saved: '+e.message;}finally{box.querySelectorAll('button').forEach(b=>b.disabled=false);}};box.append(button);}
  box.append(status);menu.prepend(box);
 }
 setInterval(refresh,30000);window.addEventListener('focus',refresh);
 return {mount,controls,refresh};
})();
