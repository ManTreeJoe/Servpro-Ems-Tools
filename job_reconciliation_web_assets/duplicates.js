'use strict';
// Suggestions use only the already-authorized inventory. Never change ownership.
function duplicateCandidates(job, jobs, cards) {
 const norm=v=>String(v||'').toLowerCase().replace(/[^a-z0-9]/g,'');
 const claim=v=>{const n=norm(v);return ['na','none','unknown','pending','notfiledyet','notavailable'].includes(n)?'':n;};
 const words=v=>new Set(String(v||'').toLowerCase().split(/[^a-z0-9]+/).filter(w=>w.length>2&&!['contents','recon','ems','program','farmers','state','farm','aaa','mercury','the','and'].includes(w)));
 const ownCards=new Set(cards.filter(c=>c.links.some(l=>l.job_id===job.job_id)).map(c=>c.card_id));
 const a=words(job.display_name);
 return jobs.filter(j=>j.job_id!==job.job_id).map(j=>{
  const reasons=[];let score=0;
  if(cards.some(c=>ownCards.has(c.card_id)&&c.links.some(l=>l.job_id===j.job_id))){reasons.push('Same Trello card linked to both jobs');score+=100;}
  if(claim(job.claim_number)&&claim(job.claim_number)===claim(j.claim_number)){reasons.push('Same claim number');score+=40;}
  if(norm(job.address)&&norm(job.address)===norm(j.address)){reasons.push('Same address');score+=20;}
  const b=words(j.display_name),overlap=[...a].filter(w=>b.has(w)).length;
  if(norm(job.display_name)&&norm(job.display_name)===norm(j.display_name)||overlap>=2&&overlap/Math.min(a.size,b.size)>=0.75){reasons.push('Similar job name');score+=10;}
  const conflict=claim(job.claim_number)&&claim(j.claim_number)&&claim(job.claim_number)!==claim(j.claim_number);
  return {job:j,reasons,score,conflict};
 }).filter(x=>x.score).sort((a,b)=>b.score-a.score||a.job.display_name.localeCompare(b.job.display_name));
}
window.renderDuplicatePanel=()=>{
 const job=jobInventory.find(j=>j.job_id===$('link-target').value);
 $('duplicate-panel').hidden=!job;
 $('duplicate-results').replaceChildren();if(!job)return;
 const matches=duplicateCandidates(job,jobInventory,inventory);
 $('duplicate-heading').textContent=`Possible duplicates (${matches.length})`;
 if(!matches.length){$('duplicate-results').append(el('p','No matches found in the accessible saved jobs. This does not rule out duplicates with different or missing details.'));return;}
 for(const match of matches){const j=match.job,row=el('section','');row.className='connected-section';
  row.append(el('h3',j.display_name),el('p',match.reasons.join(' · ')),el('p',`Claim: ${j.claim_number||'Not recorded'} · Address: ${j.address||'Not recorded'} · Section: ${j.department||'Not recorded'}`));
  if(match.conflict)row.append(el('p','Different claim numbers — verify these are the same loss before combining.'));
  const btn=el('button','Review merge');btn.type='button';btn.onclick=()=>{
   if(busy)return;
   clear();clearLink();$('target').value=job.job_id;$('source').value=j.job_id;
   $('mode').value='merge';$('merge-panel').hidden=false;$('link-panel').hidden=true;
   $('choose').requestSubmit();$('merge-panel').scrollIntoView({block:'start',behavior:'auto'});
  };row.append(btn);$('duplicate-results').append(row);
 }
};
window.renderDuplicatePanel();
