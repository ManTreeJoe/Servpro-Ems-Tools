window.ExtraJobTasks = {mount(root, client, cardId) {
  if (!cardId || !window.pywebview?.api.extra_job_tasks || root.querySelector('.extra-job-tasks')) return;
  const anchor = root.querySelector('.checklist-section');
  if (!anchor) return;
  const section = document.createElement('section'); section.className = 'aud-section extra-job-tasks';
  section.innerHTML = '<h3>Extra job tasks · Subcontractors</h3><p>Shared across this job’s sections. These tasks do not verify paperwork or change templates.</p><div data-tasks></div><form><label>New task<input maxlength="500" required spellcheck="true" placeholder="e.g. Confirm electrician appointment"></label><button type="submit" class="btn">Add task</button></form><p role="status">Loading tasks…</p><button type="button" class="text-btn" data-reload>Reload checklist</button>';
  anchor.after(section);
  const list = section.querySelector('[data-tasks]'), form = section.querySelector('form'), input = form.querySelector('input'), status = section.querySelector('[role=status]');
  let token = '', tasks = [], busy = false;
  function lock(value) { busy = value; section.querySelectorAll('button,input').forEach(el => el.disabled = value); }
  function paint() {
    list.replaceChildren();
    for (const task of tasks) {
      const row = document.createElement('div'); row.className = 'extra-job-task-row';
      const label = document.createElement('label'), check = document.createElement('input'), title = document.createElement('span');
      check.type = 'checkbox'; check.checked = task.complete; title.textContent = task.text;
      label.append(check, title); row.append(label);
      check.onchange = () => save({action:'complete',id:task.id,complete:check.checked});
      for (const action of ['rename','remove']) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'text-btn'; button.textContent = action === 'rename' ? 'Edit' : 'Remove';
        button.setAttribute('aria-label', button.textContent + ' task: ' + task.text);
        button.onclick = () => {
          if (action === 'remove') { if (confirm('Remove this extra task?')) save({action,id:task.id}); return; }
          const edit = document.createElement('input'); edit.value = task.text; edit.maxLength = 500; edit.setAttribute('aria-label','Edit task'); edit.spellcheck = true;
          const commit = document.createElement('button'); commit.type = 'button'; commit.textContent = 'Save';
          const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
          row.replaceChildren(edit,commit,cancel); cancel.onclick = paint;
          commit.onclick = () => save({action:'rename',id:task.id,text:edit.value}); edit.focus();
        };
        row.append(button);
      }
      list.append(row);
    }
    if (!tasks.length) list.textContent = 'No extra tasks yet.';
  }
  async function request(command) {
    const result = await pywebview.api.extra_job_tasks(client,cardId,token,command);
    if (!result?.ok) throw Error(result?.error || 'Checklist could not be loaded.');
    tasks = result.tasks || []; token = result.token; paint();
  }
  async function save(command) {
    if (busy || !token) return;
    lock(true); status.textContent = 'Saving…';
    try { await request(command); if(command.action==='add') input.value=''; status.textContent='Saved to this job.'; }
    catch(error) { token=''; paint(); status.textContent=error.message+' Your new-task text is kept. Reload before retrying.'; }
    finally {lock(false);}
  }
  async function load() {
    if (busy) return; lock(true); status.textContent='Loading tasks…';
    try {await request(null);status.textContent='';} catch(error) {token='';status.textContent=error.message;}
    finally {lock(false);}
  }
  form.onsubmit = e => {e.preventDefault();save({action:'add',text:input.value});};
  section.querySelector('[data-reload]').onclick = load;
  void load();
}};
