window.CardTitle = {
  mount(root, client, cardId) {
    const title = root.querySelector('.audit-head-main .modal-title');
    if (!title || !cardId || !window.pywebview?.api.card_title_load) return;
    const edit = document.createElement('button');
    edit.type = 'button'; edit.className = 'text-btn card-title-edit'; edit.textContent = '✎';
    edit.title = 'Edit name';
    edit.setAttribute('aria-label', 'Edit this card name in OneLoss and Trello');
    title.after(edit);
    edit.onclick = async () => {
      edit.disabled = true;
      const dialog = document.createElement('dialog'); dialog.className = 'job-members-dialog';
      dialog.innerHTML = '<header><h2>Edit card name</h2><button type="button" data-close aria-label="Close">×</button></header><p>Updates this linked Trello card. Other division cards and the job folder are unchanged.</p><label class="member-search">Card name<input type="search" maxlength="512" spellcheck="true" disabled></label><p role="status">Loading current name…</p><button type="button" data-save disabled>Save name</button>';
      document.body.append(dialog); dialog.showModal();
      const input = dialog.querySelector('input'), status = dialog.querySelector('[role=status]'), save = dialog.querySelector('[data-save]');
      let busy = false, expected = '';
      dialog.querySelector('[data-close]').onclick = () => { if (!busy) dialog.close(); };
      dialog.oncancel = e => { if (busy) e.preventDefault(); };
      dialog.onclose = () => {dialog.remove(); edit.disabled = false; edit.focus();};
      try {
        const result = await pywebview.api.card_title_load(client, cardId);
        if (!dialog.isConnected) return;
        if (!result?.ok) throw Error(result?.error || 'Name could not load.');
        input.value = expected = result.name; input.disabled = false; save.disabled = false; status.textContent = ''; input.focus();
      } catch(e) { status.textContent = e.message; }
      save.onclick = async () => {
        if (!input.value.trim()) {status.textContent = 'Enter a card name.';return;}
        busy = true; save.disabled = input.disabled = true; status.textContent = 'Saving to Trello…';
        try {
          const result = await pywebview.api.card_title_save(client, cardId, input.value, expected);
          if (!result?.ok) throw Error(result?.error || 'Rename not confirmed.');
          title.textContent = result.name; root.dataset.renamedCardTitle = result.name;
          busy = false; dialog.close();
        } catch(e) {status.textContent = e.message;busy = false;input.disabled = false;save.disabled = false;}
      };
    };
    // Resolve the exact card's current name, without renaming the shared job.
    pywebview.api.card_title_load(client, cardId).then(result => {
      if (result?.ok && root.isConnected && !root.dataset.renamedCardTitle) title.textContent = result.name;
    }).catch(()=>{});
  }
};
