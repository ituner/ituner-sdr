import {TrafficView,CoverageWindow,COVERAGE_WINDOWS,aged,positioned,freshness} from './adsb_view.js';
import {bandReadings} from './adsb_bands.js';
import {mountCoverage} from './adsb_coverage.js';
import {ADSBGlobe,startupNoticeVisible,receptionSummary} from './adsb_globe.js';
const $=id=>document.getElementById(id),fmt=(value,digits=0)=>typeof value==='number'?value.toLocaleString(undefined,{maximumFractionDigits:digits}):value==='ground'?'GROUND':'—';
let token='',state=null,editing=false,logKind='flights',selected=null,selectedAt=0,lastCount=null,lastTime=0,logBusy=false,refreshBusy=false,noticeTimer,windowNoticeKey='',windowNoticeTimer;
const error=message=>{$('error').textContent=message||'';};
const enteredAt=performance.now();let clockOffset=0,clockReady=false,historySeconds=7776000;
const viewNow=()=>Date.now()/1000+clockOffset,view=new TrafficView();
let globe,uatEditing=false;
try {globe=new ADSBGlobe($('globe'),plane=>{if(plane){selected=plane;selectedAt=Date.now();}renderDetails(plane);},error);globe.trafficView=view;globe.trafficNow=viewNow;globe.setStyle('both');globe.trailSeconds=Number($('trails').value);globe.onFollowChange=()=>renderDetails(currentPlane());} catch(e){error('The globe could not start: '+e.message);}
$('usb').onchange=()=>{editing=true;control('assign');};
$('uat-usb').onchange=()=>{uatEditing=true;control('assign',{band:'978'});};
const savedTracks=()=>Object.fromEntries([...(globe?.traces||[])].map(([key,v])=>[key,v.points]));
const shownAircraft=()=>view.aircraft(state?.aircraft||[],savedTracks(),viewNow());
function currentPlane(){return shownAircraft().find(p=>p.hex===selected?.hex)||null;}
function renderBands(){
  if(!state)return;
  for(const band of bandReadings(state,viewNow())){const row=$('live-band-'+band.id);row.dataset.tone=band.tone;row.querySelector('[data-band-state]').textContent=band.status;row.querySelector('[data-band-details]').textContent=band.details;}
}
function renderReception(){
  if(!state)return;
  renderBands();
  const now=viewNow(),startup=startupNoticeVisible(state,now),offline=state.status==='OFFLINE';
  $('map-empty').hidden=!offline&&(view.live(state.aircraft,now).some(positioned)||(state.enabled&&!startup));
  $('map-empty').querySelector('b').textContent=offline?'Receiver offline':state.enabled?'Listening for aircraft':'Receiver stopped';
  $('status').textContent=state.status==='RECEIVING'?receptionSummary(state,now):state.status;
  if(view.mode==='history')$('map-empty').hidden=true;
  clearTimeout(noticeTimer);
  if(startup)noticeTimer=setTimeout(renderReception,Math.max(1,(state.started_at+5-now)*1000));
}
function detailField(label,value,unit){const box=document.createElement('div'),small=document.createElement('small'),b=document.createElement('b'),em=document.createElement('em');small.textContent=label;b.textContent=value;em.textContent=unit;box.append(small,b,em);return box;}
function choose(plane){selected=plane;selectedAt=Date.now();if(globe){globe.selected=plane.hex;globe.render();}renderDetails(plane);renderTraffic();trafficVisible(false);closeViewOptions();}
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
  const clear=document.createElement('button');clear.textContent='CLEAR';clear.onclick=()=>{clearSelection();renderTraffic();globe?.render();};
  controls.append(follow,center,clear);card.append(controls);
  $('follow-banner').hidden=!globe?.following;$('follow-banner').textContent=(positioned(contact)?'FOLLOWING ':'WAITING FOR ')+(p.flight||p.hex).trim();
  requestAnimationFrame(clampAircraftPanel);
}
function renderTraffic(){
  if(!state||$('traffic-panel').hidden)return;const query=$('filter').value.trim().toLowerCase(),sort=$('sort').value;
  const planes=shownAircraft().filter(p=>((p.flight||'')+' '+p.hex).toLowerCase().includes(query)).sort((a,b)=>sort==='altitude'?(Number(b.alt_baro)||0)-(Number(a.alt_baro)||0):sort==='callsign'?(a.flight||a.hex).localeCompare(b.flight||b.hex):(a.seen||0)-(b.seen||0));
  const list=$('aircraft-list');list.replaceChildren();$('list-total').textContent=planes.length;$('traffic-empty').hidden=planes.length>0;
  $('traffic-empty').lastElementChild.textContent=view.mode==='history'?'Aircraft trails are kept for 24 hours.':'Last known positions stay for '+view.liveLabel+'. Fresh radio contacts use 15 seconds.';
  if(!planes.length)$('traffic-empty').firstChild.textContent=query?'No aircraft match your search.':view.mode==='live'?'No live contacts right now.':view.mode==='session'?'No contacts received since this window started.':'No aircraft in this history window.';
  for(const p of planes){const row=document.createElement('button');row.className='aircraft-row'+(p.hex===selected?.hex?' selected':'')+(view.arrival(p.hex,viewNow())?' arrival':'');row.setAttribute('aria-label','Select '+(p.flight||p.hex).trim());const top=document.createElement('div'),bottom=document.createElement('div');top.className='row-top';bottom.className='row-bottom';const title=document.createElement('b'),alt=document.createElement('span');title.textContent=(p.flight||p.hex).trim();alt.textContent=fmt(p.alt_baro)+' ft';top.append(title,alt);for(const text of [p.hex.toUpperCase(),p.band==='978'?'978 UAT':'1090 ES',fmt(p.gs)+' kt',positioned(p)?'FRESH POSITION':Number.isFinite(p.position_time)?(p.historical?'SAVED POSITION':'POSITION OLD'):'NO POSITION']){const s=document.createElement('span');s.textContent=text;bottom.append(s);}const fresh=document.createElement('div');fresh.className='freshness-line';fresh.textContent=freshness(p);if(view.arrival(p.hex,viewNow())){const badge=document.createElement('span');badge.className='arrival-tag';badge.textContent='NEW';top.append(badge);}row.append(top,bottom,fresh);row.onclick=()=>choose(p);list.append(row);}
}

