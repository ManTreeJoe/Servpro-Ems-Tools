// Only action menus: searchable pickers and expandable content stay open.
(() => {
  const selector = 'details.toolbar-more, .tool-quick-menu';
  const timers = new WeakMap();
  let keyboard = false;
  const cancel = menu => { clearTimeout(timers.get(menu)); timers.delete(menu); };
  const close = menu => {
    cancel(menu);
    if (menu.matches('details')) menu.open = false;
    else {
      menu.classList.remove('is-open');
      menu.querySelector('.tool-menu-trigger')?.setAttribute('aria-expanded', 'false');
    }
  };
  document.addEventListener('keydown', event => {
    keyboard = true;
    document.querySelectorAll(selector).forEach(cancel);
    if (event.key === 'Escape') {
      document.querySelectorAll('details.toolbar-more[open]').forEach(menu => {
        close(menu);
        menu.querySelector('summary')?.focus();
      });
    }
  }, true);
  document.addEventListener('pointerdown', event => {
    keyboard = event.pointerType !== 'mouse';
    document.querySelectorAll(selector).forEach(menu => {
      if (!menu.contains(event.target)) close(menu);
    });
  }, true);
  document.addEventListener('pointerover', event => {
    const menu = event.target.closest?.(selector);
    if (menu) cancel(menu);
  });
  document.addEventListener('pointerout', event => {
    if (event.pointerType !== 'mouse' || keyboard) return;
    const menu = event.target.closest?.(selector);
    if (!menu || (event.relatedTarget && menu.contains(event.relatedTarget))) return;
    cancel(menu);
    timers.set(menu, setTimeout(() => {
      if (!keyboard && menu.isConnected && !menu.matches(':hover')) close(menu);
    }, 250));
  });
})();
