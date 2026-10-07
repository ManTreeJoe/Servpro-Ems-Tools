/* Private SQLite drafts; no provider writes and no automatic submission. */
window.JobDrafts = (() => {
  const pending = new Map();
  function mount(host, key, read, restore) {
    if (!host || !key[0] || !window.pywebview?.api?.job_draft) return null;
    const notice = document.createElement('div'); notice.className = 'job-draft-notice';
    notice.setAttribute('role', 'status'); host.append(notice);
    let version = 0, scope = '', ready = false, retained = null, changed = false, disposed = false;
    let timer, queue = Promise.resolve();
    const api = change => {
      const id = JSON.stringify(key);
      const task = (pending.get(id) || Promise.resolve()).catch(() => {}).then(async () => {
        const result = await window.pywebview.api.job_draft(...key, typeof change === 'function' ? change() : change);
        if (result?.ok) { version = result.version; scope = result.scope; }
        return result;
      });
      pending.set(id, task);
      task.finally(() => { if (pending.get(id) === task) pending.delete(id); }).catch(() => {});
      return task;
    };
    const fail = error => { notice.textContent = `Draft not saved on this PC: ${error?.message || error}`; };
    function write(payload) {
      queue = api(() => ({scope,version,payload})).then(result => {
        if (!result?.ok) throw Error(result?.error || 'Local draft save failed');
        version = result.version;
        if (!disposed) notice.textContent = payload ? 'Draft saved on this PC · not submitted' : '';
      }).catch(error => { ready = false; fail(error); });
      return queue;
    }
    function save() {
      if (ready && !retained && !disposed) write(read());
    }
    function change() {
      changed = true; clearTimeout(timer);
      if (retained) return; // Never overwrite a recovered draft before the user's choice.
      timer = setTimeout(save, 300);
    }
    host.addEventListener('input', change); host.addEventListener('change', change);
    const loaded = api(null).then(result => {
      if (!result?.ok) throw Error(result?.error || 'Local draft unavailable');
      version = result.version; scope = result.scope; ready = true;
      if (disposed) return;
      retained = result.payload;
      if (retained) {
        notice.textContent = 'An unsent draft is saved on this PC. ';
        for (const [label, use] of [['Restore draft',true],['Discard saved draft',false]]) {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'text-btn'; button.textContent = label;
          button.onclick = () => {
            if (use && changed && !confirm('Replace the text you just entered with the saved draft?')) return;
            if (use) restore(retained);
            retained = null; notice.textContent = ''; if (use || changed) save(); else write(null);
          };
          notice.append(button);
        }
      } else if (changed) save();
    }).catch(fail);
    return {
      capture: change,
      async flush() { clearTimeout(timer); await loaded; if (changed && ready && !retained) await write(read()); },
      async clear() { clearTimeout(timer); changed = false; retained = null; await loaded; if (ready) await write(null); },
      dispose() { clearTimeout(timer); if (changed && ready && !retained) save(); disposed = true; host.removeEventListener('input',change); host.removeEventListener('change',change); },
      notice
    };
  }
  return {mount};
})();
