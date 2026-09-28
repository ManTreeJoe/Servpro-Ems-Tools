window.SavedRunActivity = (() => {
  function mount(host, client, division) {
    if (!host) return;
    for (const child of [...host.children]) if (child.tagName !== 'SUMMARY') child.remove();
    let loaded = false, busy = false;
    const section = document.createElement('div');
    section.innerHTML = '<div class="section-title-row"><h3>Saved run history</h3><button class="btn compact">Refresh saved history</button></div><p role="status">Open Run Activity to load saved history.</p><div data-run-history-rows></div>';
    host.append(section);
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
    host._runActivity = {activate() { if (!loaded) load(); }};
  }
  return {mount};
})();
