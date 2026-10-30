// Shared across native companion pages. A notice never programs USB without Yes.
(()=>{
  if(document.getElementById('usb-detection-notice'))return;
  const dialog=document.createElement('dialog');dialog.id='usb-detection-notice';dialog.setAttribute('aria-labelledby','usb-notice-title');
  const heading=document.createElement('div');heading.className='usb-notice-heading';
  const title=document.createElement('h2');title.id='usb-notice-title';
  const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Close USB receiver notice');heading.append(title,close);
  const message=document.createElement('p'),list=document.createElement('div'),hint=document.createElement('p'),error=document.createElement('p'),actions=document.createElement('div');
  list.className='usb-notice-list';hint.className='usb-notice-hint';error.className='usb-notice-error';error.setAttribute('role','status');actions.className='usb-notice-actions';
  const check=document.createElement('button');check.type='button';check.textContent='Refresh';
  const status=document.createElement('p');status.className='usb-notice-scan';status.setAttribute('role','status');
  const cancel=document.createElement('button');cancel.type='button';const yes=document.createElement('button');yes.type='button';yes.className='usb-notice-primary';yes.textContent='Yes, assign a new ID';actions.append(check,cancel,yes);
  dialog.append(heading,message,list,hint,error,status,actions);document.body.append(dialog);
  let event=null,token='',last=null,deadline=null,pending=false,selected=null,timer=null,oldFocus=null,polling=false;
  try{last=sessionStorage.getItem('usb-notice-dismissed');}catch{}
  const dismiss=()=>{if(event){fetch('/api/dongle-notice',{method:'POST',headers:{'Content-Type':'application/json','X-USB-Notice-Token':token},body:JSON.stringify({action:'dismiss',event:event.id})}).catch(()=>{});last=event.id;try{sessionStorage.setItem('usb-notice-dismissed',last);}catch{}}dialog.close();clearInterval(timer);oldFocus?.focus?.({preventScroll:true});};
  close.onclick=cancel.onclick=dismiss;dialog.addEventListener('cancel',e=>{e.preventDefault();dismiss();});
  function render(notice){
    const fresh=event?.id!==notice.id;event=notice;if(fresh){deadline=notice.timeout_seconds!=null?Date.now()+notice.timeout_seconds*1000:['ready','arrival'].includes(notice.kind)?Date.now()+(notice.kind==='arrival'?15000:10000):null;error.textContent='';}
    if(fresh||!notice.receivers.some(r=>r.id===selected&&(r.can_assign||r.can_choose)))selected=notice.receivers.find(r=>r.id===notice.target&&(r.can_assign||r.can_choose))?.id||null;
    title.textContent=notice.title;message.textContent=notice.message;
    const statuses={busy:'In use',unverified:'Identity needs checking',queued:'Queued',working:'Writing and verifying…',failed:'Failed',conflict:'ID conflict',ready:'Ready'};
    list.replaceChildren(...notice.receivers.map(r=>{
      const row=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('span');
      row.className='usb-notice-row'+(r.conflict?' usb-notice-conflict':'')+(r.id===selected?' usb-notice-target':'');
      name.textContent=r.name;meta.textContent='ID '+r.serial+' · USB '+r.port+' · '+(r.state==='reconnect'?'Reconnect → '+r.new_serial:statuses[r.state]||'Ready');row.append(name,meta);
      if(r.error){const detail=document.createElement('span');detail.textContent=r.error;row.append(detail);}
      if(r.can_assign||r.can_choose){const choose=document.createElement('button');choose.type='button';choose.textContent=r.id===selected?'Selected':notice.kind==='select'?'Select':'Assign ID';choose.setAttribute('aria-pressed',r.id===selected?'true':'false');choose.onclick=()=>{selected=r.id;deadline=null;render(event);};row.append(choose);}
      return row;
    }));
    const connectedPorts=new Set(notice.receivers.map(r=>r.port));
    for(const p of notice.pending_reconnects||[]){if(connectedPorts.has(p.port))continue;const row=document.createElement('div');row.className='usb-notice-row';row.textContent=p.name+' · USB '+p.port+' · Reconnect → '+p.serial;list.append(row);}
    const candidate=notice.receivers.find(r=>r.id===selected&&(r.can_assign||r.can_choose));
    yes.hidden=!candidate&&notice.kind!=='discovery'&&!notice.duplicate_warning;yes.disabled=pending;yes.textContent=notice.duplicate_warning?'Fix now':notice.kind==='discovery'?'Review receivers':notice.kind==='select'?'Use receiver':'Yes, assign a new ID';cancel.textContent=notice.kind==='discovery'||notice.duplicate_warning?'Later':['conflict','failed','select'].includes(notice.kind)?'Cancel':'Close';
    hint.textContent=notice.kind==='discovery'?'You can also configure receivers later under USB-Radios.':notice.kind==='select'?'Choose a receiver to assign and start.':candidate?'Selected: '+candidate.name+' · USB '+candidate.port+'. After saving, reconnect only this receiver. Other ID changes can be queued.':notice.kind==='working'?'New plug-ins remain visible while ID changes finish.':'Leave the hub powered. Reconnect updated receivers individually.';
    const tick=()=>{if(deadline!==null){hint.textContent='Closes automatically in '+Math.max(0,Math.ceil((deadline-Date.now())/1000))+' seconds.';if(Date.now()>=deadline)dismiss();}};
    clearInterval(timer);tick();if(notice.id===last)return;if(deadline!==null)timer=setInterval(tick,250);
    const passive=notice.kind==='arrival'&&!notice.duplicate_warning;
    dialog.dataset.arrival=String(notice.kind==='arrival');
    if(dialog.open&&dialog.dataset.passive!==String(passive))dialog.close();
    dialog.dataset.passive=String(passive);
    if(!dialog.open){if(passive)dialog.show();else{oldFocus=document.activeElement;dialog.showModal();cancel.focus({preventScroll:true});}}
    if(fresh){const index=notice.receivers.findIndex(r=>(notice.arrived_ports||[]).includes(r.port));if(index>=0)list.children[index]?.scrollIntoView?.({block:'nearest'});}
  }
  yes.onclick=async()=>{
    if(pending||!event||(!selected&&event.kind!=='discovery'&&!event.duplicate_warning))return;const approved={action:event.kind==='discovery'||event.duplicate_warning?'review':event.kind==='select'?'choose':'assign_id',event:event.id,target:selected};pending=true;yes.disabled=true;error.textContent='';
    try{const r=await fetch('/api/dongle-notice',{method:'POST',headers:{'Content-Type':'application/json','X-USB-Notice-Token':token},body:JSON.stringify(approved)});if(!r.ok)throw Error((await r.json()).error||'Could not assign ID');await refresh();}
    catch(e){error.textContent=e.message;}finally{pending=false;yes.disabled=false;}
  };
  check.onclick=async()=>{
    if(check.disabled)return;check.disabled=true;status.textContent='Checking USB…';
    try{const r=await fetch('/api/dongle-notice',{method:'POST',headers:{'Content-Type':'application/json','X-USB-Notice-Token':token},body:JSON.stringify({action:'refresh'}),signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error('Could not request USB check');await refresh();}
    catch(e){status.textContent=e.message;}finally{check.disabled=false;}
  };
  async function refresh(){
    if(document.hidden||polling)return;polling=true;
    try{const r=await fetch('/api/dongle-notice',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error('USB check unavailable');const state=await r.json();if(!state.available)throw Error('USB discovery unavailable');token=state.control_token;
      const age=state.checked_at?Math.max(0,Math.floor(Date.now()/1000-state.checked_at)):null,count=state.receivers?.length??state.notice?.receivers.length??0;
      status.textContent=count+' connected · '+(state.scan_error?'USB check failed · '+state.scan_error:age===null?'Checking USB…':age>10?'Last checked '+age+'s ago · waiting for USB check':state.checking?'Checking USB…':(age<2?'Checked just now':'Checked '+age+'s ago')+' · Auto refresh');
      if(!state.notice){if(dialog.open)dialog.close();event=null;clearInterval(timer);return;}
      if(state.notice.id===last)return;
      render(state.notice);
    }catch{status.textContent='Cannot refresh USB list · retrying automatically';}
    finally{polling=false;}
  }
  refresh();setInterval(refresh,1500);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();
