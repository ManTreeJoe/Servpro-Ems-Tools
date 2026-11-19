/* Standalone controller: only the explicit setup bridge is used. */
(() => {
  let busy = false, opened = false, workspaceChanged = false, api, info, previousFocus;
  const attempted = new Set();
  const $ = id => document.getElementById(id);
  function element(tag, text, parent) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    parent?.append(el); return el;
  }
  function input(label, name, value = '', type = 'text') {
    const wrap = element('label', label, $('fr-step'));
    const el = element('input', '', wrap);
    el.name = name; el.type = type; el.value = value; el.required = true;
    el.autocomplete = type === 'password' ? 'current-password' : name === 'email' ? 'username' : 'off';
    return el;
  }
  function lock(value) {
    busy = value;
    $('fr-step-form').querySelectorAll('button,input,select').forEach(el => { el.disabled = value; });
    $('fr-step-form').setAttribute('aria-busy', String(value));
  }
  async function close() {
    if (busy) return;
    $('fr-overlay').classList.add('hidden'); opened = false;
    previousFocus?.focus();
    await api.dismiss_first_run().catch(() => {});
    window.dispatchEvent(new CustomEvent("employee-setup-closed", {detail:{reload:workspaceChanged}}));
    workspaceChanged = false;
  }
  async function refresh() {
    try { info = await api.first_run(); }
    catch { info = {show:true, steps:[], error:'Setup checks could not load. Check your connection and try again.'}; }
    render();
  }
  async function run(fn) {
    if (busy) return;
    const step = (info.steps || []).find(s => !s.done && !s.skipped);
    if (step) {
      attempted.add(step.key);
      const detail = $('fr-step').querySelector('.setup-detail');
      if (detail) detail.hidden = false;
    }
    lock(true); $('fr-error').textContent = '';
    try {
      const result = await fn();
      if (result?.ok === false) throw new Error(result.error || 'This step could not finish. Try again.');
      if (result?.reload) workspaceChanged = true;
      await refresh();
    } catch (error) {
      $('fr-error').textContent = error.message || 'Setup could not continue. Check your connection and retry.';
    } finally { lock(false); }
  }
  function render() {
    const box = $('fr-step'); box.replaceChildren();
    $('fr-error').textContent = info.error || '';
    const pending = (info.steps || []).filter(s => !s.done && !s.skipped);
    const step = pending[0];
    const progress = $('fr-progress'); progress.replaceChildren();
    const complete = !step && !info.error;
    $('fr-later').hidden = complete;
    $('fr-recheck').hidden = complete;
    if (info.error) element('span', 'Setup needs another check', progress);
    else if (step) {
      const index = info.steps.indexOf(step);
      element('span', `Step ${index + 1} of 7`, progress);
      const dots = element('div', '', progress); dots.className = 'setup-dots';
      dots.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 7; i++) {
        const dot = element('span', '', dots);
        dot.className = i === index ? 'current' : info.steps[i]?.done || info.steps[i]?.skipped ? 'finished' : '';
      }
    }
    const next = $('fr-next');
    next.hidden = !!info.error;
    if (!step) {
      if (!info.error) {
        element('h2', 'Your workspace is ready', box);
        element('p', 'Required checks passed. No test jobs, projects or photos were created.', box);
        next.textContent = 'Start working';
      }
      return;
    }
    element('h2', step.title, box);
    element('p', step.help, box).className = 'setup-instruction';
    const detail = element('p', step.detail, box); detail.className = 'setup-detail';
    detail.hidden = !attempted.has(step.key);
    next.textContent = 'Save and continue';
    if (step.key === 'signin') { input('Work email', 'email', '', 'email'); input('Password', 'password', '', 'password'); }
    else if (step.key === 'profile_name') input('Display name', 'name');
    else if (step.key === 'franchise') {
      const wrap = element('label', 'Server-assigned franchise', box);
      const select = element('select', '', wrap); select.name = 'key'; select.required = true;
      const placeholder = element('option', 'Choose your franchise', select); placeholder.value = '';
      for (const key of info.departments || []) { const opt = element('option', key, select); opt.value = key; }
      next.hidden = !(info.departments || []).length;
    } else if (step.key === 'folders') {
      for (const [label, name] of [['Shared job root','job_root'], ['Daily Run folder','runs_dir']]) {
        const field = input(label, name, info.folders?.[name] || '');
        const button = element('button', `Choose ${label.toLowerCase()}`, box); button.type = 'button'; button.className = 'fr-btn fr-secondary';
        button.onclick = async () => {
          if (busy) return; lock(true);
          try {
            const result = await api.settings_pick_dir(field.value);
            if (!result.ok) throw new Error(result.error || 'Folder picker unavailable');
            if (result.path) field.value = result.path;
          } catch (e) { $('fr-error').textContent = e.message; }
          finally { lock(false); }
        };
      }
    } else if (step.key === 'trello' || step.key === 'companycam') {
      next.textContent = step.key === 'trello' ? 'Connect Trello' : 'Connect CompanyCam';
      if (step.optional) {
        const skip = element('button', 'Skip optional connection', box); skip.type = 'button'; skip.className = 'fr-btn fr-secondary';
        skip.onclick = () => run(() => api.settings_employee_setup_action('skip_companycam', {}));
      }
    } else next.textContent = 'Verify shared data';
    box.querySelector('input,select')?.focus();
  }
  async function open(bridge) {
    if (opened) return;
    api = bridge;
    try { info = await api.first_run(); }
    catch { info = {show:true, steps:[], error:'Setup checks could not load. Check your connection and retry.'}; }
    if (!info.show || info.session_dismissed) return;
    previousFocus = document.activeElement; opened = true;
    $('fr-overlay').classList.remove('hidden'); render();
    $('fr-overlay').querySelector('[role="dialog"]').focus();
    $('fr-later').onclick = close;
    $('fr-recheck').onclick = () => run(async () => ({ok:true}));
    $('fr-step-form').onsubmit = e => {
      e.preventDefault(); if (busy) return;
      const step = (info.steps || []).find(s => !s.done && !s.skipped);
      if (!step) { if (!info.error) close(); return; }
      const values = Object.fromEntries(new FormData(e.currentTarget));
      const password = e.currentTarget.querySelector('[name="password"]');
      if (password) password.value = '';
      run(() => step.key === 'live_data' ? Promise.resolve({ok:true}) :
        api.settings_employee_setup_action(step.key === 'profile_name' ? 'name' : step.key, values));
    };
    $('fr-overlay').onkeydown = e => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      if (e.key !== 'Tab') return;
      const focusable = [...$('fr-overlay').querySelectorAll('button,input,select')].filter(el => !el.disabled && el.getClientRects().length);
      if (!focusable.length) { e.preventDefault(); return; }
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement))) { e.preventDefault(); first.focus(); }
    };
  }
  window.OneLossSetup = {open};
})();
