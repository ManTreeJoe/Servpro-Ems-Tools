/* Layout only: audit validation, drafts and publication remain owned by LogsAuditUI. */
(() => {
 'use strict';
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function mount({host,queue,current,form,library,evidence,comments,openButton,backButton,onSelect,onOpenComment,query='',onQuery,onAuditLinks,links}) {
  const shell=document.createElement('div');shell.className='logs-review-workspace';
  shell.innerHTML='<aside class="logs-review-queue" aria-label="Logs review queue"><h3>Review queue</h3><label>Find a job<input type="search" data-review-search placeholder="Name or job…"></label><p data-review-count></p><div data-review-jobs></div><div data-review-tools></div></aside><section class="logs-review-detail" aria-label="Selected job audit"><div class="logs-review-title"><div><small>LOGS · TO BE PRESERVED</small><h2></h2></div><div data-review-open></div></div><div class="logs-review-facts"></div><div data-review-form></div></section><aside class="logs-review-comments" aria-label="Comments and activity"><h3>Comments & activity</h3><small>Newest first · source evidence</small><label>Search comments<input type="search" data-comment-search placeholder="Find words in comments…"></label><div data-review-comments></div><p class="logs-review-comment-help">Read-only audit evidence. Open the job card to post, reply, or view a thread.</p></aside>';
  host.replaceChildren(shell);
  for(const [column,list] of [['.logs-review-queue','[data-review-jobs]'],['.logs-review-comments','[data-review-comments]']]){
   const pane=shell.querySelector(column),results=pane.querySelector(list),header=document.createElement('div');
   header.className='logs-review-sticky-head';
   while(pane.firstChild!==results)header.append(pane.firstChild);
   pane.prepend(header);
  }
  shell.querySelector('h2').textContent=evidence.card.name;
  openButton.textContent='Open job card ↗';shell.querySelector('[data-review-open]').append(openButton);
  // More lives in the audit header; no duplicate queue screen or sidebar control.
  backButton.remove();
  const facts=shell.querySelector('.logs-review-facts');
  const received=document.createElement('div'),scope=document.createElement('div');
  received.innerHTML='<small>Job received</small><strong></strong>';
  scope.innerHTML='<small>Audit period</small><strong></strong>';
  const displayDate=v=>window.AuditFieldControls?.date(v)||v||'Not recorded';
  const updateFacts=()=>{received.querySelector('strong').textContent=displayDate(form.elements.job_date.value);scope.querySelector('strong').textContent=[form.elements.period_start.value,form.elements.period_end.value].filter(Boolean).map(displayDate).join(' → ')||'Not selected';};
  updateFacts();form.addEventListener('input',updateFacts);facts.append(received,scope);
  shell.querySelector('[data-review-form]').append(form,library);
  const search=shell.querySelector('[data-review-search]');search.value=query;
  const statusFor=id=>queue.drafts[id]?'Draft saved':'Not reviewed';
  const renderQueue=()=>{
   const cards=queue.cards.filter(c=>c.name.toLowerCase().includes(search.value.toLowerCase()));
   shell.querySelector('[data-review-count]').textContent=`${cards.length} of ${queue.cards.length} jobs · shared drafts`;
   shell.querySelector('[data-review-jobs]').innerHTML=cards.map(c=>`<button type="button" class="logs-review-job" data-review-card="${esc(c.id)}" aria-current="${c.id===current?'true':'false'}"><strong>${esc(c.name)}</strong><small>${statusFor(c.id)}</small></button>`).join('')||'<p>No matching jobs.</p>';
  };
  search.oninput=()=>{onQuery(search.value);renderQueue();};renderQueue();
  shell.querySelector('[data-review-jobs]').onclick=e=>{const b=e.target.closest('[data-review-card]');if(b&&b.dataset.reviewCard!==current)onSelect(b.dataset.reviewCard);};
  const next=document.createElement('button');next.type='button';next.textContent='Next job →';next.dataset.reviewNext='';
  next.onclick=()=>{const cards=queue.cards.filter(c=>c.name.toLowerCase().includes(search.value.toLowerCase()));const i=cards.findIndex(c=>c.id===current);if(cards.length>1)onSelect(cards[(i+1)%cards.length].id);};
  next.disabled=queue.cards.length<2;form.querySelector('.audit-footer').append(next);
  const notice=document.createElement('p');notice.className='logs-review-save-note';notice.textContent='Save draft shares your findings with authorized office users through the database. Only the separate preview and confirmation can post an audit or move a card.';form.append(notice);
  const commentSearch=shell.querySelector('[data-comment-search]');
  const ordered=[...comments].sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
  const renderComments=()=>{
   shell.querySelector('[data-review-comments]').innerHTML=ordered.filter(c=>[c.text,c.author].join(' ').toLowerCase().includes(commentSearch.value.toLowerCase())).map(c=>`<article class="logs-review-comment"><div><strong>${esc(c.author||'Unknown author')}</strong><time>${esc(window.AuditFieldControls?.stamp(c.date)||c.date||'Not recorded')}</time></div><p>${esc(c.text)}</p><button type="button" data-review-comment="${esc(c.id||'')}">Open in job card ↗</button></article>`).join('')||'<p>No matching comments.</p>';
  };
  commentSearch.oninput=renderComments;renderComments();
  window.AuditCommentLinks?.bind(shell.querySelector('[data-review-comments]'),target=>{
   const row=target.closest('.logs-review-comment'),id=row?.querySelector('[data-review-comment]')?.dataset.reviewComment;
   const comment=comments.find(c=>c.id===id);return comment?{row,card:evidence.card.id,comment}:null;
  },onAuditLinks);
  const linkHint=document.createElement('small');linkHint.textContent='Right-click a comment to link it to an audit item or edit an existing link.';shell.querySelector('.logs-review-comment-help').before(linkHint);
  shell.querySelector('[data-review-comments]').onclick=e=>{const b=e.target.closest('[data-review-comment]');if(b)onOpenComment(b.dataset.reviewComment);};
  return {refreshQueue:renderQueue};
 }
 function loading(host,queue,card){
  host.innerHTML=`<div class="logs-review-workspace" aria-busy="true"><aside class="logs-review-queue"><h3>Review queue</h3>${queue?`<p>${queue.cards.length} jobs</p>${queue.cards.map(c=>`<button class="logs-review-job" disabled aria-current="${c.id===card?.id?'true':'false'}"><strong>${esc(c.name)}</strong><small>${c.id===card?.id?'Loading evidence…':'Waiting for review'}</small></button>`).join('')}`:'<p>Loading jobs…</p><div class="logs-loading-line"></div><div class="logs-loading-line"></div><div class="logs-loading-line"></div>'}</aside><section class="logs-review-detail"><div class="logs-review-title"><div><small>LOGS · TO BE PRESERVED</small><h2>${esc(card?.name||'Logs review')}</h2></div></div><p role="status">${card?'Loading job information, checklists and comment evidence…':'Getting your review queue…'}</p><div class="logs-loading-line"></div><div class="logs-loading-line"></div><div class="logs-loading-line"></div><p>Audit fields will become available when the evidence is ready.</p></section><aside class="logs-review-comments"><h3>Comments & activity</h3><p>${card?'Loading comments…':'Select a job once the queue is ready.'}</p><div class="logs-loading-line"></div><div class="logs-loading-line"></div></aside></div>`;
 }
 window.LogsReviewWorkspace={mount,loading};
})();
