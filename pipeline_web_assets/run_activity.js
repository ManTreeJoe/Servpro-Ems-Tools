window.SavedRunActivity = (() => {
  function mount(host, client, division, cardId = '') {
    if (!host) return;
    for (const child of [...host.children]) if (child.tagName !== 'SUMMARY') child.remove();
    let loaded = false, busy = false;
    const section = document.createElement('div');
    section.innerHTML = '<div class="section-title-row"><h3>Saved run history</h3><button type="button" class="btn compact">Refresh saved history</button></div><p role="status">Expand to load saved Run history.</p><div data-run-history-rows></div>';
    // The tab already names this section; keep the outer details open without
    // a redundant second heading/collapse control.
    host.open = true;
    const summary = host.querySelector('summary'); if (summary) summary.style.display = 'none';
    const history = document.createElement('div');
    history.className = 'card-history';
    history.innerHTML = '<div class="section-title-row"><div><h3>Card history</h3><span class="card-history-caption">Movement & placement · newest first</span></div><button type="button" class="btn compact">Refresh activity</button></div><p class="card-history-status" role="status">Open Card Details to load activity.</p><div data-card-activity-rows></div>';
    const legacy = document.createElement('details');
    legacy.className = 'card-history-legacy';
    const legacyLabel = document.createElement('summary'); legacyLabel.textContent = 'Legacy Run history';
    legacy.append(legacyLabel, section); host.append(history, legacy);
    const activityStatus = history.querySelector('[role=status]'), activityButton = history.querySelector('button'), activityRows = history.querySelector('[data-card-activity-rows]');
    let activityLoaded = false, activityBusy = false;
    async function loadActivity() {
      if (activityBusy || !host.isConnected) return;
      activityBusy = true; activityButton.disabled = true; history.setAttribute('aria-busy', 'true');
      activityStatus.textContent = 'Loading card activity…';
      try {
        const result = await window.pywebview.api.card_activity_history(cardId);
        if (!host.isConnected) return;
        if (!result?.ok) throw Error(result?.error || 'Card history could not load.');
        activityLoaded = true; activityRows.replaceChildren();
        activityStatus.textContent = result.note || '';
        if (!result.rows?.length) activityStatus.textContent += ' No saved movement events for this card yet.';
        let dayKey = '', dayList;
        for (const row of result.rows || []) {
          const when = new Date(row.at), valid = !Number.isNaN(when.getTime());
          const date = valid ? when.toLocaleDateString('en-US', {month:'2-digit',day:'2-digit',year:'2-digit'}) : 'Date unavailable';
          if (date !== dayKey) {
            dayKey = date;
            const group = document.createElement('section'); group.className = 'card-history-day';
            const heading = document.createElement('h4'); heading.textContent = date;
            dayList = document.createElement('ol'); group.append(heading, dayList); activityRows.append(group);
          }
          const article = document.createElement('li'); article.className = 'saved-run-row card-history-event';
          const marker = document.createElement('span'); marker.className = 'card-history-marker'; marker.setAttribute('aria-hidden','true');
          marker.textContent = (row.actor || '?').trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();
          const body = document.createElement('div'); body.className = 'card-history-event-body';
          const action = document.createElement('p'); action.className = 'card-history-action'; action.textContent = row.action;
          const meta = document.createElement('div'); meta.className = 'card-history-meta';
          const actor = document.createElement('strong'); actor.textContent = row.actor || 'Unknown user'; actor.title = row.actor_id || '';
          const source = document.createElement('span'); source.textContent = row.source || 'Source unavailable';
          const time = document.createElement('time'); time.textContent = valid ? when.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}) : 'Time unavailable';
          if (valid) {time.dateTime = when.toISOString();time.title = when.toLocaleString('en-US');}
          meta.append(actor, source, time); body.append(action, meta); article.append(marker, body); dayList.append(article);
        }
      } catch (error) {
        if (host.isConnected) activityStatus.textContent = `${error.message || error} Use Refresh activity to retry.`;
      } finally {
        activityBusy = false; activityButton.disabled = false; history.setAttribute('aria-busy', 'false');
      }
    }
    activityButton.onclick = loadActivity;
    legacy.addEventListener('toggle', () => { if (legacy.open && !loaded) load(); });
    const status = section.querySelector('[role=status]'), button = section.querySelector('button'), list = section.querySelector('[data-run-history-rows]');
    async function load() {
      if (busy || !host.isConnected) return;
      loaded = true; busy = true; button.disabled = true; status.textContent = 'Loading saved history…';
      try {
        const result = await window.pywebview.api.saved_run_activity(client, division);
        if (!host.isConnected) return;
        if (!result?.ok) throw Error(result?.error || 'Saved history could not be loaded.');
        list.replaceChildren();
        const count = host.querySelector('summary span'); if (count) count.textContent = String((result.rows || []).length);
        status.textContent = (result.note || '') + (!(result.rows || []).length ? ' · No exact job-name match in the imported history.' : '');
        for (const row of result.rows || []) {
          const article = document.createElement('article'); article.className = 'saved-run-row';
          const title = document.createElement('strong'); title.textContent = `${row.iso} · ${(row.labels || []).join(', ') || 'Scheduled work'}`;
          const crew = document.createElement('small'); crew.textContent = `Scheduled${row.techs?.length ? ' · ' + row.techs.join(', ') : ''}`;
          const raw = document.createElement('p'); raw.textContent = row.raw;
          const open = document.createElement('button'); open.className = 'text-btn'; open.textContent = 'Open source run';
          open.onclick = async () => {
            try { const result = await window.pywebview.api.open_document(row.source); if (!result?.ok) throw Error(result?.error || 'Source unavailable'); }
            catch (error) { status.textContent = error.message || String(error); }
          };
          article.append(title, crew, raw, open); list.append(article);
        }
      } catch (error) { status.textContent = `History unavailable: ${error.message || error}. Retry with Refresh saved history.`; }
      finally { busy = false; button.disabled = false; }
    }
    button.onclick = load;
    host._runActivity = {activate() { if (!activityLoaded) loadActivity(); }};
  }
  return {mount};
})();
