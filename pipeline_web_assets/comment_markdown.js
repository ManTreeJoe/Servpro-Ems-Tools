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
  const render = text => md.render(String(text || ''));
  // Display-only decoration: never modify the Markdown used for editing/posting.
  function display(text) {
    const host=document.createElement('div');host.innerHTML=render(text);
    const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT),nodes=[];
    while(walker.nextNode())if(!walker.currentNode.parentElement.closest('a,code,pre'))nodes.push(walker.currentNode);
    for(const node of nodes){
      const pattern=/(^|[\s(\[,;:])(@[A-Za-z0-9_][A-Za-z0-9_.-]*)/g;
      const value=node.nodeValue,fragment=document.createDocumentFragment();let last=0,match;
      while((match=pattern.exec(value))){
        fragment.append(document.createTextNode(value.slice(last,match.index)+match[1]));
        const chip=document.createElement('span');chip.className='comment-mention';chip.textContent=match[2];fragment.append(chip);
        last=pattern.lastIndex;
      }
      if(last){fragment.append(document.createTextNode(value.slice(last)));node.replaceWith(fragment);}
    }
    return host.innerHTML;
  }
  function avatarColor(name){
    let hash=0;for(const char of String(name||'?').trim().toLowerCase())hash=(hash*31+char.charCodeAt(0))>>>0;
    return ['#316a91','#85428b','#257958','#75651e','#954b46','#60519a'][hash%6];
  }
  function initials(name){const parts=String(name||'?').trim().split(/\s+/);return (parts[0].charAt(0)+(parts.length>1?parts.at(-1).charAt(0):'')).toUpperCase();}
  return {render, display, avatarColor, initials, mount};
})();
