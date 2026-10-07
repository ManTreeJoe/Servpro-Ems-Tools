/* Independent, read-only timing: never infer lane age from last activity. */
window.JobCardTiming = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const duration = value => value == null ? 'Unknown' : value < 3600 ? `${Math.floor(value / 60)} min` : value < 86400 ? `${Math.floor(value / 3600)}h ${Math.floor(value % 3600 / 60)}m` : `${Math.floor(value / 86400)}d ${Math.floor(value % 86400 / 3600)}h`;
  const date = value => value ? new Date(value).toLocaleString('en-US', {year:'2-digit',month:'2-digit',day:'2-digit',hour:'numeric',minute:'2-digit'}) : 'Not recorded';
  function mount(root, cardId, api) {
    const info = root.querySelector('.job-info-section');
    if (!info || root.querySelector('.job-timing-section')) return;
    const section = document.createElement('section');
    section.className = 'aud-section job-timing-section';
    section.dataset.timingCard = cardId || '';
    info.after(section);
    if (!cardId) { section.textContent = 'Job timing · Link a card to read its movement history.'; return; }
    let busy = false, result = null;
    function paint(message = '') {
      const current = result?.periods?.find(p => p.current);
      section.innerHTML = `<div class="job-timing-heading"><div><h3>Job timing</h3><small>${current ? escape(current.board) + ' / ' + escape(current.lane) : 'Current lane entry not verified'}</small></div><div><strong>${result ? duration(result.current_seconds) : '—'}</strong><small>in current lane</small></div></div>
        <p role="status">${escape(message)}</p>
        ${result ? `<details><summary>Movement history & estimating time</summary><p class="job-timing-note">Available Trello events only · missing history stays unknown${result.complete ? '' : ' · partial retrieval'}. Separate cards are not combined.</p>
        ${(result.estimator_cycles || []).map(c => `<div class="job-timing-cycle"><b>${escape(c.first_lane)} → Logs · ${duration(c.seconds)}</b><span>${date(c.started)} → ${c.ended ? date(c.ended) : 'Logs arrival not recorded'}</span></div>`).join('')}
        <ol>${(result.periods || []).map(p => `<li><div><small>${escape(p.board)}</small><b>${escape(p.lane)}</b><span>${date(p.entered)} → ${p.current ? 'Current lane' : date(p.exited)}</span><small>Moved by ${escape(p.actor)}</small></div><strong>${duration(p.seconds)}</strong></li>`).join('') || '<li>No verified movements available.</li>'}</ol></details>` : ''}
        <button type="button" class="btn compact" ${busy ? 'disabled' : ''}>${busy ? 'Checking timing…' : result ? 'Refresh timing' : 'Retry timing'}</button>`;
      section.querySelector('button').onclick = load;
    }
    async function load() {
      if (busy) return;
      busy = true; paint(result ? 'Refreshing recorded moves…' : 'Reading recorded moves…');
      let timer;
      try {
        const next = await Promise.race([api.job_card_timing(cardId), new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Timing took too long. Retry when ready.')), 30000); })]);
        if (!section.isConnected) return;
        if (!next?.ok) throw Error(next?.error || 'Timing unavailable.');
        result = next; busy = false; paint();
      } catch (error) {
        if (section.isConnected) { busy = false; paint((error.message || 'Timing unavailable.') + (result ? ' Previous timing retained.' : '')); }
      } finally { clearTimeout(timer); }
    }
    section._timing = {activate: load};
    if (section.isConnected) load();
  }
  return {mount};
})();
