/* One settled query per picker; typing never waits for an earlier request. */
window.ScheduleSearchQueue = function ({delay=220}={}) {
  let timer=null, pending=null, busy=false, generation=0;
  async function drain(){
    if(busy||!pending?.settled)return;
    const next=pending;pending=null;busy=true;
    try{await next.run(()=>next.generation===generation);}
    finally{busy=false;void drain();}
  }
  return {
    schedule(run){
      clearTimeout(timer);
      const next={run,generation:++generation,settled:false};pending=next;
      timer=setTimeout(()=>{timer=null;next.settled=true;void drain();},delay);
    },
    invalidate(){clearTimeout(timer);timer=null;pending=null;generation++;}
  };
};
