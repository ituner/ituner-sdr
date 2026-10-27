// Shared across native companion pages. A notice never programs USB without Yes.
(()=>{
  if(document.getElementById('usb-detection-notice'))return;
  const dialog=document.createElement('dialog');dialog.id='usb-detection-notice';dialog.setAttribute('aria-labelledby','usb-notice-title');
  const heading=document.createElement('div');heading.className='usb-notice-heading';
  const title=document.createElement('h2');title.id='usb-notice-title';
  const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Close USB receiver notice');heading.append(title,close);
  const message=document.createElement('p'),list=document.createElement('div'),hint=document.createElement('p'),error=document.createElement('p'),actions=document.createElement('div');
  list.className='usb-notice-list';hint.className='usb-notice-hint';error.className='usb-notice-error';error.setAttribute('role','status');actions.className='usb-notice-actions';
  const cancel=document.createElement('button');cancel.type='button';const yes=document.createElement('button');yes.type='button';yes.className='usb-notice-primary';yes.textContent='Yes, assign a new ID';actions.append(cancel,yes);
  dialog.append(heading,message,list,hint,error,actions);document.body.append(dialog);
  let event=null,token='',last=null,deadline=null,pending=false,selected=null,timer=null,oldFocus=null;
  try{last=sessionStorage.getItem('usb-notice-dismissed');}catch{}
  const dismiss=()=>{if(event){last=event.id;try{sessionStorage.setItem('usb-notice-dismissed',last);}catch{}}dialog.close();clearInterval(timer);oldFocus?.focus?.({preventScroll:true});};
  close.onclick=cancel.onclick=dismiss;dialog.addEventListener('cancel',e=>{e.preventDefault();dismiss();});
  function render(notice){
    const fresh=event?.id!==notice.id;event=notice;if(fresh){deadline=notice.kind==='ready'?Date.now()+10000:null;error.textContent='';}
    if(!notice.receivers.some(r=>r.id===selected&&r.can_assign))selected=notice.receivers.find(r=>r.id===notice.target&&r.can_assign)?.id||null;
    title.textContent=notice.title;message.textContent=notice.message;
    const statuses={queued:'Queued',working:'Writing and verifying…',failed:'Failed',conflict:'ID conflict',ready:'Ready'};
    list.replaceChildren(...notice.receivers.map(r=>{
      const row=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('span');
      row.className='usb-notice-row'+(r.conflict?' usb-notice-conflict':'')+(r.id===selected?' usb-notice-target':'');
      name.textContent=r.name;meta.textContent='ID '+r.serial+' · USB '+r.port+' · '+(r.state==='reconnect'?'Reconnect → '+r.new_serial:statuses[r.state]||'Ready');row.append(name,meta);
      if(r.error){const detail=document.createElement('span');detail.textContent=r.error;row.append(detail);}
      if(r.can_assign){const choose=document.createElement('button');choose.type='button';choose.textContent=r.id===selected?'Selected':'Assign ID';choose.setAttribute('aria-pressed',r.id===selected?'true':'false');choose.onclick=()=>{selected=r.id;deadline=null;render(event);};row.append(choose);}
      return row;
    }));
    const connectedPorts=new Set(notice.receivers.map(r=>r.port));
    for(const p of notice.pending_reconnects||[]){if(connectedPorts.has(p.port))continue;const row=document.createElement('div');row.className='usb-notice-row';row.textContent=p.name+' · USB '+p.port+' · Reconnect → '+p.serial;list.append(row);}
    const candidate=notice.receivers.find(r=>r.id===selected&&r.can_assign);
    yes.hidden=!candidate;yes.disabled=pending;cancel.textContent=['conflict','failed'].includes(notice.kind)?'Cancel':'Close';
    hint.textContent=candidate?'Selected: '+candidate.name+' · USB '+candidate.port+'. After saving, reconnect only this receiver. Other ID changes can be queued.':notice.kind==='working'?'New plug-ins remain visible while ID changes finish.':'Leave the hub powered. Reconnect updated receivers individually.';
    const tick=()=>{if(deadline!==null){hint.textContent='Closes automatically in '+Math.max(0,Math.ceil((deadline-Date.now())/1000))+' seconds.';if(Date.now()>=deadline)dismiss();}};
    clearInterval(timer);tick();if(notice.id===last)return;if(deadline!==null)timer=setInterval(tick,250);
    if(!dialog.open){oldFocus=document.activeElement;dialog.showModal();cancel.focus({preventScroll:true});}
  }
  yes.onclick=async()=>{
    if(pending||!event||!selected)return;const approved={action:'assign_id',event:event.id,target:selected};pending=true;yes.disabled=true;error.textContent='';
    try{const r=await fetch('/api/dongle-notice',{method:'POST',headers:{'Content-Type':'application/json','X-USB-Notice-Token':token},body:JSON.stringify(approved)});if(!r.ok)throw Error((await r.json()).error||'Could not assign ID');await refresh();}
    catch(e){error.textContent=e.message;}finally{pending=false;yes.disabled=false;}
  };
  async function refresh(){
    if(document.hidden)return;
    try{const r=await fetch('/api/dongle-notice',{cache:'no-store'});if(!r.ok)return;const state=await r.json();if(!state.available)return;token=state.control_token;
      if(!state.notice){if(dialog.open)dialog.close();event=null;clearInterval(timer);return;}
      if(state.notice.id===last)return;
      render(state.notice);
    }catch{} // An unavailable server must not block receiver controls.
  }
  refresh();setInterval(refresh,1500);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();
