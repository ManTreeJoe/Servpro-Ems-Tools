/* Supabase documented Phoenix v1 protocol; user JWT + table RLS.
 * Events invalidate the view. Never trust event payloads as job data.
 */
window.OneLossScheduleRealtime=function({credentials,changed,status}){
 let socket=null,disposed=false,retry=null,heartbeat=null,authTimer=null,joinTimeout=null;
 let attempt=0,generation=0,reference=0,awaitingBeat=null,topic='';
 function clear(){clearInterval(heartbeat);clearInterval(authTimer);clearTimeout(joinTimeout);}
 function send(event,payload={},target=topic){
   if(socket?.readyState!==1)return null;
   const ref=String(++reference);socket.send(JSON.stringify({topic:target,event,payload,ref,join_ref:target===topic?'1':null}));return ref;
 }
 function lost(){
   clear();const old=socket;socket=null;generation++;old?.close();
   if(disposed||retry)return;
   status('Reconnecting · backup refresh active');
   retry=setTimeout(()=>{retry=null;connect();},Math.min(30000,1000*2**Math.min(attempt++,5)));
 }
 async function connect(){
   const gen=++generation;
   try{
     const auth=await credentials();if(disposed||gen!==generation)return;
     const url=new URL(auth.url);if(url.protocol!=='https:')throw new Error('HTTPS required');
     url.protocol='wss:';url.pathname='/realtime/v1/websocket';url.search=new URLSearchParams({apikey:auth.key,vsn:'1.0.0'}).toString();
     topic='realtime:schedule:'+auth.department;reference=0;awaitingBeat=null;
     socket=new WebSocket(url.toString());const own=socket;
     joinTimeout=setTimeout(()=>{if(gen===generation)lost();},15000);
     own.onopen=()=>{
       if(gen!==generation)return;
       send('phx_join',{access_token:auth.token,config:{broadcast:{ack:false,self:false},presence:{enabled:false},postgres_changes:[{event:'*',schema:'public',table:'schedule_visits',filter:'department=eq.'+auth.department}]}});
       heartbeat=setInterval(()=>{if(awaitingBeat){lost();return;}awaitingBeat=send('heartbeat',{},'phoenix');},25000);
       authTimer=setInterval(async()=>{
         try{const fresh=await credentials();if(gen===generation)send('access_token',{access_token:fresh.token});}
         catch{if(gen===generation)lost();}
       },60000);
     };
     own.onmessage=event=>{
       if(gen!==generation)return;
       let message;try{message=JSON.parse(event.data);}catch{return;}
       if(message.event==='phx_reply'&&message.ref===awaitingBeat)awaitingBeat=null;
       if(message.event==='system'&&message.payload?.extension==='postgres_changes'&&message.payload.status==='ok'){
         clearTimeout(joinTimeout);attempt=0;status('Live');changed();
       }else if(message.event==='postgres_changes'){changed();}
       else if(['phx_error','phx_close'].includes(message.event)||(message.event==='phx_reply'&&message.payload?.status==='error')||(message.event==='system'&&message.payload?.status==='error'))lost();
     };
     own.onclose=()=>{if(gen===generation)lost();};
     own.onerror=()=>{if(gen===generation)lost();};
   }catch{if(gen===generation)lost();}
 }
 connect();
 return {close(){disposed=true;generation++;clearTimeout(retry);clear();socket?.close();socket=null;}};
};
