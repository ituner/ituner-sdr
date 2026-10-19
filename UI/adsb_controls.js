import {TrafficView,aged,positioned,freshness} from './adsb_view.js';
import {mountCoverage} from './adsb_coverage.js';
import {ADSBGlobe,startupNoticeVisible,receptionSummary} from './adsb_globe.js';
const $=id=>document.getElementById(id),fmt=(value,digits=0)=>typeof value==='number'?value.toLocaleString(undefined,{maximumFractionDigits:digits}):value==='ground'?'GROUND':'—';
let token='',state=null,editing=false,logKind='flights',selected=null,selectedAt=0,lastCount=null,lastTime=0,logBusy=false,refreshBusy=false,noticeTimer;
const error=message=>{$('error').textContent=message||'';};
const enteredAt=performance.now();let clockOffset=0,clockReady=false,historySeconds=86400;
const viewNow=()=>Date.now()/1000+clockOffset,view=new TrafficView();
let globe;
try {globe=new ADSBGlobe($('globe'),plane=>{if(plane){selected=plane;selectedAt=Date.now();}renderDetails(plane);},error);globe.trafficView=view;globe.trafficNow=viewNow;globe.setStyle('both');globe.trailSeconds=Number($('trails').value);globe.onFollowChange=()=>renderDetails(currentPlane());} catch(e){error('The globe could not start: '+e.message);}
$('usb').onchange=()=>editing=true;
const savedTracks=()=>Object.fromEntries([...(globe?.traces||[])].map(([key,v])=>[key,v.points]));
const shownAircraft=()=>view.aircraft(state?.aircraft||[],savedTracks(),viewNow());
function currentPlane(){return shownAircraft().find(p=>p.hex===selected?.hex)||null;}
function renderReception(){
  if(!state)return;
  const now=viewNow(),startup=startupNoticeVisible(state,now),offline=state.status==='OFFLINE';
  $('map-empty').hidden=!offline&&(view.live(state.aircraft,now).some(positioned)||(state.enabled&&!startup));
  $('map-empty').querySelector('b').textContent=offline?'Receiver offline':state.enabled?'Listening for aircraft':'Receiver stopped';
  $('status').textContent=state.status==='RECEIVING'?'1090 ES · '+receptionSummary(state,now):state.status;
  clearTimeout(noticeTimer);
  if(startup)noticeTimer=setTimeout(renderReception,Math.max(1,(state.started_at+5-now)*1000));
}
function detailField(label,value,unit){const box=document.createElement('div'),small=document.createElement('small'),b=document.createElement('b'),em=document.createElement('em');small.textContent=label;b.textContent=value;em.textContent=unit;box.append(small,b,em);return box;}
function choose(plane){selected=plane;selectedAt=Date.now();if(globe){globe.selected=plane.hex;globe.render();}renderDetails(plane);renderTraffic();}
function renderDetails(live){
  const card=$('plane-card');if(!selected)return;
  const p=aged(live||selected,viewNow()),contact=view.live(state?.aircraft||[],viewNow()).find(row=>row.hex===p.hex);if(contact){p.seen=contact.seen;p.last_seen_at=contact.last_seen_at;p.contact_known=true;}card.classList.add('selected');card.replaceChildren();
  const heading=document.createElement('div');heading.className='plane-id';const title=document.createElement('h3'),source=document.createElement('span');title.textContent=(p.flight||p.hex).trim();source.className='source-tag';source.textContent=p.band==='978'?'978 UAT':'1090 ES';heading.append(title,source);card.append(heading);
  const id=document.createElement('p');id.textContent='ICAO '+p.hex.toUpperCase()+(p.squawk?' · SQUAWK '+p.squawk:'');card.append(id);
  const grid=document.createElement('div');grid.className='instrument-grid';grid.append(detailField('ALTITUDE',fmt(p.alt_baro),'ft'),detailField('GROUND SPEED',fmt(p.gs),'kt'),detailField('HEADING',fmt(p.track),'°'),detailField('VERTICAL RATE',fmt(p.baro_rate),'ft/min'));card.append(grid);
  const position=document.createElement('div');position.className='position-line';
  position.textContent=freshness(p)+(Number.isFinite(p.lat)&&Number.isFinite(p.lon)?`\n${fmt(p.lat,4)}°, ${fmt(p.lon,4)}°`:'')+(contact?`\nRSSI ${fmt(contact.rssi,1)} dBFS`:'');
  card.append(position);const controls=document.createElement('div');controls.className='button-row';
  const follow=document.createElement('button');follow.textContent=globe?.following?'FOLLOWING':'FOLLOW';follow.disabled=!positioned(contact)&&!globe?.following;follow.className=globe?.following?'follow-active':'';follow.onclick=()=>{globe?.followSelected(!globe.following);renderDetails(currentPlane());};
  const center=document.createElement('button');center.textContent='LOCATE';center.disabled=!Number.isFinite(p.lat)||!Number.isFinite(p.lon);center.onclick=()=>globe?.locate(p);
  const clear=document.createElement('button');clear.textContent='CLEAR';clear.onclick=()=>{selected=null;$('follow-banner').hidden=true;if(globe){globe.selected=null;globe.followSelected(false);globe.render();}card.classList.remove('selected');card.replaceChildren();const h=document.createElement('h3');h.textContent='Select an aircraft';card.append(h);renderTraffic();};
  controls.append(follow,center,clear);card.append(controls);
  $('follow-banner').hidden=!globe?.following;$('follow-banner').textContent=(positioned(contact)?'FOLLOWING ':'WAITING FOR ')+(p.flight||p.hex).trim();
}
function renderTraffic(){
  if(!state)return;const query=$('filter').value.trim().toLowerCase(),sort=$('sort').value;
  const planes=shownAircraft().filter(p=>((p.flight||'')+' '+p.hex).toLowerCase().includes(query)).sort((a,b)=>sort==='altitude'?(Number(b.alt_baro)||0)-(Number(a.alt_baro)||0):sort==='callsign'?(a.flight||a.hex).localeCompare(b.flight||b.hex):(a.seen||0)-(b.seen||0));
  const list=$('aircraft-list');list.replaceChildren();$('list-total').textContent=planes.length;$('traffic-empty').hidden=planes.length>0;
  if(!planes.length)$('traffic-empty').firstChild.textContent=query?'No aircraft match your search.':view.mode==='live'?'No live contacts right now.':view.mode==='session'?'No contacts received since this window started.':'No aircraft in this history window.';
  for(const p of planes){const row=document.createElement('button');row.className='aircraft-row'+(p.hex===selected?.hex?' selected':'')+(view.arrival(p.hex,viewNow())?' arrival':'');row.setAttribute('aria-label','Select '+(p.flight||p.hex).trim());const top=document.createElement('div'),bottom=document.createElement('div');top.className='row-top';bottom.className='row-bottom';const title=document.createElement('b'),alt=document.createElement('span');title.textContent=(p.flight||p.hex).trim();alt.textContent=fmt(p.alt_baro)+' ft';top.append(title,alt);for(const text of [p.hex.toUpperCase(),fmt(p.gs)+' kt',positioned(p)?'FRESH POSITION':Number.isFinite(p.position_time)?(p.historical?'SAVED POSITION':'POSITION OLD'):'NO POSITION']){const s=document.createElement('span');s.textContent=text;bottom.append(s);}const fresh=document.createElement('div');fresh.className='freshness-line';fresh.textContent=freshness(p);if(view.arrival(p.hex,viewNow())){const badge=document.createElement('span');badge.className='arrival-tag';badge.textContent='NEW';top.append(badge);}row.append(top,bottom,fresh);row.onclick=()=>choose(p);list.append(row);}
}

