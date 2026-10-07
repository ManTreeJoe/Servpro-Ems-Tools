/* Shared read-only summary in Analytics and job cards. */
window.LaneTimingSummary = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const duration = s => s == null ? 'Unknown' : s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : `${Math.floor(s / 86400)}d ${Math.floor(s % 86400 / 3600)}h`;
  const date = s => s ? new Date(s).toLocaleString('en-US', {year:'2-digit',month:'2-digit',day:'2-digit',hour:'numeric',minute:'2-digit'}) : 'Not recorded';
  function render(data) {
    const snapshots = data.snapshot_cycles || [], waits = data.waiting_lanes || [], logs = data.logs_arrivals || [];
    const row = (title, detail, value) => `<div class="lane-time-row"><div><b>${esc(title)}</b><small>${esc(detail)}</small></div><strong>${duration(value)}</strong></div>`;
    return `<section class="lane-time-summary"><h3>Snapshot turnaround</h3><p>Snapshot entry → estimator assignment · verified IE lane mappings</p>
      ${snapshots.map(s => row(s.assigned_lane ? `Assigned to ${s.assigned_lane}` : s.seconds == null ? 'Assignment unresolved' : 'Waiting for assignment', `${date(s.started)} → ${s.ended ? date(s.ended) : 'Not recorded'}`, s.seconds)).join('') || '<p>No verified Snapshot cycle.</p>'}
      <h3>Waiting time</h3><p>Recorded time by waiting lane, including returns. Not a full-job total.</p>
      ${waits.map(w => row(w.lane, `${w.board} · ${w.visits} visit${w.visits === 1 ? '' : 's'}${w.unknown_visits ? ` · ${w.unknown_visits} with unknown duration; total is partial` : ''}`, w.unknown_visits === w.visits ? null : w.seconds)).join('') || '<p>No recorded waiting intervals.</p>'}
      <h3>Logs arrivals</h3><p>Entering Logs is the milestone—not Billed or payment.</p>
      ${logs.length ? logs.map(l => `<div class="lane-time-row"><div><b>${esc(l.lane)}</b><small>${date(l.entered)}</small></div></div>`).join('') + row('Current time in Logs', 'Across Logs lanes · not payment aging', data.logs_age_seconds) : '<p>No verified Logs arrival.</p>'}
    </section>`;
  }
  return {render};
})();
