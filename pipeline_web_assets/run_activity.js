window.SavedRunActivity = (() => {
  const zone = 'America/Los_Angeles';
  function mount(host, client, division, cardId = '') {
    if (!host) return;
    for (const child of [...host.children]) if (child.tagName !== 'SUMMARY') child.remove();
    host.open = true;
    const summary = host.querySelector('summary'); if (summary) summary.style.display = 'none';
    const history = document.createElement('div'); history.className = 'card-history';
    history.innerHTML = '<div class="section-title-row"><div><h3>Card history</h3><span class="card-history-caption">OneLoss · Trello · Daily Run — newest first</span></div><button type="button" class="btn compact">Refresh activity</button></div><p role="status" class="card-history-status"></p><div data-card-activity-rows></div>';
    host.append(history);
    const status = history.querySelector('[role=status]'), button = history.querySelector('button'), list = history.querySelector('[data-card-activity-rows]');
    let busy = false, loaded = false;
    const snapshots = new Map();
    function render(rows) {
      list.replaceChildren();
      const day = row => /^\d{4}-\d{2}-\d{2}$/.test(row.at || '') ? row.at : Number.isNaN(Date.parse(row.at)) ? '' : new Date(row.at).toLocaleDateString('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'});
      rows.sort((a,b) => day(b).localeCompare(day(a)) || (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
      let dayKey = '', dayList;
      for (const row of rows) {
        const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(row.at || '');
        const when = new Date(row.at), valid = !Number.isNaN(when.getTime());
        const date = dateOnly ? `${row.at.slice(5,7)}/${row.at.slice(8,10)}/${row.at.slice(0,4)}` : valid ? when.toLocaleDateString('en-US', {timeZone:zone,month:'2-digit',day:'2-digit',year:'numeric'}) : 'Date unavailable';
        if (date !== dayKey) {
          dayKey = date;
          const group = document.createElement('section'); group.className = 'card-history-day';
          const heading = document.createElement('h4'); heading.textContent = date;
          dayList = document.createElement('ol'); group.append(heading, dayList); list.append(group);
        }
        const article = document.createElement('li'); article.className = 'saved-run-row card-history-event';
        const body = document.createElement('div'); body.className = 'card-history-event-body';
        const action = document.createElement('p'); action.className = 'card-history-action'; action.textContent = row.action;
        action.style.whiteSpace = 'pre-wrap'; action.style.overflowWrap = 'anywhere';
        const meta = document.createElement('div'); meta.className = 'card-history-meta';
        const actor = document.createElement('strong'); actor.textContent = row.actor || 'Unknown user';
        const source = document.createElement('span'); source.textContent = row.source;
        const time = document.createElement('time'); time.textContent = dateOnly ? 'Time not recorded' : valid ? when.toLocaleTimeString('en-US',{timeZone:zone,hour:'numeric',minute:'2-digit',timeZoneName:'short'}) : 'Time unavailable';
        if (valid) time.dateTime = row.at;
        meta.append(actor, source, time); body.append(action, meta);
        if (row.document) {
          const open = document.createElement('button'); open.className = 'text-btn'; open.textContent = 'Open source run';
          open.onclick = async () => {
            try { const result = await window.pywebview.api.open_document(row.document); if (!result?.ok) throw Error('Source unavailable'); }
            catch (error) { status.textContent = error.message || String(error); }
          };
          body.append(open);
        }
        article.append(body); dayList.append(article);
      }
    }
    async function load() {
      if (busy || !host.isConnected) return;
      busy = true; button.disabled = true; history.setAttribute('aria-busy','true');
      status.textContent = 'Loading history…';
      const warnings = [], pending = new Set(['OneLoss','Trello','Daily Run']);
      const api = window.pywebview.api;
      await Promise.all([
        ['OneLoss', () => api.card_activity_history(cardId)],
        ['Trello', () => api.card_provider_activity(cardId)],
        ['Daily Run', () => api.saved_run_activity(client, division)]
      ].map(async ([name, read]) => {
        try {
          const result = await read();
          if (!result?.ok) throw Error(result?.error || `${name} unavailable`);
          snapshots.set(name, name === 'Daily Run' ? (result.rows || []).map(row => ({
            at:row.iso, source:'Daily Run · saved on this PC', actor:(row.techs || []).join(', ') || 'Scheduled crew not recorded',
            action:`Scheduled work — not proof of completion: ${(row.labels || []).join(', ') || 'Daily Run'}\n${row.raw || ''}`, document:row.source
          })) : result.rows || []);
          if (name === 'Trello' && result.note) warnings.push(result.note);
        } catch (error) { warnings.push(`${name}: ${error.message || error}${snapshots.has(name) ? ' Showing previously loaded events.' : ''}`); }
        finally {
          pending.delete(name);
          if (host.isConnected && history.isConnected) {
            const rows = [...snapshots.values()].flat();
            render(rows);
            status.textContent = [pending.size ? `Loading ${[...pending].join(', ')}…` : rows.length ? `${rows.length} events · Pacific time` : 'No history found in available sources.', ...warnings].join(' ');
          }
        }
      }));
      busy = false; loaded = !warnings.length; button.disabled = false; history.setAttribute('aria-busy','false');
    }
    button.onclick = load;
    host._runActivity = {activate() { if (!loaded) load(); }};
  }
  return {mount};
})();
