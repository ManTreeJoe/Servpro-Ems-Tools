window.CardDue={mount(root,client,cardId,onSaved){
 const badge=root.querySelector('.details-dates [data-details-open-card]'),date=root.querySelector('.details-dates strong'),edit=badge;
 if(!badge||!cardId||!window.pywebview?.api.card_due_load)return;
 const paint=value=>{const label=value?new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'Not set';if(date)date.textContent=label;};
 badge.title='Edit card due date';if(edit)edit.textContent='✎ Edit due date';
 async function open(){
 const dialog=document.createElement('dialog');dialog.className='job-members-dialog';dialog.innerHTML='<header><h2>Card due date</h2><button data-close aria-label="Close">×</button></header><p>Deadline for this card, not field-work completion.</p><label>Date and time (your local timezone)<input type="datetime-local" disabled></label><p role="status">Loading current date…</p><button data-save disabled>Save date</button> <button data-clear disabled>Remove date</button>';
 document.body.append(dialog);dialog.showModal();let expected='',busy=false;const input=dialog.querySelector('input'),status=dialog.querySelector('[role=status]'),save=dialog.querySelector('[data-save]'),clear=dialog.querySelector('[data-clear]');
 dialog.querySelector('[data-close]').onclick=()=>{if(!busy)dialog.close();};dialog.oncancel=e=>{if(busy)e.preventDefault();};dialog.onclose=()=>dialog.remove();
 try{const result=await pywebview.api.card_due_load(client,cardId);if(!dialog.isConnected)return;if(!result.ok)throw Error(result.error);expected=result.due;paint(expected);if(expected){const d=new Date(expected);input.value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}input.disabled=save.disabled=clear.disabled=false;status.textContent='';}catch(e){status.textContent=e.message;}
 async function submit(remove){if(!remove&&!input.value){status.textContent='Choose a date and time.';return;}busy=true;save.disabled=clear.disabled=input.disabled=true;status.textContent='Saving…';try{const result=await pywebview.api.card_due_save(client,cardId,remove?'':new Date(input.value).toISOString(),expected);if(!result.ok)throw Error(result.error);paint(result.due);onSaved(result.due);busy=false;dialog.close();}catch(e){status.textContent=e.message;busy=false;input.disabled=false;/* Reopen after an uncertain save; do not replay it. */}}
 save.onclick=()=>submit(false);clear.onclick=()=>submit(true);
 }
 badge.onclick=open;if(edit)edit.onclick=open;
}};