function clearSelection(){selected=null;selectedAt=0;$('follow-banner').hidden=true;if(globe){globe.selected=null;globe.followSelected(false);}const card=$('plane-card');card.classList.remove('selected');card.innerHTML='<span class="eyebrow">TARGET DETAILS</span><h3>Select an aircraft</h3><p>Tap a target on the globe or choose one below.</p>';}
function renderView(){
  const now=viewNow(),counts=view.counts(state?.aircraft||[],now);
  $('tracked').textContent=counts.live;$('positioned').textContent=counts.positions;$('new-count').textContent=counts.new;$('traffic-count').textContent=shownAircraft().length;
  $('traffic-view-label').textContent=view.label.toUpperCase()+' TRAFFIC';
  const since=new Date((view.openedAt-clockOffset)*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  $('window-summary').textContent=view.mode==='session'?`Received since ${since} · maximum 24 hours · logs retained`:view.mode==='history'?'Recorded positions · '+(view.trailSeconds?$('trails').selectedOptions[0].textContent.replace('TRAILS · ',''):'trails off')+' · logs retained':'Contact & position fresh within 15s · '+(view.trailSeconds?Math.round(view.trailSeconds/60)+' min trails':'trails off');
}
function setView(mode){
  view.mode=mode;view.trailSeconds=mode==='history'?historySeconds:300;clearSelection();
  for(const button of document.querySelectorAll('[data-traffic-view]'))button.setAttribute('aria-pressed',String(button.dataset.trafficView===mode));
  $('trails').disabled=mode==='session';$('trails').value=mode==='session'?'-1':String(view.trailSeconds);
  $('history-backdrop').disabled=mode==='history';
  if(globe){globe.trailSeconds=view.trailSeconds;globe.render();}renderView();renderTraffic();
}
for(const button of document.querySelectorAll('[data-traffic-view]'))button.onclick=()=>setView(button.dataset.trafficView);
$('start-fresh').onclick=()=>{view.reset(viewNow());view.ingest(state?.aircraft||[],viewNow());setView('session');};
$('history-backdrop').onclick=()=>{view.backdrop=!view.backdrop;$('history-backdrop').setAttribute('aria-pressed',String(view.backdrop));$('history-backdrop').textContent='Past trails '+(view.backdrop?'on':'off');globe?.render();};

async function refresh(){if(refreshBusy)return;refreshBusy=true;try{
  const r=await fetch('/api/state');if(!r.ok)throw Error('Receiver unavailable');state=await r.json();token=state.control_token;if(Number.isFinite(state.now)){clockOffset=state.now-Date.now()/1000;if(!clockReady){view.reset(state.now-(performance.now()-enteredAt)/1000);clockReady=true;}}view.ingest(state.aircraft,viewNow());
  const now=performance.now(),delta=lastCount===null||state.messages<lastCount?0:(state.messages-lastCount)/Math.max(.1,(now-lastTime)/1000);lastCount=state.messages;lastTime=now;
  $('rate').textContent=fmt(delta,1);$('messages').textContent=fmt(state.messages);renderView();
  renderReception();
  $('band1090-status').textContent=state.status;$('source-status').textContent=state.status;
  $('connection').textContent='● CONNECTED';$('last-update').textContent='UPDATED '+new Date().toLocaleTimeString();$('detail').textContent=state.detail;
  const chosen=editing?$('usb').value:state.selection,choices=[{id:'auto',label:'Auto · first available RTL-SDR'},...state.devices];if(!choices.some(d=>d.id===chosen))choices.push({id:chosen,label:'Assigned dongle unavailable'});
  $('usb').replaceChildren(...choices.map(d=>{const o=document.createElement('option');o.value=d.id;o.textContent=d.label;return o;}));$('usb').value=chosen;
  $('start').disabled=state.enabled;$('stop').disabled=!state.enabled;
  $('site-status').textContent=state.receiver_position?`${state.receiver_position.lat.toFixed(5)}°, ${state.receiver_position.lon.toFixed(5)}°`:'Site not configured';
  if(state.receiver_position&&document.activeElement!==$('site-lat')&&document.activeElement!==$('site-lon')&&!$('site-form').dataset.editing){$('site-lat').value=state.receiver_position.lat;$('site-lon').value=state.receiver_position.lon;}
  error('');globe?.update(state);footprintLegend();renderTraffic();if(selected)renderDetails(currentPlane());
  if(!$('logs-panel').hidden)refreshLogs();
}catch(e){error('Receiver connection lost. Retrying…');$('status').textContent='OFFLINE';$('connection').textContent='● DISCONNECTED';if(state){state={...state,status:'OFFLINE',aircraft:[]};renderTraffic();renderReception();}$('positioned').textContent='0';$('tracked').textContent='0';$('traffic-count').textContent='0';$('map-empty').hidden=false;$('map-empty').querySelector('b').textContent='Receiver offline';globe?.update({aircraft:[]});if(selected)renderDetails(null);}finally{refreshBusy=false;}}
async function control(action,extra={}){try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':token},body:JSON.stringify({action,selection:$('usb').value,...extra})});const result=await r.json();if(!r.ok)throw Error(result.error);editing=false;await refresh();}catch(e){error(e.message);}}
for(const action of ['assign','start','stop','scan'])$(action).onclick=()=>control(action);
$('site-form').onsubmit=e=>{e.preventDefault();location.href='/settings#location';};

function showDrawer(kind,show){const node=$(kind+'-panel');node.hidden=!show;$(kind).setAttribute('aria-expanded',String(show));if(show){const other=kind==='logs'?'receiver':'logs';$(other+'-panel').hidden=true;$(other).setAttribute('aria-expanded','false');if(kind==='logs')refreshLogs();}}
for(const kind of ['logs','receiver']){$(kind).onclick=()=>showDrawer(kind,$(kind+'-panel').hidden);$('close-'+kind).onclick=()=>showDrawer(kind,false);}
$('band1090').onclick=$('band978').onclick=()=>showDrawer('receiver',true);
function trafficVisible(show){$('traffic-panel').hidden=!show;$('traffic-toggle').setAttribute('aria-expanded',String(show));$('traffic-toggle').classList.toggle('active',show);}
$('traffic-toggle').onclick=()=>trafficVisible($('traffic-panel').hidden);if(matchMedia('(max-width:720px)').matches)trafficVisible(false);
$('filter').oninput=$('sort').onchange=renderTraffic;
$('zoom-in').onclick=()=>globe?.zoom(1.6);$('zoom-out').onclick=()=>globe?.zoom(1/1.6);$('center').onclick=()=>globe?.fitTraffic();$('map-style').onchange=e=>globe?.setStyle(e.target.value);
$('trails').onchange=e=>{view.trailSeconds=Number(e.target.value);if(view.mode==='history')historySeconds=view.trailSeconds;if(globe){globe.trailSeconds=view.trailSeconds;globe.render();}renderView();};$('labels').onclick=()=>{if(!globe)return;globe.labels=!globe.labels;$('labels').textContent=globe.labels?'LABELS ON':'LABELS OFF';$('labels').setAttribute('aria-pressed',String(globe.labels));globe.render();};
$('rings').onclick=()=>{if(!globe)return;if(!state?.receiver_position){showDrawer('receiver',true);error('Set the antenna position to enable range rings.');return;}globe.rings=!globe.rings;$('rings').setAttribute('aria-pressed',String(globe.rings));globe.render();};
async function refreshLogs(){if(logBusy)return;logBusy=true;try{const requested=logKind,r=await fetch('/api/logs?kind='+requested);if(!r.ok)throw Error('Could not load log');const data=await r.json();if(requested!==logKind)return;const node=$('logs-content'),scroll=node.scrollTop;node.replaceChildren();
  if(!data.entries.length){const p=document.createElement('p');p.textContent=requested==='flights'?'No decoded aircraft observations yet. Receiver and Diagnostics show radio activity.':'No entries in this log yet.';node.append(p);}
  else if(requested==='flights'){const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');for(const text of ['TIME','CALLSIGN','ICAO','ALTITUDE','SPEED','POSITION','BAND']){const th=document.createElement('th');th.textContent=text;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');for(const item of [...data.entries].reverse()){const p=item.aircraft||{},row=document.createElement('tr');const values=[new Date(item.time*1000).toLocaleString(),(p.flight||'—').trim(),p.hex?.toUpperCase()||'—',fmt(p.alt_baro)+' ft',fmt(p.gs)+' kt',Number.isFinite(p.lat)&&Number.isFinite(p.lon)?p.lat.toFixed(4)+', '+p.lon.toFixed(4):'No position',p.band||'1090 ES'];for(const text of values){const td=document.createElement('td');td.textContent=text;row.append(td);}body.append(row);}table.append(body);node.append(table);}
  else{const pre=document.createElement('pre');if(requested==='diagnostics')pre.textContent=data.lines.join('\n');else pre.textContent=[...data.entries].reverse().map(item=>new Date(item.time*1000).toLocaleString()+'  '+String(item.event||'event').toUpperCase()+'\n'+(item.detail||item.device?.label||item.selection||'')).join('\n\n');node.append(pre);}node.scrollTop=scroll;
}catch(e){$('logs-content').textContent=e.message;}finally{logBusy=false;}}
for(const button of document.querySelectorAll('[data-log]'))button.onclick=()=>{logKind=button.dataset.log;document.querySelector('.log-note').textContent=logKind==='diagnostics'?'Receiver output · UTC timestamps · live updates':'Latest 160 entries · live updates · local time';for(const tab of document.querySelectorAll('[data-log]'))tab.setAttribute('aria-selected',String(tab===button));$('download').href='/api/log?kind='+logKind;$('download').download='adsb-'+logKind+(logKind==='diagnostics'?'.txt':'.jsonl');$('logs-content').scrollTop=0;refreshLogs();};
async function tracks(){try{const r=await fetch('/api/tracks');if(r.ok&&globe){globe.setTracks(await r.json());renderTraffic();}}catch{}}
function clock(){$('utc').textContent=new Date().toISOString().slice(11,19)+' UTC';renderReception();if(state){renderView();renderTraffic();if(selected)renderDetails(currentPlane());globe?.render();}}clock();setInterval(clock,1000);refresh();setInterval(refresh,2500);tracks();setInterval(tracks,5000);
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='Escape'){showDrawer('logs',false);showDrawer('receiver',false);}else if(e.key==='+')globe?.zoom(1.6);else if(e.key==='-')globe?.zoom(1/1.6);else if(e.key.toLowerCase()==='f'&&selected)globe?.followSelected(!globe.following);else if(e.key.toLowerCase()==='l')showDrawer('logs',$('logs-panel').hidden);});

