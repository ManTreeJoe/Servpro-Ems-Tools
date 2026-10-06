const assert=require('node:assert/strict');
(async()=>{
 const {handle}=await import('../supabase/functions/comment-parent/core.mjs');
 const card='a'.repeat(24),parent='b'.repeat(24),board='c'.repeat(24);
 const env={SUPABASE_URL:'https://db.test',SUPABASE_ANON_KEY:'anon',SUPABASE_SERVICE_ROLE_KEY:'service',TRELLO_SYNC_API_KEY:'key',TRELLO_SYNC_TOKEN:'secret'};
 let writes=[],providerReads=0,authorized=true,wrongCard=false,saved=[];
 const fetcher=async(url,options={})=>{
  url=String(url);let value;
  if(url.includes('/auth/v1/user')) value={id:'user'};
  else if(url.includes('hub_trello_mirror_cards')) {assert.equal(options.headers.Authorization,'Bearer user');value=authorized?[{board_id:board}]:[];}
  else if(url.includes('/rest/v1/job_comment_threads')) {
   if(options.method==='POST'){writes.push(JSON.parse(options.body));assert.equal(options.headers.Authorization,'Bearer service');value={};}
   else value=saved;
  } else if(url.includes('/actions/')) {providerReads++;value={id:parent,type:'commentCard',data:{card:{id:wrongCard?'d'.repeat(24):card},text:'@laura hello'},memberCreator:{username:'sam',fullName:'Sam'},date:'2026-10-06T12:00:00Z'};}
  else if(url.includes('/cards/'))value={id:card,idBoard:board};
  else throw Error('Unexpected request');
  return new Response(JSON.stringify(value),{status:200});
 };
 const request=()=>new Request('https://gateway.test',{method:'POST',headers:{Authorization:'Bearer user'},body:JSON.stringify({card_id:card,parent_id:parent,body:'forged'})});
 let result=await(await handle(request(),env,fetcher)).json();
 assert.equal(result.ok,true);assert.equal(result.author_username,'sam');assert.equal(writes[0].body,'@laura hello');
 assert.equal(writes[0].id,parent);assert.equal(writes[0].root_id,parent);
 writes=[];wrongCard=true;
 result=await(await handle(request(),env,fetcher)).json();assert.equal(result.ok,false);assert.equal(writes.length,0);
 authorized=false;providerReads=0;
 result=await(await handle(request(),env,fetcher)).json();assert.equal(result.ok,false);assert.equal(providerReads,0);
 authorized=true;wrongCard=false;saved=[{id:'oneloss:existing',provider_id:parent}];
 result=await(await handle(request(),env,fetcher)).json();assert.equal(result.parent_id,'oneloss:existing');assert.equal(writes.length,0);
 console.log('PASS: immediate verified import, caller RLS, wrong-card rejection, no client body trust, native identity preservation.');
})().catch(e=>{console.error(e);process.exitCode=1});
