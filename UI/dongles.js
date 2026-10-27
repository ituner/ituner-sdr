'use strict';
const $=id=>document.getElementById(id);let state=null,selected=null,pending=false,notice='',historyList=false,page=0;
function el(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
function status(message){$('status').textContent=message;}
async function call(data){pending=true;notice='';try{const r=await fetch('/api/dongles',{method:'POST',headers:{'Content-Type':'application/json','X-Dongle-Token':state.control_token},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error||'Receiver operation failed');state=result;render();return true;}catch(e){notice=e.message;status(notice);return false;}finally{pending=false;}}
function rename(r){selected=r;selected.action='rename';$('rename-title').textContent=r.name||r.nickname||r.product||'Rename receiver';$('identity').textContent='ID '+(r.serial||'unreadable')+' · USB '+(r.device?.usb_path||r.usb_path||'unknown');$('nickname').value=r.nickname||'';$('rename-help').textContent='This optional name is shared across all decoder lists.';$('dialog-status').textContent=r.needs_reconnect?'New ID '+r.eeprom.serial+' saved. Reconnect this radio to load it.':'';$('assign-id').hidden=!(r.connected&&!r.needs_reconnect&&(r.duplicate||['00000000','00000001'].includes(r.serial)));$('save-name').textContent='Save nickname';$('save-name').disabled=false;$('rename').showModal();}
function render(){
 const all=state.dongles,rows=all.filter(r=>historyList||r.connected),pages=Math.max(1,Math.ceil(rows.length/6));page=Math.min(page,pages-1);
 $('summary').textContent=(state.connected_count??all.filter(r=>r.connected).length)+' connected · '+(state.active_count||0)+' in use · shared across decoders';$('connected').setAttribute('aria-pressed',String(!historyList));$('saved').setAttribute('aria-pressed',String(historyList));
 const list=$('list');list.replaceChildren();
 for(const r of rows.slice(page*6,page*6+6)){
  const c=r.connection,line=el('article','','radio-row'+(c?' active':'')+(!r.connected?' offline':'')+(['conflict','reconnect'].includes(r.state)?' warning':''));
  const radio=el('button','','radio-node');radio.type='button';radio.append(el('strong',r.name||r.nickname||r.product||'RTL-SDR'),el('small','ID '+(r.serial||'Unreadable')));radio.onclick=()=>rename(r);
  const wire=el('div','','wire');wire.setAttribute('aria-hidden','true');const decoder=el('div','','decoder-node');
  decoder.append(el('strong',c?.label||({disconnected:'Disconnected',conflict:'ID conflict · select to fix',reconnect:'Reconnect to load new ID'}[r.state])||'Available'),el('small',c?[c.detail,c.status].filter(Boolean).join(' · '):r.waiting?.length?'Waiting: '+r.waiting.join(', '):'USB '+(r.usb_path||'unknown')));line.append(radio,wire,decoder);list.append(line);
 }
 if(!rows.length)list.append(el('p','No USB radios connected. Plug in a receiver; this list updates automatically.'));
 $('page').textContent=rows.length+' radios'+(pages>1?' · '+(page+1)+' / '+pages:'');$('previous').hidden=$('next').hidden=pages===1;$('previous').disabled=page===0;$('next').disabled=page===pages-1;
 if(notice)status(notice);else if(state.operation?.running)status(state.operation.message);else status('');
 if(selected&&$('rename').open){const r=all.find(r=>r.id===selected.id);if(r?.needs_reconnect){$('dialog-status').textContent='New ID '+r.eeprom.serial+' saved. Reconnect only this receiver.';$('assign-id').hidden=true;}}
}
$('connected').onclick=()=>{historyList=false;page=0;render();};$('saved').onclick=()=>{historyList=true;page=0;render();};$('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
$('assign-id').onclick=()=>{selected.action='assign_id';$('rename-title').textContent='Assign a new USB ID?';$('rename-help').textContent='An unused ID is generated for this radio. Reception pauses briefly; reconnect this receiver afterward. A sole factory ID can be kept.';$('save-name').textContent='Yes, assign new ID';$('assign-id').hidden=true;};
async function refresh(){if(pending||document.hidden)return;try{const r=await fetch('/api/usb-radios',{cache:'no-store'});if(!r.ok)throw Error('USB receiver service unavailable');state=await r.json();render();}catch(e){status(e.message);}}
$('scan').onclick=()=>call({action:'scan'});$('cancel').onclick=()=>$('rename').close();$('rename-form').onsubmit=async e=>{e.preventDefault();if(await call({action:selected.action,id:selected.id,nickname:$('nickname').value})){$('rename').close();notice=selected.action==='rename'?'Nickname saved.':'Assigning new ID…';status(notice);}else $('dialog-status').textContent=notice;};
try{const from=new URL(document.referrer);if(from.hostname===location.hostname&&from.protocol===location.protocol)$('back').href=from.href;}catch{}
refresh();setInterval(refresh,2000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
