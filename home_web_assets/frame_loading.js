/* Covers navigation before a tool's own API/loading code has booted. */
(() => {
  const watching=new Map();
  function check() {
    for(const [frame,record] of watching) if(!frame.isConnected){record.finish?.();frame.removeEventListener('load',record.onLoad);watching.delete(frame);}
    for(const frame of document.querySelectorAll('iframe')) {
      let record=watching.get(frame);
      if(!record){record={src:'',finish:null};record.onLoad=()=>{record.finish?.();record.finish=null;};frame.addEventListener('load',record.onLoad);watching.set(frame,record);}
      const src=frame.getAttribute('src') || '';
      if(src===record.src)continue;
      record.finish?.();record.finish=null;record.src=src;
      if(!src || src==='about:blank')continue;
      const promise=new Promise(resolve=>{record.finish=resolve;});
      window.LoadingFeedback?.track('tool_navigation',promise,{force:true,label:'Opening tool…'});
    }
  }
  const start=()=>{new MutationObserver(check).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['src']});check();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
