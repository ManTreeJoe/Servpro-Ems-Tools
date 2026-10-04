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
    history.innerHTML = '<div class="section-title-row"><h3>Card activity</h3><button type="button" class="btn compact">Refresh activity</button></div><p role="status">Open Card Details to load activity.</p><div data-card-activity-rows></div>';
    const legacy = document.createElement('details');
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
        for (const row of result.rows || []) {
          const article = document.createElement('article'); article.className = 'saved-run-row';
          const actor = document.createElement('strong'); actor.textContent = row.actor; actor.title = row.actor_id || '';
          const meta = document.createElement('small');
          const when = new Date(row.at); meta.textContent = `${Number.isNaN(when.getTime()) ? 'Date unavailable' : when.toLocaleString()} · ${row.source}`;
          const action = document.createElement('p'); action.textContent = row.action;
          article.append(actor, meta, action); activityRows.append(article);
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
