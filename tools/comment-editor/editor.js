import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import TurndownService from 'turndown';
import {mentions} from './mentions';

const markdown = new TurndownService({headingStyle:'atx', bulletListMarker:'-', codeBlockStyle:'fenced', emDelimiter:'*'});
markdown.addRule('strike', {filter:['s','del','strike'], replacement:content => `~~${content}~~`});
const escapeText=markdown.escape.bind(markdown);
// Trello needs the literal username; don't turn @sam_example into @sam\_example.
markdown.escape=text=>escapeText(text).replace(/(^|[\s(\[])@([A-Za-z0-9_.\\-]+)/g,(whole,prefix,user)=>prefix+'@'+user.replace(/\\_/g,'_'));
const safeLink = value => /^(https?:\/\/|mailto:)/i.test(value);
const icons = {
  bullet:'<circle cx="4" cy="5" r="1"/><circle cx="4" cy="10" r="1"/><circle cx="4" cy="15" r="1"/><path d="M8 5h10M8 10h10M8 15h10"/>',
  number:'<path d="M3 3h1v5M2 8h4M2 12c3-2 5 0 2 2l-2 3h4M9 5h9M9 10h9M9 15h9"/>',
  quote:'<path d="M3 5h5v6H4c0 3 2 4 3 4M12 5h5v6h-4c0 3 2 4 3 4"/>',
  link:'<path d="m8 12 4-4M7 14l-1 1a3 3 0 0 1-4-4l4-4a3 3 0 0 1 4 0M10 6l1-1a3 3 0 0 1 4 4l-4 4a3 3 0 0 1-4 0"/>',
};
function mount(source) {
  if (!source || source._richEditor) return source?._richEditor;
  const box = document.createElement('section'); box.className='comment-editor';
  const toolbar = document.createElement('div'); toolbar.className='comment-editor-toolbar';
  toolbar.setAttribute('role','group'); toolbar.setAttribute('aria-label','Comment formatting');
  const surface = document.createElement('div');
  box.append(toolbar, surface); source.before(box);
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value');
  let updating = false;
  const buttons = [];
  function paint(editor) {
    box.classList.toggle('is-empty',editor.isEmpty);
    for (const [button,active] of buttons) button.setAttribute('aria-pressed',String(editor.isActive(active)));
  }
  const editor = new Editor({
    element:surface, injectCSS:false,
    extensions:[StarterKit.configure({underline:false, link:{openOnClick:false, autolink:false, isAllowedUri:safeLink}})],
    content:window.CommentMarkdown.render(source.value),
    editorProps:{attributes:{class:'comment-editor-content',role:'textbox','aria-label':'Job comment','aria-multiline':'true','data-placeholder':'Write an update for this job…'},
      // Paste plain text deliberately: no email fonts, hidden markup, or remote images.
      handlePaste(view,event) {
        const text=event.clipboardData?.getData('text/plain');
        if (text == null) return false;
        event.preventDefault();
        editor.commands.insertContent(text.split(/\r?\n/).map(line=>({type:'paragraph',content:line?[{type:'text',text:line}]:[]})));
        return true;
      },
      handleDOMEvents:{drop:(_view,event)=>{event.preventDefault();return true;}}
    },
    onUpdate:({editor})=>{
      updating=true;
      nativeValue.set.call(source,editor.isEmpty?'':markdown.turndown(editor.getHTML()));
      source.dispatchEvent(new Event('input',{bubbles:true}));
      updating=false; paint(editor);
    },
    onSelectionUpdate:({editor})=>paint(editor),
    onTransaction:({editor})=>paint(editor),
  });
  // Keep existing posting/draft code using its established textarea contract.
  Object.defineProperty(source,'value',{configurable:true,
    get(){return nativeValue.get.call(source);},
    set(value){nativeValue.set.call(source,value); if(!updating) {editor.commands.setContent(window.CommentMarkdown.render(String(value||'')),{emitUpdate:false});paint(editor);}}
  });
  source.hidden=true;
  source.addEventListener('input',syncSource);
  function syncSource(){if(!updating) {editor.commands.setContent(window.CommentMarkdown.render(source.value),{emitUpdate:false});paint(editor);}}
  const linkPanel=document.createElement('div'); linkPanel.className='comment-link-panel'; linkPanel.hidden=true;
  linkPanel.innerHTML='<label>Link address<input type="url" placeholder="https://…" aria-label="Link address"></label><div><button type="button" data-apply-link>Apply</button><button type="button" data-remove-link>Remove link</button><button type="button" data-cancel-link>Cancel</button></div><small role="alert"></small>';
  box.append(linkPanel);
  let linkSelection=null;
  function closeLink(){linkPanel.hidden=true;editor.commands.focus();}
  linkPanel.querySelector('[data-cancel-link]').onclick=closeLink;
  linkPanel.querySelector('[data-remove-link]').onclick=()=>{editor.chain().focus().setTextSelection(linkSelection).extendMarkRange('link').unsetLink().run();closeLink();};
  function applyLink(){
    const href=linkPanel.querySelector('input').value.trim();
    if(!safeLink(href)){linkPanel.querySelector('small').textContent='Use an https://, http://, or mailto: address.';return;}
    const chain=editor.chain().focus().setTextSelection(linkSelection);
    if(linkSelection.from===linkSelection.to && !editor.isActive('link')) chain.insertContent({type:'text',text:href,marks:[{type:'link',attrs:{href}}]}).run();
    else chain.extendMarkRange('link').setLink({href}).run();
    closeLink();
  }
  linkPanel.querySelector('[data-apply-link]').onclick=applyLink;
  linkPanel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();event.preventDefault();closeLink();}else if(event.key==='Enter'){event.preventDefault();applyLink();}});
  const definitions=[['bold','Bold (Ctrl+B)','B','bold','toggleBold'],['italic','Italic (Ctrl+I)','I','italic','toggleItalic'],['strike','Strikethrough','S','strike','toggleStrike'],['bullet','Bulleted list',null,'bulletList','toggleBulletList'],['number','Numbered list',null,'orderedList','toggleOrderedList'],['quote','Quote',null,'blockquote','toggleBlockquote'],['link','Insert or edit link',null,'link',null]];
  for(const [kind,label,text,active,command] of definitions){
    const button=document.createElement('button');button.type='button';button.dataset.commentFormat=kind;button.title=label;button.setAttribute('aria-label',label);
    if(text) button.textContent=text; else button.innerHTML=`<svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${icons[kind]}</svg>`;
    button.addEventListener('mousedown',event=>event.preventDefault());
    button.onclick=()=>{
      if(command) editor.chain().focus()[command]().run();
      else {linkSelection={from:editor.state.selection.from,to:editor.state.selection.to};linkPanel.hidden=false;linkPanel.querySelector('input').value=editor.getAttributes('link').href||'';linkPanel.querySelector('small').textContent='';linkPanel.querySelector('input').focus();}
      paint(editor);
    };
    toolbar.append(button);buttons.push([button,active]);
  }
  paint(editor);
  const mentionPicker=mentions(editor,source,box);
  source._richEditor={editor,destroy(){mentionPicker.destroy();source.removeEventListener('input',syncSource);delete source.value;delete source._richEditor;editor.destroy();box.remove();source.hidden=false;}};
  return source._richEditor;
}
window.CommentRichEditor={mount};
