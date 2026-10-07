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
    const threadDrafts = new Map();
    const thread = document.createElement('dialog');
    thread.className = 'comment-thread-panel';
    thread.setAttribute('aria-label', 'Comment thread');
    thread.innerHTML = '<header class="comment-thread-head"><div><strong>Thread</strong><small data-thread-count></small></div><button class="text-btn" type="button" aria-label="Close thread">×</button></header><div class="comment-thread-original"></div><div class="comment-thread-messages"></div><form class="comment-thread-compose"><label>Reply to thread<textarea rows="3" data-thread-input placeholder="Write a reply…"></textarea></label><div><small role="status" data-thread-status></small><button type="submit" class="btn btn-primary">Send reply</button></div></form>';
    root.append(thread);
    const threadInput = thread.querySelector('[data-thread-input]');
    const threadStatus = thread.querySelector('[data-thread-status]');
    const threadSend = thread.querySelector('[type="submit"]');
    function draft() {
      if (!threadDrafts.has(threadRoot)) threadDrafts.set(threadRoot, {text:'', parent:threadRoot, actor:'original message', status:'', sending:false});
      return threadDrafts.get(threadRoot);
    }
    function positionThread() {
      if (!thread.open) return;
      const area = root.querySelector('.job-card-activity').getBoundingClientRect();
      const width = window.innerWidth <= 700 ? window.innerWidth - 24 : 460;
      const height = Math.min(820, window.innerHeight - 24);
      thread.style.width = width + 'px';
      thread.style.left = Math.max(12, Math.min(area.right - width, window.innerWidth - width - 12)) + 'px';
      thread.style.top = Math.max(12, Math.min(area.top, window.innerHeight - height - 12)) + 'px';
      thread.style.height = height + 'px';
    }
    function closeThread() {
      if (!thread.open) return;
      thread.close(); threadRoot = '';
      window.removeEventListener('resize', positionThread);
      if (opener?.isConnected) opener.focus({preventScroll:true});
      else search?.focus({preventScroll:true});
    }
    thread.querySelector('.comment-thread-head button').onclick = closeThread;
    thread.addEventListener('cancel', event => { event.preventDefault(); event.stopPropagation(); closeThread(); });
    thread.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeThread(); }
    });
    let backdropDown = false;
    thread.addEventListener('pointerdown', event => { backdropDown = event.target === thread; });
    thread.addEventListener('click', event => {
      if (event.target === thread && backdropDown) closeThread();
      backdropDown = false;
    });
    threadInput.addEventListener('input', () => { draft().text = threadInput.value; });
    function paintComposer() {
      const saved = draft();
      if (threadInput.value !== saved.text) threadInput.value = saved.text;
      threadStatus.textContent = saved.status || `Replying to ${saved.actor}`;
      threadSend.disabled = saved.sending;
    }
    thread.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      const saved = draft(), activeRoot = threadRoot, text = saved.text.trim();
      if (!text || saved.sending) return;
      if (saved.body !== text) { saved.body = text; saved.operation = crypto.randomUUID(); }
      saved.sending = true; saved.status = 'Saving reply…'; paintComposer(); generation++;
      try {
        const result = await api.reply_job_comment(cardId, saved.parent, text, saved.operation);
        if (!result?.ok) throw new Error(result?.error || 'Reply was not confirmed. Retry with this draft.');
        records = records.filter(row => row.id !== result.comment.id); records.push(result.comment);
        if (result.parent && !records.some(row => row.id === result.parent.id)) records.push(result.parent);
        if (saved.text.trim() === text) { saved.text = ''; saved.body = ''; saved.operation = null; }
        saved.status = result.warning || 'Reply saved'; apply();
      } catch (error) { saved.status = error.message; }
      finally { saved.sending = false; if (threadRoot === activeRoot) paintComposer(); }
    });

    function filter() { search?.dispatchEvent(new Event('input')); }
    function banner() {
      replyBanner.replaceChildren();
      const reply = root._commentReply;
      replyBanner.hidden = !reply;
      compose.querySelectorAll('[data-comment-destination],[data-comment-placement]').forEach(el => {
        if (reply) { if (!('threadDisabled' in el.dataset)) el.dataset.threadDisabled = String(el.disabled); el.disabled = true; }
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
      const list = thread.querySelector('.comment-thread-messages'), original = thread.querySelector('.comment-thread-original');
      const scroll = list.scrollTop;
      list.replaceChildren(); original.replaceChildren();
      const rows = records.filter(row => row.root_id === threadRoot).sort((a,b) => (Date.parse(b.created_at)||0)-(Date.parse(a.created_at)||0));
      const replies = rows.filter(row => row.id !== threadRoot);
      thread.querySelector('[data-thread-count]').textContent = `${replies.length} ${replies.length === 1 ? 'reply' : 'replies'} · Newest first`;
      if (!replies.length) {
        const empty = document.createElement('p'); empty.textContent = 'No replies yet. Start the conversation below.'; list.append(empty);
      }
      for (const row of rows) {
        const article = document.createElement('article');
        article.dataset.threadMessage = row.id;
        const label = document.createElement('strong'); label.textContent = row.actor;
        const body = document.createElement('p'); body.textContent = row.body;
        const context = document.createElement('small');
        context.textContent = row.id === threadRoot ? (row.native ? 'Original message' : 'Saved original · may have changed in Trello') : new Date(row.created_at).toLocaleString();
        const reply = document.createElement('button'); reply.type = 'button'; reply.className = 'text-btn'; reply.textContent = 'Reply';
        reply.onclick = () => {
          const saved = draft(); if (saved.sending) return;
          if (saved.parent !== row.id) { saved.parent = row.id; saved.operation = null; saved.body = ''; }
          saved.actor = row.actor; saved.status = ''; paintComposer(); threadInput.focus();
        };
        article.append(label, context, body, reply);
        (row.id === threadRoot ? original : list).append(article);
        if (row.id === draft().parent) draft().actor = row.actor;
      }
      if (!original.children.length) original.textContent = 'Original message is not available in the saved thread.';
      list.scrollTop = scroll; paintComposer();
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
        opener = button; threadRoot = article.dataset.threadRoot; paintThread();
        thread.showModal(); positionThread(); window.addEventListener('resize', positionThread);
        thread.querySelector('button')?.focus({preventScroll:true});
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
    const timer = setInterval(() => { if (!root.isConnected) { clearInterval(timer); window.removeEventListener('resize', positionThread); } else refresh(); }, 30000);
  }
  return {mount};
})();
