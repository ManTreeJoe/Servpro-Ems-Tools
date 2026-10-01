/* DEV-only launcher. The sandbox receives a copy of already-loaded cards, never an API. */
window.installJobViewsTrial = function (getPayload) {
  if (document.getElementById('job-views-trial')) return;
  const button = document.createElement('button');
  button.id = 'job-views-trial'; button.className = 'btn';
  button.textContent = 'Try Jobs Views · DEV';
  document.querySelector('.topbar-actions').prepend(button);
  button.onclick = () => {
    const payload = getPayload();
    if (!payload?.boards?.length) { button.textContent = 'Load boards first, then try again'; return; }
    const dialog = document.createElement('dialog');
    dialog.style.cssText = 'width:98vw;max-width:none;height:96vh;max-height:96vh;padding:0;border:0;overflow:hidden';
    const frame = document.createElement('iframe');
    // Without allow-same-origin the trial cannot reach the parent's write-capable bridge.
    frame.setAttribute('sandbox', 'allow-scripts');
    frame.title = 'Jobs Views DEV trial — no changes saved';
    frame.style.cssText = 'width:100%;height:100%;border:0';
    frame.src = '../dev_prototypes/job_views.html';
    const listener = event => {
      if (event.source !== frame.contentWindow) return;
      if (event.data?.type === 'job-views-ready') frame.contentWindow.postMessage({type:'job-views-seed',payload}, '*');
      if (event.data?.type === 'job-views-close') dialog.close();
    };
    window.addEventListener('message', listener);
    dialog.append(frame); document.body.append(dialog);
    dialog.addEventListener('close', () => { window.removeEventListener('message', listener); dialog.remove(); button.focus(); }, {once:true});
    dialog.showModal();
  };
};
