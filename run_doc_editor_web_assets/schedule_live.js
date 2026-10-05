/* Persistent drafts only. Transport is the signed-in desktop API. */
window.OneLossScheduleLive = function ({render, notice}) {
  let context='', department='', pending=null, loading=false;
  const call=async(name,...args)=>{
    const api=window.pywebview?.api;
    if(!api)throw new Error('The desktop connection is not ready. Reopen Schedule.');
    const result=await api[name](...args);
    if(!result?.ok)throw new Error(result?.error||'Schedule request failed.');
    return result;
  };
  return {
    importDocument(day){return call('schedule_pick_document',day,context);},
    credentials(){return call('schedule_realtime',context);},
    async load() {
      if(loading)return; loading=true;
      try {
        const result=await call('schedule_load');
        if(context&&context!==result.context)throw new Error('Account or office changed. Reopen Schedule before continuing.');
        context=result.context;department=result.department;
        render(result.records);notice('Live drafts · '+department+' · Saved visits only. Confirm day, posting and printing are not enabled yet.');
      } catch(error) {notice(error.message,true);throw error;}
      finally {loading=false;}
    },
    async search(query) {
      if(!context)throw new Error('Wait for Schedule to load before searching.');
      return (await call('schedule_search',query,context)).jobs;
    },
    async save(row, placement) {
      if(!context)throw new Error('Reopen Schedule before saving.');
      const visit={id:row.id,job_id:row.job_id,queue:row.queue,group:row.group,
        date:row.date||null,arrival:row.time||'',activities:row.activities,
        equipment:row.equipment||'',access:row.access||'',notes:row.notes||'',status:'active'};
      const command={department,expected_revision:row.revision||0,visit};
      if(placement)command.before_id=placement.beforeId||null;
      const signature=JSON.stringify(command);
      if(!pending||pending.signature!==signature)pending={signature,command:{...command,operation_id:crypto.randomUUID()}};
      await call('schedule_save',pending.command,context);
      pending=null;
    }
  };
};
