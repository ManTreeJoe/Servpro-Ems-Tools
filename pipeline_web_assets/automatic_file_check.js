/* Scan only opened jobs, after their saved workspace is visible. No polling. */
window.AutomaticFileCheck = (() => {
  const checks = new Map();
  async function run(api, client, card, division, current, apply, status) {
    if (!current() || !api.refresh_job_card_workspace) return;
    const key = JSON.stringify([client, card, division]);
    let record = checks.get(key);
    if (record && !record.pending && Date.now() < record.retryAt) {
      status(record.failed ? 'File check unavailable · retry on next open' : record.missing ? 'Job folder unavailable · check its link' : '');
      return;
    }
    status('Checking files…');
    if (!record?.pending) {
      record = {pending: null, retryAt: 0};
      checks.set(key, record);
      record.pending = Promise.resolve().then(() => api.refresh_job_card_workspace(client, card, division))
        .then(result => {
          if (!result?.ok) throw new Error(result?.error || 'File check unavailable');
          record.failed = false; record.retryAt = Date.now() + 120000;
          record.missing = result.audit?.found === false;
          return result;
        }).catch(() => {
          record.failed = true; record.retryAt = Date.now() + 30000;
          return null;
        }).finally(() => { record.pending = null; });
      // Bound bookkeeping without evicting scans still running.
      if (checks.size > 200) for (const [id, item] of checks) {
        if (!item.pending && id !== key) { checks.delete(id); break; }
      }
    }
    const result = await record.pending;
    if (!current()) return;
    try { if (result) apply(result); }
    catch (_) { status('File results could not display · reopen job'); return; }
    status(result ? record.missing ? 'Job folder unavailable · check its link' : '' : 'File check unavailable · retry on next open');
  }
  return {run};
})();
