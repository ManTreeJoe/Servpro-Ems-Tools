/* Both surfaces use the real Pipeline workspace; Snapshot owns only its report. */
window.SnapshotJobWorkspace = (() => {
  let cardFrame, commentsFrame, selectedKey = '', commentKey = '', request = 0;
  function makeFrame(row, mode) {
    const frame = document.createElement('iframe');
    frame.title = mode === 'snapshot_card' ? 'Snapshot job card' : 'Job card comments';
    const params = new URLSearchParams({job_workspace:'1',[mode]:'1',card_id:row.cardId,
      division:row.division || 'EMS',focus:row.client || 'Job'});
    frame.src = '../pipeline_web_assets/index.html?' + params;
    return frame;
  }
  function dock() {
    let host = document.querySelector('#snapshot-job-comments');
    if (!host) {
      host = document.createElement('aside'); host.id = 'snapshot-job-comments';
      host.setAttribute('aria-label','Job comments'); document.body.append(host);
    }
    return host;
  }
  async function showComments(row) {
    const key = JSON.stringify([row.cardId,row.division || 'EMS']);
    const token = ++request;
    if (commentKey === key) return;
    await commentsFrame?.contentWindow?.flushSnapshotCommentDraft?.();
    if (token !== request) return;
    commentKey = key;
    commentsFrame = row.cardId ? makeFrame(row,'snapshot_comments') : null;
    const host = dock(); host.replaceChildren();
    if (commentsFrame) host.append(commentsFrame);
    else host.innerHTML = '<h3>Comments</h3><p>Choose a linked job to load its conversation.</p>';
  }
  async function select(row) {
    const key = JSON.stringify([row.cardId || '',row.division || 'EMS']);
    document.body.classList.add('snapshot-job-docked');
    if (selectedKey === key) return;
    selectedKey = key;
    const host = document.querySelector('#audit-result');
    if (!host) return;
    cardFrame = row.cardId ? makeFrame(row,'snapshot_card') : null;
    host.replaceChildren();
    if (cardFrame) host.append(cardFrame);
    else host.textContent = 'Choose a linked job to open its job card here.';
    document.querySelector('#audit-subview')?.classList.remove('hidden');
    await showComments(row);
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    const fromCard = event.source === cardFrame?.contentWindow;
    if (!fromCard && event.source !== commentsFrame?.contentWindow) return;
    const data = event.data || {};
    if (fromCard && data.type === 'snapshot-card-height' && Number.isFinite(data.height)) {
      cardFrame.style.height = Math.max(320,Math.min(20000,data.height + 2)) + 'px';
    } else if (['linguar-open-job','ems-open-tool-modal','ems-nav','linguar-open-daily-run'].includes(data.type)) {
      window.parent.postMessage(data,location.origin);
    }
  });
  function visible(show) {
    document.body.classList.toggle('snapshot-job-docked',show);
    const host = document.querySelector('#snapshot-job-comments');
    if (host) host.hidden = !show;
  }
  return {select, visible, render() {}};
})();
