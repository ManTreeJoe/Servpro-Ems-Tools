/* Scheduling people only. Manual names remain usable if roster loading fails. */
window.ScheduleCrew = (() => {
  let entries = [], status = 'Loading crew…', sequence = 0, host, controls = [];
  const key = value => value.trim().toLowerCase();
  const tokens = input => input.value.split(/[,;/]/).map(s=>s.trim()).filter(Boolean);
  function button(text, action) {
    const el=document.createElement('button');el.type='button';el.className='btn';el.textContent=text;el.onclick=action;return el;
  }
  function write(input, people) {
    input.value=people.join(', ');input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function mount(container) {
    host = container;
    controls.forEach(c=>c.panel.remove());controls=[];
    for (const input of host.querySelectorAll('[data-assignment]')) {
      const label=input.parentElement,title=label.textContent.replace(/\s*— assigned to\s*$/, '').trim();
      const row=document.createElement('section');row.className='crew-row';
      const heading=document.createElement('strong');heading.textContent=title;
      const chips=document.createElement('div');chips.className='crew-chips';
      const panel=document.createElement('div');panel.className='crew-popover';panel.setAttribute('popover','auto');panel.setAttribute('aria-label',`Crew for ${title}`);
      const top=document.createElement('div');top.className='crew-popover-heading';
      const caption=document.createElement('strong');caption.textContent=`Crew · ${title}`;
      top.append(caption,button('Done',()=>{panel.hidePopover();trigger.focus();}));
      const search=document.createElement('input');search.type='search';search.placeholder='Search name or initials';search.setAttribute('aria-label','Search crew');
      const notice=document.createElement('p');notice.className='crew-notice';notice.setAttribute('role','status');
      const options=document.createElement('div');options.className='crew-options';
      const manual=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Edit names manually';
      const copy=button('Use this crew for all activities',()=>{
        controls.forEach(c=>{if(c.input!==input)write(c.input,tokens(input));});notice.textContent='Crew applied to all activities.';
      });
      copy.hidden=host.querySelectorAll('[data-assignment]').length<2;
      const trigger=button('Assign crew',()=>{panel.showPopover();place();search.focus();});
      trigger.dataset.crewPicker=input.dataset.assignment;trigger.setAttribute('aria-label',`Assign crew to ${title}`);trigger.setAttribute('aria-expanded','false');
      function place(){
        const rect=trigger.getBoundingClientRect();panel.style.width=Math.min(390,innerWidth-32)+'px';
        panel.style.left=Math.max(16,Math.min(rect.left,innerWidth-panel.offsetWidth-16))+'px';
        panel.style.top=Math.max(16,Math.min(rect.bottom+8,innerHeight-panel.offsetHeight-16))+'px';
      }
      function render(){
        chips.replaceChildren();
        for(const name of tokens(input)){
          const chip=button(name+' ×',()=>{write(input,tokens(input).filter(n=>key(n)!==key(name)));trigger.focus();});
          chip.className='crew-chip';chip.setAttribute('aria-label',`Remove ${name}`);chips.append(chip);
        }
        if(!tokens(input).length)chips.textContent='No crew assigned';
        options.replaceChildren();
        const found=entries.filter(p=>[p.name,...(p.aliases||[])].some(n=>key(n).includes(key(search.value))));
        notice.textContent=entries.length?(found.length?'Select everyone needed for this activity.':'No matching crew. Enter a name below.'):status;
        for(const person of found){
          const names=new Set([person.name,...(person.aliases||[])].map(key)),selected=tokens(input).some(n=>names.has(key(n)));
          const pill=button(person.name,()=>{
            const retained=tokens(input).filter(n=>!names.has(key(n)));if(!selected)retained.push(person.name);
            write(input,retained);[...options.children].find(el=>el.textContent===person.name)?.focus();
          });
          pill.setAttribute('aria-pressed',String(selected));options.append(pill);
        }
        if(panel.matches(':popover-open'))place();
      }
      label.before(row);manual.append(summary,label);panel.append(top,search,notice,options,manual,copy);row.append(heading,chips,trigger,panel);
      panel.addEventListener('toggle',()=>trigger.setAttribute('aria-expanded',String(panel.matches(':popover-open'))));
      search.oninput=render;input.addEventListener('input',render);controls.push({input,panel,render});render();
    }
  }
  async function load() {
    const ticket = ++sequence;
    entries = []; status = 'Loading crew…';
    controls.forEach(c=>c.render());
    try {
      const result = await window.pywebview.api.get_crew_roster();
      if (ticket !== sequence) return;
      if (!result.ok) throw new Error('Roster unavailable');
      entries = result.entries || [];
      status = 'No saved crew. Use Edit names manually below.';
    } catch {
      if (ticket !== sequence) return;
      status = 'Crew unavailable. Use Edit names manually below.';
    }
    controls.forEach(c=>c.render());
  }
  return {mount, load};
})();
