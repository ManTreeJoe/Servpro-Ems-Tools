/* DEV All Jobs grid over existing board records. No job-write API. */
window.JobsPlanPrototype = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const columns = {job:'Job / Claim', board:'Board', lane:'Lane', division:'Workstream', carrier:'Carrier', loss:'Loss type', due:'Due', checklist:'Checklist', address:'Address'};
  const defaults = ['job','board','lane','division','carrier','loss','due','checklist'];
  const configs = new Map(), collapsed = new Set();
  let activeKey = '';
  function division(row) {
    const name = String(row.c.division || row.b.key || '').toLowerCase();
    return name.includes('contents') ? 'Contents' : name.includes('recon') ? 'Recon' : ['wip','est','estimating','ems','logs','old'].includes(name) ? 'EMS' : 'Unverified';
  }
  const value = (row, field) => ({job:row.c.client||row.c.name||'(no name)', division:division(row), carrier:row.c.job_info?.carrier||'Not recorded', board:row.b.name, lane:row.l.name, due:row.c.due||'9999'})[field] || '';
  function config(key, saved) {
    if (!configs.has(key)) configs.set(key, {
      group: ['division','carrier','board','lane'].includes(saved?.group) ? saved.group : '',
      sort: ['job','carrier','due'].includes(saved?.sort) ? saved.sort : 'job',
      direction: saved?.direction === 'desc' ? 'desc' : 'asc',
      density: ['compact','comfortable'].includes(saved?.density) ? saved.density : 'compact',
      columns: Array.isArray(saved?.columns) && !saved.columns.some(k => !Object.hasOwn(columns,k)) ? [...new Set(['job', ...saved.columns.filter(k => Object.hasOwn(columns,k))])] : [...defaults],
    });
    return configs.get(key);
  }
  function snapshot() { return structuredClone(config(activeKey)); }
  function reset() { configs.clear(); collapsed.clear(); }
  function render(host, source, options) {
    activeKey = options.key;
    const cfg = config(activeKey, options.saved);
    host.dataset.density = cfg.density;
    const rows = [...source].sort((a,b) => value(a,cfg.sort).localeCompare(value(b,cfg.sort), undefined, {numeric:true}) * (cfg.direction === 'desc' ? -1 : 1));
    const select = (key, choices, label) => `<label>${label} <select data-config="${key}">${choices.map(([v,n])=>`<option value="${v}" ${cfg[key]===v?'selected':''}>${n}</option>`).join('')}</select></label>`;
    host.innerHTML = `<div class="jobs-list-controls">${select('group',[['','None'],['division','Workstream'],['board','Board'],['lane','Lane'],['carrier','Carrier']],'Group')}${select('sort',[['job','Job name'],['carrier','Carrier'],['due','Due date']],'Sort')}${select('direction',[['asc','Ascending'],['desc','Descending']],'Order')}${select('density',[['compact','Compact'],['comfortable','Comfortable']],'Rows')}<details class="jobs-columns"><summary class="btn">Columns</summary><div>${[...cfg.columns,...Object.keys(columns).filter(k=>!cfg.columns.includes(k))].map(k=>`<div class="jobs-column-option"><label><input type="checkbox" data-column="${k}" ${cfg.columns.includes(k)?'checked':''} ${k==='job'?'disabled':''}>${columns[k]}</label>${k!=='job'&&cfg.columns.includes(k)?`<button type="button" data-reorder="${k}" data-step="-1" aria-label="Move ${columns[k]} left" ${cfg.columns.indexOf(k)===1?'disabled':''}>↑</button><button type="button" data-reorder="${k}" data-step="1" aria-label="Move ${columns[k]} right" ${cfg.columns.indexOf(k)===cfg.columns.length-1?'disabled':''}>↓</button>`:''}</div>`).join('')}<button type="button" class="btn" data-reset-columns>Reset defaults</button></div></details><small>Existing board records · click a job to open</small></div><div class="all-jobs-list" role="region" aria-label="All jobs list" tabindex="0"><table><caption class="all-jobs-caption">${esc(options.name||'All Jobs')}</caption><thead><tr>${cfg.columns.map(k=>`<th scope="col">${columns[k]}</th>`).join('')}</tr></thead><tbody></tbody></table></div>`;
    const tbody = host.querySelector('tbody');
    const groups = new Map();
    rows.forEach((row,i)=>{const group=cfg.group?value(row,cfg.group):'';if(!groups.has(group))groups.set(group,[]);groups.get(group).push({row,i});});
    for(const [group, entries] of groups) {
      const groupKey=JSON.stringify([activeKey,cfg.group,group]);
      if(cfg.group) tbody.insertAdjacentHTML('beforeend',`<tr class="jobs-group"><td colspan="${cfg.columns.length}"><button type="button" data-group="${esc(groupKey)}" aria-expanded="${!collapsed.has(groupKey)}">${collapsed.has(groupKey)?'▸':'▾'} ${esc(group)} <small>${entries.length} records</small></button></td></tr>`);
      if(cfg.group && collapsed.has(groupKey))continue;
      for(const {row,i} of entries) {
        const {c,b,l}=row;
        const cell = k => {
          if(k==='division')return `<span class="jobs-stream-chip">${esc(division(row))}</span>`;
          if(k==='job')return `<button class="all-jobs-open" type="button">${esc(value(row,'job'))}</button><small>${c.job_info?.claim_number?'Claim '+esc(c.job_info.claim_number):'No claim recorded'}</small>`;
          if(k==='checklist')return c.checklist?.total ? `<div class="jobs-check-progress"><progress max="${Number(c.checklist.total)||1}" value="${Number(c.checklist.done)||0}" aria-label="Checklist completion"></progress><span>${esc(c.checklist.done||0)} / ${esc(c.checklist.total)}</span></div><small>Checklist only · not job progress</small>` : 'Not available';
          if(k==='loss')return esc((c.loss_types||[]).join(', ')||'—');
          if(k==='address')return esc(c.job_info?.address||'—');
          if(k==='due')return esc(c.due||'—');
          return esc(value(row,k));
        };
        tbody.insertAdjacentHTML('beforeend',`<tr data-result="${i}">${cfg.columns.map(k=>`<td data-field="${k}">${cell(k)}</td>`).join('')}</tr>`);
      }
    }
    if(!rows.length)tbody.innerHTML=`<tr><td colspan="${cfg.columns.length}" class="all-jobs-empty">No jobs match these filters. Try a different search or edit your saved filters.</td></tr>`;
    host.querySelectorAll('[data-config]').forEach(el=>el.onchange=()=>{cfg[el.dataset.config]=el.value;render(host,source,options);host.querySelector(`[data-config="${el.dataset.config}"]`).focus();});
    host.querySelectorAll('[data-column]').forEach(el=>el.onchange=()=>{const k=el.dataset.column;cfg.columns=el.checked?[...cfg.columns,k]:cfg.columns.filter(c=>c!==k);render(host,source,options);host.querySelector('.jobs-columns').open=true;host.querySelector(`[data-column="${k}"]`).focus();});
    host.querySelectorAll('[data-reorder]').forEach(el=>el.onclick=()=>{const i=cfg.columns.indexOf(el.dataset.reorder),j=i+Number(el.dataset.step);if(i<1||j<1||j>=cfg.columns.length)return;[cfg.columns[i],cfg.columns[j]]=[cfg.columns[j],cfg.columns[i]];render(host,source,options);host.querySelector('.jobs-columns').open=true;host.querySelector(`[data-reorder="${el.dataset.reorder}"][data-step="${el.dataset.step}"]`)?.focus();});
    host.querySelector('[data-reset-columns]').onclick=()=>{cfg.columns=[...defaults];cfg.density='compact';render(host,source,options);host.querySelector('.jobs-columns summary').focus();};
    host.querySelectorAll('[data-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.group;collapsed.has(key)?collapsed.delete(key):collapsed.add(key);render(host,source,options);[...host.querySelectorAll('[data-group]')].find(e=>e.dataset.group===key)?.focus();});
    host.querySelectorAll('[data-result]').forEach(el=>el.onclick=e=>{if(window.getSelection()?.toString()&&!e.target.closest('button'))return;const row=rows[Number(el.dataset.result)];options.open(row.c,row.b);});
  }
  return {render,snapshot,reset};
})();
