import {ADSBGlobe,startupNoticeVisible,receptionSummary} from './adsb_globe.js';
const $=id=>document.getElementById(id),fmt=(value,digits=0)=>typeof value==='number'?value.toLocaleString(undefined,{maximumFractionDigits:digits}):value==='ground'?'GROUND':'—';
let token='',state=null,editing=false,logKind='flights',selected=null,selectedAt=0,lastCount=null,lastTime=0,logBusy=false,refreshBusy=false,noticeTimer;
const error=message=>{$('error').textContent=message||'';};
let globe;
try {globe=new ADSBGlobe($('globe'),plane=>{if(plane){selected=plane;selectedAt=Date.now();}renderDetails(plane);},error);globe.setStyle('both');globe.trailSeconds=Number($('trails').value);globe.onFollowChange=()=>renderDetails(currentPlane());} catch(e){error('The globe could not start: '+e.message);}
$('usb').onchange=()=>editing=true;
const positioned=p=>Number.isFinite(p?.lat)&&Number.isFinite(p?.lon)&&(p.seen_pos??100)<15;
function currentPlane(){return state?.aircraft.find(p=>p.hex===selected?.hex)||null;}
function renderReception(){
  if(!state)return;
  const now=Date.now()/1000,startup=startupNoticeVisible(state,now),offline=state.status==='OFFLINE';
  $('map-empty').hidden=!offline&&(state.aircraft.some(positioned)||(state.enabled&&!startup));
  $('map-empty').querySelector('b').textContent=offline?'Receiver offline':state.enabled?'Listening for aircraft':'Receiver stopped';
  $('status').textContent=state.status==='RECEIVING'?'1090 ES · '+receptionSummary(state,now):state.status;
  clearTimeout(noticeTimer);
  if(startup)noticeTimer=setTimeout(renderReception,Math.max(1,(state.started_at+5-now)*1000));
}
function detailField(label,value,unit){const box=document.createElement('div'),small=document.createElement('small'),b=document.createElement('b'),em=document.createElement('em');small.textContent=label;b.textContent=value;em.textContent=unit;box.append(small,b,em);return box;}
function choose(plane){selected=plane;selectedAt=Date.now();if(globe){globe.selected=plane.hex;globe.render();}renderDetails(plane);renderTraffic();}
function renderDetails(live){
  const card=$('plane-card');if(!selected)return;
  const p=live||selected;card.classList.add('selected');card.replaceChildren();
  const heading=document.createElement('div');heading.className='plane-id';const title=document.createElement('h3'),source=document.createElement('span');title.textContent=(p.flight||p.hex).trim();source.className='source-tag';source.textContent=p.band==='978'?'978 UAT':'1090 ES';heading.append(title,source);card.append(heading);
  const id=document.createElement('p');id.textContent='ICAO '+p.hex.toUpperCase()+(p.squawk?' · SQUAWK '+p.squawk:'');card.append(id);
  const grid=document.createElement('div');grid.className='instrument-grid';grid.append(detailField('ALTITUDE',fmt(p.alt_baro),'ft'),detailField('GROUND SPEED',fmt(p.gs),'kt'),detailField('HEADING',fmt(p.track),'°'),detailField('VERTICAL RATE',fmt(p.baro_rate),'ft/min'));card.append(grid);
  const position=document.createElement('div');position.className='position-line';
  position.textContent=positioned(live)?`${fmt(p.lat,4)}°, ${fmt(p.lon,4)}°\nRSSI ${fmt(p.rssi,1)} dBFS · seen ${fmt(p.seen,1)}s ago`:live?'Position unavailable · radio contact active':`Signal lost · last contact ${Math.floor((Date.now()-selectedAt)/1000+(p.seen||0))}s ago`;
  card.append(position);const controls=document.createElement('div');controls.className='button-row';
  const follow=document.createElement('button');follow.textContent=globe?.following?'FOLLOWING':'FOLLOW';follow.disabled=!positioned(live)&&!globe?.following;follow.className=globe?.following?'follow-active':'';follow.onclick=()=>{globe?.followSelected(!globe.following);renderDetails(currentPlane());};
  const center=document.createElement('button');center.textContent='LOCATE';center.disabled=!positioned(live);center.onclick=()=>globe?.locate(live);
  const clear=document.createElement('button');clear.textContent='CLEAR';clear.onclick=()=>{selected=null;$('follow-banner').hidden=true;if(globe){globe.selected=null;globe.followSelected(false);globe.render();}card.classList.remove('selected');card.replaceChildren();const h=document.createElement('h3');h.textContent='Select an aircraft';card.append(h);renderTraffic();};
  controls.append(follow,center,clear);card.append(controls);
  $('follow-banner').hidden=!globe?.following;$('follow-banner').textContent=(positioned(live)?'FOLLOWING ':'WAITING FOR ')+(p.flight||p.hex).trim();
}
function renderTraffic(){
  if(!state)return;const query=$('filter').value.trim().toLowerCase(),sort=$('sort').value;
  const planes=state.aircraft.filter(p=>((p.flight||'')+' '+p.hex).toLowerCase().includes(query)).sort((a,b)=>sort==='altitude'?(Number(b.alt_baro)||0)-(Number(a.alt_baro)||0):sort==='callsign'?(a.flight||a.hex).localeCompare(b.flight||b.hex):(a.seen||0)-(b.seen||0));
  const list=$('aircraft-list');list.replaceChildren();$('list-total').textContent=planes.length;$('traffic-empty').hidden=planes.length>0;
  if(!planes.length)$('traffic-empty').firstChild.textContent=query?'No aircraft match your search.':'No aircraft tracked right now.';
  for(const p of planes){const row=document.createElement('button');row.className='aircraft-row'+(p.hex===selected?.hex?' selected':'');row.setAttribute('aria-label','Select '+(p.flight||p.hex).trim());const top=document.createElement('div'),bottom=document.createElement('div');top.className='row-top';bottom.className='row-bottom';const title=document.createElement('b'),alt=document.createElement('span');title.textContent=(p.flight||p.hex).trim();alt.textContent=fmt(p.alt_baro)+' ft';top.append(title,alt);for(const text of [p.hex.toUpperCase(),fmt(p.gs)+' kt',positioned(p)?'POSITION':'NO POSITION']){const s=document.createElement('span');s.textContent=text;bottom.append(s);}row.append(top,bottom);row.onclick=()=>choose(p);list.append(row);}
}
async function refresh(){if(refreshBusy)return;refreshBusy=true;try{
  const r=await fetch('/api/state');if(!r.ok)throw Error('Receiver unavailable');state=await r.json();token=state.control_token;
  const now=performance.now(),delta=lastCount===null||state.messages<lastCount?0:(state.messages-lastCount)/Math.max(.1,(now-lastTime)/1000);lastCount=state.messages;lastTime=now;
  $('rate').textContent=fmt(delta,1);$('messages').textContent=fmt(state.messages);$('tracked').textContent=state.aircraft.length;$('positioned').textContent=state.aircraft.filter(positioned).length;$('traffic-count').textContent=state.aircraft.length;
  renderReception();
  $('band1090-status').textContent=state.status;$('source-status').textContent=state.status;
  $('connection').textContent='● CONNECTED';$('last-update').textContent='UPDATED '+new Date().toLocaleTimeString();$('detail').textContent=state.detail;
  const chosen=editing?$('usb').value:state.selection,choices=[{id:'auto',label:'Auto · first available RTL-SDR'},...state.devices];if(!choices.some(d=>d.id===chosen))choices.push({id:chosen,label:'Assigned dongle unavailable'});
  $('usb').replaceChildren(...choices.map(d=>{const o=document.createElement('option');o.value=d.id;o.textContent=d.label;return o;}));$('usb').value=chosen;
  $('start').disabled=state.enabled;$('stop').disabled=!state.enabled;
  $('site-status').textContent=state.receiver_position?`${state.receiver_position.lat.toFixed(5)}°, ${state.receiver_position.lon.toFixed(5)}°`:'Site not configured';
  if(state.receiver_position&&document.activeElement!==$('site-lat')&&document.activeElement!==$('site-lon')&&!$('site-form').dataset.editing){$('site-lat').value=state.receiver_position.lat;$('site-lon').value=state.receiver_position.lon;}
  error('');globe?.update(state);renderTraffic();if(selected)renderDetails(currentPlane());
  if(!$('logs-panel').hidden)refreshLogs();
}catch(e){error('Receiver connection lost. Retrying…');$('status').textContent='OFFLINE';$('connection').textContent='● DISCONNECTED';if(state){state={...state,status:'OFFLINE',aircraft:[]};renderTraffic();renderReception();}$('positioned').textContent='0';$('tracked').textContent='0';$('traffic-count').textContent='0';$('map-empty').hidden=false;$('map-empty').querySelector('b').textContent='Receiver offline';globe?.update({aircraft:[]});if(selected)renderDetails(null);}finally{refreshBusy=false;}}
async function control(action,extra={}){try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':token},body:JSON.stringify({action,selection:$('usb').value,...extra})});const result=await r.json();if(!r.ok)throw Error(result.error);editing=false;await refresh();}catch(e){error(e.message);}}
for(const action of ['assign','start','stop','scan'])$(action).onclick=()=>control(action);
$('site-form').oninput=()=>{$('site-form').dataset.editing='true';};$('site-form').onsubmit=async e=>{e.preventDefault();await control('location',{position:{lat:Number($('site-lat').value),lon:Number($('site-lon').value)}});delete $('site-form').dataset.editing;};$('clear-site').onclick=async()=>{await control('location',{position:null});$('site-lat').value='';$('site-lon').value='';};
function showDrawer(kind,show){const node=$(kind+'-panel');node.hidden=!show;$(kind).setAttribute('aria-expanded',String(show));if(show){const other=kind==='logs'?'receiver':'logs';$(other+'-panel').hidden=true;$(other).setAttribute('aria-expanded','false');if(kind==='logs')refreshLogs();}}
for(const kind of ['logs','receiver']){$(kind).onclick=()=>showDrawer(kind,$(kind+'-panel').hidden);$('close-'+kind).onclick=()=>showDrawer(kind,false);}
$('band1090').onclick=$('band978').onclick=()=>showDrawer('receiver',true);
function trafficVisible(show){$('traffic-panel').hidden=!show;$('traffic-toggle').setAttribute('aria-expanded',String(show));$('traffic-toggle').classList.toggle('active',show);}
$('traffic-toggle').onclick=()=>trafficVisible($('traffic-panel').hidden);if(matchMedia('(max-width:720px)').matches)trafficVisible(false);
$('filter').oninput=$('sort').onchange=renderTraffic;
$('zoom-in').onclick=()=>globe?.zoom(1.6);$('zoom-out').onclick=()=>globe?.zoom(1/1.6);$('center').onclick=()=>globe?.fitTraffic();$('map-style').onchange=e=>globe?.setStyle(e.target.value);
$('trails').onchange=e=>{if(globe){globe.trailSeconds=Number(e.target.value);globe.render();}};$('labels').onclick=()=>{if(!globe)return;globe.labels=!globe.labels;$('labels').textContent=globe.labels?'LABELS ON':'LABELS OFF';$('labels').setAttribute('aria-pressed',String(globe.labels));globe.render();};
$('rings').onclick=()=>{if(!globe)return;if(!state?.receiver_position){showDrawer('receiver',true);error('Set the antenna position to enable range rings.');return;}globe.rings=!globe.rings;$('rings').setAttribute('aria-pressed',String(globe.rings));globe.render();};
async function refreshLogs(){if(logBusy)return;logBusy=true;try{const requested=logKind,r=await fetch('/api/logs?kind='+requested);if(!r.ok)throw Error('Could not load log');const data=await r.json();if(requested!==logKind)return;const node=$('logs-content'),scroll=node.scrollTop;node.replaceChildren();
  if(!data.entries.length){const p=document.createElement('p');p.textContent=requested==='flights'?'No decoded aircraft observations yet. Receiver and Diagnostics show radio activity.':'No entries in this log yet.';node.append(p);}
  else if(requested==='flights'){const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');for(const text of ['TIME','CALLSIGN','ICAO','ALTITUDE','SPEED','POSITION','BAND']){const th=document.createElement('th');th.textContent=text;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');for(const item of [...data.entries].reverse()){const p=item.aircraft||{},row=document.createElement('tr');const values=[new Date(item.time*1000).toLocaleString(),(p.flight||'—').trim(),p.hex?.toUpperCase()||'—',fmt(p.alt_baro)+' ft',fmt(p.gs)+' kt',Number.isFinite(p.lat)&&Number.isFinite(p.lon)?p.lat.toFixed(4)+', '+p.lon.toFixed(4):'No position',p.band||'1090 ES'];for(const text of values){const td=document.createElement('td');td.textContent=text;row.append(td);}body.append(row);}table.append(body);node.append(table);}
  else{const pre=document.createElement('pre');if(requested==='diagnostics')pre.textContent=data.lines.join('\n');else pre.textContent=[...data.entries].reverse().map(item=>new Date(item.time*1000).toLocaleString()+'  '+String(item.event||'event').toUpperCase()+'\n'+(item.detail||item.device?.label||item.selection||'')).join('\n\n');node.append(pre);}node.scrollTop=scroll;
}catch(e){$('logs-content').textContent=e.message;}finally{logBusy=false;}}
for(const button of document.querySelectorAll('[data-log]'))button.onclick=()=>{logKind=button.dataset.log;document.querySelector('.log-note').textContent=logKind==='diagnostics'?'Receiver output · UTC timestamps · live updates':'Latest 160 entries · live updates · local time';for(const tab of document.querySelectorAll('[data-log]'))tab.setAttribute('aria-selected',String(tab===button));$('download').href='/api/log?kind='+logKind;$('download').download='adsb-'+logKind+(logKind==='diagnostics'?'.txt':'.jsonl');$('logs-content').scrollTop=0;refreshLogs();};
async function tracks(){try{const r=await fetch('/api/tracks');if(r.ok&&globe)globe.setTracks(await r.json());}catch{}}
function clock(){$('utc').textContent=new Date().toISOString().slice(11,19)+' UTC';renderReception();}clock();setInterval(clock,1000);refresh();setInterval(refresh,2500);tracks();setInterval(tracks,5000);
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='Escape'){showDrawer('logs',false);showDrawer('receiver',false);}else if(e.key==='+')globe?.zoom(1.6);else if(e.key==='-')globe?.zoom(1/1.6);else if(e.key.toLowerCase()==='f'&&selected)globe?.followSelected(!globe.following);else if(e.key.toLowerCase()==='l')showDrawer('logs',$('logs-panel').hidden);});

const observatoryLink=document.getElementById('observatory-link');if(observatoryLink)observatoryLink.href=`http://${location.hostname}:8092/`;
