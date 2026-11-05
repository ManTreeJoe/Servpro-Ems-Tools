window.CardCompletion = {mount(root, client, cardId) {
  const menu = root.querySelector('.more-quick-menu .tool-menu-panel');
  if (!menu || !cardId || !window.pywebview?.api.card_completion || menu.querySelector('[data-complete-card]')) return;
  const trigger = document.createElement('button'); trigger.type = 'button'; trigger.dataset.completeCard = ''; trigger.textContent = 'Work completed / Move to Estimating…'; menu.append(trigger);
  trigger.onclick = async () => {
    const dialog = document.createElement('dialog'); dialog.className = 'card-completion-dialog';
    dialog.innerHTML = '<form><h3>Complete field work</h3><p>This records field-work completion, not estimate completion. Other linked cards stay where they are. This does not mark paperwork or extra tasks complete.</p><label>Work completion date<input type="date" required></label><label>Destination on Estimating<select required><option value="">Choose a section…</option></select></label><p role="status">Loading current card…</p><div><button type="button" data-close class="btn">Close</button> <button type="submit" class="btn" disabled>Save date &amp; move this card</button></div></form>';
    document.body.append(dialog); dialog.showModal();
    dialog.onclose = () => dialog.remove(); dialog.querySelector('[data-close]').onclick = () => dialog.close();
    const status = dialog.querySelector('[role=status]'), input = dialog.querySelector('input'), select = dialog.querySelector('select'), submit = dialog.querySelector('[type=submit]');
    const today = new Date(); input.max = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    let context;
    try {
      context = await pywebview.api.card_completion(client, cardId);
      if (!context?.ok) throw Error(context?.error || 'Completion could not load.');
      input.value = context.date || input.max;
      context.destinations.forEach((d,i) => select.append(new Option(d.name, String(i))));
      status.textContent = context.destinations.length ? 'Choose where this card belongs in Estimating.' : 'No accessible Estimating sections. Nothing has changed.';
      submit.disabled = !context.destinations.length;
    } catch(e) { status.textContent = e.message; }
    dialog.querySelector('form').onsubmit = async e => {
      e.preventDefault(); const destination = context?.destinations[select.value]; if (!destination || submit.disabled) return;
      submit.disabled = true; status.textContent = 'Saving completion date and moving this card…';
      try {
        const result = await pywebview.api.card_completion(client, cardId, {token:context.token,version:context.version,completed:input.value,board_id:destination.board_id,list_id:destination.list_id});
        if (!result?.ok) throw Error(result?.error || 'Save was not confirmed. Reopen before retrying.');
        root.dispatchEvent(new CustomEvent('work-completion-saved', {detail:{date:result.date}}));
        status.textContent = `Completed ${result.date} · moved to ${destination.name}.` + (result.pending_sync ? ' Trello sync is pending.' : '');
        const board = root.querySelector('[data-move-job-location="app_board"] strong'), lane = root.querySelector('[data-move-job-location="app_lane"] strong');
        if (board) board.textContent = destination.name.split(' / ')[0];
        if (lane) lane.textContent = destination.name.split(' / ').slice(1).join(' / ');
      } catch(e) { status.textContent = e.message; }
    };
  };
}};
