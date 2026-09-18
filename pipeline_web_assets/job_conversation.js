/* One conversation pane, exact linked card identities, no name matching. */
window.JobConversation = (() => {
  const divisions = ['EMS', 'CONTENTS', 'RECON'];
  const label = key => ({EMS:'EMS', CONTENTS:'Contents', RECON:'Recon'})[key] || key;
  const normalize = value => String(value || 'EMS').toUpperCase().replace('RECONSTRUCTION', 'RECON');
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
    const controls = document.createElement('div');
    controls.className = 'comment-division-controls';
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', 'Choose one comments division');
    const buttons = new Map();
    for (const division of divisions) {
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
    root.querySelector('.comment-search').before(controls);
    const status = document.createElement('small');
    status.className = 'comment-division-status';
    status.setAttribute('role', 'status');
    controls.after(status);
    const destination = document.createElement('label');
    destination.className = 'comment-post-destination';
    destination.append('Post to ');
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Post comment to division');
    for (const [division, id] of cards) {
      const item = document.createElement('option');
      item.value = division; item.textContent = label(division);
      select.append(item);
    }
    select.value = current;
    destination.append(select);
    root.querySelector('.comment-compose').prepend(destination);
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
      const nextFingerprint = JSON.stringify(messages);
      if (nextFingerprint !== fingerprint) {
        const top = stream.scrollTop;
        stream.innerHTML = messages.map(options.render).join('') ||
          '<div class="aud-empty activity-empty">No comments in the selected divisions.</div>';
        stream.scrollTop = top;
        fingerprint = nextFingerprint;
        const count = root.querySelector('[data-comment-count]');
        if (count) count.textContent = String(messages.length);
        options.onChange?.();
      }
      status.textContent = [...visible].flatMap(key => errors.has(key)
        ? [`${label(key)}: ${errors.get(key)}`]
        : pending.has(key) && !records.has(key) ? [`Loading ${label(key)}…`] : []).join(' · ');
    }
    async function refresh(force = true) {
      await Promise.all([...visible].filter(key => cards.has(key)).map(async key => {
        if (pending.has(key)) return pending.get(key);
        if (!force && records.has(key)) return;
        const version = versions.get(key) || 0;
        const requestedCard = cards.get(key);
        const task = Promise.resolve().then(() => options.fetch(requestedCard)).then(result => {
          if (!result?.ok) throw new Error(result?.error || 'Could not refresh');
          if (cards.get(key) === requestedCard && (versions.get(key) || 0) === version) {
            records.set(key, result.comments || []);
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
          if (cards.get(division) !== next.get(division)) { records.delete(division); versions.delete(division); errors.delete(division); }
        }
        const target = select.value;
        cards.clear(); for (const [division, id] of next) cards.set(division, id);
        for (const [division, button] of buttons) { button.disabled = !cards.has(division); button.title = button.disabled ? 'No verified linked card' : ''; }
        const available = [...cards.keys()];
        if (JSON.stringify([...select.options].map(o=>o.value)) !== JSON.stringify(available)) {
          select.replaceChildren(...available.map(division=>{const item=document.createElement('option');item.value=division;item.textContent=label(division);return item;}));
          select.value = cards.has(target) ? target : current;
        }
        if (post && (!cards.size || !hadCards)) post.disabled = !cards.size;
        paint();
      },
      target: () => ({division: select.value, cardId: cards.get(select.value) || ''}),
      applyInitialRefresh(cardId, comments) {
        const division = [...cards.keys()].find(key => cards.get(key) === cardId);
        if (division && !versions.get(division) && !pending.has(division)) {
          records.set(division, comments);
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
