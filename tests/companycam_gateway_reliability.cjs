// Execute the real gateway handler with deterministic, offline HTTP fixtures.
const fs = require('node:fs'), vm = require('node:vm');
const {stripTypeScriptTypes} = require('node:module');
const assert = require('node:assert/strict');
const source = fs.readFileSync('supabase/functions/companycam-gateway/index.ts','utf8')
  .replace(/^import\s*\{[\s\S]*?\}\s*from\s*"[^" ]+";\s*/, '');
async function run({credentialFailure=false, statusFailure=false}={}) {
 let handler, providerCalls=0, statusCalls=0;
 const pending=[];
 const context = {Request,Response,URL,URLSearchParams,AbortSignal,console,
  Deno:{env:{get:name=>({SUPABASE_URL:'https://fixture.invalid',SUPABASE_ANON_KEY:'fixture-key',COMPANYCAM_IE_KEY:'fixture-fallback'})[name]},serve:fn=>handler=fn},
  EdgeRuntime:{waitUntil:p=>pending.push(p)},
  serviceHeaders:()=>({}), decryptSecret:async()=> 'fixture-personal',
  encryptSecret:async()=>({cipher:'fixture',iv:'fixture'}),companyCamApp:()=>({}),
  fetch:async (url, options={})=> {
   const path=new URL(url).pathname;
   if(path==='/auth/v1/user')return Response.json({id:'fixture-user'});
   if(path==='/rest/v1/rpc/my_app_access')return Response.json({departments:['IE']});
   if(path==='/rest/v1/external_oauth_credentials')return credentialFailure
     ? Response.json({error:'database unavailable'},{status:503})
     : Response.json([{access_token_cipher:'fixture',access_token_iv:'fixture'}]);
   if(path==='/rest/v1/external_connection_status') {
    statusCalls++; if(statusFailure)throw Error('status write unavailable');
    return new Response(null,{status:204});
   }
   if(new URL(url).hostname==='api.companycam.com') {
    providerCalls++; return Response.json([{id:'fixture-project'}]);
   }
   throw Error('Unexpected test request: '+path);
  }};
 vm.runInNewContext(stripTypeScriptTypes(source),context);
 const request=()=>new Request('https://fixture.invalid/functions/v1/companycam-gateway',{
  method:'POST',headers:{Authorization:'Bearer fixture-session','Content-Type':'application/json'},
  body:JSON.stringify({department:'IE',path:'/projects',method:'GET'})});
 const response=await handler(request());
 await Promise.allSettled(pending);
 return {response,providerCalls,statusCalls,handler,request,pending};
}
(async()=>{
 const failed=await run({credentialFailure:true});
 assert.equal(failed.providerCalls,0,'DB credential failure must not switch to company token');
 assert.equal(failed.response.status,500);
 const status=await run({statusFailure:true});
 assert.equal(status.response.status,200,'ancillary health write must not erase provider success');
 const healthy=await run();
 for(let i=0;i<4;i++)assert.equal((await healthy.handler(healthy.request())).status,200);
 console.log('PASS: failed credential lookup is closed; health failure preserves provider response.');
})().catch(e=>{console.error(e);process.exit(1);});
