/* Shared pins and replies are separate from the provider feed/cache. */
window.CommentThreads = (() => {
  function mount(root, conversation, cardId) {
    if (!cardId || root._commentThreads || !window.pywebview?.api?.comment_thread_state) return;
    root._commentThreads = true;
    const api = window.pywebview.api;
    const stream = root.querySelector('[data-comment-stream]');
    const compose = root.querySelector('.comment-compose');
    const input = root.querySelector('[data-comment-input]');
    const search = root.querySelector('[data-comment-search]');
    const state = root.querySelector('[data-comment-state]');
    let records = [], loading = false, generation = 0, threadRoot = '', opener = null;
    const toolbar = document.createElement('div');
    toolbar.className = 'comment-thread-filter';
    toolbar.innerHTML = '<button class="text-btn" type="button" aria-pressed="true" data-comment-all>All</button><button class="text-btn" type="button" aria-pressed="false" data-comment-pinned-filter>Pinned</button><small role="status"></small>';
    root.querySelector('.comment-search').after(toolbar);
    const notice = toolbar.querySelector('small');
    const replyBanner = document.createElement('div');
    replyBanner.className = 'comment-reply-banner'; replyBanner.hidden = true;
    compose.prepend(replyBanner);
    const thread = document.createElement('section');
    thread.className = 'comment-thread-panel'; thread.hidden = true;
    thread.setAttribute('aria-label', 'Comment thread');
    stream.before(thread);

    function filter() { search?.dispatchEvent(new Event('input')); }
    function banner() {
      replyBanner.replaceChildren();
      const reply = root._commentReply;
      replyBanner.hidden = !reply;
      compose.querySelectorAll('[data-comment-destination],[data-comment-placement]').forEach(el => {
        if (reply) { el.dataset.threadDisabled = String(el.disabled); el.disabled = true; }
        else if ('threadDisabled' in el.dataset) { el.disabled = el.dataset.threadDisabled === 'true'; delete el.dataset.threadDisabled; }
      });
      if (!reply) return;
      const label = document.createElement('span');
      label.textContent = `Replying to ${reply.actor}: ${reply.preview.slice(0, 100)}`;
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.className = 'text-btn'; cancel.textContent = 'Cancel reply';
      cancel.onclick = () => { root._commentReply = null; banner(); input.dispatchEvent(new Event('input', {bubbles:true})); };
      replyBanner.append(label, cancel);
    }
    function selectReply(id, actor, preview) {
      root._commentReply = {id, actor, preview, cardId};
      banner(); input.dispatchEvent(new Event('input', {bubbles:true}));
      (compose.querySelector('[contenteditable="true"]') || input).focus();
    }
    function paintThread() {
      if (!threadRoot) return;
      thread.replaceChildren(); thread.hidden = false;
      const head = document.createElement('header');
      const title = document.createElement('strong'); title.textContent = 'Thread';
      const close = document.createElement('button'); close.className = 'text-btn'; close.type = 'button';
      close.textContent = 'Close thread';
      close.onclick = () => { threadRoot = ''; thread.hidden = true; opener?.focus(); };
      head.append(title, close); thread.append(head);
      const list = document.createElement('div'); list.className = 'comment-thread-messages';
      const rows = records.filter(row => row.root_id === threadRoot).sort((a,b) => Date.parse(a.created_at)-Date.parse(b.created_at));
      if (!rows.length) {
        const empty = document.createElement('p'); empty.textContent = 'No linked replies yet. Use Reply on a comment to start a thread.'; list.append(empty);
      }
      for (const row of rows) {
        const article = document.createElement('article');
        const label = document.createElement('strong'); label.textContent = row.actor;
        const body = document.createElement('p'); body.textContent = row.body;
        const context = document.createElement('small');
        context.textContent = row.native ? (row.parent_id ? 'Reply' : 'Comment') : 'Saved original · may have changed in Trello';
        const reply = document.createElement('button'); reply.type = 'button'; reply.className = 'text-btn'; reply.textContent = 'Reply';
        reply.onclick = () => selectReply(row.id, row.actor, row.body);
        article.append(label, context, body, reply); list.append(article);
      }
      thread.append(list);
    }
    function apply() { conversation.setThreadRecords(records); filter(); paintThread(); }
    async function refresh() {
      if (loading || !root.isConnected || document.hidden) return;
      loading = true; const version = generation;
      try {
        let after = '', rows = [];
        do {
          const result = await api.comment_thread_state(cardId, after);
          if (!result?.ok) throw new Error(result?.error || 'Shared comments unavailable');
          rows.push(...result.comments); after = result.next || '';
        } while (after && root.isConnected && version === generation);
        if (root.isConnected && version === generation) { records = rows; notice.textContent = ''; apply(); }
      } catch (_) { notice.textContent = 'Pins and threads unavailable · retry shortly'; }
      finally { loading = false; }
    }
    toolbar.addEventListener('click', event => {
      if (!event.target.closest('button')) return;
      root._pinnedCommentsOnly = !!event.target.closest('[data-comment-pinned-filter]');
      toolbar.querySelector('[data-comment-all]').setAttribute('aria-pressed', String(!root._pinnedCommentsOnly));
      toolbar.querySelector('[data-comment-pinned-filter]').setAttribute('aria-pressed', String(root._pinnedCommentsOnly)); filter();
    });
    stream.addEventListener('click', async event => {
      const button = event.target.closest('[data-reply-comment],[data-pin-comment],[data-open-thread]');
      if (!button) return;
      const article = button.closest('[data-comment-id]');
      const id = article.dataset.threadKey;
      if (button.hasAttribute('data-reply-comment')) {
        selectReply(id, article.querySelector('header strong')?.textContent || 'comment', article.querySelector('[data-comment-raw]')?.dataset.commentRaw || '');
      } else if (button.hasAttribute('data-open-thread')) {
        opener = button; threadRoot = article.dataset.threadRoot; paintThread(); thread.querySelector('button')?.focus();
      } else {
        button.disabled = true; generation++;
        try {
          const expected = article.dataset.commentPinned === 'true';
          const result = await api.pin_job_comment(cardId, id, !expected, expected);
          if (!result?.ok) throw new Error(result?.error || 'Pin was not saved');
          records = records.filter(row => row.id !== result.comment.id); records.push(result.comment); apply();
          notice.textContent = result.comment.pinned ? 'Pinned for this card' : 'Pin removed';
        } catch (error) { notice.textContent = error.message; }
        finally { button.disabled = false; }
      }
    });
    // Capture before the ordinary-comment handler: replies must never silently
    // become unlinked posts or fan out to multiple cards.
    compose.addEventListener('click', async event => {
      const button = event.target.closest('[data-post-comment]');
      const reply = root._commentReply;
      if (!button || !reply) return;
      event.preventDefault(); event.stopImmediatePropagation(); event.stopPropagation();
      const text = input.value.trim(); if (!text || button.disabled) return;
      if (reply.cardId !== cardId) { state.textContent = 'This reply belongs to another card.'; return; }
      if (reply.body !== text) { reply.body = text; reply.operation = crypto.randomUUID(); }
      input.dispatchEvent(new Event('input', {bubbles:true}));
      button.disabled = true; state.textContent = 'Saving reply…'; generation++;
      try {
        const result = await api.reply_job_comment(cardId, reply.id, text, reply.operation);
        if (!result?.ok) throw new Error(result?.error || 'Reply was not confirmed. Retry with this draft.');
        records = records.filter(row => row.id !== result.comment.id); records.push(result.comment);
        if (result.parent && !records.some(row => row.id === result.parent.id)) records.push(result.parent);
        apply();
        if (input.value.trim() === text && root._commentReply === reply) {
          input.value = ''; root._commentReply = null; banner();
          input.dispatchEvent(new Event('input', {bubbles:true}));
        }
        state.textContent = result.warning || 'Reply saved';
      } catch (error) { state.textContent = error.message; }
      finally { button.disabled = false; }
    }, true);
    root.addEventListener('comments-painted', filter);
    root.addEventListener('comment-reply-restored', banner);
    banner(); refresh();
    const timer = setInterval(() => { if (!root.isConnected) clearInterval(timer); else refresh(); }, 30000);
  }
  return {mount};
})();
