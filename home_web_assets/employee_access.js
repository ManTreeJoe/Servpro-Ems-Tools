/* Block tool loading until server admission is confirmed. */
window.OneLossEmployeeAccess = (() => {
  const titles = {pending: 'Your account is waiting for approval', rejected: 'Access was not approved',
    suspended: 'Your access is paused', unassigned: 'Your franchise assignment is pending',
    microsoft_required: 'Sign in with your Microsoft work account', signed_out: 'Welcome to OneLoss',
    unavailable: 'We could not verify your access'};
  async function ensure() {
    const overlay = document.createElement('section');
    overlay.setAttribute('aria-label', 'OneLoss employee sign-in');
    Object.assign(overlay.style, {position:'fixed', inset:'0', zIndex:'2147483647', background:'var(--bg, #171b1a)',
      color:'var(--text, #f5f5f5)', display:'grid', placeItems:'center', padding:'24px'});
    const card = document.createElement('div');
    Object.assign(card.style, {maxWidth:'440px', width:'100%', lineHeight:'1.6'});
    overlay.append(card); document.body.append(overlay);
    return new Promise(resolve => {
      let busy = false, signingIn = false, watcher = null;
      function stopWatching() { if (watcher !== null) clearInterval(watcher); watcher = null; }
      function watchSignIn() {
        stopWatching();
        const deadline = Date.now() + 210000;
        watcher = setInterval(() => {
          if (!overlay.isConnected) { stopWatching(); return; }
          if (Date.now() > deadline) { stopWatching(); signingIn = false; }
          void check();
        }, 1000);
      }
      async function check() {
        if (busy) return;
        busy = true;
        try {
          const access = await pywebview.api.settings_employee_access_status();
          if (access.access_state === 'approved') { stopWatching(); overlay.remove(); resolve(access); return; }
          if (signingIn && access.access_state === 'signed_out') return;
          if (access.access_state !== 'signed_out' && access.access_state !== 'unavailable') { signingIn = false; stopWatching(); }
          card.replaceChildren();
          const brand = document.createElement('p'); brand.textContent = 'ONELOSS · TEAM WORKSPACE';
          const title = document.createElement('h1'); title.textContent = titles[access.access_state] || titles.unavailable;
          const detail = document.createElement('p');
          detail.textContent = access.error || (access.access_state === 'signed_out' || access.access_state === 'microsoft_required'
            ? 'Continue with your work account. Your administrator assigns your franchise and role.'
            : `${access.email || 'Your Microsoft account'} is signed in. An administrator must approve access before you can open jobs or tools.`);
          const message = document.createElement('p'); message.setAttribute('role', 'status');
          card.append(brand, title, detail, message);
          function button(label, action) {
            const b = document.createElement('button'); b.textContent = label; b.className = 'btn';
            b.style.margin = '8px 8px 0 0';
            b.onclick = async () => { b.disabled = true; try { await action(); } catch { message.textContent = 'Could not finish. Please try again.'; } finally { b.disabled = false; } };
            card.append(b);
          }
          if (['signed_out','microsoft_required'].includes(access.access_state)) {
            button('Sign in with Microsoft', async () => {
              signingIn = true; watchSignIn();
              message.textContent = 'Complete sign-in in your browser…';
              const r = await pywebview.api.settings_supabase_sign_in_microsoft();
              signingIn = false;
              if (!overlay.isConnected) return;
              if (!r.ok) { stopWatching(); message.textContent = r.error || 'Sign-in did not finish.'; }
              else await check();
            });
          } else button('Check approval', check);
          if (access.access_state !== 'signed_out') button('Use a different account', async () => {
            await pywebview.api.settings_employee_sign_out(); await check();
          });
        } catch { card.textContent = 'Access check unavailable. Restart OneLoss after checking your connection.'; }
        finally { busy = false; }
      }
      void check();
    });
  }
  return {ensure};
})();
