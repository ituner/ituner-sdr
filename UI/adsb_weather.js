import {ADSBGlobe} from './adsb_globe.js';
export const RADAR_COLOURS=[null,'#28b774','#8acb45','#efdb45','#ed982e','#eb5049','#d754d8','#9129b9'];
export function radarRectangles(blocks,now){
  const result=[];
  for(const b of [...blocks].sort((a,b)=>b.scale-a.scale)){
    if(b.expires_at<=now||b.bins?.length!==128)continue;
    const [w,s,e,n]=b.bounds,dx=(e-w)/32,dy=(n-s)/4;
    for(let y=0;y<4;y++)for(let x=0;x<32;){
      const level=b.bins[y*32+x],start=x;while(x<32&&b.bins[y*32+x]===level)x++;
      if(level>=0&&level<8)result.push({bounds:[w+start*dx,n-(y+1)*dy,w+x*dx,n-y*dy],level});
    }
  }return result;
}
export function weatherStatus(data,now){
  if(data.status==='PAUSED FOR COMPARISON')return ['Paused for receiver comparison','The NESDR is testing 1090 MHz. Stop the comparison to restore 978 MHz weather reception.'];
  if(data.status==='STOPPED')return ['UAT stopped','Start the 978 UAT receiver under Receivers on the live map.'];
  if(data.status==='NOT INSTALLED')return ['Weather engine unavailable','The local FIS-B decoder is not installed.'];
  if(data.status==='RECEIVER UNAVAILABLE')return ['UAT receiver unavailable','Reconnect the assigned UAT dongle. Saved products retain their original expiry times.'];
  if(data.status==='CONNECTING')return ['Connecting to UAT','The weather decoder is connecting to the local 978 MHz stream.'];
  if(data.status==='DECODER ERROR')return ['Weather decoder restarting',data.last_error||'Aircraft reception continues while the weather worker recovers.'];
  if(data.last_uplink_at&&now-data.last_uplink_at<30)return ['Ground uplink received','FAA weather products appear below as their complete messages arrive.'];
  return ['Listening for ground stations',data.last_uplink_at?'No recent FAA uplink. Only unexpired saved products are shown.':'Aircraft packets are separate from weather. No FAA weather uplink has been received yet. Ground-station line of sight is required.'];
}
export function age(value,now){if(!Number.isFinite(value))return 'Never';const s=Math.max(0,Math.floor(now-value));return s<60?s+'s ago':s<3600?Math.floor(s/60)+'m ago':Math.floor(s/3600)+'h ago';}
function mount(){
  const $=id=>document.getElementById(id);let data=null,tab='reports',busy=false,offset=0,rectangles=[];
  const globe=new ADSBGlobe($('weather-globe'),()=>{},message=>$('weather-error').textContent=message,'ituner-uat-weather');
  globe.footprintEnabled=false;const now=()=>Date.now()/1000+offset;
  globe.drawWeather=()=>{
    const ctx=globe.ctx;ctx.save();
    for(const r of rectangles){const [w,s,e,n]=r.bounds,p=[[w,s],[e,s],[e,n],[w,n]].map(([lon,lat])=>globe.project({lon,lat}));if(p.some(v=>!v))continue;
      if(p.every(v=>v[0]<0)||p.every(v=>v[0]>globe.width)||p.every(v=>v[1]<0)||p.every(v=>v[1]>globe.height))continue;
      ctx.fillStyle=r.level===0?'rgba(90,165,210,.055)':RADAR_COLOURS[r.level];ctx.globalAlpha=r.level===0?1:.72;ctx.beginPath();p.forEach((v,i)=>i?ctx.lineTo(...v):ctx.moveTo(...v));ctx.closePath();ctx.fill();
    }
    ctx.restore();
    for(const s of data?.stations||[]){if(!Number.isFinite(s.lat)||!Number.isFinite(s.lon))continue;const p=globe.project(s);if(!p)continue;ctx.fillStyle=s.live?'#9bf2d2':'#8198a9';ctx.font='14px system-ui';ctx.beginPath();ctx.arc(...p,5,0,Math.PI*2);ctx.fill();ctx.fillText('FAA uplink',p[0]+10,p[1]-8);}
  };
  function empty(node,title,text){const p=document.createElement('div');p.className='weather-empty';const h=document.createElement('strong');h.textContent=title;p.append(h,document.createTextNode(text));node.append(p);}
  function card(node,title,text,detail,stamp){const a=document.createElement('article');a.className='weather-report';const h=document.createElement('h3'),small=document.createElement('small'),p=document.createElement('p');h.textContent=title;small.textContent=age(stamp,now());h.append(small);a.append(h);if(text){const pre=document.createElement('pre');pre.textContent=text;a.append(pre);}p.textContent=detail;a.append(p);node.append(a);}
  function render(){if(!data)return;const clock=now(),[title,detail]=weatherStatus(data,clock);$('weather-status').textContent=title;$('weather-detail').textContent=detail;
    $('uplinks').textContent=data.uplinks.toLocaleString();$('reports-count').textContent=data.reports.length;$('radar-count').textContent=data.radar.length;$('last-uplink').textContent=age(data.last_uplink_at,clock);
    $('weather-connection').textContent=data.connected?'● UAT STREAM CONNECTED':data.status;
    const list=$('report-list');list.replaceChildren();const filter=$('report-filter').value.trim().toUpperCase();
    const rows=data.reports.filter(r=>(r.type+' '+r.name+' '+r.text).toUpperCase().includes(filter));
    for(const r of rows){const issued=r.issued_at?'Issued '+new Date(r.issued_at*1000).toISOString().slice(11,16)+' UTC':'Issue time unavailable';card(list,r.type+' · '+r.name,r.text,issued+' · received '+age(r.received_at,clock)+' · expires '+new Date(r.expires_at*1000).toISOString().slice(11,16)+' UTC',r.issued_at||r.received_at);}
    if(!rows.length)empty(list,filter?'No matching reports':'Waiting for weather reports',filter?'Try another airport identifier or report type.':'METARs, TAFs and text advisories will appear here when received over the radio. No Internet reports are mixed into this view.');
    const stations=$('station-list');stations.replaceChildren();for(const s of data.stations){card(stations,s.live?'Receiving ground station':'Previously received station',null,`${s.id} · ${s.packets.toLocaleString()} uplinks${Number.isFinite(s.rssi)?' · '+s.rssi.toFixed(1)+' dBFS':''}${s.position_valid?'':' · advertised position (validity flag unset)'}`,s.last_heard);}
    if(!data.stations.length)empty(stations,'No ground station received yet','Receiving aircraft does not guarantee reception of a ground transmitter. This view will record each station automatically when an uplink arrives.');
    const latest=Math.max(0,...data.radar.map(b=>b.time||0));$('radar-age').textContent=data.radar.length?`${data.radar.length} received blocks · newest observation ${age(latest||null,clock)}. Gaps are unknown.`:'No radar blocks received. An empty map does not mean clear weather.';
  }
  function setTab(value){tab=value;document.body.dataset.weatherTab=tab;for(const b of document.querySelectorAll('[data-tab]'))b.setAttribute('aria-pressed',String(b.dataset.tab===tab));$('reports-panel').hidden=tab!=='reports';$('stations-panel').hidden=tab!=='stations';$('radar-note').hidden=tab!=='radar';}
  for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>setTab(b.dataset.tab);
  $('report-filter').oninput=render;$('wx-minus').onclick=()=>globe.zoom(1/1.6);$('wx-plus').onclick=()=>globe.zoom(1.6);$('wx-center').onclick=()=>{if(data?.receiver_position){globe.locate(data.receiver_position);globe.scale=8;globe.save();globe.render();globe.requestTiles();}};
  async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/weather',{signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error('Weather service unavailable');data=await r.json();offset=data.now-Date.now()/1000;rectangles=radarRectangles(data.radar,now());if(!globe.centered&&data.receiver_position){globe.locate(data.receiver_position);globe.scale=8;globe.save();}render();globe.render();$('weather-error').textContent=data.errors?'Some FIS-B products could not be decoded ('+data.errors+'). Valid products remain available.':'';}catch(e){$('weather-connection').textContent='OFFLINE';$('weather-error').textContent=e.message;}finally{busy=false;}}
  document.addEventListener('keydown',e=>{if(e.key==='Escape')location.href='/';});setTab('reports');refresh();setInterval(refresh,10000);setInterval(()=>{
    $('weather-clock').textContent=new Date().toISOString().slice(11,19)+' UTC';
    if(data&&(data.reports.some(r=>r.expires_at<=now())||data.radar.some(b=>b.expires_at<=now()))){data.reports=data.reports.filter(r=>r.expires_at>now());data.radar=data.radar.filter(b=>b.expires_at>now());rectangles=radarRectangles(data.radar,now());render();globe.render();}
  },1000);
}
if(typeof document!=='undefined')mount();
