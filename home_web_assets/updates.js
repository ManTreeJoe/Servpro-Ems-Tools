/* One desktop update flow, shared by the notice and Settings. */
(() => {
  let info = null, pending = null, installing = false, launched = false, message = '', dismissed = '';
  let dialog;
  const api = () => window.pywebview?.api;
  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  function button(text, action, primary = false) {
    const el = node('button', text, 'btn' + (primary ? ' btn-primary' : ''));
    el.type = 'button'; el.onclick = action;
    return el;
  }
  function renderNotice() {
    document.getElementById('update-bar')?.remove();
    if (!info?.ok || !info.update_available || dismissed === info.latest) return;
    const bar = node('div', '', 'update-notice'); bar.id = 'update-bar';
    bar.setAttribute('aria-label', 'App update');
    bar.append(node('span', `OneLoss ${info.latest} is available.`));
    bar.append(button('Review update', open));
    const hide = button('×', () => { dismissed = info.latest; bar.remove(); });
    hide.setAttribute('aria-label', 'Dismiss update notice');
    bar.append(hide);
    document.querySelector('.pane')?.prepend(bar);
  }
  function renderDialog() {
    if (!dialog?.open) return;
    const body = dialog.querySelector('.update-body'); body.replaceChildren();
    const status = node('p', message || (pending ? 'Checking for updates…' :
      !info?.ok ? 'Could not check for updates. Try again.' :
      info.update_available ? `Version ${info.latest} is ready. You have ${info.current}.` :
      `You’re up to date — version ${info.current}.`));
    status.setAttribute('role', 'status'); body.append(status);
    if (info?.ok && info.update_available && info.notes) {
      const details = node('details');
      details.append(node('summary', 'What’s new'), node('div', info.notes, 'update-notes'));
      body.append(details);
    }
    const actions = node('div', '', 'update-actions');
    const check = button(pending ? 'Checking…' : 'Check again', () => checkUpdate());
    check.disabled = !!pending || installing; actions.append(check);
    if (info?.ok && info.update_available) {
      const install = button(launched ? 'Installer opened' : installing ? 'Downloading…' : 'Update now', installUpdate, true);
      install.disabled = installing || !!pending; actions.append(install);
      if (info.url) actions.append(button('Release page', () => api().open_url(info.url)));
    }
    body.append(actions);
  }
  async function checkUpdate() {
    if (window.__LINGUAR_BROWSER_TOOLS__ || installing) return;
    if (pending) return pending;
    message = '';
    pending = Promise.resolve().then(() => api().check_update()).then(result => {
      info = result;
      if (!result?.ok) message = 'Could not check for updates. Check your connection and try again.';
    }).catch(() => { info = null; message = 'Could not check for updates. Check your connection and try again.'; })
      .finally(() => { pending = null; renderNotice(); renderDialog(); });
    renderDialog();
    return pending;
  }
  async function installUpdate() {
    if (installing || !info?.update_available) return;
    installing = true; message = 'Downloading the installer…'; renderDialog();
    try {
      const result = await api().install_update(info.installer || info.url || '');
      if (result?.ok && result.launched) {
        launched = true;
        message = 'Installer opened. Follow the setup prompts to finish updating.';
        // Prevent a second installer launch while setup is running.
      } else {
        installing = false;
        message = result?.opened_page ? 'Download page opened. Run the installer from there.' :
          `Update failed: ${result?.error || 'Please try again.'}`;
      }
    } catch (_) { installing = false; message = 'Download failed. Check your connection and try again.'; }
    renderDialog();
  }
  function open() {
    if (window.__LINGUAR_BROWSER_TOOLS__) return;
    if (!dialog) {
      dialog = node('dialog', '', 'update-dialog'); dialog.setAttribute('aria-labelledby', 'update-title');
      const header = node('div', '', 'update-heading');
      const title = node('h2', 'OneLoss updates'); title.id = 'update-title';
      const close = button('Close', () => dialog.close());
      header.append(title, close); dialog.append(header, node('div', '', 'update-body'));
      document.body.append(dialog);
    }
    if (!dialog.open) dialog.showModal();
    renderDialog();
    if (!info && !pending) checkUpdate();
  }
  window.OneLossUpdates = {check: checkUpdate, open};
})();
