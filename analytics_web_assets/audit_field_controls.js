/* Guided inputs retain the audit's existing canonical field contract. */
(() => {
 function elapsed(minutes){
  if(!Number.isFinite(minutes)||minutes<0)return 'Unknown';
  if(minutes>0&&minutes<1)return 'Less than a minute';
  const total=Math.floor(minutes),days=Math.floor(total/1440),hours=Math.floor(total%1440/60),mins=total%60;
  const parts=[];
  for(const [value,unit] of [[days,'day'],[hours,'hour'],[mins,'minute']])if(value)parts.push(`${value} ${unit}${value===1?'':'s'}`);
  return parts.join(' ')||'0 minutes';
 }
 const date=value=>{const m=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})/);return m?`${m[2]}/${m[3]}/${m[1]}`:String(value||'Not recorded');};
 function stamp(value){
  if(!value)return 'Not recorded';
  if(/^\d{4}-\d{2}-\d{2}$/.test(value))return date(value);
  if(!/(Z|[+-]\d{2}:\d{2})$/.test(value))return date(value.slice(0,10))+' '+value.slice(11)+' (timezone unverified)';
  const d=new Date(value);if(!Number.isFinite(d.getTime()))return 'Date unavailable';
  return new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',month:'2-digit',day:'2-digit',year:'numeric',hour:'numeric',minute:'2-digit',hour12:true,timeZoneName:'short'}).format(d);
 }
 function isoDate(value){
  const m=value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);if(!m)return '';
  const iso=`${m[3]}-${m[1]}-${m[2]}`,d=new Date(iso+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===iso?iso:'';
 }
 function timestamp(day,time,zone){
  if(!day||!time)return day||'';
  const local=day+'T'+time;
  if(zone!=='Pacific')return local+zone;
  // Validate both offsets against IANA rules; a DST gap or repeated hour needs a choice.
  const fmt=new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  const matches=['-07:00','-08:00'].filter(offset=>fmt.format(new Date(local+offset)).replace(' ','T')===local);
  return matches.length===1?local+matches[0]:'';
 }
 function pacificParts(value){
  const raw=String(value||''),m=raw.match(/^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))/);
  if(!/(Z|[+-]\d{2}:\d{2})$/.test(raw))return {day:raw.slice(0,10),time:m?.[2]||'',zone:'Pacific'};
  const instant=new Date(raw);if(!Number.isFinite(instant.getTime()))return {day:'',time:'',zone:'Pacific'};
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZoneName:'short'}).formatToParts(instant).map(p=>[p.type,p.value]));
  const day=`${parts.year}-${parts.month}-${parts.day}`,time=`${parts.hour}:${parts.minute}`;
  return {day,time,zone:timestamp(day,time,'Pacific')?'Pacific':parts.timeZoneName==='PDT'?'-07:00':'-08:00'};
 }
 function attach(form,comments){
  // Explicit US-format display regardless of the operating system's locale.
  for(const input of form.querySelectorAll('input[type=date][name]')){
   const label=input.closest('label'),title=label.firstChild.textContent.trim();
   const display=document.createElement('input');display.placeholder='MM/DD/YYYY';display.inputMode='numeric';display.setAttribute('aria-label',title);
   input.type='hidden';input.after(display);
   const picker=document.createElement('input');picker.type='date';picker.className='audit-calendar-native';picker.tabIndex=-1;picker.setAttribute('aria-label',title+' calendar');
   const button=document.createElement('button');button.type='button';button.textContent='Choose date';button.setAttribute('aria-label','Choose '+title+' date');
   // Keep only the visible text input inside the original label.
   label.after(picker,button);button.onclick=()=>picker.showPicker();
   const sync=()=>{display.value=input.value?date(input.value):'';picker.value=input.value;display.setCustomValidity('');};
   display.oninput=()=>{const value=isoDate(display.value);display.setCustomValidity(display.value&&!value?'Use a valid MM/DD/YYYY date.':'');input.value=value;picker.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));};
   display.onchange=()=>{if(display.validity.valid)input.dispatchEvent(new Event('change',{bubbles:true}));};
   picker.oninput=()=>{input.value=picker.value;sync();input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));};
   input.addEventListener('change',sync);sync();
   const group=document.createElement('div');group.className='audit-date-field';label.before(group);group.append(label,picker,button);
  }
  for(const key of ['incoming_loss_at','insured_contacted_at','on_site_at','inspection_at','field_note_posted_at','inspection_completed_at','initial_note_sent_at']){
   const input=form.elements[key];if(!input||!input.closest('label'))continue;
   const label=input.closest('label');input.type='hidden';
   const controls=document.createElement('div');controls.className='audit-clock-controls';
   controls.innerHTML='<label>Date (MM/DD/YYYY)<input data-day placeholder="MM/DD/YYYY" inputmode="numeric"></label><label>Time<input data-time type="time"></label><label>Timezone<select data-zone><option value="Pacific">Pacific (automatic)</option><option value="-07:00">PDT (UTC−07:00)</option><option value="-08:00">PST (UTC−08:00)</option></select></label><small data-clock-hint></small>';
   const group=document.createElement('div');group.className='audit-clock-field';label.before(group);group.append(label,controls);
   const day=controls.querySelector('[data-day]'),clock=controls.querySelector('[data-time]'),zone=controls.querySelector('[data-zone]'),hint=controls.querySelector('[data-clock-hint]');
   day.setAttribute('aria-label',key+' date');clock.setAttribute('aria-label',key+' time');
   const calendar=document.createElement('input');calendar.type='date';calendar.lang='en-US';calendar.className='audit-calendar-native';calendar.tabIndex=-1;calendar.setAttribute('aria-label',key+' calendar');day.after(calendar);
   const calendarButton=document.createElement('button');calendarButton.type='button';calendarButton.textContent='Choose date';calendarButton.onclick=()=>calendar.showPicker();calendar.after(calendarButton);
   function sync(){const raw=input.value,p=pacificParts(raw);day.value=p.day?date(p.day):'';calendar.value=p.day;clock.value=p.time;zone.value=p.zone;hint.textContent=raw&&!/(Z|[+-]\d{2}:\d{2})$/.test(raw)?'Unverified until date, time and timezone are confirmed.':'';}
   const update=()=>{const d=isoDate(day.value);day.setCustomValidity(day.value&&!d?'Use a valid MM/DD/YYYY date.':'');calendar.value=d;const value=timestamp(d,clock.value,zone.value);clock.setCustomValidity(d&&clock.value&&!value?'Verify this daylight-saving time and choose PST or PDT.':'');input.value=value;hint.textContent=d&&clock.value&&!value?'This Pacific time is skipped or repeated by daylight saving. Verify the time and choose PST or PDT.':!d||!clock.value?'Unverified — both date and time are required.':'';input.dispatchEvent(new Event('input',{bubbles:true}));};
   for(const el of [day,clock,zone])el.addEventListener('input',update);
   calendar.oninput=()=>{day.value=date(calendar.value);update();};
   input.addEventListener('change',sync);sync();
   if(window.AuditCommentLinks&&['field_note_posted_at','initial_note_sent_at'].includes(key)){
    const manual=document.createElement('details'),summary=document.createElement('summary'),shown=document.createElement('p');summary.textContent='Manual time / correction';manual.append(summary,controls);group.append(shown,manual);
    const updateShown=()=>shown.textContent=input.value?stamp(input.value):'Right-click the correct comment → Link to audit…';
    input.addEventListener('input',updateShown);updateShown();
   }
   if(!window.AuditCommentLinks&&['field_note_posted_at','initial_note_sent_at'].includes(key)){
    const choose=document.createElement('select');choose.setAttribute('aria-label',key==='field_note_posted_at'?'Select field inspection post':'Select coordinator initial-note post');
    choose.add(new Option('Use the posting time of a selected comment…',''));
    comments.forEach((c,i)=>choose.add(new Option(`${stamp(c.date)} · ${c.author||'Unknown'} · ${String(c.text||'').replace(/\s+/g,' ').slice(0,80)}`,String(i))));
    choose.onchange=()=>{if(choose.value==='')return;const c=comments[Number(choose.value)];input.value=c.date||'';input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('input',{bubbles:true}));
     const reference=`${key==='field_note_posted_at'?'Field':'Coordinator'} post: ${c.id||'ID unavailable'} · ${c.author||'Unknown'} · ${stamp(c.date)}`;
     form.elements.timing_source.value=[form.elements.timing_source.value,reference].filter(Boolean).join('\n');
     if(key==='initial_note_sent_at'&&c.author){form.elements.missed_by.value=c.author;form.elements.missed_by.dispatchEvent(new Event('input',{bubbles:true}));}
    };group.append(choose);
   }
  }
  const estimators=['Zac','Aaron','Juan','Aaron L','Pablo','Mark L','Amaya','Esteban','Johnny','Kim','Victoria','Samantha'];
  const people=[...new Set([...estimators,...comments.map(c=>c.author).filter(Boolean)])];
  for(const [key,names] of [['ems_estimator',estimators],['contents_estimator',estimators],['missed_by',people]]){
   const input=form.elements[key],list=document.createElement('datalist');list.id='audit-people-'+key;
   input.setAttribute('aria-label',input.closest('label').firstChild.textContent.trim());
   for(const name of [...new Set([...names,'N/A',input.value].filter(Boolean))])list.append(new Option(name,name));
   input.setAttribute('list',list.id);input.placeholder='Search or enter a name';input.after(list);
  }
  const source=form.elements.timing_source,select=document.createElement('select');select.setAttribute('aria-label','Choose timing source comment');
  if(window.AuditCommentLinks){source.closest('label').hidden=true;return;}
  select.add(new Option('Choose a supporting comment…',''));
  comments.forEach((c,i)=>select.add(new Option(`${stamp(c.date)} · ${c.author||'Unknown'} · ${String(c.text||'').replace(/\s+/g,' ').slice(0,85)}`,String(i))));
  select.onchange=()=>{if(select.value==='')return;const c=comments[Number(select.value)];source.value=`Comment ${c.id||'(ID unavailable)'} · ${c.author||'Unknown'} · ${stamp(c.date)}`;source.dispatchEvent(new Event('input',{bubbles:true}));};
  source.before(select);source.placeholder='Or enter a manual reference';
 }
 window.AuditFieldControls={date,stamp,isoDate,timestamp,pacificParts,elapsed,attach};
})();
