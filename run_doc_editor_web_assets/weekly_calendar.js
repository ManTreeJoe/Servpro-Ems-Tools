/* Storage-independent Schedule UI. No Word, network or persistence calls.
 * The host owns authorization, loading and edits; records are never mutated.
 * This presentation shape is not a proposed database schema.
 */
(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const iso = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  function date(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) throw new Error('Expected an ISO calendar date');
    const result = new Date(`${value}T12:00:00`);
    if (Number.isNaN(result.getTime()) || iso(result) !== value) throw new Error('Invalid calendar date');
    return result;
  }
  function shift(value, days) { const result=date(value); result.setDate(result.getDate()+days); return iso(result); }
  function week(value) { const start=shift(value,-((date(value).getDay()+6)%7)); return Array.from({length:7},(_,i)=>shift(start,i)); }
  function displayDate(value) { date(value); return `${value.slice(5,7)}/${value.slice(8,10)}/${value.slice(2,4)}`; }
  function parseDate(value) {
    if(!/^\d{2}\/\d{2}\/\d{2}$/.test(value)) throw new Error('Use MM/DD/YY');
    const result=`20${value.slice(6,8)}-${value.slice(0,2)}-${value.slice(3,5)}`;
    date(result); return result;
  }
  const label = value => `${date(value).toLocaleDateString(undefined,{weekday:'short'})} ${displayDate(value)}`;
  function activityColor(label) {
    const text=String(label||'').toLowerCase();
    if(text.includes('monitor'))return 'monitor';
    if(text.includes('initial'))return 'initial';
    if(text.includes('demo'))return 'demo';
    if(/contents|packout|pack back/.test(text))return 'contents';
    if(/equipment|pickup/.test(text))return 'equipment';
    return 'neutral';
  }

  function mount(host, options={}) {
    let selected=options.date || iso(new Date()), records=[], mode='calendar', query='', loading=false, error='';
    let period=options.period || 'three', anchor=selected;
    let disposed=false, draggedId=null;
    const today=()=>options.today?.() || iso(new Date());
    date(selected);
    function matching(row) {
      return (!row.completed || options.includeCompleted) &&
        [row.title,...(row.activities||[]).flatMap(a=>[a.label,...(a.people||[])])].join(' ').toLowerCase().includes(query.toLowerCase());
    }
    function rows(day) { return records.filter(r=>r.queue==='scheduled' && r.date===day && matching(r)); }
    function range() {
      if(period==='week') return week(anchor);
      if(period==='three') return [anchor,shift(anchor,1),shift(anchor,2)];
      const first=anchor.slice(0,7)+'-01', start=week(first)[0];
      return Array.from({length:42},(_,i)=>shift(start,i));
    }
    function grouped(items) {
      return ['Monitor','Work To Be Performed'].map(group=>{
        const entries=items.filter(r=>(r.group || 'Work To Be Performed')===group);
        return `<h3 class="wc-group-title">${group} <small>${entries.length}</small></h3>${entries.map(card).join('') || '<p class="wc-empty">None scheduled</p>'}`;
      }).join('');
    }
    function queues() {
      const groups=[['tbs','TBS New Loss /Reinspection'],['tbs','TBS Mitigation'],['tbs','TBS Contents'],['pending','Pending Testing/Clearance/Abatement'],['pending','Pending Approvals – Insurance/Self Pay'],['pending','Pending Approvals – Property Management'],['hold','On Hold']];
      return `<section class="wc-waiting"><h2>Waiting work</h2><p>Not booked on a day · grouped like the Run</p><div class="wc-waiting-grid" tabindex="0" aria-label="Waiting work groups">${groups.map(([queue,title])=>{
        const fallback={tbs:'TBS Mitigation',pending:'Pending Approvals – Insurance/Self Pay',hold:'On Hold'};
        const entries=records.filter(r=>r.queue===queue && (r.group||fallback[queue])===title && matching(r));
        return `<section class="wc-waiting-group"><h3>${escape(title)} <small>${entries.length}</small></h3><div class="wc-queue-scroll" tabindex="0" aria-label="${escape(title)} items">${entries.map(card).join('')||'<p class="wc-empty">No matching items</p>'}</div></section>`;
      }).join('')}</div></section>`;
    }
    function monthCell(day) {
      const entries=rows(day);
      return `<section class="wc-month-day ${day.slice(0,7)!==anchor.slice(0,7)?'wc-other-month':''}"><button class="wc-day-heading" type="button" data-open-day="${day}" aria-label="Open ${escape(label(day))}">${date(day).getDate()} <small>${entries.length} visits</small></button>${entries.slice(0,2).map(card).join('')}${entries.length>2?`<button type="button" class="btn" data-open-day="${day}">+ ${entries.length-2} more</button>`:''}</section>`;
    }
    function card(row) {
      const color=row.canceled?'canceled':row.queue==='pending'?'pending':row.queue==='hold'?'hold':activityColor(row.activities?.[0]?.label);
      return `<button type="button" class="wc-visit" data-color="${color}" data-edit="${escape(row.id)}" draggable="${Boolean(options.onSchedule)}" ${options.onEdit ? '' : 'disabled'}>
        ${row.time || row.canceled || row.completed ? `<span class="wc-time">${escape([row.time,row.canceled?'Canceled — needs rescheduling':row.completed?'Complete':''].filter(Boolean).join(' · '))}</span>` : ''}
        <strong>${escape(row.title)}</strong>
        ${row.needs_link?'<small class="wc-needs-link">Needs link</small>':row.trello_cards?.length?'<small>Trello linked</small>':''}
        ${(row.activities||[]).map(a=>`<span><span class="wc-activity" data-color="${activityColor(a.label)}">${escape(a.label)}</span>${a.people?.length ? `<small>${escape(a.people.join(', '))}</small>` : ''}</span>`).join('')}
        ${row.since && row.queue!=='scheduled' ? `<small>Since ${escape(displayDate(row.since))}</small>` : ''}
      </button>`;
    }
    function dayColumn(day) {
      const items=rows(day);
      return `<section class="wc-day ${day===selected?'is-selected':''}" aria-label="${escape(label(day))}">
        <button type="button" class="wc-day-heading" data-day="${day}" aria-pressed="${day===selected}" ${day===today()?'aria-current="date"':''}>${escape(label(day))}<small>${items.length} visit${items.length===1?'':'s'}</small></button>
        <div class="wc-day-items" tabindex="0" aria-label="${escape(label(day))} visits">${grouped(items)}</div>
        ${options.onAdd ? `<button type="button" class="btn wc-add" data-add="${day}">+ Add work<span class="wc-sr"> on ${escape(label(day))}</span></button>` : ''}
      </section>`;
    }
    function render(focus) {
      if (disposed) return;
      endDrag();
      const days=range();
      const queueRecords=records.filter(r=>r.queue===mode && matching(r));
      host.classList.add('weekly-schedule');
      host.dataset.period=period;
      host.dataset.mode=mode;
      host.innerHTML=`<header class="wc-toolbar">
        <div class="wc-navigation"><button type="button" class="btn" data-step="-1" aria-label="Previous ${period==='three'?'3 days':period}">←</button><button type="button" class="btn" data-today>Today</button><button type="button" class="btn" data-step="1" aria-label="Next ${period==='three'?'3 days':period}">→</button><h2>${period==='month'?date(anchor).toLocaleDateString(undefined,{month:'long',year:'numeric'}):`${escape(label(days[0]))} – ${escape(label(days.at(-1)))}, ${date(days.at(-1)).getFullYear()}`}</h2></div>
        <label class="wc-date">Selected day<input type="text" inputmode="numeric" placeholder="MM/DD/YY" aria-label="Selected day MM/DD/YY" value="${displayDate(selected)}" data-date></label>
        <button type="button" class="btn" data-mode="${mode==='legacy'?'calendar':'legacy'}">${mode==='legacy'?'Back to calendar':'Legacy view'}</button>
      </header>
      <nav class="wc-periods" aria-label="Calendar range">${[['three','3 Days'],['week','Week'],['month','Month']].map(([key,title])=>`<button class="btn" type="button" data-period="${key}" aria-pressed="${period===key && mode==='calendar'}">${title}</button>`).join('')}</nav>
      <nav class="wc-filters" aria-label="Schedule views">${[['calendar','Week'],['tbs','To be scheduled'],['pending','Pending'],['hold','On hold']].map(([key,text])=>`<button type="button" class="btn" data-mode="${key}" aria-pressed="${mode===key}">${text}${key==='calendar'?'':` (${records.filter(r=>r.queue===key && matching(r)).length})`}</button>`).join('')}<label class="wc-search"><span class="wc-sr">Search scheduled work</span><input type="search" placeholder="Find job, activity or crew" data-search value="${escape(query)}"></label></nav>
      <div class="wc-content" aria-busy="${loading}">${loading?'<p role="status">Loading schedule…</p>':error?`<p role="alert">${escape(error)}</p>${options.onRetry?'<button type="button" class="btn" data-retry>Retry</button>':''}`:mode==='calendar'?`<div class="wc-week">${days.map(dayColumn).join('')}</div>`:mode==='legacy'?`<section class="wc-legacy"><header><h2>${escape(label(selected))} — Daily Run</h2><p>Same visits as the calendar</p></header>${rows(selected).map(card).join('') || '<p class="wc-empty">No scheduled work for this day.</p>'}${options.onAdd?`<button type="button" class="btn" data-add="${selected}">+ Add work</button>`:''}</section>`:`<section class="wc-queue" aria-label="${mode==='tbs'?'To be scheduled':'Pending'}">${queueRecords.map(card).join('') || '<p class="wc-empty">No matching items.</p>'}</section>`}</div>`;
      host.querySelector('.wc-filters button[data-mode="calendar"]')?.replaceChildren(document.createTextNode('Scheduled'));
      const toolbar=host.querySelector('.wc-toolbar');
      const dropdown=document.createElement('details'); dropdown.className='wc-filter-menu';
      dropdown.innerHTML='<summary class="btn">Filters</summary><div class="wc-filter-popover"><strong>View</strong></div>';
      const popup=dropdown.querySelector('.wc-filter-popover');
      popup.append(host.querySelector('.wc-periods'));
      const heading=document.createElement('strong');heading.textContent='Show';popup.append(heading);
      const filters=host.querySelector('.wc-filters'),search=filters.querySelector('.wc-search');
      popup.append(filters);
      toolbar.insertBefore(dropdown,toolbar.querySelector('.wc-date'));
      const pills=document.createElement('div');pills.className='wc-selected-filters';pills.setAttribute('aria-label','Selected filters');
      pills.innerHTML=`<span class="wc-filter-pill">${{three:'3 Days',week:'Week',month:'Month'}[period]}</span>${mode!=='calendar'&&mode!=='legacy'?`<button class="wc-filter-pill" type="button" data-mode="calendar" aria-label="Clear ${escape(mode)} filter">${{tbs:'To be scheduled',pending:'Pending',hold:'On hold'}[mode]} ×</button>`:''}`;
      toolbar.insertBefore(pills,toolbar.querySelector('.wc-date'));
      popup.append(host.querySelector('.wc-date'));
      toolbar.insertBefore(search,toolbar.lastElementChild);
      if(period!=='month') toolbar.querySelector('h2').textContent=`${label(days[0])} – ${label(days.at(-1))}`;
      if (mode==='legacy' && options.renderLegacy && !loading && !error) host.querySelector('.wc-content').innerHTML=options.renderLegacy({selected,records:records.filter(matching)});
      if (mode==='calendar' && !loading && !error && period==='month') host.querySelector('.wc-content').innerHTML=`<div class="wc-month">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d=>`<strong class="wc-month-label">${d}</strong>`).join('')}${days.map(monthCell).join('')}</div>`;
      if (mode==='calendar' && period!=='month' && !loading && !error && host.dataset.layout==='focus') {
        const detail=document.createElement('section'); detail.className='wc-focus-detail';
        detail.innerHTML=`<h2>${escape(label(selected))} — work and monitors</h2>${rows(selected).map(card).join('')}`;
        host.querySelector('.wc-content').append(detail);
      }
      if (mode==='calendar' && !loading && !error) {
        host.querySelector('.wc-content').insertAdjacentHTML('beforeend',queues());
        const content=host.querySelector('.wc-content'), selectedDay=host.querySelector('.wc-day.is-selected');
        if (selectedDay && content.scrollWidth>content.clientWidth) {
          content.scrollLeft=selectedDay.getBoundingClientRect().left-content.getBoundingClientRect().left;
        }
      }
      host.querySelectorAll('.wc-day, .wc-month-day').forEach(cell=>{const heading=cell.querySelector('[data-day], [data-open-day]');cell.dataset.dropDate=heading.dataset.day || heading.dataset.openDay;});
      if (focus) host.querySelector(focus)?.focus();
    }
    function select(next) {
      date(next);
      selected=next;
      anchor=next;
      render();
      options.onRangeChange?.({start:range()[0],end:range().at(-1),selected});
    }
    function click(event) {
      const button=event.target.closest('button');
      if (!button || !host.contains(button) || button.disabled) return;
      if (button.hasAttribute('data-step')) {
        const step=Number(button.dataset.step);
        if(period==='month'){const next=date(anchor.slice(0,7)+'-01');next.setMonth(next.getMonth()+step);select(iso(next));}
        else select(shift(anchor,step*(period==='three'?3:7)));
        host.querySelector(`[data-step="${step}"]`)?.focus();
      }
      else if (button.dataset.period) { period=button.dataset.period;mode='calendar';select(selected);host.querySelector('.wc-filter-menu summary')?.focus(); }
      else if (button.dataset.openDay) { period='three';mode='calendar';select(button.dataset.openDay); }
      else if (button.hasAttribute('data-today')) { select(today()); host.querySelector('[data-today]')?.focus(); }
      else if (button.dataset.day) { selected=button.dataset.day; render(`[data-day="${selected}"]`); }
      else if (button.dataset.mode) { mode=button.dataset.mode; render('.wc-filter-menu summary'); }
      else if (button.dataset.edit) options.onEdit?.(button.dataset.edit);
      else if (button.dataset.add) options.onAdd?.(button.dataset.add);
      else if (button.hasAttribute('data-retry')) options.onRetry?.();
    }
    function change(event) {
      if(event.target.hasAttribute('data-date')) {
        try { const next=parseDate(event.target.value);event.target.setCustomValidity('');select(next);host.querySelector('[data-date]')?.focus(); }
        catch { event.target.setCustomValidity('Enter a valid date as MM/DD/YY.');event.target.reportValidity(); }
      }
    }
    function input(event) { if (event.target.hasAttribute('data-search')) { query=event.target.value; render('[data-search]'); } }
    function endDrag() {
      draggedId=null;
      host.querySelectorAll('.is-drop-target, .is-dragging').forEach(el=>el.classList.remove('is-drop-target','is-dragging'));
    }
    function drag(event) {
      if(event.type==='dragend'){endDrag();return;}
      if(event.type==='dragstart'){
        const card=event.target.closest('[draggable="true"]');
        if(!card || !host.contains(card) || !options.onSchedule || loading || error)return;
        draggedId=card.dataset.edit;
        event.dataTransfer.effectAllowed='move';
        event.dataTransfer.setData('text/plain',draggedId);
        card.classList.add('is-dragging');return;
      }
      if(!draggedId || !options.onSchedule || loading || error)return;
      const target=event.target.closest('[data-drop-date]');
      if(event.type==='dragleave'){
        if(target && !target.contains(event.relatedTarget))target.classList.remove('is-drop-target');
        return;
      }
      if(!target || !host.contains(target))return;
      event.preventDefault();
      if(event.type==='dragover'){
        event.dataTransfer.dropEffect='move';
        host.querySelectorAll('.is-drop-target').forEach(el=>{if(el!==target)el.classList.remove('is-drop-target');});
        target.classList.add('is-drop-target');
      }else if(event.type==='drop'){
        const id=draggedId,day=target.dataset.dropDate;
        endDrag();
        if(records.some(row=>row.id===id))options.onSchedule(id,day);
      }
    }
    const dragEvents=['dragstart','dragover','dragleave','drop','dragend'];
    const pointerDrag=global.bindCalendarDrag?.(host,(id,day,placement)=>{if(!disposed && !loading && !error)options.onSchedule?.(id,day,placement);});
    dragEvents.forEach(type=>host.addEventListener(type,drag));
    function dismiss(event) {
      const menu=host.querySelector('.wc-filter-menu');
      if(event.type==='keydown' && event.key==='Escape' && menu?.open){menu.open=false;menu.querySelector('summary').focus();}
      else if(event.type==='pointerdown' && menu?.open && !menu.contains(event.target)) menu.open=false;
    }
    document.addEventListener('pointerdown',dismiss);host.addEventListener('keydown',dismiss);
    host.addEventListener('click',click); host.addEventListener('change',change); host.addEventListener('input',input);
    render();
    return {
      update(next={}) {
        pointerDrag?.clear();
        if (next.records) {
          const ids=new Set();
          for (const row of next.records) {
            if (!row.id || ids.has(row.id)) throw new Error('Schedule records require unique IDs');
            ids.add(row.id);
            if (!['scheduled','tbs','pending','hold'].includes(row.queue)) throw new Error('Unknown schedule queue');
            if (row.queue==='scheduled') date(row.date);
          }
          records=structuredClone(next.records);
        }
        if ('loading' in next) loading=Boolean(next.loading);
        if ('error' in next) error=String(next.error||'');
        render();
      },
      destroy() { disposed=true; pointerDrag?.destroy();endDrag();dragEvents.forEach(type=>host.removeEventListener(type,drag));document.removeEventListener('pointerdown',dismiss);host.removeEventListener('keydown',dismiss);host.removeEventListener('click',click); host.removeEventListener('change',change); host.removeEventListener('input',input); host.replaceChildren(); host.classList.remove('weekly-schedule'); }
    };
  }
  global.OneLossWeeklyCalendar={mount,week,shift,displayDate,parseDate};
})(globalThis);
