const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 for(const type of ['apa','pipeline']){
  const page=await browser.newPage();await page.route(/^https?:/,r=>r.abort());
  await page.addInitScript(()=>{window.pywebview={api:{get_pinned_card_for_item:async()=>({}),save_doc:async(date,sections)=>({ok:true,doc:{date_iso:date,doc_exists:true,sections}})}}});
  await page.goto(pathToFileURL(path.resolve(type+'_web_assets/index.html')).href);
  const result=await page.evaluate(async(type)=>{
   if(type==='apa') state.doc={date_iso:'2026-09-25',doc_exists:true,sections:Array.from({length:8},(_,j)=>({name:'Crew '+j,items:Array.from({length:80},(_,i)=>({text:'Card '+i})),count:80}))};
   else {state.board={boards:[{key:'wip',name:'Work',lanes:Array.from({length:8},(_,j)=>({list_id:'l'+j,name:'Lane '+j,cards:Array.from({length:40},(_,i)=>({card_id:'c'+j+'-'+i,client:'Test '+i,labels:[],pos:i+1}))}))}]};state.activeBoardKey='wip';}
   renderBoard();
   const outer=()=>document.querySelector(type==='apa'?'#board':'.lanes-row');
   const lane=()=>document.querySelector(type==='apa'?'.section-body':'.lane-cards');
   outer().scrollLeft=500;lane().scrollTop=400;
   const before=[outer().scrollLeft,lane().scrollTop];
   const focus= document.querySelector(type==='apa'?'.note-btn':'[data-act="star"]');
   focus.focus({preventScroll:true});
   if(type==='apa') state.doc.sections[0].items[1].highlighted=true;
   else state.board.boards[0].lanes[0].cards[1].client='Changed name';
   if(type==='apa') await saveDoc();else renderBoard();
   const focused=document.activeElement.matches(type==='apa'?'.note-btn':'[data-act="star"]');
   const first=document.querySelector(type==='apa'?'.item':'.kcard');
   renderBoard();
   const retained=first===document.querySelector(type==='apa'?'.item':'.kcard');
   const after=[outer().scrollLeft,lane().scrollTop];
   // External drafts must never lose focus to a background board redraw.
   const draft=document.createElement('input');document.body.append(draft);draft.value='Unsaved draft';draft.focus();
   renderBoard();const draftKept=document.activeElement===draft && draft.value==='Unsaved draft';
   if(type==='apa') state.doc.date_iso='2026-09-26';
   else {state.board.boards[0].key='contents';state.activeBoardKey='contents';}
   renderBoard();const navigation=[outer().scrollLeft,lane().scrollTop];
   return{before,after,focused,retained,draftKept,navigation};
  },type);
  assert.deepEqual(result.after,result.before,type+' save/render must preserve the view');
  assert.equal(result.focused,true,type+' matching control keeps focus');
  assert.equal(result.draftKept,true,'External draft retains focus and text');
  assert.deepEqual(result.navigation,[0,0],'New board/date must not inherit unrelated scroll');
  if(type==='apa') assert.equal(result.retained,true,'Identical acknowledgment must not replace APA DOM');
  console.log('PASS: '+type+' scroll stays put');await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
