/* Display only: storage, edit source, and posting retain the original Markdown. */
window.CommentMarkdown = (() => {
  const md = window.markdownit({html: false, breaks: true, linkify: true, typographer: false});
  // Do not fetch tracking images or permit navigation to local files/custom schemes.
  md.disable('image');
  md.validateLink = url => /^(https?:\/\/|mailto:)/i.test(url);
  md.renderer.rules.link_open = (tokens, index, options, env, self) => {
    tokens[index].attrSet('rel', 'noopener noreferrer');
    tokens[index].attrSet('target', '_blank');
    return self.renderToken(tokens, index, options);
  };
  function mount(input) {
    if (window.CommentRichEditor) return window.CommentRichEditor.mount(input);
    if (!input || input.dataset.markdownTools) return;
    input.dataset.markdownTools = 'true';
    const bar = document.createElement('div');
    bar.className = 'comment-format-tools';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Comment formatting');
    const tools = [
      ['bold', 'B', 'Bold (Ctrl+B)'], ['italic', 'I', 'Italic (Ctrl+I)'],
      ['strike', 'S', 'Strikethrough'], ['bullet', '• List', 'Bulleted list'],
      ['number', '1. List', 'Numbered list'], ['quote', '❞', 'Quote'],
      ['link', 'Link', 'Insert link'],
    ];
    function apply(kind) {
      if (input.disabled || input.readOnly) return;
      let start = input.selectionStart, end = input.selectionEnd;
      let selected = input.value.slice(start, end), replacement, offset = 0, length;
      const mark = {bold:'**', italic:'*', strike:'~~'}[kind];
      if (mark) {
        const wrapped = input.value.slice(Math.max(0, start-mark.length), start) === mark && input.value.slice(end, end+mark.length) === mark;
        if (wrapped) { start -= mark.length; end += mark.length; replacement = selected; length = selected.length; }
        else { selected = selected || 'text'; replacement = mark + selected + mark; offset = mark.length; length = selected.length; }
      } else if (kind === 'link') {
        replacement = '[' + (selected || 'link text') + '](https://)';
        offset = replacement.indexOf('https://'); length = 8;
      } else {
        start = input.value.lastIndexOf('\n', start - 1) + 1;
        const lineEnd = input.value.indexOf('\n', Math.max(start, end - (input.value[end-1] === '\n' ? 1 : 0)));
        end = lineEnd < 0 ? input.value.length : lineEnd;
        selected = input.value.slice(start, end) || 'text';
        replacement = selected.split('\n').map((line, i) => (kind === 'quote' ? '> ' : kind === 'number' ? `${i+1}. ` : '- ') + line).join('\n');
        length = replacement.length;
      }
      const scroll = input.scrollTop;
      input.focus({preventScroll:true});
      input.setRangeText(replacement, start, end, 'end');
      input.setSelectionRange(start + offset, start + offset + length);
      input.scrollTop = scroll;
      input.dispatchEvent(new Event('input', {bubbles:true}));
    }
    for (const [kind, text, title] of tools) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = text;
      button.dataset.commentFormat = kind;
      button.title = title; button.setAttribute('aria-label', title);
      button.addEventListener('mousedown', event => event.preventDefault());
      button.addEventListener('click', () => apply(kind));
      bar.append(button);
    }
    input.before(bar);
    input.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && ['b','i'].includes(event.key.toLowerCase())) {
        event.preventDefault(); apply(event.key.toLowerCase() === 'b' ? 'bold' : 'italic');
      }
    });
  }
  return {render: text => md.render(String(text || '')), mount};
})();
