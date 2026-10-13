/* Local view filters only: never change delivery or read status. */
(()=>{'use strict';
  const labels={moves:'Moves',reactions:'Reactions',messages:'Messages',tags:'Tags / mentions',other:'Other activity'};
  function category(item){
    const type=item.type||item.kind;
    if(type==='mentionedOnCard'||type==='mention')return 'tags';
    if(type==='commentCard'||type==='comment')return 'messages';
    if(type==='reactionAdded'||type==='reactionRemoved')return 'reactions';
    if(item.is_move||['moveCard','moveCardToBoard','moveCardFromBoard'].includes(type))return 'moves';
    return 'other';
  }
  function mount(host,onChange){
    const selected=new Set(Object.keys(labels));
    const root=document.createElement('details');root.className='notification-types';
    const summary=document.createElement('summary');root.append(summary);
    const menu=document.createElement('div');menu.className='notification-types-menu';root.append(menu);
    const all=document.createElement('button');all.type='button';all.textContent='Select all';menu.append(all);
    const inputs=[];
    function update(){summary.textContent=selected.size===5?'Types: All':selected.size===0?'Types: None':selected.size===1?'Types: '+labels[[...selected][0]]:`Types: ${selected.size} selected`;onChange();}
    for(const [key,label] of Object.entries(labels)){
      const row=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=true;input.value=key;
      row.append(input,document.createTextNode(label));menu.append(row);inputs.push(input);
      input.onchange=()=>{input.checked?selected.add(key):selected.delete(key);update();};
    }
    all.onclick=()=>{inputs.forEach(input=>{input.checked=true;selected.add(input.value);});update();};
    root.onkeydown=e=>{if(e.key==='Escape'){root.open=false;summary.focus();}};
    document.addEventListener('click',e=>{if(!root.contains(e.target))root.open=false;});
    summary.textContent='Types: All';host.prepend(root);
    return {matches:item=>selected.has(category(item)),active:()=>selected.size!==5};
  }
  window.NotificationTypes={mount,category};
})();
