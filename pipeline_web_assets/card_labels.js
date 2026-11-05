window.CardLabels = (() => {
  const colors = {green:'#216e4e',yellow:'#7f5f01',orange:'#974f0c',red:'#ae2e24',purple:'#6e5dc6',blue:'#0055cc',sky:'#206a83',lime:'#4c6b1f',pink:'#943d73',black:'#44546f'};
  function mount(root, client, cardId) {
    const host = root.querySelector('[data-quick-labels]');
    if (!host || host._mounted || !cardId || !window.pywebview?.api?.card_labels_load) return;
    host._mounted = true;
    host.innerHTML = '<div data-label-chips aria-label="Current labels"></div><details><summary aria-label="Add or remove labels">+ Labels</summary><div class="quick-label-picker"><input type="search" aria-label="Search labels" placeholder="Search labels…"><div data-label-options></div><button type="button" data-label-reload>Reload labels</button></div></details><small role="status"></small>';
    const api = window.pywebview.api, details = host.querySelector('details'), search = host.querySelector('input');
    const status = host.querySelector('small'), list = host.querySelector('[data-label-options]'), chips = host.querySelector('[data-label-chips]');
    let labels = [], selected = new Set(), board = '', pending = new Set(), failed = new Set(), loading = false;
    const title = label => label.name || `${label.color || 'Uncolored'} label`;
    const publish = () => document.dispatchEvent(new CustomEvent('oneloss-card-labels', {detail:{cardId,labels:labels.filter(label=>selected.has(label.id))}}));
    const color = label => colors[String(label.color || '').split('_')[0]] || '#44546f';
    function paint() {
      chips.replaceChildren(); list.replaceChildren();
      for (const label of labels) {
        if (selected.has(label.id)) {
          const chip = document.createElement('button'); chip.type = 'button'; chip.textContent = title(label);
          chip.style.backgroundColor = color(label); chip.className = 'quick-label-chip';
          chip.onclick = () => {details.open = true; search.focus();}; chips.append(chip);
        }
        if (!title(label).toLowerCase().includes(search.value.toLowerCase())) continue;
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = title(label); button.style.borderLeft = `8px solid ${color(label)}`;
        button.setAttribute('aria-pressed', String(selected.has(label.id)));
        button.disabled = loading || pending.has(label.id) || failed.has(label.id);
        button.onclick = async () => {
          const want = !selected.has(label.id);
          want ? selected.add(label.id) : selected.delete(label.id);
          pending.add(label.id); paint(); status.textContent = 'Saving labels…';
          let result;
          try {result = await api.card_labels_toggle(client, cardId, label.id, want, board);}
          catch (_) {result = {ok:false};}
          pending.delete(label.id);
          if (!result?.ok) {
            want ? selected.delete(label.id) : selected.add(label.id);
            failed.add(label.id);
          }
          paint();
          status.textContent = failed.size ? 'Could not confirm a change. Reload labels to check.' : pending.size ? 'Saving labels…' : 'Labels saved';
          if(result?.warning) status.textContent=result.warning;
          if(result?.ok && !pending.size && !failed.size) publish();
          if(result?.ok && result.work_environment){
            const select=root.querySelector('[data-work-env="Contents"], [data-work-env="CONTENTS"]');
            // Do not clobber an in-flight manual stage save.
            if(select && !select.disabled){
              select.value=result.work_environment.stage;
              select.closest('[data-work-type-card]')?.classList.toggle('has-stage',select.value!=='not_applicable');
            }
          }
        };
        list.append(button);
      }
      if (!list.children.length) list.textContent = loading ? 'Loading labels…' : 'No matching labels';
    }
    async function load() {
      if (pending.size || loading) return;
      loading = true; paint(); status.textContent = 'Loading labels…';
      let result;
      try {result = await api.card_labels_load(client, cardId);} catch (_) {result = {ok:false};}
      loading = false;
      if (result?.ok) { labels = result.labels; selected = new Set(result.selected); board = result.board_id; failed.clear(); }
      else {labels = []; selected.clear();}
      paint(); status.textContent = result?.ok ? '' : result?.error || 'Labels unavailable. Try Reload labels.';
      if(result?.ok) publish();
    }
    search.oninput = paint;
    details.addEventListener('toggle', () => {if (details.open) search.focus();});
    host.addEventListener('keydown', event => {if (event.key === 'Escape' && details.open) {event.stopPropagation(); details.open = false; host.querySelector('summary').focus();}});
    host.querySelector('[data-label-reload]').onclick = load;
    load();
  }
  return {mount};
})();
