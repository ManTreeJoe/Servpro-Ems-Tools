const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('pipeline_web_assets/app.js','utf8');
const code=source.slice(source.indexOf('async function onLaneDrop('),source.indexOf('function moveCardLocally('));
(async()=>{
 for(const mode of ['normal','failed','conflict-cancel','conflict-accept']){
  let prompts=0,moves=0,undos=0,reloads=0,local=0;
  const ctx={state:{drag:{name:'Test',cardId:'c',fromListId:'a',conflict:mode.startsWith('conflict')}},
   confirm:()=>{prompts++;return mode==='conflict-accept';},setStatus(){},
   pywebview:{api:{move_card:async()=>{moves++;return {ok:mode!=='failed'};}}},
   moveCardLocally(){local++;},renderBoard(){},showMoveUndo(){undos++;},loadBoard:async()=>{reloads++;}};
  vm.createContext(ctx);vm.runInContext(code,ctx);
  await ctx.onLaneDrop({preventDefault(){},currentTarget:{dataset:{listId:'b',laneName:'Next'},classList:{remove(){}}}});
  assert.equal(prompts,mode.startsWith('conflict')?1:0);
  assert.equal(moves,mode==='conflict-cancel'?0:1);
  assert.equal(undos,mode==='normal'||mode==='conflict-accept'?1:0);
  assert.equal(local,undos);assert.equal(reloads,mode==='failed'?1:0);
 }
 console.log('PASS: routine moves are direct; undo, conflicts and failed-move recovery remain.');
})().catch(e=>{console.error(e);process.exitCode=1;});
