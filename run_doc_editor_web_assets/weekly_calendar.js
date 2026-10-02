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
  const label = value => date(value).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'});

  function mount(host, options={}) {
    let selected=options.date || iso(new Date()), records=[], mode='calendar', query='', loading=false, error='';
    let disposed=false;
    const today=()=>options.today?.() || iso(new Date());
    date(selected);
    function matching(row) {
      return (!row.completed || options.includeCompleted) &&
        [row.title,...(row.activities||[]).flatMap(a=>[a.label,...(a.people||[])])].join(' ').toLowerCase().includes(query.toLowerCase());
    }
    function rows(day) { return records.filter(r=>r.queue==='scheduled' && r.date===day && matching(r)); }
    function card(row) {
      return `<button type="button" class="wc-visit" data-edit="${escape(row.id)}" ${options.onEdit ? '' : 'disabled'}>
        <span class="wc-time">${escape(row.time || 'Time not set')}${row.canceled ? ' · Canceled — needs rescheduling' : row.completed ? ' · Complete' : ''}</span>
        <strong>${escape(row.title)}</strong>
        ${(row.activities||[]).map(a=>`<span>${escape(a.label)}${a.people?.length ? `<small>${escape(a.people.join(', '))}</small>` : ''}</span>`).join('')}
        ${row.since ? `<small>Since ${escape(row.since)}</small>` : ''}
      </button>`;
    }
    function dayColumn(day) {
      const items=rows(day);
      return `<section class="wc-day ${day===selected?'is-selected':''}" aria-label="${escape(label(day))}">
        <button type="button" class="wc-day-heading" data-day="${day}" aria-pressed="${day===selected}" ${day===today()?'aria-current="date"':''}>${escape(label(day))}<small>${items.length} visit${items.length===1?'':'s'}</small></button>
        <div class="wc-day-items">${items.map(card).join('') || '<p class="wc-empty">No scheduled work</p>'}</div>
        ${options.onAdd ? `<button type="button" class="btn wc-add" data-add="${day}">+ Add work<span class="wc-sr"> on ${escape(label(day))}</span></button>` : ''}
      </section>`;
    }
    function render(focus) {
      if (disposed) return;
      const days=week(selected);
      const queueRecords=records.filter(r=>r.queue===mode && matching(r));
      host.classList.add('weekly-schedule');
      host.innerHTML=`<header class="wc-toolbar">
        <div class="wc-navigation"><button type="button" class="btn" data-step="-7" aria-label="Previous week">←</button><button type="button" class="btn" data-today>Today</button><button type="button" class="btn" data-step="7" aria-label="Next week">→</button><h2>${escape(label(days[0]))} – ${escape(label(days[6]))}, ${date(days[6]).getFullYear()}</h2></div>
        <label class="wc-date">Selected day<input type="date" value="${selected}" data-date></label>
        <button type="button" class="btn" data-mode="${mode==='legacy'?'calendar':'legacy'}">${mode==='legacy'?'Back to calendar':'Legacy view'}</button>
      </header>
      <nav class="wc-filters" aria-label="Schedule views">${[['calendar','Week'],['tbs','To be scheduled'],['pending','Pending']].map(([key,text])=>`<button type="button" class="btn" data-mode="${key}" aria-pressed="${mode===key}">${text}${key==='calendar'?'':` (${records.filter(r=>r.queue===key && matching(r)).length})`}</button>`).join('')}<label class="wc-search"><span class="wc-sr">Search scheduled work</span><input type="search" placeholder="Find job, activity or crew" data-search value="${escape(query)}"></label></nav>
      <div class="wc-content" aria-busy="${loading}">${loading?'<p role="status">Loading schedule…</p>':error?`<p role="alert">${escape(error)}</p>${options.onRetry?'<button type="button" class="btn" data-retry>Retry</button>':''}`:mode==='calendar'?`<div class="wc-week">${days.map(dayColumn).join('')}</div>`:mode==='legacy'?`<section class="wc-legacy"><header><h2>${escape(label(selected))} — Daily Run</h2><p>Same visits as the calendar</p></header>${rows(selected).map(card).join('') || '<p class="wc-empty">No scheduled work for this day.</p>'}${options.onAdd?`<button type="button" class="btn" data-add="${selected}">+ Add work</button>`:''}</section>`:`<section class="wc-queue" aria-label="${mode==='tbs'?'To be scheduled':'Pending'}">${queueRecords.map(card).join('') || '<p class="wc-empty">No matching items.</p>'}</section>`}</div>`;
      if (mode==='calendar') {
        const content=host.querySelector('.wc-content'), selectedDay=host.querySelector('.wc-day.is-selected');
        if (selectedDay && content.scrollWidth>content.clientWidth) {
          content.scrollLeft=selectedDay.getBoundingClientRect().left-content.getBoundingClientRect().left;
        }
      }
      if (focus) host.querySelector(focus)?.focus();
    }
    function select(next) {
      date(next);
      selected=next;
      render();
      options.onRangeChange?.({start:week(selected)[0],end:week(selected)[6],selected});
    }
    function click(event) {
      const button=event.target.closest('button');
      if (!button || !host.contains(button) || button.disabled) return;
      if (button.hasAttribute('data-step')) { select(shift(selected,Number(button.dataset.step))); host.querySelector(`[data-step="${button.dataset.step}"]`)?.focus(); }
      else if (button.hasAttribute('data-today')) { select(today()); host.querySelector('[data-today]')?.focus(); }
      else if (button.dataset.day) { selected=button.dataset.day; render(`[data-day="${selected}"]`); }
      else if (button.dataset.mode) { mode=button.dataset.mode; render('[data-mode]'); }
      else if (button.dataset.edit) options.onEdit?.(button.dataset.edit);
      else if (button.dataset.add) options.onAdd?.(button.dataset.add);
      else if (button.hasAttribute('data-retry')) options.onRetry?.();
    }
    function change(event) { if (event.target.hasAttribute('data-date') && event.target.value) { select(event.target.value); host.querySelector('[data-date]')?.focus(); } }
    function input(event) { if (event.target.hasAttribute('data-search')) { query=event.target.value; render('[data-search]'); } }
    host.addEventListener('click',click); host.addEventListener('change',change); host.addEventListener('input',input);
    render();
    return {
      update(next={}) {
        if (next.records) {
          const ids=new Set();
          for (const row of next.records) {
            if (!row.id || ids.has(row.id)) throw new Error('Schedule records require unique IDs');
            ids.add(row.id);
            if (!['scheduled','tbs','pending'].includes(row.queue)) throw new Error('Unknown schedule queue');
            if (row.queue==='scheduled') date(row.date);
          }
          records=structuredClone(next.records);
        }
        if ('loading' in next) loading=Boolean(next.loading);
        if ('error' in next) error=String(next.error||'');
        render();
      },
      destroy() { disposed=true; host.removeEventListener('click',click); host.removeEventListener('change',change); host.removeEventListener('input',input); host.replaceChildren(); host.classList.remove('weekly-schedule'); }
    };
  }
  global.OneLossWeeklyCalendar={mount,week,shift};
})(globalThis);