const observatoryLink=document.getElementById('observatory-link');if(observatoryLink)observatoryLink.href=`http://${location.hostname}:8092/`;

let footprintBusy=false;
function footprintLegend(){if(globe){$('rx-footprint').setAttribute('aria-pressed',String(globe.footprintEnabled));$('footprint-legend').hidden=!globe.footprintRegions().length;}}
async function refreshFootprint(){
  if(footprintBusy||!globe||!globe.footprintEnabled)return;footprintBusy=true;
  try{const r=await fetch('/api/footprint',{signal:AbortSignal.timeout(10000)});if(r.ok){const data=await r.json();if(data.status==='LOADING')setTimeout(refreshFootprint,1200);else{globe.setFootprint(data.footprint);footprintLegend();}}}catch{}finally{footprintBusy=false;}
}
$('rx-footprint').onclick=()=>{if(!globe)return;globe.footprintEnabled=!globe.footprintEnabled;globe.save();footprintLegend();globe.render();if(globe.footprintEnabled)refreshFootprint();};
footprintLegend();refreshFootprint();setInterval(refreshFootprint,10000);
const reloadCoverage=mountCoverage($('coverage-panel'));
function coverageVisible(show){document.body.classList.toggle('coverage-open',show);$('coverage-panel').hidden=!show;$('coverage').setAttribute('aria-expanded',String(show));if(show){history.replaceState(null,'',location.pathname+'#coverage');showDrawer('logs',false);showDrawer('receiver',false);reloadCoverage();}if(location.hash==='#coverage'&&!show)history.replaceState(null,'',location.pathname);}
$('coverage').onclick=()=>coverageVisible($('coverage-panel').hidden);$('close-coverage').onclick=()=>coverageVisible(false);
$('traffic-toggle').addEventListener('click',()=>coverageVisible(false));
document.addEventListener('keydown',e=>{if(e.key==='Escape')coverageVisible(false);});
if(location.hash==='#coverage')coverageVisible(true);
