const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const code=fs.readFileSync('apa_web_assets/app.js','utf8');
const save=code.slice(code.indexOf('async function saveDoc()'),code.indexOf('// ── Search / toggle'));
const drop=code.slice(code.indexOf('function attachApaSectionDrop('),code.indexOf('// ── Franchise picker popover'));
(async()=>{
 for(const mode of ['ok','rejected','exception']){
  const messages=[],handlers={};
  const initial={date_iso:'2026-09-18',sections:[{name:'Final Uploads',count:1,items:[{text:'Test job',highlighted:true}]},{name:'Amaya',count:0,items:[]}]};
  const context={state:{doc:structuredClone(initial)},saveTimer:null,_apaDragRef:{section:'Final Uploads',index:0},renderBoard(){},setStatus:(...v)=>messages.push(v),pywebview:{api:{save_doc:async(date,sections)=>{
   if(mode==='exception')throw Error('Share unavailable');
   if(mode==='rejected')return {ok:false,error:'Unknown lane'};
   return {ok:true,doc:{date_iso:date,sections}};
  }}}};
  vm.createContext(context);vm.runInContext(save+'\n'+drop,context);
  context.attachApaSectionDrop({dataset:{section:'Amaya'},classList:{remove(){}},querySelectorAll:()=>[],addEventListener:(type,fn)=>handlers[type]=fn});
  await handlers.drop({preventDefault(){},clientY:100});
  const rows=context.state.doc.sections;
  assert.equal(rows.reduce((n,s)=>n+s.items.length,0),1);
  assert.equal(rows[mode==='ok'?1:0].items[0].text,'Test job');
  assert.equal(messages.at(-1)[1],mode==='ok'?'ok':'error');
 }
 console.log('PASS: actual drop/save handlers preserve the card on success, rejection, and exception.');
})().catch(e=>{console.error(e);process.exitCode=1;});
