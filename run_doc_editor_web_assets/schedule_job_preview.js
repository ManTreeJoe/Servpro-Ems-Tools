/* Read-only job facts, shared by search preview and the selected visit. */
window.ScheduleJobPreview=(()=>{
 const dialog=document.createElement('dialog');
 dialog.className='schedule-job-preview';dialog.setAttribute('aria-label','Job preview');
 document.body.append(dialog);let generation=0;
 const node=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
 function facts(job){
  const body=document.createElement('div');body.className='schedule-job-facts';
  for(const section of job.info_sections||[]){
   body.append(node('h3',section.name));const list=document.createElement('dl');
   for(const field of section.fields){let value=field.value;
    if(['date_received','date_of_loss'].includes(field.id)&&/^\d{4}-\d{2}-\d{2}$/.test(value))value=value.slice(5,7)+'/'+value.slice(8,10)+'/'+value.slice(0,4);
    list.append(node('dt',field.label),node('dd',value));
   }body.append(list);
  }
  if(!body.childElementCount)body.append(node('p','No job details have been recorded.'));
  return body;
 }
 function cardButtons(job){
  const body=document.createElement('div');body.className='schedule-card-actions';
  const cards=job.trello_cards||[];
  for(const [index,id] of cards.entries()){
   const button=node('button',cards.length===1?'Open job card':`Open linked card ${index+1}`);
   button.type='button';button.className='btn';button.title=id;
   button.onclick=()=>{if(dialog.open)dialog.close();parent.postMessage({type:'linguar-open-job',cardId:id,focus:job.title},location.origin);};body.append(button);
  }
  if(!cards.length)body.append(node('p','No saved Trello card link for this job.'));
  return body;
 }
 function selected(container,job){
  container.replaceChildren();if(!job)return;
  const details=document.createElement('details');details.append(node('summary','All job details (read only)'),facts(job),cardButtons(job));container.append(details);
 }
 async function open(job,load,choose){
  const version=++generation;dialog.replaceChildren();
  const close=node('button','Close preview');close.type='button';close.className='btn';close.onclick=()=>dialog.close();
  dialog.append(close,node('h2',job.title),node('p','Loading current job details…'));dialog.showModal();
  try{const current=await load(job.job_id);if(version!==generation||!dialog.open)return;
   dialog.replaceChildren(close,node('h2',current.title),node('p','Saved job-card information · previewing does not change the visit.'),facts(current),cardButtons(current));
   const select=node('button','Use this job');select.type='button';select.className='btn btn-primary';select.onclick=()=>{dialog.close();choose(current);};dialog.append(select);
  }catch(error){if(version===generation&&dialog.open){dialog.replaceChildren(close,node('h2',job.title),node('p',error.message));}}
 }
 dialog.addEventListener('close',()=>generation++);
 return {open,selected};
})();
