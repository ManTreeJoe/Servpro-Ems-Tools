/* Open settings cards, packed into independent rows without stretching controls. */
(() => {
  const root = document.querySelector('.wrap');
  if (!root) return;
  let frame;
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(layout);
  }
  function layout() {
    root.querySelectorAll('details').forEach(details => {
      const section = document.createElement('section');
      for (const attr of details.attributes) {
        if (attr.name !== 'open') section.setAttribute(attr.name, attr.value);
      }
      const summary = details.querySelector(':scope > summary');
      if (summary) {
        const heading = document.createElement('h2');
        heading.className = 'settings-static-heading';
        heading.append(...summary.childNodes);
        summary.replaceWith(heading);
      }
      section.append(...details.childNodes);
      details.replaceWith(section);
    });
    const cards = [...root.children].flatMap(el => el.id === 'form-fields' ? [...el.children] : [el]);
    for (const card of cards) {
      card.style.removeProperty('grid-row-end');
    }
  }
  new MutationObserver(schedule).observe(root, {childList:true, subtree:true, attributes:true, attributeFilter:['class','style']});
  window.addEventListener('resize', schedule);
  root.classList.remove('settings-packed');
  schedule();
})();
