/* Reload only the visible tool, not every warm panel in the shell. */
(()=>{
 'use strict';
 if(window.OneLossReload)return;
 function reload(){
  const frames=[...document.querySelectorAll('iframe')].filter(frame=>
   frame.getClientRects().length && getComputedStyle(frame).visibility!=='hidden');
  const frame=frames.at(-1);
  if(frame){
   try{if(frame.contentWindow.OneLossReload){frame.contentWindow.OneLossReload();return;}}catch{}
   if(!window.confirm('Reload this page? Unsaved entries may be lost.'))return;
   frame.src=frame.src;return;
  }
  const unfinished=[...document.querySelectorAll('textarea,input,select,[contenteditable="true"]')].some(el=>{
   if(el.disabled||!el.getClientRects().length)return false;
   if(el.isContentEditable)return !!el.textContent.trim();
   if(el.tagName==='SELECT')return [...el.options].some(o=>o.selected!==o.defaultSelected);
   if(['checkbox','radio'].includes(el.type))return el.checked!==el.defaultChecked;
   if(['button','submit','hidden','search'].includes(el.type))return false;
   return el.value!==el.defaultValue;
  });
  if(unfinished&&!window.confirm('Reload this page? Unsaved entries may be lost.'))return;
  window.location.reload();
 }
 window.OneLossReload=reload;
 window.addEventListener('keydown',event=>{
  if(event.defaultPrevented||event.repeat||event.altKey||!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=='r')return;
  event.preventDefault();event.stopPropagation();reload();
 },true);
})();
