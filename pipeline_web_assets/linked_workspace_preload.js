/* One navigation session; bounded, one-shot saved-detail warming, never a full audit. */
window.LinkedWorkspacePreload = {create(api, isActive) {
  const entries=new Map(), comments=new Map(), visited=new Set();
  let plan=[],running=false;
  const key=(id,division)=>`${String(division||'EMS').toUpperCase()}:${id}`;
  function commentLoad(id){
    const old=comments.get(id);
    if(old&&Date.now()-old.at<30000)return old.promise;
    const row={at:Date.now()};
    row.promise=Promise.resolve().then(()=>api.refresh_job_comments(id)).then(result=>{
      if(!result?.ok)comments.delete(id);
      return result;
    }).catch(error=>{comments.delete(id);throw error;});
    comments.set(id,row);return row.promise;
  }
  function fast(client,id,division){
    const row={at:Date.now(),value:null};
    row.promise=Promise.resolve().then(()=>api.job_card_workspace_fast(client,id,division)).then(value=>{
      row.value=value?.ok&&(!value.card_id||value.card_id===id)?value:null;
      return value;
    });
    entries.set(key(id,division),row);return row;
  }
  async function drain(){
    if(running)return;running=true;
    try{
      while(plan.length&&isActive()){
        const {client,id,division,onComments}=plan.shift(),k=key(id,division);
        if(visited.has(k)||entries.has(k))continue;
        const row=fast(client,id,division);
        try{
          await row.promise;
          if(!row.value){entries.delete(k);continue;}
          if(!isActive())continue;
          const result=await commentLoad(id);
          if(result?.ok){
            if(row.value)row.value={...row.value,comments:result.comments||[]};
            if(isActive())onComments?.(id,result);
          }
        }catch(_){entries.delete(k);/* Foreground open keeps its existing retry/error flow. */}
      }
    }finally{running=false;}
  }
  return {
    peek(id,division){const row=entries.get(key(id,division));return row&&Date.now()-row.at<30000?row.value:null;},
    load(client,id,division){
      const k=key(id,division),old=entries.get(k);visited.add(k);entries.delete(k);
      if(old&&Date.now()-old.at<30000)return old.promise.then(value=>old.value||value);
      return api.job_card_workspace_fast(client,id,division);
    },
    comments:commentLoad,
    schedule(data,onComments){
      const blocked=new Set((data.division_card_reconciliation?.divisions||[]).filter(row=>['conflict','ambiguous'].includes(row.state)).map(row=>String(row.division).toUpperCase()));
      const cards=data.division_trello_cards||[];
      plan=['EMS','CONTENTS','RECON'].filter(division=>division!==String(data.selected_division||'EMS').toUpperCase()).flatMap(division=>{
        const rows=cards.filter(row=>String(row.division).toUpperCase()===division&&row.card_id&&row.pinned===true&&!row.conflict);
        const ids=new Set(rows.map(row=>row.card_id));const row=rows[0];
        if(ids.size!==1||blocked.has(division)||cards.some(other=>String(other.division).toUpperCase()!==division&&other.card_id===row.card_id))return [];
        return [{client:data.client,id:row.card_id,division,onComments}];
      });
      // Yield so the opened division paints before speculative work begins.
      setTimeout(drain,0);
    }
  };
}};
