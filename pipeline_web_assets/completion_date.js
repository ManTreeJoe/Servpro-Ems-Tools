window.CompletionDate = {mount(root, client, cardId, onSaved) {
  const badge = root.querySelector('.header-card-completed');
  const detail = root.querySelector('[data-completion-date-value]');
  const edit = root.querySelector('[data-edit-completion-date]');
  const api = window.pywebview?.api;
  if (!badge || !api?.card_completion_date || !cardId) return;
  const label = value => value ? new Date(value + 'T12:00:00').toLocaleDateString('en-US', {month:'short',day:'numeric',year:'numeric'}) : '';
  function paint(value) {
    badge.textContent = value ? 'Work completed · ' + label(value) : 'Add date';
    badge.title = 'Work completed date';
    if (detail) detail.textContent = value ? label(value) : 'Not recorded';
    if (edit) edit.textContent = value ? 'Edit date' : 'Add date';
    onSaved(value);
  }
  root.addEventListener('work-completion-saved', event => paint(event.detail.date));
  api.card_completion_date(client, cardId).then(result => {
    if (root.isConnected && result?.ok) paint(result.date);
    else if (root.isConnected) badge.textContent = 'Check completion date';
  }).catch(() => { if (root.isConnected) badge.textContent = 'Check completion date'; });
  async function open() {
    const dialog = document.createElement('dialog'); dialog.className = 'job-members-dialog completion-date-dialog';
    dialog.innerHTML = '<header><h2>Work completed</h2><button data-close aria-label="Close">×</button></header><p>Date field work finished. Changing this date does not move the card or change its due date.</p><label>Completion date<input type="date" disabled></label><p role="status">Loading current date…</p><button data-save disabled>Save date</button> <button data-clear disabled>Remove date</button>';
    document.body.append(dialog); dialog.showModal();
    const input = dialog.querySelector('input'), status = dialog.querySelector('[role=status]');
    const save = dialog.querySelector('[data-save]'), clear = dialog.querySelector('[data-clear]');
    let token, busy = false;
    const now = new Date(); input.max = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
    dialog.querySelector('[data-close]').onclick = () => { if (!busy) dialog.close(); };
    dialog.oncancel = e => { if (busy) e.preventDefault(); }; dialog.onclose = () => dialog.remove();
    try {
      const result = await api.card_completion_date(client, cardId);
      if (!dialog.isConnected) return;
      if (!result?.ok) throw Error(result?.error || 'Completion date unavailable.');
      token = result.token; input.value = result.date || ''; paint(result.date);
      input.disabled = save.disabled = false; clear.disabled = !result.date; status.textContent = '';
    } catch (error) { status.textContent = error.message; }
    async function submit(remove) {
      if (busy) return;
      if (!remove && (!input.value || !input.checkValidity())) { status.textContent = 'Choose the date work finished, no later than today.'; return; }
      busy = true; input.disabled = save.disabled = clear.disabled = true; status.textContent = 'Saving…';
      try {
        const result = await api.card_completion_date(client, cardId, {token, completed:remove ? '' : input.value});
        if (!result?.ok) throw Error(result?.error || 'Save not confirmed. Reopen before retrying.');
        paint(result.date); busy = false; dialog.close();
      } catch (error) { busy = false; status.textContent = error.message; }
    }
    save.onclick = () => submit(false); clear.onclick = () => submit(true);
  }
  badge.onclick = open; if (edit) edit.onclick = open;
}};
