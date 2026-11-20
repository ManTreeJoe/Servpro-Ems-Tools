/* Settings navigation: explicit sections, existing controls and save ownership. */
(() => {
  const root=document.querySelector('.wrap');
  const definitions=[
    ['you',[['profile','Profile / account'],['connections','Connections'],['folders','My folders'],['appearance','Appearance & sidebar']]],
    ['office',[['people','People & access'],['franchises','Franchises'],['profiles','Job profiles'],['managers','Property managers'],['integrations','Integrations'],['reporting','Reporting / automation']]],
    ['maintenance',[['links','Job links / backfill'],['portable','Portable paths']]],
    ['advanced/support',[['advanced','Advanced / support']]]
  ];
  let role=false,selected='profile',latestHealth=null;
  const topCard=id=>{let n=document.getElementById(id);while(n && n.parentElement!==root && n.parentElement?.id!=='form-fields')n=n.parentElement;return n;};
  function tag(node,topic){if(!node)return;node.dataset.topic=topic;node.classList.add('topic-card');node.classList.remove('scope-hidden');if(node.tagName==='DETAILS')node.open=true;}
  function makeCard(id,title,description,parent=root){let node=document.getElementById(id);if(!node){node=document.createElement('section');node.id=id;node.className='settings-card';const h=document.createElement('h2');h.textContent=title;const p=document.createElement('p');p.className='topic-description';p.textContent=description;node.append(h,p);parent.append(node);}return node;}
  function select(topic){
    const allowed=new Set(definitions.filter((_,i)=>role||i===0).flatMap(([,rows])=>rows.map(([key])=>key)));
    selected=allowed.has(topic)?topic:'profile';
    root.querySelectorAll('[data-topic]').forEach(n=>{n.classList.toggle('topic-hidden',n.dataset.topic!==selected);});
    document.querySelectorAll('[data-settings-topic]').forEach(b=>{b.classList.toggle('active',b.dataset.settingsTopic===selected);b.setAttribute('aria-current',b.dataset.settingsTopic===selected?'page':'false');});
    root.scrollTop=0;
  }
  function health(status){latestHealth=status;if(!document.getElementById('settings-health-row'))return;const s=status||{};document.getElementById('settings-health-row').textContent=
    `Server: ${s.ok?(s.reachable?'Connected':'Unavailable'):'Unknown'}  ·  Signed in: ${s.ok?(s.signed_in?'Yes':'No'):'Unknown'}  ·  Pending sync: ${s.offline?.queued??'Unknown'}  ·  Trello writes paused: ${typeof s.trello_writes_paused==='boolean'?(s.trello_writes_paused?'Yes':'No'):'Unknown'}`;}
  function confirmAction(message,action){
    let dialog=document.getElementById('settings-confirm');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='settings-confirm';dialog.setAttribute('aria-labelledby','settings-confirm-title');dialog.innerHTML='<h2 id="settings-confirm-title">Advanced setting</h2><p id="settings-confirm-description"></p><div class="confirm-actions"><button type="button" class="btn" id="settings-confirm-cancel">Cancel</button><button type="button" class="btn btn-primary" id="settings-confirm-continue">Continue</button></div>';document.body.append(dialog);}
    dialog.querySelector('p').textContent=message;
    dialog.querySelector('#settings-confirm-cancel').onclick=()=>dialog.close();
    dialog.querySelector('#settings-confirm-continue').onclick=()=>{dialog.close();action();};
    dialog.showModal();dialog.querySelector('#settings-confirm-cancel').focus();
  }
  const confirmations={
    'sb-use-cloud':'Use the shared database for job data on this computer. This changes the database selected by the app.',
    'sb-use-local':'Switch this computer to the local recovery database. It may not contain the latest shared job data.',
    'open-config-file':'Open the configuration file in an external editor. It contains credentials; changes can break connections or redirect data.',
    'open-data-folder':'Open this computer’s application data folder. It can contain credentials and cached job information. Do not share its contents.',
    'open-tech-roster':'Open the roster JSON in an external editor. Changes affect name matching on this computer.',
    'authorize-trello-manual':'Open Trello’s manual authorization page. The resulting token grants access to your Trello account; keep it private.'
  };
  document.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button || !confirmations[button.id])return;
    if(button.dataset.confirmed==='yes'){delete button.dataset.confirmed;return;}
    event.preventDefault();event.stopImmediatePropagation();
    if(!role)return;
    confirmAction(confirmations[button.id],()=>{button.dataset.confirmed='yes';button.click();});
  },true);
  function gate(node,label,message){
    if(!node || node.closest('.support-gate'))return;
    const wrap=document.createElement('div');wrap.className='support-gate';const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=label;
    node.before(wrap);wrap.append(button,node);node.hidden=true;
    button.onclick=()=>confirmAction(message,()=>{node.hidden=false;button.hidden=true;node.querySelector('input,select,button')?.focus();});
  }
  function mount(access){
    role=!!access.is_admin;
    if(!document.getElementById('settings-navigation')){
      const shell=document.createElement('div');shell.className='settings-shell';root.before(shell);
      const nav=document.createElement('nav');nav.id='settings-navigation';nav.setAttribute('aria-label','Settings navigation');shell.append(nav,root);
      const row=document.createElement('div');row.id='settings-health-row';row.setAttribute('role','status');root.prepend(row);
    }
    root.querySelector('.settings-tabs').hidden=true;
    root.querySelector('.health-settings').hidden=true;
    root.querySelectorAll('[data-settings-scope]').forEach(n=>n.classList.toggle('scope-hidden',n.dataset.settingsScope==='admin'&&!role));
    const mapping={ 'account-sync':'profile','first-run-card':'profile','my-connections':'connections','folder-owner':'folders','user-access-card':'people','employee-access-card':'people','jp-list':'profiles','pm-list':'managers','dept-fields':'franchises','ji-result':'links','panel-visibility-grid':'appearance','browsers-body':'advanced'};
    for(const [id,topic] of Object.entries(mapping))tag(topCard(id),topic);
    const form=document.getElementById('form-fields');
    [...form.children].forEach(card=>{
      if(card.id==='folder-owner')return;
      const title=card.querySelector('summary,h2')?.textContent.trim();
      tag(card,({'Appearance & shortcuts':'appearance','Integration configuration':'integrations','Office identity':'franchises','Reporting goals':'reporting','Automation':'reporting'})[title]||card.dataset.topic||'advanced');
    });
    const support=makeCard('support-fields','Advanced / support','Recovery and connection controls. Confirm an action before using it.',form);tag(support,'advanced');
    const tools=topCard('open-config-file');
    if(tools && tools!==support){
      const roster=document.getElementById('edit-tech-roster');(document.getElementById('employee-access-card') || document.getElementById('user-access-card'))?.append(roster);
      const reporting=makeCard('reporting-actions','Workflow automation','Review the office’s automation setup.');tag(reporting,'reporting');reporting.append(document.getElementById('open-workflow-automations'));
      support.append(...tools.querySelector('.settings-disclosure-body').childNodes);tools.remove();
    }
    support.querySelectorAll('.admin-advanced').forEach(n=>n.open=true);
    const account=document.getElementById('account-sync');
    const preflight=document.getElementById('pf-run')?.parentElement;
    if(preflight && account.contains(preflight)) preflight.hidden=true;
    account.querySelectorAll('.admin-advanced').forEach(n=>n.hidden=true);
    ['sb-use-cloud','sb-use-local','sb-sync','pf-run','pf-out'].forEach(id=>{const n=document.getElementById(id);if(n&&!support.contains(n))support.append(n);});
    ['supabase_url','supabase_anon_key','preferred_browser'].forEach(key=>{const field=document.getElementById('f-'+key)?.closest('.field');if(field&&!field.closest('.support-gate')){support.append(field);gate(field,'Configure '+(key==='preferred_browser'?'browser command':key==='supabase_url'?'server URL':'server key'),key==='preferred_browser'?'Change the executable or command used to open external links. Only use a trusted browser command.':'Change the shared backend connection on this computer. An incorrect value can disconnect the app or point it at another database.');}});
    const browser=topCard('browsers-body');if(browser && browser!==support){support.append(browser);delete browser.dataset.topic;gate(browser,'Configure franchise browser commands','Change which browser command opens external tools for each franchise. Only use trusted executables.');}
    const portable=makeCard('portable-settings','Portable paths','Preview saved folder links before applying franchise-relative paths.');tag(portable,'portable');
    ['folder-path-preview','folder-path-apply'].forEach(id=>{const n=document.getElementById(id);if(n)portable.append(n);});
    // All original fields retain their existing form ancestry and save selectors.
    root.querySelectorAll('.field').forEach(field=>{const label=field.querySelector('label');if(label&&!field.querySelector('.field-description')){const d=document.createElement('small');d.className='field-description';d.textContent=field.closest('[data-topic="appearance"]')?'Personal preference on this computer.':field.closest('[data-topic="folders"]')?'Location reachable from this computer.':'Applies to the selected office or shared setup.';label.append(d);}});
    const nav=document.getElementById('settings-navigation');nav.replaceChildren();
    definitions.forEach(([label,items],index)=>{if(index&&!role)return;const group=document.createElement('section');group.dataset.navGroup=label;const h=document.createElement('h2');h.textContent=label;group.append(h);items.forEach(([key,title])=>{const b=document.createElement('button');b.type='button';b.dataset.settingsTopic=key;b.textContent=title;b.onclick=()=>select(key);group.append(b);});nav.append(group);});
    const updates=document.getElementById('open-app-updates');const updateCard=topCard('open-app-updates');if(updates){nav.append(updates);if(updateCard&&updateCard!==root)updateCard.hidden=true;}
    window.SettingsLayout.ready=true;health(latestHealth);select(selected);
  }
  window.addEventListener('employee-access-panel-ready',()=>{
    tag(topCard('employee-access-card'),'people');
    select(selected);
  });
  window.SettingsLayout={mount,select,health,ready:false};
})();
