/* Move existing sections, never clone them: drafts and action bindings stay intact. */
window.JobWorkspaceTabs = (() => {
  const remembered = new Map();
  const definitions = [
    ['overview', 'Overview'], ['log', 'Job Log'],
    ['requirements', 'Requirements'], ['files', 'Files'], ['run', 'Run Activity'],
  ];
  function mount(root, identity) {
    const layout = root.querySelector('.job-card-layout');
    const main = root.querySelector('.job-card-main');
    const activity = root.querySelector('.job-card-activity');
    const nav = document.createElement('div');
    nav.className = 'job-workspace-tabs';
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'Job workspace');
    const panels = new Map();
    const buttons = new Map();
    const sections = Array.from(main.children);
    for (const [key, label] of definitions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.id = `job-tab-${key}`;
      button.textContent = label;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', `job-panel-${key}`);
      const panel = document.createElement('section');
      panel.id = `job-panel-${key}`;
      panel.className = 'job-workspace-panel';
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', button.id);
      panel.tabIndex = 0;
      panels.set(key, panel);
      buttons.set(key, button);
      nav.append(button);
      main.append(panel);
    }
    for (const section of sections) {
      // Link conflicts must remain visible on every tab.
      if (section.matches('.division-conflict-banner')) continue;
      const key = section.matches('.job-log-section') ? 'log'
        : section.matches('.progress-section,.checklist-section') ? 'requirements'
        : section.matches('.signatures-section,.job-attachments-section') ? 'files'
        : section.matches('.job-run-section') ? 'run' : 'overview';
      panels.get(key).append(section);
    }
    // History belongs to its tab; the original composer stays outside the
    // scrolling body so it is usable from every tab and retains its draft.
    const body = root.querySelector('.modal-body');
    const composer = activity?.querySelector('.comment-compose');
    if (composer) body.after(composer);
    if (activity) panels.get('log').append(activity);
    layout.classList.add('tabbed-job-layout');
    root.querySelector('.modal-body').before(nav);
    function select(key, focus = false) {
      if (!panels.has(key)) key = 'overview';
      for (const [name, panel] of panels) {
        panel.hidden = name !== key;
        const button = buttons.get(name);
        button.setAttribute('aria-selected', String(name === key));
        button.tabIndex = name === key ? 0 : -1;
      }
      remembered.set(identity, key);
      if (focus) buttons.get(key).focus();
    }
    for (const [key, button] of buttons) {
      button.addEventListener('click', () => select(key));
      button.addEventListener('keydown', event => {
        const keys = [...buttons.keys()];
        const index = keys.indexOf(key);
        const next = event.key === 'ArrowRight' ? (index + 1) % keys.length
          : event.key === 'ArrowLeft' ? (index + keys.length - 1) % keys.length
          : event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : -1;
        if (next < 0) return;
        event.preventDefault();
        select(keys[next], true);
      });
    }
    // Reveal the destination before existing handlers open/focus its editor.
    root.addEventListener('click', event => {
      if (event.target.closest('[data-add-job-log]')) select('log');
    }, true);
    select(remembered.get(identity));
    return { select };
  }
  return { mount };
})();
