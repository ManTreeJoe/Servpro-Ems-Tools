window.VisitControls = (() => {
  let request = 0;
  const tokens = value => value.split(/\s*[,;/]\s*/).map(s=>s.trim()).filter(Boolean);
  const same = (a,b) => a.toLocaleLowerCase() === b.toLocaleLowerCase();
  async function open() {
    const ticket = ++request;
    const crew = document.querySelector('#field-crew');
    const host = document.querySelector('#crew-options');
    const search = document.querySelector('#crew-search');
    const message = document.querySelector('#crew-message');
    document.querySelector('#arrival-from').value = '';
    document.querySelector('#arrival-through').value = '';
    document.querySelector('#arrival-error').textContent = '';
    host.replaceChildren();search.value = '';message.textContent = 'Loading roster…';
    let result;
    try { result = await window.pywebview.api.get_crew_roster(); }
    catch { result = {ok:false}; }
    if (ticket !== request) return;
    const entries = result.entries || [];
    message.textContent = !result.ok ? 'Roster unavailable. Enter crew names above.' : entries.length ? '' : 'No technicians saved yet. Enter crew names above.';
    function render() {
      const selected = tokens(crew.value);
      host.replaceChildren();
      for (const entry of entries) {
        const names = [entry.name,...(entry.aliases || [])];
        if (!names.join(' ').toLowerCase().includes(search.value.toLowerCase())) continue;
        const label = document.createElement('label'), checkbox = document.createElement('input');
        checkbox.type = 'checkbox';checkbox.checked = selected.some(token=>names.some(name=>same(name,token)));
        label.append(checkbox,document.createTextNode(entry.name));host.append(label);
        checkbox.addEventListener('change',()=>{
          const retained = tokens(crew.value).filter(token=>!names.some(name=>same(name,token)));
          if (checkbox.checked) retained.push(entry.name);
          crew.value = retained.join(', ');crew.dispatchEvent(new Event('input',{bubbles:true}));
        });
      }
    }
    search.oninput = render;
    crew.oninput = render;
    render();
  }
  function applyArrival() {
    const from = document.querySelector('#arrival-from').value;
    const through = document.querySelector('#arrival-through').value;
    const error = document.querySelector('#arrival-error');
    if (!from || !through || through <= from) {
      error.textContent = 'Choose both times, with the latest arrival after the earliest.';return;
    }
    const label = time => {
      const [hour,minute] = time.split(':').map(Number);
      return `${hour%12||12}${minute?':'+String(minute).padStart(2,'0'):''} ${hour<12?'AM':'PM'}`;
    };
    const field=document.querySelector('#field-time');
    field.value=`${label(from)}–${label(through)}`;
    field.dispatchEvent(new Event('input',{bubbles:true}));error.textContent='';
  }
  return {open,applyArrival};
})();
