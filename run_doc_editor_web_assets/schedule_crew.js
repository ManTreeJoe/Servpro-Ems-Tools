/* Scheduling people only. Manual names remain usable if roster loading fails. */
window.ScheduleCrew = (() => {
  let entries = [], status = 'Loading crew…', sequence = 0, host;
  const key = value => value.trim().toLowerCase();
  function fill(select) {
    select.replaceChildren(new Option(status, ''));
    for (const person of entries) select.add(new Option(person.name, person.name));
    select.disabled = !entries.length;
  }
  function mount(container) {
    host = container;
    for (const input of host.querySelectorAll('[data-assignment]')) {
      const select = document.createElement('select');
      select.dataset.crewPicker = input.dataset.assignment;
      select.setAttribute('aria-label', 'Add crew to ' + input.parentElement.textContent.trim());
      fill(select);
      input.parentElement.after(select);
      select.onchange = () => {
        const person = entries.find(p => p.name === select.value);
        if (!person) return;
        const aliases = new Set([person.name, ...(person.aliases || [])].map(key));
        const retained = input.value.split(/[,;/]/).map(s => s.trim())
          .filter(s => s && !aliases.has(key(s)));
        retained.push(person.name);
        input.value = retained.join(', ');
        input.dispatchEvent(new Event('input', {bubbles: true}));
        select.value = '';
      };
    }
  }
  async function load() {
    const ticket = ++sequence;
    entries = []; status = 'Loading crew…';
    host?.querySelectorAll('[data-crew-picker]').forEach(fill);
    try {
      const result = await window.pywebview.api.get_crew_roster();
      if (ticket !== sequence) return;
      if (!result.ok) throw new Error('Roster unavailable');
      entries = result.entries || [];
      status = entries.length ? 'Add crew member…' : 'No saved crew — type names above';
    } catch {
      if (ticket !== sequence) return;
      status = 'Crew unavailable — type names above';
    }
    host?.querySelectorAll('[data-crew-picker]').forEach(fill);
  }
  return {mount, load};
})();
