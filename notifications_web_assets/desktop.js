(() => {
  window.addEventListener('pywebviewready', async () => {
    const mode = document.getElementById('desktop-alert-mode');
    const test = document.getElementById('desktop-alert-test');
    const status = document.getElementById('desktop-alert-status');
    let saved = 'off';
    try {
      const result = await pywebview.api.desktop_settings();
      if (!result?.ok) throw Error(result?.error || 'Desktop settings could not load.');
      saved = mode.value = result.mode;
      mode.disabled = test.disabled = !result.available;
      status.textContent = result.error || (result.available ? '' : 'Available in the main Windows app.');
    } catch (error) { status.textContent = error.message; }
    mode.onchange = async () => {
      mode.disabled = true;
      try {
        const result = await pywebview.api.desktop_settings(mode.value);
        if (!result?.ok) throw Error(result?.error || 'Settings were not saved.');
        saved = mode.value = result.mode;
        status.textContent = saved === 'off' ? 'Desktop alerts off.' : 'Saved. Only new activity will alert you.';
      } catch (error) { mode.value = saved; status.textContent = error.message; }
      finally { mode.disabled = false; }
    };
    test.onclick = async () => {
      test.disabled = true;
      try {
        const result = await pywebview.api.desktop_test();
        if (!result?.ok) throw Error(result?.error || 'The test could not be sent.');
        status.textContent = 'Sent to Windows. Check Notification Center if no banner appears.';
      } catch (error) { status.textContent = error.message; }
      finally { test.disabled = false; }
    };
  }, {once:true});
})();
