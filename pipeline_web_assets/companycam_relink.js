/* Correct a job's project without touching photos or silently accepting failed writes. */
window.CompanyCamRelink = {open({client, cardId, api, onSaved}) {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const modal = window.openModal({id:'companycam-relink', title:'Change CompanyCam project',
    sub:client, body:`<p>Search for the correct project. This replaces the saved link for this job; existing downloaded photos stay unchanged.</p>
      <form data-cc-search-form><label>Project name or address<input data-cc-query value="${esc(client)}" style="width:100%;box-sizing:border-box;padding:8px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:6px"></label><button class="btn" type="submit">Search</button></form>
      <p data-cc-message role="status"></p><div data-cc-results style="max-height:300px;overflow:auto"></div>`});
  modal.style.zIndex='600'; // Above the job workspace, like its other nested pickers.
  const form = modal.querySelector('[data-cc-search-form]');
  const message = modal.querySelector('[data-cc-message]');
  const results = modal.querySelector('[data-cc-results]');
  let generation = 0, saving = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving) return;
    const query = modal.querySelector('[data-cc-query]').value.trim();
    const request = ++generation;
    results.replaceChildren();
    if (!query) {message.textContent='Enter a project name or address.'; return;}
    message.textContent='Searching CompanyCam…';
    try {
      const response = await api.companycam_search(query);
      if (!modal.isConnected || request !== generation) return;
      if (!response?.ok) throw new Error(response?.error || 'Search failed. Try again.');
      const candidates = response.candidates || [];
      message.textContent=candidates.length ? 'Check the name, address and project ID before choosing.' : 'No matching projects. Try another name or address.';
      for (const candidate of candidates) {
        const button = document.createElement('button');
        button.type='button'; button.className='btn'; button.dataset.ccProject=String(candidate.id || '');
        button.style.cssText='display:block;width:100%;text-align:left;white-space:normal;margin:6px 0;padding:10px';
        button.disabled=!!candidate.unavailable || !candidate.id;
        button.textContent=`${candidate.name || 'Unnamed project'} — ${candidate.address || 'No address'} · ID ${candidate.id || 'unknown'}${candidate.photo_count != null ? ` · ${candidate.photo_count}${candidate.approx ? '+' : ''} photos` : ''}${candidate.unavailable ? ' · Unavailable' : ''}`;
        button.addEventListener('click', async () => {
          if (saving || !confirm(`Link “${client}” to “${candidate.name}” (project ${candidate.id})? This replaces the job’s previous CompanyCam link.`)) return;
          saving=true;
          modal.querySelectorAll('input,button').forEach(el=>el.disabled=true);
          message.textContent='Saving project link…';
          try {
            const saved=await api.companycam_pin(client, String(candidate.id), cardId);
            if (!saved?.ok) throw new Error(saved?.error || 'The link could not be saved.');
            if (modal.isConnected) window.closeModal('companycam-relink');
            onSaved?.(saved);
          } catch (error) {
            message.textContent=error.message || 'The link could not be saved. Try again.';
          } finally {
            saving=false;
            modal.querySelectorAll('input,button').forEach(el=>el.disabled=false);
            candidates.filter(c=>c.unavailable || !c.id).forEach(c=>{
              Array.from(results.children).find(el=>el.dataset.ccProject===String(c.id || ''))?.setAttribute('disabled','');
            });
          }
        });
        results.append(button);
      }
    } catch (error) {
      if (modal.isConnected && request === generation) message.textContent=error.message || 'Search failed.';
    }
  });
  modal.querySelector('[data-cc-query]').focus();
  form.requestSubmit();
}};