function clearSelection(){selected=null;selectedAt=0;$('follow-banner').hidden=true;if(globe){globe.selected=null;globe.followSelected(false);}const card=$('plane-card');card.classList.remove('selected');card.innerHTML='<h3>Select an aircraft</h3><p>Tap a plane on the map to inspect it.</p>';}
function renderView(){
  const now=viewNow(),counts=view.counts(state?.aircraft||[],now,savedTracks());
  $('tracked').textContent=counts.live;$('positioned').textContent=counts.positions;$('new-count').textContent=counts.new;$('traffic-count').textContent=shownAircraft().length;
  $('traffic-view-label').textContent=view.label.toUpperCase()+' TRAFFIC';
  const since=new Date((view.openedAt-clockOffset)*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  const historyLabel=[...$('trails').options].find(o=>Number(o.value)===historySeconds)?.textContent||'All recorded';
  const windowLabel=view.mode==='history'?'HISTORY · '+historyLabel+(!view.historyTrails?' · trails off':historySeconds>86400?' · trails up to 24 h':''):'LIVE · LAST 5 MIN'+(view.freshAt!==null?' · SINCE '+new Date((view.freshAt-clockOffset)*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'');
  const noticeKey=[view.mode,view.freshAt,view.trailSeconds,historySeconds,view.liveSeconds,view.historyTrails].join(':');
  $('history-trails').textContent='History dots & trails '+(view.historyTrails?'on':'off');$('history-trails').setAttribute('aria-pressed',String(view.historyTrails));
  const labels=view.labelsVisible(globe?.labels??true);$('labels').textContent='Labels '+(labels?'on':'off');$('labels').setAttribute('aria-pressed',String(labels));
  const icons=view.iconsVisible(globe?.aircraftIcons??true);$('aircraft-icons').textContent='Aircraft icons '+(icons?'on':'off');$('aircraft-icons').setAttribute('aria-pressed',String(icons));
  $('window-summary').textContent=windowLabel+(view.mode==='live'?' · keep positions '+view.liveLabel:'');
  for(const button of document.querySelectorAll('[data-traffic-view="live"]')){const dome=$('coverage-panel').contains(button);button.textContent=dome?'Live':'Live · '+view.liveLabel;button.title=dome?'Accumulate new reception without expiring earlier dome observations.':'Tap again to cycle aircraft visibility: 15 s, 30 s, 1 min, 2 min, 5 min. Older positions show their age.';}
  if(noticeKey!==windowNoticeKey){windowNoticeKey=noticeKey;$('window-summary').hidden=false;clearTimeout(windowNoticeTimer);windowNoticeTimer=setTimeout(()=>{$('window-summary').hidden=true;},5000);}
  for(const label of document.querySelectorAll('[data-window-label]'))label.textContent=$('coverage-panel').contains(label)&&view.mode!=='history'?'LIVE · ACCUMULATING':windowLabel;

}
function setView(mode){
  if(mode!=='live')view.liveArmed=false;
  view.mode=mode;view.trailSeconds=mode==='history'?Math.min(historySeconds,86400):300;view.coverageSeconds=mode==='history'?historySeconds:300;clearSelection();
  for(const button of document.querySelectorAll('[data-traffic-view]'))button.setAttribute('aria-pressed',String(button.dataset.trafficView===mode));
  $('trails').value=String(historySeconds);view.backdrop=false;
  if(globe){globe.trailSeconds=view.trailSeconds;globe.render();}renderView();renderTraffic();renderReception();refreshFootprint();reloadCoverage();
}
for(const button of document.querySelectorAll('[data-traffic-view]'))button.onclick=()=>{const mode=button.dataset.trafficView;if(mode!=='live'){setView(mode);return;}const previous=view.mode;view.pressLive();if(previous!=='live')setView('live');else{renderView();renderTraffic();globe?.render();}};
$('start-fresh').onclick=()=>{view.startFresh(viewNow());$('view-options').open=false;setView('live');};

async function refresh(){if(refreshBusy)return;refreshBusy=true;try{
  const r=await fetch('/api/state');if(!r.ok)throw Error('Receiver unavailable');state=await r.json();token=state.control_token;if(Number.isFinite(state.now)){clockOffset=state.now-Date.now()/1000;if(!clockReady){view.reset(state.now-(performance.now()-enteredAt)/1000);clockReady=true;}}view.ingest(state.aircraft,viewNow());
  const now=performance.now(),delta=lastCount===null||state.messages<lastCount?0:(state.messages-lastCount)/Math.max(.1,(now-lastTime)/1000);lastCount=state.messages;lastTime=now;
  $('rate').textContent=fmt(delta,1);$('messages').textContent=fmt(state.messages);renderView();
  renderReception();
  const primary=state.bands?.find(b=>b.id==='1090')||state,uat=state.bands?.find(b=>b.id==='978')||{};
  $('band1090-status').textContent=primary.status;$('source-status').textContent=primary.status;
  $('band978-status').textContent=uat.status||'NOT INSTALLED';$('uat-status').textContent=uat.status||'NOT INSTALLED';
  $('uat-detail').textContent=uat.detail||'';$('uat-stats').textContent='UAT aircraft packets · saved '+fmt(uat.messages||0)+' · this run '+fmt(uat.session_messages||0)+' · '+(uat.assigned?USB_Radios.name(uat.assigned):(uat.enabled?'Waiting for assigned receiver':'Receiver stopped'));
  const uatChosen=uatEditing?$('uat-usb').value:uat.selection||'auto';
  USB_Radios.fill($('uat-usb'),state.devices,{leases:state.leases,owner:'uat',selection:uatChosen,blocked:primary.assigned?[primary.assigned.id]:[],auto:'Auto · spare radio'});
  $('uat-start').disabled=!uat.installed;$('uat-start').hidden=!!uat.enabled;$('uat-stop').hidden=!uat.enabled;
  $('connection').textContent='● CONNECTED';$('last-update').textContent='UPDATED '+new Date().toLocaleTimeString();$('detail').textContent=state.detail;
  const chosen=editing?$('usb').value:state.selection;
  USB_Radios.fill($('usb'),state.devices,{leases:state.leases,owner:'adsb',selection:chosen,unique:false});
  $('start').hidden=!!primary.enabled;$('stop').hidden=!primary.enabled;
  $('site-status').textContent=state.receiver_position?`${state.receiver_position.lat.toFixed(5)}°, ${state.receiver_position.lon.toFixed(5)}°`:'Site not configured';
  if(state.receiver_position&&document.activeElement!==$('site-lat')&&document.activeElement!==$('site-lon')&&!$('site-form').dataset.editing){$('site-lat').value=state.receiver_position.lat;$('site-lon').value=state.receiver_position.lon;}
  error('');globe?.update(state);footprintLegend();renderTraffic();if(selected)renderDetails(currentPlane());
  if(!$('logs-panel').hidden)refreshLogs();
}catch(e){error('Receiver connection lost. Retrying…');$('status').textContent='OFFLINE';$('connection').textContent='● DISCONNECTED';if(state){state={...state,status:'OFFLINE',aircraft:[]};renderTraffic();renderReception();}$('positioned').textContent='0';$('tracked').textContent='0';$('traffic-count').textContent='0';$('map-empty').hidden=false;$('map-empty').querySelector('b').textContent='Receiver offline';globe?.update({aircraft:[]});if(selected)renderDetails(null);}finally{refreshBusy=false;}}
async function control(action,extra={}){try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-ADSB-Token':token},body:JSON.stringify({action,selection:extra.band==='978'?$('uat-usb').value:$('usb').value,...extra})});const result=await r.json();if(!r.ok)throw Error(result.error);editing=false;uatEditing=false;await refresh();}catch(e){error(e.message);}}
for(const action of ['assign','start','stop','scan']){$(action).onclick=()=>control(action);$('uat-'+action).onclick=()=>control(action,{band:'978'});}
$('site-form').onsubmit=e=>{e.preventDefault();location.href='/settings#location';};

let drawerParent=null;
function showDrawer(kind,show,returnToParent=true){const node=$(kind+'-panel'),wasVisible=!node.hidden;if(show&&!wasVisible)drawerParent=$('settings-menu').open?'settings':null;node.hidden=!show;$(kind).setAttribute('aria-expanded',String(show));if(kind==='receiver')$('live-receivers').setAttribute('aria-expanded',String(show));if(show){$('settings-menu').open=false;closeViewOptions();const other=kind==='logs'?'receiver':'logs';$(other+'-panel').hidden=true;$(other).setAttribute('aria-expanded','false');if(kind==='logs')refreshLogs();}else if(wasVisible&&returnToParent&&drawerParent==='settings'){$('settings-menu').open=true;drawerParent=null;}}
for(const kind of ['logs','receiver']){$(kind).onclick=()=>showDrawer(kind,$(kind+'-panel').hidden);$('close-'+kind).onclick=()=>showDrawer(kind,false);}
$('live-receivers').onclick=()=>showDrawer('receiver',$('receiver-panel').hidden);
function receiverBand(id){for(const band of ['1090','978']){$('source'+band).hidden=band!==id;$('band'+band).setAttribute('aria-pressed',String(band===id));$('band'+band).classList.toggle('accent',band===id);}}
$('band1090').onclick=()=>receiverBand('1090');$('band978').onclick=()=>receiverBand('978');receiverBand('1090');
for(const [id,source] of [['band1090','source1090'],['band978','source978']])$(id).onclick=()=>$(source).scrollIntoView({block:'start',behavior:'smooth'});
function trafficVisible(show){$('traffic-panel').hidden=!show;$('traffic-toggle').setAttribute('aria-expanded',String(show));$('traffic-toggle').classList.toggle('active',show);if(show)renderTraffic();}
$('traffic-toggle').onclick=()=>{trafficVisible($('traffic-panel').hidden);closeViewOptions();};$('close-traffic').onclick=()=>trafficVisible(false);trafficVisible(false);
$('filter').oninput=$('sort').onchange=renderTraffic;
$('zoom-in').onclick=()=>globe?.zoom(1.6);$('zoom-out').onclick=()=>globe?.zoom(1/1.6);$('center').onclick=()=>globe?.fitTraffic();$('map-style').onchange=e=>globe?.setStyle(e.target.value);
function closeViewOptions(){ $('view-options').open=false;$('trails').value=String(historySeconds); }
$('view-options').addEventListener('toggle',()=>{if(!$('view-options').open)$('trails').value=String(historySeconds);});
$('view-options').addEventListener('toggle',()=>{if($('view-options').open)$('settings-menu').open=false;});
$('settings-menu').addEventListener('toggle',()=>{if($('settings-menu').open)closeViewOptions();});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#view-options,#settings-menu')){closeViewOptions();$('settings-menu').open=false;}});
$('cancel-view-options').onclick=closeViewOptions;
$('apply-history').onclick=()=>{historySeconds=Number($('trails').value);closeViewOptions();if(view.mode==='history')setView('history');else renderView();};
$('labels').onclick=()=>{if(!globe)return;if(view.mode==='history')view.historyLabels=!view.historyLabels;else globe.labels=!globe.labels;globe.render();renderView();};
$('aircraft-icons').onclick=()=>{if(!globe)return;if(view.mode==='history')view.historyIcons=!view.historyIcons;else globe.aircraftIcons=!globe.aircraftIcons;globe.render();renderView();};
$('history-trails').onclick=()=>{view.historyTrails=!view.historyTrails;globe?.render();renderView();};
$('rings').onclick=()=>{if(!globe)return;if(!state?.receiver_position){showDrawer('receiver',true);error('Set the antenna position to enable range rings.');return;}globe.rings=!globe.rings;$('rings').setAttribute('aria-pressed',String(globe.rings));globe.render();};
const aircraftPanel=$('aircraft-overlay'),aircraftHandle=$('drag-aircraft');let panelLocation=null,panelDrag=null;
try{const saved=JSON.parse(localStorage.getItem('adsb-aircraft-panel')||'null');if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y))panelLocation=saved;}catch{}
function moveAircraftPanel(x,y){
  const box=aircraftPanel.getBoundingClientRect(),top=matchMedia('(max-width:720px)').matches?200:145;
  x=Math.max(16,Math.min(x,innerWidth-box.width-16));y=Math.max(top,Math.min(y,Math.max(top,innerHeight-box.height-30)));
  panelLocation={x:x/innerWidth,y:y/innerHeight};Object.assign(aircraftPanel.style,{left:x+'px',top:y+'px',right:'auto',bottom:'auto'});
}
function clampAircraftPanel(){if(panelLocation)moveAircraftPanel(panelLocation.x*innerWidth,panelLocation.y*innerHeight);}
function saveAircraftPanel(){try{localStorage.setItem('adsb-aircraft-panel',JSON.stringify(panelLocation));}catch{}}
aircraftHandle.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();const box=aircraftPanel.getBoundingClientRect();panelDrag={x:e.clientX,y:e.clientY,left:box.left,top:box.top};aircraftHandle.setPointerCapture(e.pointerId);});
aircraftHandle.addEventListener('pointermove',e=>{if(panelDrag)moveAircraftPanel(panelDrag.left+e.clientX-panelDrag.x,panelDrag.top+e.clientY-panelDrag.y);});
aircraftHandle.addEventListener('pointerup',e=>{if(!panelDrag)return;panelDrag=null;saveAircraftPanel();aircraftHandle.releasePointerCapture(e.pointerId);});
aircraftHandle.addEventListener('pointercancel',()=>{panelDrag=null;saveAircraftPanel();});
aircraftHandle.addEventListener('keydown',e=>{const step={ArrowLeft:[-12,0],ArrowRight:[12,0],ArrowUp:[0,-12],ArrowDown:[0,12]}[e.key];if(!step)return;e.preventDefault();const box=aircraftPanel.getBoundingClientRect();moveAircraftPanel(box.left+step[0],box.top+step[1]);saveAircraftPanel();});
$('reset-panels').onclick=()=>{panelLocation=null;aircraftPanel.removeAttribute('style');try{localStorage.removeItem('adsb-aircraft-panel');}catch{}closeViewOptions();};
window.addEventListener('resize',clampAircraftPanel);requestAnimationFrame(clampAircraftPanel);
async function refreshLogs(){if(logBusy)return;logBusy=true;try{const requested=logKind,r=await fetch('/api/logs?kind='+requested);if(!r.ok)throw Error('Could not load log');const data=await r.json();if(requested!==logKind)return;const node=$('logs-content'),scroll=node.scrollTop;node.replaceChildren();
  if(!data.entries.length){const p=document.createElement('p');p.textContent=requested==='flights'?'No decoded aircraft observations yet. Receiver and Diagnostics show radio activity.':'No entries in this log yet.';node.append(p);}
  else if(requested==='flights'){const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');for(const text of ['TIME','CALLSIGN','ICAO','ALTITUDE','SPEED','POSITION','BAND']){const th=document.createElement('th');th.textContent=text;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');for(const item of [...data.entries].reverse()){const p=item.aircraft||{},row=document.createElement('tr');const values=[new Date(item.time*1000).toLocaleString(),(p.flight||'—').trim(),p.hex?.toUpperCase()||'—',fmt(p.alt_baro)+' ft',fmt(p.gs)+' kt',Number.isFinite(p.lat)&&Number.isFinite(p.lon)?p.lat.toFixed(4)+', '+p.lon.toFixed(4):'No position',p.band||'1090 ES'];for(const text of values){const td=document.createElement('td');td.textContent=text;row.append(td);}body.append(row);}table.append(body);node.append(table);}
  else{const pre=document.createElement('pre');if(requested.endsWith('diagnostics'))pre.textContent=data.lines.join('\n');else pre.textContent=[...data.entries].reverse().map(item=>new Date(item.time*1000).toLocaleString()+'  '+String(item.event||'event').toUpperCase()+'\n'+(item.detail||item.device?.label||item.selection||'')).join('\n\n');node.append(pre);}node.scrollTop=scroll;
}catch(e){$('logs-content').textContent=e.message;}finally{logBusy=false;}}
for(const button of document.querySelectorAll('[data-log]'))button.onclick=()=>{logKind=button.dataset.log;document.querySelector('.log-note').textContent=logKind==='diagnostics'?'Receiver output · UTC timestamps · live updates':'Latest 160 entries · live updates · local time';for(const tab of document.querySelectorAll('[data-log]'))tab.setAttribute('aria-selected',String(tab===button));$('download').href='/api/log?kind='+logKind;$('download').download='adsb-'+logKind+(logKind==='diagnostics'?'.txt':'.jsonl');$('logs-content').scrollTop=0;refreshLogs();};
async function tracks(){try{const r=await fetch('/api/tracks');if(r.ok&&globe){globe.setTracks(await r.json());renderTraffic();}}catch{}}
function clock(){$('utc').textContent=new Date().toISOString().slice(11,19)+' UTC';renderReception();if(state){renderView();renderTraffic();if(selected)renderDetails(currentPlane());globe?.render();}}clock();setInterval(clock,1000);refresh();setInterval(refresh,2500);tracks();setInterval(tracks,5000);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if($('view-options').open){closeViewOptions();return;}if($('settings-menu').open){$('settings-menu').open=false;return;}if(!$('logs-panel').hidden){showDrawer('logs',false);return;}if(!$('receiver-panel').hidden){showDrawer('receiver',false);return;}if(!$('traffic-panel').hidden){trafficVisible(false);return;}if(!$('coverage-panel').hidden)coverageVisible(false);return;}if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='+')globe?.zoom(1.6);else if(e.key==='-')globe?.zoom(1/1.6);else if(e.key.toLowerCase()==='f'&&selected)globe?.followSelected(!globe.following);else if(e.key.toLowerCase()==='l')showDrawer('logs',$('logs-panel').hidden);});

