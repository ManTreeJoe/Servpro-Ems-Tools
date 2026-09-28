/* Read-only view of the selected office Run. No import/save actions live here. */
(function (host) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g,
    char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let dialog, options, request = 0, preview = null, openedFrom;
  const find = selector => dialog.querySelector(selector);
  const dateLabel = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return 'Not scheduled';
    return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,
      {month:'short',day:'numeric',year:'numeric'});
  };

  function init(config) {
    options = config;
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.className = 'schedule-import-review';
    dialog.setAttribute('aria-labelledby', 'import-review-title');
    dialog.innerHTML = `
      <header class="import-review-head">
        <div><p class="import-review-overline">Schedule transition · Read-only</p>
          <h2 id="import-review-title">Review digital import</h2>
          <p data-import-context></p></div>
        <button type="button" class="btn" data-import-close autofocus>Close</button>
      </header>
      <div class="import-review-body">
        <p class="import-review-note">Review how the saved Run will carry into the digital Schedule. Nothing is imported here; the Run remains your working copy.</p>
        <p class="import-review-warning" data-import-warning hidden></p>
        <div data-import-message role="status" aria-live="polite"></div>
        <button type="button" class="btn" data-import-retry hidden>Try again</button>
        <section data-import-content hidden>
          <p data-import-summary></p>
          <div class="import-review-filters">
            <label>Show<select data-import-filter><option value="all">All rows</option><option value="dated">Dated work</option><option value="waiting">Waiting / not scheduled</option></select></label>
            <label class="import-review-search">Find in Run<input type="search" data-import-search placeholder="Job, address, crew or note"></label>
          </div>
          <p class="import-review-help">Dates are proposals from the Run section. Job links, division, crew and arrival times still need confirmation. Crossed-out text is preserved, not assumed completed.</p>
          <p data-import-count role="status" aria-live="polite"></p>
          <div data-import-rows></div>
          <details class="import-review-source">
            <summary>Original Run text and source</summary>
            <p data-import-source></p><pre data-import-original></pre>
            <div data-import-tables></div>
          </details>
        </section>
      </div>
      <footer class="import-review-foot">Preview only. Shared Schedule storage and the final import step are not enabled yet.</footer>`;
    document.body.append(dialog);
    find('[data-import-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { request++; preview = null; openedFrom?.focus(); });
    find('[data-import-retry]').addEventListener('click', load);
    find('[data-import-filter]').addEventListener('change', renderRows);
    find('[data-import-search]').addEventListener('input', renderRows);
    document.querySelector('#review-schedule-import').addEventListener('click', open);
  }

  function open() {
    if (dialog.open) return;
    openedFrom = document.activeElement;
    dialog.showModal();
    find('[data-import-filter]').value = 'all';
    find('[data-import-search]').value = '';
    find('.import-review-source').open = false;
    load();
  }

  async function load() {
    const sequence = ++request;
    const current = {...options.context()};
    preview = null;
    find('[data-import-context]').textContent = `${current.workspace || ''} · ${dateLabel(current.date)}`;
    find('[data-import-content]').hidden = true;
    find('[data-import-retry]').hidden = true;
    find('[data-import-warning]').hidden = true;
    find('[data-import-message]').textContent = 'Reading the saved Run…';
    let timer;
    try {
      const result = await Promise.race([
        Promise.resolve().then(() => options.read(current)),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(
          'The Run did not finish loading. Check the shared folder, then try again.')), 30_000); }),
      ]);
      if (!dialog.open || sequence !== request) return;
      const now = options.context();
      if (now.date !== current.date || now.workspace !== current.workspace)
        throw new Error('The selected day or workspace changed. Close this preview and open it again.');
      if (!result?.ok) throw new Error(result?.error || 'The Run could not be read. Check the selected day and shared folder.');
      if (result.workspace !== current.workspace || result.run_date !== current.date)
        throw new Error('This preview belongs to another day or workspace. Close it and reload the Schedule.');
      if (!Array.isArray(result.visits) || !Array.isArray(result.paragraphs))
        throw new Error('The import preview is incomplete. Try again.');
      preview = result;
      const warnings = [];
      if (current.dirty) warnings.push('This preview uses the saved Run. Your unsaved Schedule edits are not included.');
      if (current.version && current.version !== result.source_version)
        warnings.push('The Word file changed since you opened the Schedule. This preview shows the newer saved file; your editor has not been replaced.');
      if ((result.blockers || []).includes('tables_require_review')) warnings.push('The Run contains tables. Their text is included below and needs separate review.');
      if ((result.blockers || []).includes('tracked_changes_or_textboxes_require_review')) warnings.push('Tracked changes or text boxes need review in the original Word document. They are not fully represented in this list.');
      find('[data-import-warning]').textContent = warnings.join(' ');
      find('[data-import-warning]').hidden = !warnings.length;
      const waiting = result.visits.filter(row => !row.proposed_date).length;
      find('[data-import-summary]').textContent = `${result.visits.length} rows to review · ${result.visits.length - waiting} dated · ${waiting} waiting / undated`;
      find('[data-import-source]').textContent = `${result.source_filename || 'Selected Run'} · ${result.paragraphs.length} paragraphs preserved · Revision ${String(result.source_version || '').slice(0, 12)}`;
      find('[data-import-original]').textContent = result.paragraphs.map(row => row.raw_text || '').join('\n');
      find('[data-import-tables]').innerHTML = (result.tables || []).map((table, index) =>
        `<h3>Table ${index + 1}</h3><div class="import-review-table-wrap"><table>${table.map(row =>
          `<tr>${row.map(cell => `<td>${escape(cell)}</td>`).join('')}</tr>`).join('')}</table></div>`).join('');
      find('[data-import-message]').textContent = '';
      find('[data-import-content]').hidden = false;
      renderRows();
    } catch (error) {
      if (!dialog.open || sequence !== request) return;
      find('[data-import-message]').textContent = error.message || 'The Run could not be read.';
      find('[data-import-retry]').hidden = false;
    } finally { clearTimeout(timer); }
  }

  function renderRows() {
    if (!preview) return;
    const filter = find('[data-import-filter]').value;
    const query = find('[data-import-search]').value.trim().toLocaleLowerCase();
    const rows = preview.visits.filter(row =>
      (filter === 'all' || (filter === 'dated' ? !!row.proposed_date : !row.proposed_date)) &&
      (!query || String(row.raw_text || '').toLocaleLowerCase().includes(query)));
    find('[data-import-count]').textContent = `${rows.length} of ${preview.visits.length} rows shown`;
    const groups = new Map();
    for (const row of rows) {
      if (!groups.has(row.section)) groups.set(row.section, []);
      groups.get(row.section).push(row);
    }
    find('[data-import-rows]').innerHTML = rows.length ? [...groups].map(([section, entries]) => `
      <section class="import-review-group">
        <h3>${escape(preview.section_labels?.[section] || section)} <span>${entries.length}</span></h3>
        <ol>${entries.map(row => `<li data-import-row>
          <div class="import-review-line"><span>${row.struck ? `<s>${escape(row.raw_text)}</s>` : escape(row.raw_text)}</span>
            <small>Run paragraph ${Number(row.source_paragraph) + 1}${row.struck ? ' · Crossed out in Run' : ''}</small></div>
          <span class="import-review-date">${row.proposed_date ? escape(dateLabel(row.proposed_date)) : 'Not scheduled'}</span>
        </li>`).join('')}</ol>
      </section>`).join('') : '<p class="import-review-no-results">No matching rows. Try another search or show all rows.</p>';
  }
  host.ScheduleImportReview = {init};
})(window);
