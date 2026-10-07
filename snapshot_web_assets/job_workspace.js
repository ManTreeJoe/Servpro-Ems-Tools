/* Snapshot report state stays separate from the live job-card conversation. */
window.SnapshotJobWorkspace = (() => {
  let frame, selected = null, overview = null, request = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render() {
    const host = document.querySelector('#audit-result');
    if (!host) return;
    const data = overview || {};
    const sections = (data.sections || []).filter(s => !['Pipeline','App location'].includes(s.name));
    host.innerHTML = `<div class="snapshot-job-overview"><header><div><h3>${esc(data.client || selected?.client || 'Job overview')}</h3><small>${esc(data.division || selected?.division || 'EMS')} · ${data.pending ? 'Saved details · checking for updates' : overview ? 'Job card details' : 'Loading job card details…'}</small></div><button type="button" class="btn" data-open-full-job ${selected?.cardId ? '' : 'disabled'}>Open job card</button></header>
      ${data.placement?.board || data.placement?.lane ? `<div class="snapshot-job-location"><span>${esc(data.placement.board)}</span><strong>${esc(data.placement.lane)}</strong></div>` : ''}
      ${sections.map(section => {
        const fields = (section.fields || []).filter(f => String(f.value ?? '').trim());
        return fields.length ? `<section><h4>${esc(section.name)}</h4><div class="snapshot-job-facts">${fields.map(f=>`<button type="button" data-copy-fact="${esc(f.value)}" title="Copy ${esc(f.label)}"><small>${esc(f.label)}</small><strong>${esc(f.value)}</strong></button>`).join('')}</div></section>` : '';
      }).join('')}
      ${data.error ? `<p role="alert">${esc(data.error)} · Open the job card to retry.</p>` : ''}
      ${overview && !data.pending && !sections.some(s => (s.fields || []).some(f => String(f.value ?? '').trim())) ? '<p>No saved customer details available. Open the job card to review its link.</p>' : ''}</div>`;
    host.querySelector('[data-open-full-job]').onclick = () => window.parent.postMessage({type:'linguar-open-job',focus:selected.client,cardId:selected.cardId,division:selected.division}, location.origin);
    host.querySelectorAll('[data-copy-fact]').forEach(button => button.onclick = async () => {
      try {
        if (!await window.copyText(button.dataset.copyFact)) throw new Error('Copy failed');
        button.title = 'Copied';
      } catch (_) { button.title = 'Copy failed — try again'; }
    });
  }
  async function select(row) {
    const cardId = String(row?.cardId || '');
    document.body.classList.add('snapshot-job-docked');
    let dock = document.querySelector('#snapshot-job-comments');
    if (!dock) {
      dock = document.createElement('aside'); dock.id = 'snapshot-job-comments';
      dock.setAttribute('aria-label', 'Job comments'); document.body.append(dock);
    }
    const token = ++request;
    if (selected?.cardId === cardId && selected?.division === row.division) return;
    try { await frame?.contentWindow?.flushSnapshotCommentDraft?.(); } catch (_) {}
    if (token !== request) return;
    selected = {...row,cardId}; overview = null;
    dock.replaceChildren(); frame = null;
    if (cardId) {
      frame = document.createElement('iframe'); frame.title = 'Job card comments';
      const params = new URLSearchParams({job_workspace:'1',snapshot_comments:'1',card_id:cardId,division:row.division || 'EMS',focus:row.client || 'Job'});
      frame.src = '../pipeline_web_assets/index.html?' + params;
      dock.append(frame);
    } else dock.innerHTML = '<h3>Comments</h3><p>Choose a linked job to load its conversation.</p>';
    document.querySelector('#audit-subview')?.classList.remove('hidden');
    render();
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
    const data = event.data || {};
    if (data.type !== 'snapshot-job-overview' || data.cardId !== selected?.cardId) return;
    overview = {...(overview || {}),...data}; render();
  });
  function visible(show) {
    document.body.classList.toggle('snapshot-job-docked', show);
    const dock = document.querySelector('#snapshot-job-comments');
    if (dock) dock.hidden = !show;
  }
  return {select, render, visible};
})();
