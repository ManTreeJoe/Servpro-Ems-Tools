/* Keep the existing work_type text contract for logs, Trello and PDF exports. */
window.JobActivities = {
  mount(select, value, crew) {
    const defaults = [...select.options].filter(o => o.value !== '__custom__').map(o => o.value);
    const root = document.createElement('div');
    root.className = 'job-activities';
    select.parentElement.replaceWith(root);
    select.hidden = true;
    root.append(select);
    const title = document.createElement('span'); title.textContent = 'Activities'; root.append(title);
    const details = document.createElement('details'); root.append(details);
    const summary = document.createElement('summary'); summary.setAttribute('aria-label', 'Select activities'); details.append(summary);
    const options = document.createElement('div'); options.className = 'job-activity-options'; details.append(options);
    options.setAttribute('popover', 'auto');
    const positionPicker = () => {
      const box = summary.getBoundingClientRect();
      const width = Math.min(Math.max(box.width, 300), window.innerWidth - 24);
      options.style.width = width + 'px';
      options.style.left = Math.max(12, Math.min(box.left, window.innerWidth - width - 12)) + 'px';
      const below = window.innerHeight - box.bottom - 16;
      const above = box.top - 16;
      const up = below < 240 && above > below;
      options.style.maxHeight = Math.max(80, Math.min(300, up ? above : below)) + 'px';
      options.style.top = (up ? Math.max(12, box.top - options.offsetHeight - 6) : box.bottom + 6) + 'px';
    };
    details.addEventListener('toggle', () => {
      if (details.open && root.isConnected) {
        options.showPopover(); positionPicker();
        window.addEventListener('resize', positionPicker);
        document.addEventListener('scroll', positionPicker, true);
      } else {
        options.hidePopover();
        window.removeEventListener('resize', positionPicker);
        document.removeEventListener('scroll', positionPicker, true);
      }
    });
    options.addEventListener('toggle', () => {
      if (!options.matches(':popover-open')) details.open = false;
    });
    const hint = document.createElement('small'); hint.textContent = 'Select all that apply'; root.append(hint);
    const assignments = document.createElement('div'); assignments.className = 'job-activity-assignments wide';
    assignments.style.cssText = 'grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px';
    root.after(assignments);
    if (crew) { crew.type = 'hidden'; crew.parentElement.hidden = true; }
    let people = {};
    let selected = [], choices = [...defaults];
    const renderSummary = () => {
      summary.replaceChildren();
      for (const name of selected) {
        const pill = document.createElement('span'); pill.className = 'job-activity-pill'; pill.textContent = name; summary.append(pill);
      }
      if (!selected.length) summary.textContent = 'Choose activities…';
    };
    const syncCrew = (notify = true) => {
      if (!crew) return;
      crew.value = selected.map(name => `${name}: ${people[name] || 'Unassigned'}`).join(' | ');
      if (notify) crew.dispatchEvent(new Event('input', {bubbles:true}));
    };
    const renderAssignments = () => {
      assignments.replaceChildren();
      for (const name of selected) {
        const label = document.createElement('label'); label.textContent = name + ' — assigned to';
        const input = document.createElement('input'); input.value = people[name] || '';
        input.placeholder = 'Names or initials, e.g. ME, FB';
        input.setAttribute('aria-label', name + ' assigned to');
        input.addEventListener('input', () => { people[name] = input.value.trim(); syncCrew(); });
        label.append(input); assignments.append(label);
      }
    };
    const render = () => {
      renderSummary(); renderAssignments();
      options.replaceChildren();
      for (const name of choices) {
        const pill = document.createElement('button');
        pill.type = 'button'; pill.className = 'job-activity-pill'; pill.textContent = name;
        pill.setAttribute('aria-pressed', String(selected.includes(name)));
        pill.addEventListener('click', () => {
          selected = selected.includes(name) ? selected.filter(n => n !== name) : [...selected, name];
          pill.setAttribute('aria-pressed', String(selected.includes(name)));
          commit();
          renderSummary(); renderAssignments();
          positionPicker();
        });
        options.append(pill);
      }
      const custom = document.createElement('input'); custom.placeholder = 'Custom activity'; custom.setAttribute('aria-label', 'Custom activity');
      const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Add activity';
      const addCustom = () => {
        const name = custom.value.trim(); if (!name) return;
        if (!choices.includes(name)) choices.push(name);
        if (!selected.includes(name)) selected.push(name);
        commit(); render(); positionPicker(); options.querySelector('[aria-label="Custom activity"]').focus();
      };
      add.onclick = addCustom;
      custom.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); addCustom(); } };
      options.append(custom, add);
    };
    const commit = (notify = true) => {
      const text = selected.join(' + ');
      select.replaceChildren(new Option(text, text, true, true));
      if (notify) {
        select.dispatchEvent(new Event('input', {bubbles:true}));
        select.dispatchEvent(new Event('change', {bubbles:true}));
      }
      syncCrew(notify);
    };
    const set = (text, crewText = crew?.value || '') => {
      selected = [...new Set(String(text || '').split(' + ').map(s => s.trim()).filter(Boolean))];
      people = {};
      const lines = crewText.split(' | ');
      const mapped = selected.some(name => lines.some(line => line.startsWith(name + ': ')));
      for (const name of selected) {
        const found = mapped ? (lines.find(line => line.startsWith(name + ': ')) || '').slice(name.length + 2) : crewText;
        people[name] = found === 'Unassigned' ? '' : found;
      }
      choices = [...new Set([...defaults, ...selected])]; commit(false); render();
    };
    details.addEventListener('keydown', e => { if (e.key === 'Escape') { details.open = false; summary.focus(); e.stopPropagation(); } });
    root.addEventListener('focusout', () => setTimeout(() => { if (!root.contains(document.activeElement)) details.open = false; }, 0));
    set(value || defaults[0]);
    if (!document.getElementById('job-activities-style')) {
      const style = document.createElement('style'); style.id = 'job-activities-style';
      style.textContent = `.job-activities{display:flex;flex-direction:column;gap:6px;min-width:0}.job-activities summary{cursor:pointer;display:flex;flex-wrap:wrap;gap:5px;padding:9px;border:1px solid var(--border,#555);border-radius:7px;min-height:38px}.job-activities summary:after{content:'▾';margin-left:auto}.job-activity-pill{display:inline-block;border:1px solid var(--border,#666);background:var(--surface-2,#272c32);color:var(--text,#eee);border-radius:14px;padding:3px 8px;font-size:12px}.job-activity-options{padding:8px;display:flex;flex-wrap:wrap;gap:8px;max-height:260px;overflow:auto;border:1px solid var(--border,#555)}.job-activity-options label{display:flex!important;flex-direction:row!important;align-items:center;gap:4px;cursor:pointer}.job-activity-options input[type=checkbox]{width:16px!important;height:16px}.job-activity-options input:checked+span{border-color:var(--accent,#68ae94)}.job-activities small{color:var(--muted,#aaa)}.job-activities summary:focus-visible{outline:2px solid var(--accent,#68ae94);outline-offset:2px}`;
      document.head.append(style);
      style.textContent += `.job-activity-options{position:fixed;inset:auto;margin:0;box-sizing:border-box;padding:12px;border-radius:10px;background:var(--surface,#202429);color:var(--text,#eee);box-shadow:0 12px 32px #0006;align-content:flex-start}.job-activity-options:not(:popover-open){display:none}.job-activity-options .job-activity-pill{cursor:pointer;font-weight:600;min-height:30px}.job-activity-options .job-activity-pill[aria-pressed=true]{background:var(--accent,#68ae94);border-color:var(--accent,#68ae94);color:#102a22}.job-activity-options .job-activity-pill:focus-visible{outline:2px solid var(--accent,#68ae94);outline-offset:2px}.job-activity-options input[aria-label="Custom activity"]{width:100%;min-width:0}.job-activity-options::backdrop{background:transparent}`;
    }
    return {set, focus:()=>summary.focus(), valid:()=>selected.length > 0};
  }
};
