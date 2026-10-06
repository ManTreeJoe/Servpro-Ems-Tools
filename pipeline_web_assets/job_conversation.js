/* One conversation pane, exact linked card identities, no name matching. */
window.JobConversation = (() => {
  const divisions = ['EMS', 'CONTENTS', 'RECON'];
  const label = key => ({EMS:'EMS', CONTENTS:'Contents', RECON:'Recon'})[key] || key;
  const normalize = value => String(value || 'EMS').toUpperCase().replace('RECONSTRUCTION', 'RECON');
  const esc = value => String(value || '').replace(/[&<>"']/g, char =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]);
  function mount(root, options) {
    const current = normalize(options.division);
    const cards = new Map();
    for (const row of options.cards || []) {
      const division = normalize(row.division);
      if (divisions.includes(division) && row.card_id && row.pinned !== false && !row.conflict) {
        cards.set(division, String(row.card_id));
      }
    }
    if (options.cardId) cards.set(current, String(options.cardId));
    // One provider card must never appear twice under different divisions.
    for (const [division, id] of cards) {
      if (division !== current && id === cards.get(current)) cards.delete(division);
    }
    const visible = new Set([current]);
    const records = new Map([[current, options.comments || []]]);
    const versions = new Map();
    const pending = new Map();
    const errors = new Map();
    const completed = new Set(options.initialComplete ? [current] : []);
    if (options.initialError) errors.set(current, String(options.initialError));
    const controls = document.createElement('div');
    controls.className = 'comment-division-controls';
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', 'Choose one comments division');
    const buttons = new Map();
    for (const division of options.followWorkspace ? [] : divisions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label(division);
      button.dataset.commentDivision = division;
      button.disabled = !cards.has(division);
      if (button.disabled) button.title = 'No verified linked card';
      button.onclick = () => {
        visible.clear(); visible.add(division);
        paint();
        refresh(false);
      };
      controls.append(button);
      buttons.set(division, button);
    }
    if (!options.followWorkspace) root.querySelector('.comment-search').before(controls);
    const status = document.createElement('small');
    status.className = 'comment-division-status';
    status.setAttribute('role', 'status');
    if (options.followWorkspace) {
      status.classList.add('workspace-comment-status');
      root.querySelector('.activity-head').append(status);
    } else controls.append(status);
    const errorStatus = document.createElement('small');
    errorStatus.className = 'comment-division-error';
    errorStatus.setAttribute('role', 'alert');
    errorStatus.hidden = true;
    root.querySelector('.comment-search').before(errorStatus);
    const selectedDestinations = new Set([current]);
    const destination = document.createElement('div');
    destination.className = 'comment-post-destination';
    destination.append('Send to ');
    const pills = document.createElement('div');
    pills.className = 'comment-division-controls comment-post-pills';
    pills.setAttribute('role', 'group');
    pills.setAttribute('aria-label', 'Post comment to divisions');
    const postPills = new Map();
    for (const division of divisions) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = label(division);
      button.dataset.commentDestination = division;
      button.onclick = () => {
        if (selectedDestinations.has(division)) selectedDestinations.delete(division);
        else selectedDestinations.add(division);
        paintDestinations();
      };
      postPills.set(division, button); pills.append(button);
    }
    function paintDestinations() {
      for (const [division, button] of postPills) {
        button.disabled = !cards.has(division);
        button.title = button.disabled ? 'No verified linked card' : '';
        button.setAttribute('aria-pressed', String(selectedDestinations.has(division) && cards.has(division)));
      }
    }
    paintDestinations();
    destination.append(pills);
    (root.querySelector('.comment-send-row') || root.querySelector('.comment-compose')).prepend(destination);
    const primaryIds = new Set([...cards.values()]);
    const extraPlacements = (options.placements || []).filter(row =>
      row?.card_id && row.pinned !== false && !row.primary &&
      !primaryIds.has(String(row.card_id)));
    let placementPicker = null;
    if (extraPlacements.length) {
      placementPicker = document.createElement('details');
      placementPicker.className = 'comment-extra-destinations';
      placementPicker.innerHTML = `<summary>Also post to linked boards</summary><div>${extraPlacements.map(row => {
        const title = row.board || row.purpose || 'Linked board';
        const location = row.lane ? ` · ${row.lane}` : '';
        return `<label><input type="checkbox" data-comment-placement="${esc(row.card_id)}"><span>${esc(label(normalize(row.division)))} · ${esc(title)}${esc(location)}</span></label>`;
      }).join('')}</div>`;
      root.querySelector('.comment-compose').prepend(placementPicker);
    }
    const stream = root.querySelector('[data-comment-stream]');
    const post = root.querySelector('[data-post-comment]');
    if (post) post.disabled = !cards.size;
    let fingerprint = null;
    function paint() {
      for (const [key, button] of buttons) {
        button.setAttribute('aria-pressed', String(visible.has(key)));
      }
      const messages = [];
      const seen = new Set();
      for (const division of visible) {
        for (const row of records.get(division) || []) {
          const key = `${cards.get(division)}:${row.external_id || row.id}`;
          if (seen.has(key)) continue;
          seen.add(key);
          messages.push({...row, division, card_id: cards.get(division)});
        }
      }
      messages.sort((a,b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
      const failed = [...visible].some(key => errors.has(key));
      const loading = [...visible].some(key => pending.has(key) || !completed.has(key));
      const emptyText = failed ? 'Comments could not be checked. Try refreshing.'
        : loading ? '' : 'No comments in this division.';
      const nextFingerprint = JSON.stringify([messages, messages.length ? '' : emptyText]);
      if (nextFingerprint !== fingerprint) {
        const top = stream.scrollTop;
        stream.innerHTML = messages.map(options.render).join('') ||
          `<div class="aud-empty activity-empty" role="status">${emptyText}</div>`;
        stream.scrollTop = top;
        fingerprint = nextFingerprint;
        const count = root.querySelector('[data-comment-count]');
        if (count) count.textContent = !messages.length && (loading || failed) ? '…' : String(messages.length);
        options.onChange?.();
      }
      const errorText = [...visible].flatMap(key => errors.has(key)
        ? [`${label(key)}: ${errors.get(key)}`]
        : []).join(' · ');
      const busy = loading && !failed;
      stream.setAttribute('aria-busy', String(busy));
      status.classList.toggle('is-loading', busy);
      status.innerHTML = busy ? '<span class="ui-spinner" aria-hidden="true"></span><span class="ui-loading-label">Loading comments…</span>' : '';
      status.title = busy ? 'Checking comments for updates' : '';
      errorStatus.textContent = errorText;
      errorStatus.hidden = !errorText;
    }
    async function refresh(force = true) {
      await Promise.all([...visible].filter(key => cards.has(key)).map(async key => {
        if (pending.has(key)) return pending.get(key);
        if (!force && completed.has(key) && !errors.has(key)) return;
        errors.delete(key);
        const version = versions.get(key) || 0;
        const requestedCard = cards.get(key);
        const task = Promise.resolve().then(async () => {
          if (!records.has(key) && options.fetchSaved) {
            try {
              const saved = await options.fetchSaved(requestedCard);
              if (saved?.ok && saved.cached && cards.get(key) === requestedCard &&
                  (versions.get(key) || 0) === version) {
                records.set(key, saved.comments || []);
                if (root.isConnected) paint();
              }
            } catch (_) { /* A local cache miss must not block remote recovery. */ }
          }
          return options.fetch(requestedCard, force);
        }).then(result => {
          if (!result?.ok) throw new Error(result?.error || 'Could not refresh');
          if (cards.get(key) === requestedCard && (versions.get(key) || 0) === version) {
            records.set(key, result.comments || []);
            completed.add(key);
            versions.set(key, version + 1);
          }
          errors.delete(key);
        }).catch(error => errors.set(key, String(error?.message || error))).finally(() => {
          pending.delete(key); if (root.isConnected) paint();
        });
        pending.set(key, task); paint(); await task;
      }));
    }
    function mutate(cardId, action) {
      const division = [...cards.keys()].find(key => cards.get(key) === cardId);
      if (!division) return;
      versions.set(division, (versions.get(division) || 0) + 1);
      records.set(division, action(records.get(division) || []));
      paint();
    }
    paint();
    // The initial workspace owns its remote refresh. Read only the saved
    // projection here so comments can paint before that larger request ends.
    if (options.cardId && options.fetchSaved && !completed.has(current) &&
        !(records.get(current) || []).length) {
      const requestedCard = cards.get(current);
      Promise.resolve().then(() => options.fetchSaved(requestedCard)).then(saved => {
        if (!root.isConnected || cards.get(current) !== requestedCard ||
            completed.has(current) || versions.get(current) ||
            (records.get(current) || []).length) return;
        if (saved?.ok && saved.cached && Array.isArray(saved.comments)) {
          records.set(current, saved.comments);
          paint();
        }
      }).catch(() => {}); // A cache miss must not interfere with live loading.
    }
    return {
      refresh,
      updateCards(rows) {
        const hadCards = cards.size > 0;
        const next = new Map();
        for (const row of rows || []) {
          const division = normalize(row.division);
          if (divisions.includes(division) && row.card_id && row.pinned !== false && !row.conflict) next.set(division, String(row.card_id));
        }
        if (options.cardId) next.set(current, String(options.cardId));
        for (const [division, id] of next) if (division !== current && id === next.get(current)) next.delete(division);
        for (const division of divisions) {
          if (cards.get(division) !== next.get(division)) { records.delete(division); versions.delete(division); errors.delete(division); completed.delete(division); }
        }
        cards.clear(); for (const [division, id] of next) cards.set(division, id);
        for (const [division, button] of buttons) { button.disabled = !cards.has(division); button.title = button.disabled ? 'No verified linked card' : ''; }
        for (const division of selectedDestinations) if (!cards.has(division)) selectedDestinations.delete(division);
        paintDestinations();
        if (post && (!cards.size || !hadCards)) post.disabled = !cards.size;
        paint();
      },
      resetTargets() {
        selectedDestinations.clear(); selectedDestinations.add(current);
        placementPicker?.querySelectorAll('[data-comment-placement]').forEach(input => {input.checked=false;});
        paintDestinations();
      },
      restoreTargets(ids) {
        const allowed = new Set(ids || []);
        selectedDestinations.clear();
        for (const [division, id] of cards) if (allowed.has(id)) selectedDestinations.add(division);
        placementPicker?.querySelectorAll('[data-comment-placement]').forEach(input => {input.checked = allowed.has(input.dataset.commentPlacement);});
        paintDestinations();
      },
      retainFailedTargets(ids) {
        const failed = new Set(ids);
        for (const division of selectedDestinations) if (!failed.has(cards.get(division))) selectedDestinations.delete(division);
        placementPicker?.querySelectorAll('[data-comment-placement]').forEach(input => {input.checked=failed.has(input.dataset.commentPlacement);});
        paintDestinations();
      },
      target: () => { const division = [...selectedDestinations][0]; return {division, cardId:cards.get(division) || ''}; },
      targets: () => {
        const selected = [...selectedDestinations].map(division => ({division,
          cardId:cards.get(division) || '', primary:true}));
        for (const input of placementPicker?.querySelectorAll('[data-comment-placement]:checked') || []) {
          const row = extraPlacements.find(item => String(item.card_id) === input.dataset.commentPlacement);
          if (row) selected.push({division: normalize(row.division),
            cardId: String(row.card_id), purpose: row.purpose || '',
            board: row.board || '', lane: row.lane || ''});
        }
        return selected.filter((row, index, rows) => row.cardId &&
          rows.findIndex(other => other.cardId === row.cardId) === index);
      },
      applyInitialRefresh(cardId, comments, complete = true, error = '') {
        const division = [...cards.keys()].find(key => cards.get(key) === cardId);
        if (division && !versions.get(division) && !pending.has(division)) {
          if (complete || comments.length) records.set(division, comments);
          if (error) errors.set(division, String(error));
          else if (complete) { completed.add(division); errors.delete(division); }
          paint();
        }
      },
      add(cardId, comment) {
        mutate(cardId, rows => [comment, ...rows.filter(row => row.id !== comment.id)]);
        const division = [...cards.keys()].find(key => cards.get(key) === cardId);
        if (division) { visible.clear(); visible.add(division); }
        paint();
      },
      update(cardId, id, text) { mutate(cardId, rows => rows.map(row => row.id === id ? {...row, text} : row)); },
      remove(cardId, id) { mutate(cardId, rows => rows.filter(row => row.id !== id)); },
    };
  }
  return {mount};
})();
