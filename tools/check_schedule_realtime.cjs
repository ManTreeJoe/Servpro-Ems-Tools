// Read-only live handshake check. Credentials remain in memory and are never logged.
const {execFileSync}=require('node:child_process');
const auth=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c',
 "import json; from schedule_store import ScheduleStore; s=ScheduleStore(); print(json.dumps({'url':s.url,'key':s.key,'token':s.token,'department':s.department}))"],{encoding:'utf8'}));
async function subscriber(){
 return new Promise((resolve,reject)=>{
  const url=new URL(auth.url);url.protocol='wss:';url.pathname='/realtime/v1/websocket';url.search=new URLSearchParams({apikey:auth.key,vsn:'1.0.0'});
  const socket=new WebSocket(url),timeout=setTimeout(()=>{socket.close();reject(new Error('Subscription timed out'));},15000);
  socket.onopen=()=>socket.send(JSON.stringify({topic:'realtime:schedule-check',event:'phx_join',ref:'1',join_ref:'1',payload:{access_token:auth.token,config:{broadcast:{ack:false,self:false},presence:{enabled:false},postgres_changes:[{event:'*',schema:'public',table:'schedule_visits',filter:'department=eq.'+auth.department}]}}}));
  socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.event==='system'&&m.payload?.extension==='postgres_changes'&&m.payload.status==='ok'){clearTimeout(timeout);socket.close();resolve();}else if(m.payload?.status==='error'){clearTimeout(timeout);socket.close();reject(new Error('Subscription rejected'));}};
  socket.onerror=()=>{clearTimeout(timeout);socket.close();reject(new Error('Websocket connection failed'));};
 });
}
Promise.all([subscriber(),subscriber()]).then(()=>console.log('Two independent authenticated schedule subscriptions connected. No records modified.')).catch(e=>{console.error(e.message);process.exitCode=1;});