const observatoryLink=document.getElementById('observatory-link');if(observatoryLink)observatoryLink.href=`http://${location.hostname}:8092/`;

let footprintBusy=false;
function footprintLegend(){if(globe){for(const button of document.querySelectorAll('[data-layer-rx]'))button.setAttribute('aria-pressed',String(globe.footprintEnabled));$('rx-footprint').textContent='RX '+(globe.footprintEnabled?'on':'off');$('footprint-legend').hidden=!globe.footprintRegions().length;$('footprint-legend').title='Accumulated maximum range at this antenna site';}}
async function refreshFootprint(){
  if(footprintBusy||!globe||!globe.footprintEnabled)return;footprintBusy=true;
  try{const r=await fetch('/api/footprint?scope=maximum',{signal:AbortSignal.timeout(10000)});if(r.ok){const data=await r.json();if(data.status==='LOADING')setTimeout(refreshFootprint,1200);else{globe.setFootprint(data.footprint);footprintLegend();}}}catch{}finally{footprintBusy=false;}
}
function toggleFootprint(){if(!globe)return;globe.footprintEnabled=!globe.footprintEnabled;globe.save();footprintLegend();globe.render();if(globe.footprintEnabled)refreshFootprint();}
for(const button of document.querySelectorAll('[data-layer-rx]'))button.onclick=toggleFootprint;
footprintLegend();refreshFootprint();setInterval(refreshFootprint,10000);
const domeWindow=new CoverageWindow(),domeTimespan=$('dome-timespan');
const reloadCoverage=mountCoverage($('coverage-panel'),()=>domeWindow.since(viewNow()),undefined,()=>view.live(state?.aircraft||[],viewNow()));
function renderDomeWindow(){
  document.querySelector('[data-dome-window-label]').textContent=(domeWindow.seconds?'LAST '+domeWindow.label.toUpperCase():'ALL RECORDED')+(domeWindow.startedAt!==null?' · SINCE RESET':'')+' · LIVE UPDATES';
  domeTimespan.textContent='Time · '+domeWindow.label;
  for(const button of $('dome-time-options').querySelectorAll('button'))button.setAttribute('aria-pressed',String(Number(button.dataset.seconds)===domeWindow.seconds));
}
$('dome-time-options').replaceChildren(...COVERAGE_WINDOWS.map(([value,label])=>{
  const button=document.createElement('button');button.type='button';button.textContent=label;button.setAttribute('aria-label',label);button.dataset.seconds=String(value);
  button.title=value?'Rolling reception history; does not restart at each interval.':'All retained reception history.';
  button.onclick=()=>{domeWindow.select(value,viewNow());$('dome-time-menu').open=false;renderDomeWindow();reloadCoverage();};return button;
}));
$('dome-reset').onclick=()=>{domeWindow.reset(viewNow());$('dome-time-menu').open=false;renderDomeWindow();reloadCoverage(true);};
$('dome-time-menu').addEventListener('keydown',event=>{if(event.key==='Escape'){$('dome-time-menu').open=false;domeTimespan.focus();}});
renderDomeWindow();
function coverageVisible(show){document.body.classList.toggle('coverage-open',show);$('coverage-panel').hidden=!show;$('coverage').setAttribute('aria-expanded',String(show));if(show){history.replaceState(null,'',location.pathname+'#coverage');showDrawer('logs',false,false);showDrawer('receiver',false,false);closeViewOptions();$('settings-menu').open=false;reloadCoverage();}if(location.hash==='#coverage'&&!show)history.replaceState(null,'',location.pathname);}
$('coverage').onclick=()=>coverageVisible($('coverage-panel').hidden);$('close-coverage').onclick=()=>coverageVisible(false);
$('traffic-toggle').addEventListener('click',()=>coverageVisible(false));
if(location.hash==='#coverage')coverageVisible(true);
