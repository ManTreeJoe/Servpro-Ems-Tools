/* Coalesce server invalidations, not drafts. Existing presentation queue owns
 * hidden-panel, in-flight refresh and drag protections. Polling remains backup. */
window.startJobsLive=function(changed){
 if(!window.OneLossScheduleRealtime || !window.pywebview?.api?.jobs_realtime)return null;
 let pending=null;
 const live=window.OneLossScheduleRealtime({
  channel:'jobs',changes:[{event:'*',schema:'public',table:'hub_jobs_live_changes'}],
  credentials:async()=>{const auth=await pywebview.api.jobs_realtime();if(!auth?.ok)throw Error('Unavailable');return auth;},
  status:()=>{},
  changed:()=>{if(pending!==null)return;pending=setTimeout(()=>{pending=null;changed();},500);}
 });
 const close=()=>{clearTimeout(pending);live.close();};
 window.addEventListener('pagehide',close,{once:true});
 return {close};
};
